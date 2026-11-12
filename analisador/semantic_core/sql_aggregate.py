"""Funções de agregação do SELECT (MAX, MIN, COUNT, SUM, AVG), lidas pelos tokens do léxico.

Uma coluna de projeção como `MAX(NLIBRC_CANAL_CONTR) + 1` vira (função, coluna, operador, operando, padrão). O resultado segue o DB2:
sem linhas, MAX/MIN/SUM/AVG dão NULL (COUNT dá 0) e aritmética com NULL dá NULL. `VALUE`/`COALESCE`/`IFNULL(agregação, padrão)` troca o NULL
da agregação pelo padrão antes da aritmética (`VALUE(MAX(X), 0) + 1`).
"""
from __future__ import annotations

from token_utils import tokens_of, V, is_sym, match_paren

FUNCS = ('MAX', 'MIN', 'COUNT', 'SUM', 'AVG')
ARITH = ('+', '-', '*', '/')


def parse_aggregate(expr):
    """(função, [tokens do argumento], operador|None, operando|None, padrão|None) ou None quando a coluna não é agregação."""
    toks = tokens_of(expr)
    padrao = None
    if len(toks) > 6 and toks[0][0] in ('IDENT', 'KEYWORD') and V(toks[0]) in ('VALUE', 'COALESCE', 'IFNULL') and is_sym(toks[1], '('):
        fim = match_paren(toks, 1)
        dentro = toks[2:fim]
        virg = [i for i, t in enumerate(dentro) if is_sym(t, ',') and V(dentro[0]) in FUNCS and i > match_paren(dentro, 1)]
        if not virg or len(dentro) != virg[0] + 2 or dentro[-1][0] != 'NUMBER':
            return None
        padrao = float(dentro[-1][1]) if '.' in dentro[-1][1] else int(dentro[-1][1])
        toks = dentro[:virg[0]] + toks[fim + 1:]
    if len(toks) < 4 or toks[0][0] not in ('IDENT', 'KEYWORD') or V(toks[0]) not in FUNCS or not is_sym(toks[1], '('):
        return None
    end = match_paren(toks, 1)
    rest = toks[end + 1:]
    op = operand = None
    if rest:
        if len(rest) != 2 or rest[0][0] != 'SYMBOL' or rest[0][1] not in ARITH or rest[1][0] != 'NUMBER':
            return None
        op, operand = rest[0][1], rest[1][1]
        operand = float(operand) if '.' in operand else int(operand)
    return V(toks[0]), toks[2:end], op, operand, padrao


def _column(arg):
    """Nome da coluna do argumento (A.B vira 'A.B'); '*' devolve '*'."""
    if len(arg) == 1 and is_sym(arg[0], '*'):
        return '*'
    return ''.join(t[1] for t in arg).upper()


def evaluate(agg, rows, value_of):
    """Valor da agregação sobre as linhas já filtradas; value_of(coluna, linha) lê a coluna."""
    func, arg, op, operand, *resto = agg
    padrao = resto[0] if resto else None
    col = _column(arg)
    if func == 'COUNT':
        vals = rows if col == '*' else [r for r in rows if value_of(col, r) is not None]
        result = len(vals)
    else:
        vals = [v for v in (value_of(col, r) for r in rows) if v is not None]
        if not vals:
            if padrao is None:
                return None
            vals = None
        result = padrao if vals is None else {'MAX': max, 'MIN': min, 'SUM': sum}.get(func, lambda x: sum(x) / len(x))(vals)
    if op is None:
        return result
    return {'+': result + operand, '-': result - operand, '*': result * operand,
            '/': (result / operand if operand else None)}[op]
