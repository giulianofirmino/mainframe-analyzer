"""IA (ia/report.json) e humano (human/report.html) carregam a mesma informação, e o HTML não tem JSON.
Uso: python3 tests/relatorios_equivalencia.py [pasta-das-fases] [pasta-do-runtime]  (padrão: analises/tcap-codigo)"""
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R / 'tools'))
sys.path.insert(0, str(R / 'semantic_core'))
import gerar_relatorios as gr  # noqa: E402
import report_render as rr  # noqa: E402

# 1) fixture sintética: texto de dict/lista sai legível, nunca JSON
m = {'title': 't', 'subtitle': '', 'summary': [], 'sections': [{'id': 'a', 'title': 'A', 'text': None, 'blocks': [
    {'type': 'table', 'title': 'x', 'columns': ['c'], 'rows': [[{'k': 1, 'l': [1, 2]}], [[True, None]]], 'note': None}]}]}
h = rr.page(m)
assert 'k=1; l=1, 2' in h and '{' not in h.split('</style>')[1].split('<script>')[0], h[-400:]  # o <script> do índice lateral é comportamento, não dado

# 2) resultados reais
base = Path(sys.argv[1]) if len(sys.argv) > 1 else R.parent / 'analises' / 'tcap-codigo'
rt = Path(sys.argv[2]) if len(sys.argv) > 2 else base / 'runtime'
n = 0
for d in sorted(base.iterdir()):
    if (d / 'ia' / 'report.json').exists() and d.name not in rr.SO_IA:   # etapa só para IA não tem página
        erros = gr.verificar(d)
        assert not erros, (d.name, erros)
        n += 1
assert n >= 7, n

# 3) todo diagrama tem a sua tabela (faixas e diagramas sem tabela automática precisam de uma tabela na mesma seção)
import json  # noqa: E402
sem = []
for d in sorted(base.iterdir()):
    rj = d / 'ia' / 'report.json'
    if not rj.exists():
        continue
    for sec in json.loads(rj.read_text(encoding='utf-8')).get('sections', []):
        blocos = sec.get('blocks', [])
        tem_tabela = any(b['type'] == 'table' for b in blocos)
        for b in blocos:
            if b['type'] in ('bands', 'graph') and not tem_tabela and (b['type'] == 'bands' or b.get('sem_tabela')):
                sem.append((d.name, sec['id'], b.get('title')))
assert not sem, ('diagrama sem tabela', sem[:5])
print(f'OK relatórios equivalentes IA/humano: {n} fases')
