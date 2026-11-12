"""Modelo de visão (view-model) de cada fase, montado a partir dos resultados estruturados.

Um único modelo alimenta os dois formatos: report_render.page() -> HTML humano (tabelas e diagramas, sem JSON)
e ia/report.json (o mesmo modelo serializado). Nada aqui lê o fonte COBOL: só os resultados das fases.
Modelo: {'title','subtitle','summary':[{label,value}],'sections':[{id,title,text,blocks}]}
Blocos: text | table(columns,rows) | bars(series[{label,parts[{name,value}]}]) | graph(kind,nodes,edges)."""
from collections import Counter, defaultdict

ROLE_ORDER = ['protagonista', 'coadjuvante', 'figurante', 'não referenciada']


def T(title, columns, rows, note=None, ids=None, marks=None, descartadas=None, riscadas=None):
    """Tabela. ids = âncora de cada linha (para os links de outras tabelas e de outros relatórios apontarem para ela)."""
    out = {'type': 'table', 'title': title, 'columns': columns, 'rows': [list(r) for r in rows], 'note': note}
    if ids is not None:
        out['row_ids'] = list(ids)
    if marks is not None:
        out['row_marks'] = [bool(m) for m in marks]   # linhas em destaque (a coluna que justifica o destaque aparece na própria linha)
    if riscadas is not None:
        out['row_riscada'] = [bool(m) for m in riscadas]   # linhas riscadas: itens que existiam e não serão mais implementados (a coluna de detalhe diz por quê)
    if descartadas is not None:
        out['row_descartada'] = [bool(m) for m in descartadas]   # linhas de itens descartados: o checkbox "Mostrar descartados" do diagrama da seção as esconde
    return out


def link(text, phase, anchor):
    """Link para uma linha ancorada (row_ids) de uma tabela do relatório da fase `phase`."""
    return {'text': text, 'phase': phase, 'anchor': anchor}


def link_arquivo(text, url, modal=None):
    """Link para um arquivo publicado junto do relatório da fase (caminho relativo à página humana, por exemplo evidencias/<id>.html).
    Com `modal` (título da janela), a página humana abre o arquivo numa janela sobre o relatório em vez de navegar para ele."""
    return {'text': text, 'url': url, **({'modal': modal} if modal else {})}


def sql_link(sq, phase='04-data-lineage'):
    """Link para a linha do comando SQL `sq` (id programa@linha:tabela) na tabela de comandos SQL da linhagem; o texto traz o início do SQL."""
    txt = ' '.join(str(sq.get('text') or '').split())
    return link(f'{sq["id"]}: ' + (txt if len(txt) <= 100 else txt[:99] + '…'), phase, 'sql-' + sq['id'])


def with_links(text, links):
    """Célula de tabela com texto e links (o HTML desenha os links; o JSON guarda o mesmo conteúdo). Sem links, só o texto."""
    return {'text': text, 'links': links} if links else text


def expandir(text, detalhe):
    """Célula com resumo e conteúdo completo: o HTML mostra o resumo com uma ação «…» que expande o detalhe; o JSON guarda os dois. Sem detalhe maior, só o texto."""
    return {'text': text, 'detalhe': detalhe} if detalhe and detalhe != text else text


def X(text, title=None):
    return {'type': 'text', 'title': title, 'text': text}


def SQL(sql, title=None, escrita=None):
    """Comando SQL formatado (indentado, uma cláusula por linha); é um bloco de texto marcado, então o conteúdo continua sendo o texto do comando."""
    from sql_format import formatar
    if escrita is None:
        escrita = str(sql).lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'MERGE'))
    return {'type': 'text', 'title': title, 'text': formatar(sql), 'sql': 'w' if escrita else 'r'}


def COD(text, title=None):
    """Texto pré-formatado (por exemplo um copybook): é um bloco de texto marcado, então o conteúdo continua sendo o texto."""
    return {'type': 'text', 'title': title, 'text': text, 'pre': True}


def OPENAPI(doc, yaml, title=None):
    """Contrato OpenAPI 3.1 mostrado como página de documentação (operações, parâmetros, respostas e schemas); `yaml` é o arquivo do contrato."""
    return {'type': 'openapi', 'title': title, 'doc': doc, 'yaml': yaml}


def B(title, series):
    return {'type': 'bars', 'title': title, 'series': series}


def G(title, nodes, edges, kind='flow', note=None):
    return {'type': 'graph', 'title': title, 'kind': kind, 'nodes': nodes, 'edges': edges, 'note': note}


def graph_table(g):
    """Todo diagrama ganha a tabela com o mesmo conteúdo (regra do relatório): arestas ou, no ER, colunas."""
    lab = {n['id']: n['label'] for n in g['nodes']}
    if g.get('kind') == 'er':
        has_s = any(c.get('state') for n in g['nodes'] for c in n.get('columns') or [])
        rows = [(n['label'], c['name'], c.get('type', ''), 'chave' if c.get('key') else '') + ((c.get('state', ''),) if has_s else ()) for n in g['nodes'] if n.get('columns') is not None for c in n['columns']]
        rel = [(lab.get(e['from'], e['from']), lab.get(e['to'], e['to']), e.get('label', '')) for e in g['edges']]
        out = [T('Tabela do diagrama: colunas — ' + (g.get('title') or ''), ['Tabela', 'Coluna', 'Tipo', 'Chave'] + (['Situação'] if has_s else []), rows)]
        if rel:
            out.append(T('Tabela do diagrama: relacionamentos — ' + (g.get('title') or ''), ['De', 'Para', 'Coluna em comum'], rel))
        return out
    if g.get('kind') == 'contextos':
        comp = []
        for n in g['nodes']:
            for m in (n.get('componentes') or []):
                comp.append((n['label'], n.get('sub', ''), m['label'], m.get('sub', '')))
                comp += [(n['label'], n.get('sub', ''), m['label'], 'regra de negócio: ' + rg) for rg in m.get('regras') or []]
        rel = [(lab.get(e['from'], e['from']), e.get('label', ''), lab.get(e['to'], e['to'])) for e in g['edges']]
        out = [T('Tabela do diagrama: componentes de cada contexto — ' + (g.get('title') or ''), ['Contexto', 'Tipo do contexto', 'Componente', 'Detalhe do componente'], comp)]
        out.append(T('Tabela do diagrama: relacionamentos — ' + (g.get('title') or ''), ['De', 'Ligação', 'Para'], rel))
        return out
    if g.get('kind') == 'sequencia':
        lab = {n['id']: n['label'] + (f' ({n["grupo"]})' if n.get('grupo') else '') for n in g['nodes']}   # caso de uso e a aplicação a que pertence
        rows, num = [], 0
        for e in g['edges']:
            if e.get('nota'):
                rows.append(('', lab.get(e['from'], e['from']), e.get('label', ''), lab.get(e['to'], e['to']), e.get('nota_tipo') or 'regra de negócio'))
            else:
                num += 1
                rows.append((num, lab.get(e['from'], e['from']), e.get('label', ''), lab.get(e['to'], e['to']), 'resposta' if e.get('retorno') else 'chamada'))
        return [T('Tabela do diagrama de sequência — ' + (g.get('title') or ''), ['Passo', 'De', 'Mensagem', 'Para', 'Tipo'], rows)]
    has_c = any(e.get('cond') or any(c.get('cond') for c in e.get('cmds', [])) for e in g['edges'])
    has_m = any(e.get('cmds') for e in g['edges'])
    rows = []
    for e in g['edges']:
        de, para = lab.get(e['from'], e['from']), lab.get(e['to'], e['to'])
        for c in e.get('cmds') or [None]:
            row = (de, (f'{c["op"]} {c["at"]}' if c else e.get('label', '')), para)
            if has_m:
                row += (c['text'] if c else '',)
            if has_c:
                row += (with_links((c or e).get('cond', ''), (c or e).get('cond_links') or []),)
            rows.append(row)
    iso = [n['label'] for n in g['nodes'] if not any(e['from'] == n['id'] or e['to'] == n['id'] for e in g['edges'])]
    rows += [(x, '', '') + (('',) if has_m else ()) + (('',) if has_c else ()) for x in iso]
    cols = ['De', 'Ligação', 'Para'] + (['Comando'] if has_m else []) + (['Condição que escolhe esta fonte (campo com mais de uma fonte)'] if has_c else [])
    return [T('Tabela do diagrama — ' + (g.get('title') or ''), cols, rows)]


def S(id_, title, blocks, text=None):
    out = []
    for b in blocks:
        out.append(b)
        if b['type'] == 'graph' and not b.get('sem_tabela'):
            out.extend(graph_table(b))
    return {'id': id_, 'title': title, 'text': text, 'blocks': out}


def card(label, value):
    return {'label': label, 'value': value}


def counter_series(counter, name='qtd', suffix=None):
    return [{'label': str(k), 'parts': [{'name': name, 'value': v}]} for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))]


def model(title, subtitle, summary, sections):
    return {'title': title, 'subtitle': subtitle, 'summary': summary, 'sections': sections}


# ---------------------------------------------------------------- 00 classificação
def m_classification(r, ctx):
    from program_classifier import CRITERIOS
    ps = r['programs']
    c0 = lambda p: p.get('phase0_classification') or p['classification']
    k0 = lambda p: p.get('phase0_confidence') or p['confidence']
    by = Counter(p['classification'] for p in ps)
    conf = Counter(p['confidence'] for p in ps)
    series = [{'label': p['program'], 'parts': [{'name': k, 'value': v} for k, v in p['scores'].items() if v]} for p in ps]
    rev = lambda p: (p.get('refinement') or {}).get('reason') or p.get('confidence_note') or 'sem mudança'
    rows = [(p['program'], p['classification'], c0(p), p['confidence'], k0(p), p.get('criterion', ''), ', '.join(f'{c} ({k})' for c, k in (p.get('caller_classes') or {}).items()) or 'nenhum (ponto de entrada)',
             rev(p), p['recommendation'], p['reason'], p['evidence']) for p in ps]
    return model('Fase 0 — Classificação dos programas', 'Papel de cada programa (interface, coordenador, funcional, corporativo, infraestrutura), a confiança na classificação e a recomendação de tratamento.',
                 [card('programas', len(ps))] + [card(k, v) for k, v in by.items()] + [card('confiança ' + k.lower(), v) for k, v in sorted(conf.items())],
                 [S('classes', 'Programas por classe', [B('Programas por classificação', counter_series(by, 'programas')), B('Programas por confiança na classificação', counter_series(conf, 'programas'))]),
                  S('criterios', 'Critérios da classificação', [T('Critério de cada classe', ['Classe', 'Critério', 'Sinal usado'], CRITERIOS,
                                                                  'Aplicados na ordem da tabela: infraestrutura pela pontuação técnica, depois corporativo pelo número de chamadores, depois coordenador, funcional e interface.')]),
                  S('scores', 'Pontuação por classe', [B('Pontos por classe em cada programa', series)], 'Cada barra soma os indícios encontrados nos tokens (chamadas, SQL, CICS, decisões); a relação de chamadas e a revisão pelo fluxo (coluna "Revisão pelo fluxo" da tabela Programas) podem mudar a classe final.'),
                  S('tabela', 'Detalhe', [T('Programas', ['Programa', 'Classe', 'Classe pela estrutura', 'Confiança', 'Confiança pela estrutura', 'Critério aplicado', 'Chamado por', 'Revisão pelo fluxo', 'Recomendação', 'Motivo', 'Evidências'], rows)])])


# ---------------------------------------------------------------- 02 análise estática
def effect_text(e):
    """Uma linha legível por efeito, a partir da estrutura do efeito (sem vocabulário do domínio)."""
    t, d, rd = e.get('type'), ' '.join(str(e.get('detail') or '').split()), e.get('resolved_detail') or {}
    if t == 'EXEC_SQL':
        return f'SQL {rd.get("operation", "")} {", ".join(rd.get("tables") or [])}'.strip()
    if t == 'EXEC_CICS':
        return f'CICS {rd.get("operation", "")} {rd.get("program_reference", "")}'.strip()
    if t == 'CALL':
        return f'CALL {rd.get("target", d)}'
    return f'{t} {d}'


def effect_group(effects):
    """Classe estrutural da consequência (cor do nó): decidida só pelo tipo dos efeitos."""
    ty = [(e.get('type'), (e.get('resolved_detail') or {}).get('operation')) for e in effects]
    if any(t == 'EXEC_CICS' and o == 'RETURN' for t, o in ty):
        return 'encerra o programa'
    if any(t in ('FILE_WRITE', 'FILE_REWRITE', 'FILE_DELETE') or (t == 'EXEC_SQL' and o in ('INSERT', 'UPDATE', 'DELETE', 'MERGE')) for t, o in ty):
        return 'grava dados'
    if any(t in ('CALL', 'EXEC_CICS') for t, o in ty):
        return 'chama programa/serviço'
    if any(t == 'EXEC_SQL' for t, o in ty):
        return 'lê dados'
    if any(t in ('MOVE', 'SET', 'COMPUTE', 'ADD', 'SUBTRACT', 'MULTIPLY', 'DIVIDE', 'STRING', 'UNSTRING', 'INSPECT') for t, o in ty):
        return 'altera campos'
    return 'só desvia o fluxo'


# ---------------------------------------------------------------- 06/07 goldens
def _scen_text(sc):
    parts = []
    for k in ('inputs', 'tables', 'files'):
        for n, v in (sc.get(k) or {}).items():
            parts.append(f'{k[:-1] if k != "files" else "arquivo"} {n}={v}')
    return '; '.join(parts)


ESTRATEGIAS = {
    'FRESH_WITNESS': 'Testemunha direta: a entrada mínima é sintetizada só da condição do ramo (restrições sobre campos de entrada) e, ao executar, o programa atinge o ramo-alvo.',
    'FRESH_PRODUCER': 'Testemunha com produtor de status: a entrada da condição chegou a outro desfecho antes do alvo porque um comando intermediário (SQL ou CICS) devolveu outro status; o cenário passa a forçar o status que produz o caminho.',
    'FRESH_FIRST_DIVERGENCE': 'Solver de caminho: nenhuma entrada direta serviu; o solver executa, acha a primeira decisão em que o caminho divergiu do alvo e ajusta a entrada ali, repetindo até atingir o ramo (a profundidade é o número de ajustes).',
}
GOLDEN_REGRA = 'Em todas as estratégias o caso só vira dourado depois de executar três vezes, atingir o ramo-alvo e produzir o mesmo hash de trace nas três execuções.'


def m_goldens(r, ctx, step='08'):
    g = r['goldens']
    strat = Counter(x['strategy'] for x in g)
    prog = Counter(x['program'] for x in g)
    rows = [(x['target_id'], x['program'], x['line'], x['branch'], x['strategy'], x['depth'], _scen_text(x['scenario']), x['trace_hash'][:12]) for x in g]
    name = 'Fase 7 — Análise dinâmica' if step == '07' else 'Fase 8 — Casos dourados'
    summ = [card('casos', len(g))] + ([card('execuções verificadas', r['summary']['executions_verified']), card('replays determinísticos', r['summary']['deterministic_replays'])] if 'summary' in r else [])
    return model(name, 'Cada ramo provado por uma entrada mínima, reexecutada de forma determinística.', summ,
                 [S('estrategia', 'Como cada caso foi obtido', [B('Casos por estratégia', counter_series(strat, 'casos')),
                                                                 T('O que é cada estratégia', ['Estratégia', 'O que é', 'Casos'], [(k, v, strat.get(k, 0)) for k, v in ESTRATEGIAS.items()] + [(k, 'Estratégia não descrita neste relatório.', n) for k, n in strat.items() if k not in ESTRATEGIAS])]),
                  S('programas', 'Casos por programa', [B('Casos por programa', counter_series(prog, 'casos'))]),
                  S('casos', 'Casos', [X(GOLDEN_REGRA), T('Casos dourados', ['Alvo', 'Programa', 'Linha', 'Ramo', 'Estratégia', 'Profundidade', 'Entrada mínima', 'Hash do trace'], rows)])])


def m_dynamic(r, ctx):
    return m_goldens(r, ctx, '07')


# ---------------------------------------------------------------- 08 certificação
STATUS_CERT = {
    'GOLDEN_VERIFIED': 'Ramo provado: existe um caso dourado, uma entrada mínima que executa o ramo e foi reexecutada três vezes com o mesmo hash de trace.',
    'UNKNOWN_DEPENDENCY': 'Ramo ainda sem prova: não se encontrou entrada que o atinja dentro do limite da busca (a condição depende de nível 88 sem resolução, de EVALUATE, de dado de outro programa ou de um estado que o solver não alcançou). Não é erro do código: é falta de prova.',
    'UNSUPPORTED': 'Ramo cuja execução depende de uma construção que o runtime ainda não suporta.',
}
ITENS_CONTAGEM = {
    'sources': 'Programas-fonte lidos na análise.',
    'outcomes': 'Ramos (desfechos) catalogados: cada decisão contribui com um ramo verdadeiro e um falso.',
    'direct': 'Ramos cuja condição se resolve direto sobre campos de entrada (restrição direta); a síntese tenta uma entrada que os atinja.',
    'needs_88': 'Ramos cuja condição usa nome de condição (nível 88); precisam resolver a linhagem do campo e do valor antes da síntese.',
    'evaluate': 'Ramos de EVALUATE (WHEN), tratados à parte da síntese direta.',
    'clean_room_goldens': 'Casos dourados produzidos do zero, só pelo código, sem reaproveitar entradas históricas.',
    'historical_inputs_used': 'Se alguma entrada histórica (de produção ou de testes antigos) foi usada para gerar os casos; falso = prova independente.',
    'decision_trees': 'Decisões (IF, EVALUATE, SEARCH) presentes nas árvores de decisão de todos os programas.',
    'tree_business_rules': 'Regras de negócio extraídas das árvores de decisão (caminho de decisão + efeitos).',
    'decision_branch_audit': 'Ramos de decisão auditados: cada ramo conferido contra as regras extraídas.',
    'dependency_programs': 'Programas com mapa de dependências (chamadas, tabelas, copybooks).',
    'certification': 'Resultado geral: PASS só quando nenhum ramo ficou sem prova (UNKNOWN_DEPENDENCY) nem sem suporte (UNSUPPORTED).',
}


def m_certification(r, ctx):
    out, cs = r['outcomes'], r['summary']
    st = Counter(o['status'] for o in out)
    per = defaultdict(Counter)
    for o in out:
        per[o['program']][o['status']] += 1
    series = [{'label': p, 'parts': [{'name': k, 'value': v} for k, v in c.items()]} for p, c in per.items()]
    pend = [(o['program'], o['line'], o['branch'], o['status'], o['reason']) for o in out if o['status'] != 'GOLDEN_VERIFIED']
    reasons = Counter(o['reason'] for o in out if o['status'] != 'GOLDEN_VERIFIED')
    return model('Fase 9 — Certificação', 'Situação de cada ramo do código: provado por caso dourado ou pendente, e por quê.',
                 [card('ramos', len(out))] + [card(k, v) for k, v in st.items()],
                 [S('status', 'Situação dos ramos', [B('Ramos por status', counter_series(st, 'ramos')),
                                                     T('O que cada status significa', ['Status', 'Significado', 'Ramos'], [(k, v, st.get(k, 0)) for k, v in STATUS_CERT.items()] + [(k, 'Status não descrito neste relatório.', n) for k, n in st.items() if k not in STATUS_CERT]),
                                                     B('Ramos por programa e status', series)]),
                  S('motivos', 'Motivos das pendências', [B('Pendências por motivo', counter_series(reasons, 'ramos'))]),
                  S('pendentes', 'Ramos pendentes', [T('Ramos sem caso dourado', ['Programa', 'Linha', 'Ramo', 'Status', 'Motivo'], pend)]),
                  S('catalogo', 'Catálogo', [T('Contagens', ['Item', 'Valor', 'O que significa'], [(k, v, ITENS_CONTAGEM.get(k, '')) for k, v in cs.items() if not isinstance(v, (dict, list))]),
                                             T('Status terminal', ['Status', 'Ramos'], list(cs['terminal_status'].items()))])])


# ---------------------------------------------------------------- runtime x estático
def _txt(v):
    if isinstance(v, list):
        return ' | '.join(str(x) for x in v)
    return v


def _ep_usage(ctx):
    """Por entry point: programas chamados como mock, linhas de SQL executadas por programa e tabelas que os cenários preenchem."""
    out = defaultdict(lambda: {'mock': set(), 'real': set(), 'sql': defaultdict(set), 'tables': set()})
    for x in ctx.get('scenarios') or []:
        d, r = x.get('def') or {}, x.get('res') or {}
        u = out[r.get('entry_point') or d.get('entry_point')]
        for c in r.get('calls') or []:
            if c.get('target'):
                (u['real'] if c.get('mode') == 'REAL' else u['mock']).add(c['target'])
        for q in r.get('sql') or []:
            u['sql'][q['program']].add(q['line'])
        u['tables'] |= set(d.get('tables') or {}) | set(r.get('final_tables') or {})
    return out


def _flow_graph(ep, use=None, deps=None, qual=lambda t: t, cls=None):
    """Programas e tabelas do fluxo de um entry point. Executado = cor normal; mockado (retorno vindo do cenário, não executado de verdade) = fundo amarelo claro;
    não alcançado por nenhum cenário = cinza tracejado."""
    nodes, edges, stack = {}, [], {}
    use = use or {'mock': set(), 'real': set(), 'sql': {}, 'tables': set()}
    short = lambda t: t.split('.')[-1]
    for f in ep['flow']:
        p = f['program']
        if f.get('executed') or p in use['real']:
            state = 'executado'
        elif f.get('infrastructure') or p in use['mock']:
            state = 'mockado'
        else:
            state = 'não alcançado'
        grp = (cls or {}).get(p) or ('INFRAESTRUTURA' if f.get('infrastructure') else 'programa')   # cor = classe do programa; o estado vai no estilo (cinza tracejado, fundo amarelo)
        sl = f.get('slice')
        pct = sl['pct'] if sl else f.get('branch_coverage_pct')
        nodes.setdefault(p, {'id': p, 'label': f'{p} {pct}%' if pct is not None else p, 'group': grp,
                             'inactive': state == 'não alcançado', 'mocked': state == 'mockado',
                             'detail': f'{p} ({state}): {f.get("branches_exercised")}/{f.get("branches")} ramos' + (f'; no fluxo {sl["exercised"]}/{sl["branches"]}' if sl else '')})
        stack[f['depth']] = p
        if f['depth'] > 0 and stack.get(f['depth'] - 1):
            k = (stack[f['depth'] - 1], p)
            if k not in {(e['from'], e['to']) for e in edges}:
                edges.append({'from': k[0], 'to': p, 'label': f'{f.get("via")} @{f.get("line")}'})
    for p in list(nodes):
        acc = defaultdict(list)
        for a in ((deps or {}).get(p) or {}).get('table_access', []):
            acc[a['table']].append(a)
        for t, xs in sorted(acc.items()):
            ran = any(a['line'] in use['sql'].get(p, ()) for a in xs)
            seen = t in use['tables'] or any(short(t) == short(n) for n in use['tables'])
            state = 'executado' if ran else ('mockado' if seen else 'não alcançado')
            nodes.setdefault('T:' + t, {'id': 'T:' + t, 'label': qual(t), 'group': 'tabela DB2', 'inactive': state == 'não alcançado', 'mocked': state == 'mockado',
                                        'detail': f'{t} ({state}' + (': nenhum SQL do código a alcançou; os dados vêm das linhas do cenário)' if state == 'mockado' else ')')})
            if state == 'executado':
                nodes['T:' + t].update({'inactive': False, 'mocked': False})
            edges.append({'from': p, 'to': 'T:' + t, 'label': '/'.join(sorted({a['operation'] for a in xs})), 'inactive': state == 'não alcançado'})
    return list(nodes.values()), edges


def m_runtime(r, ctx):
    sm_, eps = r['summary'], ctx.get('eps') or []
    cov = r['coverage_by_program']
    series = [{'label': p, 'parts': [{'name': 'exercitados', 'value': c['branches_exercised']}, {'name': 'não exercitados', 'value': c['branches'] - c['branches_exercised']}], 'suffix': f'{c["branch_coverage_pct"]}%'} for p, c in cov.items() if not c['infrastructure']]
    sections = [S('cobertura', 'Cobertura por programa', [B('Ramos exercitados por programa', series),
                T('Cobertura', ['Programa', 'Executado', 'Mockado', 'Decisões', 'Ramos', 'Exercitados', '%', 'Regras', 'Regras exercitadas'],
                  [(p, c['executed_in_scenarios'], c['mocked_in_scenarios'], c['decisions'], c['branches'], c['branches_exercised'], c['branch_coverage_pct'], c['business_rules'], c['business_rules_exercised']) for p, c in cov.items() if not c['infrastructure']])])]
    usage = _ep_usage(ctx)
    deps = ctx['phase'].get('01-discovery-dependencies', {}).get('programs', {})
    from report_maps import table_qualifier
    qual = table_qualifier(ctx)
    if eps:
        blocks = [T('Entry points', ['Entry point', 'Cenários', 'Programas no fluxo', 'Ramos do fluxo', 'Exercitados', '%'],
                    [(e['entry_point'], e['scenarios'], len(e['flow']), sum(f['slice']['branches'] for f in e['flow'] if f.get('slice') and f.get('executed')), sum(f['slice']['exercised'] for f in e['flow'] if f.get('slice') and f.get('executed')),
                      round(100.0 * sum(f['slice']['exercised'] for f in e['flow'] if f.get('slice') and f.get('executed')) / max(1, sum(f['slice']['branches'] for f in e['flow'] if f.get('slice') and f.get('executed'))), 1)) for e in eps])]
        for e in eps:
            n, ed = _flow_graph(e, usage.get(e['entry_point']), deps, qual, {x['program']: x['classification'] for x in (ctx['phase'].get('00-program-classification') or {}).get('programs', [])})
            blocks.append({**G(f'Fluxo de execução — {e["entry_point"]}', n, ed, note='Percentual = ramos alcançáveis da fatia que os cenários exercitaram. Tabela: executado = algum SQL do código a alcançou.'),
                           'inactive_label': 'cinza tracejado = programa ou tabela que nenhum cenário alcançou',
                           'mocked_label': 'fundo amarelo = mockado (programa com retorno definido pelo cenário; tabela só com linhas do cenário, sem SQL do código)'})
        sections.append(S('fluxos', 'Fluxo dos entry points', blocks))
    sc = r['slice_coverage']
    sections.append(S('fatia', 'Cobertura da fatia alcançável', [T('Ramos alcançáveis por entry point e programa',
                      ['Entry point', 'Programa', 'Ramos', 'Exercitados', '%', 'Podados', 'Parágrafos', 'Chamado por', 'Constantes do chamador', 'Fora da fatia (deve ser vazio)'],
                      [(e, p, c['branches'], c['exercised'], c['pct'], c['pruned'], f'{c["paragraphs_reached"]}/{c["paragraphs_total"]}', c['called_from'], c['constants'], c['outside_slice_taken']) for e, ps in sc.items() for p, c in ps.items()])],
                      'Fatia = ramos que o chamador ainda permite alcançar (constantes que ele fixa antes da chamada).'))
    ba = r.get('branch_analysis')
    if ba:
        items = [(e, p, x) for e, ps in ba['por_entry_point'].items() for p, l in ps.items() for x in l]
        rc = Counter(x['reason'] for _, _, x in items)
        rows = [(e, p, x['source_line'], x['type'], x['branch'], x['expression'], x['reason'], x['explanation'], _txt(x['evidence']), x['suggestion'], _txt(x['snippet'])) for e, p, x in items]
        sections.append(S('ramos', 'Por que cada ramo ficou sem cobertura', [
            B('Ramos sem cobertura por motivo', counter_series(rc, 'ramos')),
            T('O que cada motivo significa', ['Motivo', 'Descrição'], list(ba['descricao'].items())),
            T('Ramos sem cobertura', ['Entry point', 'Programa', 'Linha', 'Tipo', 'Ramo', 'Condição', 'Motivo', 'Explicação', 'Evidência', 'Sugestão de cenário', 'Trecho'], rows)]))
    sections.append(S('cenarios', 'Cenários', [T('Cenários executados', ['Cenário', 'Entry point', 'Status', 'Status do runtime', 'Determinístico', 'Consistência estática', 'Erros'],
                      [(s['name'], s.get('entry_point'), s['status'], s.get('runtime_status'), s.get('deterministic'), s.get('static_consistency'), s.get('errors') or s.get('error')) for s in r['scenarios']])]))
    return model('Runtime x Análise Estática', 'Execução real dos cenários contra o que a análise estática prevê: cobertura, fluxo por entry point e motivo de cada ramo não coberto.',
                 [card('cenários', sm_['scenarios']), card('aprovados', sm_['pass']), card('ramos exercitados', f'{sm_["branches_exercised"]}/{sm_["branches_total_non_infra"]}'), card('regras exercitadas', f'{sm_["business_rules_exercised"]}/{sm_["business_rules_total"]}')], sections)




# ---------------------------------------------------------------- 03 uso de dados (tabelas, ER, campos)


# ---------------------------------------------------------------- análise dinâmica (06 + 07 + 08 + runtime)
def _rd(v):
    from report_render import readable
    return readable(v)


def auto_mocks(scen):
    c = Counter()
    for x in scen:
        for p, info in ((x.get('res') or {}).get('mock_plan') or {}).items():
            if not info.get('returns_defined'):
                c[(p, info.get('reason'))] += 1
    return [(p, why, n) for (p, why), n in sorted(c.items())]


def scenario_tables(scen):
    """Tabelas dos cenários: definição (entradas, tabelas, mocks, status simulados, esperado) e o que a execução produziu."""
    rows, mocks, tabs, checks, calls = [], [], [], [], []
    for x in scen:
        d, r = x.get('def') or {}, x.get('res') or {}
        name = r.get('name') or d.get('name')
        ok = sum(1 for c in r.get('checks', []) if c['result'] == 'MATCH')
        rows.append((name, r.get('entry_point') or d.get('entry_point'), r.get('status'), d.get('inputs') or {}, d.get('tables') or {},
                     {**(d.get('db2_status') or {}), **(d.get('cics_status') or {})}, d.get('expected') or {}, f'{ok}/{len(r.get("checks", []))}'))
        for prog, info in sorted((r.get('mock_plan') or {}).items()):
            if info.get('returns_defined'):
                mocks.append((name, prog, info.get('reason'), (d.get('mocks') or {}).get(prog, {}).get('returns') or {}))
        ft = r.get('final_tables') or {}
        for t in sorted(set(d.get('tables') or {}) | set(ft)):
            ini, fin = (d.get('tables') or {}).get(t), ft.get(t)
            tabs.append((name, t, len(ini) if isinstance(ini, list) else '', len(fin) if isinstance(fin, list) else ''))
        for c in r.get('checks', []):
            checks.append((name, c['check'], c.get('name', ''), c.get('expected'), c.get('actual'), c['result']))
        for c in r.get('calls', []):
            calls.append((name, c['caller'], c['line'], c['mechanism'], c['target'], c['mode']))
    return rows, mocks, tabs, checks, calls


def m_dynamic_all(r06, ctx):
    rt, scen = ctx.get('rt'), ctx.get('scenarios') or []
    ph = ctx['phase']
    base = m_runtime(rt, ctx) if rt else model('', '', [], [])
    secs = {s['id']: s for s in base['sections']}
    out = []
    for k in ('cobertura', 'fluxos', 'fatia'):
        if k in secs:
            out.append(secs[k])
    if rt:
        rows, mocks, tabs, checks, calls = scenario_tables(scen)
        out.append(S('cenarios', 'Cenários: entradas, mocks e resultados', [
            T('Cenários', ['Cenário', 'Entry point', 'Status', 'Entradas', 'Tabelas de entrada', 'Status DB2/CICS simulados', 'Saídas esperadas', 'Verificações que bateram'], rows),
            T('Programas mockados com retorno definido no cenário', ['Cenário', 'Programa', 'Motivo do mock', 'Retornos definidos'], mocks),
            T('Programas mockados automaticamente (sem retorno definido)', ['Programa', 'Motivo', 'Cenários em que é mockado'], auto_mocks(scen)),
            T('Tabelas: linhas de entrada e de saída', ['Cenário', 'Tabela', 'Linhas de entrada', 'Linhas ao final'], tabs),
            T('Verificações: esperado x obtido', ['Cenário', 'Verificação', 'Nome', 'Esperado', 'Obtido', 'Resultado'], checks),
            T('Chamadas feitas em cada cenário (real ou mock)', ['Cenário', 'Chamador', 'Linha', 'Mecanismo', 'Programa', 'Modo'], calls)]))
    if ph.get('08-golden-cases'):
        g = m_goldens(ph['08-golden-cases'], ctx, '08')
        out.append(S('goldens', 'Casos dourados', g['sections'][0]['blocks'] + g['sections'][2]['blocks'], 'Cada ramo provado por uma entrada mínima, reexecutada de forma determinística.'))
    if ph.get('09-certification'):
        c = m_certification(ph['09-certification'], ctx)
        out.append(S('certificacao', 'Certificação dos ramos', [b for s in c['sections'][:3] for b in s['blocks']]))
    out.extend(_inferred_and_missing(rt, scen, ctx))
    ba = (rt or {}).get('branch_analysis')
    sm_ = (rt or {}).get('summary') or {}
    goldens = len((ph.get('08-golden-cases') or {}).get('goldens', []))
    outc = Counter(o['status'] for o in (ph.get('09-certification') or {}).get('outcomes', []))
    return model('Fase 7 — Análise dinâmica', 'Execução real dos cenários contra a análise estática: cenários com entradas, saídas e mocks; cobertura por entry point; casos dourados; certificação; o que foi inferido e o que falta.',
                 ([card('cenários', sm_.get('scenarios')), card('aprovados', sm_.get('pass')), card('ramos exercitados', f'{sm_.get("branches_exercised")}/{sm_.get("branches_total_non_infra")}'),
                   card('regras exercitadas', f'{sm_.get("business_rules_exercised")}/{sm_.get("business_rules_total")}')] if sm_ else []) + [card('casos dourados', goldens)] + [card(k, v) for k, v in outc.items()], out)


def _inferred_and_missing(rt, scen, ctx):
    ph, sm_ = ctx['phase'], ctx['static']
    inferred, missing = [], []
    warn = defaultdict(lambda: {'progs': set(), 'in': set(), 'out': set(), 'attr': set()})
    reasons = Counter()
    undefined = Counter()
    for x in scen:
        r = x.get('res') or {}
        for w in r.get('warnings', []):
            if w['type'] == 'COPYBOOK_AUSENTE_CAMPOS_DEDUZIDOS':
                a = warn[w['copybook']]
                a['progs'] |= set(w['programs'])
                a['in'] |= set(w['inputs'])
                a['out'] |= set(w['outputs'])
                a['attr'].add(w['attribution'])
        for p, info in (r.get('mock_plan') or {}).items():
            reasons[(p, info['reason'])] += 1
            if not info.get('returns_defined'):
                undefined[p] += 1
    for cb, a in sorted(warn.items(), key=lambda kv: str(kv[0])):
        inferred.append(('campos deduzidos pelo uso (copybook ausente)', str(cb), len(a['in']) + len(a['out']),
                         f'{len(a["in"])} entradas e {len(a["out"])} saídas deduzidas nos programas {", ".join(sorted(a["progs"]))}; atribuição: {", ".join(sorted(a["attr"]))}'))
    mock_by = defaultdict(list)
    for (p, why), n in sorted(reasons.items()):
        mock_by[why].append(f'{p}×{n}')
    for why, l in mock_by.items():
        inferred.append(('programas mockados automaticamente', why, len(l), ', '.join(l)))
    for why, txt in (('EXTERNO', 'programa chamado sem fonte na base analisada'), ('INFRAESTRUTURA', 'programa classificado como infraestrutura'), ('DEFINIDO_NO_CENARIO', 'mock definido no cenário')):
        pass
    cov = (rt or {}).get('coverage_by_program', {})
    for p, c in sorted(cov.items()):
        if not c['infrastructure'] and c['executed_in_scenarios']:
            inferred.append(('cobertura medida', p, c['branches_exercised'], f'{c["branches_exercised"]} de {c["branches"]} ramos ({c["branch_coverage_pct"]}%); {c["business_rules_exercised"]} de {c["business_rules"]} regras'))
    # o que falta
    mcb = sm_.get('missing_copybooks') or []
    if mcb:
        missing.append(('copybooks ausentes', ', '.join(map(str, mcb)) if len(mcb) < 12 else f'{len(mcb)} copybooks', len(mcb), 'Fornecer os membros para declarar os campos; hoje os tipos são deduzidos pelo uso.'))
    dcl = (ph.get('03-data-schema') or {}).get('program_bindings', {})
    miss_dcl = sorted({m for b in dcl.values() for m in b['summary'].get('includes_missing', [])})
    if miss_dcl:
        missing.append(('DCLGEN ausentes', ', '.join(miss_dcl) if len(miss_dcl) < 12 else f'{len(miss_dcl)} membros', len(miss_dcl), 'Fornecer os DCLGEN para conhecer colunas e tipos das tabelas.'))
    ext = sm_.get('externals') or []
    if ext:
        missing.append(('programas chamados sem fonte', ', '.join(map(str, ext)) if len(ext) < 12 else f'{len(ext)} programas', len(ext), 'Fornecer os fontes ou definir o retorno de cada um nos cenários (mocks).'))
    unres = [c for c in sm_.get('call_graph', []) if not c.get('target')]
    if unres:
        missing.append(('chamadas sem destino resolvido', f'{len(unres)} chamadas', len(unres), 'O nome do programa chamado vem de variável sem VALUE; informe o valor no cenário.'))
    for p, n in sorted(undefined.items()):
        missing.append(('mock sem retorno definido', p, n, 'Definir os retornos do programa nos cenários; sem isso ele devolve valores iniciais.'))
    never = [p for p, c in sorted(cov.items()) if not c['infrastructure'] and not c['executed_in_scenarios']]
    if never:
        missing.append(('programas nunca executados de verdade', ', '.join(never), len(never), 'Nenhum cenário executa o programa; só mock.'))
    ba = (rt or {}).get('branch_analysis')
    if ba:
        rc = Counter(x['reason'] for ps in ba['por_programa'].values() for x in ps)
        for k, n in rc.most_common():
            missing.append(('ramos sem cobertura', k, n, ba['descricao'].get(k, '')))
    pend = Counter(o['reason'] for o in (ph.get('09-certification') or {}).get('outcomes', []) if o['status'] != 'GOLDEN_VERIFIED')
    for k, n in pend.most_common():
        missing.append(('ramos pendentes na certificação', k, n, 'Sem caso dourado que prove o ramo.'))
    secs = [S('inferido', 'O que a análise inferiu', [T('Inferências', ['Categoria', 'Item', 'Quantidade', 'Detalhe'], inferred)], 'Tudo o que foi deduzido pelo script em vez de vir declarado no código ou nos cenários.'),
            S('falta', 'O que falta para uma análise completa', [T('Pendências', ['Categoria', 'Item', 'Quantidade', 'O que fazer'], missing)])]
    if ba:
        items = [(e, p, x) for e, ps in ba['por_entry_point'].items() for p, l in ps.items() for x in l]
        rows = [(e, p, x['source_line'], x['type'], x['branch'], x['expression'], x['reason'], x['explanation'], _txt(x['evidence']), x['suggestion'], _txt(x['snippet'])) for e, p, x in items]
        secs.append(S('ramos', 'Ramos sem cobertura e o motivo de cada um', [
            B('Ramos sem cobertura por motivo', counter_series(Counter(x['reason'] for _, _, x in items), 'ramos')),
            T('O que cada motivo significa', ['Motivo', 'Descrição'], list(ba['descricao'].items())),
            T('Ramos sem cobertura', ['Entry point', 'Programa', 'Linha', 'Tipo', 'Ramo', 'Condição', 'Motivo', 'Explicação', 'Evidência', 'Sugestão de cenário', 'Trecho'], rows)]))
    return secs


def _steps():
    import report_maps as mp
    import report_lineage as rl
    import report_resumo as rs
    return {'00-program-classification': m_classification, '01-discovery-dependencies': mp.m_dependencies, '05-decision-map': mp.m_static,
            '02-program-schema': mp.m_program_schema,            '03-data-schema': mp.m_schema, '04-data-lineage': rl.m_lineage, '04b-lineage-summary': rs.m_resumo, '06-deterministic-rules': rl.m_rules, '07-dynamic-analysis': m_dynamic_all,
            '08-golden-cases': m_goldens, '09-certification': m_certification}


class _Steps(dict):
    def __missing__(self, k):
        self.update(_steps())
        return self[k]

    def items(self):
        self.update(_steps())
        return super().items()


STEPS = _Steps()
