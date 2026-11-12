"""Cursor ligado à tabela, fluxo de dados por tokens e regras por caminho de decisão, sobre um programa mínimo."""
import sys, pathlib, tempfile
ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'semantic_core'))
import static_model, data_flow, rule_paths

with tempfile.TemporaryDirectory() as d:
    m = static_model.build(ROOT / 'tests' / 'fixture_flow', pathlib.Path(d) / 'static')
p = m['programs']['PROGX']
dep = p['dependencies']
assert [c['cursor'] for c in dep['cursors']] == ['CSR-PESSOA'] and dep['cursors'][0]['tables'] == ['ESQ.TB_PESSOA']
assert dep['tables'] == ['ESQ.TB_PESSOA'], dep['tables']          # o cursor não vira tabela
assert {a['operation'] for a in dep['table_access']} == {'OPEN', 'FETCH', 'CLOSE'}
fl = data_flow.build(m)['PROGX']
assert fl['inputs'] == ['DFHCOMMAREA']
fetch = [f for f in fl['flows'] if f['op'] == 'FETCH']
assert [(f['from'][0]['name'], f['to']['name']) for f in fetch] == [('ESQ.TB_PESSOA.ID_PESSOA', 'WRK-ID'), ('ESQ.TB_PESSOA.NM_PESSOA', 'WRK-NOME')], fetch
import decision_map
from dependency_map import declared_cursors
from readable_code import Namer
g, pre = decision_map.group_names(p)
dm = {'PROGX': decision_map.build('PROGX', p['ast'], g, p['linemap'].source_line, pre, declared_cursors(p['text']))}
rules = rule_paths.build(m, {'PROGX': fl}, dm, {'PROGX': Namer(g, pre)})['PROGX']['rules']
by = {tuple((c['code'], c['condition'], c['result']) for c in r['conditions']): r for r in rules}
sem_id = by[(('D001', 'LNK-ID == ZEROS', 'Sim'),)]
assert {e['target_group'] for e in sem_id['effects']} == {'DFHCOMMAREA'} and sem_id['kind'] == 'validação', sem_id['kind']
assert sem_id['references'] == ['D001'] and sem_id['code'].startswith('R')
# o que vem depois do IF que encerra o programa só roda com a condição negada
erro = by[(('D001', 'LNK-ID == ZEROS', 'Não'), ('D002', 'SQLCODE != ZEROS', 'Sim'))]
assert erro['kind'] == 'tratamento de erro', erro['kind']
# o mapa de decisão traz os comandos legíveis, sem cortar
boxes = {r['code']: r['text'] for r in dm['PROGX']['rows'] if r['kind'] == 'execução'}
assert boxes['E002'] == ['LNK-RET = 08', 'LNK-MSG = "SEM-ID"'] and boxes['E003'] == ['CICS RETURN'], boxes
print('fluxo_regras smoke OK')
