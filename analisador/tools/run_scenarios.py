#!/usr/bin/env python3
"""Runtime com cenários de entrada/saída nos entry points, validado contra a análise estática.

Uso:
  python3 tools/run_scenarios.py <fontes> <cenarios> [saida] [--rapido]
  python3 tools/run_scenarios.py <fontes> --modelo <PROGRAMA|entry-points> [saida]

Toda execução refaz a análise dos fontes:
  1. pipeline completo (tools/certify_from_zero.py) em <saida>/analise  (pule com --rapido);
  2. análise estática com copybooks/DCLGEN expandidos em <saida>/static, usada na comparação;
  3. cenários em <saida>/cenarios e consolidado em <saida>/runtime-validation.json.
--modelo gera cenários-modelo (entradas candidatas, 88s, mocks previstos) em <saida>/modelos.
"""
import argparse
import json, os
import shutil
import subprocess
import sys
import time
from pathlib import Path

R = Path(__file__).parents[1]
sys.path.insert(0, str(R / 'semantic_core'))
sys.path.insert(0, str(R / 'tools'))
import static_model  # noqa: E402
import scenario_runner as sr  # noqa: E402
from artifact_renderer import publish  # noqa: E402


SO_ESTATICOS = {'rule_paths.py', 'condition_criteria.py'}


def _codigo():
    """Hash do código do analisador (semantic_core/*.py, menos os report_*.py): resultado em cache de uma versão antiga do runtime nunca é reaproveitado."""
    import hashlib
    h = hashlib.sha1()
    for f in sorted((R / 'semantic_core').glob('*.py')):
        if f.name.startswith('report_') or f.name in SO_ESTATICOS:
            continue   # relatórios e análises só estáticas (regras, critérios das condições) não alteram o resultado dos cenários
        h.update(f.name.encode() + f.read_bytes())
    h.update(os.environ.get('ANALISE_PREFIXO_CORE', '').encode())   # a classificação (fase 0) muda com o prefixo do core business
    return h.hexdigest()[:12]


def _link_or_copy(src, dst):
    """Reuso do cache sem copiar bytes (link físico; copia se o sistema de arquivos não permitir)."""
    try:
        if os.path.exists(dst):
            os.remove(dst)
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _cached(cache, model, s, outdir, runs):
    """Roda o cenário; com --cache reaproveita o resultado (e os arquivos do cenário) se o cenário não mudou."""
    if not cache:
        return sr.run_scenario(model, s, outdir, runs=runs)
    import hashlib, pickle
    key = hashlib.sha1(json.dumps([s, runs, sorted(model['programs']), _codigo()], sort_keys=True, default=str).encode()).hexdigest()[:20]
    base = Path(cache) / key
    slug = sr.slug(s['name'])
    if (base / 'r.pkl').exists():
        try:
            r = pickle.loads((base / 'r.pkl').read_bytes())   # entrada truncada por uma rodada interrompida: recalcula
            if (base / 'dir').exists():
                shutil.copytree(base / 'dir', Path(outdir) / slug, dirs_exist_ok=True, copy_function=_link_or_copy)
            return r
        except (EOFError, pickle.UnpicklingError, OSError):
            shutil.rmtree(base, ignore_errors=True)
    r = sr.run_scenario(model, s, outdir, runs=runs)
    base.mkdir(parents=True, exist_ok=True)
    if (Path(outdir) / slug).exists():
        shutil.copytree(Path(outdir) / slug, base / 'dir', dirs_exist_ok=True)
    tmp_pkl = base / 'r.pkl.tmp'
    tmp_pkl.write_bytes(pickle.dumps(r))
    os.replace(tmp_pkl, base / 'r.pkl')   # gravação atômica: o cache nunca fica com resultado pela metade
    return r


def main():
    a = argparse.ArgumentParser()
    a.add_argument('posicionais', nargs='+', metavar='fontes [cenarios] [saida]')
    a.add_argument('--modelo', help='gera cenário-modelo para PROGRAMA ou para todos os entry-points')
    a.add_argument('--rapido', action='store_true', help='não roda o pipeline completo de análise/certificação')
    a.add_argument('--execucoes', type=int, default=3, help='repetições para verificar determinismo')
    a.add_argument('--cache', help='pasta que guarda o resultado de cada cenário já rodado; permite retomar uma rodada interrompida (execuções longas)')
    x = a.parse_intermixed_args()
    pos = x.posicionais
    x.fontes = pos[0]
    if x.modelo and len(pos) == 2:
        x.cenarios, x.saida = None, pos[1]
    else:
        x.cenarios = pos[1] if len(pos) > 1 else None
        x.saida = pos[2] if len(pos) > 2 else None
    out = Path(x.saida or (R / 'runtime-output'))
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    t0 = time.time()
    model = static_model.build(x.fontes, out / 'static')
    (out / 'static' / 'io-deduction.json').write_text(json.dumps({p: x['io'] for p, x in model['programs'].items()}, indent=2, default=str, ensure_ascii=False), encoding='utf-8')
    (out / 'static' / 'static-model.json').write_text(json.dumps(static_model.public(model), indent=2, default=str, ensure_ascii=False), encoding='utf-8')
    print(f"análise estática: {len(model['programs'])} programas, {len(model['entry_points'])} entry points "
          f"({', '.join(model['entry_points'])}), {len(model['externals'])} externos, "
          f"{len(model['missing_copybooks'])} copybooks ausentes [{time.time() - t0:.1f}s]")

    if not x.rapido and not x.modelo:
        t2 = time.time()
        p = subprocess.run([sys.executable, str(R / 'tools' / 'certify_from_zero.py'), x.fontes, str(out / 'analise')],
                           stdout=subprocess.PIPE, text=True)  # stderr herdado: mostra o progresso [certify ...] em tempo real
        last = (p.stdout.strip().splitlines() or [''])[-1]
        try:
            s = json.loads(last)
            print(f"análise completa: {s['sources']} fontes, {s['outcomes']} ramos, {s['clean_room_goldens']} goldens, "
                  f"{s['tree_business_rules']} regras, DCLGEN {s.get('dclgen', {}).get('coverage_percent')}% [{time.time() - t2:.1f}s] -> {out / 'analise'}")
        except (ValueError, KeyError):
            print('análise completa falhou:', last[-500:])

    if x.modelo:
        targets = model['entry_points'] if x.modelo.lower() in ('entry-points', 'todos', 'all') else [x.modelo.upper()]
        d = out / 'modelos'
        d.mkdir()
        for p in targets:
            (d / f'{p}.json').write_text(json.dumps(sr.template(model, p), indent=2, ensure_ascii=False, default=str), encoding='utf-8')
        print(f'modelos gerados em {d}: {", ".join(targets)}')
        if not x.cenarios:
            return

    if not x.cenarios:
        a.error('informe a pasta/arquivo de cenários ou --modelo')
    scenarios = sr.load_scenarios(x.cenarios)
    results = []
    for s in scenarios:
        t1 = time.time()
        try:
            r = _cached(x.cache, model, s, out / 'cenarios', x.execucoes)
        except Exception as e:  # cenário mal formado não derruba a rodada
            r = {'name': s.get('name'), 'entry_point': s.get('entry_point'), 'status': 'INVALID', 'error': f'{type(e).__name__}: {e}'}
        results.append(r)
        if r.get('status') != 'INVALID' and (out / 'cenarios' / sr.slug(s['name'])).exists():
            (out / 'cenarios' / sr.slug(s['name']) / 'scenario.json').write_text(json.dumps(s, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
        diffs = [c for c in r.get('checks', []) if c['result'] != 'MATCH']
        print(f"[{r['status']:7}] {r['name']}  entry={r.get('entry_point')}  runtime={r.get('runtime_status')}  "
              f"estático={r.get('static_consistency')}  divergências={len(r.get('divergences', []))}  "
              f"avisos={len(r.get('warnings', []))}  checks≠={len(diffs)}  [{time.time() - t1:.1f}s]")
        for c in diffs:
            print(f"          {c['check']} {c.get('name', '')}: esperado={c.get('expected')!r} obtido={c.get('actual')!r} -> {c['result']}")
        for w in r.get('warnings', []):
            if w['type'] == 'COPYBOOK_AUSENTE_CAMPOS_DEDUZIDOS':
                ex = ', '.join((w['inputs'] + w['outputs'])[:4])
                print(f"          AVISO dedução: {w['detail'].split(':')[0]}; programas {','.join(w['programs'])}; "
                      f"{len(w['inputs'])} entrada(s) e {len(w['outputs'])} saída(s) deduzidas (ex.: {ex})")
        if r.get('error'):
            print(f"          erro: {r['error']}")
        for e in r.get('errors', []):
            print(f"          runtime: {e.get('message')}")
    agg = sr.aggregate(model, [r for r in results if r.get('status') != 'INVALID'])
    def io_summary(r):
        io = r.get('io') or {}
        return {'inputs_deduced': sum(1 for i in io.get('inputs', []) if i['origin'] == 'DEDUZIDO'),
                'inputs_from_scenario': sum(1 for i in io.get('inputs', []) if i['origin'] == 'CENARIO'),
                'inputs_not_deduced': sum(1 for i in io.get('inputs', []) if i['origin'] == 'NAO_DEDUZIDO'),
                'outputs_deduced': len(io.get('outputs', [])),
                'copybooks_missing': sorted({w['copybook'] for w in r.get('warnings', []) if w['type'] == 'COPYBOOK_AUSENTE_CAMPOS_DEDUZIDOS' and w['copybook']})}
    import branch_reasons as br
    executed = {p for p, c in agg['coverage_by_program'].items() if c['executed_in_scenarios']}
    branch_analysis = br.analyze(model, agg['uncovered_branches'], agg['slice_coverage'], executed)
    report = {'summary': agg['summary'], 'scenarios': [{**{k: v for k, v in r.items() if not k.startswith('_') and k not in ('outputs', 'final_tables', 'io')}, 'io_summary': io_summary(r)} for r in results],
              'coverage_by_program': agg['coverage_by_program'], 'scenarios_by_entry_point': agg['scenarios_by_entry_point'],
              'executed_lines': agg['executed_lines'], 'executed_paragraphs': agg['executed_paragraphs'], 'taken_branches': agg['taken_branches'], 'uncovered_branches': agg['uncovered_branches'], 'slice_coverage': agg['slice_coverage'], 'branch_analysis': branch_analysis}
    (out / 'runtime-validation.json').write_text(json.dumps(report, indent=2, default=str, ensure_ascii=False), encoding='utf-8')
    publish(out, 'runtime-validation', report, 'Runtime x Análise Estática')
    import entry_point_coverage as epc
    eps = epc.build(out)
    (out / 'entry-point-coverage.json').write_text(json.dumps(eps, ensure_ascii=False, indent=1), encoding='utf-8')
    (out / 'entry-point-coverage.md').write_text(epc.markdown(eps), encoding='utf-8')
    (out / 'entry-point-coverage.html').write_text(epc.page(eps), encoding='utf-8')
    if (out / 'analise').exists():   # com --rapido o pipeline não roda e não há relatórios de fase para gerar
        import gerar_relatorios as gr
        feitos = gr.gerar(out / 'analise', out)
        print(f'relatórios (HTML humano + ia/report.json): {len(feitos)} fases')
    print(json.dumps(agg['summary'], ensure_ascii=False))
    raise SystemExit(0 if results and all(r.get('status') == 'PASS' for r in results) else 2)


if __name__ == '__main__':
    main()
