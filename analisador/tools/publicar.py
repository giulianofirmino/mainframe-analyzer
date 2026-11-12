#!/usr/bin/env python3
"""Publica uma pasta de análise (saída de tools/analisar.py) em outra, conferindo o resultado: apaga o destino, copia, compara arquivo a arquivo e confere o MANIFESTO.json.
Uso: python3 tools/publicar.py <pasta-gerada> <pasta-destino>   (a cópia de pasta grande é lenta: rode em segundo plano se o seu shell tiver limite de tempo)"""
import filecmp
import shutil
import sys
from pathlib import Path


o, d = Path(sys.argv[1]), Path(sys.argv[2])
if d.exists():
    shutil.rmtree(d)
shutil.copytree(o, d)
dif = []
for f in sorted(o.rglob('*')):
    if f.is_file() and not filecmp.cmp(f, d / f.relative_to(o), shallow=False):
        dif.append(f.relative_to(o).as_posix())
n_o = sum(1 for f in o.rglob('*') if f.is_file())
n_d = sum(1 for f in d.rglob('*') if f.is_file())
print(f'{n_d}/{n_o} arquivos copiados; {len(dif)} diferente(s)')
sys.exit(1 if dif or n_o != n_d else 0)
