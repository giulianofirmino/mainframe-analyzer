"""Regras: indicador de nulo, status ligado ao SQL anterior (inclusive via PERFORM), decisão indiferente sai do caminho, nome 88 do valor fixo."""
import sys, pathlib, tempfile
ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'semantic_core'))
import static_model, data_flow, decision_map, rule_paths
from dependency_map import declared_cursors

SRC = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WRK-A       PIC X(5).
       01  WRK-A-IND   PIC S9(4) COMP.
       01  WRK-TIPO    PIC 9(3).
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05 LNK-ID   PIC 9(5).
           05 LNK-RET  PIC 9(2).
              88 ERRO-NEGOCIO VALUE 08.
           05 LNK-OUT  PIC X(5).
       PROCEDURE DIVISION.
       P0.
           IF LNK-ID = ZEROS
              PERFORM P1
           ELSE
              PERFORM P1
           END-IF
           GOBACK.
       P1.
           EXEC SQL SELECT COL1 INTO :WRK-A :WRK-A-IND
              FROM SCH.TAB WHERE K = :LNK-ID END-EXEC
           PERFORM P2
           IF WRK-A-IND < 0
              MOVE SPACES TO LNK-OUT
           END-IF.
       P2.
           IF SQLCODE = +100
              MOVE 08 TO LNK-RET
              GOBACK
           END-IF.
"""
with tempfile.TemporaryDirectory() as d:
    src = pathlib.Path(d) / 'src'
    src.mkdir()
    (src / 'PROGR.CBL').write_text(SRC)
    m = static_model.build(src, pathlib.Path(d) / 'st')
p = m['programs']['PROGR']
fl = data_flow.build(m)
assert fl['PROGR']['indicators'] == {'WRK-A-IND': {'column': 'SCH.TAB.COL1', 'host': 'WRK-A', 'op': 'SELECT', 'line': fl['PROGR']['indicators']['WRK-A-IND']['line']}}
dm = {'PROGR': decision_map.build('PROGR', p['ast'], source_line=p['linemap'].source_line, cursors=declared_cursors(p['text']))}
rules = rule_paths.build(m, fl, dm)['PROGR']['rules']
by = {r['kind']: r for r in rules}
# a decisão da raiz (LNK-ID = ZEROS) não muda nenhum efeito: sai do caminho das regras
assert all('D001' not in r['references'] or r['kind'] == 'x' for r in rules), [r['references'] for r in rules]
nulo = by['derivação']
ind = [c for c in nulo['condition_fields'] if c['role'] == 'indicador de nulo']
assert len(ind) == 1 and ind[0]['column'] == 'COL1', nulo['condition_fields']
# regra funcional de consulta: tabela, colunas devolvidas e WHERE com tabela.campo e origem no código
cons = by['consulta de dados']
e = cons['effects'][0]
assert e['nature'] == 'consulta' and e['target'] == 'SCH.TAB' and e['columns'][0]['column'] == 'COL1' and e['columns'][0]['host'].startswith('WRK-A'), e
w = e['where'][0]
assert (w['table'], w['field'], w['op'], w['hosts']) == ('SCH.TAB', 'K', '=', ['LNK-ID']), w
assert cons['scope']['scope'] == 'negócio' and cons['tables_read'] == ['SCH.TAB']
erro = by['tratamento de erro']
st = [c for c in erro['condition_fields'] if c['role'] == 'status'][0]
assert st['table'] == 'SCH.TAB' and st['lineage_id'].startswith('PROGR@') and erro['ends_flow']
assert erro['effects'][0]['value_name'] == 'ERRO-NEGOCIO', erro['effects'][0]
print('regras_sinais smoke OK')
