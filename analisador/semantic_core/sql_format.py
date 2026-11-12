"""Formatação determinística de comando SQL para os relatórios: uma cláusula por linha, lista de colunas uma por linha, AND/OR de nível alto alinhados, parênteses com
condições aninhadas indentados. Só reorganiza espaços e quebras de linha; nenhum token é alterado, trocado ou removido (a verificação `sem_espacos` confere)."""
import re

CLAUSULAS = ('SELECT DISTINCT', 'SELECT', 'INSERT INTO', 'UPDATE', 'DELETE FROM', 'FROM', 'WHERE', 'GROUP BY', 'HAVING', 'ORDER BY', 'FETCH FIRST', 'VALUES', 'SET', 'WITH UR', 'WITH CS', 'WITH RS', 'WITH RR',
             'LEFT OUTER JOIN', 'RIGHT OUTER JOIN', 'INNER JOIN', 'LEFT JOIN', 'RIGHT JOIN', 'JOIN', 'UNION ALL', 'UNION', 'FOR UPDATE', 'FOR READ ONLY', 'OPTIMIZE FOR', 'WITH')
INDENT = '    '
_TOKEN = re.compile(r"'(?:[^']|'')*'|\"[^\"]*\"|[(),]|[^\s(),']+")


def _tokens(sql):
    return _TOKEN.findall(' '.join(str(sql).split()))


def _clausula(toks, i):
    """Cláusula (várias palavras) que começa em toks[i], ou None."""
    for c in CLAUSULAS:
        n = c.split()
        if [t.upper() for t in toks[i:i + len(n)]] == n:
            return c, len(n)
    return None


def formatar(sql):
    """SQL em várias linhas, com indentação."""
    toks = _tokens(sql)
    if not toks:
        return ''
    linhas, atual, nivel, pilha, i = [], [], 0, [], 0   # pilha: um item por parêntese aberto (True = condições aninhadas, em linhas próprias)
    clausula = ''

    def fecha_linha():
        nonlocal atual
        if atual:
            linhas.append(INDENT * (nivel + (0 if not clausula or atual_inicio_clausula[0] else 1)) + ' '.join(atual).replace(' ,', ',').replace('( ', '(').replace(' )', ')'))
        atual = []
    atual_inicio_clausula = [False]
    lista_virgula = False   # dentro de SELECT/SET/ORDER BY/GROUP BY/VALUES no nível 0: uma vírgula = nova linha
    while i < len(toks):
        t = toks[i]
        c = _clausula(toks, i) if not pilha else None
        if c:
            fecha_linha()
            clausula = c[0]
            atual_inicio_clausula[0] = True
            atual = [' '.join(toks[i:i + c[1]])]
            fecha_linha()
            atual_inicio_clausula[0] = False
            lista_virgula = clausula in ('SELECT', 'SELECT DISTINCT', 'SET', 'ORDER BY', 'GROUP BY', 'VALUES')
            i += c[1]
            continue
        if t == '(':
            # parêntese com AND/OR no nível imediato: condições aninhadas, indentadas
            j, prof, aninha = i + 1, 1, False
            while j < len(toks) and prof:
                if toks[j] == '(':
                    prof += 1
                elif toks[j] == ')':
                    prof -= 1
                elif prof == 1 and toks[j].upper() in ('AND', 'OR'):
                    aninha = True
                j += 1
            if aninha and clausula in ('WHERE', 'HAVING', 'FROM', 'SET'):
                atual.append('(')
                fecha_linha()
                nivel += 1
                pilha.append(True)
            else:
                pilha.append(False)
                atual.append('(')
            i += 1
            continue
        if t == ')':
            if pilha and pilha.pop():
                fecha_linha()
                nivel -= 1
                atual = [')']
            else:
                atual.append(')')
            i += 1
            continue
        if t.upper() in ('AND', 'OR') and clausula in ('WHERE', 'HAVING', 'FROM') and (not pilha or pilha[-1]) and not _entre(toks, i):
            fecha_linha()
            atual = [t]
            i += 1
            continue
        if t == ',' and lista_virgula and not pilha:
            atual.append(',')
            fecha_linha()
            i += 1
            continue
        atual.append(t)
        i += 1
    fecha_linha()
    return '\n'.join(linhas)


def _entre(toks, i):
    """AND que pertence a BETWEEN x AND y (não quebra linha)."""
    j = i - 1
    while j >= 0 and toks[j] not in ('(', ')') and toks[j].upper() not in ('AND', 'OR') and not _clausula(toks, j):
        if toks[j].upper() == 'BETWEEN':
            return True
        j -= 1
    return False


def sem_espacos(sql):
    return ''.join(str(sql).split())


if __name__ == '__main__':
    import sys
    ex = sys.argv[1:] or ["SELECT DISTINCT A.NPLANO_CAPTZ, A.CPLANO_CAPTZ, IFNULL (CHAR (A.DFIM_VGCIA), '') FROM SCHEMA.TABELA_A A, SCHEMA.TABELA_B B WHERE A.NPLANO_CAPTZ = B.NPLANO_CAPTZ AND (A.NPLANO_CAPTZ =:WRK-CH OR A.NPLANO_CAPTZ >:WRK-CH) ORDER BY A.CPLANO_CAPTZ ASC, A.DINIC_VGCIA ASC WITH UR"]
    for e in ex:
        f = formatar(e)
        print(f)
        assert sem_espacos(f) == sem_espacos(e), 'token alterado'
