"""Execução de cenários de entrada/saída nos entry points e validação contra a análise estática.

Fluxo de cada rodada (sempre a partir dos fontes, sem reaproveitar resultado anterior):
1. static_model.build: expande copybooks/DCLGEN, AST, árvore de decisão, regras, grafo de chamadas;
2. para cada cenário: monta mocks (política + definidos no cenário), executa o entry point
   3 vezes no runtime sobre AST e exige o mesmo hash de trace;
3. compara saída obtida x esperada e o caminho percorrido x análise estática.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from cobol_ast_runtime import Runtime
from db2_functional_sql import norm
import io_runtime
import slice_reach
from token_utils import parse_ref

MOCK_POLICIES = ('infra_and_external', 'external_only', 'none')


# --------------------------------------------------------------------------- #
# Cenários
# --------------------------------------------------------------------------- #
def load_scenarios(path):
    path = Path(path)
    files = sorted(f for f in path.rglob('*.json') if f.name != 'analise.config.json') if path.is_dir() else [path]   # analise.config.json é a configuração do projeto, não um cenário
    out = []
    for f in files:
        data = json.loads(f.read_text(encoding='utf-8'))
        items = data.get('scenarios') if isinstance(data, dict) and 'scenarios' in data else (data if isinstance(data, list) else [data])
        for i, s in enumerate(items):
            s = dict(s)
            s.setdefault('name', f.stem if len(items) == 1 else f'{f.stem}-{i + 1}')
            s['_file'] = str(f)
            out.append(s)
    return out


def slug(x):
    full = re.sub(r'[^A-Za-z0-9_.-]+', '_', x).strip('_')
    if len(full) <= 80:
        return full or 'cenario'
    import hashlib  # nome longo: corta e acrescenta hash do nome inteiro para não colidir com outro cenário
    return full[:71] + '_' + hashlib.sha1(x.encode('utf-8')).hexdigest()[:8]


def _normalize_mock(spec):
    """Aceita {returns}, {scenarios:[...], default:{returns}} ou lista; devolve formato do runtime."""
    if spec in (None, 'auto', True):
        return {'scenarios': [{'default': True, 'returns': {}}]}, True
    if isinstance(spec, list):
        spec = {'scenarios': spec}
    scs = [dict(x) for x in spec.get('scenarios', [])]
    whens = [x for x in scs if not x.get('default')]
    defaults = [x for x in scs if x.get('default')]
    if 'returns' in spec and not spec.get('scenarios'):
        defaults.append({'default': True, 'returns': spec['returns']})
    if isinstance(spec.get('default'), dict):
        defaults.append({'default': True, 'returns': spec['default'].get('returns', {})})
    empty = not whens and all(not d.get('returns') for d in defaults)
    if not defaults:
        defaults = [{'default': True, 'returns': {}}]
    return {'scenarios': whens + defaults[:1]}, empty


def mock_plan(model, scenario):
    policy = scenario.get('mock_policy', 'infra_and_external')
    if policy not in MOCK_POLICIES:
        raise ValueError(f'mock_policy inválida: {policy} (use {MOCK_POLICIES})')
    force = {x.upper() for x in scenario.get('execute', [])}
    user = {k.upper(): v for k, v in (scenario.get('mocks') or {}).items()}
    plan = {}
    progs = model['programs']
    for p, x in progs.items():
        if p == scenario['entry_point'].upper() or p in force:
            continue
        if policy == 'infra_and_external' and x['infrastructure']:
            plan[p] = 'INFRAESTRUTURA'
    if policy in ('infra_and_external', 'external_only'):
        for p in model['externals']:
            if p not in force:
                plan[p] = 'EXTERNO'
    for p in user:
        if p not in force:
            plan[p] = 'DEFINIDO_NO_CENARIO'
    mocks, info = {}, {}
    for p, why in sorted(plan.items()):
        m, empty = _normalize_mock(user.get(p))
        mocks[p] = m
        info[p] = {'reason': why, 'returns_defined': not empty}
    return mocks, info


def _translate_keys(d, model):
    """Chaves 'PROGRAMA:linha' do cenário usam a linha do fonte original; o runtime usa a expandida."""
    out = {}
    for k, v in (d or {}).items():
        prog, _, ln = k.rpartition(':')
        x = model['programs'].get(prog.upper())
        if x and ln.isdigit():
            e = x['linemap'].to_expanded(int(ln))
            if e:
                out[f'{prog.upper()}:{e}'] = v
                continue
        out[k] = v
    return out


def runtime_input(model, s):
    return {'name': s['name'], 'inputs': {_input_key(k): v for k, v in (s.get('inputs') or {}).items()}, 'tables': s.get('tables', {}), 'files': s.get('files', {}),
            'file_status_map': s.get('file_status_map', {}), 'accept': s.get('accept', {}), 'teclas': s.get('teclas', []), 'file_status': _translate_keys(s.get('file_status'), model), 'cics_containers': s.get('cics_containers', {}),
            'db2_status': _translate_keys(s.get('db2_status'), model), 'cics_status': _translate_keys(s.get('cics_status'), model),
            'cics_link_outputs': _translate_keys(s.get('cics_link_outputs'), model),
            **({'cics_retrieve': s['cics_retrieve']} if 'cics_retrieve' in s else {}), **({'mq': s['mq']} if 'mq' in s else {})}   # dados do START e filas IBM MQ simuladas


# --------------------------------------------------------------------------- #
# Extração do caminho dinâmico
# --------------------------------------------------------------------------- #
def _label(result):
    if result is True:
        return 'TRUE'
    if result is False:
        return 'FALSE'
    r = str(result)
    return r.replace('WHEN:', 'WHEN_') if r.startswith('WHEN:') else r


def _executed_lines(trace):
    """Do rastro: linhas (do fonte expandido) dos comandos simples executados (AST_NODE) e parágrafos executados por PERFORM
    (ENTER_PERFORM: alvo e fim), por programa."""
    out, paras = {}, {}
    for e in trace:
        if e.get('event') == 'AST_NODE':
            out.setdefault(e['program'], set()).add(e['start_line'])
        elif e.get('event') == 'ENTER_PERFORM':
            paras.setdefault(e['program'], set()).add((e.get('target'), e.get('end') or e.get('target')))
    return {'lines': {p: sorted(v) for p, v in out.items()}, 'paras': {p: sorted(map(list, v)) for p, v in paras.items()}}


def dynamic_path(run):
    branches = [{'program': b['program'], 'line': b['line'], 'result': _label(b['result'])} for b in run['branches']]
    calls, pending = [], None
    sql = []
    for e in run['trace']:
        ev = e['event']
        if ev == 'PROGRAM_CALL' and e.get('mode') == 'MQ':   # IBM MQ simulado: a chamada é a operação da MQI
            if pending:
                calls.append({**pending, 'target': None, 'mode': 'SEM_DESTINO'})
            calls.append({'caller': e.get('caller'), 'line': e.get('line'), 'mechanism': 'CALL', 'target': e.get('program'), 'mode': 'MQ'})
            pending = None
        elif ev == 'PROGRAM_CALL':
            pending = {'caller': e.get('caller'), 'line': e.get('line'), 'mechanism': 'CALL'}
        elif ev == 'CICS_EXECUTE' and str(e.get('operation', '')).upper() in ('LINK', 'XCTL'):
            if pending:
                calls.append({**pending, 'target': None, 'mode': 'SEM_DESTINO'})
            pending = {'caller': e.get('program'), 'line': e.get('line'), 'mechanism': e['operation'].upper()}
        elif ev in ('ENTER_PROGRAM', 'MOCK_PROGRAM', 'CICS_EXTERNAL_PROGRAM', 'CICS_LINK_FALHOU') and pending:
            # LINK que falhou (resposta de erro no cenário): a chamada foi tentada, mas o programa não roda
            mode = {'ENTER_PROGRAM': 'REAL', 'MOCK_PROGRAM': 'MOCK', 'CICS_EXTERNAL_PROGRAM': 'EXTERNO_SEM_MOCK', 'CICS_LINK_FALHOU': 'FALHOU'}[ev]
            calls.append({**pending, 'target': e.get('program'), 'mode': mode})
            pending = None
        elif ev == 'CICS_EXECUTE' and pending:
            calls.append({**pending, 'target': None, 'mode': 'SEM_DESTINO'})
            pending = None
        elif ev == 'SQL_EXECUTE':
            sql.append({'program': e.get('program'), 'line': e.get('line')})
        elif ev == 'SQL_RESULT' and sql:
            sql[-1].update({'operation': e.get('operation'), 'sqlcode': e.get('sqlcode')})
    if pending:
        calls.append({**pending, 'target': None, 'mode': 'SEM_DESTINO'})
    return {'branches': branches, 'calls': calls, 'sql': sql}


def trace_hash(run):
    body = [{k: v for k, v in e.items() if k != 'seq'} for e in run['trace']]
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


# --------------------------------------------------------------------------- #
# Comparações
# --------------------------------------------------------------------------- #
def _num(v):
    try:
        if isinstance(v, bool):
            return None
        return Decimal(str(v).strip())
    except (InvalidOperation, ValueError):
        return None


def lookup(values, name):
    """Aceita CAMPO, CAMPO OF GRUPO ou GRUPO.CAMPO (lido pelos tokens do léxico)."""
    field, quals = parse_ref(name)
    if field is None:
        return False, None
    f = norm(field)
    cands = [f'{norm(q)}.{f}' for q in quals] + [f]
    if not quals:
        cands += [k for k in values if isinstance(k, str) and k.rpartition('.')[2] == f and '.' in k]
    for c in cands:
        if c in values:
            return True, values[c]
    return False, None


def _input_key(k):
    field, quals = parse_ref(k)
    return f'{quals[0]}.{field}' if field and quals else k


def same_value(expected, actual):
    if actual is None:
        return False
    a, b = _num(expected), _num(actual)
    if a is not None and b is not None:
        return a == b
    ex = str(expected).rstrip()
    ac = str(actual).rstrip()
    if ex.upper() in ('SPACES', 'SPACE') and ac.strip() == '':
        return True
    if ex.upper() in ('ZEROS', 'ZERO', 'ZEROES'):
        return _num(actual) == 0
    return ex == ac


def check_expected(model, s, run, dyn, rules_hit):
    exp = s.get('expected') or {}
    checks = []
    want_status = exp.get('status', 'SUCCESS')
    checks.append({'check': 'status', 'expected': want_status, 'actual': run['status'],
                   'result': 'MATCH' if run['status'] == want_status else 'DIFF'})
    for k, v in (exp.get('outputs') or {}).items():
        sub = re.fullmatch(r'\s*(.+?)\s*\(\s*(\d+)\s*\)\s*', k)   # CAMPO(n): a ocorrência n de um campo de tabela (OCCURS)
        found, act = lookup(run['outputs'], sub.group(1) if sub else k)
        if sub and found:
            i = int(sub.group(2))
            act = act[i - 1] if isinstance(act, (list, tuple)) and 1 <= i <= len(act) else (act if not isinstance(act, (list, tuple)) and i == 1 else None)
        res = 'MISSING' if not found else ('MATCH' if same_value(v, act) else 'DIFF')
        checks.append({'check': 'output', 'name': k, 'expected': v, 'actual': act, 'result': res})
    final = {k.upper(): v for k, v in run.get('final_tables', {}).items()}
    for t, rows in (exp.get('tables') or {}).items():
        have = final.get(t.upper(), [])
        for r in rows:
            want = {norm(a): b for a, b in r.items()}
            ok = any(all(same_value(b, {norm(x): y for x, y in h.items()}.get(a)) for a, b in want.items()) for h in have)
            checks.append({'check': 'table_row', 'name': t, 'expected': r, 'result': 'MATCH' if ok else 'DIFF'})
    finais = {k.upper(): v for k, v in (run.get('final_files') or {}).items()}
    for fn, rows in (exp.get('files') or {}).items():
        recs = (finais.get(fn.upper()) or {}).get('records', []) if isinstance(finais.get(fn.upper()), dict) else []
        if isinstance(rows, int):  # só a quantidade de registros do arquivo ao final
            checks.append({'check': 'file_count', 'name': fn, 'expected': rows, 'actual': len(recs), 'result': 'MATCH' if len(recs) == rows else 'DIFF'})
            continue
        for r in rows:
            want = {norm(a): b for a, b in r.items()}
            ok = any(all(same_value(b, {norm(x): y for x, y in h.items()}.get(a)) for a, b in want.items()) for h in recs)
            checks.append({'check': 'file_record', 'name': fn, 'expected': r, 'result': 'MATCH' if ok else 'DIFF'})
    # filas IBM MQ ao fim (só o que foi confirmado em SYNCPOINT): cada mensagem esperada traz campos que precisam estar na mensagem da mesma posição
    filas = {k.strip(): v for k, v in (run.get('final_queues') or {}).items()}
    for fila, msgs in (exp.get('mq') or {}).items():
        reais = filas.get(fila.strip(), [])
        checks.append({'check': 'mq_count', 'name': fila, 'expected': len(msgs), 'actual': len(reais), 'result': 'MATCH' if len(msgs) == len(reais) else 'DIFF'})
        for i, m in enumerate(msgs):
            real = reais[i] if i < len(reais) else {}
            dados = real.get('dados') if isinstance(real.get('dados'), dict) else {}
            ok = all(str(dados.get(k, real.get(k))) == str(v) for k, v in m.items())
            checks.append({'check': 'mq_message', 'name': f'{fila}[{i + 1}]', 'expected': m, 'actual': {k: dados.get(k, real.get(k)) for k in m}, 'result': 'MATCH' if ok else 'DIFF'})
    called = {c['target'] for c in dyn['calls'] if c['target']}
    for p in exp.get('calls', []):
        checks.append({'check': 'call', 'name': p, 'result': 'MATCH' if p.upper() in called else 'DIFF'})
    for p in exp.get('not_calls', []):
        checks.append({'check': 'not_call', 'name': p, 'result': 'MATCH' if p.upper() not in called else 'DIFF'})
    taken = {(b['program'], b['line'], b['result']) for b in dyn['branches']}
    for step in exp.get('path', []):
        prog = step['program'].upper()
        x = model['programs'].get(prog)
        el = x['linemap'].to_expanded(int(step['line'])) if x else None
        res = _label(step['result']) if isinstance(step['result'], bool) else str(step['result']).upper().replace('WHEN:', 'WHEN_')
        checks.append({'check': 'path', 'name': f"{prog}:{step['line']}", 'expected': res,
                       'result': 'MATCH' if (prog, el, res) in taken else 'DIFF'})
    for rid in exp.get('rules', []):
        checks.append({'check': 'business_rule', 'name': rid, 'result': 'MATCH' if rid in rules_hit else 'DIFF'})
    return checks


def validate_against_static(model, dyn):
    """Caminho percorrido x análise estática: decisões, contexto, efeitos, SQL, chamadas, regras."""
    progs = model['programs']
    divergences, warnings = [], []
    coverage = {}
    exercised = {}
    taken_all = {}
    by_prog = {}
    for b in dyn['branches']:
        by_prog.setdefault(b['program'], []).append(b)

    def src(p, ln):
        x = progs.get(p)
        return x['linemap'].source_line(ln) if x else ln

    for p, bs in by_prog.items():
        x = progs.get(p)
        if not x:
            continue
        decisions = {d['line']: d for d in x['decision_tree']['decisions']}
        by_id = {d['decision_id']: d for d in x['decision_tree']['decisions']}
        owner = {(d['decision_id'], b['result']): b.get('falls_through_to') or b['result'] for d in decisions.values() for b in d['branches']}
        last = {}
        ex = set()
        taken = set()
        for b in bs:
            d = decisions.get(b['line'])
            if d is None:
                divergences.append({'type': 'DECISAO_SEM_CORRESPONDENTE_ESTATICO', 'program': p, 'line': src(p, b['line']), 'result': b['result']})
                continue
            labels = {br['result'] for br in d['branches']}
            if b['result'] == 'NO_MATCH':
                warnings.append({'type': 'RAMO_IMPLICITO_NO_MATCH', 'program': p, 'line': src(p, b['line']),
                                 'detail': 'EVALUATE sem WHEN OTHER não casou nenhum WHEN; a árvore estática não tem esse ramo'})
            elif b['result'] not in labels:
                divergences.append({'type': 'RAMO_INEXISTENTE_NA_ARVORE', 'program': p, 'line': src(p, b['line']), 'result': b['result']})
                continue
            eff = owner.get((d['decision_id'], b['result']), b['result'])
            for anc in d['path_context']:
                got = last.get(anc['decision_id'])
                if got is None:
                    divergences.append({'type': 'CONTEXTO_AUSENTE', 'program': p, 'line': src(p, b['line']),
                                        'detail': f"decisão ancestral na linha {src(p, by_id[anc['decision_id']]['line'])} não foi avaliada antes"})
                elif got != anc['result']:
                    divergences.append({'type': 'CONTEXTO_DIVERGENTE', 'program': p, 'line': src(p, b['line']),
                                        'detail': f"ancestral linha {src(p, by_id[anc['decision_id']]['line'])}: estático exige {anc['result']}, execução deu {got}"})
            last[d['decision_id']] = eff
            taken.add((d['decision_id'], b['result']))
            ex.add((d['decision_id'], b['result']))
            ex.add((d['decision_id'], eff))
        exercised[p] = ex
        taken_all[p] = taken
        total = sum(len(d['branches']) for d in decisions.values())
        hit = {(i, r) for i, r in taken if r != 'NO_MATCH'}
        coverage[p] = {'decisions': len(decisions), 'branches': total,
                       'branches_exercised': len(hit),
                       'decisions_evaluated': len({i for i, _ in ex})}

    # efeitos previstos nos ramos percorridos x observados
    sql_seen = {(q['program'], q['line']) for q in dyn['sql']}
    call_seen = {(c['caller'], c['line']) for c in dyn['calls']}
    for p, ex in exercised.items():
        x = progs[p]
        for d in x['decision_tree']['decisions']:
            for br in d['branches']:
                if (d['decision_id'], br['result']) not in ex or br.get('falls_through_to'):
                    continue
                for e in br['effects']:
                    t, ln = e.get('type'), e.get('line')
                    if t == 'EXEC_SQL' and (p, ln) not in sql_seen:
                        warnings.append({'type': 'EFEITO_PREVISTO_NAO_OBSERVADO', 'program': p, 'line': src(p, ln), 'effect': 'SQL',
                                         'branch': f"linha {src(p, d['line'])} {br['result']}"})
                    elif (t == 'CALL' or (t == 'EXEC_CICS' and (e.get('resolved_detail') or {}).get('operation') in ('LINK', 'XCTL'))) \
                            and (p, ln) not in call_seen:
                        warnings.append({'type': 'EFEITO_PREVISTO_NAO_OBSERVADO', 'program': p, 'line': src(p, ln), 'effect': 'CHAMADA',
                                         'branch': f"linha {src(p, d['line'])} {br['result']}"})
    # SQL executado x SQL conhecido estaticamente
    for q in dyn['sql']:
        x = progs.get(q['program'])
        if x and q['line'] not in {s['line'] for s in x['sql']}:
            divergences.append({'type': 'SQL_NAO_PREVISTO', 'program': q['program'], 'line': src(q['program'], q['line'])})
    # chamadas executadas x grafo estático
    for c in dyn['calls']:
        x = progs.get(c['caller'])
        if not x:
            continue
        st = next((s for s in x['calls'] if s['line'] == c['line']), None)
        base = {'program': c['caller'], 'line': src(c['caller'], c['line']), 'target': c['target']}
        if st is None:
            divergences.append({'type': 'CHAMADA_NAO_PREVISTA', **base})
        elif c['target'] is None:
            warnings.append({'type': 'CHAMADA_SEM_DESTINO', **base, 'detail': f"variável {st['raw']} vazia no momento da chamada"})
        elif st['target'] is None:
            warnings.append({'type': 'DESTINO_RESOLVIDO_SO_EM_EXECUCAO', **base, 'detail': f"{st['raw']} ({st['resolution']})"})
        elif st['target'] != c['target']:
            divergences.append({'type': 'DESTINO_DIVERGENTE', **base, 'static_target': st['target']})
    # regras de negócio exercitadas
    rules_hit = set()
    for p, ex in exercised.items():
        for r in progs[p]['rules']['business_rules']:
            if all((s['decision_id'], s['result']) in ex for s in r['decision_path']):
                rules_hit.add(r['rule_id'])
    return {'divergences': divergences, 'warnings': warnings, 'coverage': coverage,
            'exercised': {p: sorted([list(t) for t in ex]) for p, ex in exercised.items()},
            'taken': {p: sorted([list(t) for t in tk]) for p, tk in taken_all.items()}, 'rules_hit': sorted(rules_hit)}


def fixture_warnings(model, s):
    """Tabelas/colunas do cenário conferidas contra o catálogo DCLGEN (quando existir)."""
    cat = model['dclgen']
    tables = {}
    for m in cat['members'].values():
        if m['table']:
            tables[m['table']] = {c['name'] for c in m['columns']}
    out = []
    if not tables:
        return out
    for t, rows in (s.get('tables') or {}).items():
        key = t.upper()
        cols = tables.get(key) or next((v for k, v in tables.items() if k.split('.')[-1] == key.split('.')[-1]), None)
        if cols is None:
            out.append({'type': 'TABELA_SEM_DCLGEN', 'table': t})
            continue
        for r in rows:
            for c in r:
                if norm(c) not in cols:
                    out.append({'type': 'COLUNA_INEXISTENTE_NA_DCLGEN', 'table': t, 'column': c})
    return out


# --------------------------------------------------------------------------- #
# Execução
# --------------------------------------------------------------------------- #
def run_scenario(model, s, outdir=None, runs=3, max_steps=100000):
    entry = s['entry_point'].upper()
    if entry not in model['programs']:
        return {'name': s['name'], 'entry_point': entry, 'status': 'INVALID', 'error': f'entry point {entry} não encontrado nos fontes'}
    mocks, mock_info = mock_plan(model, s)
    programs = {p: x['expanded_file'] for p, x in model['programs'].items() if p not in mocks}
    rt_in = runtime_input(model, s)
    # Entradas/saídas deduzidas do código para campos sem declaração (copybook ausente); "deduce_inputs": false desliga.
    reach = io_runtime.reachable(model, entry, mocks)
    ded = io_runtime.plan(model, s, entry, mocks) if s.get('deduce_inputs', True) else None
    if ded:
        for k, v in ded['seeds'].items():
            rt_in['inputs'].setdefault(k, v)
    sdir = Path(outdir) / slug(s['name']) if outdir else None
    if sdir:
        sdir.mkdir(parents=True, exist_ok=True)
    first, hashes = None, []
    for i in range(runs):
        rt = Runtime(programs, mocks=mocks, max_steps=s.get('max_steps', max_steps))
        kw = {'log_path': str(sdir / 'trace.log'), 'jsonl_path': str(sdir / 'trace.jsonl')} if (sdir and i == 0) else {}
        r = rt.run(entry, copy.deepcopy(rt_in), **kw)
        hashes.append(trace_hash(r))
        if first is None:
            first = r
    dyn = dynamic_path(first)
    val = validate_against_static(model, dyn)
    checks = check_expected(model, s, first, dyn, set(val['rules_hit']))
    deterministic = len(set(hashes)) == 1
    ok = deterministic and all(c['result'] == 'MATCH' for c in checks)

    def src(p, ln):
        x = model['programs'].get(p)
        return x['linemap'].source_line(ln) if x else ln

    mocks_used = sorted({c['target'] for c in dyn['calls'] if c['mode'] == 'MOCK'})
    io, io_warns = io_runtime.finish(model, ded, s, first, lookup)
    res = {
        'name': s['name'], 'file': s.get('_file'), 'entry_point': entry,
        'is_entry_point': entry in model['entry_points'],
        'status': 'PASS' if ok else 'FAIL', 'runtime_status': first['status'], 'errors': first['errors'],
        'deterministic': deterministic, 'trace_hashes': hashes,
        'checks': checks,
        'static_consistency': 'CONSISTENTE' if not val['divergences'] else 'DIVERGENTE',
        'divergences': val['divergences'], 'warnings': val['warnings'] + fixture_warnings(model, s) +
        (ded['warnings'] if ded else []) + io_warns + io_runtime.mock_warnings(model, reach, mocks_used, mock_info),
        'mock_plan': mock_info, 'mocks_used': mocks_used,
        'executed_programs': first['executed_programs'],
        'path': [{'program': b['program'], 'line': src(b['program'], b['line']), 'result': b['result']} for b in dyn['branches']],
        'calls': [{**c, 'line': src(c['caller'], c['line'])} for c in dyn['calls']],
        'sql': [{**q, 'line': src(q['program'], q['line'])} for q in dyn['sql']],
        'coverage': val['coverage'], 'business_rules_exercised': val['rules_hit'], 'io': io,
        'outputs': first['outputs'], 'final_tables': first.get('final_tables', {}),
        '_exercised': val['exercised'], '_taken': val['taken'], '_lines': _executed_lines(first['trace']),
    }
    if sdir:
        (sdir / 'result.json').write_text(json.dumps({k: v for k, v in res.items() if not k.startswith('_')}, indent=2, default=str, ensure_ascii=False), encoding='utf-8')
    return res


def slice_coverage(model, results):
    """Cobertura por entry point só dos ramos alcançáveis a partir dele (slice_reach): o denominador de cada programa
    chamado é a fatia que o chamador realmente usa, e o numerador só conta os cenários daquele entry point."""
    out = {}
    for e in model['entry_points']:
        taken = set()
        for r in results:
            if r.get('entry_point') == e:
                for p, ts in r.get('_taken', {}).items():
                    taken |= {(p, t[0], t[1]) for t in ts if t[1] != 'NO_MATCH'}
        out[e] = {}
        for p, x in slice_reach.slices(model, e).items():
            dec = {d['decision_id']: d for d in model['programs'][p]['decision_tree']['decisions']}
            sl = x['branches']
            hit = {b for b in sl if (p, b[0], b[1]) in taken}
            outside = sorted(f'{d}:{b}' for (q, d, b) in taken if q == p and (d, b) not in sl)
            out[e][p] = {'branches': len(sl), 'exercised': len(hit), 'pct': round(100 * len(hit) / len(sl), 1) if sl else None,
                         'pruned': sum(len(d['branches']) for d in dec.values()) - len(sl),
                         'paragraphs_reached': x['paragraphs'][0], 'paragraphs_total': x['paragraphs'][1],
                         'called_from': sorted(x['via']), 'constants': x['consts'], 'outside_slice_taken': outside,
                         'uncovered': [{'decision_id': d, 'line': dec[d]['line'], 'type': dec[d]['type'], 'expression': dec[d]['expression'], 'branch': b}
                                       for d, b in sorted(sl - hit, key=lambda k: (dec[k[0]]['line'], k[1]))]}
    return out


def aggregate(model, results):
    progs = model['programs']
    cov = {}
    rules_all = {}
    uncovered = {}
    for p, x in progs.items():
        dec = x['decision_tree']['decisions']
        ex, tk = set(), set()
        for r in results:
            ex |= {tuple(t) for t in r.get('_exercised', {}).get(p, [])}
            tk |= {tuple(t) for t in r.get('_taken', {}).get(p, [])}
        br_total = sum(len(d['branches']) for d in dec)
        hit = {(i, r) for i, r in tk if r != 'NO_MATCH'}
        missing = [{'decision_id': d['decision_id'], 'line': d['line'], 'type': d['type'], 'expression': d['expression'], 'branch': b['result']}
                   for d in dec for b in d['branches'] if (d['decision_id'], b['result']) not in hit]
        uncovered[p] = missing
        brs = [r for r in x['rules']['business_rules']]
        rules_hit = {r['rule_id'] for r in brs if all((s['decision_id'], s['result']) in ex for s in r['decision_path'])}
        rules_all[p] = {'business_rules': len(brs), 'exercised': len(rules_hit)}
        cov[p] = {'executed_in_scenarios': any(p in r.get('executed_programs', []) for r in results),
                  'mocked_in_scenarios': any(p in r.get('mocks_used', []) for r in results),
                  'infrastructure': x['infrastructure'], 'decisions': len(dec), 'branches': br_total,
                  'branches_exercised': len(hit), 'branch_coverage_pct': round(100 * len(hit) / br_total, 1) if br_total else None,
                  **{'business_rules': len(brs), 'business_rules_exercised': len(rules_hit)}}
    lines, paras, taken_all = {}, {}, {}
    for r in results:
        for p, ls in r.get('_lines', {}).get('lines', {}).items():
            for ln in ls:
                lines.setdefault(p, {}).setdefault(ln, 0)
                lines[p][ln] += 1
        for p, ps in r.get('_lines', {}).get('paras', {}).items():
            paras.setdefault(p, set()).update(tuple(x) for x in ps)
        for p, ts in r.get('_taken', {}).items():
            taken_all.setdefault(p, set()).update(tuple(t) for t in ts)
    executed_lines = {p: [[ln, n] for ln, n in sorted(v.items())] for p, v in sorted(lines.items())}
    executed_paragraphs = {p: sorted(map(list, v)) for p, v in sorted(paras.items())}
    taken_branches = {p: sorted(map(list, v)) for p, v in sorted(taken_all.items())}
    ep = {e: [r['name'] for r in results if r.get('entry_point') == e] for e in model['entry_points']}
    slice_cov = slice_coverage(model, results)
    summary = {
        'scenarios': len(results), 'pass': sum(r['status'] == 'PASS' for r in results),
        'fail': sum(r['status'] != 'PASS' for r in results),
        'static_divergent': sum(r.get('static_consistency') == 'DIVERGENTE' for r in results),
        'entry_points': len(model['entry_points']),
        'entry_points_with_scenario': sum(bool(v) for v in ep.values()),
        'entry_points_without_scenario': sorted(e for e, v in ep.items() if not v),
        'branches_exercised': sum(c['branches_exercised'] for c in cov.values() if not c['infrastructure']),
        'branches_total_non_infra': sum(c['branches'] for c in cov.values() if not c['infrastructure']),
        'business_rules_exercised': sum(c['business_rules_exercised'] for c in cov.values()),
        'business_rules_total': sum(c['business_rules'] for c in cov.values()),
    }
    return {'summary': summary, 'executed_lines': executed_lines, 'executed_paragraphs': executed_paragraphs, 'taken_branches': taken_branches, 'coverage_by_program': cov, 'scenarios_by_entry_point': ep, 'slice_coverage': slice_cov,
            'uncovered_branches': {p: v for p, v in uncovered.items() if v and not progs[p]['infrastructure']}}


def template(model, program, policy='infra_and_external'):
    """Modelo de cenário para um entry point: entradas candidatas (LINKAGE), 88s e mocks previstos."""
    p = program.upper()
    x = model['programs'][p]
    link = x['linkage']
    c88 = {k: v for k, v in x['data_model']['conditions_88'].items() if any(i['name'] == v['parent'] for i in link)}
    fake = {'entry_point': p, 'mock_policy': policy}
    mocks, info = mock_plan(model, fake)
    reach = set()
    stack = [p]
    while stack:
        q = stack.pop()
        if q in reach:
            continue
        reach.add(q)
        if q in model['programs'] and q not in mocks:
            stack += [c['target'] for c in model['programs'][q]['calls'] if c['target']]
    calls = [c for c in x['calls']]
    pl = io_runtime.plan(model, fake, p, mocks)
    return {
        'name': f'{p} - descreva o caso',
        'entry_point': p,
        'mock_policy': policy,
        'deduce_inputs': True,
        'inputs': {'EIBCALEN': 1},
        '_entradas_deduzidas': [{'campo': r['field'], 'tipo': r['type'], 'valor_inicial': r['initial'], 'copybook_ausente': r['copybook'] or r['candidates']}
                                for r in pl['inputs'] if r['origin'] != 'CENARIO'],
        '_saidas_deduzidas': [{'campo': r['field'], 'tipo': r['type'], 'copybook_ausente': r['copybook'] or r['candidates']} for r in pl['outputs']],
        '_entradas_candidatas': {i['name']: i['pic'] for i in link if i['level'] != 88 and i['pic']},
        '_opcoes_88_nas_entradas': {k: {'campo': v['parent'], 'valor': v['value']} for k, v in c88.items()},
        'tables': {},
        'mocks': {q: {'_motivo': info[q]['reason'], 'returns': {},
                      '_commarea_passada': sorted({c.get('commarea') for pp in reach if pp in model['programs'] for c in model['programs'][pp]['calls'] if c['target'] == q and c.get('commarea')})}
                  for q in sorted(mocks) if q in reach},
        'execute': [],
        'expected': {'status': 'SUCCESS', 'outputs': {}, 'calls': [], 'path': [], 'rules': []},
        '_programas_alcancaveis': sorted(reach),
        '_chamadas_do_entry_point': [{'line': x['linemap'].source_line(c['line']), 'mechanism': c['mechanism'], 'target': c['target'] or c['raw']} for c in calls],
    }
