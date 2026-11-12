"""Laço do cursor: o PERFORM ... UNTIL (de parágrafo ou em linha) que repete o FETCH é registrado."""
import sys, pathlib, tempfile
ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'semantic_core'))
import static_model, rule_paths

SRC = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WRK-A       PIC X(5).
       PROCEDURE DIVISION.
       P0.
           EXEC SQL DECLARE C1 CURSOR FOR SELECT COL1 FROM SCH.TAB
              END-EXEC
           EXEC SQL OPEN C1 END-EXEC
           PERFORM P1 UNTIL SQLCODE = +100
           EXEC SQL FETCH C1 INTO :WRK-A END-EXEC
           PERFORM UNTIL SQLCODE = +100
              EXEC SQL FETCH C1 INTO :WRK-A END-EXEC
           END-PERFORM
           GOBACK.
       P1.
           EXEC SQL FETCH C1 INTO :WRK-A END-EXEC.
"""
with tempfile.TemporaryDirectory() as d:
    src = pathlib.Path(d) / 'src'
    src.mkdir()
    (src / 'PROGL.CBL').write_text(SRC)
    m = static_model.build(src, pathlib.Path(d) / 'st')
p = m['programs']['PROGL']
lp = rule_paths.cursor_loops(p)
by = {ln: v for ln, v in lp.items()}
assert len(by) == 2, by                      # o FETCH solto, fora de laço, não aparece
fetches = sorted(by)
assert by[fetches[0]]['perform'].startswith('PERFORM UNTIL') and by[fetches[0]]['until'] == 'SQLCODE == +100' or 'SQLCODE' in by[fetches[0]]['until'], by
assert any(v['target'] == 'P1' for v in by.values()) and any(v['target'] == '' for v in by.values()), by
print('cursor_laco smoke OK')
