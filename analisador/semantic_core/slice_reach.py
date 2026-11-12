"""Fatia alcançável de um programa chamado, dado o que o chamador fixa antes da chamada.

Tudo sai da AST e dos tokens: o grafo de PERFORM/parágrafos, as condições dos IF e as atribuições literais do
chamador (MOVE 'S' TO campo) antes do LINK/CALL. Um IF cuja condição só depende de campos "constantes"
(fixados pelo chamador ou mantidos no valor inicial e nunca alterados pelo programa) tem um único ramo
alcançável; qualquer outra condição mantém os dois. Resultado: {(decision_id, resultado)} alcançáveis.
Não executa nada; as condições já vêm extraídas da AST e são avaliadas pelo mesmo avaliador do runtime."""
import re
from cobol_condition_runtime import evaluate, _split, _strip_outer, _norm
from token_utils import perform_spec, V

FIG = {'ZERO', 'ZEROS', 'ZEROES', 'SPACE', 'SPACES', 'LOW-VALUE', 'LOW-VALUES', 'HIGH-VALUE', 'HIGH-VALUES'}
NAME = re.compile(r'^[A-Z][A-Z0-9-]*$')


def _first(name):
    return name.replace('(', ' ').split()[0].upper() if name.strip() else ''


def _kids(items):
    ch = {}
    for it in items:
        if it.get('parent'):
            ch.setdefault(it['parent'].upper(), []).append(it['name'].upper())
    return ch


def _descendants(ch, n, acc=None):
    acc = set() if acc is None else acc
    for k in ch.get(n, []):
        if k not in acc:
            acc.add(k)
            _descendants(ch, k, acc)
    return acc


def _walk_nodes(b):
    for n in b:
        yield n
        for k in ('then', 'else_body', 'body'):
            if isinstance(n.get(k), list):
                yield from _walk_nodes(n[k])
        for w in n.get('whens', []) or []:
            yield from _walk_nodes(w['body'])


def _unqualified(words):
    """Nomes de dado de uma lista de palavras, sem os qualificadores ('A OF B' dá A)."""
    out = []
    for i, v in enumerate(words):
        if NAME.match(v) and v not in FIG | {'TRUE', 'FALSE', 'OF', 'IN'} and not (i and words[i - 1] in ('OF', 'IN')):
            out.append(_first(v))
    return out


def _receivers(n):
    """Nomes que o nó pode alterar (conservador)."""
    t = n['type']
    words = [V(x) for x in n.get('arg_tokens') or n.get('tokens') or []]
    if t == 'MOVE':
        i = words.index('TO') if 'TO' in words else len(words)
        if words[:1] == ['DFHCOMMAREA']:
            return set()  # imagem da COMMAREA do chamador: traz os valores dele, não é atribuição do programa
        return set(_unqualified(words[i + 1:]))
    if t == 'SET':
        i = words.index('TO') if 'TO' in words else len(words)
        return set(_unqualified(words[:i]))
    if t == 'INITIALIZE':
        return set(_unqualified([w for w in words if w not in ('REPLACING', 'WITH', 'TO', 'BY', 'DATA', 'ALL')]))
    if t in ('EXEC_SQL', 'EXEC_CICS', 'COMPUTE', 'ADD', 'STRING', 'SUBTRACT', 'MULTIPLY', 'DIVIDE', 'ACCEPT', 'READ', 'UNSTRING', 'INSPECT'):
        return set(_unqualified(words))
    return set()


def caller_constants(caller, call_line):
    """MOVE literal TO campo incondicionais do parágrafo do chamador, antes da linha da chamada."""
    body = caller['ast']['body']
    idx = next((i for i, n in enumerate(body) if n['start_line'] > call_line), len(body))
    start = 0
    for i in range(min(idx, len(body)) - 1, -1, -1):
        if body[i]['type'] == 'LABEL':
            start = i
            break
    consts = {}
    for n in body[start:idx]:
        if n['type'] != 'MOVE':
            continue
        toks = list(n.get('arg_tokens') or [])
        words = [V(x) for x in toks]
        if 'TO' not in words:
            continue
        i = words.index('TO')
        if i != 1:
            continue
        kind = toks[0][0]
        if kind == 'STRING':
            v = toks[0][1].strip("'\"")
        elif re.fullmatch(r'\d+', words[0]):
            v = int(words[0])
        elif words[0] in ('ZERO', 'ZEROS', 'ZEROES'):
            v = 0
        elif words[0] in ('SPACE', 'SPACES'):
            v = ' '
        else:
            continue
        for w in words[i + 1:]:
            if NAME.match(w) and w not in ('OF', 'IN'):
                consts[w] = v
                break
    return consts


def _env(callee, consts, via_commarea, caller_assigned=frozenset(), inherit=None):
    """Valores fixos: constantes do chamador + valor inicial dos demais campos do mesmo grupo 01, salvo os que o
    programa chamado altera (ou cujos grupos ele altera)."""
    items = callee['data_model']['items']
    by = {}
    for it in items:
        by.setdefault(it['name'].upper(), it)
    ch = _kids(items)
    assigned = set()
    for n in _walk_nodes(callee['ast']['body']):
        for r in _receivers(n):
            assigned.add(r)
            assigned |= _descendants(ch, r)

    def top(n):
        seen = set()
        while by.get(n) and by[n].get('parent') and n not in seen:
            seen.add(n)
            n = by[n]['parent'].upper()
        return n

    env = {}
    for g in {top(k) for k in consts if k in by}:
        for k in _descendants(ch, g):
            it = by.get(k)
            if not it or it.get('level') == 88 or k in assigned or k in caller_assigned or k in ch or k == 'FILLER':
                continue
            cat = (it.get('picture') or {}).get('category', '')
            env[k] = 0 if cat.startswith('NUMERIC') else (it.get('value') if it.get('value') not in (None, '') else ' ')
    for k, v in (inherit or {}).items():  # valor inicial dos campos da COMMAREA que o chamador nunca altera com dados
        if k in by and k not in assigned and k not in caller_assigned and k not in ch:
            env.setdefault(k, v)
    for k, v in consts.items():
        if k in by and k not in assigned:
            env[k] = v
    if via_commarea:
        env.setdefault('EIBCALEN', 1)
    return env


def _tri(text, env, c88):
    """Avaliação de três valores: True, False ou None (depende de dado desconhecido)."""
    s = _strip_outer(_norm(text))
    if re.match(r'^NOT\s+', s, re.I):
        v = _tri(re.sub(r'^NOT\s+', '', s, count=1, flags=re.I), env, c88)
        return None if v is None else not v
    for word in ('OR', 'AND'):
        ps = _split(s, word)
        if len(ps) > 1:
            m = re.match(r'(.+?)\s*(>=|<=|!=|<>|=|>|<)\s*(.+)$', ps[0])
            if m:
                lhs, op = m.group(1).strip(), m.group(2)
                ps = [ps[0]] + [(f'{lhs} {op} {p}' if not re.search(r'(>=|<=|!=|<>|=|>|<|\bNUMERIC\b)', p, re.I) else p) for p in ps[1:]]
            vs = [_tri(p, env, c88) for p in ps]
            if word == 'OR':
                return True if any(v is True for v in vs) else (None if any(v is None for v in vs) else False)
            return False if any(v is False for v in vs) else (None if any(v is None for v in vs) else True)
    touched = []

    def res(name):
        k = _first(name)
        if '(' in name or k not in env:
            touched.append(k)
            return 0
        return env[k]

    def cond88(name):
        c = c88.get(_first(name))
        if c is None:
            return None
        p = _first(c['parent'])
        if p not in env:
            touched.append(p)
            return False
        return env[p] == c['value']
    r = evaluate(s, res, cond88)
    return None if touched else r


def reach(prog, consts=None, via_commarea=False, caller_assigned=frozenset(), inherit=None):
    """{'branches': {(decision_id, resultado)}, 'calls': {linhas}, 'paragraphs': (alcançados, total)}"""
    body = prog['ast']['body']
    labels = {n['name'].upper(): i for i, n in enumerate(body) if n['type'] == 'LABEL'}
    dec = {(d['line'], d['type']): d for d in prog['decision_tree']['decisions']}
    c88 = {k.upper(): v for k, v in prog['data_model']['conditions_88'].items()}
    env = _env(prog, consts, via_commarea, caller_assigned, inherit) if (consts or inherit) else ({'EIBCALEN': 1} if via_commarea else {})
    out = {'branches': set(), 'calls': set()}
    done, done_par = {}, set()

    def mark(line, typ, results):
        d = dec.get((line, typ))
        if d:
            for b in d['branches']:
                if b['result'] in results:
                    out['branches'].add((d['decision_id'], b['result']))

    def block(b):
        """True se o bloco encerra o fluxo (EXEC CICS RETURN) incondicionalmente."""
        for n in b:
            t = n['type']
            if t == 'IF':
                v = _tri(n['condition'], env, c88)
                mark(n['start_line'], 'IF', {'TRUE'} if v is True else {'FALSE'} if v is False else {'TRUE', 'FALSE'})
                a = block(n['then']) if v is not False else None
                b = block(n['else_body']) if v is not True else None
                if (a if v is True else b if v is False else (a and b)):
                    return True
            elif t == 'EVALUATE':
                for wi, w in enumerate(n['whens'], 1):
                    mark(n['start_line'], 'EVALUATE', {f'WHEN_{wi}'})
                    block(w['body'])
            elif t == 'PERFORM':
                if n.get('inline'):
                    block(n['body'])
                else:
                    sp = perform_spec(n.get('header_tokens') or [], False)
                    if sp['target'] and sp['target'].upper() in labels:
                        if run_paragraphs(sp['target'].upper(), (sp['end'] or sp['target']).upper()):
                            return True  # o parágrafo executado encerra o programa (RETURN)
            elif t in ('EXEC_CICS', 'CALL', 'EXEC_SQL'):
                out['calls'].add(n['start_line'])
                if t == 'EXEC_CICS' and (n.get('command') or '').split()[:1] == ['RETURN']:
                    return True
        return False

    def run_paragraphs(target, end):
        if (target, end) in done:
            return done[(target, end)]
        done[(target, end)] = False
        start = labels[target]
        endidx = labels.get(end, start)
        done_par.add(target)
        j = start + 1
        while j < len(body):
            if j > endidx and body[j]['type'] == 'LABEL':
                break
            if body[j]['type'] == 'LABEL':
                done_par.add(body[j]['name'].upper())
            if block([body[j]]):
                done[(target, end)] = True
                return True
            j += 1
        return False

    for n in body:
        if n['type'] == 'LABEL':
            done_par.add(n['name'].upper())
        if block([n]):
            break
    out['terminating'] = sorted(t for (t, e), v in done.items() if v)
    out['paragraphs'] = (len(done_par), len(labels))
    out['labels'] = sorted(done_par)
    return out


def commarea_initials(caller, group):
    """Valor inicial (VALUE ou padrão da PIC) de cada elementar do grupo passado em COMMAREA pelo chamador."""
    if not group:
        return {}
    items = caller['data_model']['items']
    ch = _kids(items)
    by = {}
    for it in items:
        by.setdefault(it['name'].upper(), it)
    out = {}
    for k in _descendants(ch, group.upper()):
        it = by.get(k)
        if not it or it.get('level') == 88 or k in ch or k == 'FILLER' or it.get('redefines'):
            continue
        v = it.get('value')
        cat = (it.get('picture') or {}).get('category', '')
        if isinstance(v, str) and v.upper() in FIG:
            v = 0 if v.upper() in ('ZERO', 'ZEROS', 'ZEROES') else ' '
        out[k] = v if v not in (None, '') else (0 if cat.startswith('NUMERIC') else ' ')
    return out


def assigned_by(prog, ignore=('INITIALIZE', 'EXEC_CICS')):
    """Campos que o programa pode alterar com dados (com os descendentes dos grupos alterados). INITIALIZE só devolve
    o valor inicial, então não conta: o campo continua sendo o valor padrão."""
    ch = _kids(prog['data_model']['items'])
    out = set()
    for n in _walk_nodes(prog['ast']['body']):
        if n['type'] in ignore:
            continue
        for r in _receivers(n):
            out.add(r)
            out |= _descendants(ch, r)
    return out


def slices(model, entry):
    """{programa: {'branches': set, 'via': set, 'consts': dict, 'paragraphs': (n, total)}} do fluxo do entry point."""
    progs = model['programs']
    res = {}

    def visit(p, consts, via, via_commarea, caller_assigned=frozenset(), inherit=None):
        r = reach(progs[p], consts, via_commarea, caller_assigned, inherit)
        cur = res.setdefault(p, {'branches': set(), 'via': set(), 'consts': {}, 'paragraphs': r['paragraphs']})
        new = not (r['branches'] <= cur['branches']) or via not in cur['via']
        cur['branches'] |= r['branches']
        cur['via'].add(via)
        cur['consts'].update(consts or {})
        cur.setdefault('labels', set()).update(r['labels'])
        cur['paragraphs'] = (max(cur['paragraphs'][0], r['paragraphs'][0]), r['paragraphs'][1])
        if not new:
            return
        for c in progs[p]['calls']:
            t = c.get('target')
            if not t or t not in progs or progs[t].get('infrastructure') or c['line'] not in r['calls']:
                continue
            visit(t, caller_constants(progs[p], c['line']), p, bool(c.get('commarea')), assigned_by(progs[p]),
                  commarea_initials(progs[p], c.get('commarea')))

    visit(entry, {}, 'ENTRY', False)
    return res
