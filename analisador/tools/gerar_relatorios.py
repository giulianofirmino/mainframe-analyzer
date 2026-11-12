#!/usr/bin/env python3
"""Gera os relatórios de todas as fases a partir dos resultados estruturados.

  human/report.html  -> tabelas e diagramas SVG, sem JSON;
  ia/report.json     -> o MESMO modelo (mesmas seções, tabelas e grafos) em JSON.
Uso: gerar_relatorios.py <pasta-das-fases> [<pasta-do-runtime>]
  <pasta-das-fases>: contém NN-*/ia/result.json;  <pasta-do-runtime>: contém runtime-validation.json e static/static-model.json.
Também importável: gerar(fases, runtime) e verificar(pasta_da_fase)."""
import json
import re
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R / 'semantic_core'))
import report_model as rm  # noqa: E402
import report_render as rr  # noqa: E402


def _load(p):
    p = Path(p)
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None


def _write(step_dir, name, model):
    model['phase'] = name
    ia = step_dir / 'ia'
    ia.mkdir(parents=True, exist_ok=True)
    (ia / 'report.json').write_text(json.dumps(model, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
    rr.gravar_html(step_dir, model)   # etapa só com a visão para IA (rr.SO_IA) não tem página humana
    sp = ia / 'schema.json'
    schema = _load(sp) or {'artifact_contract': 'MFAA_STEP_ARTIFACT_V1', 'step': name}
    schema.update({'canonical_model': 'result.json', 'report_model': 'report.json',
                   'human_projection': None if name in rr.SO_IA else '../human/report.html',
                   'equivalence': 'report.json e report.html vêm do mesmo modelo de visão: mesmas seções, tabelas, grafos e valores'})
    sp.write_text(json.dumps(schema, indent=1, ensure_ascii=False), encoding='utf-8')


def _scenarios(runtime):
    out = []
    base = runtime / 'cenarios' if runtime else None
    if base and base.exists():
        for d in sorted(base.iterdir()):
            r = _load(d / 'result.json')
            if r is None:
                continue
            keep = ('name', 'entry_point', 'status', 'checks', 'mock_plan', 'mocks_used', 'executed_programs', 'calls', 'sql', 'warnings', 'final_tables')
            out.append({'res': {k: r.get(k) for k in keep}, 'def': _load(d / 'scenario.json')})
    return out


def gerar(fases, runtime=None):
    fases, runtime = Path(fases), Path(runtime) if runtime else None
    phase = {d.name: _load(d / 'ia' / 'result.json') for d in sorted(fases.iterdir()) if d.is_dir() and (d / 'ia' / 'result.json').exists()}
    rt = _load(runtime / 'runtime-validation.json') if runtime else None
    if '04-data-lineage' in phase:   # fase 4b: resumo calculado só da fase 4 (sempre refeito: é derivado)
        import lineage_summary
        classes = {x['program']: x['classification'] for x in (phase.get('00-program-classification') or {}).get('programs', [])}
        phase['04b-lineage-summary'] = lineage_summary.build(phase['04-data-lineage']['lineage'], classes=classes)
        (fases / '04b-lineage-summary' / 'ia').mkdir(parents=True, exist_ok=True)
        (fases / '04b-lineage-summary' / 'ia' / 'result.json').write_text(json.dumps(phase['04b-lineage-summary'], indent=1, ensure_ascii=False, default=str), encoding='utf-8')
    static = _load((runtime or fases) / 'static' / 'static-model.json') or _load(fases.parent / 'runtime' / 'static' / 'static-model.json') or {'call_graph': [], 'programs': {}}
    ctx = {'phase': phase, 'static': static, 'rt': rt, 'scenarios': _scenarios(runtime), 'eps': _load(runtime / 'entry-point-coverage.json') if runtime else None}
    done = []
    for step, fn in rm.STEPS.items():
        if step in phase:
            _write(fases / step, step, fn(phase[step], ctx))
            done.append(step)
    rr.reindexar(fases)
    return done


def _html_counts(html):
    html = re.sub(r'<table class="oa-t">.*?</table>', '', html, flags=re.S)  # tabelas internas do contrato OpenAPI (visual estilo Swagger) não são tabelas do relatório
    tables = html.count('<table>')
    outras = [int(n) for n in re.findall(r' data-linhas="(\d+)"', html)]   # tabelas desenhadas como cartões, ficha ou texto (estilo elegante)
    return {'sections': html.count('<h2 '), 'tables': tables + len(outras), 'table_rows': len(re.findall(r'<tr[ >]', html)) - tables + sum(outras)}


def verificar(step_dir):
    """IA e humano com o mesmo conteúdo: compara o modelo do JSON com o que o HTML desenha. Retorna lista de divergências."""
    step_dir = Path(step_dir)
    model = _load(step_dir / 'ia' / 'report.json')
    html = (step_dir / 'human' / 'report.html').read_text(encoding='utf-8')
    c, h = rr.counts(model), _html_counts(html)
    erros = [f'{k}: json={c[k]} html={h[k]}' for k in h if c[k] != h[k]]
    if html != rr.page(model):
        erros.append('html não é a projeção do report.json')
    if re.search(r'<pre(?! class="cod")|"[A-Za-z_]+":\s', re.sub(r'<pre class="cod">.*?</pre>', '', html, flags=re.S)):
        erros.append('html contém JSON')
    return erros


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    fases, rt = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else None)
    done = gerar(fases, rt)
    bad = 0
    for s in done:
        if s in rr.SO_IA:   # sem página humana: nada a comparar
            print(f'OK  {s} (só visão para IA)')
            continue
        d = Path(fases) / s
        e = verificar(d)
        bad += bool(e)
        print(f'{"OK " if not e else "ERRO"} {s} {"; ".join(e)}')
    raise SystemExit(1 if bad else 0)


if __name__ == '__main__':
    main()
