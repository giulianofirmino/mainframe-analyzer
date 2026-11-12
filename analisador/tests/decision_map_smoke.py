"""Mapa de decisão: EVALUATE vira cadeia IF/ELSIF, condições e comandos legíveis, códigos na ordem do fonte."""
import sys, pathlib
ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'semantic_core'))
from cobol_token_parser import parse_text
import decision_map

SRC = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PY.
       PROCEDURE DIVISION.
       A.
           EVALUATE TRUE
             WHEN ERRO-DB
                SET ERRO-DB2 TO TRUE
                MOVE SQLCODE TO WRK-SQLCODE-NUM
             WHEN ERRO-MODULO
                MOVE 1 TO X
             WHEN OTHER
                CONTINUE
           END-EVALUATE.
       B.
           IF WRK-CONT > 3
              PERFORM A
           END-IF.
"""
dm = decision_map.build('PY', parse_text(SRC))
rows = {r['code']: r for r in dm['rows']}
assert [r['code'] for r in dm['rows'] if r['kind'] == 'decisão'] == ['D001', 'D002', 'D003'], dm['rows']
assert rows['D001']['text'] == ['ERRO-DB == TRUE'] and rows['D001']['construct'] == 'EVALUATE'
assert rows['D002']['text'] == ['ERRO-MODULO == TRUE'] and rows['D002']['construct'] == 'ELSIF'
assert rows['E001']['text'] == ['ERRO-DB2 = TRUE', 'WRK-SQLCODE-NUM = SQLCODE']
assert rows['D001']['true_keys'] == ['WHEN_1'] and rows['D002']['true_keys'] == ['WHEN_2'] and rows['D002']['false_keys'] == ['WHEN_3']
assert rows['D003']['text'] == ['WRK-CONT > 3']
print('decision_map smoke OK')

# SQL, PERFORM e CALL ficam cada um na sua caixa; comandos de cursor mostram a tabela do DECLARE
from dependency_map import declared_cursors
SRC2 = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PZ.
       PROCEDURE DIVISION.
       A.
           MOVE 1 TO X
           EXEC SQL SELECT COL1 INTO :W-COL1 FROM SCH.TAB1
              WHERE K = :W-K END-EXEC
           MOVE SQLCODE TO W-SQL
           EXEC SQL DECLARE C1 CURSOR FOR
              SELECT COL2 FROM SCH.TAB2 END-EXEC
           EXEC SQL OPEN C1 END-EXEC
           EXEC SQL FETCH C1 INTO :W-COL2 END-EXEC
           SET ERRO-MODULO TO TRUE
           PERFORM 9999-ERRO
           MOVE WRK-AREA-A-W000-COD TO Y.
"""
dm2 = decision_map.build('PZ', parse_text(SRC2), cursors=declared_cursors(SRC2))
subs = [(r['sub'], r['sql_op'], r['tables']) for r in dm2['rows'] if r['kind'] == 'execução']
assert [s[0] for s in subs] == ['dados', 'sql', 'dados', 'sql', 'sql', 'sql', 'dados', 'perform', 'dados'], subs
assert subs[1] == ('sql', 'SELECT', ['SCH.TAB1']) and subs[4][2] == ['SCH.TAB2'] and subs[5][2] == ['SCH.TAB2']
assert dm2['rows'][6]['text'] == ['ERRO-MODULO = TRUE'] and dm2['rows'][8]['text'] == ['Y = WRK-AREA-A-W000-COD']
print('decision_map caixas separadas OK')
