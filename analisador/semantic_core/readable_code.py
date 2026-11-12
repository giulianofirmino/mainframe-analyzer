"""Texto legível de condições e comandos COBOL, calculado só a partir de tokens (tipo, valor, linha, coluna).

Nenhum nome do código analisado aparece aqui. Regras (todas estruturais):
  * operadores por extenso viram símbolos: EQUAL [TO] -> ==, NOT EQUAL -> !=, GREATER [THAN] -> >, LESS -> <,
    NOT GREATER -> <=, NOT LESS -> >=, GREATER THAN OR EQUAL TO -> >=;
  * condição abreviada herda sujeito e operador: `A NOT EQUAL X AND Y` -> `A != X AND A != Y`;
  * três ou mais valores comparados por igualdade com OR (ou por diferença com AND) viram `IN (...)` / `NOT IN (...)`;
  * subscrito NOME(I) -> NOME[I]; referência parcial NOME(1:2) -> NOME[1:2]; DFHRESP(NORMAL) e FUNCTION x(...) mantêm parênteses;
  * nomes de campo ficam exatamente como no fonte (`X OF Y` continua `X OF Y`);
  * MOVE a TO b -> b = a; SET x TO TRUE -> x = TRUE; ADD a TO b -> b += a; COMPUTE x = e -> x = e; etc.
O Namer é mantido só como ponto de extensão: hoje devolve o nome original."""
from __future__ import annotations

FIGURATIVE = {'ZERO', 'ZEROS', 'ZEROES', 'SPACE', 'SPACES', 'LOW-VALUE', 'LOW-VALUES', 'HIGH-VALUE', 'HIGH-VALUES',
              'QUOTE', 'QUOTES', 'NULL', 'NULLS', 'TRUE', 'FALSE', 'ALL'}
ZEROS = {'ZERO', 'ZEROS', 'ZEROES'}
CLASSES = {'NUMERIC', 'ALPHABETIC', 'ALPHABETIC-LOWER', 'ALPHABETIC-UPPER', 'POSITIVE', 'NEGATIVE'}
ARITH = {'+', '-', '*', '/', '**'}


def _v(t):
    return '' if t[0] == 'STRING' else t[1].upper()


class Namer:
    """Mantém o nome do campo exatamente como está no fonte (sem separar grupo e campo por '.').

    Os parâmetros `groups` e `prefixes` são aceitos só por compatibilidade; não alteram o texto."""

    def __init__(self, groups=(), prefixes=()):
        self.groups = {g.upper() for g in groups if g}
        self.prefixes = self.groups | {g.upper() for g in prefixes if g}

    def __call__(self, name):
        return name


def _lit(t):
    """Literal como está no fonte; numérico sem sinal separado."""
    return t[1]


class _P:
    """Analisador de condição sobre tokens. Produz uma árvore ('or'|'and'|'not'|'rel'|'cls'|'bare'|'raw')."""

    def __init__(self, toks, namer):
        self.t, self.i, self.n = list(toks), 0, namer
        self.dq = False

    def lit(self, t):
        if self.dq and t[0] == 'STRING':
            q = t[1][0]
            body = t[1][1:-1].replace(q + q, q)
            return '"' + body + '"' if '"' not in body else t[1]
        return t[1]

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else None

    def take(self):
        x = self.t[self.i]
        self.i += 1
        return x

    def eat(self, *words):
        p = self.peek()
        if p and _v(p) in words:
            self.i += 1
            return True
        return False

    # ----- operandos (expressões aritméticas)
    def operand(self):
        """Uma expressão aritmética: termos ligados por + - * / **, com parênteses e subscritos."""
        parts = [self.term()]
        while True:
            p = self.peek()
            if p and p[0] == 'SYMBOL' and p[1] in ARITH and parts[-1] is not None:
                self.take()
                parts.append(p[1])
                parts.append(self.term())
            else:
                break
        return ' '.join(x for x in parts if x is not None)

    def term(self):
        p = self.peek()
        if p is None:
            return None
        if p[0] == 'SYMBOL' and p[1] in ('+', '-'):
            self.take()
            q = self.peek()
            inner = self.term() if q else ''
            return p[1] + (inner or '')
        if p[0] == 'SYMBOL' and p[1] == '(':
            j = _close(self.t, self.i)
            inner = _P(self.t[self.i + 1:j], self.n).operand()
            self.i = j + 1
            return '(' + inner + ')'
        if p[0] in ('NUMBER', 'STRING'):
            self.take()
            return self.lit(p)
        if p[0] in ('IDENT', 'KEYWORD'):
            self.take()
            name = p[1]
            if _v(p) == 'FUNCTION' and self.peek() and self.peek()[0] in ('IDENT', 'KEYWORD'):
                name = 'FUNCTION ' + self.take()[1]
            elif _v(p) == 'LENGTH' and self.peek() and _v(self.peek()) == 'OF':
                self.take()
                return 'LENGTH OF ' + (self.term() or '')
            elif _v(p) in ('ADDRESS',) and self.peek() and _v(self.peek()) == 'OF':
                self.take()
                return 'ADDRESS OF ' + (self.term() or '')
            # qualificação X OF Y [OF Z]: mantida como está no fonte
            quals = [name]
            while self.peek() and _v(self.peek()) in ('OF', 'IN') and self.peek(1) and self.peek(1)[0] in ('IDENT', 'KEYWORD'):
                self.take()
                quals.append(self.take()[1])
            if len(quals) > 1:
                name = ' OF '.join(self.n(q) for q in quals)
            elif name in FIGURATIVE or _v(p) in FIGURATIVE:
                name = name.upper() if _v(p) in FIGURATIVE else name
            else:
                name = self.n(name)
            q = self.peek()
            if q and q[0] == 'SYMBOL' and q[1] == '(':
                j = _close(self.t, self.i)
                args = self.t[self.i + 1:j]
                self.i = j + 1
                call = _v(p) == 'DFHRESP' or name.startswith('FUNCTION ')
                if call:
                    inner = ', '.join(_P(a, self.n).operand() for a in _split(args, lambda x: x[0] == 'SYMBOL' and x[1] == ',')) if any(x[0] == 'SYMBOL' and x[1] == ',' for x in args) else ' '.join(_lit(a) if a[0] != 'IDENT' else self.n(a[1]) for a in args)
                    return f'{name}({inner})'
                return name + '[' + _subscript(args, self.n) + ']'
            return name
        self.take()
        return p[1]

    # ----- condições
    def relop(self):
        """Lê o operador relacional (com IS/NOT/TO/THAN); devolve símbolo ou None."""
        save = self.i
        self.eat('IS')
        neg = self.eat('NOT')
        p = self.peek()
        if p is None:
            self.i = save
            return None
        v = _v(p)
        op = None
        if p[0] == 'SYMBOL' and p[1] in ('=', '>', '<', '>=', '<=', '<>'):
            self.take()
            op = {'=': '==', '<>': '!='}.get(p[1], p[1])
        elif v == 'EQUAL':
            self.take()
            self.eat('TO')
            op = '=='
        elif v in ('GREATER', 'LESS'):
            self.take()
            self.eat('THAN')
            op = '>' if v == 'GREATER' else '<'
            if self.peek() and _v(self.peek()) == 'OR' and self.peek(1) and _v(self.peek(1)) == 'EQUAL':
                self.take(); self.take(); self.eat('TO')
                op = '>=' if v == 'GREATER' else '<='
        elif v in CLASSES:
            self.take()
            return ('cls', v, neg)
        else:
            self.i = save
            return None
        if neg:
            op = {'==': '!=', '!=': '==', '>': '<=', '<': '>=', '>=': '<', '<=': '>'}[op]
        return ('op', op)

    def or_expr(self):
        items = [self.and_expr()]
        while self.peek() and _v(self.peek()) == 'OR':
            self.take()
            items.append(self.and_expr(prev=items[-1]))
        return items[0] if len(items) == 1 else ('or', items)

    def and_expr(self, prev=None):
        items = [self.unary(prev)]
        while self.peek() and _v(self.peek()) == 'AND':
            self.take()
            items.append(self.unary(items[-1]))
        return items[0] if len(items) == 1 else ('and', items)

    def unary(self, prev=None):
        p = self.peek()
        if p is None:
            return ('raw', '')
        if _v(p) == 'NOT':
            self.take()
            return ('not', self.unary(prev))
        if p[0] == 'SYMBOL' and p[1] == '(':
            j = _close(self.t, self.i)
            inner = self.t[self.i + 1:j]
            if _is_condition(inner):
                self.i = j + 1
                return ('group', _P(inner, self.n).or_expr())
        return self.rel(prev)

    def rel(self, prev):
        last = _last_rel(prev)
        p = self.peek()
        # abreviada: começa por operador ou por valor sem sujeito
        if last and p is not None:
            save = self.i
            op = self.relop()
            if op and op[0] == 'op':
                return ('rel', last[1], op[1], self.operand())
            self.i = save
            if _valuelike(p):
                rhs = self.operand()
                return ('rel', last[1], last[2], rhs)
        left = self.operand()
        op = self.relop()
        if op is None:
            return ('bare', left)
        if op[0] == 'cls':
            return ('cls', left, op[1], op[2])
        return ('rel', left, op[1], self.operand())


def _close(toks, i):
    d = 0
    for j in range(i, len(toks)):
        if toks[j][0] == 'SYMBOL' and toks[j][1] == '(':
            d += 1
        elif toks[j][0] == 'SYMBOL' and toks[j][1] == ')':
            d -= 1
            if d == 0:
                return j
    return len(toks) - 1


def _split(toks, pred):
    out, cur, d = [], [], 0
    for t in toks:
        if t[0] == 'SYMBOL' and t[1] == '(':
            d += 1
        elif t[0] == 'SYMBOL' and t[1] == ')':
            d -= 1
        if d == 0 and pred(t):
            out.append(cur)
            cur = []
        else:
            cur.append(t)
    out.append(cur)
    return out


def _subscript(args, namer):
    """Conteúdo de NOME(...): subscritos separados por espaço/vírgula ou referência parcial com ':'."""
    if any(t[0] == 'SYMBOL' and t[1] == ':' for t in args):
        a, b = _split(args, lambda t: t[0] == 'SYMBOL' and t[1] == ':')[:2]
        return _P(a, namer).operand() + ':' + (_P(b, namer).operand() if b else '')
    groups, cur = [], []
    for t in args:
        if t[0] == 'SYMBOL' and t[1] == ',':
            groups.append(cur)
            cur = []
            continue
        # cada IDENT/NUMBER sem operador entre eles é um subscrito próprio
        if cur and not (cur[-1][0] == 'SYMBOL' and cur[-1][1] in ARITH) and not (t[0] == 'SYMBOL' and t[1] in ARITH):
            groups.append(cur)
            cur = []
        cur.append(t)
    groups.append(cur)
    return ', '.join(_P(g, namer).operand() for g in groups if g)


def _valuelike(t):
    return t[0] in ('NUMBER', 'STRING') or (t[0] == 'SYMBOL' and t[1] in ('+', '-')) or _v(t) in FIGURATIVE


def _is_condition(toks):
    for t in toks:
        if _v(t) in ('AND', 'OR', 'NOT', 'EQUAL', 'GREATER', 'LESS') or (t[0] == 'SYMBOL' and t[1] in ('=', '>', '<', '>=', '<=', '<>')) or _v(t) in CLASSES:
            return True
    return False


def _last_rel(node):
    """Último 'rel' de uma expressão já lida (sujeito e operador para a condição abreviada)."""
    if node is None:
        return None
    if node[0] == 'rel':
        return node
    if node[0] in ('and', 'or'):
        return _last_rel(node[1][-1])
    if node[0] == 'group':
        return _last_rel(node[1])
    return None


# ----------------------------------------------------------------------------- texto da condição
def _in_value(v):
    return '0' if v.upper() in ZEROS else v


def _render(node, top=True):
    k = node[0]
    if k == 'rel':
        return f'{node[1]} {node[2]} {node[3]}'
    if k == 'cls':
        return f'{node[1]} IS {"NOT " if node[3] else ""}{node[2]}'
    if k == 'bare':
        return node[1]
    if k == 'raw':
        return node[1]
    if k == 'group':
        if node[1][0] not in ('and', 'or'):
            return _render(node[1])
        return '(' + _render(node[1]) + ')'
    if k == 'not':
        inner = _render(node[1], False)
        return 'NOT ' + (f'({inner})' if node[1][0] in ('and', 'or') else inner)
    if k in ('and', 'or'):
        eq = '==' if k == 'or' else '!='
        out, i, items = [], 0, node[1]
        while i < len(items):
            it = items[i]
            if it[0] == 'rel' and it[2] == eq:
                j = i
                while j < len(items) and items[j][0] == 'rel' and items[j][2] == eq and items[j][1] == it[1]:
                    j += 1
                if j - i >= 3:
                    vals = ', '.join(_in_value(x[3]) for x in items[i:j])
                    out.append(f'{it[1]} {"IN" if k == "or" else "NOT IN"} ({vals})')
                    i = j
                    continue
            out.append(_render(it, False))
            i += 1
        return f' {k.upper()} '.join(out)
    return ''


def condition_text(tokens, namer=None):
    """Condição em forma legível a partir dos tokens (condition_tokens do IF, ou WHEN)."""
    n = namer or Namer()
    p = _P(tokens, n)
    node = p.or_expr()
    while node[0] == 'group':
        node = node[1]
    text = _render(node)
    rest = p.t[p.i:]
    if rest:  # sobra não reconhecida: mantém legível em vez de perder
        text += ' ' + ' '.join(_lit(t) for t in rest)
    return text


def evaluate_when_text(subject_tokens, when_tokens, namer=None):
    """Condição de um WHEN de EVALUATE como expressão de IF (ver evaluate_group_text)."""
    return evaluate_group_text(subject_tokens, [when_tokens], namer)


def evaluate_group_text(subject_tokens, whens, namer=None):
    """Condição de um ou mais WHEN empilhados (mesmo corpo) de um EVALUATE, como expressão de IF:
    sujeito TRUE -> a própria condição (condição-nome vira `X == TRUE`); outro sujeito -> `sujeito == valor`,
    e três ou mais valores viram `sujeito IN (...)`."""
    n = namer or Namer()
    whens = [w for w in whens if w]
    if len(subject_tokens) == 1 and _v(subject_tokens[0]) in ('TRUE', 'FALSE'):
        neg = _v(subject_tokens[0]) == 'FALSE'
        outs = []
        for w in whens:
            node = _P(w, n).or_expr()
            text = condition_text(w, n)
            outs.append(f'{text} == {"FALSE" if neg else "TRUE"}' if node[0] == 'bare' else (f'NOT ({text})' if neg else text))
        return ' OR '.join(outs)
    subj = _P(subject_tokens, n).operand()
    vals = []
    for w in whens:
        for pt in _split(w, lambda t: _v(t) == 'OR'):
            pp = _P(pt, n)
            a = pp.operand()
            if pp.peek() and _v(pp.peek()) in ('THRU', 'THROUGH'):
                pp.take()
                vals.append(('range', a, pp.operand()))
            else:
                vals.append(('v', a))
    if len(vals) >= 3 and all(v[0] == 'v' for v in vals):
        return f'{subj} IN (' + ', '.join(_in_value(v[1]) for v in vals) + ')'
    return ' OR '.join(f'{subj} == {v[1]}' if v[0] == 'v' else f'{subj} BETWEEN {v[1]} AND {v[2]}' for v in vals)


# ----------------------------------------------------------------------------- comandos
def _terms(toks, n, dq=True):
    """Lista de operandos simples (destinos/origens) de uma sequência de tokens."""
    p = _P(toks, n)
    p.dq = dq
    out = []
    while p.peek():
        if p.peek()[0] == 'SYMBOL' and p.peek()[1] == ',':
            p.take()
            continue
        out.append(p.operand())
    return out


def _expr(toks, n):
    p = _P(toks, n)
    p.dq = True
    return p.operand()


def _clean(toks):
    return [t for t in toks if _v(t) not in ('ROUNDED',)]


def _cut(toks, *words):
    """Divide os tokens no primeiro token (fora de parênteses) cujo valor é uma das palavras; devolve (antes, palavra, depois)."""
    d = 0
    for i, t in enumerate(toks):
        if t[0] == 'SYMBOL' and t[1] == '(':
            d += 1
        elif t[0] == 'SYMBOL' and t[1] == ')':
            d -= 1
        elif d == 0 and _v(t) in words:
            return toks[:i], _v(t), toks[i + 1:]
    return toks, None, []


def _sum(terms):
    return ' + '.join(terms)


def _generic(toks, n):
    p = _P(toks, n)
    p.dq = True
    out = []
    while p.peek():
        t = p.peek()
        if t[0] in ('IDENT', 'NUMBER', 'STRING') or (t[0] == 'SYMBOL' and t[1] == '('):
            out.append(p.term())
        else:
            out.append(p.take()[1])
    return ' '.join(out)


def _cics(toks, n):
    out, i = [], 0
    while i < len(toks):
        t = toks[i]
        if t[0] in ('IDENT', 'KEYWORD') and i + 1 < len(toks) and toks[i + 1][0] == 'SYMBOL' and toks[i + 1][1] == '(':
            j = _close(toks, i + 1)
            inner = toks[i + 2:j]
            out.append(f'{t[1]}({_expr(inner, n) if inner else ""})')
            i = j + 1
        else:
            out.append(_expr([t], n) if t[0] == 'STRING' else t[1])
            i += 1
    return ' '.join(out)


def _sql_join(toks):
    """Texto do comando SQL a partir dos tokens: uma palavra por token; sem espaço em volta de '.', depois de '(' e ':' nem antes de ')' e ','."""
    out, prev = '', None
    for t in toks:
        v = t[1] if t[0] != 'STRING' else '"' + t[1].strip('\'"') + '"' if False else t[1]
        if prev is not None and not (v in ('.', ')', ',') or prev in ('.', '(', ':')):
            out += ' '
        out += v
        prev = v
    return out


def statement_lines(node, namer=None):
    """Um ou mais comandos legíveis (uma linha por atribuição/efeito) de um nó de comando da AST."""
    n = namer or Namer()
    ty = node.get('type')
    toks = node.get('arg_tokens') or []
    if ty == 'EXEC_SQL':
        return ['SQL ' + (_sql_join(node['tokens']) if node.get('tokens') else ' '.join(str(node.get('sql') or '').split()))]
    if ty == 'EXEC_CICS':
        return ['CICS ' + _cics(node.get('tokens') or [], n)] if node.get('tokens') else ['CICS ' + ' '.join(str(node.get('command') or '').split())]
    if ty == 'PERFORM':
        return ['PERFORM ' + perform_text(node, n)]
    if ty == 'MOVE':
        head = toks[0] if toks else None
        corr = head is not None and _v(head) in ('CORR', 'CORRESPONDING')
        src, w, dst = _cut(toks[1:] if corr else toks, 'TO')
        if w and src and dst:
            s = _expr(src, n)
            return [f'{d} = {s}' + (' (CORRESPONDING)' if corr else '') for d in _terms(dst, n)]
    elif ty == 'SET':
        a, w, b = _cut(toks, 'TO', 'UP', 'DOWN')
        if w == 'TO' and a and b:
            v = _expr(b, n)
            return [f'{d} = {v}' for d in _terms(a, n)]
        if w in ('UP', 'DOWN') and b and _v(b[0]) == 'BY':
            v = _expr(b[1:], n)
            return [f'{d} {"+=" if w == "UP" else "-="} {v}' for d in _terms(a, n)]
    elif ty == 'COMPUTE':
        a, w, b = _cut(_clean(toks), '=')
        if w == '=' and a and b:
            e = _expr(b, n)
            return [f'{d} = {e}' for d in _terms(a, n)]
    elif ty == 'ADD':
        a, w, b = _cut(_clean(toks), 'TO', 'GIVING')
        if w == 'TO' and a and b:
            b, w2, g = _cut(b, 'GIVING')
            if w2 and g:
                return [f'{d} = {_sum(_terms(a, n))} + {_sum(_terms(b, n))}' for d in _terms(g, n)]
            s = _sum(_terms(a, n))
            return [f'{d} += {s}' for d in _terms(b, n)]
        if w == 'GIVING' and a and b:
            return [f'{d} = {_sum(_terms(a, n))}' for d in _terms(b, n)]
    elif ty == 'SUBTRACT':
        a, w, b = _cut(_clean(toks), 'FROM')
        if w and a and b:
            b, w2, g = _cut(b, 'GIVING')
            s = _sum(_terms(a, n))
            if w2 and g:
                base = _terms(b, n)[0] if b else ''
                return [f'{d} = {base} - ({s})' if len(_terms(a, n)) > 1 else f'{d} = {base} - {s}' for d in _terms(g, n)]
            return [f'{d} -= {s}' for d in _terms(b, n)]
    elif ty == 'MULTIPLY':
        a, w, b = _cut(_clean(toks), 'BY')
        if w and a and b:
            b, w2, g = _cut(b, 'GIVING')
            x = _expr(a, n)
            if w2 and g:
                return [f'{d} = {x} * {_expr(b, n)}' for d in _terms(g, n)]
            return [f'{d} *= {x}' for d in _terms(b, n)]
    elif ty == 'DIVIDE':
        a, w, b = _cut(_clean(toks), 'INTO', 'BY')
        if w and a and b:
            b, w2, g = _cut(b, 'GIVING')
            g, w3, r = _cut(g, 'REMAINDER')
            x = _expr(a, n)
            if w2 and g:
                y = _expr(b, n)
                expr = f'{y} / {x}' if w == 'INTO' else f'{x} / {y}'
                lines = [f'{d} = {expr}' for d in _terms(g, n)]
                if w3 and r:
                    lines.append(f'{_terms(r, n)[0]} = {y} % {x}' if w == 'INTO' else f'{_terms(r, n)[0]} = {x} % {y}')
                return lines
            if not w2:
                b2, w3, r = _cut(b, 'REMAINDER')
                return [f'{d} /= {x}' for d in _terms(b2, n)]
    elif ty in ('GOBACK', 'EXIT', 'CONTINUE', 'STOP'):
        return [ty + (' ' + _generic(toks, n) if toks else '')]
    text = _generic(toks, n) if toks else ' '.join(str(node.get('args') or node.get('header') or '').split())
    return [f'{ty.replace("_", " ")} {text}'.strip()]


def perform_text(node, namer=None):
    """PERFORM legível: alvo [THRU alvo] [n TIMES] [UNTIL condição] (o corpo de PERFORM em linha é tratado pelo chamador)."""
    n = namer or Namer()
    toks = node.get('header_tokens') or []
    a, w, b = _cut(toks, 'UNTIL')
    text = _generic(a, n) if a else ''
    if w:
        text = (text + ' ' if text else '') + 'UNTIL ' + condition_text(b, n)
    return text.strip()
