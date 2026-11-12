"""Regras da fase 0 e refinamento da fase 6 sobre programas sintéticos (nomes sem significado para o analisador)."""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'semantic_core'))
import static_model

HEAD = '       IDENTIFICATION DIVISION.\n       PROGRAM-ID. {n}.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n       01 WS-A PIC X(5).\n       01 WS-B PIC 9(3).\n       PROCEDURE DIVISION.\n{b}\n           GOBACK.\n'
SQL = "           EXEC SQL SELECT A INTO :WS-A FROM {t} END-EXEC\n"
PROGS = {
    'AAA1': "           CALL 'BBB1'\n           CALL 'BBB2'\n           CALL 'BBB3'\n",           # coordena
    'BBB1': SQL.format(t='T1') + "           CALL 'CCC1'\n",                                   # funcional (chamado por coordenador) que chama CCC1
    'BBB2': SQL.format(t='T2') + "           CALL 'DDD1'\n",
    'BBB3': SQL.format(t='T3'),
    'CCC1': SQL.format(t='T4') + "           CALL 'EEE1'\n",                                   # chamado por FUNCIONAL, um único chamador -> corporativo
    'DDD1': SQL.format(t='T5'),                                                                 # idem
    'EEE1': "           MOVE 1 TO WS-B\n           IF WS-B > 0 MOVE 2 TO WS-B END-IF\n",       # fim do fluxo, sem dados -> infraestrutura
}
with tempfile.TemporaryDirectory() as d:
    for n, b in PROGS.items():
        (Path(d) / f'{n}.CBL').write_text(HEAD.format(n=n, b=b))
    m = static_model.build(Path(d))
c = {p: x['classification'] for p, x in m['programs'].items()}
got = {p: (x['classification'], x['phase0_classification']) for p, x in c.items()}
print(got)
assert got['AAA1'][0] == 'COORDENADOR'
assert got['BBB1'][0] == got['BBB2'][0] == got['BBB3'][0] == 'FUNCIONAL'
assert got['CCC1'][0] == 'CORPORATIVO' and got['DDD1'][0] == 'CORPORATIVO'
assert got['EEE1'] == ('INFRAESTRUTURA', 'FUNCIONAL') and c['EEE1']['refinement']['from'] == 'FUNCIONAL'
assert m['programs']['EEE1']['infrastructure'] is True
assert got['AAA1'][1] == 'COORDENADOR' and 'ponto de entrada' in c['AAA1']['criterion']
print('OK classificação')

# prefixo do core business (ANALISE_PREFIXO_CORE): programa sem o prefixo só pode ser CORPORATIVO ou INFRAESTRUTURA
os.environ['ANALISE_PREFIXO_CORE'] = 'BBB'
try:
    with tempfile.TemporaryDirectory() as d:
        for n, b in PROGS.items():
            (Path(d) / f'{n}.CBL').write_text(HEAD.format(n=n, b=b))
        m2 = static_model.build(Path(d))
finally:
    del os.environ['ANALISE_PREFIXO_CORE']
c2 = {p: x['classification'] for p, x in m2['programs'].items()}
got2 = {p: x['classification'] for p, x in c2.items()}
print(got2)
assert got2['AAA1'] == 'CORPORATIVO' and 'fora do core business' in c2['AAA1']['criterion']      # ponto de entrada sem o prefixo não é coordenador
assert got2['BBB1'] == got2['BBB2'] == got2['BBB3'] == 'FUNCIONAL'                                # com o prefixo, a regra normal vale
assert got2['CCC1'] == 'CORPORATIVO' and got2['DDD1'] == 'CORPORATIVO'
assert got2['EEE1'] == 'INFRAESTRUTURA'
assert all(v in ('CORPORATIVO', 'INFRAESTRUTURA') for p, v in got2.items() if not p.startswith('BBB'))
print('OK classificação com prefixo do core business')
