"""Layout em bytes de um grupo COBOL e conversão texto <-> campos, para a memória por campo do runtime conversar com quem só enxerga bytes
(fila IBM MQ, container CICS, MOVE de grupo para área e de área para grupo).

O layout sai do modelo de dados do programa (cobol_data_model): elementares na ordem, FILLER como brancos, REDEFINES ignorado (vale o item
redefinido), OCCURS com o máximo e OCCURS ... DEPENDING ON pelo valor corrente do campo de controle. Formato dos elementares como no
mainframe em DISPLAY: alfanumérico alinhado à esquerda com brancos; numérico com zeros à esquerda, escala implícita (V) e sinal no último
dígito ("overpunch": {A-I positivo, }J-R negativo). COMP/BINARY/COMP-4/COMP-5 em binário big-endian (complemento de 2 quando tem
sinal) e COMP-3 em decimal compactado (sinal C/D/F no último meio byte), como no z/OS: cada byte é um caractere latin-1 do texto.
Uma tabela de PIC X(1) (área de bytes, como um campo PIC X(1) OCCURS 0 TO n) é guardada como um texto só, no nome do grupo que a
contém, como o runtime já guarda essas áreas.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

POS = '{ABCDEFGHI'
NEG = '}JKLMNOPQR'


def _tam(it):
    d = it['picture']['digits'] or 0
    u = it.get('usage')
    if u == 'COMP-3':
        return d // 2 + 1
    if u in ('COMP', 'BINARY', 'COMP-4', 'COMP-5'):
        return 2 if d <= 4 else 4 if d <= 9 else 8
    return d


def layout(items, grupo):
    """Lista de entradas do grupo: ('E', nome, tamanho, categoria, sinal, escala) elementar; ('F', tamanho) FILLER;
    ('T', nome, tamanho) área de bytes (texto); ('O', nome, máximo, depending, [entradas de uma ocorrência])."""
    i = next((k for k, x in enumerate(items) if x['name'] == grupo and x['level'] not in (66, 88)), None)
    if i is None:
        return None
    return _filhos(items, i)[0]


def _filhos(items, i):
    it = items[i]
    if it.get('pic'):
        return [_elem(it)], i + 1
    diretos, j = [], i + 1
    while j < len(items) and (items[j]['level'] in (66, 88) or items[j]['level'] > it['level']) and items[j]['level'] != 77:
        if items[j]['level'] in (66, 88):
            j += 1
            continue
        sub, fim = _filhos(items, j)
        diretos.append((j, sub))
        j = fim
    validos = [(k, sub) for k, sub in diretos if not items[k].get('redefines')]
    out = []
    for k, sub in validos:
        x = items[k]
        if x.get('occurs') is not None or x.get('occurs_max'):
            mx = x.get('occurs_max') or x.get('occurs') or 0
            if x.get('pic') and (x['picture']['digits'] or 0) == 1 and x['picture']['category'] != 'NUMERIC':
                out.append(('T', it['name'] if len(validos) == 1 else x['name'], mx))   # tabela de bytes: um texto só
            else:
                out.append(('O', x['name'], mx, x.get('depending_on'), sub))
        else:
            out.extend(sub)
    return out, j


def _elem(it):
    if it['name'] == 'FILLER':
        return ('F', _tam(it))
    pi = it['picture']
    u = it.get('usage')
    uso = 'BIN' if u in ('COMP', 'BINARY', 'COMP-4', 'COMP-5') else 'PACK' if u == 'COMP-3' else ''
    return ('E', it['name'], _tam(it), pi['category'], bool(pi['signed']), pi['scale'] or 0, uso)


def _numero(v, escala):
    """Valor do campo como inteiro sem escala (V implícito), ou None quando não é número."""
    if isinstance(v, str) and not v.strip().lstrip('+-').replace('.', '', 1).isdigit():
        return 0 if not v.strip() else None
    try:
        return int(Decimal(str(v if v not in (None, '') else 0).strip()).scaleb(escala))
    except (InvalidOperation, ValueError):
        return 0


def _bin_formatar(e, v):
    _, _, n, cat, sinal, escala, uso = e
    x = _numero(v, escala)
    if x is None:
        return str(v).ljust(n)[:n]
    if uso == 'BIN':
        x %= 256 ** n   # trunca no tamanho do campo; com sinal, o complemento de 2
        return x.to_bytes(n, 'big').decode('latin-1')
    dig = str(abs(x)).zfill(2 * n - 1)[-(2 * n - 1):]   # COMP-3: 2n-1 dígitos e o meio byte de sinal
    s = ('D' if x < 0 else 'C') if sinal else 'F'
    return bytes.fromhex(dig + s).decode('latin-1')


def _bin_ler(e, t):
    _, _, n, cat, sinal, escala, uso = e
    if not t.strip(' '):
        return t   # área não gravada (brancos): fica como veio, como nos campos em DISPLAY
    b = t.encode('latin-1', 'replace')[:n].ljust(n, b'\0')
    if uso == 'BIN':
        x = int.from_bytes(b, 'big', signed=sinal)
    else:
        h = b.hex().upper()
        if not h[:-1].isdigit():
            return t
        x = -int(h[:-1]) if h[-1] in 'DB' else int(h[:-1])
    d = Decimal(x).scaleb(-escala)
    return int(d) if escala == 0 else float(d)


def formatar(e, v):
    _, _, n, cat, sinal, escala = e[:6]
    if len(e) > 6 and e[6] and cat == 'NUMERIC':
        return _bin_formatar(e, v)
    if cat != 'NUMERIC':
        return ('' if v is None else str(v)).ljust(n)[:n]
    if isinstance(v, str) and not v.strip().lstrip('+-').replace('.', '', 1).isdigit():
        return v.ljust(n)[:n] if v.strip() else '0' * n   # conteúdo não numérico (como veio) passa adiante; brancos viram zeros
    try:
        d = Decimal(str(v if v not in (None, '') else 0).strip())
    except InvalidOperation:
        d = Decimal(0)
    neg = d < 0
    dig = str(int(abs(d).scaleb(escala))).zfill(n)[-n:]
    if not sinal:
        return dig
    return dig[:-1] + (NEG if neg else POS)[int(dig[-1])]


def ler(e, t):
    _, _, n, cat, sinal, escala = e[:6]
    if len(e) > 6 and e[6] and cat == 'NUMERIC':
        return _bin_ler(e, t)
    if cat != 'NUMERIC':
        return t
    x, neg = t, False
    if sinal and x:
        u = x[-1]
        if u in POS:
            x = x[:-1] + str(POS.index(u))
        elif u in NEG:
            x, neg = x[:-1] + str(NEG.index(u)), True
    if not x.isdigit():
        return t   # não numérico: fica como veio (o programa testa com NOT NUMERIC)
    d = Decimal(int(x)).scaleb(-escala)
    d = -d if neg else d
    return int(d) if escala == 0 else float(d)


def codificar(lay, ler_campo, ler_texto):
    """Texto do grupo. ler_campo(nome, índice|None) devolve o valor do elementar; ler_texto(nome) o texto de uma área de bytes."""
    out = []
    for e in lay:
        k = e[0]
        if k == 'F':
            out.append(' ' * e[1])
        elif k == 'E':
            out.append(formatar(e, ler_campo(e[1], None)))
        elif k == 'T':
            out.append(str(ler_texto(e[1]) or ''))   # área de bytes: só o que foi gravado (o tamanho efetivo vem do controle)
        else:
            _, nome, mx, dep, sub = e
            qtd = mx if not dep else max(0, min(mx, _int(ler_campo(dep, None))))
            for i in range(1, qtd + 1):
                for x in sub:
                    out.append(' ' * x[1] if x[0] == 'F' else formatar(x, ler_campo(x[1], i)) if x[0] == 'E' else '')
    return ''.join(out)


def decodificar(lay, texto, gravar, ler_campo, gravar_texto):
    """Distribui o texto pelos elementares do grupo: gravar(nome, índice|None, valor); OCCURS ... DEPENDING ON só até o valor de controle
    (as ocorrências seguintes ficam como estão, como no COBOL)."""
    pos = 0
    for e in lay:
        k = e[0]
        if k == 'F':
            pos += e[1]
        elif k == 'E':
            gravar(e[1], None, ler(e, texto[pos:pos + e[2]].ljust(e[2])))
            pos += e[2]
        elif k == 'T':
            gravar_texto(e[1], texto[pos:pos + e[2]])
            pos += e[2]
        else:
            _, nome, mx, dep, sub = e
            qtd = mx if not dep else max(0, min(mx, _int(ler_campo(dep, None))))
            for i in range(1, qtd + 1):
                if pos >= len(texto):
                    break
                for x in sub:
                    if x[0] == 'F':
                        pos += x[1]
                    elif x[0] == 'E':
                        gravar(x[1], i, ler(x, texto[pos:pos + x[2]].ljust(x[2])))
                        pos += x[2]


def tem_odo(lay):
    return any(e[0] == 'O' and e[3] for e in lay or [])


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(str(v).strip() or 0)
        except ValueError:
            return 0
