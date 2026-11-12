import sys, pathlib, tempfile
ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'semantic_core'))
import static_model
import scenario_runner as sr
from io_deduction import resolve_tags

FIX = ROOT / 'tests' / 'fixture_missing'
assert resolve_tags({'flag'}) == 'flag' and resolve_tags({'num', 'str'}) == 'str' and resolve_tags({'str', 'arith'}) == 'num'
assert resolve_tags({'numtest'}) == 'num' and resolve_tags(set()) is None

with tempfile.TemporaryDirectory() as d:
    m = static_model.build(FIX, pathlib.Path(d) / 'static')
    io = m['programs']['VALID01']['io']
    f = {x['name']: x for x in io['fields']}

    # o que é deduzido, com tipo pelo uso e copybook ausente
    assert set(m['missing_copybooks']) == {'MISSCPY', 'MISSDCL'}
    assert (f['MISSCPY-STATUS']['kind'], f['MISSCPY-QTD']['kind'], f['MISSCPY-ATIVO']['kind'], f['MISSCPY-CONT']['kind'],
            f['MISSCPY-RESULTADO']['kind']) == ('str', 'num', 'flag', 'num', 'str')
    assert f['MISSCPY-STATUS']['default'] == ' ' and f['MISSCPY-QTD']['default'] == 0 and f['MISSCPY-ATIVO']['default'] is False
    assert f['MISSCPY-STATUS']['copybook'] == 'MISSCPY' and f['MISSCPY-STATUS']['attribution'] == 'PREFIXO'
    assert any('SPACES' in e for e in f['MISSCPY-STATUS']['evidence'])
    # estrutura DCLGEN ausente: atribuída pelo qualificador, tipo pela coluna de mesmo nome em outra DCLGEN
    assert f['K-ID']['copybook'] == 'MISSDCL' and f['K-ID']['attribution'] == 'QUALIFICADOR' and f['K-ID']['kind'] == 'num'
    assert any('K_ID' in e for e in f['K-ID']['evidence']) and f['K-NOME']['kind'] == 'str'
    # nomes do runtime (EIB, SQLCODE) e declarados no fonte não são "deduzidos"
    assert not {'EIBCALEN', 'SQLCODE', 'WRK-OK', 'DFHCOMMAREA'} & set(f)
    assert 'MISSCPY-STATUS' in io['inputs'] and 'MISSCPY-RESULTADO' in io['outputs'] and 'MISSCPY-RESULTADO' not in io['inputs']

    base = {'entry_point': 'VALID01', 'inputs': {'EIBCALEN': 1, 'K-ID': 7},
            'tables': {'DB2PRD.TK': [{'K_ID': 7, 'K_NOME': 'ANA'}]}}

    # 1. entradas deduzidas são usadas: SPACES compara igual, ZEROS compara igual, flag fica falso
    r = sr.run_scenario(m, {**base, 'name': 'deduz', 'expected': {'outputs': {'WRK-OK': 'S', 'MISSCPY-RESULTADO': 'Z', 'MISSCPY-CONT': 0,
                                                                              'K-NOME OF MISSDCL': 'ANA'}}}, d)
    assert r['status'] == 'PASS', r['checks']
    w = {x['copybook']: x for x in r['warnings'] if x['type'] == 'COPYBOOK_AUSENTE_CAMPOS_DEDUZIDOS'}
    assert set(w) == {'MISSCPY', 'MISSDCL'}
    assert {'MISSCPY-STATUS', 'MISSCPY-QTD', 'MISSCPY-ATIVO'} <= set(w['MISSCPY']['inputs'])
    assert {'MISSCPY-RESULTADO', 'MISSCPY-CONT'} <= set(w['MISSCPY']['outputs']) and w['MISSDCL']['outputs'] == ['K-NOME']
    assert 'DEDUZIDAS' in w['MISSCPY']['detail'] and 'MISSCPY' in w['MISSCPY']['detail']
    ins = {i['field']: i for i in r['io']['inputs']}
    assert ins['MISSCPY-STATUS']['origin'] == 'DEDUZIDO' and ins['MISSCPY-STATUS']['initial'] == ' ' and ins['K-ID']['origin'] == 'CENARIO'
    outs = {o['field']: o for o in r['io']['outputs']}
    assert outs['MISSCPY-RESULTADO']['final_value'] == 'Z' and outs['K-NOME']['final_value'] == 'ANA'
    # saída esperada em campo sem declaração vira aviso
    assert any(x['type'] == 'SAIDA_ESPERADA_EM_CAMPO_DEDUZIDO' for x in r['warnings'])

    # 2. sem dedução o comportamento muda (0 não é igual a SPACES): o resultado esperado falha
    r = sr.run_scenario(m, {**base, 'name': 'sem-deduz', 'deduce_inputs': False, 'expected': {'outputs': {'WRK-OK': 'S'}}}, d)
    assert r['status'] == 'FAIL' and not [x for x in r['warnings'] if x['type'] == 'COPYBOOK_AUSENTE_CAMPOS_DEDUZIDOS']

    # 3. o que o cenário informa prevalece sobre o deduzido
    r = sr.run_scenario(m, {**base, 'name': 'informado', 'inputs': {**base['inputs'], 'MISSCPY-ATIVO': True, 'MISSCPY-STATUS': 'X'},
                            'expected': {'outputs': {'WRK-OK': 'N', 'MISSCPY-CONT': 1}}}, d)
    assert r['status'] == 'PASS', r['checks']
    ins = {i['field']: i for i in r['io']['inputs']}
    assert ins['MISSCPY-ATIVO']['origin'] == 'CENARIO' and ins['MISSCPY-STATUS']['origin'] == 'CENARIO'

    # 4. modelo de cenário lista as entradas e saídas deduzidas
    t = sr.template(m, 'VALID01')
    assert {'MISSCPY-STATUS', 'MISSCPY-QTD'} <= {x['campo'] for x in t['_entradas_deduzidas']}
    assert 'MISSCPY-RESULTADO' in {x['campo'] for x in t['_saidas_deduzidas']} and t['deduce_inputs'] is True

print('PASS IO DEDUCTION')
