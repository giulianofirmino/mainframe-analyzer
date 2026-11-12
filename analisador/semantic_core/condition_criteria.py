"""Critérios de uma condição: cada termo ligado por AND/OR é avaliado em separado (tokens, nunca expressão regular sobre o fonte).

`split(texto, infra)` devolve os critérios (termos atômicos, com a marca de infraestrutura que `infra(texto_do_termo)` decide) e o texto da condição
só com os critérios de negócio (None quando todos são de infraestrutura; o mesmo texto quando nenhum é)."""
from __future__ import annotations
from token_utils import tokens_of, V, _wrap_fixed


def _slice(lines, a, b):
    """Texto original entre o início do token a e o fim do token b (colunas do texto já distribuído em linhas)."""
    (_t, _v, l1, c1), (_t2, v2, l2, c2) = a, b
    if l1 == l2:
        return lines[l1 - 1][c1 - 1:c2 - 1 + len(v2)]
    parts = [lines[l1 - 1][c1 - 1:]] + [x.strip() for x in lines[l1:l2 - 1]] + [lines[l2 - 1][:c2 - 1 + len(v2)].strip()]
    return ' '.join(x.strip() for x in parts if x.strip())


def _match_close(toks, i):
    depth = 0
    for k in range(i, len(toks)):
        if toks[k][0] == 'SYMBOL' and toks[k][1] == '(':
            depth += 1
        elif toks[k][0] == 'SYMBOL' and toks[k][1] == ')':
            depth -= 1
            if depth == 0:
                return k
    return -1


def _split_top(toks, i, j, word):
    """Posições (nível zero de parênteses) em que a palavra `word` separa termos; AND de BETWEEN não separa."""
    cuts, depth, between = [], 0, False
    for k in range(i, j):
        t = toks[k]
        if t[0] == 'SYMBOL' and t[1] == '(':
            depth += 1
        elif t[0] == 'SYMBOL' and t[1] == ')':
            depth -= 1
        elif depth == 0 and t[0] == 'KEYWORD' or (depth == 0 and t[0] == 'IDENT'):
            v = V(t)
            if v == 'BETWEEN':
                between = True
            elif v == 'AND' and word == 'AND' and between:
                between = False
            elif v == word:
                cuts.append(k)
    return cuts


def _parse(toks, i, j):
    for word in ('OR', 'AND'):
        cuts = _split_top(toks, i, j, word)
        if cuts:
            edges = [i - 1] + cuts + [j]
            return ('op', word, [_parse(toks, edges[n] + 1, edges[n + 1]) for n in range(len(edges) - 1) if edges[n] + 1 < edges[n + 1]])
    if toks[i][0] == 'SYMBOL' and toks[i][1] == '(' and _match_close(toks, i) == j - 1 and j - i > 2:
        return ('paren', _parse(toks, i + 1, j - 1))
    return ('atom', i, j)


def split(text, infra):
    if not text or not text.strip():
        return {'criteria': [], 'business': text, 'mixed': False, 'all_infra': False}
    body = _wrap_fixed(text) if '\n' not in text else text
    lines = body.split('\n')
    toks = tokens_of(text)
    if not toks:
        return {'criteria': [], 'business': text, 'mixed': False, 'all_infra': False}
    tree = _parse(toks, 0, len(toks))
    atoms, multi = [], {}

    def render(n):
        if n[0] == 'atom':
            t = _slice(lines, toks[n[1]], toks[n[2] - 1])
            inf = bool(infra(t))
            atoms.append({'text': t, 'infra': inf})
            return None if inf else t
        if n[0] == 'paren':
            r = render(n[1])
            if r is None:
                return None
            return f'({r})' if n[1][0] == 'op' and multi.get(id(n[1])) else r
        parts = [x for x in (render(c) for c in n[2]) if x is not None]
        multi[id(n)] = len(parts) > 1
        if not parts:
            return None
        return parts[0] if len(parts) == 1 else f' {n[1]} '.join(parts)
    biz = render(tree)
    n_inf = sum(a['infra'] for a in atoms)
    return {'criteria': atoms, 'business': biz, 'mixed': 0 < n_inf < len(atoms), 'all_infra': bool(atoms) and n_inf == len(atoms)}


CMP_OPS = {'==': '=', '=': '=', '!=': '≠', '<>': '≠', '<': '<', '>': '>', '<=': '≤', '>=': '≥'}


def atomos(texto):
    """[{campo, op, valor}] de cada critério da condição, só por tokens: `campo op literal|campo|figurativa`, `campo IN (a, b)`, `campo IS [NOT] NUMERIC`,
    `campo == TRUE` (indicador). Campo qualificado (X OF Y) vale pelo primeiro nome. O que não é comparação de campo (chamada de função, expressão) não entra."""
    out = []
    for crit in split(texto, lambda _t: False)['criteria']:
        toks = tokens_of(' ' * 7 + crit['text'], fixed=False)
        toks = [t for t in toks if not (t[0] == 'SYMBOL' and t[1] in '()' and False)]
        neg = bool(toks) and V(toks[0]) == 'NOT'
        k = 0
        while k < len(toks):
            t = toks[k]
            if t[0] == 'IDENT' and V(t) not in ('NOT', 'AND', 'OR', 'IN', 'IS', 'OF', 'TRUE', 'FALSE', 'NUMERIC', 'ZEROS', 'ZERO', 'SPACES', 'SPACE'):
                campo, j = V(t), k + 1
                while j + 1 < len(toks) and V(toks[j]) == 'OF' and toks[j + 1][0] == 'IDENT':
                    j += 2
                nxt = toks[j] if j < len(toks) else None
                op, n_sym = '', 0
                while j + n_sym < len(toks) and toks[j + n_sym][0] == 'SYMBOL' and n_sym < 2 and set(toks[j + n_sym][1]) <= set('=!<>'):
                    op += toks[j + n_sym][1]
                    n_sym += 1
                if op in CMP_OPS and j + n_sym < len(toks):
                    r = toks[j + n_sym]
                    v = str(r[1])
                    if r[0] == 'SYMBOL' and r[1] in '+-' and j + n_sym + 1 < len(toks):
                        v = r[1] + str(toks[j + n_sym + 1][1])
                    out.append({'campo': campo, 'op': CMP_OPS[op], 'valor': 'verdadeiro (indicador ligado)' if v.upper() == 'TRUE' else v})
                    k = j + n_sym
                elif nxt is not None and V(nxt) == 'IN' and j + 1 < len(toks) and toks[j + 1][1] == '(':
                    e = _match_close(toks, j + 1)
                    vals = [str(x[1]) for x in toks[j + 2:e] if not (x[0] == 'SYMBOL' and x[1] == ',')]
                    out.append({'campo': campo, 'op': 'não está em' if neg else 'está em', 'valor': ', '.join(vals)})
                elif nxt is not None and V(nxt) == 'IS':
                    m = toks[j + 1:j + 3]
                    isn = bool(m) and V(m[0]) == 'NOT'
                    if (m[1:2] and V(m[1]) == 'NUMERIC') or (m and V(m[0]) == 'NUMERIC'):
                        out.append({'campo': campo, 'op': 'não é' if isn else 'é', 'valor': 'numérico'})
            k += 1
    return out
