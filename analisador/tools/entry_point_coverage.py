#!/usr/bin/env python3
"""Fluxo de execução de cada entry point com percentual de cobertura do runtime.

Uso: python3 tools/entry_point_coverage.py <pasta runtime> [saida]
Lê <runtime>/static/static-model.json (grafo de chamadas) e <runtime>/runtime-validation.json (cobertura por programa)
e grava entry-point-coverage.json, .md e .html. Só junta dados já produzidos; não interpreta código."""
import html
import json
import sys
from pathlib import Path


def pct(a, b):
    return round(100.0 * a / b, 1) if b else None


def fmt(v):
    return '-' if v is None else f'{v:.1f}%'


def build(rt):
    model = json.load(open(Path(rt) / 'static/static-model.json', encoding='utf-8'))
    val = json.load(open(Path(rt) / 'runtime-validation.json', encoding='utf-8'))
    cov, progs = val['coverage_by_program'], model['programs']
    by_ep = val.get('scenarios_by_entry_point', {})
    out = []
    for ep in model['entry_points']:
        ep = ep if isinstance(ep, str) else ep.get('program') or ep.get('name')
        flow, seen = [], set()
        sl = val.get('slice_coverage', {}).get(ep, {})  # ramos alcançáveis a partir deste entry point (slice_reach)

        def walk(p, depth, via, line):
            c = cov.get(p, {})
            row = {'program': p, 'depth': depth, 'via': via, 'line': line, 'in_source': p in progs,
                   'infrastructure': bool(c.get('infrastructure') or progs.get(p, {}).get('infrastructure')),
                   'executed': c.get('executed_in_scenarios', False) and (not sl or p == ep or bool((sl.get(p) or {}).get('exercised'))), 'mocked': c.get('mocked_in_scenarios', False),
                   'branches': c.get('branches', 0), 'branches_exercised': c.get('branches_exercised', 0),
                   'branch_coverage_pct': c.get('branch_coverage_pct'),
                   'business_rules': c.get('business_rules', 0), 'business_rules_exercised': c.get('business_rules_exercised', 0),
                   'repeated': p in seen, 'slice': sl.get(p)}
            flow.append(row)
            if p in seen or p not in progs or row['infrastructure'] or (row['mocked'] and not row['executed']):
                return  # infraestrutura e programa só mockado não expõem o que chamariam
            seen.add(p)
            for call in sorted(progs[p]['calls'], key=lambda x: x['line']):
                if call.get('target'):
                    walk(call['target'], depth + 1, call['mechanism'], call['line'])

        walk(ep, 0, 'ENTRY', None)
        uniq = {r['program']: r for r in flow if r['in_source'] and not r['infrastructure']}
        b, be = sum(r['branches'] for r in uniq.values()), sum(r['branches_exercised'] for r in uniq.values())
        rb, rbe = sum(r['business_rules'] for r in uniq.values()), sum(r['business_rules_exercised'] for r in uniq.values())
        # cobertura "própria": só o entry point e o funcional executado de verdade (sem serviços sempre mockados)
        real = {p: r for p, r in uniq.items() if r['executed']}
        rb2, rbe2 = sum(r['branches'] for r in real.values()), sum(r['branches_exercised'] for r in real.values())
        sb = sum(x['branches'] for x in sl.values())
        sbe = sum(x['exercised'] for x in sl.values())
        sx = {p: x for p, x in sl.items() if p in real}
        sxb, sxbe = sum(x['branches'] for x in sx.values()), sum(x['exercised'] for x in sx.values())
        out.append({'entry_point': ep, 'scenarios': len(by_ep.get(ep, [])), 'flow': flow,
                    'slice_branches': sb, 'slice_exercised': sbe, 'slice_pct': pct(sbe, sb),
                    'slice_branches_executed_programs': sxb, 'slice_exercised_executed_programs': sxbe, 'slice_executed_programs_pct': pct(sxbe, sxb),
                    'slice_outside_taken': sum(len(x['outside_slice_taken']) for x in sl.values()),
                    'branches': b, 'branches_exercised': be, 'branch_coverage_pct': pct(be, b),
                    'branches_executed_programs': rb2, 'branches_exercised_executed_programs': rbe2,
                    'branch_coverage_executed_programs_pct': pct(rbe2, rb2),
                    'business_rules': rb, 'business_rules_exercised': rbe, 'business_rules_pct': pct(rbe, rb)})
    return out


def markdown(eps):
    L = ['# Fluxo de execução dos entry points e cobertura do runtime', '',
         'Cobertura de ramos (IF/EVALUATE) e de regras de negócio dos programas do fluxo, sem contar programas classificados como infraestrutura. '
         '"Fatia" = só os ramos alcançáveis a partir do entry point (o chamador fixa valores de campos antes da chamada e parte do serviço chamado fica inalcançável), contados com os cenários daquele entry point. '
         '"Executados" = programas que os cenários rodam de verdade; "só mockado" = o cenário substitui o programa por retorno fixo.', '',
         '| Entry point | Cenários | Ramos alcançáveis (fatia) | Fatia (só programas executados) | Ramos (programa inteiro) | Regras de negócio |', '|---|---|---|---|---|---|']
    for e in eps:
        L.append(f"| {e['entry_point']} | {e['scenarios']} | {e['slice_exercised']}/{e['slice_branches']} ({fmt(e['slice_pct'])}) | "
                 f"{e['slice_exercised_executed_programs']}/{e['slice_branches_executed_programs']} ({fmt(e['slice_executed_programs_pct'])}) | "
                 f"{e['branches_exercised']}/{e['branches']} ({fmt(e['branch_coverage_pct'])}) | "
                 f"{e['business_rules_exercised']}/{e['business_rules']} ({fmt(e['business_rules_pct'])}) |")
    for e in eps:
        L += ['', f"## {e['entry_point']}  ({e['scenarios']} cenários)", '', '```']
        for r in e['flow']:
            tag = 'INFRA' if r['infrastructure'] else 'sem fonte' if not r['in_source'] else ('executado' if r['executed'] else 'só mockado' if r['mocked'] else 'não exercitado')
            cv = '' if r['infrastructure'] or not r['in_source'] else (f"  fatia {r['slice']['exercised']}/{r['slice']['branches']} ({fmt(r['slice']['pct'])}) de {r['branches']} ramos, regras {r['business_rules_exercised']}/{r['business_rules']}" if r.get('slice') else f"  ramos {r['branches_exercised']}/{r['branches']} ({fmt(r['branch_coverage_pct'])}), regras {r['business_rules_exercised']}/{r['business_rules']}")
            via = '' if r['via'] == 'ENTRY' else f"{r['via']}@{r['line']} -> "
            L.append('  ' * r['depth'] + f"{via}{r['program']} [{tag}]{cv}" + (' (já listado)' if r['repeated'] else ''))
        L.append('```')
    return '\n'.join(L) + '\n'


def page(eps):
    css = ('body{font:14px system-ui,sans-serif;margin:24px;max-width:1100px}table{border-collapse:collapse;width:100%}'
           'td,th{border:1px solid #ccc;padding:4px 8px;text-align:left}th{background:#f0f0f0}.bar{background:#e5e5e5;width:120px;height:10px;display:inline-block;vertical-align:middle}'
           '.bar i{display:block;height:10px;background:#2a7}pre{background:#f7f7f7;padding:10px;overflow:auto}')
    def bar(p):
        return f'<span class="bar"><i style="width:{p or 0}%"></i></span> {fmt(p)}'
    h = [f'<!doctype html><meta charset="utf-8"><title>Cobertura por entry point</title><style>{css}</style><h1>Fluxo de execução dos entry points e cobertura</h1>',
         '<table><tr><th>Entry point</th><th>Cenários</th><th>Fatia alcançável</th><th>Fatia (executados)</th><th>Ramos (programa inteiro)</th><th>Regras</th></tr>']
    for e in eps:
        h.append(f"<tr><td><a href='#{e['entry_point']}'>{e['entry_point']}</a></td><td>{e['scenarios']}</td>"
                 f"<td>{e['slice_exercised']}/{e['slice_branches']} {bar(e['slice_pct'])}</td>"
                 f"<td>{e['slice_exercised_executed_programs']}/{e['slice_branches_executed_programs']} {bar(e['slice_executed_programs_pct'])}</td>"
                 f"<td>{e['branches_exercised']}/{e['branches']} {bar(e['branch_coverage_pct'])}</td>"
                 f"<td>{e['business_rules_exercised']}/{e['business_rules']} {bar(e['business_rules_pct'])}</td></tr>")
    h.append('</table>')
    for e in eps:
        h.append(f"<h2 id='{e['entry_point']}'>{e['entry_point']}</h2><pre>")
        for r in e['flow']:
            tag = 'INFRA' if r['infrastructure'] else 'sem fonte' if not r['in_source'] else ('executado' if r['executed'] else 'só mockado' if r['mocked'] else 'não exercitado')
            cv = '' if r['infrastructure'] or not r['in_source'] else (f"  fatia {r['slice']['exercised']}/{r['slice']['branches']} ({fmt(r['slice']['pct'])}) de {r['branches']} ramos, regras {r['business_rules_exercised']}/{r['business_rules']}" if r.get('slice') else f"  ramos {r['branches_exercised']}/{r['branches']} ({fmt(r['branch_coverage_pct'])}), regras {r['business_rules_exercised']}/{r['business_rules']}")
            via = '' if r['via'] == 'ENTRY' else f"{r['via']}@{r['line']} → "
            h.append(html.escape('  ' * r['depth'] + f"{via}{r['program']} [{tag}]{cv}" + (' (já listado)' if r['repeated'] else '')))
        h.append('</pre>')
    return '\n'.join(h)


if __name__ == '__main__':
    rt = sys.argv[1]
    dst = Path(sys.argv[2] if len(sys.argv) > 2 else rt)
    eps = build(rt)
    (dst / 'entry-point-coverage.json').write_text(json.dumps(eps, ensure_ascii=False, indent=1), encoding='utf-8')
    (dst / 'entry-point-coverage.md').write_text(markdown(eps), encoding='utf-8')
    (dst / 'entry-point-coverage.html').write_text(page(eps), encoding='utf-8')
    print(markdown(eps).split('\n## ')[0])
