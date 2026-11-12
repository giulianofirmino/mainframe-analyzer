#!/usr/bin/env python3
"""Experimento (análise separada): relação completa entre programas, comandos SQL e tabelas sobre a fase 1, com o que a execução dinâmica não alcançou em cinza.

Uso: gerar_experimento_dependencias.py <analise-de-origem> <pasta-de-saida>
  <analise-de-origem>: pasta de uma análise (tem 00-program-classification, 01-discovery-dependencies e runtime/); só é lida.
  <pasta-de-saida>:    recebe 01x-dependencies-sql/{human/report.html, ia/report.json}; a análise de origem não é alterada.
Determinístico e repetível: o relatório vem só dos resultados estruturados das fases 0 e 1 e do modelo estático e dos cenários do runtime."""
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R / 'semantic_core'))
sys.path.insert(0, str(R / 'tools'))
import gerar_relatorios as gr  # noqa: E402
import report_deps_sql as rds  # noqa: E402

STEP = '01x-dependencies-sql'


def gerar(origem, saida):
    origem, saida = Path(origem), Path(saida)
    phase = {d.name: gr._load(d / 'ia' / 'result.json') for d in sorted(origem.iterdir()) if d.is_dir() and (d / 'ia' / 'result.json').exists()}
    runtime = origem / 'runtime'
    runtime = runtime if runtime.exists() else None
    rt = gr._load(runtime / 'runtime-validation.json') if runtime else None
    static = gr._load(runtime / 'static' / 'static-model.json') if runtime else None
    fontes = {}
    for prog, x in ((static or {}).get('programs') or {}).items():   # fontes com os copybooks expandidos, para ler cursor (DECLARE) e montar SQL dinâmico
        f = runtime / 'static' / x['expanded_file'] if runtime and x.get('expanded_file') else None
        if f and f.exists():
            fontes[prog] = f.read_text(encoding='utf-8', errors='replace')
    ctx = {'fontes': fontes, 'phase': phase, 'static': static or {'call_graph': [], 'programs': {}}, 'rt': rt, 'scenarios': gr._scenarios(runtime), 'eps': None}
    gr._write(saida / STEP, STEP, rds.m_dependencias_sql(phase['01-discovery-dependencies'], ctx))
    return saida / STEP


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    d = gerar(sys.argv[1], sys.argv[2])
    e = gr.verificar(d)
    print(('OK  ' if not e else 'ERRO ') + str(d) + ' ' + '; '.join(e))
    raise SystemExit(1 if e else 0)
