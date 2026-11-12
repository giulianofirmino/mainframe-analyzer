"""Scripts e prompts não podem ter nada amarrado ao código analisado.
Lê da pasta de resultados os nomes de programas, tabelas e o prefixo do core business e, quando a análise tem as fases 19 e 20, também as aplicações,
os programas e copybooks novos, as filas e os recursos REST dos contratos; falha se algum aparece em script ou prompt (motor, fases de IA e pipeline).
Uso: python3 tests/agnostico_smoke.py [pasta-das-fases]   (padrão: analises/tcap-codigo)"""
import json
import re
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[1]
base = Path(sys.argv[1]) if len(sys.argv) > 1 else R.parent / 'analises' / 'tcap-codigo'
progs = {p['program'] for p in json.loads((base / 'phase-0-program-classification.json').read_text(encoding='utf-8'))['programs']}
tabs = set()
cat = base / 'dclgen-catalog.json'
if cat.exists():
    for t in json.loads(cat.read_text(encoding='utf-8'))['tables']:
        tabs.add(t.split('.')[-1])
        tabs.add(t)
prefixos = set()
for p in sorted(progs):
    prefixos.add(p[:4])
recorte = set()   # nomes do recorte que a arquitetura alvo criou: aplicações, programas e copybooks novos, filas e recursos REST dos contratos


def _texto(c):
    return c.get('text', '') if isinstance(c, dict) else str(c)


for fase, titulo, colunas in (('19 - target-architecture', 'Modelo de recursos aprovados', ('Id',)),
                              ('19 - target-architecture', 'Comandos SQL: fila de pedido, programa e fila de resposta',
                               ('MQ_REQ', 'MQ_RSP', 'Copybook de requisição', 'PROGRAM_DB2 ou PROGRAM_CORP', 'Copybook de resposta'))):
    f = base / fase / 'ia' / 'report.json'
    if f.exists():
        for sec in json.loads(f.read_text(encoding='utf-8'))['sections']:
            for b in sec['blocks']:
                if b['type'] == 'table' and b['title'] == titulo:
                    for r in b['rows']:
                        recorte |= {_texto(r[b['columns'].index(c)]) for c in colunas if c in b['columns']}
for f in (base / '20 - contracts' / 'ia' / 'contracts').glob('*/*.yaml'):
    recorte |= {seg for cam in re.findall(r'^  (/[^:]+):', f.read_text(encoding='utf-8'), re.M) for seg in cam.split('/') if '-' in seg}
nomes = {n for n in progs | tabs | recorte if len(n) >= 5 and ' ' not in n}
FASES = R / 'fases'
PIPELINE = R.parent / 'pipeline' / 'src'
ARQUIVOS = [f for pasta in (R / 'semantic_core', R / 'tools', FASES, FASES / 'prompts') for f in pasta.glob('*') if f.suffix in ('.py', '.md')]
ARQUIVOS += [f for f in R.glob('*.py')] + [f for f in PIPELINE.rglob('*.py')]
EXCETO = {'gen_cenarios_qal_real.py', 'gerar_experimento_dependencias.py'}   # geradores de cenário e experimento desta base, fora do pipeline de análise
achados = []
for f in ARQUIVOS:
    if f.name in EXCETO:
        continue
    txt = f.read_text(encoding='utf-8', errors='ignore')
    for n in sorted(nomes):
        if re.search(r'(?<![A-Za-z0-9_-])' + re.escape(n) + r'(?![A-Za-z0-9_])', txt):
            achados.append((str(f.relative_to(R.parent)), n))
    for pre in prefixos:
        if len(pre) == 4 and re.search(r'(?<![A-Za-z0-9])' + pre + r'[A-Z0-9]{1,6}(?![A-Za-z0-9])', txt) and pre in {p[:4] for p in progs}:
            m = re.search(r'(?<![A-Za-z0-9])' + pre + r'[A-Z0-9]{1,6}(?![A-Za-z0-9])', txt)
            achados.append((str(f.relative_to(R.parent)), m.group(0)))
achados = sorted(set(achados))
for a in achados:
    print('AMARRADO', *a)
assert not achados, f'{len(achados)} nome(s) do código analisado em scripts ou prompts'
print(f'OK agnóstico: {len(ARQUIVOS)} arquivos, {len(nomes)} nomes do código analisado, nenhum encontrado')
