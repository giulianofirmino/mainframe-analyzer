"""Expansão de COPY e EXEC SQL INCLUDE com mapa de linhas para a origem.

Os comandos são achados pelos TOKENS do analisador léxico (COPY nome [REPLACING ...] . e
EXEC SQL INCLUDE nome END-EXEC), não por leitura de texto. Cada comando informa a linha inicial e a
final; a expansão troca essas linhas físicas pelo conteúdo do membro, e cada linha expandida guarda
(arquivo de origem, linha de origem), de modo que qualquer linha que o parser/runtime produza sobre o
texto expandido volta ao fonte original ou ao copybook de onde veio.
COPY ... REPLACING não é aplicado (não ocorre na base analisada); é reportado.
"""
from __future__ import annotations

from pathlib import Path

from cobol_token_lexer import lex
from token_utils import as_tuple, V, joined_name

COPY_EXT = {'.CPY', '.DCL', '.COPY', '.CPYBK', '.INC'}
SYSTEM_INCLUDES = {'SQLCA', 'SQLDA'}


def read_text(path, keep_eof=False):
    """Texto do membro sem BOM; o marcador Ctrl-Z de fim de arquivo é removido, salvo keep_eof (DCLGEN o classifica)."""
    data = Path(path).read_bytes()
    if data.startswith(b'\xef\xbb\xbf'):
        data = data[3:]
    text = data.decode('latin-1')
    return text if keep_eof else text.replace('\x1a', '')


def library(root):
    """Membros de copybook/DCLGEN disponíveis sob root, por nome de membro."""
    lib = {}
    for p in sorted(Path(root).rglob('*')):
        if p.is_file() and p.suffix.upper() in COPY_EXT:
            lib.setdefault(p.stem.upper(), p)
    return lib


def copy_refs(text):
    """COPY e EXEC SQL INCLUDE de um fonte: [{'kind','name','line','end_line','replacing'}], pelos tokens do léxico."""
    toks = [as_tuple(t) for t in lex(text) if t.type != 'EOF']
    refs, i, n = [], 0, len(toks)
    while i < n:
        t = toks[i]
        if t[0] in ('IDENT', 'KEYWORD') and V(t) == 'COPY':
            name, j = joined_name(toks, i + 1)
            if name:
                replacing = j < n and V(toks[j]) == 'REPLACING'
                k = j
                while k < n and toks[k][0] != 'PERIOD':
                    k += 1
                refs.append({'kind': 'COPY', 'name': name, 'line': t[2], 'end_line': toks[min(k, n - 1)][2], 'replacing': replacing})
                i = k + 1
                continue
        if V(t) == 'EXEC' and i + 2 < n and V(toks[i + 1]) == 'SQL' and V(toks[i + 2]) == 'INCLUDE':
            name, j = joined_name(toks, i + 3)
            k = j
            while k < n and V(toks[k]) != 'END-EXEC':
                k += 1
            if name:
                refs.append({'kind': 'INCLUDE', 'name': name, 'line': t[2], 'end_line': toks[min(k, n - 1)][2], 'replacing': False})
            i = k + 1
            continue
        i += 1
    return refs


def expand_file(path, lib):
    """Retorna (linhas_expandidas, mapa, relatório). mapa[i] = (arquivo, linha) da linha i+1."""
    report = {'expanded': [], 'missing': [], 'replacing_not_supported': [], 'cycles': []}
    out, origin = [], []

    def walk(p, stack):
        text = read_text(p)
        lines = text.splitlines()
        starts = {}
        for r in copy_refs(text):
            starts.setdefault(r['line'], r)
        i = 1
        while i <= len(lines):
            r = starts.get(i)
            if r is None or (r['kind'] == 'INCLUDE' and r['name'] in SYSTEM_INCLUDES):
                out.append(lines[i - 1])
                origin.append((str(p), i))
                i += 1
                continue
            name = r['name']
            here = {'member': name, 'kind': r['kind'], 'file': str(p), 'line': i}
            if r['replacing']:
                report['replacing_not_supported'].append({'member': name, 'file': str(p), 'line': i})
            if name in lib and name not in stack:
                report['expanded'].append(here)
                out.append('      *>' + r['kind'] + ' ' + name)
                origin.append((str(p), i))
                walk(lib[name], stack | {name})
            else:
                report['cycles' if name in stack else 'missing'].append(here)
                for k in range(i, r['end_line'] + 1):  # sem o membro: o comando fica como está
                    out.append(lines[k - 1])
                    origin.append((str(p), k))
            i = max(r['end_line'], i) + 1

    walk(Path(path), {Path(path).stem.upper()})
    return out, origin, report


class LineMap:
    """Tradução linha expandida -> origem, e linha do fonte original -> linha expandida."""

    def __init__(self, program_file, origin):
        self.file = str(program_file)
        self.origin = origin
        self.reverse = {ln: i + 1 for i, (f, ln) in enumerate(origin) if f == self.file}

    def to_source(self, expanded_line):
        if not expanded_line or expanded_line < 1 or expanded_line > len(self.origin):
            return {'file': None, 'line': None}
        f, ln = self.origin[expanded_line - 1]
        return {'file': Path(f).name, 'line': ln, 'in_program': f == self.file}

    def source_line(self, expanded_line):
        x = self.to_source(expanded_line)
        return x['line'] if x.get('in_program') else None

    def to_expanded(self, source_line):
        return self.reverse.get(source_line)
