"""Saídas de comandos CICS (ASKTIME/FORMATTIME) viram atribuição com origem 'comando CICS'; origem não rastreada x valor inicial; ordem de execução."""
import sys, pathlib, tempfile
ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'semantic_core'))
import static_model, data_flow, field_lineage

SRC = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WRK-ABS     PIC S9(15) COMP-3.
       01  WRK-DATA    PIC X(10).
       01  WRK-NUNCA   PIC X(5).
       01  WRK-K       PIC 9(5).
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05 LNK-ID   PIC 9(5).
       PROCEDURE DIVISION.
       P0.
           EXEC CICS ASKTIME ABSTIME(WRK-ABS) END-EXEC
           EXEC CICS FORMATTIME ABSTIME(WRK-ABS)
              DDMMYYYY(WRK-DATA) END-EXEC
           MOVE 7 TO WRK-K
           MOVE LNK-ID TO WRK-K
           EXEC SQL INSERT INTO SCH.TAB (C1, C2, C3)
              VALUES (:WRK-DATA, :WRK-K, :WRK-NUNCA) END-EXEC
           GOBACK.
"""
with tempfile.TemporaryDirectory() as d:
    src = pathlib.Path(d) / 'src'
    src.mkdir()
    (src / 'PROGC.CBL').write_text(SRC)
    m = static_model.build(src, pathlib.Path(d) / 'st')
fl = data_flow.build(m)
lin = field_lineage.build(m, fl, {})
w = lin['tables']['SCH.TAB']['writes'][0]
col = {c['column']: c for c in w['columns']}
assert [o['kind'] for o in col['C1']['origins']] == ['comando CICS'], col['C1']['origins']
assert all(o['expected'] for o in col['C1']['origins'])
# ordem: MOVE LNK-ID TO WRK-K (incondicional, depois de MOVE 7) encerra o valor fixo 7
assert [o['kind'] for o in col['C2']['origins']] == ['entrada do entry point'], [(o['kind'], o['name']) for o in col['C2']['origins']]
assert [o['kind'] for o in col['C3']['origins']] == ['valor inicial (campo nunca atribuído no programa)'] and col['C3']['origins'][0]['expected']
print('cics_saidas smoke OK')
