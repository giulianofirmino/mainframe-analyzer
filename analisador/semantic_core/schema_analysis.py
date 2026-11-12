"""Análise de esquema das tabelas DB2, calculada dos comandos SQL (tokens) e dos DCLGEN.

  * uso de cada coluna por programa (lê, grava, filtra), lido de SELECT/FETCH INTO, INSERT, UPDATE SET e WHERE;
  * dedução de colunas para tabelas sem DCLGEN: nome da coluna do SQL, campo COBOL que a recebe (variável hospedeira) e o
    tipo lido da declaração PIC desse campo; sem declaração (copybook ausente) o tipo fica 'sem declaração';
  * dono provável de cada tabela: programa que mais altera (INSERT/UPDATE/DELETE; em empate, quem insere); demais programas que
    gravam; programas que só consomem.
Só tokens e a estrutura do SQL; nenhum nome de tabela, coluna ou programa fixado aqui."""
from __future__ import annotations
from collections import defaultdict

from token_utils import tokens_of, V, is_sym, find, dotted_name, split_top, sql_tables, sql_host_pairs, match_paren

WRITE = ('INSERT', 'UPDATE', 'DELETE', 'MERGE')
READ = ('SELECT', 'FETCH', 'OPEN', 'CLOSE')
CMP = {'=', '<', '>', '<=', '>=', '<>'}
STOP = ('FROM', 'WHERE', 'GROUP', 'ORDER', 'FETCH', 'WITH', 'FOR', 'END-EXEC', 'INTO')


def _walk(nodes):
    for n in nodes:
        yield n
        for k in ('body', 'then', 'else_body', 'at_end'):
            if isinstance(n.get(k), list):
                yield from _walk(n[k])
        for w in n.get('whens', []) or []:
            yield from _walk(w.get('body', []))


def _colname(item):
    """Nome da coluna de um item de lista SELECT (ignora função e literal): último trecho do primeiro nome que não é função."""
    for i, t in enumerate(item):
        if t[0] == 'IDENT' and V(t) not in ('DISTINCT', 'ALL', 'AS'):
            if i + 1 < len(item) and is_sym(item[i + 1], '('):
                continue
            name, _ = dotted_name(item, i)
            return name.split('.')[-1].upper() if name else None
    return None


def _first_host(toks):
    for i, t in enumerate(toks):
        if is_sym(t, ':'):
            name, _ = dotted_name(toks, i + 1)
            if name:
                return name.upper()
    return None


def _lit_kind(t):
    return 'numérico' if t[0] == 'NUMBER' else ('alfanumérico' if t[0] == 'STRING' else None)


FIG_NUM = {'ZERO', 'ZEROS', 'ZEROES'}
FIG_ALF = {'SPACE', 'SPACES', 'HIGH-VALUE', 'HIGH-VALUES', 'LOW-VALUE', 'LOW-VALUES'}


def _kind_of(t):
    k = _lit_kind(t)
    if k:
        return k
    v = str(t[1]).upper()
    return 'numérico' if v in FIG_NUM else ('alfanumérico' if v in FIG_ALF else None)


def _field_literals(ast):
    """{campo: {tipo}} do que o código faz com cada campo: MOVE literal/figurativa TO campo e campo comparado com literal/figurativa num IF."""
    out = defaultdict(set)
    for n in _walk(ast.get('body', [])):
        t = n.get('type')
        if t == 'MOVE' and n.get('args'):
            tk = tokens_of(' ' * 7 + n['args'], fixed=False)
            if tk and _kind_of(tk[0]):
                k = _kind_of(tk[0])
                for j, x in enumerate(tk):
                    if str(x[1]).upper() == 'TO' and x[0] in ('IDENT', 'KEYWORD'):
                        for y in tk[j + 1:]:
                            if y[0] == 'IDENT' and str(y[1]).upper() not in ('OF', 'IN'):
                                out[str(y[1]).upper().split('.')[-1]].add(k)
                        break
        elif t == 'IF' and n.get('condition'):
            tk = tokens_of(' ' * 7 + n['condition'], fixed=False)
            for j in range(1, len(tk) - 1):
                if tk[j][0] == 'SYMBOL' and tk[j][1] in CMP and tk[j - 1][0] == 'IDENT' and _kind_of(tk[j + 1]):
                    i = j - 1
                    while i >= 2 and str(tk[i - 1][1]).upper() in ('OF', 'IN') and tk[i - 2][0] == 'IDENT':   # campo OF grupo: o campo é o primeiro nome
                        i -= 2
                    out[str(tk[i][1]).upper().split('.')[-1]].add(_kind_of(tk[j + 1]))
    return out


def _move_peers(ast):
    """{campo: {campos com quem troca valor num MOVE}}: `MOVE a TO b` liga a e b (o tipo de um serve de pista para o outro)."""
    out = defaultdict(set)
    for n in _walk(ast.get('body', [])):
        if n.get('type') != 'MOVE' or not n.get('args'):
            continue
        tk = tokens_of(' ' * 7 + n['args'], fixed=False)
        k = next((j for j, x in enumerate(tk) if str(x[1]).upper() == 'TO' and x[0] in ('IDENT', 'KEYWORD')), -1)
        if k < 1:
            continue
        def names(seq):
            r, i = [], 0
            while i < len(seq):
                if seq[i][0] == 'IDENT' and str(seq[i][1]).upper() not in {'OF', 'IN', 'CORRESPONDING', 'CORR'} | FIG_NUM | FIG_ALF:
                    r.append(str(seq[i][1]).upper().split('.')[-1])
                    i += 1
                    while i + 1 < len(seq) and str(seq[i][1]).upper() in ('OF', 'IN'):
                        i += 2
                else:
                    i += 1
            return r
        src, dst = names(tk[:k])[:1], names(tk[k + 1:])
        for a in src:
            for b in dst:
                out[a].add(b)
                out[b].add(a)
    return out


def _where_literals(toks):
    """[(coluna, tipo do literal)] dos predicados `coluna op literal` depois de WHERE (o tipo do literal diz o tipo da coluna)."""
    i = find(toks, ('WHERE',))
    if i < 0:
        return []
    out, seg = [], toks[i + 1:]
    for j, t in enumerate(seg):
        if j and t[0] == 'SYMBOL' and t[1] in CMP and seg[j - 1][0] == 'IDENT' and j + 1 < len(seg):
            r = seg[j + 1]
            if r[0] == 'SYMBOL' and r[1] in '+-' and j + 2 < len(seg):
                r = seg[j + 2]
            k = _lit_kind(r)
            if k:
                out.append((seg[j - 1][1].split('.')[-1].upper(), k))
    return out


def _where(toks):
    """[(coluna, host)] dos predicados `coluna op :host` ou `:host op coluna` depois de WHERE."""
    i = find(toks, ('WHERE',))
    if i < 0:
        return []
    out, seg = [], toks[i + 1:]
    for j, t in enumerate(seg):
        if t[0] == 'SYMBOL' and t[1] in CMP or V(t) in ('LIKE', 'IN', 'BETWEEN'):
            left = seg[j - 1] if j else None
            right = seg[j + 1:j + 4]
            col = host = None
            if left is not None and left[0] == 'IDENT' and V(left) not in ('AND', 'OR', 'NOT'):
                col = left[1].split('.')[-1].upper()
                host = _first_host(seg[j + 1:j + 5])
            if col is None and left is not None and j >= 3:
                host2 = _first_host(seg[max(0, j - 4):j])
                r = right[0] if right and right[0][0] == 'IDENT' else None
                if host2 and r:
                    col, host = r[1].split('.')[-1].upper(), host2
            if col:
                out.append((col, host))
    return out


def parse_sql(toks, cursors):
    """Estrutura do comando: {'op','tables','pairs':[(coluna, host|None, modo)]}. modo: lê | grava | filtra."""
    toks = list(toks)
    if not toks:
        return None
    op = V(toks[0])
    tables = [t.upper() for t in sql_tables(toks)]
    pairs = []
    if op == 'SELECT' or (op == 'DECLARE' and find(toks, ('SELECT',)) >= 0):
        s = find(toks, ('SELECT',))
        e = min([x for x in (find(toks, ('INTO',), s), find(toks, ('FROM',), s)) if x >= 0] or [len(toks)])
        cols = [c for c in (_colname(it) for it in split_top(toks[s + 1:e], lambda t: is_sym(t, ','))) if True]
        hosts = [h for h, _ind in sql_host_pairs(toks[s:])] if op == 'SELECT' else []
        for k, c in enumerate(cols):
            if c:
                pairs.append((c, hosts[k].upper() if len(hosts) == len(cols) else None, 'lê'))
        if op == 'DECLARE':
            name = toks[1][1].upper() if len(toks) > 1 else None
            cursors[name] = {'tables': tables, 'cols': cols}
            op = 'DECLARE'
    elif op == 'FETCH':
        cn = next((V(t) for t in toks[1:3] if V(t) in cursors), None)
        hosts = [h for h, _ in sql_host_pairs(toks)]
        if cn:
            info = cursors[cn]
            tables = list(info['tables'])
            for k, c in enumerate(info['cols']):
                if c:
                    pairs.append((c, hosts[k].upper() if len(hosts) == len(info['cols']) else None, 'lê'))
    elif op == 'INSERT':
        i = find(toks, ('INTO',))
        if i >= 0:
            j = next((k for k in range(i, len(toks)) if is_sym(toks[k], '(')), None)
            if j is not None:
                c_end = match_paren(toks, j)
                cols = [_colname(x) for x in split_top(toks[j + 1:c_end], lambda t: is_sym(t, ','))]
                v = find(toks, ('VALUES',), c_end)
                hosts = []
                if v >= 0 and v + 1 < len(toks) and is_sym(toks[v + 1], '('):
                    hosts = [_first_host(x) for x in split_top(toks[v + 2:match_paren(toks, v + 1)], lambda t: is_sym(t, ','))]
                for k, c in enumerate(cols):
                    if c:
                        pairs.append((c, hosts[k] if k < len(hosts) else None, 'grava'))
    elif op == 'UPDATE':
        s = find(toks, ('SET',))
        if s >= 0:
            end = find(toks, ('WHERE',), s)
            for it in split_top(toks[s + 1:end if end >= 0 else len(toks)], lambda t: is_sym(t, ',')):
                if it and it[0][0] == 'IDENT':
                    pairs.append((_colname(it[:1]), _first_host(it), 'grava'))
    if op in ('SELECT', 'UPDATE', 'DELETE', 'DECLARE', 'FETCH') and (op != 'FETCH'):
        for c, h in _where(toks):
            pairs.append((c, h, 'filtra'))
    lits = list(_where_literals(toks)) + _values_literals(toks, op)
    return {'op': op, 'tables': tables, 'pairs': pairs, 'literals': lits}


def _values_literals(toks, op):
    """[(coluna, tipo do literal)] de INSERT ... (cols) VALUES (literais) e de UPDATE SET coluna = literal."""
    out = []
    if op == 'INSERT':
        i = find(toks, ('INTO',))
        j = next((k for k in range(i, len(toks)) if is_sym(toks[k], '(')), None) if i >= 0 else None
        if j is not None:
            c_end = match_paren(toks, j)
            cols = [_colname(x) for x in split_top(toks[j + 1:c_end], lambda t: is_sym(t, ','))]
            v = find(toks, ('VALUES',), c_end)
            if v >= 0 and v + 1 < len(toks) and is_sym(toks[v + 1], '('):
                vals = split_top(toks[v + 2:match_paren(toks, v + 1)], lambda t: is_sym(t, ','))
                for c, it in zip(cols, vals):
                    lits = [x for x in it if _lit_kind(x)]
                    if c and len(it) <= 2 and lits:
                        out.append((c, _lit_kind(lits[0])))
    elif op == 'UPDATE':
        s_ = find(toks, ('SET',))
        if s_ >= 0:
            end = find(toks, ('WHERE',), s_)
            for it in split_top(toks[s_ + 1:end if end >= 0 else len(toks)], lambda t: is_sym(t, ',')):
                if len(it) >= 3 and it[0][0] == 'IDENT' and is_sym(it[1], '=') and _lit_kind(it[2]):
                    out.append((it[0][1].split('.')[-1].upper(), _lit_kind(it[2])))
    return out


def _type_of(dm, host):
    """Tipo lido da declaração do campo hospedeiro: PIC [USAGE]; None se o campo não está declarado."""
    if not host:
        return None
    it = dm['by_name'].get(host.split('.')[-1].upper())
    if not it or not it.get('pic'):
        return None
    return f'PIC {it["pic"]}' + (f' {it["usage"]}' if it.get('usage') else '')


OP_KIND = {'INSERT': ('insere',), 'UPDATE': ('altera',), 'DELETE': ('exclui',), 'MERGE': ('altera', 'insere'),
           'SELECT': ('consulta',), 'OPEN': ('consulta',), 'FETCH': ('consulta',)}
OP_ORDER = ('insere', 'altera', 'exclui', 'consulta')


def table_operations(model, dependencies, canon_name=lambda t: t):
    """O que cada programa faz em cada tabela: insere, altera, exclui, consulta (só o que o código faz; sem dono nem papel).
    [{'program','table','counts':{op:n},'accesses':[{'line','source_line','statement','kind','via_cursor'}]}] ordenado por tabela e programa.
    Comando SQL -> tipo: INSERT insere; UPDATE altera; DELETE exclui; MERGE altera e insere; SELECT, OPEN e FETCH consultam; CLOSE não conta."""
    acc = defaultdict(list)
    for p, d in dependencies.items():
        lm = model['programs'][p]['linemap'] if p in model.get('programs', {}) else None
        for a in d.get('table_access', []):
            kinds = OP_KIND.get(a['operation'])
            if not kinds:
                continue
            acc[(canon_name(a['table']), p)].append({'line': a['line'], 'source_line': lm.source_line(a['line']) if lm else a['line'], 'statement': a['operation'],
                                                     'kinds': list(kinds), 'via_cursor': a['via_cursor']})
    out = []
    for (t, p), xs in sorted(acc.items()):
        xs.sort(key=lambda x: (x['line'] or 0, x['statement']))
        counts = {k: sum(1 for x in xs if k in x['kinds']) for k in OP_ORDER}
        out.append({'program': p, 'table': t, 'counts': counts, 'accesses': xs})
    return out


def analyze(model, dependencies, dclgen_tables, roles):
    """dclgen_tables: {tabela: {coluna, ...}} (tabelas com DCLGEN e suas colunas); roles: saída de table_roles.build."""
    canon = {}
    for t in dclgen_tables:
        canon.setdefault(t.split('.')[-1], t)

    def name(t):
        t = t.upper()
        return t if '.' in t or t not in canon else canon[t]
    host_pic = {}                                                              # campo hospedeiro -> PIC declarado em qualquer programa da base
    for p, x in model['programs'].items():
        for nm, it in x['data_model']['by_name'].items():
            if it.get('pic'):
                host_pic.setdefault(nm.upper(), f'PIC {it["pic"]}' + (f' {it["usage"]}' if it.get('usage') else ''))
    host_lit = defaultdict(set)                                                # campo hospedeiro -> tipos de literal movidos para ele ou comparados com ele no código
    for p, x in model['programs'].items():
        for nm, ks in _field_literals(x['ast']).items():
            host_lit[nm] |= ks
    host_peer = defaultdict(set)                                               # campo hospedeiro -> campos com quem troca valor num MOVE
    for p, x in model['programs'].items():
        for nm, ps in _move_peers(x['ast']).items():
            host_peer[nm] |= ps
    lit_kind = defaultdict(lambda: defaultdict(set))                           # tabela -> coluna -> tipos de literal comparados ou gravados
    col_use = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))       # tabela -> coluna -> modo -> {programa}
    evid = defaultdict(lambda: defaultdict(list))                              # tabela -> coluna -> evidências
    for p, x in model['programs'].items():
        cursors = {}
        dm = x['data_model']
        for n in _walk(x['ast'].get('body', [])):
            if n.get('type') != 'EXEC_SQL':
                continue
            r = parse_sql(n.get('tokens') or [], cursors)
            if not r or len(set(r['tables'])) != 1:
                continue
            t = name(r['tables'][0])
            for c, k in r.get('literals', []):
                lit_kind[t][c].add(k)
            for c, host, mode in r['pairs']:
                col_use[t][c][mode].add(p)
                evid[t][c].append({'program': p, 'line': x['linemap'].source_line(n['start_line']), 'operation': r['op'], 'mode': mode,
                                   'host': host, 'type': _type_of(dm, host)})
    # colunas deduzidas para tabelas sem DCLGEN
    deduced = []
    for t in sorted(col_use):
        if t in dclgen_tables:
            continue
        for c in sorted(col_use[t]):
            ev = sorted(evid[t][c], key=lambda e: (e['program'], e['line'] or 0, e['mode']))
            typ = next((e['type'] for e in ev if e['type']), None)
            hosts = sorted({e['host'] for e in ev if e['host']})
            how = 'PIC do campo hospedeiro' if typ else ''
            if not typ:   # campo sem declaração no programa: o mesmo campo declarado em outro programa da base
                for h in hosts:
                    typ = host_pic.get(h.split('.')[-1])
                    if typ:
                        how = f'PIC de {h.split(".")[-1]} declarado em outro programa'
                        break
            if not typ and lit_kind[t].get(c):
                ks = sorted(lit_kind[t][c])
                typ = ('numérico' if ks == ['numérico'] else 'alfanumérico' if ks == ['alfanumérico'] else 'numérico ou alfanumérico') + ' (literal comparado ou gravado)'
                how = 'tipo do literal usado no SQL'
            if not typ:
                ks = sorted(set().union(*[host_lit.get(h.split('.')[-1].upper(), set()) for h in hosts])) if hosts else []
                if ks:
                    typ = ('numérico' if ks == ['numérico'] else 'alfanumérico' if ks == ['alfanumérico'] else 'numérico ou alfanumérico') + ' (literal movido ou comparado no código)'
                    how = 'tipo do literal que o código move para o campo hospedeiro ou compara com ele'
            if not typ:   # campo que troca valor com o hospedeiro num MOVE e tem PIC declarada
                for h in hosts:
                    for q in sorted(host_peer.get(h.split('.')[-1].upper(), ())):
                        if host_pic.get(q):
                            typ, how = host_pic[q], f'PIC de {q}, que troca valor com {h.split(".")[-1]} num MOVE'
                            break
                    if typ:
                        break
            deduced.append({'table': t, 'column': c, 'type': typ or 'sem declaração', 'host_fields': hosts,
                            'modes': sorted({m for m in col_use[t][c]}), 'programs': sorted({e['program'] for e in ev}),
                            'lines': sorted({(e['program'], e['line']) for e in ev})[:12], 'basis': 'uso no SQL' + (f' + {how}' if typ else ' (campo sem declaração)')})
    # uso de coluna nas tabelas com DCLGEN (aproveita as mesmas evidências)
    usage = []
    for t in sorted(col_use):
        for c in sorted(col_use[t]):
            usage.append({'table': t, 'column': c, 'read': sorted(col_use[t][c].get('lê', ())), 'write': sorted(col_use[t][c].get('grava', ())), 'filter': sorted(col_use[t][c].get('filtra', ())),
                          'statements': sorted({(e['program'], e['operation']) for e in evid[t][c]}),
                          'known_by': 'DCLGEN' if t in dclgen_tables and c in dclgen_tables[t] else ('SQL' if t not in dclgen_tables else 'SQL (fora do DCLGEN)')})
    return {'column_usage': usage, 'deduced_columns': deduced, 'operations': table_operations(model, dependencies, name)}
