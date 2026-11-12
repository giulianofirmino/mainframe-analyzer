"""Regras de dado por caminho de decisão: para cada efeito de negócio do programa, o caminho de decisões que o executa, incluindo
os desvios que passam por PERFORM e os ramos que encerram o programa (o que vem depois de um IF que termina só roda com a condição negada).
Só AST e tokens; nenhum nome do código analisado fixado aqui.

Uma regra = um caminho de decisão + os efeitos de negócio que ele produz. Efeito de negócio:
  gravação      INSERT/UPDATE/DELETE em tabela ou WRITE/REWRITE em arquivo;
  chamada       envio de área a outro programa (CALL, CICS LINK/XCTL);
  valor fixo    atribuição de constante a um campo que chega à saída do programa.
Os demais fluxos do mesmo caminho (MOVE de campo a campo, leituras, chaves de busca) são só detalhe: entram na regra como referência
ao fluxo (Fnnnn, o mesmo id da linhagem), sem virar efeito.

Sinais estruturais (calculados do AST e do fluxo de dados):
  entrada        todas as condições testam só campos que vêm de fora (derivados da LINKAGE ou nunca atribuídos no programa);
  status         alguma condição testa nome de runtime (SQLCODE, EIBRESP, ...);
  tabela         alguma condição testa dado lido de tabela;
  encerra        o trecho do caminho termina o programa (GOBACK, STOP RUN, CICS RETURN, PERFORM de parágrafo que termina);
  valor fixo, gravação, chamada  como acima.
Tipo, na ordem: gravação -> alteração de estado; valor fixo com status -> tratamento de erro; valor fixo + encerra + entrada -> validação;
valor fixo + encerra (condição de tabela/cálculo) -> tratamento de erro; valor fixo sem encerrar: condição só de entrada -> derivação,
senão tratamento de erro; só chamada -> roteamento. O que não tem efeito de negócio não é regra e fica contado.
Cada condição do caminho leva o código da decisão do mapa de decisão (Dnnn); cada efeito e detalhe leva o id do fluxo (Fnnnn)."""
from collections import defaultdict

from decision_tree import _id
from data_flow import refs, Scope
from io_deduction import is_runtime_name
from token_utils import V, perform_spec, find, join_tokens, tokens_of

MAX_VISITS = 400000
MAX_PATHS_PER_FLOW = 24


def build(model, flows, dmaps=None, namers=None):
    dmaps = dmaps or {}
    out = {p: program_rules(x, flows[p], dmaps.get(p)) for p, x in model['programs'].items()}
    infra = {p for p, x in model['programs'].items() if ((x.get('classification') or {}).get('classification')) == 'INFRAESTRUTURA'}
    for p, x in model['programs'].items():     # regra de programa que a fase 0 classificou como infraestrutura é de infraestrutura
        if p in infra:
            for r in out[p]['rules']:
                r['scope'] = {'scope': 'infraestrutura', 'reason': 'programa classificado como INFRAESTRUTURA na fase 0'}
        else:
            _mecanismos_implicitos(x, flows[p], out[p]['rules'], infra, dmaps.get(p))
    return out


ESCOPO_MECANISMO = 'mecanismos implícitos'


def _areas_enviadas(rules, so_infra=None):
    """Áreas (grupos) que o programa envia em chamadas a outros programas (efeitos 'chamada'); com so_infra, só as enviadas a esses programas."""
    out = set()
    for r in rules:
        for e in r['effects']:
            if e['nature'] == 'chamada' and e.get('value') and (so_infra is None or e['target'] in so_infra):
                out |= {v.strip() for v in str(e['value']).split(',') if v.strip()}
    return out


def _estado_de_cursor(prog, flow, dmap=None):
    """(campos de estado da paginação por cursor, códigos das decisões que controlam a página).
    Estado: campos do cabeçalho do laço que lê o cursor (UNTIL, TIMES, VARYING), campos atribuídos no parágrafo do FETCH em laço e os que trocam valor
    com eles num MOVE (por exemplo o número da página que volta ao chamador). Controle: decisão cujos ramos atribuem algum campo de estado."""
    loops = cursor_loops(prog)
    if not loops:
        return set(), set()
    est = set()
    paras = {f.get('paragraph') for f in flow['flows'] if f.get('op') == 'FETCH' and f.get('line') in loops}
    campos = {str(x['name']).upper().split('.')[-1] for f in flow['flows'] for x in [f['to']] + list(f['from'] or []) if x['type'] == 'campo'}
    testados = set()    # campos que alguma decisão do programa testa

    def colhe(nodes):
        for n in nodes:
            if not isinstance(n, dict):
                continue
            for txt in [n.get('condition'), n.get('subject')] + [w.get('condition') for w in n.get('whens') or []]:
                if txt:
                    testados.update(str(t[1]).upper() for t in tokens_of(' ' * 7 + str(txt), fixed=False) if t[0] == 'IDENT')
            for key in ('then', 'else_body', 'body'):
                if isinstance(n.get(key), list):
                    colhe(n[key])
            for w in n.get('whens') or []:
                colhe(w.get('body') or [])
    colhe(prog['ast']['body'])
    for lp in loops.values():
        for txt in (lp.get('until') or '', lp.get('perform') or ''):
            est |= {str(t[1]).upper() for t in tokens_of(' ' * 7 + txt, fixed=False) if t[0] == 'IDENT' and str(t[1]).upper() in campos}
    for f in flow['flows']:   # só contador (ADD de literal) e indicador (MOVE de literal no parágrafo do FETCH); o dado lido pelo FETCH não é estado
        if f['to']['type'] != 'campo' or not f['from'] or not all(x['type'] in ('literal', 'figurativa') for x in f['from']):
            continue
        if str(f['to']['name']).upper().split('.')[-1] in testados and (f.get('op') in ('ADD', 'COMPUTE') or (f.get('op') == 'MOVE' and f.get('paragraph') in paras)):
            est.add(str(f['to']['name']).upper().split('.')[-1])
            est.add(str(f['to']['group']).upper())
    def contadores(nodes):   # ADD literal TO campo: contador de ocorrências lidas
        for n in nodes:
            if not isinstance(n, dict):
                continue
            if n.get('type') == 'ADD' and n.get('args'):
                tk = tokens_of(' ' * 7 + n['args'], fixed=False)
                if tk and tk[0][0] == 'NUMBER':
                    k = next((q for q, x in enumerate(tk) if str(x[1]).upper() == 'TO'), -1)
                    for x in (tk[k + 1:] if k >= 0 else []):
                        if x[0] == 'IDENT' and str(x[1]).upper() in testados:
                            est.add(str(x[1]).upper())
            for key in ('then', 'else_body', 'body'):
                if isinstance(n.get(key), list):
                    contadores(n[key])
            for w in n.get('whens') or []:
                contadores(w.get('body') or [])
    contadores(prog['ast']['body'])
    est = {n for n in est if not _is_command_status(n)}
    from schema_analysis import _move_peers
    peers = _move_peers(prog['ast'])
    for a in list(est):   # o que troca valor com o estado num MOVE (o número da página que volta ao chamador)
        est |= peers.get(a, set())

    def alvos(n):
        if n.get('type') not in ('MOVE', 'ADD', 'COMPUTE') or not n.get('args'):
            return set()
        tk = tokens_of(' ' * 7 + n['args'], fixed=False)
        if n['type'] == 'COMPUTE':
            return {str(tk[0][1]).upper().split('.')[-1]} if tk else set()
        k = next((q for q, x in enumerate(tk) if str(x[1]).upper() == 'TO'), -1)
        return {str(x[1]).upper().split('.')[-1] for x in tk[k + 1:] if x[0] == 'IDENT' and str(x[1]).upper() not in ('OF', 'IN')} if k >= 0 else set()

    def simples(nodes):
        """Corpo só de atribuições, PERFORM e SET: sem decisão aninhada nem acesso a dados (o ramo apenas posiciona a página ou recusa o pedido)."""
        return all(isinstance(n, dict) and n.get('type') not in ('IF', 'EVALUATE', 'EXEC_SQL', 'EXEC_CICS') for n in nodes)

    def atribui(n):
        if n.get('type') != 'EVALUATE':     # posicionar a página é escolher entre ramos que atribuem o estado (início, seguinte...): EVALUATE com mais de um ramo que o atribui
            return False
        corpos = [c for c in (w.get('body') or [] for w in n.get('whens') or []) if c]
        return bool(corpos) and all(simples(c) for c in corpos) and sum(1 for c in corpos if any(alvos(x) & est for x in c)) >= 2
    ids = set()

    def walk(nodes):
        for n in nodes:
            if not isinstance(n, dict):
                continue
            if n.get('type') in ('IF', 'EVALUATE') and atribui(n):
                ids.add(_id(prog['program'], n))
            for key in ('then', 'else_body', 'body'):
                if isinstance(n.get(key), list):
                    walk(n[key])
            for w in n.get('whens') or []:
                walk(w.get('body') or [])
    walk(prog['ast']['body'])
    codigos = {r_['code'] for r_ in (dmap or {}).get('rows', []) if r_.get('decision_id') in ids}
    return est, codigos


def _mecanismos_implicitos(prog, flow, rules, infra, dmap=None):
    """Regra de negócio que é só mecanismo implícito da plataforma/arquitetura, não regra do negócio:
    - roteamento para outra função (o único efeito é chamar outro programa);
    - montagem de chamada à infraestrutura (os efeitos são chamar programa de infraestrutura e preencher a área enviada a ele);
    - erro/retorno repassado (as decisões da regra testam só campos da área que o programa enviou a outro programa: o retorno da chamada);
    - paginação (as decisões testam só campos de controle de leitura de cursor em laço, ou indicadores de bloco de área sem declaração
      de um programa que envia área à infraestrutura).
    Só vale para regra sem consulta nem gravação de tabela e que não seja de tipo validação: validação nunca é descartada por esta heurística (um teste de
    retorno de outra função ou de indicador de bloco que o código trata como validação continua sendo regra de negócio; nem a IA a descarta: o gerador de
    business-rules rejeita 'mecanismos' que citem validação). A regra mantém tipo e subtipo; muda o escopo e ganha 'mecanismo' com a categoria."""
    enviadas = _areas_enviadas(rules)
    infra_env = _areas_enviadas(rules, infra)
    estado, controle = _estado_de_cursor(prog, flow, dmap)
    interface = {str(i['name']).upper() for i in prog.get('linkage', [])}   # área de entrada do próprio programa: dado de negócio recebido, não retorno de chamada
    for r in rules:
        if r['scope']['scope'] != 'negócio' or r['kind'] == 'validação':
            continue
        eff = r['effects']
        cat = None
        if r['kind'] == 'roteamento':
            cat = 'roteamento para outra função'
        elif eff and all((e['nature'] == 'chamada' and e['target'] in infra) or (e['nature'] == 'valor fixo' and e.get('target_group') in infra_env) or
                         (e.get('target_group') in infra_env and e['nature'] not in ('consulta', 'gravação')) for e in eff) and \
                any(e['nature'] == 'chamada' and e['target'] in infra for e in eff):
            cat = 'montagem de chamada à infraestrutura'
        elif not any(e['nature'] in ('consulta', 'gravação') for e in eff):
            by_dec = defaultdict(list)
            for f in r['condition_fields']:
                by_dec[f['decision']].append(f)
            decs = [c for c in r['conditions'] if c.get('code') and not all(k.get('infra') for k in c.get('criteria', [])) and c['code'] in by_dec]
            tipos = set()
            for c in decs:
                fs = by_dec[c['code']]
                t = set()
                if c['code'] in controle:
                    tipos.add('paginação')
                    continue
                for f in fs:
                    nome = str(f['field']).upper().split('.')[-1]
                    if nome in estado or str(f['group']).upper() in estado:
                        t.add('paginação')
                    elif f['group'] in enviadas and nome not in interface and str(f['group']).upper() not in interface:
                        t.add('erro ou retorno repassado de outra função')
                    elif infra_env and f['role'] == 'sem atribuição':   # indicador que o programa nunca atribui (vem da área do framework) num programa que envia área à infraestrutura
                        t.add('paginação')
                    else:
                        t = None
                        break
                if t is None:
                    tipos = None
                    break
                tipos |= t
            if decs and tipos:
                cat = ' e '.join(sorted(tipos))
        if cat:
            r['scope'] = {'scope': ESCOPO_MECANISMO, 'reason': cat}
            r['mecanismo'] = cat


_MERGED_ENDS = set()


def collect_paths(prog, by_line):
    """Caminhos de decisão até cada comando. by_line: {linha do fonte: [chaves]}. Devolve ({chave: {caminho}}, {contextos que encerram})."""
    body = prog['ast']['body']
    lm = prog['linemap']
    labels = {n['name'].upper(): i for i, n in enumerate(body) if n['type'] == 'LABEL'}
    hits = defaultdict(set)
    ends = set()
    budget = [MAX_VISITS]
    fin = [None]

    def step(n, result, cond, key):
        return (_id(prog['program'], n), lm.source_line(n['start_line']), cond, result, key)

    def cond_text(n):
        return ' '.join(str(n.get('condition') or n.get('subject') or '').split())

    def record(n, ctx):
        for k in by_line.get(lm.source_line(n['start_line']), ()):
            if len(hits[k]) < MAX_PATHS_PER_FLOW:
                hits[k].add(tuple(ctx))

    def stop(ctx):
        ends.add(tuple(ctx))
        return True

    def visit(stmts, ctx, stack):
        ctx = list(ctx)
        for n in stmts:
            budget[0] -= 1
            if budget[0] < 0:
                return True
            t = n['type']
            record(n, ctx)
            if t == 'IF':
                c = cond_text(n)
                th = visit(n.get('then') or [], ctx + [step(n, 'Sim', c, 'TRUE')], stack)
                el = visit(n.get('else_body') or [], ctx + [step(n, 'Não', c, 'FALSE')], stack)
                if th and el:
                    return stop(ctx)
                if th:
                    ctx.append(step(n, 'Não', c, 'FALSE'))
                elif el:
                    ctx.append(step(n, 'Sim', c, 'TRUE'))
            elif t == 'EVALUATE':
                for i, w in enumerate(n.get('whens') or []):
                    visit(w['body'], ctx + [step(n, 'WHEN ' + ' '.join(str(w.get('condition') or '').split()), cond_text(n), f'WHEN_{i + 1}')], stack)
            elif t == 'PERFORM':
                if n.get('inline'):
                    visit(n.get('body') or [], ctx, stack)
                else:
                    sp = perform_spec(n.get('header_tokens') or [], False)
                    tg = (sp['target'] or '').upper()
                    if tg in labels and tg not in stack:
                        end = (sp['end'] or tg).upper()
                        ended, ctx = run(tg, end, ctx, stack + [tg])
                        if ended:
                            return stop(ctx)
            elif t == 'EXEC_CICS':
                toks = list(n.get('tokens') or [])
                if toks and V(toks[0]) == 'RETURN':
                    return stop(ctx)
            elif t in ('GOBACK', 'STOP_RUN', 'STOP'):
                return stop(ctx)
        fin[0] = ctx
        return False

    def run(target, end, ctx, stack):
        """Percorre o parágrafo chamado acumulando as condições que o encerram só num ramo (o que vem depois só roda com a condição negada).
        Devolve (encerrou, condições ao sair): quem chamou continua com essas condições."""
        start = labels[target]
        endidx = labels.get(end, start)
        j = start + 1
        cur = list(ctx)
        while j < len(body):
            if j > endidx and body[j]['type'] == 'LABEL':
                break
            if visit([body[j]], cur, stack):
                return True, cur
            cur = fin[0]
            j += 1
        return False, cur

    visit(body, [], [])
    return hits, ends


def path_conditions(dmap, path):
    """Condições de um caminho como referências ao mapa de decisão: [{code, condition, result, line}]."""
    return _refs(dmap, path) if dmap else [{'code': '', 'condition': c, 'result': r, 'line': ln} for _d, ln, c, r, _k in path]


def program_rules(prog, flow, dmap=None):
    sc = Scope(prog)
    lm = prog['linemap']
    by_line = defaultdict(list)
    for k, f in enumerate(flow['flows']):
        by_line[f['line']].append(k)       # todo fluxo de dado do programa (não só os que chegam à saída): vira detalhe da regra do mesmo caminho
    hits, ends = collect_paths(prog, by_line)
    _MERGED_ENDS.clear()
    resolved = {(lm.source_line(c['line']), c['mechanism']): c['target'] for c in prog['calls'] if c.get('target')}
    names88 = _names88(prog['data_model'])
    input_derived = _forward(flow, set(flow['inputs']))
    table_derived = {f['to']['group'] for f in flow['flows'] if f['op'] in ('SELECT', 'FETCH') and f['to']['type'] == 'campo'}
    assigned = {f['to']['group'] for f in flow['flows'] if f['to']['type'] == 'campo'}
    struct = _decision_structure(prog)
    by_dec = defaultdict(list)
    for r_ in (dmap or {}).get('rows', []):
        if r_.get('decision_id'):
            by_dec[r_['decision_id']].append(r_)
    loops = cursor_loops(prog)
    effect_pos = {}
    groups = defaultdict(list)
    for k, paths in hits.items():
        for path in paths:
            groups[path].append(k)
    part = defaultdict(lambda: defaultdict(list))
    for path, ks in groups.items():
        for k in ks:
            fk = flow['flows'][k]
            if _nature(fk) in DATA_NATURES:
                key = ('d', fk['line'], fk['from'][0]['group'] if _is_read(fk) else fk['to']['group'], fk.get('cursor') or '')
            else:
                key = ('o',)
            part[key][_without_success_guards(path) if key[0] == 'd' else path].append(k)
    work = [(key[0] == 'd', _merge_paths(g, ends, flow)) for key, g in sorted(part.items())]
    rules, unclassified = [], defaultdict(int)
    for is_data, groups in work:
      for path, ks in groups.items():
        effs = [flow['flows'][k] for k in sorted(set(ks), key=lambda k: (flow['flows'][k]['line'] or 0, k))]
        conds = path_conditions(dmap, path)
        troca = _business_path(conds)   # cada critério (termo ligado por AND/OR) é avaliado em separado; os de infraestrutura saem da condição


        def sub(steps):   # texto legível (o mesmo das condições da regra) e, nas condições mistas, só o critério de negócio
            out_ = []
            for p_ in steps:
                t_ = _legivel(by_dec, p_)
                out_.append((p_[0], p_[1], troca.get(t_, t_), p_[3], p_[4]))
            return tuple(out_)
        guard_free = _without_early_exit_guards(path, ends)   # as validações superadas são detectadas no caminho original
        decisive0 = sub(_without_success_guards(guard_free))
        infra_decisive = any(_is_infra_failure(st) for st in decisive0)   # algum critério decisivo é o ramo de FALHA do status de um comando: o efeito é tratamento de plataforma
        removed_infra = []
        bpath, bguard = sub(path), sub(guard_free)
        if not infra_decisive:   # regra de negócio: os critérios de infraestrutura que sobraram (testes de sucesso do status) saem e valem só os de negócio
            bpath, conds, removed_infra = _drop_infra(bpath, conds)
            bguard = _drop_infra(bguard, [])[0]
        biz = [(e, _nature(e)) for e in effs]
        business = [(e, n) for e, n in biz if n]
        details = [e for e, n in biz if not n]
        if not business:
            unclassified['sem efeito de negócio (só mapeamento de campos)'] += 1
            continue
        if not path and not is_data:
            unclassified['efeito de negócio sem condição'] += 1
            continue
        is_end = tuple(path) in ends or path in _MERGED_ENDS
        kind, basis, signals = _classify(prog, sc, _without_success_guards(bpath), business, is_end, input_derived, table_derived, assigned, flow['indicators'])
        profile = _condition_profile(prog, sc, _without_success_guards(bguard), input_derived, table_derived, assigned, flow['indicators'])
        decisive = _without_success_guards(bguard)
        if 'valor fixo' in {n for _e, n in business} and ((kind == 'tratamento de erro' and _all_status_on_success(conds)) or (kind in ('validação', 'tratamento de erro') and not decisive)):
            kind, basis = 'retorno de sucesso', 'valor fixo de retorno sem decisão que o distinga: só passa por validações já superadas e por decisões de status no ramo de sucesso'
            signals = signals + ['nenhuma decisão restante além das validações superadas e do status em sucesso']
        eff = _statement_effects(prog['program'], flow, [e for e, _n in business], loops) if is_data else [_effect(e, n, resolved, names88) for e, n in business]
        det = [{'flow': e.get('id'), 'line': e['line'], 'paragraph': e['paragraph'], 'op': e['op'], 'target': _name(e['to']), 'value': ', '.join(_name(s) for s in e['from']) if e['from'] else '', 'text': e.get('text') or '', 'terminal': bool(e.get('terminal'))} for e in details]
        ctxf = _context(prog, sc, flow, dmap, conds, input_derived, table_derived, assigned, resolved)
        _mark_technical(conds, ctxf)
        rid = None
        order_key = __import__('hashlib').sha1(repr((prog['program'], path, [(x['line'], x['target']) for x in eff])).encode()).hexdigest()
        for e in eff:
            effect_pos.setdefault((e.get('paragraph') or '', e['op'], e['target']), set()).add(e['line'] or 0)
        rules.append({'rule_id': rid, '_path': path, '_order': order_key, 'program': prog['program'], 'kind': kind, 'basis': basis, 'signals': signals, 'ends_flow': is_end,
                      'conditions': conds, 'references': [c['code'] for c in conds if c.get('code')], 'condition_fields': ctxf,
                      'reads': _reads(ctxf) + [{'table': e['target'], 'column': None, 'lineage_id': e['lineage_id'], 'via': 'consulta'} for e in eff if e['nature'] == 'consulta'],
                      'effects': eff, 'details': det,
                      'scope': _scope(infra_decisive, removed_infra, conds),
                      'subtype': _subtype(kind, _scope(infra_decisive, removed_infra, conds), profile),
                      'removed_infra': removed_infra,
                      'tables': sorted({e['target_group'] for e in eff if e['nature'] == 'gravação' and e['target_kind'] == 'tabela'}),
                      'tables_read': sorted({e['target'] for e in eff if e['nature'] == 'consulta'}),
                      'called': sorted({e['target'] for e in eff if e['nature'] == 'chamada'}),
                      'paragraphs': sorted({e['paragraph'] or '' for e in eff} | {d['paragraph'] or '' for d in det})})
    for r in rules:
        r['rule_id'] = _structural_id(prog['program'], r.pop('_path'), r['effects'], struct, effect_pos)
    rules.sort(key=lambda r: (r['effects'][0]['line'] or 0, r.pop('_order')))
    for i, r in enumerate(rules, 1):
        r['code'] = f'R{i:03d}'
    return {'program': prog['program'], 'rules': rules, 'unclassified': dict(sorted(unclassified.items())), 'inputs': flow['inputs'], 'outputs': flow['outputs'],
            'status_commands': status_commands(prog, dmap)}


def cursor_loops(prog):
    """{linha do FETCH: laço que o repete}: o PERFORM (em linha ou de parágrafo) com UNTIL, VARYING ou TIMES que contém o FETCH. Só AST e tokens.
    {'line', 'perform': texto do cabeçalho, 'until', 'target'}. FETCH fora de laço não aparece."""
    body, lm = prog['ast']['body'], prog['linemap']
    labels = {n['name'].upper(): i for i, n in enumerate(body) if n['type'] == 'LABEL'}
    out = {}

    def describe(n, spec):
        return {'line': lm.source_line(n['start_line']), 'perform': 'PERFORM ' + join_tokens(list(n.get('header_tokens') or [])), 'until': spec['until'] or '', 'target': spec['target'] or ''}

    def looping(spec):
        return bool(spec['until'] or spec['times'] or spec['varying'])

    def walk(nodes, loop, seen):
        for n in nodes:
            if not isinstance(n, dict):
                continue
            t = n.get('type')
            toks = n.get('tokens') or []
            if t == 'EXEC_SQL' and toks and V(toks[0]) == 'FETCH' and loop:
                out.setdefault(lm.source_line(n['start_line']), loop)
            if t == 'PERFORM':
                sp = perform_spec(n.get('header_tokens') or [], bool(n.get('inline')))
                lp = describe(n, sp) if looping(sp) else loop
                if n.get('inline'):
                    walk(n.get('body') or [], lp, seen)
                else:
                    tg = (sp['target'] or '').upper()
                    if lp and tg in labels and tg not in seen:
                        end = labels.get((sp['end'] or tg).upper(), labels[tg])
                        j = labels[tg] + 1
                        while j < len(body) and not (j > end and body[j]['type'] == 'LABEL'):
                            walk([body[j]], lp, seen | {tg})
                            j += 1
                continue
            for k in ('then', 'else_body', 'body'):
                if isinstance(n.get(k), list):
                    walk(n[k], loop, seen)
            for w in n.get('whens') or []:
                walk(w.get('body') or [], loop, seen)
    walk(body, None, frozenset())
    return out


def _decision_structure(prog):
    """{id da decisão: (parágrafo, ordem entre as decisões de mesmo texto no parágrafo)}: posição estrutural, que não muda quando linhas são inseridas acima."""
    out, seen = {}, defaultdict(int)

    def walk(nodes, par):
        for n in nodes:
            if not isinstance(n, dict):
                continue
            t = n.get('type')
            if t == 'LABEL':
                par = n['name'].upper()
            if t in ('IF', 'EVALUATE'):
                txt = ' '.join(str(n.get('condition') or n.get('subject') or '').split())
                out[_id(prog['program'], n)] = (par, txt, seen[(par, txt)])
                seen[(par, txt)] += 1
            for k in ('then', 'else_body', 'body'):
                if isinstance(n.get(k), list):
                    walk(n[k], par)
            for w in n.get('whens') or []:
                walk(w.get('body') or [], par)
    walk(prog['ast']['body'], '')
    return out


def _structural_id(program, path, effects, struct, pos):
    """Id da regra pela estrutura (parágrafo, ordem da decisão e do comando dentro do parágrafo, operação e alvo), sem número de linha:
    inserir ou apagar linhas acima não muda o id; mudar a decisão, o comando ou o alvo muda."""
    import hashlib
    steps = [(struct.get(d, ('', '', 0)), r, k) for d, _ln, _c, r, k in path]
    effs = []
    for e in sorted(effects, key=lambda e: (e['line'] or 0, e['target'])):
        key = (e.get('paragraph') or '', e['op'], e['target'])
        effs.append(key + (sorted(pos[key]).index(e['line'] or 0),))
    return 'BR2-' + hashlib.sha1(repr((program, steps, effs)).encode()).hexdigest()[:12].upper()


def _idents(text):
    from token_utils import tokens_of
    return [t for t in tokens_of(text) if t[0] == 'IDENT']


DATA_NATURES = ('consulta', 'gravação')
GENERIC_FAILURE = 'falha genérica de status de execução'


def _is_read(f):
    return f['op'] in ('SELECT', 'FETCH') and f['to']['type'] == 'campo' and bool(f['from']) and f['from'][0]['type'] == 'tabela'


def _is_command_status(n):
    """Resultado de comando SQL/CICS (SQLCODE, SQLSTATE, SQLWARN*, SQLERR*, EIBRESP*): só estes valem como teste de status de execução. Campos de
    contexto como EIBCALEN (tamanho da área de comunicação) são dado de entrada, não status."""
    return n in ('SQLCODE', 'SQLSTATE', 'RETURN-CODE', 'EIBRESP', 'EIBRESP2') or n.startswith(('SQLWARN', 'SQLERR'))


def _status_kind(text):
    """Como a condição usa o status de execução (SQLCODE, EIBRESP...): ('específico', None) quando compara com valor diferente de zero
    (ex.: SQLCODE = +100); ('genérico', resultado que indica falha) quando só separa sucesso de falha (!= zero, = zero, DFHRESP(NORMAL)); None sem status."""
    from token_utils import tokens_of
    toks = tokens_of(text)
    names = {V(t) for t in toks if t[0] == 'IDENT' and is_runtime_name(V(t)) and _is_command_status(V(t))}
    if not names and not any(t[0] == 'IDENT' and V(t) == 'DFHRESP' for t in toks):
        return None
    equal = False
    for i, t in enumerate(toks):
        if V(t) in names and i + 2 < len(toks) and toks[i + 1][1] in ('==', '='):
            j = i + 2
            while j < len(toks) and toks[j][1] == '=':
                j += 1
            v = toks[j] if j < len(toks) else None
            equal = True
            if v is None:
                continue
            if v[0] == 'NUMBER' and v[1].lstrip('+-').strip('0.') != '':
                return 'específico', None
            if V(v) == 'DFHRESP' and j + 2 < len(toks) and V(toks[j + 2]) != 'NORMAL':
                return 'específico', None
            if V(v) == 'DFHRESP' and j + 2 < len(toks) and V(toks[j + 2]) == 'NORMAL':
                return 'genérico', 'Não'
            if v[0] == 'SYMBOL' and v[1] in ('+', '-') and j + 1 < len(toks) and toks[j + 1][0] == 'NUMBER' and toks[j + 1][1].strip('0.') != '':
                return 'específico', None
    if any(x[1] in ('!=', '<>') for x in toks):
        return 'genérico', 'Sim'
    if equal:
        return 'genérico', 'Não'
    return 'genérico', 'Sim'


def _without_success_guards(path):
    """Caminho sem as decisões genéricas de status em que o ramo seguido é o de sucesso: só dizem que a operação anterior deu certo e não mudam
    de que dado o efeito depende."""
    out = []
    for p in path:
        k = _status_kind(p[2]) if p[3] in ('Sim', 'Não') else None
        if k and ((k[0] == 'genérico' and p[3] != k[1]) or (k[0] == 'específico' and p[3] == 'Não')):
            continue
        out.append(p)
    return tuple(out)


def _mark_technical(conds, ctxf):
    """Marca cada condição do caminho que é só teste genérico de sucesso/falha do status de execução (`technical`)."""
    stat = {c['decision'] for c in ctxf if c['role'] == 'status'}
    for c in conds:
        k = _status_kind(c['condition']) if c.get('code') in stat else None
        c['technical'] = bool(k and k[0] == 'genérico')


def _is_infra_criterion(texto):
    k = _status_kind(texto)
    return bool(k and k[0] == 'genérico')


def _legivel(by_dec, step):
    """Texto legível (do mapa de decisão) da condição de um passo do caminho; o texto cru do passo quando não há mapa."""
    chain = by_dec.get(step[0], [])
    k = next((i for i, r in enumerate(chain) if step[4] in r['true_keys']), None)
    return chain[k]['text'][0] if k is not None else step[2]


def _business_path(conds):
    """Avalia cada critério das condições em separado: condição com critérios de infraestrutura (teste genérico de sucesso/falha do status de execução)
    e de negócio perde os de infraestrutura (em `conds`, o texto passa a ser só o de negócio; o original e os critérios retirados ficam registrados).
    Devolve {texto original: texto de negócio} para o caminho. Condição só de infraestrutura fica como está."""
    import condition_criteria as cc
    troca = {}
    for c in conds:
        r = cc.split(c['condition'], _is_infra_criterion)
        c['criteria'] = r['criteria']
        if r['mixed']:
            troca[c['condition']] = r['business']
            c['condition_original'] = c['condition']
            c['removed_criteria'] = [a['text'] for a in r['criteria'] if a['infra']]
            c['condition'] = r['business']
    return troca


def _is_infra_failure(step):
    """Passo (did, linha, texto, resultado, chave) que segue o ramo de FALHA de um teste genérico de status de execução."""
    k = _status_kind(step[2]) if step[3] in ('Sim', 'Não') else None
    return bool(k and k[0] == 'genérico' and step[3] == k[1])


def _drop_infra(bpath, conds):
    """Retira do caminho e das condições os critérios de infraestrutura (decisão que só testa o status genérico de execução, em qualquer resultado).
    Devolve (caminho, condições, critérios retirados com o resultado)."""
    def pure_infra(texto):
        k = _status_kind(texto)
        return bool(k and k[0] == 'genérico')
    removed, keep = [], []
    for c in conds:
        if c.get('code') is not None and pure_infra(c['condition']):
            removed.append(f'{c["code"]} {c["condition"]} → {c["result"]}')
        else:
            keep.append(c)
    return tuple(p for p in bpath if not pure_infra(p[2])), keep, removed


def _scope(infra_decisive, removed_infra, conds):
    """Escopo para modernização, avaliando cada critério da regra em separado: só é de infraestrutura quando todos os critérios que decidem o caminho são
    o ramo de FALHA de um teste genérico de status de execução (SQLCODE, EIBRESP... sem comparar com valor específico). Validações já superadas e
    testes de sucesso não decidem. Havendo critério de negócio, os de infraestrutura são retirados da regra e vale só o de negócio (inclusive comparar o
    status com um valor específico, SQLCODE = +100: linha não encontrada)."""
    if infra_decisive:
        return {'scope': 'infraestrutura', 'reason': GENERIC_FAILURE}
    if removed_infra or any(c.get('removed_criteria') for c in conds):
        return {'scope': 'negócio', 'reason': 'critério(s) de infraestrutura retirado(s); vale só o de negócio'}
    return {'scope': 'negócio', 'reason': ''}


def _statement_effects(p, flow, fs, loops=None):
    """Um efeito por comando SQL (consulta ou gravação): tabela, colunas (com o campo hospedeiro ou valor) e condições do WHERE."""
    cmds = {(c['line'], c['table'], c['cursor']): c for c in flow.get('commands', [])}
    grp = {}
    for e in fs:
        if _is_read(e):
            grp.setdefault((e['line'], 'consulta', e['from'][0]['group'], e.get('cursor')), []).append(e)
        else:
            grp.setdefault((e['line'], 'gravação', e['to']['group'], e.get('cursor')), []).append(e)
    out = []
    for (line, nat, table, cur), es in sorted(grp.items(), key=lambda x: (x[0][0], x[0][2], x[0][3] or '')):
        cmd = cmds.get((line, table, cur))
        if nat == 'consulta':
            cols = [{'column': x['from'][0]['name'].rsplit('.', 1)[-1], 'host': _name(x['to']), 'flow': x.get('id')} for x in es]
        else:
            cols = [{'column': x['to']['name'].rsplit('.', 1)[-1], 'value': ', '.join(_name(sv) for sv in x['from']), 'flow': x.get('id')} for x in es if x['op'] != 'DELETE']
        out.append({'flow': es[0].get('id'), 'flows': [x.get('id') for x in es], 'nature': nat, 'line': line, 'paragraph': es[0]['paragraph'], 'op': es[0]['op'],
                    'target': table, 'target_kind': 'tabela', 'target_group': table, 'value': '', 'value_kind': '', 'note': None, 'value_name': None,
                    'cursor': cur, 'lineage_id': f'{p}@{line}:{_short(table)}', 'columns': cols, 'where': (cmd or {}).get('where', []),
                    'loop': (loops or {}).get(line)})
    return out


def _nature(e):
    d = e['to']
    if _is_read(e):
        return 'consulta'
    if d['type'] in ('tabela', 'arquivo') and e['op'] != 'FILTRO':
        return 'gravação'
    if d['type'] == 'programa' and e['note'] == 'área enviada':
        return 'chamada'
    if d['type'] == 'campo' and e.get('terminal') and _vkind(e['from']) == 'valor fixo' and e['op'] != 'INITIALIZE':
        return 'valor fixo'
    return None


def _effect(e, nature, resolved=None, names88=None):
    tgt = _name(e['to'])
    if nature == 'chamada' and resolved:
        tgt = resolved.get((e['line'], e['op']), tgt)
    return {'flow': e.get('id'), 'nature': nature, 'line': e['line'], 'paragraph': e['paragraph'], 'op': e['op'], 'target': tgt,
            'target_kind': e['to']['type'], 'target_group': e['to']['group'], 'value': ', '.join(_name(s) for s in e['from']) if e['from'] else '',
            'value_kind': _vkind(e['from']), 'note': e['note'], 'value_name': _value_name(e, names88)}


def _classify(prog, sc, path, business, ends, input_derived, table_derived, assigned, indicators=None):
    natures = {n for _e, n in business}
    groups, status = _cond_groups(prog, sc, [p[2] for p in path])
    indicators = indicators or {}
    null_test = any(V(t) in indicators for p in path for t in _idents(p[2]))
    if null_test:
        groups = {g for g in groups if g not in {sc.top(i) for i in indicators}}
    from_table = bool(groups & table_derived)
    input_only = bool(groups) and not from_table and all(g in input_derived or g not in assigned for g in groups)
    signals = []
    if status:
        signals.append('condição testa status de execução (SQLCODE, EIBRESP...)')
    if from_table:
        signals.append('condição depende de dado lido de tabela')
    if null_test:
        signals.append('condição testa indicador de nulo de coluna SQL')
    if input_only:
        signals.append('condição depende só de dado de entrada')
    if 'valor fixo' in natures:
        signals.append('atribui valor fixo a campo de saída')
    if 'gravação' in natures:
        signals.append('grava em tabela ou arquivo')
    if 'consulta' in natures:
        signals.append('consulta tabela')
    if 'chamada' in natures:
        signals.append('envia área a outro programa')
    if ends:
        signals.append('encerra o programa neste caminho')
    if 'gravação' in natures:
        return 'alteração de estado', 'o caminho insere, altera ou exclui em tabela (ou grava arquivo)', signals
    if natures == {'consulta'}:
        return 'consulta de dados', 'o caminho consulta tabela (SELECT ou FETCH de cursor)', signals
    if 'valor fixo' in natures:
        if null_test and not status:
            return 'derivação', 'valor padrão atribuído quando a coluna lida vem nula (indicador de nulo)', signals
        if status:
            return 'tratamento de erro', 'valor fixo de retorno sob condição de status de execução', signals
        if ends and input_only:
            return 'validação', 'condição só sobre a entrada, valor fixo de retorno e encerramento do programa', signals
        if ends:
            return 'tratamento de erro', 'valor fixo de retorno com encerramento, sob condição de dado lido ou calculado', signals
        if input_only:
            return 'derivação', 'valor fixo atribuído por condição sobre a entrada, sem encerrar o programa', signals
        return 'tratamento de erro', 'valor fixo de retorno sob condição de dado lido ou calculado', signals
    return 'roteamento', 'a condição decide a chamada de outro programa', signals


def _condition_profile(prog, sc, path, input_derived, table_derived, assigned, indicators=None):
    """De onde vêm os campos testados no caminho (só estrutura): `input` = campos que chegam de fora (ou nunca atribuídos), `data` = resultado de comando
    de dados (coluna lida de tabela ou status de SQL/CICS que sobrou no caminho), `other` = campos calculados no próprio programa, `null_test` = indicador de nulo."""
    indicators = indicators or {}
    groups, status = _cond_groups(prog, sc, [p[2] for p in path])
    null_test = any(V(t) in indicators for p in path for t in _idents(p[2]))
    if null_test:
        groups = {g for g in groups if g not in {sc.top(i) for i in indicators}}
    from_table = groups & table_derived
    inp = {g for g in groups - from_table if g in input_derived or g not in assigned}
    return {'input': bool(inp), 'data': bool(from_table) or status, 'other': bool(groups - from_table - inp), 'null_test': null_test}


def _without_early_exit_guards(path, ends):
    """Caminho sem as decisões que só foram vencidas porque o ramo oposto encerra o programa (validação anterior): são pré-requisito de todo o resto
    do programa e não mudam de que dado a regra depende."""
    allends = set(ends) | _MERGED_ENDS
    out = []
    for i, st in enumerate(path):
        if st[3] == 'Não' and st[4] == 'FALSE':
            sim = tuple(path[:i]) + ((st[0], st[1], st[2], 'Sim', 'TRUE'),)
            if any(e[:i + 1] == sim for e in allends):
                continue
        out.append(st)
    return tuple(out)


def _all_status_on_success(conds):
    """Há pelo menos uma decisão de status de execução (SQLCODE, EIBRESP...) no caminho e todas seguem o ramo de sucesso."""
    seen = False
    for c in conds:
        k = _status_kind(c['condition'])
        if not k or c['result'] not in ('Sim', 'Não'):
            continue
        seen = True
        if not ((k[0] == 'genérico' and c['result'] != k[1]) or (k[0] == 'específico' and c['result'] == 'Não')):
            return False
    return seen


SUBTYPES = ('validação de entrada', 'exceção de negócio', 'exceção de negócio com pré-condição', 'condição sobre campo calculado', 'valor padrão por coluna nula',
            'retorno de sucesso', 'falha técnica de execução')


def _subtype(kind, scope, prof):
    """Subtipo decidido só pelos campos da condição: só entrada -> validação de entrada; resultado de comando de dados -> exceção de negócio;
    os dois -> exceção de negócio com pré-condição. Vazio nos tipos que não retornam valor fixo."""
    if kind not in ('validação', 'tratamento de erro', 'derivação', 'retorno de sucesso'):
        return ''
    if scope['scope'] == 'infraestrutura':
        return 'falha técnica de execução'
    if prof['null_test']:
        return 'valor padrão por coluna nula'
    if kind == 'retorno de sucesso':
        return 'retorno de sucesso'
    if prof['data']:
        return 'exceção de negócio com pré-condição' if prof['input'] else 'exceção de negócio'
    if prof['input'] and not prof['other']:
        return 'validação de entrada'
    return 'condição sobre campo calculado'


def _refs(dmap, path):
    """Condições do caminho como referências ao mapa de decisão: [{code, condition, result, line}]. Numa cadeia IF/ELSIF
    (EVALUATE), chegar ao WHEN n exige as condições anteriores da cadeia falsas."""
    by = defaultdict(list)
    for r in dmap['rows']:
        if r['decision_id']:
            by[r['decision_id']].append(r)
    out, seen = [], set()

    def add(r, res):
        if (r['code'], res) not in seen:
            seen.add((r['code'], res))
            out.append({'code': r['code'], 'condition': r['text'][0], 'result': res, 'line': r['source_line']})
    for did, _ln, _c, _res, key in path:
        chain = by.get(did, [])
        k = next((i for i, r in enumerate(chain) if key in r['true_keys']), None)
        if k is not None:
            for r in chain[:k]:
                add(r, 'Não')
            add(chain[k], 'Sim')
        else:
            for r in chain:
                if key in r['false_keys']:
                    add(r, 'Não')
    return out


def _name(x, nm=lambda s: s):
    return nm(x['name']) if x['type'] != 'campo' or x['group'] in (None, x['name']) else f'{nm(x["name"])} ({nm(x["group"])})'


def _vkind(src):
    if src and all(s['type'] in ('literal', 'figurativa') for s in src):
        return 'valor fixo'
    return 'copia/calcula' if src else ''


def _forward(flow, seeds):
    fwd = defaultdict(set)
    for x in flow['flows']:
        if x['to']['type'] == 'campo':
            for s in x['from']:
                if s['type'] == 'campo':
                    fwd[s['group']].add(x['to']['group'])
    seen, st = set(), list(seeds)
    while st:
        g = st.pop()
        if g not in seen:
            seen.add(g)
            st.extend(fwd.get(g, ()))
    return seen


def _cond_groups(prog, sc, exprs):
    from token_utils import tokens_of
    groups, status = set(), False
    for e in exprs:
        toks = tokens_of(e)
        for t in toks:
            if t[0] == 'IDENT' and is_runtime_name(V(t)) and not sc.declared(V(t)):
                status = True
        for r in refs(toks, sc, stop=set()):
            if r['type'] == 'campo':
                groups.add(r['group'])
    return groups, status




SQL_OPS = ('SELECT', 'FETCH', 'INSERT', 'UPDATE', 'DELETE')


def _short(t):
    return t.split('.')[-1]


def _prev_command(dmap, row):
    """Último comando SQL ou CICS antes da decisão `row` na mesma linha de execução: caixas irmãs anteriores da decisão e dos blocos
    que a contêm (sem entrar em ramos de outras decisões), entrando nos PERFORM de parágrafo pela sequência de cima do parágrafo chamado."""
    pars = {p['name']: p['items'] for p in dmap['paragraphs']}

    def locate(items, code, trail):
        for i, it in enumerate(items):
            if it['kind'] == 'decision':
                if it['code'] == code:
                    return trail + [(items, i)]
                for side in ('then', 'else'):
                    r = locate(it[side], code, trail + [(items, i)])
                    if r:
                        return r
        return None

    def last_top(items, upto, depth):
        for it in reversed(items[:upto]):
            if it['kind'] != 'box':
                continue
            if it['sub'] in ('sql', 'cics'):
                return it
            if it['sub'] == 'perform' and depth < 6:
                for t in it['performs']:
                    x = last_top(pars.get(t, []), len(pars.get(t, [])), depth + 1)
                    if x:
                        return x
        return None
    def caller_trails(items, name, trail):
        for i, it in enumerate(items):
            if it['kind'] == 'box' and it['sub'] == 'perform' and name in it['performs']:
                yield trail + [(items, i)]
            elif it['kind'] == 'decision':
                for side in ('then', 'else'):
                    yield from caller_trails(it[side], name, trail + [(items, i)])

    def up(trail, name, seen):
        """Sobe da posição `trail`: comando anterior no mesmo parágrafo; senão, antes de cada PERFORM que chama o parágrafo (primeiro chamador em ordem do fonte)."""
        for items, i in reversed(trail):
            x = last_top(items, i, 0)
            if x:
                return x
        if name in seen:
            return None
        for q in dmap['paragraphs']:
            for t in caller_trails(q['items'], name, []):
                x = up(t, q['name'], seen | {name})
                if x:
                    return x
        return None
    for p in dmap['paragraphs']:
        trail = locate(p['items'], row['code'], [])
        if trail:
            return up(trail, p['name'], frozenset())
    return None


def status_commands(prog, dmap):
    """{código da decisão: comando de que ela testa o status}: para cada decisão cuja condição cita nome de runtime não declarado (SQLCODE, SQLWARN0,
    EIBRESP...), o último SQL ou CICS antes dela. SQL: {'kind':'sql','id','line','op','table','text'}; CICS: {'kind':'cics','line','op','text'}."""
    from token_utils import tokens_of
    if not dmap:
        return {}
    sc = Scope(prog)
    p = prog['program']
    out = {}
    for row in dmap.get('rows', []):
        if row.get('kind') != 'decisão':
            continue
        toks = tokens_of(' '.join(row.get('text') or []))
        names = [V(t) for n, t in enumerate(toks) if t[0] == 'IDENT' and not (n and V(toks[n - 1]) in ('OF', 'IN'))]
        if not any(is_runtime_name(n) and n != 'DFHRESP' and not sc.declared(n) for n in names):
            continue
        cmd = _prev_command(dmap, row)
        if not cmd:
            continue
        text = ' '.join(' '.join(cmd['lines']).split())
        if cmd['sub'] == 'sql':
            tab = cmd['tables'][0] if cmd['tables'] else None
            out[row['code']] = {'kind': 'sql', 'id': f'{p}@{cmd["source_line"]}:{_short(tab)}' if tab else None, 'line': cmd['source_line'], 'op': cmd['sql_op'], 'table': tab, 'text': text}
        else:
            out[row['code']] = {'kind': 'cics', 'id': None, 'line': cmd['source_line'], 'op': 'CICS', 'table': None, 'text': text}
    return out


def _context(prog, sc, flow, dmap, conds, input_derived, table_derived, assigned, resolved=None):
    """Papel de cada campo testado nas condições da regra, para quem lê a regra saber de onde vem o dado:
    entrada (chega de fora), lido de tabela (coluna, comando e linha do SELECT/FETCH), status do último SQL/CICS antes da decisão,
    indicador de nulo de uma coluna, atribuído no programa (comandos que o atribuem) ou sem atribuição (valor inicial ou entrada externa).
    Nome depois de OF/IN é qualificador, não campo; DFHRESP(...) é constante do CICS."""
    from token_utils import tokens_of
    p = prog['program']
    prow = {r['code']: r for r in (dmap or {}).get('rows', [])}
    sel = defaultdict(list)
    setters = defaultdict(list)
    for f in flow['flows']:
        if f['to']['type'] != 'campo':
            continue
        (sel if f['op'] in ('SELECT', 'FETCH') else setters)[f['to']['name']].append(f)
    ind = flow.get('indicators') or {}
    out, seen = [], set()
    for c in conds:
        row = prow.get(c.get('code')) or {}
        toks = tokens_of(c['condition'])
        for n, t in enumerate(toks):
            if t[0] != 'IDENT':
                continue
            if n and V(toks[n - 1]) in ('OF', 'IN'):
                continue
            if n + 1 < len(toks) and toks[n + 1][1] == '(' and V(t) == 'DFHRESP':
                continue
            name = V(t)
            if name == 'DFHRESP' or (c.get('code'), name) in seen:
                continue
            seen.add((c.get('code'), name))
            if is_runtime_name(name) and not sc.declared(name):
                cmd = _prev_command(dmap, row) if row and dmap else None
                if cmd and cmd['sub'] == 'sql':
                    tab = cmd['tables'][0] if cmd['tables'] else None
                    lid = f'{p}@{cmd["source_line"]}:{_short(tab)}' if tab else None
                    out.append({'decision': c.get('code'), 'field': name, 'role': 'status', 'group': None, 'table': tab, 'lineage_id': lid, 'sql_line': cmd['source_line'],
                                'detail': f'status do {cmd["sql_op"]} em {tab} (linha {cmd["source_line"]})'})
                elif cmd:
                    out.append({'decision': c.get('code'), 'field': name, 'role': 'status', 'group': None, 'table': None, 'lineage_id': None, 'sql_line': cmd['source_line'],
                                'detail': f'status do comando CICS da linha {cmd["source_line"]}: {" ".join(cmd["lines"][:1])}'})
                else:
                    out.append({'decision': c.get('code'), 'field': name, 'role': 'status', 'group': None, 'table': None, 'lineage_id': None,
                                'detail': 'status de runtime sem comando SQL/CICS anterior identificado no parágrafo'})
                continue
            if not sc.declared(name):
                continue
            g = sc.top(name)
            if name in ind:
                i = ind[name]
                out.append({'decision': c.get('code'), 'field': name, 'role': 'indicador de nulo', 'group': g, 'table': i['column'].rsplit('.', 1)[0], 'column': i['column'].rsplit('.', 1)[-1],
                            'lineage_id': f'{p}@{i["line"]}:{_short(i["column"].rsplit(".", 1)[0])}',
                            'detail': f'indicador de nulo de {i["column"]} ({i["op"]} na linha {i["line"]}, host {i["host"]})'})
            elif name in sel:
                f = sel[name][0]
                src = f['from'][0]
                out.append({'decision': c.get('code'), 'field': name, 'role': 'lido de tabela', 'group': g, 'table': src['group'], 'column': src['name'].rsplit('.', 1)[-1],
                            'lineage_id': f'{p}@{f["line"]}:{_short(src["group"])}', 'detail': f'{src["name"]} lido por {f["op"]} (linha {f["line"]})'})
            elif g in flow['inputs']:
                out.append({'decision': c.get('code'), 'field': name, 'role': 'entrada', 'group': g, 'detail': f'campo de {g}, que chega de fora do programa'})
            elif g in input_derived and name in setters:
                out.append({'decision': c.get('code'), 'field': name, 'role': 'derivado da entrada', 'group': g,
                            'detail': 'copiado ou calculado de: ' + '; '.join(f'{", ".join(x["name"] for x in f["from"])} ({f["op"]}, linha {f["line"]})' for f in setters[name][:3])})
            elif g not in assigned:
                out.append({'decision': c.get('code'), 'field': name, 'role': 'sem atribuição', 'group': g, 'detail': 'nunca atribuído no programa (valor inicial ou entrada externa)'})
            else:
                fs = setters.get(name, [])
                out.append({'decision': c.get('code'), 'field': name, 'role': 'atribuído no programa', 'group': g,
                            'detail': ('atribuído por ' + '; '.join(f'{f["op"]} (linha {f["line"]})' for f in fs[:3])) if fs else 'atribuído por grupo ou comando não mapeado'})
    return out


def _reads(ctx):
    """Consultas a tabela que alimentam as condições da regra: [{table, column, lineage_id, via}] sem repetição."""
    out, seen = [], set()
    for c in ctx:
        if c.get('table'):
            k = (c['table'], c.get('column'), c.get('lineage_id'))
            if k not in seen:
                seen.add(k)
                out.append({'table': c['table'], 'column': c.get('column'), 'lineage_id': c.get('lineage_id'), 'via': c['role']})
    return out


def _norm(v):
    v = str(v).strip()
    if len(v) > 1 and v[0] in '\'"' and v[-1] == v[0]:
        v = v[1:-1]
    return int(v) if v.lstrip('+-').isdigit() else v.upper()


def _names88(dm):
    """{(campo, valor): [nomes de condição 88]}: o significado que o próprio programa dá a um valor do campo."""
    out = defaultdict(list)
    for name, c in dm['conditions_88'].items():
        if c.get('parent') and c.get('value') is not None:
            out[(c['parent'].upper(), _norm(c['value']))].append(name)
    return out


def _value_name(e, names88):
    if not names88 or e['to']['type'] != 'campo' or len(e['from']) != 1 or e['from'][0]['type'] != 'literal':
        return None
    got = names88.get((e['to']['name'].upper(), _norm(e['from'][0]['name'])))
    return ', '.join(sorted(got)) if got else None


def _merge_paths(groups, ends, flow):
    """Caminhos que produzem os mesmos efeitos de negócio e diferem só no resultado (Sim/Não) de uma decisão: a decisão não muda o efeito
    e sai do caminho. Repete até não haver mais o que juntar."""
    def biz(ks):
        return tuple(sorted(k for k in set(ks) if _nature(flow['flows'][k])))

    def ended(p):
        return tuple(p) in ends or p in _MERGED_ENDS
    cur = {p: list(ks) for p, ks in groups.items()}
    changed = True
    while changed:
        changed = False
        by_key = defaultdict(list)
        for p in sorted(cur, key=lambda p: (len(p), [x[:4] for x in p])):
            by_key[(biz(cur[p]), len(p), ended(p))].append(p)
        for _k, ps in by_key.items():
            for i in range(len(ps)):
                for j in range(i + 1, len(ps)):
                    a, b = ps[i], ps[j]
                    diff = [n for n in range(len(a)) if a[n] != b[n]]
                    if len(diff) == 1 and a[diff[0]][:3] == b[diff[0]][:3] and {a[diff[0]][4], b[diff[0]][4]} == {'TRUE', 'FALSE'}:
                        m = tuple(x for n, x in enumerate(a) if n != diff[0])
                        was_end = ended(a)
                        ks = cur.pop(a) + cur.pop(b) + cur.get(m, [])
                        cur[m] = ks
                        if was_end:
                            _MERGED_ENDS.add(m)
                        changed = True
                        break
                if changed:
                    break
            if changed:
                break
    return cur
