"""Regras: subtipo pelos campos da condição (validação de entrada, exceção de negócio, com pré-condição, falha técnica) e retorno de sucesso."""
import sys, pathlib, tempfile
ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'semantic_core'))
import static_model, data_flow, decision_map, rule_paths
from dependency_map import declared_cursors

SRC = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WRK-A       PIC X(5).
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05 LNK-ID   PIC 9(5).
           05 LNK-QTD  PIC 9(5).
           05 LNK-RET  PIC 9(2).
       PROCEDURE DIVISION.
       P0.
           IF LNK-ID = ZEROS
              MOVE 08 TO LNK-RET
              GOBACK
           END-IF
           EXEC SQL SELECT COL1 INTO :WRK-A
              FROM SCH.TAB WHERE K = :LNK-ID END-EXEC
           IF SQLCODE NOT = ZEROS AND SQLCODE NOT = +100
              MOVE 12 TO LNK-RET
              GOBACK
           END-IF
           IF SQLCODE = +100 AND LNK-QTD > 5
              MOVE 09 TO LNK-RET
              GOBACK
           END-IF
           IF SQLCODE = +100
              MOVE 07 TO LNK-RET
              GOBACK
           END-IF
           MOVE 00 TO LNK-RET
           GOBACK.
"""
def regras(texto):
    with tempfile.TemporaryDirectory() as d:
        src = pathlib.Path(d) / 'src'
        src.mkdir()
        (src / 'PROGS.CBL').write_text(texto)
        m = static_model.build(src, pathlib.Path(d) / 'st')
    p = m['programs']['PROGS']
    fl = data_flow.build(m)
    dm = {'PROGS': decision_map.build('PROGS', p['ast'], source_line=p['linemap'].source_line, cursors=declared_cursors(p['text']))}
    return rule_paths.build(m, fl, dm)['PROGS']['rules']


rules = regras(SRC)
por = {}
for r in rules:
    v = [e['value'] for e in r['effects'] if e['nature'] == 'valor fixo']
    por[v[0] if v else r['kind']] = r
for ret, sub in (('8', 'validação de entrada'), ('12', 'falha técnica de execução'), ('9', 'exceção de negócio com pré-condição'), ('7', 'exceção de negócio'), ('0', 'retorno de sucesso')):
    k = next((k for k in por if k.lstrip('0') == ret.lstrip('0') or k == ret), None)
    assert k is not None, (ret, list(por))
    assert por[k]['subtype'] == sub, (ret, por[k]['kind'], por[k]['subtype'], por[k]['conditions'])
assert por[next(k for k in por if k.lstrip('0') == '')]['kind'] == 'retorno de sucesso'
# id estrutural: linhas de comentário inseridas acima e no meio do código não mudam o id de nenhuma regra
deslocado = regras(SRC.replace('       P0.\n', '      * comentário\n      * outro\n       P0.\n').replace('           IF SQLCODE = +100\n', '      * mais um\n           IF SQLCODE = +100\n'))
assert sorted(r['rule_id'] for r in rules) == sorted(r['rule_id'] for r in deslocado)
assert [e['line'] for r in rules for e in r['effects']] != [e['line'] for r in deslocado for e in r['effects']]
print('regras_subtipo smoke OK')
