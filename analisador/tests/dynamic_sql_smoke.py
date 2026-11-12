"""SQL dinâmico: rastreio do campo que carrega o comando (MOVE literal, STRING com campo de valor inicial e campo não literal, MOVE entre campos), cursor sobre comando preparado."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'semantic_core'))
import dynamic_sql as ds  # noqa: E402

SRC = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. DYN1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WRK-SQL PIC X(200).
       01 WRK-OUT PIC X(200).
       01 WRK-TAB PIC X(18) VALUE 'TCLIENTE'.
       01 WRK-ID PIC X(10).
       01 WRK-GRP.
          05 FILLER PIC X(12) VALUE 'DELETE FROM '.
          05 WRK-T2 PIC X(8) VALUE 'TPEDIDO'.
       PROCEDURE DIVISION.
       0000-MAIN.
           STRING 'SELECT NOME FROM ' DELIMITED BY SIZE
                  WRK-TAB DELIMITED BY SPACE
                  ' WHERE ID = ' DELIMITED BY SIZE
                  WRK-ID DELIMITED BY SPACE
              INTO WRK-SQL
           END-STRING
           EXEC SQL PREPARE STMT1 FROM :WRK-SQL END-EXEC
           EXEC SQL DECLARE C1 CURSOR FOR STMT1 END-EXEC
           EXEC SQL OPEN C1 END-EXEC
           EXEC SQL FETCH C1 INTO :WRK-OUT END-EXEC
           EXEC SQL CLOSE C1 END-EXEC
           MOVE WRK-GRP TO WRK-OUT
           EXEC SQL EXECUTE IMMEDIATE :WRK-GRP END-EXEC
           STOP RUN.
'''
r = ds.analisar(SRC)
assert len(r) == 2, r
a, b = r
assert a['montagens'] == ['SELECT NOME FROM TCLIENTE WHERE ID = <WRK-ID>'], a
assert a['tabelas'] == ['TCLIENTE'] and a['operacao'] == 'SELECT' and len(a['linhas']) == 5, a
assert b['montagens'] == ['DELETE FROM TPEDIDO'] and b['tabelas'] == ['TPEDIDO'] and b['operacao'] == 'DELETE', b
print('dynamic_sql smoke OK')

# no relatório: comando dinâmico entra com o SQL montado, cursor vira o SQL do DECLARE e programa sem comando não aparece
import report_deps_sql as rds  # noqa: E402
SRC2 = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. ST1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WRK-X PIC X(10).
       PROCEDURE DIVISION.
       0000-MAIN.
           EXEC SQL DECLARE C2 CURSOR FOR SELECT COLA FROM DB2.TAB2
                WHERE COLB = :WRK-X END-EXEC
           EXEC SQL OPEN C2 END-EXEC
           EXEC SQL FETCH C2 INTO :WRK-X END-EXEC
           EXEC SQL CLOSE C2 END-EXEC
           EXEC SQL SET :WRK-X = CURRENT TIMESTAMP END-EXEC
           STOP RUN.
'''
ps = {'DYN1': {'sql_commands': [{'line': 20, 'operation': 'PREPARE', 'sql': 'PREPARE STMT1 FROM :WRK-SQL'}, {'line': 21, 'operation': 'OPEN', 'sql': 'OPEN C1'}, {'line': 24, 'operation': 'EXECUTE', 'sql': 'EXECUTE IMMEDIATE :WRK-GRP'}],
               'cursors': [], 'table_access': []},
      'ST1': {'sql_commands': [{'line': 9, 'operation': 'OPEN', 'sql': 'OPEN C2'}, {'line': 10, 'operation': 'FETCH', 'sql': 'FETCH C2'}, {'line': 12, 'operation': 'SET', 'sql': 'SET:WRK-X = CURRENT TIMESTAMP'}],
              'cursors': [{'cursor': 'C2', 'declared_line': 8, 'tables': ['DB2.TAB2'], 'operations': [{'line': 9, 'operation': 'OPEN'}, {'line': 10, 'operation': 'FETCH'}, {'line': 11, 'operation': 'CLOSE'}]}],
              'table_access': [{'line': 9, 'table': 'DB2.TAB2', 'operation': 'OPEN', 'via_cursor': 'C2'}, {'line': 10, 'table': 'DB2.TAB2', 'operation': 'FETCH', 'via_cursor': 'C2'}]},
      'NOSQL': {'sql_commands': [], 'cursors': [], 'table_access': []}}
cm = rds.comandos(ps, None, {'DYN1': SRC, 'ST1': SRC2})
ids = {c['id']: c for c in cm}
assert set(ids) == {'DYN1@20', 'DYN1@26', 'ST1@8'}, ids
assert ids['ST1@8']['sql'].startswith('SELECT COLA FROM DB2.TAB2 WHERE COLB') and ids['ST1@8']['operacao'] == 'SELECT' and ids['ST1@8']['tabelas'] == ['DB2.TAB2'] and ids['ST1@8']['dinamico'] is False
assert ids['DYN1@20']['dinamico'] and ids['DYN1@20']['montagens'] == ['SELECT NOME FROM TCLIENTE WHERE ID = <WRK-ID>']
m = rds.m_dependencias_sql({'programs': ps}, {'static': {'call_graph': [{'caller': 'NOSQL', 'target': 'ST1', 'mechanism': 'CALL', 'line': 3}], 'programs': {}}, 'phase': {}, 'rt': None, 'scenarios': [], 'fontes': {'DYN1': SRC, 'ST1': SRC2}})
txt = str(m)
assert 'NOSQL' not in txt and 'SELECT NOME FROM TCLIENTE' in txt
print('dynamic_sql report smoke OK')
