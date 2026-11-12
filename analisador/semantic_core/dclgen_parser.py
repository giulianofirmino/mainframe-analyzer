"""Analisador sintático de DCLGEN (DB2 for z/OS, LANGUAGE(COBOL)) sobre os tokens do analisador léxico.

Um membro DCLGEN tem quatro partes, todas reconhecidas linha a linha:

1. Cabeçalho em comentário com o comando que o gerou
   (TABLE, LIBRARY, ACTION, LANGUAGE, STRUCTURE, APOST/QUOTE, LABEL, NAMES, COLSUFFIX, INDVAR ...).
2. ``EXEC SQL DECLARE <tabela> TABLE ( <coluna> <tipo> [NOT NULL] ... ) END-EXEC.``
3. Estrutura COBOL ``01 <estrutura>.`` com um item nível 10 por coluna
   (VARCHAR vira grupo com dois itens nível 49: -LEN e -TEXT) e, com INDVAR(YES),
   a estrutura de indicadores ``01 I<estrutura>`` com ``OCCURS n TIMES``.
4. Trailer ``THE NUMBER OF COLUMNS DESCRIBED BY THIS DECLARATION IS n``.

Código (partes 2 e 3) e comentários são lidos como tokens do léxico (`cobol_token_lexer`); só a
disposição física de colunas (indicador na coluna 7, marcador Ctrl-Z, linhas em branco) é posicional.
Linha que não se encaixa na gramática vira ``UNRECOGNIZED`` e reprova o membro: a cobertura é medida.
Além da sintaxe, valida a coerência coluna SQL <-> campo COBOL (nome, tipo, tamanho, escala, quantidade).
"""
from __future__ import annotations

from pathlib import Path

from cobol_token_lexer import lex
from copybook_resolver import copy_refs, read_text
from token_utils import as_tuple, tokens_of, V, is_sym, match_paren, adjacent, dotted_name

EOF_MARK = '\x1a'  # Ctrl-Z gravado por transferências PC <-> mainframe


def read_member(path):
    return read_text(path, keep_eof=True)


def physical_lines(text):
    """(numero, linha, indicador, área) em formato fixo: col 7 indicador, cols 8-72 área."""
    out = []
    for n, raw in enumerate(text.splitlines(), 1):
        raw = raw.rstrip('\r\n')
        if raw.strip() in ('', EOF_MARK):
            out.append((n, raw, None, raw.strip()))
            continue
        line = raw.replace(EOF_MARK, '')
        ind = line[6:7] if len(line) > 6 else ' '
        area = line[7:72] if len(line) > 7 else ''
        out.append((n, raw, ind, area))
    return out


def _join(toks):
    """Reconstrói o texto de uma sequência de tokens (junta os adjacentes, separa os demais)."""
    out, prev = '', None
    for t in toks:
        if prev is not None and not adjacent(prev, t):
            out += ' '
        out += t[1]
        prev = t
    return out


# --------------------------------------------------------------------------- #
# Cabeçalho (comentários), lido pelos tokens do léxico
# --------------------------------------------------------------------------- #
OPTION_NAMES = {'TABLE', 'LIBRARY', 'ACTION', 'LANGUAGE', 'STRUCTURE', 'APOST', 'QUOTE', 'LABEL', 'NAMES', 'COLSUFFIX',
                'INDVAR', 'DBCSSYMBOL', 'DBCSDELIM', 'DBCSOPT', 'RMARGIN', 'DCLBIT', 'CCSID'}
COLCOUNT_WORDS = ['THE', 'NUMBER', 'OF', 'COLUMNS', 'DESCRIBED', 'BY', 'THIS', 'DECLARATION', 'IS']


def classify_comment(area):
    toks = [t for t in tokens_of(area) if not is_sym(t, '*')]
    if not toks:
        return 'COMMENT_BANNER', None
    vals = [V(t) for t in toks]
    if len(toks) == len(COLCOUNT_WORDS) + 1 and vals[:len(COLCOUNT_WORDS)] == COLCOUNT_WORDS and toks[-1][0] == 'NUMBER':
        return 'COMMENT_COLUMN_COUNT', int(toks[-1][1])
    if {'DCLGEN', 'COMMAND', 'MADE'} <= set(vals):
        return 'COMMENT_GENERATED_BY', None
    if vals[:4] == ['COBOL', 'DECLARATION', 'FOR', 'TABLE']:
        name, _ = dotted_name(toks, 4)
        if name:
            return 'COMMENT_COBOL_DECLARATION', name
    i = 1 if len(vals) > 1 and vals[0] == 'DCLGEN' and vals[1] in OPTION_NAMES else 0
    if vals[i] in OPTION_NAMES:
        if i + 1 == len(toks):
            return 'COMMENT_OPTION', (vals[i], True)
        if is_sym(toks[i + 1], '('):
            e = match_paren(toks, i + 1)
            if e == len(toks) - 1:
                return 'COMMENT_OPTION', (vals[i], _join(toks[i + 2:e]))
    return 'COMMENT_TEXT', _join(toks)


# --------------------------------------------------------------------------- #
# Parte SQL: EXEC SQL DECLARE ... TABLE ( ... ) END-EXEC
# --------------------------------------------------------------------------- #
# tipo -> forma do argumento
SQL_TYPES = {
    'CHAR': 'LEN', 'CHARACTER': 'LEN', 'VARCHAR': 'LEN', 'GRAPHIC': 'LEN', 'VARGRAPHIC': 'LEN',
    'BINARY': 'LEN', 'VARBINARY': 'LEN', 'LONG': 'LONG',
    'DECIMAL': 'PREC', 'DEC': 'PREC', 'NUMERIC': 'PREC', 'DECFLOAT': 'LEN',
    'INTEGER': None, 'INT': None, 'SMALLINT': None, 'BIGINT': None,
    'REAL': None, 'FLOAT': 'LEN', 'DOUBLE': 'DOUBLE',
    'DATE': None, 'TIME': None, 'TIMESTAMP': 'LEN',
    'BLOB': 'LOB', 'CLOB': 'LOB', 'DBCLOB': 'LOB', 'ROWID': None, 'XML': None,
}
CANON = {'CHARACTER': 'CHAR', 'DEC': 'DECIMAL', 'NUMERIC': 'DECIMAL', 'INT': 'INTEGER'}


class DclgenSyntaxError(Exception):
    def __init__(self, msg, line):
        super().__init__(f'{msg} (linha {line})')
        self.line = line


class _Tokens:
    """Cursor sobre os tokens de um EXEC SQL: itens (valor, linha, tipo), nomes qualificados A.B já unidos."""

    def __init__(self, toks):
        self.t, i = [], 0
        while i < len(toks):
            if toks[i][0] == 'IDENT':
                name, j = dotted_name(toks, i)
                self.t.append((name, toks[i][2], 'IDENT'))
                i = j
            else:
                self.t.append((toks[i][1], toks[i][2], toks[i][0]))
                i += 1
        self.i = 0

    def peek(self, k=0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else (None, None, None)

    def val(self, k=0):
        v, _, ty = self.peek(k)
        return v.upper() if v is not None and ty != 'STRING' else v

    def type(self, k=0):
        return self.peek(k)[2]

    def line(self):
        return self.peek()[1] if self.i < len(self.t) else (self.t[-1][1] if self.t else 0)

    def take(self, expected=None):
        v, ln, ty = self.peek()
        if v is None:
            raise DclgenSyntaxError(f'fim inesperado; esperado {expected}', self.line())
        if expected and (ty == 'STRING' or v.upper() != expected):
            raise DclgenSyntaxError(f"esperado '{expected}', encontrado '{v}'", ln)
        self.i += 1
        return v, ln

    def accept(self, *words):
        if self.val() in words:
            return self.take()
        return None


def _parse_int(tk, what):
    ty = tk.type()
    v, ln = tk.take()
    if ty != 'NUMBER' or not v.isdigit():
        raise DclgenSyntaxError(f'{what} deveria ser numérico, encontrado {v}', ln)
    return int(v)


def _parse_type(tk):
    v, ln = tk.take()
    t = v.upper()
    if t not in SQL_TYPES:
        raise DclgenSyntaxError(f'tipo SQL desconhecido {v}', ln)
    kind = SQL_TYPES[t]
    info = {'sql_type': CANON.get(t, t), 'length': None, 'precision': None, 'scale': None}
    if kind == 'LONG':  # LONG VARCHAR / LONG VARGRAPHIC
        v2, _ = tk.take()
        info['sql_type'] = 'LONG ' + v2.upper()
        return info
    if kind == 'DOUBLE':
        tk.accept('PRECISION')
        info['sql_type'] = 'DOUBLE'
        return info
    if t in ('CHAR', 'CHARACTER') and tk.val() == 'VARYING':
        tk.take()
        info['sql_type'] = 'VARCHAR'
    if tk.val() == '(' and kind is not None:
        tk.take('(')
        if kind == 'PREC':
            info['precision'] = _parse_int(tk, 'precisão')
            info['scale'] = 0
            if tk.accept(','):
                info['scale'] = _parse_int(tk, 'escala')
        elif kind == 'LOB':
            n = _parse_int(tk, 'tamanho de LOB')
            unit = tk.accept('K', 'M', 'G')
            info['length'] = n * {'': 1, 'K': 1024, 'M': 1024 ** 2, 'G': 1024 ** 3}[unit[0].upper() if unit else '']
        else:
            info['length'] = _parse_int(tk, 'comprimento')
        tk.take(')')
    elif kind == 'PREC':
        info['precision'], info['scale'] = 5, 0  # default DB2
    elif t in ('CHAR', 'CHARACTER', 'GRAPHIC', 'BINARY'):
        info['length'] = 1
    if info['sql_type'] == 'TIMESTAMP' and info['length'] is None:
        info['length'] = 6  # precisão fracionária default
    while True:  # sufixos de tipo aceitos pelo DB2
        if tk.val() == 'FOR' and tk.val(1) in ('BIT', 'SBCS', 'MIXED') and tk.val(2) == 'DATA':
            info['for_data'] = tk.val(1)
            tk.take(); tk.take(); tk.take()
        elif tk.val() == 'CCSID':
            tk.take()
            info['ccsid'] = tk.take()[0].upper()
        elif tk.val() in ('WITHOUT', 'WITH') and tk.val(1) == 'TIME' and tk.val(2) == 'ZONE':
            info['time_zone'] = tk.val() == 'WITH'
            tk.take(); tk.take(); tk.take()
        else:
            break
    return info


def parse_declare(toks):
    """toks: tokens do bloco EXEC SQL ... END-EXEC [.]."""
    tk = _Tokens(toks)
    tk.take('EXEC')
    tk.take('SQL')
    tk.take('DECLARE')
    name, name_line = tk.take()
    tk.take('TABLE')
    tk.take('(')
    cols = []
    while True:
        if tk.type() != 'IDENT':
            raise DclgenSyntaxError(f'nome de coluna inválido {tk.peek()[0]}', tk.line())
        cname, cline = tk.take()
        col = {'position': len(cols) + 1, 'name': cname.upper(), 'line': cline, 'nullable': True, 'default': False}
        col.update(_parse_type(tk))
        while True:
            if tk.val() == 'NOT' and tk.val(1) == 'NULL':
                tk.take(); tk.take()
                col['nullable'] = False
            elif tk.val() == 'WITH' and tk.val(1) == 'DEFAULT':
                tk.take(); tk.take()
                col['default'] = True
            else:
                break
        cols.append(col)
        if tk.accept(','):
            continue
        tk.take(')')
        break
    tk.take('END-EXEC')
    if tk.type() == 'PERIOD':
        tk.take()
    if tk.peek()[0] is not None:
        raise DclgenSyntaxError(f"texto após END-EXEC: '{tk.peek()[0]}'", tk.line())
    table = name.upper()
    schema, _, tname = table.rpartition('.')
    return {'table': table, 'schema': schema or None, 'table_name': tname, 'line': name_line, 'columns': cols}


# --------------------------------------------------------------------------- #
# Parte COBOL: estrutura hospedeira, lida pelos tokens
# --------------------------------------------------------------------------- #
USAGES = {'COMP', 'COMP-3', 'COMP-4', 'COMP-5', 'COMP-1', 'COMP-2', 'BINARY', 'DISPLAY',
          'DISPLAY-1', 'PACKED-DECIMAL', 'COMPUTATIONAL', 'COMPUTATIONAL-3', 'COMPUTATIONAL-4',
          'COMPUTATIONAL-5', 'NATIONAL', 'SQL'}
USAGE_CANON = {'COMPUTATIONAL': 'COMP', 'COMPUTATIONAL-3': 'COMP-3', 'PACKED-DECIMAL': 'COMP-3',
               'COMPUTATIONAL-4': 'COMP-4', 'COMPUTATIONAL-5': 'COMP-5', 'BINARY': 'COMP-4'}
CLAUSE_WORDS = USAGES | {'USAGE', 'VALUE', 'OCCURS', 'REDEFINES', 'INDEXED', 'PIC', 'PICTURE'}


def parse_data_entry(toks, line):
    """Entrada de dados como tokens, sem o ponto final."""
    if not toks or toks[0][0] != 'NUMBER' or not toks[0][1].isdigit():
        raise DclgenSyntaxError('entrada de dados sem número de nível', line)
    if len(toks) < 2 or toks[1][0] not in ('IDENT', 'KEYWORD'):
        raise DclgenSyntaxError('entrada de dados sem nome', line)
    e = {'level': int(toks[0][1]), 'name': V(toks[1]), 'pic': None, 'pic_tokens': [], 'usage': None, 'occurs': None,
         'sql_type_clause': None, 'line': line}
    i, n = 2, len(toks)
    while i < n:
        w = V(toks[i])
        if w in ('PIC', 'PICTURE'):
            i += 1
            if i < n and V(toks[i]) == 'IS':
                i += 1
            j = i
            while j < n and V(toks[j]) not in CLAUSE_WORDS and (j == i or adjacent(toks[j - 1], toks[j])):
                j += 1  # a máscara PIC não tem espaços: termina no primeiro token não adjacente
            if j == i:
                raise DclgenSyntaxError('PIC sem máscara', line)
            e['pic_tokens'] = toks[i:j]
            e['pic'] = _join(toks[i:j])
            i = j
            continue
        if w == 'USAGE':
            i += 1
            if i < n and V(toks[i]) == 'IS':
                i += 1
            if i >= n or V(toks[i]) not in USAGES:
                raise DclgenSyntaxError(f"USAGE inválido '{toks[i][1] if i < n else ''}'", line)
            if V(toks[i]) == 'SQL':  # USAGE SQL TYPE IS BLOB-LOCATOR etc.
                e['sql_type_clause'] = _join(toks[i:])
                break
            e['usage'] = USAGE_CANON.get(V(toks[i]), V(toks[i]))
        elif w in USAGES:
            e['usage'] = USAGE_CANON.get(w, w)
        elif w == 'OCCURS':
            i += 1
            if i >= n or toks[i][0] != 'NUMBER' or not toks[i][1].isdigit():
                raise DclgenSyntaxError('OCCURS sem quantidade', line)
            e['occurs'] = int(toks[i][1])
            if i + 1 < n and V(toks[i + 1]) == 'TIMES':
                i += 1
        else:
            raise DclgenSyntaxError(f"cláusula não reconhecida '{toks[i][1]}'", line)
        i += 1
    return e


def pic_chars(toks):
    """Símbolos da PIC a partir dos tokens: S9(8)V -> S,9,9,9,9,9,9,9,9,V (o repetidor vem entre parênteses)."""
    chars, i = [], 0
    while i < len(toks):
        t = toks[i]
        if is_sym(t, '(') and i + 2 < len(toks) and toks[i + 1][0] == 'NUMBER' and is_sym(toks[i + 2], ')') and chars:
            chars += [chars[-1]] * (int(toks[i + 1][1]) - 1)
            i += 3
            continue
        chars += list(V(t)) if t[0] != 'STRING' else []
        i += 1
    return chars


def pic_info(pic_tokens, usage):
    """Categoria, dígitos, escala e tamanho em bytes de uma PIC."""
    chars = pic_chars(pic_tokens)
    if not chars:
        return {'category': 'GROUP', 'digits': None, 'scale': None, 'signed': False, 'bytes': None}
    signed = chars[0] == 'S'
    body = chars[1:] if signed else chars
    kinds = set(body)
    if kinds == {'X'}:
        return {'category': 'ALPHANUMERIC', 'digits': None, 'scale': None, 'signed': False, 'bytes': len(body), 'length': len(body)}
    if kinds in ({'G'}, {'N'}):
        return {'category': 'GRAPHIC', 'digits': None, 'scale': None, 'signed': False, 'bytes': 2 * len(body), 'length': len(body)}
    if not kinds <= {'9', 'V'}:
        return {'category': 'UNSUPPORTED', 'digits': None, 'scale': None, 'signed': False, 'bytes': None}
    left, right = (body[:body.index('V')], body[body.index('V') + 1:]) if 'V' in body else (body, [])
    digits, scale = left.count('9') + right.count('9'), right.count('9')
    u = usage or 'DISPLAY'
    if u == 'COMP-3':
        nbytes = digits // 2 + 1
    elif u in ('COMP', 'COMP-4', 'COMP-5'):
        nbytes = 2 if digits <= 4 else 4 if digits <= 9 else 8
    elif u == 'COMP-1':
        nbytes = 4
    elif u == 'COMP-2':
        nbytes = 8
    else:
        nbytes = digits
    return {'category': 'NUMERIC', 'digits': digits, 'scale': scale, 'signed': signed, 'bytes': nbytes}


def parse_structures(entries):
    """Monta hierarquia 01 -> 10 -> 49 a partir das entradas lineares."""
    structs, stack = [], []
    for e in entries:
        e = dict(e)
        e.update(pic_info(e['pic_tokens'], e['usage']))
        e['children'] = []
        if e['level'] == 1:
            structs.append(e)
            stack = [e]
            continue
        if not stack:
            raise DclgenSyntaxError(f"item nível {e['level']} fora de estrutura 01", e['line'])
        while stack and stack[-1]['level'] >= e['level']:
            stack.pop()
        if not stack:
            raise DclgenSyntaxError(f"nível {e['level']} sem item pai", e['line'])
        stack[-1]['children'].append(e)
        stack.append(e)
    return structs


# --------------------------------------------------------------------------- #
# Compatibilidade SQL <-> COBOL (regras do DCLGEN / "Equivalent SQL and COBOL data types")
# --------------------------------------------------------------------------- #
def expected_host(col):
    t = col['sql_type']
    if t == 'DECIMAL':
        return {'shape': 'NUMERIC', 'usage': {'COMP-3'}, 'digits': col['precision'], 'scale': col['scale']}
    if t == 'SMALLINT':
        return {'shape': 'NUMERIC', 'usage': {'COMP', 'COMP-4', 'COMP-5'}, 'digits': 4, 'scale': 0}
    if t == 'INTEGER':
        return {'shape': 'NUMERIC', 'usage': {'COMP', 'COMP-4', 'COMP-5'}, 'digits': 9, 'scale': 0}
    if t == 'BIGINT':
        return {'shape': 'NUMERIC', 'usage': {'COMP', 'COMP-4', 'COMP-5'}, 'digits': 18, 'scale': 0}
    if t == 'REAL' or (t == 'FLOAT' and (col['length'] or 53) <= 21):
        return {'shape': 'FLOAT', 'usage': {'COMP-1'}}
    if t in ('FLOAT', 'DOUBLE'):
        return {'shape': 'FLOAT', 'usage': {'COMP-2'}}
    if t in ('CHAR', 'BINARY'):
        return {'shape': 'ALPHANUMERIC', 'length': col['length']}
    if t == 'DATE':
        return {'shape': 'ALPHANUMERIC', 'length': 10}
    if t == 'TIME':
        return {'shape': 'ALPHANUMERIC', 'length': 8}
    if t == 'TIMESTAMP':
        p = col['length'] if col['length'] is not None else 6
        return {'shape': 'ALPHANUMERIC', 'length': 19 + (p + 1 if p else 0)}
    if t in ('VARCHAR', 'VARBINARY', 'LONG VARCHAR'):
        return {'shape': 'VARCHAR', 'length': col['length']}
    if t == 'GRAPHIC':
        return {'shape': 'GRAPHIC', 'length': col['length']}
    if t in ('VARGRAPHIC', 'LONG VARGRAPHIC'):
        return {'shape': 'VARGRAPHIC', 'length': col['length']}
    return {'shape': 'OTHER'}


def check_pair(col, field):
    exp = expected_host(col)
    issues = []
    shape = exp['shape']
    if shape == 'NUMERIC':
        if field['category'] != 'NUMERIC':
            issues.append('esperado campo numérico')
        else:
            if (field['usage'] or 'DISPLAY') not in exp['usage']:
                issues.append(f"USAGE {field['usage']} incompatível com {col['sql_type']}")
            if field['digits'] != exp['digits'] or field['scale'] != exp['scale']:
                issues.append(f"PIC {field['pic']} ({field['digits']},{field['scale']}) difere de ({exp['digits']},{exp['scale']})")
            if not field['signed']:
                issues.append('PIC numérica sem sinal')
    elif shape == 'FLOAT':
        if (field['usage'] or '') not in exp['usage']:
            issues.append(f"USAGE {field['usage']} incompatível com {col['sql_type']}")
    elif shape in ('ALPHANUMERIC', 'GRAPHIC'):
        cat = 'ALPHANUMERIC' if shape == 'ALPHANUMERIC' else 'GRAPHIC'
        if field['category'] != cat:
            issues.append(f'esperado campo {cat}')
        elif field.get('length') != exp['length']:
            issues.append(f"PIC {field['pic']} com {field.get('length')} posições, esperado {exp['length']}")
    elif shape in ('VARCHAR', 'VARGRAPHIC'):
        kids = field['children']
        if field['category'] != 'GROUP' or len(kids) != 2 or any(k['level'] != 49 for k in kids):
            issues.append('VARCHAR deve ser grupo com dois itens nível 49 (-LEN e -TEXT)')
        else:
            ln, tx = kids
            if ln['category'] != 'NUMERIC' or ln['digits'] != 4 or (ln['usage'] or '') not in ('COMP', 'COMP-4', 'COMP-5'):
                issues.append(f"{ln['name']}: tamanho deve ser S9(4) COMP/COMP-5")
            want = 'ALPHANUMERIC' if shape == 'VARCHAR' else 'GRAPHIC'
            if tx['category'] != want or tx.get('length') != exp['length']:
                issues.append(f"{tx['name']}: esperado {want} com {exp['length']} posições")
    else:
        issues.append(f"tipo {col['sql_type']} sem regra de compatibilidade")
    return issues


def _bytes(field):
    if field['children']:
        return sum(_bytes(c) for c in field['children'])
    return (field['bytes'] or 0) * (field['occurs'] or 1)


def _public(field):
    keys = ('level', 'name', 'pic', 'usage', 'occurs', 'category', 'digits', 'scale', 'signed', 'line')
    out = {k: field.get(k) for k in keys}
    out['length'] = field.get('length')
    out['bytes'] = _bytes(field)
    if field['children']:
        out['children'] = [_public(c) for c in field['children']]
    return out


# --------------------------------------------------------------------------- #
# API principal
# --------------------------------------------------------------------------- #
def _code_tokens(text):
    return [as_tuple(t) for t in lex(text.replace(EOF_MARK, '')) if t.type != 'EOF']


def looks_like_dclgen(text):
    toks = _code_tokens(text)
    decl = any(V(toks[i]) == 'EXEC' and V(toks[i + 1]) == 'SQL' and V(toks[i + 2]) == 'DECLARE'
               and any(V(x) == 'TABLE' for x in toks[i + 3:i + 8]) for i in range(len(toks) - 8))
    struct = any(toks[i][0] == 'NUMBER' and toks[i][1] in ('1', '01') and toks[i + 1][0] == 'IDENT' and toks[i + 2][0] == 'PERIOD'
                 for i in range(len(toks) - 3))
    return decl and struct


def _statements(toks):
    """Divide os tokens de código em blocos EXEC SQL ... END-EXEC [.] e entradas de dados ... ."""
    out, i, n = [], 0, len(toks)
    while i < n:
        if V(toks[i]) == 'EXEC':
            j = i
            while j < n and V(toks[j]) != 'END-EXEC':
                j += 1
            end = j + 1 if j + 1 < n and toks[j + 1][0] == 'PERIOD' else j
            out.append(('SQL', toks[i:end + 1]))
            i = end + 1
        else:
            j = i
            while j < n and toks[j][0] != 'PERIOD':
                j += 1
            out.append(('DATA', toks[i:j + 1]))
            i = j + 1
    return out


def parse_dclgen(text, member=None):
    for bom in ('﻿', '\xef\xbb\xbf'):
        if text.startswith(bom):
            text = text[len(bom):]
    lines = physical_lines(text)
    kinds, options, unrecognized = {}, {}, []
    trailer = cobol_decl_for = declare = None
    entries, code_lines = [], set()
    for n, raw, ind, area in lines:
        if ind is None:
            kinds[n] = 'EOF_MARKER' if area == EOF_MARK else 'BLANK'
        elif ind in ('*', '/'):
            k, v = classify_comment(area)
            kinds[n] = k
            if k == 'COMMENT_OPTION':
                options.setdefault(v[0], v[1])
            elif k == 'COMMENT_COLUMN_COUNT':
                trailer = v
            elif k == 'COMMENT_COBOL_DECLARATION':
                cobol_decl_for = v
        elif ind not in (' ', '-'):
            kinds[n] = 'UNRECOGNIZED'
            unrecognized.append({'line': n, 'text': raw.strip(), 'reason': f"indicador de coluna 7 inválido '{ind}'"})
        elif not area.strip():
            kinds[n] = 'BLANK'
        else:
            code_lines.add(n)

    def span_lines(stoks):
        return sorted({t[2] for t in stoks})

    for kind, stoks in _statements([t for t in _code_tokens(text) if t[2] in code_lines]):
        first_line = stoks[0][2]
        try:
            if kind == 'SQL':
                if declare is not None:
                    raise DclgenSyntaxError('mais de um EXEC SQL DECLARE TABLE no membro', first_line)
                declare = parse_declare(stoks)
                col_lines = {c['line'] for c in declare['columns']}
                end_line = stoks[-1][2]
                for ln in span_lines(stoks):
                    if ln == first_line:
                        kinds[ln] = 'SQL_DECLARE_TABLE'
                    elif ln in col_lines:
                        kinds[ln] = 'SQL_COLUMN'
                    elif ln == end_line:
                        kinds[ln] = 'SQL_END_EXEC'
                    else:
                        kinds[ln] = 'SQL_CONTINUATION'
            else:
                if stoks[-1][0] != 'PERIOD':
                    raise DclgenSyntaxError('entrada de dados sem ponto final', first_line)
                e = parse_data_entry(stoks[:-1], first_line)
                entries.append(e)
                for k, ln in enumerate(span_lines(stoks)):
                    kinds[ln] = ('COBOL_' + ('STRUCTURE_01' if e['level'] == 1 else f"LEVEL_{e['level']:02d}")) if k == 0 else 'COBOL_CONTINUATION'
        except (DclgenSyntaxError, ValueError, IndexError) as err:
            bad = getattr(err, 'line', first_line)
            for ln in span_lines(stoks):
                kinds[ln] = 'UNRECOGNIZED'
            unrecognized.append({'line': bad, 'text': _join([t for t in stoks if t[2] == bad]), 'reason': str(err)})

    try:
        structs = parse_structures(entries)
    except DclgenSyntaxError as e:
        structs = []
        unrecognized.append({'line': e.line, 'text': '', 'reason': str(e)})

    host = structs[0] if structs else None
    indicator = next((s for s in structs[1:] if s['children'] and s['children'][0].get('occurs')), None)
    extra_structs = [s['name'] for s in structs[1:] if s is not indicator]

    # --------------------------- validação semântica --------------------------- #
    issues, mapping = [], []
    if declare is None:
        issues.append('EXEC SQL DECLARE ... TABLE ausente')
    if host is None:
        issues.append('estrutura COBOL 01 ausente')
    if extra_structs:
        issues.append(f'estruturas 01 inesperadas: {extra_structs}')
    if declare and host:
        cols = declare['columns']
        fields = host['children']
        if any(f['level'] != 10 for f in fields):
            issues.append('itens elementares da estrutura devem ser nível 10')
        if len(fields) != len(cols):
            issues.append(f'{len(cols)} colunas SQL x {len(fields)} campos COBOL')
        colsuffix = str(options.get('COLSUFFIX', 'NO')).upper() == 'YES'
        for col, fld in zip(cols, fields):
            want = '-'.join(col['name'].split('_'))
            pair_issues = []
            if fld['name'] != want and not colsuffix:
                pair_issues.append(f"nome {fld['name']} não corresponde à coluna {col['name']}")
            pair_issues += check_pair(col, fld)
            mapping.append({'position': col['position'], 'column': col['name'], 'sql_type': col['sql_type'],
                            'length': col['length'], 'precision': col['precision'], 'scale': col['scale'],
                            'nullable': col['nullable'], 'field': fld['name'], 'pic': fld['pic'],
                            'usage': fld['usage'], 'bytes': _bytes(fld), 'field_line': fld['line'],
                            'column_line': col['line'], 'compatible': not pair_issues, 'issues': pair_issues})
            issues += [f"{col['name']}: {x}" for x in pair_issues]
        if trailer is not None and trailer != len(cols):
            issues.append(f'trailer declara {trailer} colunas, DECLARE tem {len(cols)}')
        if trailer is None:
            issues.append('trailer "THE NUMBER OF COLUMNS ..." ausente')
        opt_table = options.get('TABLE')
        if isinstance(opt_table, str) and opt_table.upper() != declare['table']:
            issues.append(f"opção TABLE({opt_table}) difere do DECLARE {declare['table']}")
        opt_struct = options.get('STRUCTURE')
        if isinstance(opt_struct, str) and opt_struct.upper() != host['name']:
            issues.append(f"opção STRUCTURE({opt_struct}) difere da estrutura {host['name']}")
        if cobol_decl_for and cobol_decl_for != declare['table']:
            issues.append(f'comentário COBOL DECLARATION cita {cobol_decl_for}, DECLARE é {declare["table"]}')
        if indicator is not None:
            occ = indicator['children'][0]['occurs']
            if occ != len(cols):
                issues.append(f'estrutura de indicadores com OCCURS {occ}, esperado {len(cols)}')

    total = len(lines)
    counts = {}
    for k in kinds.values():
        counts[k] = counts.get(k, 0) + 1
    unclassified = [n for n, *_ in lines if n not in kinds]
    for n in unclassified:
        unrecognized.append({'line': n, 'text': lines[n - 1][1].strip(), 'reason': 'linha não classificada'})
    recognized = total - counts.get('UNRECOGNIZED', 0) - len(unclassified)
    return {
        'member': (member or (host['name'] if host else None)),
        'status': 'PASS' if not unrecognized and not issues else 'FAIL',
        'table': declare['table'] if declare else None,
        'schema': declare['schema'] if declare else None,
        'table_name': declare['table_name'] if declare else None,
        'structure': host['name'] if host else None,
        'indicator_structure': indicator['name'] if indicator else None,
        'options': options,
        'declared_column_count': trailer,
        'columns': declare['columns'] if declare else [],
        'host_structure': _public(host) if host else None,
        'record_length': _bytes(host) if host else None,
        'mapping': mapping,
        'coverage': {'lines': total, 'recognized': recognized, 'unrecognized': total - recognized,
                     'percent': round(100.0 * recognized / total, 2) if total else 100.0, 'by_kind': counts},
        'unrecognized': sorted(unrecognized, key=lambda x: x['line']),
        'issues': issues,
        'line_kinds': [{'line': n, 'kind': kinds.get(n, 'UNRECOGNIZED')} for n, *_ in lines],
    }


def parse_file(path):
    p = Path(path)
    r = parse_dclgen(read_member(p), member=p.stem.upper())
    r['file'] = str(p)
    return r


# --------------------------------------------------------------------------- #
# Catálogo e ligação com os programas
# --------------------------------------------------------------------------- #
COBOL_EXT = {'.CBL', '.COB', '.CBLLE'}


def discover(root):
    """Todo arquivo (exceto fontes COBOL e cópias .TXT) cujo conteúdo é um DCLGEN."""
    out = []
    for p in sorted(Path(root).rglob('*')):
        if not p.is_file() or p.suffix.upper() in COBOL_EXT or p.suffix.upper() == '.TXT':
            continue
        try:
            t = read_member(p)
        except OSError:
            continue
        if looks_like_dclgen(t):
            out.append(p)
    return out


def build_catalog(root):
    members = {}
    for p in discover(root):
        r = parse_file(p)
        key = p.stem.upper()
        if key in members:
            r['issues'].append(f'membro duplicado: {members[key]["file"]}')
            r['status'] = 'FAIL'
            key = f'{key}@{p}'
        members[key] = r
    tables = {}
    for k, r in members.items():
        if r['table']:
            tables.setdefault(r['table'], []).append(k)
    lines = sum(r['coverage']['lines'] for r in members.values())
    rec = sum(r['coverage']['recognized'] for r in members.values())
    summary = {
        'members': len(members),
        'tables': len(tables),
        'columns': sum(len(r['columns']) for r in members.values()),
        'lines': lines,
        'recognized_lines': rec,
        'coverage_percent': round(100.0 * rec / lines, 2) if lines else 100.0,
        'unrecognized_lines': lines - rec,
        'members_pass': sum(r['status'] == 'PASS' for r in members.values()),
        'members_fail': sorted(k for k, r in members.items() if r['status'] != 'PASS'),
        'status': 'PASS' if members and all(r['status'] == 'PASS' for r in members.values()) else ('FAIL' if members else 'EMPTY'),
    }
    return {'summary': summary, 'members': members, 'tables': tables}


def _host_refs(toks):
    """Referências a campos de estrutura pelos tokens: ':ESTRUTURA.CAMPO' (SQL) e 'CAMPO OF|IN ESTRUTURA' (COBOL)."""
    out, n = [], len(toks)
    for i, t in enumerate(toks):
        if is_sym(t, ':') and i + 3 < n and toks[i + 1][0] == 'IDENT' and toks[i + 2][0] == 'PERIOD' and toks[i + 3][0] == 'IDENT':
            out.append((V(toks[i + 1]), V(toks[i + 3]), toks[i + 3][2], 'HOST_VARIABLE'))
        elif t[0] == 'IDENT' and V(t) in ('OF', 'IN') and 0 < i < n - 1 and toks[i - 1][0] == 'IDENT' and toks[i + 1][0] == 'IDENT':
            out.append((V(toks[i + 1]), V(toks[i - 1]), toks[i - 1][2], 'QUALIFIED_OF'))
    return out


def program_bindings(program, text, catalog):
    """INCLUDEs do programa e referências a campos de DCLGEN, com tabela.coluna (tudo lido dos tokens do programa)."""
    members = catalog['members']
    by_struct = {r['structure']: r for r in members.values() if r['structure']}
    includes = []
    for r in copy_refs(text):
        if r['kind'] != 'INCLUDE':
            continue
        name = r['name']
        if name in ('SQLCA', 'SQLDA'):
            includes.append({'name': name, 'line': r['line'], 'status': 'SYSTEM'})
            continue
        m = members.get(name)
        includes.append({'name': name, 'line': r['line'], 'status': 'RESOLVED' if m else 'MISSING',
                         'table': m['table'] if m else None, 'structure': m['structure'] if m else None})
    included = {x['structure'] for x in includes if x.get('structure')}
    missing = {x['name'] for x in includes if x['status'] == 'MISSING'}
    refs = {}

    def add(struct, field, line, how):
        r = by_struct.get(struct)
        if struct in missing and not r:  # estrutura de um INCLUDE cujo membro DCLGEN não foi fornecido
            row = refs.setdefault((struct, field), {'structure': struct, 'field': field, 'table': None, 'column': None,
                                                    'sql_type': None, 'status': 'DCLGEN_MISSING', 'lines': [], 'forms': []})
        elif r and r['structure'] in included:
            mp = next((x for x in r['mapping'] if x['field'] == field), None)
            if mp is None:  # campos 49 de VARCHAR (-LEN/-TEXT) apontam para a coluna do grupo
                for c in r['host_structure'].get('children', []):
                    if any(g['name'] == field for g in c.get('children', []) or []):
                        mp = next((x for x in r['mapping'] if x['field'] == c['name']), None)
            row = refs.setdefault((r['structure'], field), {'structure': r['structure'], 'field': field, 'table': r['table'],
                                                            'column': mp['column'] if mp else None,
                                                            'sql_type': mp['sql_type'] if mp else None,
                                                            'status': 'RESOLVED' if mp else 'FIELD_NOT_IN_DCLGEN', 'lines': [], 'forms': []})
        else:
            return
        if line not in row['lines']:
            row['lines'].append(line)
        if how not in row['forms']:
            row['forms'].append(how)

    for struct, field, line, how in _host_refs(_code_tokens(text)):
        add(struct, field, line, how)
    for row in refs.values():
        row['lines'].sort()
        row['forms'].sort()
    rows = sorted(refs.values(), key=lambda x: (x['structure'], x['lines'][0]))
    return {'program': program, 'includes': includes, 'field_references': rows,
            'summary': {'includes': len([x for x in includes if x['status'] != 'SYSTEM']),
                        'includes_resolved': sum(x['status'] == 'RESOLVED' for x in includes),
                        'includes_missing': sorted(x['name'] for x in includes if x['status'] == 'MISSING'),
                        'field_references': len(rows),
                        'field_references_resolved': sum(x['status'] == 'RESOLVED' for x in rows),
                        'field_references_dclgen_missing': sum(x['status'] == 'DCLGEN_MISSING' for x in rows),
                        'field_references_unknown_field': sum(x['status'] == 'FIELD_NOT_IN_DCLGEN' for x in rows)}}
