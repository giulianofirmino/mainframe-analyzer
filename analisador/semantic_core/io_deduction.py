"""Dedução das entradas e saídas usadas pelo código quando falta o copybook que as declara.

Trabalha sobre os TOKENS do analisador léxico: o parser guarda em cada nó da AST os tokens que ele
consumiu (arg_tokens, condition_tokens, header_tokens, subject_tokens, tokens de EXEC SQL/CICS), e aqui
identificadores, literais, qualificação (X OF Y), subscritos, host variables e variáveis indicadoras
saem da sequência de tokens, sem reler texto.

Para cada programa levanta o que é lido e o que é escrito (IF/EVALUATE, MOVE, aritmética, SET, PERFORM,
CALL, EXEC CICS, EXEC SQL, I/O de arquivo...). Nome usado no código e não declarado no fonte expandido
(nem em copybook/DCLGEN presente) é um campo "sem declaração": o tipo é deduzido pelo uso, o copybook
ausente é atribuído pelo qualificador (ESTRUTURA.CAMPO), pelo prefixo do nome, por ser o único ausente do
programa, ou apontado como candidato.
"""
from __future__ import annotations

from collections import defaultdict

from token_utils import V, is_sym, match_paren, split_top, find, strip_outer

FIG_NUM = {'ZERO', 'ZEROS', 'ZEROES'}
FIG_STR = {'SPACE', 'SPACES', 'LOW-VALUE', 'LOW-VALUES', 'HIGH-VALUE', 'HIGH-VALUES', 'QUOTE', 'QUOTES', 'NULL', 'NULLS'}

# Palavras que o léxico devolve como IDENT mas que não são nomes de dados.
RESERVED = set("""ACCEPT ALPHABETIC ALPHANUMERIC ALSO ANY ARE AFTER BEFORE CANCEL CHARACTERS CONTENT CORR CORRESPONDING
DELIMITED DELIMITER DIVISION EQUAL EQUALS EXCEPTION FIRST FUNCTION GREATER INITIAL LEADING LESS LINE NEGATIVE NO NUMERIC
OF OTHER POINTER POSITIVE PROCEDURE REFERENCE REMAINDER REPLACING RETURNING ROUNDED SENTENCE SORT SPACE SPACES TALLYING
TEST THAN THEN UPON VALUES WORKING-STORAGE CURRENT TIMESTAMP DATE TIME OF IN
END-ADD END-CALL END-COMPUTE END-DIVIDE END-MULTIPLY END-STRING END-SUBTRACT END-UNSTRING END-RETURN END-ACCEPT END-DISPLAY""".split()) | FIG_NUM | FIG_STR

RUNTIME_NAMES = {'SQLCA', 'SQLDA', 'RETURN-CODE', 'SORT-RETURN', 'TALLY', 'DFHCOMMAREA', 'SQLCODE', 'SQLSTATE', 'SQLERRD',
                 'SQLERRMC', 'SQLERRML', 'SQLCAID', 'SQLCABC', 'SQLERRP', 'SQLTEXT', 'SQLEXT'}
NUM_SQL = {'DECIMAL', 'SMALLINT', 'INTEGER', 'BIGINT', 'REAL', 'FLOAT', 'DOUBLE', 'DECFLOAT'}
CICS_NUM_KEYS = {'LENGTH', 'FLENGTH', 'ITEM', 'NUMITEMS', 'RESP', 'RESP2', 'KEYLENGTH', 'ABSTIME', 'INTERVAL', 'NUMREC'}
CICS_WRITE_KEYS = {'INTO', 'SET', 'RESP', 'RESP2', 'NUMITEMS', 'NUMREC'}
FORMATTIME_WRITE = {'DATE', 'TIME', 'YYYYMMDD', 'DDMMYYYY', 'MMDDYYYY', 'YYYYDDD', 'YYDDD', 'YYMMDD', 'DDMMYY', 'MMDDYY',
                    'DAYOFWEEK', 'DAYOFMONTH', 'MONTHOFYEAR', 'YEAR', 'DAYCOUNT', 'MILLISECONDS'}
REL_SYMBOLS = ('=', '>', '<', '>=', '<=', '<>', '!=')
FILE_NODES = {'FILE_OPEN', 'FILE_CLOSE', 'FILE_READ', 'FILE_WRITE', 'FILE_REWRITE', 'FILE_DELETE', 'FILE_START'}

DEFAULTS = {'num': 0, 'str': ' ', 'flag': False, None: None}
TYPE_NAME = {'num': 'NUMERIC', 'str': 'ALPHANUMERIC', 'flag': 'CONDITION_88', None: None}


def is_runtime_name(n):
    return n in RUNTIME_NAMES or n.startswith(('EIB', 'DFH', 'SQLWARN', 'SQLERR'))


def resolve_tags(tags):
    tags = set(tags)
    if 'flag' in tags and not (tags & {'num', 'str', 'arith', 'sub'}):
        return 'flag'
    if tags & {'arith', 'sub'}:
        return 'num'
    if 'str' in tags:
        return 'str'
    if tags & {'num', 'numtest'}:
        return 'num'
    if 'flag' in tags:
        return 'flag'
    return None


def column_categories(dclgen):
    """coluna -> ('num'|'str', [tabelas]) somente quando todas as DCLGEN concordam."""
    seen = defaultdict(set)
    for m in (dclgen or {}).get('members', {}).values():
        for c in m.get('columns', []):
            seen[c['name']].add(('num' if c['sql_type'] in NUM_SQL else 'str', m.get('table')))
    return {k: (next(iter({c for c, _ in v})), sorted({t for _, t in v})) for k, v in seen.items() if len({c for c, _ in v}) == 1}


# --------------------------------------------------------------------------- #
# Comparações COBOL em forma de frase (IS NOT EQUAL TO, GREATER THAN OR EQUAL TO...) sobre tokens
# --------------------------------------------------------------------------- #
def _op_at(vals, i):
    """Frase de comparação COBOL a partir de i: devolve (operador, próximo índice) ou None."""
    j = i

    def take(*ws):
        nonlocal j
        if j < len(vals) and vals[j] in ws:
            j += 1
            return True
        return False

    take('IS')
    neg = take('NOT')
    if take('EQUAL', 'EQUALS'):
        take('TO')
        return ('!=' if neg else '='), j
    for word, plain, orequal, notplain, notorequal in (('GREATER', '>', '>=', '<=', '<'), ('LESS', '<', '<=', '>=', '>')):
        if take(word):
            take('THAN')
            k = j
            if take('OR') and take('EQUAL', 'EQUALS'):
                take('TO')
                return (notorequal if neg else orequal), j
            j = k
            return (notplain if neg else plain), j
    if take('NUMERIC'):
        return ('NOT_NUMERIC' if neg else 'NUMERIC'), j
    return None


def normalize_ops(toks):
    """Frases como IS NOT EQUAL TO / GREATER THAN OR EQUAL TO viram um único token ('OP', operador, linha, coluna)."""
    vals = [V(t) for t in toks]
    out, i = [], 0
    while i < len(toks):
        t = toks[i]
        if t[0] == 'SYMBOL' and t[1] in REL_SYMBOLS:
            out.append(('OP', t[1], t[2], t[3]))
            i += 1
            continue
        if vals[i] in ('IS', 'NOT', 'EQUAL', 'EQUALS', 'GREATER', 'LESS', 'NUMERIC'):
            r = _op_at(vals, i)
            if r:
                out.append(('OP', r[0], t[2], t[3]))
                i = r[1]
                continue
        out.append(t)
        i += 1
    return out


def _is_op(t, ops=None):
    return t[0] == 'OP' and (ops is None or t[1] in ops)


# --------------------------------------------------------------------------- #
class _Analyzer:
    def __init__(self, dm, labels, colcat, linemap):
        self.dm, self.labels, self.colcat, self.lm = dm, labels, colcat, linemap
        self.reads, self.writes = defaultdict(set), defaultdict(set)
        self.tags, self.evid, self.quals = defaultdict(set), defaultdict(list), defaultdict(set)
        self.links = []

    def L(self, line):
        return (self.lm.source_line(line) or line) if self.lm else line

    def note(self, name, tag, line, why=None):
        self.tags[name].add(tag)
        if why and len(self.evid[name]) < 4:
            e = f'L{self.L(line)}: {why}'
            if e not in self.evid[name]:
                self.evid[name].append(e)

    def read(self, r, tag=None, why=None):
        self.reads[r['n']].add(r['line'])
        self.quals[r['n']].update(r['quals'])
        if tag:
            self.note(r['n'], tag, r['line'], why)

    def write(self, r, tag=None, why=None):
        self.writes[r['n']].add(r['line'])
        self.quals[r['n']].update(r['quals'])
        if tag:
            self.note(r['n'], tag, r['line'], why)

    # ---- referências a dados (a partir dos tokens) ----------------------------
    def refs(self, toks):
        out, i, n = [], 0, len(toks)
        while i < n:
            t = toks[i]
            v = V(t)
            if v in ('LENGTH', 'ADDRESS') and i + 1 < n and V(toks[i + 1]) == 'OF':
                i += 2
                continue
            if t[0] == 'IDENT' and v in ('DFHRESP', 'DFHVALUE'):
                i = (match_paren(toks, i + 1) + 1) if i + 1 < n and is_sym(toks[i + 1], '(') else i + 1
                continue
            if t[0] != 'IDENT' or v in RESERVED or v in self.labels:
                i += 1
                continue
            quals, j = [], i + 1
            while j + 1 < n and V(toks[j]) in ('OF', 'IN') and toks[j + 1][0] == 'IDENT':
                quals.append(V(toks[j + 1]))
                j += 2
            if j < n and is_sym(toks[j], '('):
                e = match_paren(toks, j)
                for st in toks[j + 1:e]:
                    if st[0] == 'IDENT' and V(st) not in RESERVED and V(st) not in self.labels:
                        self.read({'n': V(st), 'quals': [], 'line': st[2]}, 'sub', 'usado como subscrito/refmod')
                j = e + 1
            out.append({'n': v, 'quals': quals, 'line': t[2]})
            i = j
        return out

    def side(self, toks):
        """Operando: literal, referência única ou expressão. Devolve (tipo, detalhe, texto, linha)."""
        toks = strip_outer(list(toks))
        if not toks:
            return ('empty', None, '', 0)
        text = ' '.join(t[1] for t in toks)
        line = toks[0][2]
        v0 = V(toks[0])
        if len(toks) == 1 and toks[0][0] == 'STRING':
            return ('lit', 'str', text, line)
        if len(toks) == 1 and toks[0][0] == 'NUMBER':
            return ('lit', 'num', text, line)
        if len(toks) == 2 and is_sym(toks[0]) and toks[0][1] in ('+', '-') and toks[1][0] == 'NUMBER':
            return ('lit', 'num', text, line)
        if len(toks) == 1 and v0 in FIG_NUM:
            return ('lit', 'num', text, line)
        if len(toks) == 1 and v0 in FIG_STR:
            return ('lit', 'str', text, line)
        if v0 == 'ALL' and len(toks) >= 2 and (toks[1][0] == 'STRING' or V(toks[1]) in FIG_STR):
            return ('lit', 'str', text, line)
        if v0 in ('DFHRESP', 'DFHVALUE'):
            return ('lit', 'num', text, line)
        rs = self.refs(toks)
        arith = any(is_sym(t) and t[1] in ('+', '-', '*', '/', '**') and i > 0 and not is_sym(toks[i - 1], '(')
                    for i, t in enumerate(toks))
        for r in rs:
            self.read(r, 'arith' if arith else None, 'operando de expressão aritmética' if arith else None)
        if len(rs) == 1 and not arith:
            return ('ref', rs[0], text, line)
        return ('expr', rs, text, line)

    def pair(self, ka, kb, verb):
        for x, y in ((ka, kb), (kb, ka)):
            if x[0] == 'ref':
                if y[0] == 'lit':
                    self.note(x[1]['n'], y[1], y[3], f'{verb} {y[2]}')
                elif y[0] == 'ref':
                    self.links.append((x[1]['n'], y[1]['n']))

    # ---- condições ------------------------------------------------------------
    def cond(self, toks, normalized=False):
        toks = list(toks)
        if not normalized:
            toks = normalize_ops(toks)
        toks = strip_outer(toks)
        if not toks:
            return
        if toks[0][0] == 'KEYWORD' and V(toks[0]) == 'NOT':
            return self.cond(toks[1:], True)
        for word in ('OR', 'AND'):
            ps = split_top(toks, lambda t, w=word: t[0] == 'KEYWORD' and V(t) == w)
            if len(ps) > 1:
                k = next((i for i, t in enumerate(ps[0]) if _is_op(t, REL_SYMBOLS)), -1)
                if k >= 0:  # relação abreviada: X = A OR B  ->  X = A OR X = B
                    lhs, op = ps[0][:k], ps[0][k]
                    ps = [ps[0]] + [(lhs + [op] + p) if not any(_is_op(t) for t in p) else p for p in ps[1:]]
                for p in ps:
                    self.cond(p, True)
                return
        if _is_op(toks[-1], ('NUMERIC', 'NOT_NUMERIC')):
            for r in self.refs(toks[:-1]):
                self.read(r, 'numtest', 'testado com NUMERIC')
            return
        k = next((i for i, t in enumerate(toks) if _is_op(t, REL_SYMBOLS)), -1)
        if k >= 0:
            self.pair(self.side(toks[:k]), self.side(toks[k + 1:]), 'comparado com')
            return
        s = self.side(toks)
        if s[0] == 'ref':
            self.read(s[1], 'flag', 'usado como condição (nome de condição 88)')

    def evaluate(self, n):
        subj = list(n.get('subject_tokens') or [])
        sv = [V(t) for t in subj]
        is_bool = len(subj) == 1 and sv and sv[0] in ('TRUE', 'FALSE')
        also = 'ALSO' in sv
        sk = None
        if also:
            for part in split_top(subj, lambda t: V(t) == 'ALSO'):
                self.side(part)
        elif subj and not is_bool:
            sk = self.side(subj)
        for w in n.get('whens') or []:
            c = list(w.get('condition_tokens') or [])
            if not c or (len(c) == 1 and V(c[0]) == 'OTHER'):
                continue
            if is_bool:
                self.cond(c)
            else:
                for piece in split_top(c, lambda t: V(t) in ('THRU', 'THROUGH', 'ALSO')):
                    kb = self.side(piece)
                    if sk:
                        self.pair(sk, kb, 'EVALUATE contra')

    # ---- comandos -------------------------------------------------------------
    def stmt(self, n):
        t = n['type']
        a = list(n.get('arg_tokens') or [])
        if t == 'IF':
            self.cond(n.get('condition_tokens') or [])
        elif t == 'EVALUATE':
            self.evaluate(n)
        elif t == 'SEARCH':
            for r in self.refs(n.get('subject_tokens') or []):
                self.read(r)
            for w in n.get('whens') or []:
                self.cond(w.get('condition_tokens') or [])
        elif t == 'PERFORM':
            self.perform(list(n.get('header_tokens') or []))
        elif t == 'MOVE':
            self.move(a)
        elif t == 'INITIALIZE':
            i = find(a, ('REPLACING',))
            for r in self.refs(a if i < 0 else a[:i]):
                self.write(r)
        elif t == 'COMPUTE':
            i = next((k for k, x in enumerate(a) if is_sym(x, '=')), -1)
            if i >= 0:
                for r in self.refs(a[:i]):
                    self.write(r, 'arith', 'resultado de COMPUTE')
                for r in self.refs(a[i + 1:]):
                    self.read(r, 'arith', 'operando de COMPUTE')
        elif t in ('ADD', 'SUBTRACT', 'MULTIPLY', 'DIVIDE'):
            self.arith(t, a)
        elif t == 'SET':
            self.set_(a)
        elif t == 'CALL':
            self.call(a)
        elif t == 'EXEC_CICS':
            self.cics(list(n.get('tokens') or []))
        elif t == 'EXEC_SQL':
            self.sql(list(n.get('tokens') or []))
        elif t in FILE_NODES:
            self.fileio(a)
        elif t == 'STRING':
            i = find(a, ('INTO',))
            for r in self.refs(a if i < 0 else a[:i]):
                self.read(r)
            if i >= 0:
                for k, r in enumerate(self.refs(a[i + 1:])):
                    (self.write if k == 0 else self.read)(r)
        elif t == 'UNSTRING':
            i = find(a, ('INTO',))
            rs = self.refs(a if i < 0 else a[:i])
            if rs:
                self.read(rs[0])
            if i >= 0:
                for r in self.refs(a[i + 1:]):
                    self.write(r)
        elif t == 'INSPECT':
            for k, r in enumerate(self.refs(a)):
                self.read(r)
                if k == 0:
                    self.write(r)
        elif t in ('DISPLAY', 'GO', 'GOTO'):
            for r in self.refs(a):
                self.read(r, 'num' if t != 'DISPLAY' else None, 'índice de GO TO DEPENDING' if t != 'DISPLAY' else None)
        elif t == 'ACCEPT':
            for r in self.refs(a):
                self.write(r)

    def move(self, a):
        if a and V(a[0]) in ('CORRESPONDING', 'CORR'):
            a = a[1:]
        i = find(a, ('TO',))
        if i < 0:
            return
        sk = self.side(a[:i])
        for r in self.refs(a[i + 1:]):
            self.write(r)
            if sk[0] == 'lit':
                self.note(r['n'], sk[1], r['line'], f'recebe {sk[2]}')
            elif sk[0] == 'ref':
                self.links.append((r['n'], sk[1]['n']))

    def arith(self, verb, a):
        g = find(a, ('GIVING',))
        before, giving = (a, []) if g < 0 else (a[:g], a[g + 1:])
        kw = {'ADD': 'TO', 'SUBTRACT': 'FROM', 'MULTIPLY': 'BY', 'DIVIDE': 'INTO'}[verb]
        i = find(before, (kw,))
        if i < 0 and verb == 'DIVIDE':
            i = find(before, ('BY',))
        operands, targets = (before[:i], before[i + 1:]) if i >= 0 else (before, [])
        for r in self.refs(operands):
            self.read(r, 'arith', f'operando de {verb}')
        for r in self.refs(targets):
            self.read(r, 'arith', f'{verb} (acumulador)')
            if g < 0:
                self.write(r, 'arith', f'resultado de {verb}')
        for r in self.refs(giving):
            self.write(r, 'arith', f'GIVING de {verb}')

    def set_(self, a):
        up = find(a, ('UP', 'DOWN'))
        if up >= 0:
            for r in self.refs(a[:up]):
                self.read(r, 'arith', 'índice ajustado por SET UP/DOWN BY')
                self.write(r, 'arith')
            b = find(a, ('BY',), up)
            if b >= 0:
                self.side(a[b + 1:])
            return
        i = find(a, ('TO',))
        if i < 0:
            return
        rhs = a[i + 1:]
        if len(rhs) == 1 and V(rhs[0]) in ('TRUE', 'FALSE'):
            for r in self.refs(a[:i]):
                self.write(r, 'flag', f'SET ... TO {V(rhs[0])} (nome de condição 88)')
            return
        sk = self.side(rhs)
        for r in self.refs(a[:i]):
            self.write(r)
            if sk[0] == 'lit':
                self.note(r['n'], sk[1], r['line'], f'SET recebe {sk[2]}')

    def perform(self, h):
        if not h:
            return
        vals = [V(t) for t in h]
        if 'VARYING' in vals:
            v = vals.index('VARYING')
            f = find(h, ('FROM',), v)
            b = find(h, ('BY',), f) if f >= 0 else -1
            u = find(h, ('UNTIL',), b) if b >= 0 else -1
            if f >= 0 and b >= 0 and u >= 0:
                for r in self.refs(h[v + 1:f]):
                    self.write(r, 'arith', 'variável de PERFORM VARYING')
                    self.read(r)
                for x in (h[f + 1:b], h[b + 1:u]):
                    k = self.side(x)
                    if k[0] == 'ref':
                        self.note(k[1]['n'], 'arith', k[3], 'início/passo de PERFORM VARYING')
                self.cond(h[u + 1:])
                return
        u = find(h, ('UNTIL',))
        if u >= 0:
            self.cond(h[u + 1:])
            h = h[:u]
        t = find(h, ('TIMES',))
        if t >= 0:
            head = h[:t]
            if head and V(head[0]) in self.labels:
                head = head[1:]
                th = find(head, ('THRU', 'THROUGH'))
                if th >= 0:
                    head = head[th + 2:]
            for r in self.refs(head):
                self.read(r, 'arith', 'quantidade de PERFORM ... TIMES')

    def call(self, a):
        if not a:
            return
        u = find(a, ('USING',))
        head = a if u < 0 else a[:u]
        if not (len(head) == 1 and head[0][0] == 'STRING'):
            for r in self.refs(head):
                self.read(r, 'str', 'nome de programa em CALL dinâmico')
        if u < 0:
            return
        seg, mode, cur = a[u + 1:], 'REFERENCE', []

        def flush():
            for r in self.refs(cur):
                self.read(r)
                if mode == 'REFERENCE':
                    self.write(r)

        i = 0
        while i < len(seg):
            if V(seg[i]) == 'BY' and i + 1 < len(seg) and V(seg[i + 1]) in ('REFERENCE', 'CONTENT', 'VALUE'):
                flush()
                mode, cur = V(seg[i + 1]), []
                i += 2
                continue
            cur.append(seg[i])
            i += 1
        flush()

    def cics(self, a):
        verb = V(a[0]) if a else ''
        i = 0
        while i < len(a):
            t = a[i]
            if t[0] in ('IDENT', 'KEYWORD') and i + 1 < len(a) and is_sym(a[i + 1], '('):
                e = match_paren(a, i + 1)
                self.cics_option(verb, V(t), a[i + 2:e])
                i = e + 1
            else:
                i += 1

    def cics_option(self, verb, key, arg):
        if not arg or (len(arg) == 1 and arg[0][0] in ('STRING', 'NUMBER')):
            return
        num = key in CICS_NUM_KEYS
        for r in self.refs(arg):
            if verb == 'ASSIGN':
                self.write(r, 'str', f'EXEC CICS ASSIGN {key}')
            elif verb == 'FORMATTIME' and key in FORMATTIME_WRITE:
                self.write(r, 'str', f'EXEC CICS FORMATTIME {key}')
            elif verb == 'ASKTIME' and key == 'ABSTIME':
                self.write(r, 'num', 'EXEC CICS ASKTIME ABSTIME')
            elif key in CICS_WRITE_KEYS:
                self.write(r, 'num' if num else 'str', f'EXEC CICS {verb} {key}')
                if key == 'LENGTH':
                    self.read(r)
            else:
                self.read(r, 'num' if num else 'str', f'EXEC CICS {verb} {key}')
                if key == 'COMMAREA' and verb in ('LINK', 'XCTL', 'RETURN'):
                    self.write(r)
                if key == 'LENGTH':
                    self.write(r)

    def fileio(self, a):
        pts = sorted((i, w) for w in ('INTO', 'FROM', 'KEY') for i in [find(a, (w,))] if i >= 0)
        for k, (i, w) in enumerate(pts):
            end = pts[k + 1][0] if k + 1 < len(pts) else len(a)
            for r in self.refs(a[i + 1:end]):
                (self.write if w == 'INTO' else self.read)(r)

    def sql(self, a):
        if not a:
            return
        first = V(a[0])
        if first == 'INCLUDE' or (first == 'DECLARE' and not any(V(t) == 'CURSOR' for t in a)):
            return
        n = len(a)
        hvs, i = [], 0
        while i < n:
            if is_sym(a[i], ':') and i + 1 < n and a[i + 1][0] == 'IDENT':
                j, struct, name = i + 2, None, V(a[i + 1])
                if j + 1 < n and a[j][0] == 'PERIOD' and a[j + 1][0] == 'IDENT':
                    struct, name, j = name, V(a[j + 1]), j + 2
                hvs.append({'n': name, 'struct': struct, 'start': i, 'end': j, 'line': a[i + 1][2]})
                i = j
            else:
                i += 1
        if not hvs:
            return
        for k, h in enumerate(hvs):  # variável indicadora: ':A.B' seguido direto de ':IND', sem vírgula
            h['ind'] = k > 0 and hvs[k - 1]['end'] == h['start']
        into = find(a, ('INTO',)) if first in ('SELECT', 'FETCH') else -1
        frm = find(a, ('FROM',), into + 1) if into >= 0 else -1
        from_pos = frm if frm >= 0 else (n if into >= 0 else -1)
        cols = None
        if first == 'SELECT' and into > 0:
            cols = split_top(a[1:into], lambda t: is_sym(t, ','))
        real = [h for h in hvs if not h['ind']]
        for k, h in enumerate(hvs):
            r = {'n': h['n'], 'quals': [h['struct']] if h['struct'] else [], 'line': h['line']}
            is_write = (into >= 0 and into < h['start'] < from_pos) or (first == 'SET' and k == 0)
            (self.write if is_write else self.read)(r)
            if h['ind']:
                self.note(h['n'], 'num', h['line'], 'variável indicadora de NULL')
                continue
            cat = why = None
            s = h['start'] - 1
            while s >= 0 and is_sym(a[s], '('):
                s -= 1
            if s >= 1 and ((a[s][0] in ('SYMBOL', 'OP') and a[s][1] in REL_SYMBOLS) or V(a[s]) in ('LIKE', 'IN')):
                c = a[s - 1]
                if c[0] == 'IDENT' and V(c) in self.colcat:
                    cat, why = self.colcat[V(c)][0], f'comparado com a coluna {V(c)} (DCLGEN)'
            if cat is None and cols and is_write and len(cols) == len(real) and h in real:
                c = cols[real.index(h)]
                col = V(c[-1]) if (len(c) == 1 and c[0][0] == 'IDENT') or (len(c) == 3 and c[1][0] == 'PERIOD') else None
                if col and col in self.colcat:
                    cat, why = self.colcat[col][0], f'recebe a coluna {col} (DCLGEN)'
            if cat is None and h['struct']:
                col = '_'.join(h['n'].split('-'))
                if col in self.colcat:
                    cat, why = self.colcat[col][0], f'mesmo nome da coluna {col} em {self.colcat[col][1][0]}'
            if cat is None and h['start'] > 0 and V(a[h['start'] - 1]) == 'FOR':
                cat, why = 'num', 'quantidade de linhas do rowset'
            if cat:
                self.note(h['n'], cat, h['line'], why)


def _attribute(name, quals, missing):
    for q in quals:
        if q in missing:
            return q, 'QUALIFICADOR'
    best, parts = None, name.split('-')
    for cb in missing:  # o copybook dá o prefixo do nome: o primeiro(s) segmento(s) do campo coincidem com o nome do copybook
        seg = cb.split('-')
        if parts[:len(seg)] == seg and (best is None or len(cb) > len(best)):
            best = cb
    if best:
        return best, 'PREFIXO'
    if len(missing) == 1:
        return missing[0], 'UNICO_AUSENTE'
    return None, 'CANDIDATOS' if missing else 'SEM_COPYBOOK_AUSENTE'


def analyze_program(program, ast, dm, missing, linkage, colcat, linemap=None):
    from static_model import walk  # import tardio: static_model importa este módulo
    labels = {n['name'] for n in walk(ast.get('body', [])) if n.get('type') == 'LABEL'}
    A = _Analyzer(dm, labels, colcat or {}, linemap)
    for n in walk(ast.get('body', [])):
        if n.get('type') != 'LABEL':
            A.stmt(n)
    declared = set(dm['by_name']) | {x['indexed_by'] for x in dm['items'] if x.get('indexed_by')}
    names = set(A.reads) | set(A.writes) | set(A.tags)
    undeclared = {n for n in names if n not in declared and not is_runtime_name(n)}
    for a, b in A.links:  # tipo vindo de campo declarado ligado por MOVE/comparação
        for x, y in ((a, b), (b, a)):
            if x in undeclared and y in dm['by_name']:
                it = dm['by_name'][y]
                cat = it['picture']['category']
                if it['level'] != 88 and cat in ('NUMERIC', 'ALPHANUMERIC', 'GROUP'):
                    A.tags[x].add('num' if cat == 'NUMERIC' else 'str')
    for _ in range(3):
        for a, b in A.links:
            for x, y in ((a, b), (b, a)):
                if x in undeclared and resolve_tags(A.tags[x]) is None and y in undeclared:
                    t = resolve_tags(A.tags[y])
                    if t in ('num', 'str'):
                        A.tags[x].add(t)
    lines = lambda d: sorted(A.L(x) for x in d)[:6]
    fields = []
    for n in sorted(undeclared):
        kind = resolve_tags(A.tags.get(n, ()))
        cb, how = _attribute(n, sorted(A.quals.get(n, ())), missing)
        fields.append({
            'name': n, 'type': TYPE_NAME[kind], 'kind': kind, 'default': DEFAULTS[kind],
            'tags': sorted(A.tags.get(n, ())), 'read': n in A.reads, 'written': n in A.writes,
            'read_lines': lines(A.reads.get(n, ())), 'write_lines': lines(A.writes.get(n, ())),
            'evidence': A.evid.get(n, [])[:4], 'qualifiers': sorted(A.quals.get(n, ())),
            'copybook': cb, 'attribution': how, 'candidates': sorted(missing) if cb is None else [],
        })
    boundary = undeclared | set(linkage) | {n for n in names if is_runtime_name(n)}
    return {
        'program': program, 'fields': fields,
        'reads': sorted(A.reads), 'writes': sorted(A.writes),
        'inputs': sorted(n for n in A.reads if n in boundary and n not in A.writes),
        'outputs': sorted(n for n in A.writes if n in undeclared or n in set(linkage)),
        'summary': {'undeclared': len(fields), 'undeclared_read': sum(f['read'] for f in fields),
                    'untyped': sum(f['kind'] is None for f in fields),
                    'by_copybook': _count(f['copybook'] or '(não identificado)' for f in fields)},
    }


def _count(it):
    d = defaultdict(int)
    for x in it:
        d[x] += 1
    return dict(sorted(d.items()))
