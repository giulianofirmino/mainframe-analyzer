"""Os relatórios das fases não dependem da ordem de iteração de conjuntos (PYTHONHASHSEED).
Regera os relatórios (tools/gerar_relatorios.py) três vezes com sementes diferentes sobre uma pasta de resultados e compara o hash de todos os ia/report.json.
Uso: python3 tests/determinismo_hashseed.py <pasta-das-fases>   (a pasta é regerada no lugar: use uma cópia de trabalho)"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[1]
pasta = Path(sys.argv[1])
hashes = []
for semente in ('1', '2', '3'):
    subprocess.run([sys.executable, str(R / 'tools' / 'gerar_relatorios.py'), str(pasta)], env={**os.environ, 'PYTHONHASHSEED': semente, 'ANALISE_RAIZ': str(R)}, check=True, capture_output=True)
    h = hashlib.sha256()
    for f in sorted(pasta.glob('*/ia/report.json')):
        h.update(f.name.encode() + f.parent.parent.name.encode() + f.read_bytes())
    hashes.append(h.hexdigest())
assert len(set(hashes)) == 1, ('relatórios dependem da semente de hash', hashes)
print('OK determinismo: 3 sementes de hash, relatórios idênticos')
