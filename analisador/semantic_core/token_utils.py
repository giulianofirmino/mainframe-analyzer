"""Primitivas sobre listas de tokens do analisador léxico.

Um token aqui é a tupla (tipo, valor, linha, coluna) que o parser guarda nos nós da AST
(arg_tokens, condition_tokens, header_tokens, subject_tokens, tokens) ou que sai de `lex()`.
Nenhuma função lê texto: tudo trabalha sobre tipo/valor/posição dos tokens.
"""
from __future__ import annotations

from cobol_token_lexer import lex, Token


def as_tuple(t):
    return (t.type, t.value, t.line, t.column) if isinstance(t, Token) else t


def _wrap_fixed(text, width=60):
    """Distribui um trecho de uma linha em linhas de formato fixo (colunas 8-72) quebrando só entre palavras, fora de literais."""
    lines, cur, quote, start = [], '', None, 0
    for i, c in enumerate(text + ' '):
        if quote:
            if c == quote:
                quote = None
            continue
        if c in ('"', "'"):
            quote = c
        elif c.isspace():
            word = text[start:i]
            if word:
                if cur and len(cur) + 1 + len(word) > width:
                    lines.append(cur)
                    cur = word
                else:
                    cur = (cur + ' ' + word) if cur else word
            start = i + 1
    if cur:
        lines.append(cur)
    return '\n'.join('       ' + ln for ln in lines)


def tokens_of(text, fixed=True):
    """Tokens de um trecho de código. fixed=True devolve o formato fixo (colunas 8-72), com o texto começando na coluna 8;
    trechos longos de uma linha são quebrados entre palavras para não perder o que passa da coluna 72."""
    body = _wrap_fixed(text) if fixed and '\n' not in text else text
    return [as_tuple(t) for t in lex(body) if t.type != 'EOF']


def V(t):
    """Valor em maiúsculas para comparar com palavras; literal (STRING) nunca casa com palavra."""
    return '' if t[0] == 'STRING' else t[1].upper()


def is_sym(t, s=None):
    return t[0] == 'SYMBOL' and (s is None or t[1] == s)


def string_value(t):
    """Conteúdo de um literal alfanumérico (o token traz as aspas e aspas duplicadas)."""
    q = t[1][0]
    return t[1][1:-1].replace(q + q, q)


def match_paren(toks, i):
    d = 0
    for j in range(i, len(toks)):
        if is_sym(toks[j], '('):
            d += 1
        elif is_sym(toks[j], ')'):
            d -= 1
            if d == 0:
                return j
    return len(toks) - 1


def split_top(toks, pred):
    out, d = [[]], 0
    for t in toks:
        if is_sym(t, '('):
            d += 1
        elif is_sym(t, ')'):
            d -= 1
        if d == 0 and pred(t):
            out.append([])
        else:
            out[-1].append(t)
    return out


def find(toks, words, start=0):
    """Índice do primeiro token (fora de parênteses) cujo valor está em words; -1 se não houver."""
    d = 0
    for i in range(start, len(toks)):
        t = toks[i]
        if is_sym(t, '('):
            d += 1
        elif is_sym(t, ')'):
            d -= 1
        elif d == 0 and V(t) in words:
            return i
    return -1


def strip_outer(toks):
    while len(toks) >= 2 and is_sym(toks[0], '(') and is_sym(toks[-1], ')') and match_paren(toks, 0) == len(toks) - 1:
        toks = toks[1:-1]
    return toks


def adjacent(a, b):
    """b começa exatamente onde a termina (mesma linha, sem espaço)."""
    return a[2] == b[2] and b[3] == a[3] + len(a[1])


def joined_name(toks, i):
    """Nome de membro/copybook que o léxico partiu em vários tokens (I#NOMEXX -> I, #, NOMEXX).
    Devolve (nome, próximo índice); aceita literal entre aspas."""
    if i >= len(toks):
        return None, i
    if toks[i][0] == 'STRING':
        return string_value(toks[i]).strip().upper(), i + 1
    if toks[i][0] not in ('IDENT', 'KEYWORD', 'NUMBER'):
        return None, i
    name, j = toks[i][1], i + 1
    while j < len(toks) and adjacent(toks[j - 1], toks[j]) and toks[j][0] in ('IDENT', 'KEYWORD', 'NUMBER', 'SYMBOL') \
            and (toks[j][0] != 'SYMBOL' or toks[j][1] in ('#', '@', '$')):
        name += toks[j][1]
        j += 1
    return name.upper(), j


def dotted_name(toks, i):
    """IDENT [. IDENT]  ->  (nome qualificado com '.', próximo índice)."""
    if i >= len(toks) or toks[i][0] != 'IDENT':
        return None, i
    name, j = V(toks[i]), i + 1
    if j + 1 < len(toks) and toks[j][0] == 'PERIOD' and adjacent(toks[j - 1], toks[j]) and toks[j + 1][0] == 'IDENT' \
            and adjacent(toks[j], toks[j + 1]):
        return name + '.' + V(toks[j + 1]), j + 2
    return name, j


def cics_options(toks):
    """(verbo, [(opção, tokens do argumento)]) de um EXEC CICS: cada opção é PALAVRA ( ... )."""
    verb = V(toks[0]) if toks else ''
    out, i = [], 0
    while i < len(toks):
        t = toks[i]
        if t[0] in ('IDENT', 'KEYWORD') and i + 1 < len(toks) and is_sym(toks[i + 1], '('):
            e = match_paren(toks, i + 1)
            out.append((V(t), toks[i + 2:e]))
            i = e + 1
        else:
            i += 1
    return verb, out


SQL_TABLE_INTRO = ('FROM', 'JOIN', 'UPDATE', 'INTO')
SQL_TABLE_STATEMENTS = ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'MERGE', 'DECLARE')


def sql_tables(toks):
    """Tabelas citadas num EXEC SQL: nome (qualificado ou não) logo depois de FROM/JOIN/UPDATE/INTO."""
    if not toks or V(toks[0]) not in SQL_TABLE_STATEMENTS:
        return []
    out = []
    for i, t in enumerate(toks):
        if V(t) in SQL_TABLE_INTRO and i + 1 < len(toks) and toks[i + 1][0] == 'IDENT':
            name, _ = dotted_name(toks, i + 1)
            if name not in out:
                out.append(name)
    return out


def parse_ref(text):
    """Referência a dado escrita como texto (CAMPO, CAMPO OF GRUPO, GRUPO.CAMPO), lida pelos tokens do léxico.
    Devolve (campo, [qualificadores]) ou (None, [])."""
    toks = tokens_of(text)
    name, j = dotted_name(toks, 0)
    if name is None:
        return None, []
    quals = []
    if '.' in name:
        q, _, name = name.partition('.')
        quals.append(q)
    while j + 1 < len(toks) and V(toks[j]) in ('OF', 'IN') and toks[j + 1][0] == 'IDENT':
        quals.append(V(toks[j + 1]))
        j += 2
    return name, quals


SQL_INTO_END = ('FROM', 'WHERE', 'GROUP', 'ORDER', 'FETCH', 'WITH', 'FOR', 'END-EXEC')


def sql_host_pairs(toks):
    """Variáveis hospedeiras da cláusula INTO de um SELECT/FETCH, com a variável indicadora quando existe:
    [(host, indicador|None)]. `:HOST :IND` e `:HOST:IND` são lidos pelos tokens ':' IDENT ['.' IDENT] ':' IDENT."""
    if not toks or V(toks[0]) not in ('SELECT', 'FETCH'):
        return []
    i = find(toks, ('INTO',))
    if i < 0:
        return []
    out, i = [], i + 1
    while i < len(toks) and V(toks[i]) not in SQL_INTO_END:
        if is_sym(toks[i], ':'):
            host, j = dotted_name(toks, i + 1)
            if host is None:
                i += 1
                continue
            ind = None
            if j < len(toks) and is_sym(toks[j], ':'):
                ind, j = dotted_name(toks, j + 1)
            out.append((host, ind))
            i = j
        else:
            i += 1
    return out


def join_tokens(toks):
    """Texto de um trecho de tokens: uma palavra por token, sem espaço em volta de ':' e '.', nem depois de '(' e antes de ')' ou ','."""
    out = ''
    prev = None
    for t in toks:
        v = t[1]
        if prev is not None and not (v in (':', '.', ',', ')') or prev in (':', '.', '(')):
            out += ' '
        out += v
        prev = v
    return out


def perform_spec(header_tokens, inline):
    """Cabeçalho de um PERFORM lido pelos tokens.
    {'target','end'}: parágrafo (e THRU) do PERFORM fora de linha;
    {'times'}: PERFORM ... n TIMES; {'until','test_after'}: PERFORM ... UNTIL cond;
    {'varying': (var, de, passo)} com 'until': PERFORM VARYING var FROM de BY passo UNTIL cond; 'after': True se houver AFTER (não suportado)."""
    toks = [as_tuple(t) for t in header_tokens or []]
    spec = {'target': None, 'end': None, 'times': None, 'until': None, 'varying': None, 'test_after': False, 'after': False}
    i = 0
    if not inline and toks:
        spec['target'] = V(toks[0])
        spec['end'] = spec['target']
        i = 1
        if i + 1 < len(toks) and V(toks[i]) in ('THRU', 'THROUGH'):
            spec['end'] = V(toks[i + 1])
            i += 2
    rest = toks[i:]
    if len(rest) >= 3 and V(rest[0]) == 'WITH' and V(rest[1]) == 'TEST':
        spec['test_after'] = V(rest[2]) == 'AFTER'
        rest = rest[3:]
    if rest and V(rest[-1]) == 'TIMES':
        spec['times'] = join_tokens(rest[:-1])
    elif rest and V(rest[0]) == 'UNTIL':
        spec['until'] = join_tokens(rest[1:])
    elif rest and V(rest[0]) == 'VARYING':
        f, b, u = find(rest, ('FROM',)), find(rest, ('BY',)), find(rest, ('UNTIL',))
        if min(f, b, u) < 0:
            raise ValueError('PERFORM VARYING incompleto')
        a = find(rest, ('AFTER',), u)
        spec['after'] = a >= 0
        spec['varying'] = (join_tokens(rest[1:f]), join_tokens(rest[f + 1:b]), join_tokens(rest[b + 1:u]))
        spec['until'] = join_tokens(rest[u + 1:a if a >= 0 else len(rest)])
    return spec
