"""Mapa de decisão de um programa: parágrafos -> sequência de caixas de execução (E) e decisões (D), em texto legível.

Tudo sai da AST (tokens). Nada aqui depende de nomes do código analisado.
  * cada trecho de comandos sem decisão vira UMA caixa de execução (código Enn), com todos os comandos, sem cortar;
  * cada IF vira uma decisão (Dnn); EVALUATE vira uma cadeia IF / ELSIF (uma decisão por WHEN, WHEN OTHER vira o ELSE);
  * PERFORM em linha (laço) vira uma decisão de laço; PERFORM de parágrafo aparece como comando da caixa;
  * a chave de cobertura de cada decisão é (decision_id, rótulo do ramo) da árvore de decisão: TRUE/FALSE no IF e WHEN_n no EVALUATE.
Os códigos (E001, D001...) numeram na ordem do fonte, dentro do programa; são estáveis para o mesmo fonte."""
from __future__ import annotations
from decision_tree import _id
from token_utils import V, sql_tables
from readable_code import Namer, condition_text, evaluate_group_text, statement_lines, perform_text, _generic, _v


SEPARATE = {'EXEC_SQL': 'sql', 'PERFORM': 'perform', 'CALL': 'call', 'EXEC_CICS': 'cics'}


def _target(node):
    toks = node.get('header_tokens') or []
    return toks[0][1].upper() if toks and toks[0][0] in ('IDENT', 'NUMBER', 'KEYWORD') and not node.get('inline') else None


def _ends(n, term):
    t = n['type']
    if t in ('GOBACK', 'STOP'):
        return True
    if t == 'EXEC_CICS' and (n.get('command') or '').split()[:1] == ['RETURN']:
        return True
    if t == 'PERFORM' and not n.get('inline'):
        return _target(n) in term
    if t == 'IF':
        return _seq_ends(n['then'], term) and _seq_ends(n['else_body'], term)
    if t == 'EVALUATE':
        ws = n.get('whens') or []
        return bool(ws) and any(len(w.get('condition_tokens') or []) == 1 and _v(w['condition_tokens'][0]) == 'OTHER' for w in ws) \
            and all(_seq_ends(w['body'], term) or not w['body'] for w in ws)
    return False


def _seq_ends(nodes, term):
    return any(_ends(n, term) for n in nodes)


def _paragraphs(ast):
    """[(nome, linha, [nós])] na ordem do fonte; o que vem antes do primeiro rótulo fica em '(início)'."""
    out, cur = [], None
    for n in ast.get('body', []):
        if n['type'] == 'LABEL':
            cur = [str(n.get('name') or '').upper(), n['start_line'], []]
            out.append(cur)
        else:
            if cur is None:
                cur = ['(início)', n['start_line'], []]
                out.append(cur)
            cur[2].append(n)
    return out


def group_names(prog):
    """(grupos declarados, prefixos de estrutura) de um programa do modelo estático.
    Prefixo de estrutura: nome de grupo/registro; nome de cada membro COPY (expandido ou ausente); e o primeiro trecho (até o
    hífen) dos grupos vindos de copybook, se esse trecho não aparece em nenhum item declarado no próprio programa."""
    items = prog['data_model']['items']
    kids = {}
    for i in items:
        kids.setdefault((i.get('parent') or '').upper(), []).append(i)
    groups = {i['name'].upper() for i in items if i['level'] == 1 or kids.get(i['name'].upper())}
    lm = prog['linemap']
    local, book = set(), {}
    for i in items:
        if i['level'] == 88 or '-' not in i['name']:
            continue
        first = i['name'].upper().split('-')[0]
        o = lm.to_source(i['start_line'])
        if o.get('file') and not o.get('in_program'):
            if kids.get(i['name'].upper()):
                book[first] = book.get(first, 0) + 1
        else:
            local.add(first)
    prefixes = {t for t in book if t not in local}
    cb = prog['copybooks']
    prefixes |= {m['member'].upper() for m in cb['expanded']} | {m['member'].upper() for m in cb['missing']}
    return groups, prefixes


def build(program, ast, groups=(), source_line=lambda n: n, prefixes=(), cursors=None):
    namer = Namer(groups, prefixes)
    cursors = cursors or {}
    pars = _paragraphs(ast)
    term = set()
    changed = True
    while changed:
        changed = False
        for name, _l, nodes in pars:
            if name not in term and _seq_ends(nodes, term):
                term.add(name)
                changed = True

    def sql_tables_of(n):
        """Tabelas do comando; OPEN/FETCH/CLOSE de cursor usam as tabelas do SELECT do DECLARE. Devolve (tabelas, cursor|None)."""
        toks = list(n.get('tokens') or [])
        own = [x.upper() for x in sql_tables(toks)]
        if toks and V(toks[0]) in ('OPEN', 'FETCH', 'CLOSE'):
            cn = next((V(t) for t in toks[1:] if V(t) in cursors), None)
            if cn:
                return list(cursors[cn]['tables']), cn
        return own, None

    def is_other(w):
        c = w.get('condition_tokens') or []
        return len(c) == 1 and _v(c[0]) == 'OTHER'

    def seq(nodes):
        out, box = [], None

        def flush():
            nonlocal box
            if box:
                out.append(box)
                box = None
        for n in nodes:
            t = n['type']
            if t == 'IF':
                flush()
                out.append({'kind': 'decision', 'construct': 'IF', 'decision_id': _id(program, n), 'line': n['start_line'],
                            'cond': condition_text(n.get('condition_tokens') or [], namer),
                            'true_keys': ['TRUE'], 'false_keys': ['FALSE'],
                            'then': seq(n['then']), 'else': seq(n['else_body'])})
            elif t == 'EVALUATE':
                flush()
                out.append(evaluate(n))
            elif t == 'PERFORM' and n.get('inline'):
                flush()
                head = perform_text(n, namer)
                out.append({'kind': 'decision', 'construct': 'LOOP', 'decision_id': None, 'line': n['start_line'],
                            'cond': 'PERFORM ' + head if head else 'PERFORM (laço)', 'true_keys': [], 'false_keys': [],
                            'then': seq(n['body']), 'else': []})
            else:
                lines = statement_lines(n, namer)
                sub = SEPARATE.get(t)
                if sub:  # SQL, chamada de parágrafo/programa e CICS ficam cada um na sua caixa
                    flush()
                    box = {'kind': 'box', 'line': n['start_line'], 'end_line': n['end_line'], 'lines': lines, 'ends': False, 'stmt_lines': [],
                           'effects': [], 'performs': [], 'sub': sub, 'tables': [], 'sql_op': ''}
                elif box is None:
                    box = {'kind': 'box', 'line': n['start_line'], 'end_line': n['end_line'], 'lines': [], 'ends': False, 'stmt_lines': [], 'effects': [], 'performs': [], 'sub': 'dados', 'tables': [], 'sql_op': ''}
                if not sub:
                    box['lines'].extend(lines)
                box['end_line'] = n['end_line']
                if t != 'PERFORM':
                    box['stmt_lines'].append(n['start_line'])
                else:
                    box['performs'].append(_target(n))
                tk = (n.get('tokens') or [None])[0]
                first = (tk[1] if tk else None) if t == 'EXEC_SQL' else ((n.get('command') or '').split() or [None])[0] if t == 'EXEC_CICS' else None
                box['effects'].append([t, str(first).upper() if first else ''])
                if t == 'EXEC_SQL':
                    box['sql_op'] = str(first).upper() if first else ''
                    box['tables'], via = sql_tables_of(n)
                    if via:
                        box['lines'] = box['lines'] + ['↳ tabela ' + ', '.join(box['tables']) + f' (cursor {via})'] if box['tables'] else box['lines']
                    elif box['tables']:
                        box['lines'] = box['lines'] + ['↳ tabela ' + ', '.join(box['tables'])]
                if _ends(n, term):
                    box['ends'] = True
                if sub:
                    flush()
        flush()
        return out

    def evaluate(n):
        ws = n.get('whens') or []
        subj = n.get('subject_tokens') or []
        # WHENs empilhados sem corpo se juntam ao próximo WHEN com corpo (OR das condições)
        groups, pend = [], []
        for i, w in enumerate(ws):
            pend.append((i, w))
            if w.get('body') or i == len(ws) - 1:
                groups.append(pend)
                pend = []
        other = next((g for g in groups if any(is_other(w) for _i, w in g)), None)
        chain = [g for g in groups if g is not other]
        keys = lambda g: [f'WHEN_{i + 1}' for i, _w in g]
        multi = any(_v(t) == 'ALSO' for t in subj) or any(_v(t) == 'ALSO' for w in ws for t in (w.get('condition_tokens') or []))

        def ctext(g):
            cs = [w.get('condition_tokens') or [] for _i, w in g if not is_other(w)]
            if multi:
                return ' OR '.join('EVALUATE ' + _generic(subj, namer) + ' WHEN ' + _generic(c, namer) for c in cs)
            return evaluate_group_text(subj, cs, namer)
        tail = seq(other[-1][1]['body']) if other else []
        later_keys = keys(other) if other else ['NO_MATCH']
        item = None
        for pos in range(len(chain) - 1, -1, -1):
            g = chain[pos]
            fk = [k for gg in chain[pos + 1:] for k in keys(gg)] + later_keys
            item = {'kind': 'decision', 'construct': 'EVALUATE' if pos == 0 else 'ELSIF', 'decision_id': _id(program, n), 'line': g[0][1]['start_line'] if pos else n['start_line'],
                    'cond': ctext(g), 'true_keys': keys(g), 'false_keys': fk,
                    'then': seq(g[-1][1]['body']), 'else': [item] if item else tail}
        if item is None:  # só WHEN OTHER
            return {'kind': 'box', 'line': n['start_line'], 'end_line': n['end_line'], 'lines': ['(EVALUATE só com WHEN OTHER)'], 'ends': False, 'stmt_lines': [], 'effects': [], 'performs': [], 'sub': 'dados', 'tables': [], 'sql_op': ''}
        return item

    paragraphs = []
    for name, line, nodes in pars:
        paragraphs.append({'name': name, 'line': line, 'source_line': source_line(line), 'terminates': name in term, 'items': seq(nodes)})
    # códigos na ordem do fonte
    cnt = {'E': 0, 'D': 0}
    rows = []

    def code(it, par):
        if it['kind'] == 'box':
            cnt['E'] += 1
            it['code'] = f'E{cnt["E"]:03d}'
            rows.append({'code': it['code'], 'kind': 'execução', 'paragraph': par, 'line': it['line'], 'source_line': source_line(it['line']), 'text': it['lines'],
                         'decision_id': None, 'true_keys': [], 'false_keys': [], 'construct': None, 'performs': it['performs'],
                         'sub': it.get('sub', 'dados'), 'tables': it.get('tables', []), 'sql_op': it.get('sql_op', '')})
            it['source_line'] = source_line(it['line'])
            return
        cnt['D'] += 1
        it['code'] = f'D{cnt["D"]:03d}'
        it['source_line'] = source_line(it['line'])
        row = {'code': it['code'], 'kind': 'decisão', 'paragraph': par, 'line': it['line'], 'source_line': it['source_line'], 'text': [it['cond']],
               'decision_id': it['decision_id'], 'true_keys': it['true_keys'], 'false_keys': it['false_keys'], 'construct': it['construct']}
        rows.append(row)
        for b in ('then', 'else'):
            for c in it[b]:
                code(c, par)
            row[b + '_first'] = None
        row['_it'] = it
    for p in paragraphs:
        for it in p['items']:
            code(it, p['name'])
    for r in rows:  # primeiro código de cada ramo (para a tabela)
        it = r.pop('_it', None)
        if it:
            r['then_first'] = it['then'][0]['code'] if it['then'] else ''
            r['else_first'] = it['else'][0]['code'] if it['else'] else ''
    return {'program': program, 'paragraphs': paragraphs, 'rows': rows,
            'summary': {'paragraphs': len(paragraphs), 'decisions': cnt['D'], 'boxes': cnt['E']}}
