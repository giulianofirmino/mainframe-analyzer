#!/usr/bin/env python3
"""Executor único dos testes: roda cada tests/*_smoke.py e tests/relatorios_equivalencia.py [pasta-das-fases] e resume. Código de saída 1 se algum falhar.
Uso: python3 tests/rodar_todos.py [pasta-das-fases] [--parte=i/n]"""
import subprocess
import sys
import time
from pathlib import Path

R = Path(__file__).resolve().parent
args = [a for a in sys.argv[1:] if not a.startswith('--')]
parte = next((a.split('=')[1] for a in sys.argv[1:] if a.startswith('--parte=')), None)   # --parte=i/n: roda só a i-ésima de n fatias (para shells com limite de tempo)
res = []
alvos = sorted(R.glob('*_smoke.py')) + [R / 'relatorios_equivalencia.py']
if parte:
    i, n = (int(x) for x in parte.split('/'))
    alvos = alvos[i - 1::n]
for t in alvos:
    t0 = time.time()
    cmd = [sys.executable, str(t)] + (args if t.name in ('relatorios_equivalencia.py', 'ligacoes_smoke.py') and args else [])
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    fim = (p.stdout.strip().splitlines() or p.stderr.strip().splitlines() or [''])[-1][:110]
    res.append((t.name, p.returncode, round(time.time() - t0, 1), fim))
    print(('OK  ' if p.returncode == 0 else 'FALHA'), t.name, f'{res[-1][2]}s', fim, flush=True)
falhas = [r for r in res if r[1]]
print(f'{len(res) - len(falhas)}/{len(res)} testes passaram')
sys.exit(1 if falhas else 0)
