"""Fase 4b: origem resumida sem campos de transporte, valor fixo através de variáveis, tabela com link, escolha por condição, transformação e destino."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'semantic_core'))
import lineage_summary as ls  # noqa: E402


def step(op, de, para, prog='P1', line=10, text=None, **k):
    return {'program': prog, 'line': line, 'op': op, 'kind': 'fluxo', 'from': de, 'to': para, 'text': text or f'{op} {de} TO {para}', **k}


def origem(kind, name, steps, when_conds=(), expected=True):
    return {'kind': kind, 'name': name, 'steps': steps, 'when': '', 'when_conds': list(when_conds), 'expected': expected}


C = lambda code, cond, res, prog='P1': {'code': code, 'condition': cond, 'result': res, 'line': 1, 'program': prog}
tecn = {'code': 'D9', 'condition': 'SQLCODE != ZEROS', 'result': 'Não', 'line': 1, 'program': 'P1', 'sql': {'id': 'x'}}
where = [
    {'connector': None, 'column': 'T.A', 'field': 'A', 'op': '=', 'value': ':W-A', 'value_kind': 'campo', 'text': 'T.A = :W-A', 'role': 'filtro', 'value_resolved': ':W-A',
     'origins': [origem('origem não rastreada', 'EP · E-A (AREA-ENT)', [step('MOVE', 'EP · E-A (AREA-ENT)', 'P1 · X1'), step('MOVE', 'P1 · X1', 'P1 · W-A')], expected=False)]},
    {'connector': 'AND', 'column': 'T.B', 'field': 'B', 'op': '=', 'value': ':W-B', 'value_kind': 'campo', 'text': 'T.B = :W-B', 'role': 'filtro', 'value_resolved': ':W-B',
     'origins': [origem('valor fixo', '503', [step('MOVE', '503', 'P1 · T1'), step('MOVE', 'P1 · T1', 'P1 · W-B')])]},
    {'connector': 'AND', 'column': 'T.C', 'field': 'C', 'op': '=', 'value': ':W-C', 'value_kind': 'campo', 'text': 'T.C = :W-C', 'role': 'filtro', 'value_resolved': ':W-C',
     'origins': [origem('valor fixo', '1', [step('MOVE', '1', 'P1 · W-C')], [C('D1', 'E-X > 0', 'Sim'), tecn]),
                 origem('tabela', 'DB2.TAB2.COLC', [step('SELECT', 'DB2.TAB2.COLC', 'P1 · W-C', line=5)], [C('D1', 'E-X > 0', 'Não'), tecn])]},
    {'connector': 'AND', 'column': 'T.D', 'field': 'D', 'op': '=', 'value': ':W-D', 'value_kind': 'campo', 'text': 'T.D = :W-D', 'role': 'filtro', 'value_resolved': ':W-D',
     'origins': [origem('origem não rastreada', 'EP · E-D (AREA-ENT)', [step('MOVE', 'EP · E-D (AREA-ENT)', 'P1 · W-D', text='MOVE E-D(1:3) TO W-D')], expected=False)]},
]
dest = [{'kind': 'saída do programa', 'name': 'P1 · S-A (AREA-SAI)', 'program': 'P1', 'line': 30, 'op': 'MOVE', 'steps': [step('MOVE', 'P1 · COLA', 'P1 · S-A (AREA-SAI)')]}]
lin = {'entry_points': ['EP'], 'tables': {'DB2.T': {'sql': [{'id': 'P1@20:T', 'program': 'P1', 'line': 20, 'statement': 'SELECT', 'sql': 'SELECT', 'where': where, 'entry_points': ['EP']}],
                                          'reads': [{'id': 'P1@20:T', 'program': 'P1', 'line': 20, 'statement': 'SELECT', 'where': where, 'keys': [], 'entry_points': ['EP'],
                                                     'returns': [{'column': 'COLA', 'host': 'COLA', 'use': 'usada', 'destinations': dest}]}], 'writes': []}}}
r = ls.build(lin)
c = r['commands'][0]
a = {e['curto']: e['alternativas'] for e in c['entradas']}
assert a['A = W-A'][0]['tipo'] == 'entrada do entry point' and 'E-A' in a['A = W-A'][0]['resumo'] and a['A = W-A'][0]['copias'] == 2 and not a['A = W-A'][0]['transformacoes']
assert a['B = W-B'][0]['tipo'] == 'valor fixo' and a['B = W-B'][0]['valor'] == '503'
c3 = a['C = W-C']
assert [x['tipo'] for x in c3] == ['valor fixo', 'tabela lida'] and c3[1]['ref_sql'] == 'P1@5:TAB2'
assert c3[0]['quando'] == ['P1:D1 se E-X > 0'] and c3[1]['quando'] == ['P1:D1 senão (E-X > 0)'], c3   # a condição de status (SQLCODE) não escolhe valor
assert a['D = W-D'][0]['transformacoes'] and 'E-D(1:3)' in a['D = W-D'][0]['resumo']
d = c['saidas'][0]['destinos'][0]
assert d['tipo'] == 'saída do programa' and d['campo'] == 'S-A' and not d['transformacoes']
# cursor: DECLARE (condições) e FETCH (colunas lidas) viram um comando só
lin2 = {'entry_points': ['EP'], 'tables': {'DB2.T': {'sql': [{'id': 'P1@20:T', 'program': 'P1', 'line': 20, 'statement': 'SELECT', 'cursor': 'C1', 'sql': 'S', 'where': where, 'entry_points': ['EP']}],
        'reads': [{'id': 'P1@40:T', 'program': 'P1', 'line': 40, 'statement': 'FETCH', 'cursor': 'C1', 'where': [], 'keys': [], 'entry_points': ['EP'],
                   'returns': [{'column': 'COLA', 'host': 'COLA', 'use': 'usada', 'destinations': dest}]}], 'writes': []}}}
r2 = ls.build(lin2, classes={'P1': 'FUNCIONAL'})
assert len(r2['commands']) == 1 and r2['commands'][0]['ids'] == ['P1@20:T', 'P1@40:T'] and r2['commands'][0]['linhas'] == [20, 40] and r2['commands'][0]['entradas'] and r2['commands'][0]['saidas']
# novos campos: parte do SQL, trecho, percurso entre programas, condições de execução
assert all(e['grupo'] == 'where' and e['parte'] == 'WHERE' and e['fragmento'] for e in c['entradas'])
assert a['A = W-A'][0]['percurso'] == ['P1'] or 'P1' in a['A = W-A'][0]['percurso']
# campo como parâmetro (INSERT VALUES) e comando de gravação
w_ = {'id': 'P1@50:T', 'program': 'P1', 'line': 50, 'statement': 'INSERT', 'entry_points': ['EP'], 'conditions': [[C('D2', 'E-Y = 1', 'Sim'), tecn]],
      'columns': [{'column': 'COLX', 'op': 'INSERT', 'value': ':W-X', 'origins': [origem('valor fixo', '7', [step('MOVE', '7', 'P1 · W-X')])]}]}
r3 = ls.build({'entry_points': ['EP'], 'tables': {'DB2.T': {'sql': [], 'reads': [], 'writes': [w_]}}, 'calls': [{'caller': 'EP', 'callee': 'P1', 'line': 3, 'mechanism': 'LINK'}]})
c4 = r3['commands'][0]
assert c4['entradas'][0]['grupo'] == 'campos' and c4['entradas'][0]['parte'] == 'VALUES' and 'COLX' in c4['entradas'][0]['fragmento']
assert c4['executa_quando'][0][0]['codigo'] == 'D2' and c4['executa_quando'][0][1]['tecnica'] is True
# o modelo da página nasce só do resultado (sem execução dinâmica nada fica cinza; com a execução, o comando não executado fica em cinza)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'semantic_core'))
import report_resumo as rs  # noqa: E402
m = rs.m_resumo(r2, {})
secs = {x['id']: x for x in m['sections']}
assert 'rp-P1' in secs and any(b.get('row_ids') and 'cmd-P1@20:T' in b['row_ids'] for b in secs['rp-P1']['blocks'] if b['type'] == 'table')
assert not any(n.get('inactive') for b in secs['rp-P1']['blocks'] if b['type'] == 'graph' for n in b['nodes'])
import report_maps as mp  # noqa: E402
ctx = {'rt': {'coverage_by_program': {}}, 'scenarios': [{'res': {'executed_programs': ['P1'], 'sql': [{'program': 'P1', 'line': 99}]}}]}
m2 = rs.m_resumo(r2, ctx)
g = [b for b in {x['id']: x for x in m2['sections']}['rp-P1']['blocks'] if b['type'] == 'graph' and b['title'].startswith('Fluxo')][0]
assert any(n.get('inactive') for n in g['nodes']) and g['toggle_label']
print('lineage_summary smoke OK')
