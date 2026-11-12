"""Uso da dedução de entradas/saídas na execução dinâmica.

plan():   antes de executar, junta os campos sem declaração dos programas realmente executados
          (fluxo alcançável a partir do entry point, sem os mockados), decide o valor inicial tipado
          de cada um que o código lê e que o cenário não informou, e monta o aviso por copybook ausente;
finish(): depois de executar, lista as saídas deduzidas com o valor final e avisa se o cenário
          espera saída em campo deduzido.
"""
from __future__ import annotations

from db2_functional_sql import norm
from token_utils import parse_ref
from io_deduction import resolve_tags, DEFAULTS, TYPE_NAME

WARN = 'COPYBOOK_AUSENTE_CAMPOS_DEDUZIDOS'


def reachable(model, entry, mocks):
    seen, stack = [], [entry]
    while stack:
        p = stack.pop()
        if p in seen or p in mocks or p not in model['programs']:
            continue
        seen.append(p)
        stack += [c['target'] for c in model['programs'][p]['calls'] if c['target']]
    return seen


def _field(k):
    """Nome do campo (sem qualificador) de uma referência escrita no cenário, lido pelos tokens do léxico."""
    field, _ = parse_ref(str(k))
    return norm(field if field else str(k))


def provided_names(s):
    """Nomes que o cenário já informa (entradas e retornos de mock), no formato do runtime."""
    out = set()

    def add(k):
        out.add(_field(k))

    for k in (s.get('inputs') or {}):
        add(k)
    for spec in (s.get('mocks') or {}).values():
        if isinstance(spec, dict):
            for k in (spec.get('returns') or {}):
                add(k)
            for sc in list(spec.get('scenarios') or []) + ([spec['default']] if isinstance(spec.get('default'), dict) else []):
                for k in (sc.get('returns') or {}):
                    add(k)
        elif isinstance(spec, list):
            for sc in spec:
                for k in (sc.get('returns') or {}):
                    add(k)
    return out


def plan(model, s, entry, mocks):
    reach = reachable(model, entry, mocks)
    declared, merged = set(), {}
    for p in reach:
        x = model['programs'][p]
        declared |= {norm(n) for n in x['data_model']['by_name']}
        declared |= {norm(i['indexed_by']) for i in x['data_model']['items'] if i.get('indexed_by')}
        for f in x['io']['fields']:
            a = merged.setdefault(f['name'], {'tags': set(), 'read': False, 'written': False, 'programs': [], 'evidence': [],
                                              'copybooks': {}, 'candidates': set()})
            a['tags'] |= set(f['tags'])
            a['read'] |= f['read']
            a['written'] |= f['written']
            a['programs'].append(p)
            a['evidence'] += [e for e in f['evidence'] if e not in a['evidence']][:4]
            if f['copybook']:
                a['copybooks'][f['copybook']] = f['attribution']
            a['candidates'] |= set(f['candidates'])
    prov = provided_names(s)
    seeds, inputs, outputs, unresolved = {}, [], [], []
    for name, a in sorted(merged.items()):
        key = norm(name)
        if key in declared:
            continue  # declarado em outro programa do fluxo (VALUE/PIC valem)
        kind = resolve_tags(a['tags'])
        cb = sorted(a['copybooks'])[0] if a['copybooks'] else None
        common = {'field': name, 'type': TYPE_NAME[kind], 'copybook': cb,
                  'attribution': a['copybooks'].get(cb) if cb else ('CANDIDATOS' if a['candidates'] else 'SEM_COPYBOOK_AUSENTE'),
                  'candidates': sorted(a['candidates']) if cb is None else [], 'programs': sorted(set(a['programs'])),
                  'evidence': a['evidence']}
        if a['read']:
            if key in prov:
                inputs.append({**common, 'origin': 'CENARIO', 'initial': None})
            elif kind is None:
                unresolved.append(name)
                inputs.append({**common, 'origin': 'NAO_DEDUZIDO', 'initial': None})
            else:
                seeds[key] = DEFAULTS[kind]
                inputs.append({**common, 'origin': 'DEDUZIDO', 'initial': DEFAULTS[kind]})
        if a['written']:
            outputs.append({**common, 'origin': 'DEDUZIDO', 'final_value': None})
    warnings = _warnings(inputs, outputs, unresolved)
    return {'reach': reach, 'seeds': seeds, 'inputs': inputs, 'outputs': outputs, 'warnings': warnings,
            'undeclared': {norm(n) for n in merged if norm(n) not in declared}}


def _warnings(inputs, outputs, unresolved):
    groups = {}
    for kind, rows in (('inputs', inputs), ('outputs', outputs)):
        for r in rows:
            if kind == 'inputs' and r['origin'] == 'CENARIO':
                continue
            g = groups.setdefault(r['copybook'] or '(não identificado)', {'copybook': r['copybook'], 'attribution': r['attribution'],
                                                                         'candidates': r['candidates'], 'programs': set(),
                                                                         'inputs': [], 'outputs': [], 'not_deduced': []})
            g[kind].append(r['field'])
            g['programs'] |= set(r['programs'])
            if kind == 'inputs' and r['origin'] == 'NAO_DEDUZIDO':
                g['not_deduced'].append(r['field'])
    out = []
    for name, g in sorted(groups.items()):
        cb = g['copybook']
        if cb:
            how = {'QUALIFICADOR': 'referência qualificada', 'PREFIXO': 'pelo prefixo do nome', 'UNICO_AUSENTE': 'único copybook ausente do fluxo'}
            why = f"copybook {cb} ausente ({how.get(g['attribution'], g['attribution'])})"
        elif g['candidates']:
            why = f"copybook ausente não identificado; candidatos: {', '.join(g['candidates'][:8])}"
        else:
            why = 'nome não declarado no fonte nem em copybook/DCLGEN disponível'
        out.append({'type': WARN, 'copybook': cb, 'attribution': g['attribution'], 'candidates': g['candidates'],
                    'programs': sorted(g['programs']), 'inputs': sorted(set(g['inputs'])), 'outputs': sorted(set(g['outputs'])),
                    'not_deduced': sorted(set(g['not_deduced'])),
                    'detail': f"{why}: entradas e saídas DEDUZIDAS pelo uso no código (tipo e valor inicial inferidos, não vêm do layout)"})
    return out


def finish(model, pl, s, run, lookup):
    """Preenche o valor final das saídas deduzidas e avisa sobre expectativas em campo deduzido."""
    if not pl:
        return {'inputs': [], 'outputs': []}, []
    warns = []
    for o in pl['outputs']:
        found, v = lookup(run['outputs'], o['field'])
        o['final_value'] = v if found else None
    exp = (s.get('expected') or {}).get('outputs') or {}
    hit = []
    for k in exp:
        if _field(k) in pl['undeclared']:
            hit.append(k)
    if hit:
        warns.append({'type': 'SAIDA_ESPERADA_EM_CAMPO_DEDUZIDO', 'fields': sorted(hit),
                      'detail': 'o valor esperado é comparado com um campo sem declaração (copybook ausente); o tipo/tamanho não foram validados contra o layout'})
    return {'inputs': pl['inputs'], 'outputs': pl['outputs']}, warns


def mock_warnings(model, reach, mocks_used, mock_info):
    """Mock sem retorno definido: mostra de que campos o código executado depende (deduzido do fonte do mock, se houver)."""
    out = []
    real_reads = set()
    for p in reach:
        real_reads |= set(model['programs'][p]['io']['reads'])
    for p in mocks_used:
        if mock_info[p]['returns_defined']:
            continue
        x = model['programs'].get(p)
        w = {'type': 'MOCK_SEM_RETORNO_DEFINIDO', 'program': p}
        if x is None:
            w['detail'] = 'programa sem fonte disponível: os campos que ele devolveria não podem ser deduzidos; defina "returns" no mock'
        else:
            need = sorted(set(x['io']['writes']) & real_reads)
            w['fields'] = need[:40]
            w['detail'] = (f'o código executado lê {len(need)} campo(s) que o fonte de {p} escreve; sem "returns" ficam com o valor inicial '
                           f'(deduzido para campos sem declaração, senão o padrão do runtime)') if need else \
                f'{p} não escreve campos lidos pelo fluxo executado'
        out.append(w)
    return out
