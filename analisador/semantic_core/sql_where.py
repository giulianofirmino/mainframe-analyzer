"""Predicados do WHERE de um comando SQL, lidos dos tokens (sem regex, nenhum nome fixo).

`predicates(tokens_depois_do_WHERE)` devolve uma lista, na ordem do comando, de
  {'connector': 'AND'|'OR'|None, 'group' (G1, G2...: predicados do mesmo parêntese; '' fora de parênteses), 'column', 'op', 'value', 'value_kind', 'hosts', 'text'}
  value_kind: 'campo' (variável hospedeira), 'valor fixo' (número ou texto), 'coluna', 'subconsulta', 'expressão', '' (sem operando, ex.: IS NULL).
  hosts: nomes das variáveis hospedeiras do operando (último componente do nome, como no fluxo de dados).
O conector é o AND/OR que liga o predicado ao anterior. Grupos entre parênteses são achatados na ordem em que aparecem.
O WHERE termina em ORDER, GROUP, HAVING, FOR, WITH, FETCH, OPTIMIZE, UNION ou no fim dos tokens."""
from token_utils import V, join_tokens, dotted_name

END_WORDS = {'ORDER', 'GROUP', 'HAVING', 'FOR', 'WITH', 'FETCH', 'OPTIMIZE', 'UNION', 'INTO'}
SYM_OPS = {'=': '=', '<>': '<>', '¬=': '<>', '!=': '<>', '>': '>', '<': '<', '>=': '>=', '<=': '<='}
WORD_OPS = {'LIKE', 'IN', 'BETWEEN', 'IS', 'EXISTS'}
FLIP = {'=': '=', '<>': '<>', '>': '<', '<': '>', '>=': '<=', '<=': '>='}


def _close(toks, i):
    d = 0
    for j in range(i, len(toks)):
        if toks[j][1] == '(' and toks[j][0] == 'SYMBOL':
            d += 1
        elif toks[j][1] == ')' and toks[j][0] == 'SYMBOL':
            d -= 1
            if d == 0:
                return j
    return len(toks) - 1


def _split_logic(toks):
    """[(conector, tokens)] cortando em AND/OR de nível zero; o AND de BETWEEN a AND b fica no predicado."""
    out, cur, d, conn, between = [], [], 0, None, False
    for t in toks:
        if t[0] == 'SYMBOL' and t[1] == '(':
            d += 1
        elif t[0] == 'SYMBOL' and t[1] == ')':
            d -= 1
        v = V(t)
        if d == 0 and t[0] != 'STRING':
            if v == 'BETWEEN':
                between = True
            if v in ('AND', 'OR') and not (v == 'AND' and between):
                out.append((conn, cur))
                cur, conn, between = [], v, False
                continue
            if v == 'AND' and between:
                between = False
        cur.append(t)
    out.append((conn, cur))
    return [(c, p) for c, p in out if p]


def _hosts(toks):
    out, i = [], 0
    while i < len(toks):
        if toks[i][0] == 'SYMBOL' and toks[i][1] == ':':
            name, j = dotted_name(toks, i + 1)
            if name:
                out.append(name.split('.')[-1])
                i = j
                continue
        i += 1
    return out


def _value(toks):
    hs = _hosts(toks)
    text = join_tokens(toks)
    if hs:
        kind = 'campo'
    elif len(toks) == 1 and toks[0][0] in ('NUMBER', 'STRING'):
        kind = 'valor fixo'
    elif toks and toks[0][1] == '(' and len(toks) > 1 and V(toks[1]) == 'SELECT':
        kind = 'subconsulta'
    elif len(toks) == 1 or (len(toks) == 3 and toks[1][1] == '.'):
        kind = 'coluna'
    else:
        kind = 'expressão'
    return text, kind, hs


def _one(conn, toks):
    depth = 0
    for i, t in enumerate(toks):
        if t[0] == 'SYMBOL' and t[1] == '(':
            depth += 1
        elif t[0] == 'SYMBOL' and t[1] == ')':
            depth -= 1
        if depth:
            continue
        v = V(t)
        op = None
        j = i + 1
        if t[0] == 'SYMBOL' and t[1] in SYM_OPS:
            op = SYM_OPS[t[1]]
        elif v in WORD_OPS or (v == 'NOT' and i + 1 < len(toks) and V(toks[i + 1]) in WORD_OPS):
            words = [v]
            if v == 'NOT':
                words.append(V(toks[i + 1]))
                j = i + 2
            if words[-1] == 'IS' and j < len(toks) and V(toks[j]) == 'NOT':
                words.append('NOT')
                j += 1
            if 'IS' in words and j < len(toks) and V(toks[j]) == 'NULL':
                words.append('NULL')
                j += 1
            op = ' '.join(words)
        if op:
            left, right = toks[:i], toks[j:]
            if _hosts(left) and not _hosts(right):
                left, right = right, left
                op = FLIP.get(op, op)
            lt = join_tokens(left)
            vt, vk, hs = _value(right) if right else ('', '', [])
            names = [x[1] for x in left if x[0] == 'IDENT']
            simple = len(left) == len(names) + (len(names) - 1) and all(x[0] == 'IDENT' or x[1] == '.' for x in left) and names
            return {'connector': conn, 'column': lt, 'qualifier': '.'.join(names[:-1]) if simple else '', 'field': names[-1] if simple else lt,
                    'op': op, 'value': vt, 'value_kind': vk, 'hosts': hs,
                    'text': ' '.join(x for x in (lt, op, vt) if x)}
    txt = join_tokens(toks)
    return {'connector': conn, 'column': txt, 'qualifier': '', 'field': txt, 'op': '', 'value': '', 'value_kind': 'expressão', 'hosts': _hosts(toks), 'text': txt}


def predicates(toks, _grp=None, _pref=''):
    _grp = _grp if _grp is not None else [0]
    toks = list(toks)
    cut = len(toks)
    d = 0
    for i, t in enumerate(toks):
        if t[0] == 'SYMBOL' and t[1] == '(':
            d += 1
        elif t[0] == 'SYMBOL' and t[1] == ')':
            d -= 1
        elif d == 0 and t[0] != 'STRING' and V(t) in END_WORDS:
            cut = i
            break
    toks = toks[:cut]
    out = []
    for conn, piece in _split_logic(toks):
        if piece[0][0] == 'SYMBOL' and piece[0][1] == '(' and _close(piece, 0) == len(piece) - 1 and len(piece) > 2 and \
                any(V(x) in ('AND', 'OR') for x in piece[1:-1] if x[0] != 'STRING'):
            _grp[0] += 1
            gid = f'G{_grp[0]}'
            sub = predicates(piece[1:-1], _grp, gid)
            if sub:
                sub[0]['connector'] = conn
                out.extend(sub)
                continue
        x = _one(conn, piece)
        x['group'] = _pref
        out.append(x)
    return out


FROM_STOP = {'WHERE', 'GROUP', 'ORDER', 'FOR', 'WITH', 'UNION', 'HAVING', 'FETCH', 'OPTIMIZE'}
ALIAS_STOP = FROM_STOP | {'JOIN', 'INNER', 'LEFT', 'RIGHT', 'FULL', 'OUTER', 'CROSS', 'ON', 'USING', 'SET', 'AS'}


def aliases(toks):
    """{apelido em maiúsculas: tabela} das tabelas do FROM (com ou sem AS) e do nome completo de cada tabela; lido dos tokens."""
    toks = list(toks)
    out = {}
    i = next((k for k, t in enumerate(toks) if t[0] != 'STRING' and V(t) == 'FROM'), -1)
    if i < 0:
        return out
    i += 1
    depth = 0
    want = True
    while i < len(toks):
        t = toks[i]
        if t[0] == 'SYMBOL' and t[1] == '(':
            depth += 1
        elif t[0] == 'SYMBOL' and t[1] == ')':
            depth -= 1
        elif depth == 0 and t[0] != 'STRING':
            v = V(t)
            if v in FROM_STOP:
                break
            if v == 'JOIN' or (t[0] == 'SYMBOL' and t[1] == ','):
                want = True
            elif v == 'ON':
                want = False
            elif want and t[0] == 'IDENT':
                name, j = dotted_name(toks, i)
                if name:
                    out.setdefault(name.upper(), name)
                    out.setdefault(name.split('.')[-1].upper(), name)
                    k = j
                    if k < len(toks) and V(toks[k]) == 'AS':
                        k += 1
                    if k < len(toks) and toks[k][0] == 'IDENT' and V(toks[k]) not in ALIAS_STOP:
                        out[V(toks[k])] = name
                        j = k + 1
                    want = False
                    i = j
                    continue
        i += 1
    return out


def resolve(pred, table_of):
    """Tabela de um predicado: pelo qualificador (apelido, nome curto ou completo); sem qualificador só se houver uma tabela no FROM."""
    q = pred.get('qualifier', '').upper()
    if q:
        return table_of.get(q) or table_of.get(q.split('.')[-1]) or ''
    tabs = sorted({v for v in table_of.values()})
    return tabs[0] if len(tabs) == 1 else ''


def resolve_value(value, al, table):
    """(texto do valor com o apelido trocado pelo nome curto da tabela, [tabelas das colunas citadas no valor]): `B.Y` com `B` apelido de SCH.T2 vira `T2.Y`.
    Coluna sem qualificador vale a tabela única do FROM. Só tokens."""
    from token_utils import tokens_of
    toks = tokens_of(value)
    out, tabs, i = [], [], 0
    uniq = sorted(set(al.values()))
    while i < len(toks):
        t = toks[i]
        if t[0] == 'IDENT' and i + 2 < len(toks) and toks[i + 1][1] == '.' and toks[i + 2][0] == 'IDENT' and (i + 3 >= len(toks) or toks[i + 3][1] != '.'):
            tb = al.get(V(t)) or al.get(V(t).split('.')[-1]) or ''
            if tb:
                tabs.append(tb)
                out.append(('IDENT', tb.split('.')[-1]))
                out.append(('SYMBOL', '.'))
                out.append(toks[i + 2])
                i += 3
                continue
        out.append(t)
        i += 1
    return join_tokens(out), sorted(set(tabs))


def role(pred, table, tables_in_value):
    """Papel do predicado: ligação entre tabelas (compara coluna de uma tabela com coluna de outra) ou o tipo de filtro, decidido pelo operando."""
    k = pred.get('value_kind', '')
    other = [t for t in tables_in_value if t and t != table]
    if k == 'coluna':
        return 'ligação entre tabelas' if other else 'comparação entre colunas da mesma tabela'
    if k == 'expressão':
        return 'ligação entre tabelas' if other else 'filtro por expressão'
    return {'campo': 'filtro por campo do programa', 'valor fixo': 'filtro por valor fixo', 'subconsulta': 'filtro por subconsulta', '': 'teste sem operando'}.get(k, 'filtro')
