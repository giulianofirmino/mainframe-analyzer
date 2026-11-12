import sys, pathlib, tempfile
ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'semantic_core'))
import static_model
import slice_reach

with tempfile.TemporaryDirectory() as d:
    m = static_model.build(ROOT / 'tests' / 'fixture_slice', pathlib.Path(d) / 'static')
    for x in m['programs'].values():
        x['infrastructure'] = False   # a classificação (folha sem dados = infraestrutura) não é o objeto deste teste: a fatia segue as chamadas dos dois programas
    s = slice_reach.slices(m, 'CHAMADOR')
    assert set(s) == {'CHAMADOR', 'SERVICO'}, set(s)
    sv = s['SERVICO']
    dec = {x['expression']: x for x in m['programs']['SERVICO']['decision_tree']['decisions']}
    a, b = dec["AREA-OPCAO-A EQUAL 'S'"], dec["AREA-OPCAO-B EQUAL 'S'"]
    # o chamador fixa A='S' e deixa B no valor inicial (branco): só TRUE de A e só FALSE de B são alcançáveis
    assert sv['consts'] == {'AREA-OPCAO-A': 'S'}, sv['consts']
    assert sv['branches'] == {(a['decision_id'], 'TRUE'), (b['decision_id'], 'FALSE')}, sv['branches']
    assert '1000-OPCAO-A' in sv['labels'] and '2000-OPCAO-B' not in sv['labels']
    assert sv['paragraphs'][0] < sv['paragraphs'][1]
print('slice_reach smoke OK')
