"""Teste do texto legível: cada par (entrada COBOL -> saída esperada) vem dos exemplos pedidos; nomes de grupo são dados de teste."""
import sys
from pathlib import Path
R = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(R / 'semantic_core')]
from token_utils import tokens_of
from cobol_token_parser import parse_text
from readable_code import Namer, condition_text, evaluate_when_text, evaluate_group_text, statement_lines

N = Namer({'FRWKW200', 'FRWKEL84', 'FRWKGL01', 'GCORW910', 'FRWKGDB2'})
COND = [
    ('WRK-PTR-CHANNEL EQUAL NULL', 'WRK-PTR-CHANNEL == NULL'),
    ('WRK-CONT GREATER WRK-QTD-OCCURS-USADAS', 'WRK-CONT > WRK-QTD-OCCURS-USADAS'),
    ('FRWKW200-FUN-CONS-VERIF', 'FRWKW200-FUN-CONS-VERIF'),
    ("FRWKEL84-TIPO-BLOCO(WRK-IND) EQUAL '1' OR 'B' OR 'D' OR 'F'", "FRWKEL84-TIPO-BLOCO[WRK-IND] IN ('1', 'B', 'D', 'F')"),
    ('FRWKGL01-IFLUXO-EXTER EQUAL SPACES', 'FRWKGL01-IFLUXO-EXTER == SPACES'),
    ('SQLCODE NOT EQUAL ZEROS AND +100', 'SQLCODE != ZEROS AND SQLCODE != +100'),
    ('EIBRESP NOT EQUAL DFHRESP (NORMAL)', 'EIBRESP != DFHRESP(NORMAL)'),
    ('GCORW910-COD-RETORNO NOT EQUAL ZEROS AND 01 AND 08', 'GCORW910-COD-RETORNO NOT IN (0, 01, 08)'),
    ('A IS NOT NUMERIC OR B >= 3', 'A IS NOT NUMERIC OR B >= 3'),
    ('WRK-AREA-CDPSWAAA-W000-COD-RETORNO EQUAL 12', 'WRK-AREA-CDPSWAAA-W000-COD-RETORNO == 12'),
]
STMT = [
    ('SET', 'ERRO-DB2 TO TRUE', ['ERRO-DB2 = TRUE']),
    ('MOVE', 'SQLCODE TO WRK-SQLCODE-NUM', ['WRK-SQLCODE-NUM = SQLCODE']),
    ('MOVE', "'TOPER_ATUAL_PSSOA' TO FRWKGDB2-NOME-TABELA", ['FRWKGDB2-NOME-TABELA = "TOPER_ATUAL_PSSOA"']),
    ('ADD', '1 TO WRK-IND1', ['WRK-IND1 += 1']),
    ('COMPUTE', 'X = 103 * Y', ['X = 103 * Y']),
    ('DIVIDE', 'A BY 16 GIVING Q REMAINDER R', ['Q = A / 16', 'R = A % 16']),
]


def first(src, typ):
    a = parse_text('       IDENTIFICATION DIVISION.\n       PROGRAM-ID. PX.\n       PROCEDURE DIVISION.\n       A.\n' + src)
    return next(n for n in a['body'] if n['type'] == typ)


def main():
    bad = 0
    for cond, exp in COND:
        n = first('           IF ' + cond.replace(' OR ', '\n              OR ').replace(' AND ', '\n              AND ') + '\n              CONTINUE\n           END-IF.\n', 'IF')
        got = condition_text(n['condition_tokens'], N)
        if got != exp:
            bad += 1
            print('FALHA cond:', cond, '->', got, '| esperado', exp)
    for typ, args, exp in STMT:
        n = first(f'           {typ} {args}\n', typ)
        got = statement_lines(n, N)
        if got != exp:
            bad += 1
            print('FALHA cmd:', typ, args, '->', got, '| esperado', exp)
    ev = first('           EVALUATE TRUE\n             WHEN ERRO-DB\n                CONTINUE\n           END-EVALUATE.\n', 'EVALUATE')
    got = evaluate_when_text(ev['subject_tokens'], ev['whens'][0]['condition_tokens'], N)
    if got != 'ERRO-DB == TRUE':
        bad += 1
        print('FALHA evaluate:', got)
    print('readable_code_smoke:', 'OK' if not bad else f'{bad} falhas')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
