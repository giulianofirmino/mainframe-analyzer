"""Arquivos e telas de um programa COBOL, lidos pelos tokens do léxico (sem expressões regulares sobre o fonte).

  file_model(texto) -> {'files': {ARQUIVO: {'organization','access','key','alt_keys','status','record'}}, 'records': {REGISTRO: ARQUIVO}, 'screen': {CAMPO-DE-TELA: VARIAVEL}}

 - SELECT ... ORGANIZATION / ACCESS MODE / RECORD KEY / ALTERNATE RECORD KEY / FILE STATUS (FILE-CONTROL);
 - FD <arquivo> e o primeiro registro 01 que o segue (FILE SECTION);
 - SCREEN SECTION: cada campo de entrada (USING/TO/FROM variável) aponta para a variável que o ACCEPT preenche."""
from cobol_token_lexer import lex


def _v(t):
    return t.value.upper()


def _ate_ponto(t, i):
    a = []
    while i < len(t) and t[i].type != 'PERIOD':
        a.append(t[i])
        i += 1
    return a, i + 1


def _depois(a, *palavras):
    """Primeiro identificador depois da sequência de palavras (ignora IS)."""
    vals = [_v(x) for x in a]
    n = len(palavras)
    for k in range(len(vals) - n):
        if tuple(vals[k:k + n]) == palavras:
            j = k + n
            while j < len(a) and vals[j] in ('IS', 'ARE'):
                j += 1
            return vals[j] if j < len(a) else None
    return None


ATRIBUTOS_TELA = {'LINE', 'COLUMN', 'BLANK', 'VALUE', 'FOREGROUND-COLOR', 'BACKGROUND-COLOR', 'PIC', 'PICTURE', 'USING', 'TO', 'FROM', 'HIGHLIGHT', 'REVERSE-VIDEO', 'ERASE', 'AUTO', 'REQUIRED', 'SECURE', 'BELL', 'BLINK', 'UNDERLINE', 'FULL', 'LOWLIGHT'}


def file_model(texto):
    t = lex(texto)
    out = {'files': {}, 'records': {}, 'screen': {}}
    i = 0
    while i < len(t):
        v = _v(t[i])
        if v == 'SELECT' and i + 1 < len(t):
            a, j = _ate_ponto(t, i + 1)
            nome = _v(a[0])
            vals = [_v(x) for x in a]
            # chave primária = RECORD KEY que não vem logo depois de ALTERNATE; as demais são chaves alternativas
            prim, alts = None, []
            for k in range(len(vals) - 2):
                if vals[k] == 'RECORD' and vals[k + 1] == 'KEY':
                    j2 = k + 2
                    while j2 < len(vals) and vals[j2] == 'IS':
                        j2 += 1
                    nome_k = vals[j2] if j2 < len(vals) else None
                    if k > 0 and vals[k - 1] == 'ALTERNATE':
                        alts.append(nome_k)
                    elif prim is None:
                        prim = nome_k
            out['files'][nome] = {'organization': _depois(a, 'ORGANIZATION') or 'SEQUENTIAL', 'access': _depois(a, 'ACCESS', 'MODE') or 'SEQUENTIAL',
                                  'key': prim, 'alt_keys': alts, 'status': _depois(a, 'FILE', 'STATUS'), 'record': None}
            i = j
            continue
        if v == 'FD' and i + 1 < len(t):
            a, j = _ate_ponto(t, i + 1)
            nome = _v(a[0])
            if j < len(t) and t[j].type == 'NUMBER' and j + 1 < len(t):
                rec = _v(t[j + 1])
                out['records'][rec] = nome
                if nome in out['files']:
                    out['files'][nome]['record'] = rec
            i = j
            continue
        if v == 'SCREEN' and i + 1 < len(t) and _v(t[i + 1]) == 'SECTION':
            i += 3
            while i < len(t) and not (_v(t[i]) == 'PROCEDURE' and i + 1 < len(t) and _v(t[i + 1]) == 'DIVISION'):
                a, i = _ate_ponto(t, i)
                if len(a) > 2 and a[0].type == 'NUMBER' and _v(a[1]) not in ATRIBUTOS_TELA:
                    alvo = _depois(a, 'USING') or _depois(a, 'TO') or _depois(a, 'FROM')
                    if alvo:
                        out['screen'][_v(a[1])] = alvo
            continue
        i += 1
    return out
