"""Referências cruzadas entre relatórios (report_render.ligar) sobre relatórios sintéticos: nomes sem significado para o analisador."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'semantic_core'))
import report_render as rr


def T(title, cols, rows):
    return {'type': 'table', 'title': title, 'columns': cols, 'rows': rows, 'note': None}


def modelo(fase, secoes):
    return {'title': fase, 'subtitle': '', 'summary': [], 'sections': [{'id': i, 'title': i, 'text': None, 'blocks': b} for i, b in secoes], 'phase': fase}


def grava(pasta, fase, m):
    (pasta / fase / 'ia').mkdir(parents=True)
    (pasta / fase / 'human').mkdir(parents=True)
    (pasta / fase / 'ia' / 'report.json').write_text(json.dumps(m), encoding='utf-8')


with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    grava(d, '00-program-classification', modelo('00-program-classification', [('t', [T('Programas', ['Programa', 'Classe'], [['PROGA', 'x'], ['PROGB', 'y']])])]))
    grava(d, '03-data-schema', modelo('03-data-schema', [('colunas', [T('Colunas por tabela: tipo', ['Tabela', 'Coluna'], [['TABX_Y', 'C1'], ['TABX_Y', 'C2']])])]))
    grava(d, '04-data-lineage', modelo('04-data-lineage', [('tab-TABX_Y', [])]))
    grava(d, '05-decision-map', modelo('05-decision-map', [('prog-PROGA', [T('Mapa de decisão — PROGA', ['Código', 'Condição'], [['PROGA:D001', 'CAMPO == 1'], ['PROGA:E001', 'x']])])]))
    grava(d, '06-deterministic-rules', modelo('06-deterministic-rules', [('r', [T('Regras de PROGA', ['Regra', 'Condições'], [['R001', 'PROGA:D001 → Sim em PROGB, programa PROGA, tabela TABX_Y']])])]))
    grava(d, '11 - business-rules', modelo('11 - business-rules', [('x', [T('Regras', ['Regra', 'Programa', 'Regras determinísticas'], [['G1', 'PROGB', 'PROGA:R001 e PROGB:R001']])])]))
    n = rr.ligar(d)
    assert n > 0
    assert rr.ligar(d) == 0, 'ligar não pode duplicar links'
    m = json.loads((d / '06-deterministic-rules' / 'ia' / 'report.json').read_text(encoding='utf-8'))
    c = m['sections'][0]['blocks'][0]['rows'][0][1]
    alvos = {(p['phase'], p['anchor']) for p in c['parts'] if isinstance(p, dict)}
    assert ('05-decision-map', 'decisao-PROGA-D001') in alvos and ('00-program-classification', 'programa-PROGB') in alvos and ('03-data-schema', 'tabela-TABX_Y') in alvos and ('05-decision-map', 'prog-PROGA') in alvos
    assert m['sections'][0]['blocks'][0]['row_ids'] == ['regra-PROGA-R001']
    b = json.loads((d / '11 - business-rules' / 'ia' / 'report.json').read_text(encoding='utf-8'))['sections'][0]['blocks'][0]['rows'][0]
    assert {('06-deterministic-rules', 'regra-PROGA-R001')} == {(p['phase'], p['anchor']) for p in b[2]['parts'] if isinstance(p, dict) and p['phase'].startswith('06')}
    assert b[1]['parts'][0]['anchor'] == 'programa-PROGB'
    mp = json.loads((d / '00-program-classification' / 'ia' / 'report.json').read_text(encoding='utf-8'))['sections'][0]['blocks'][0]
    assert mp['rows'][0][0]['parts'][0]['anchor'] == 'prog-PROGA', 'todo link de programa aponta para o mapa de decisões do programa'
    assert mp['rows'][1][0] == 'PROGB' or mp['rows'][1][0]['parts'][0]['anchor'] == 'programa-PROGB'
print('OK referências cruzadas ligadas')
