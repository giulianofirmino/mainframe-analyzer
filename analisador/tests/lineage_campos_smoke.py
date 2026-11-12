"""Linhagem por campo entre programas: o dado gravado na coluna é seguido até a entrada do entry point atravessando o CALL,
por faixa de bytes; a condição do caminho vem do decision-map; consulta traz chave e destino."""
import sys, pathlib, tempfile
ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'semantic_core'))
import static_model, data_flow, decision_map, field_lineage
from dependency_map import declared_cursors

A = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA.
           05 WS-A   PIC X(5).
           05 WS-B   PIC 9(3).
       01  WS-RES    PIC X(2).
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05 IN-CODE PIC X(5).
       PROCEDURE DIVISION.
       P1.
           MOVE IN-CODE TO WS-A
           MOVE 7 TO WS-B
           CALL 'PROGB' USING WS-AREA
           GOBACK.
"""
B = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WK-OUT    PIC X(2).
       LINKAGE SECTION.
       01  LK-AREA.
           05 LK-A   PIC X(5).
           05 LK-B   PIC 9(3).
       PROCEDURE DIVISION USING LK-AREA.
       P1.
           IF LK-B > 5
              EXEC SQL INSERT INTO SCH.TAB (C1, C2)
                 VALUES (:LK-A, :LK-B) END-EXEC
           END-IF
           EXEC SQL SELECT C3 INTO :WK-OUT FROM SCH.TAB2
              WHERE K = :LK-A END-EXEC
           GOBACK.
"""
with tempfile.TemporaryDirectory() as d:
    src = pathlib.Path(d) / 'src'
    src.mkdir()
    (src / 'PROGA.CBL').write_text(A)
    (src / 'PROGB.CBL').write_text(B)
    m = static_model.build(src, pathlib.Path(d) / 'st')
assert m['programs']['PROGB']['ast']['procedure_using'] == ['LK-AREA']
lay = field_lineage.layout(m['programs']['PROGA']['data_model'])
assert lay['root_len']['WS-AREA'] == 8 and [x for x in lay['items']['WS-AREA'] if x[0] == 'WS-B'] == [('WS-B', 5, 8)], lay
fl = data_flow.build(m)
dm = {p: decision_map.build(p, x['ast'], source_line=x['linemap'].source_line, cursors=declared_cursors(x['text'])) for p, x in m['programs'].items()}
lin = field_lineage.build(m, fl, dm)
w = lin['tables']['SCH.TAB']['writes'][0]
cols = {c['column']: c for c in w['columns']}
o1 = cols['C1']['origins'][0]
assert o1['kind'] == 'entrada do entry point' and 'IN-CODE' in o1['name'], o1
assert {s['program'] for s in o1['steps']} >= {'PROGA', 'PROGA→PROGB'}, o1['steps']
assert [(o['kind'], o['name']) for o in cols['C2']['origins']] == [('valor fixo', '7')], cols['C2']
assert w['conditions'] == [[{'code': 'D001', 'condition': 'LK-B > 5', 'result': 'Sim', 'line': w['conditions'][0][0]['line']}]], w['conditions']
r = lin['tables']['SCH.TAB2']['reads'][0]
assert [k['field'] for k in r['keys']] == ['LK-A'] and r['keys'][0]['origins'][0]['kind'] == 'entrada do entry point'
assert r['returns'][0]['column'] == 'C3' and r['returns'][0]['host'] == 'WK-OUT'
assert lin['calls'][0]['area_bytes'] == 8 and lin['calls'][0]['param'] == 'LK-AREA'
print('lineage_campos smoke OK')
