import sys, pathlib, tempfile
ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'semantic_core'))
import static_model
import scenario_runner as sr

FIX = ROOT / 'tests' / 'fixture_runtime'
with tempfile.TemporaryDirectory() as d:
    m = static_model.build(FIX, pathlib.Path(d) / 'static')

    # análise estática refeita a partir dos fontes: copybook expandido, destinos resolvidos por VALUE
    assert m['entry_points'] == ['ENTRADA'] and m['externals'] == ['EXTERNO9'] and not m['missing_copybooks']
    assert m['programs']['INFRA01']['infrastructure'] is True
    ev = next(x for x in m['programs']['ENTRADA']['decision_tree']['decisions'] if x['type'] == 'EVALUATE')
    assert ev['branches'][0].get('falls_through_to') == 'WHEN_2'

    base = {'entry_point': 'ENTRADA', 'inputs': {'EIBCALEN': 1, 'CLI-ID': 7},
            'tables': {'DB2PRD.TCLI': [{'ID': 7, 'NOME': 'ANA'}]}}

    # 1. WHEN empilhado (OPC-CONSULTA cai no corpo de OPC-LISTA); infra e externo mockados pela política
    r = sr.run_scenario(m, {**base, 'name': 'consulta', 'inputs': {**base['inputs'], 'OPCAO': 'C'},
                            'expected': {'outputs': {'RETORNO': 0, 'NOME': 'ANA'}, 'calls': ['NEGOCIO1'],
                                         'path': [{'program': 'ENTRADA', 'line': 18, 'result': 'WHEN_1'},
                                                  {'program': 'NEGOCIO1', 'line': 13, 'result': True}]}}, d)
    assert r['status'] == 'PASS', r['checks']
    assert r['deterministic'] and r['static_consistency'] == 'CONSISTENTE', r['divergences']
    assert r['mock_plan']['INFRA01']['reason'] == 'INFRAESTRUTURA' and r['mock_plan']['EXTERNO9']['reason'] == 'EXTERNO'
    assert r['executed_programs'] == ['ENTRADA', 'NEGOCIO1'] and set(r['mocks_used']) == {'INFRA01', 'EXTERNO9'}
    assert r['business_rules_exercised']
    assert (pathlib.Path(d) / 'consulta' / 'trace.log').exists()

    # 2. cliente inexistente: SQLCODE 100 -> ramo FALSE, externo não chamado
    r = sr.run_scenario(m, {**base, 'name': 'inexistente', 'inputs': {**base['inputs'], 'OPCAO': 'L', 'CLI-ID': 9},
                            'expected': {'outputs': {'RETORNO': 4}, 'not_calls': ['EXTERNO9']}}, d)
    assert r['status'] == 'PASS', r['checks']

    # 3. saída esperada errada é reprovada com DIFF
    r = sr.run_scenario(m, {**base, 'name': 'errado', 'inputs': {**base['inputs'], 'OPCAO': 'I'},
                            'expected': {'outputs': {'RETORNO': 0}}}, d)
    assert r['status'] == 'FAIL' and any(c['result'] == 'DIFF' and c.get('name') == 'RETORNO' for c in r['checks'])

    # 4. mock definido no cenário, com 'when' e padrão; 'execute' força rodar a infraestrutura real
    r = sr.run_scenario(m, {**base, 'name': 'mock-when', 'inputs': {**base['inputs'], 'OPCAO': 'C'},
                            'mocks': {'NEGOCIO1': {'scenarios': [{'when': {'CLI-ID': 7}, 'returns': {'NOME': 'MOCKADA', 'RETORNO': 0}}],
                                                   'default': {'returns': {'RETORNO': 4}}}},
                            'execute': ['INFRA01'],
                            'expected': {'outputs': {'NOME': 'MOCKADA'}, 'calls': ['NEGOCIO1', 'INFRA01']}}, d)
    assert r['status'] == 'PASS', r['checks']
    assert 'INFRA01' in r['executed_programs'] and r['mocks_used'] == ['NEGOCIO1']

    # 5. commarea vazia: sai na primeira decisão
    r = sr.run_scenario(m, {**base, 'name': 'sem-commarea', 'inputs': {'EIBCALEN': 0},
                            'expected': {'outputs': {'RETORNO': 99}, 'not_calls': ['INFRA01']}}, d)
    assert r['status'] == 'PASS', r['checks']

    # 6. tabela/coluna do cenário conferida contra DCLGEN (não há DCLGEN no fixture -> sem avisos)
    assert not [w for w in r['warnings'] if w['type'].startswith('TABELA')]

    # 7. cobertura agregada e modelo de cenário
    agg = sr.aggregate(m, [sr.run_scenario(m, {**base, 'name': n, 'inputs': {**base['inputs'], 'OPCAO': o}}, d)
                           for n, o in (('a', 'C'), ('b', 'L'), ('c', 'I'), ('d', 'X'))])
    cov = agg['coverage_by_program']['ENTRADA']
    assert cov['branches'] == 6 and cov['branches_exercised'] == 5  # falta só EIBCALEN = 0
    t = sr.template(m, 'ENTRADA')
    assert 'OPCAO' in t['_entradas_candidatas'] and 'OPC-LISTA' in t['_opcoes_88_nas_entradas'] and 'INFRA01' in t['mocks']

# 8. a validação acusa divergências (caminho fabricado que a análise estática não conhece)
v = sr.validate_against_static(m, {'branches': [{'program': 'ENTRADA', 'line': 9999, 'result': 'TRUE'}],
                                  'calls': [{'caller': 'ENTRADA', 'line': 9998, 'mechanism': 'CALL', 'target': 'X', 'mode': 'REAL'}],
                                  'sql': [{'program': 'NEGOCIO1', 'line': 9997}]})
assert {'DECISAO_SEM_CORRESPONDENTE_ESTATICO', 'CHAMADA_NAO_PREVISTA', 'SQL_NAO_PREVISTO'} <= {d['type'] for d in v['divergences']}

# 9. referência qualificada nas saídas e variável indicadora no SQL
assert sr.lookup({'RETORNO': 0}, 'RETORNO OF DFHCOMMAREA') == (True, 0)
assert sr.lookup({'TCAPB080.NPLANO_CAPTZ': 1}, 'NPLANO-CAPTZ OF TCAPB080') == (True, 1)
from db2_stateful_runtime import hv
assert hv(':A.X :IND', {'A.X': 5, 'IND': -1}) is None and hv(':A.X:IND', {'A.X': 5, 'IND': 0}) == 5
assert hv(':GRP.CAMPO', {'CAMPO': 7}) == 7

print('PASS SCENARIO RUNNER')
