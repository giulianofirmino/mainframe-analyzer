"""Modelos de visão das fases 1 a 6: dependências, mapa de decisão, esquema de dados, linhagem (DFD) e regras determinísticas.

Tudo sai dos resultados estruturados das fases (result.json) e da execução dos cenários (runtime). O que a execução
dinâmica mostra que não foi chamado/executado fica acinzentado (nó `inactive`) com legenda e motivo em tabela."""
import re
from collections import Counter, defaultdict

import report_model as rm
from report_model import T, X, B, G, S, card, counter_series, model, effect_group, with_links, sql_link
from table_roles import CRITERIOS_PAPEL

INACTIVE_TXT = 'cinza tracejado = não chamado/executado em nenhum cenário; o motivo está na tabela ao lado do diagrama'


# ----------------------------------------------------------------------------- o que a execução dinâmica mostra
def dynamic(ctx):
    """Resumo do que os cenários chamaram/executaram: programas, tabelas (via linha do SQL executado). None sem execução."""
    rt, scen = ctx.get('rt'), ctx.get('scenarios') or []
    if not rt:
        return None
    real, mock, sqls = set(), set(), defaultdict(set)
    for x in scen:
        r = x.get('res') or {}
        real |= set(r.get('executed_programs') or [])
        for c in r.get('calls') or []:
            if c.get('target'):
                (real if c.get('mode') == 'REAL' else mock).add(c['target'])
        for q in r.get('sql') or []:
            sqls[q['program']].add(q['line'])
    return {'real': real, 'mock': mock - real, 'sql_lines': sqls, 'coverage': rt.get('coverage_by_program', {})}


def mocked_lines(scenarios):
    """{programa: {linha: texto}} dos comandos cujo resultado é sempre definido pelo cenário: chamada de programa mockada (nunca REAL) e
    comando SQL/CICS com status forçado (db2_status, cics_status) em todos os cenários que o executam."""
    call_mock, call_real = defaultdict(set), defaultdict(set)
    forced, free = defaultdict(set), defaultdict(set)
    for x in scenarios or []:
        d, r = x.get('def') or {}, x.get('res') or {}
        for c in r.get('calls') or []:
            (call_real if c.get('mode') == 'REAL' else call_mock)[c['caller']].add(c['line'])
        f_here = defaultdict(set)
        for key in list((d.get('db2_status') or {})) + list((d.get('cics_status') or {})):
            prog, _, ln = str(key).rpartition(':')
            if prog and ln.isdigit():
                f_here[prog].add(int(ln))
        for prog, ls in f_here.items():
            forced[prog] |= ls
        for q in r.get('sql') or []:
            if q['line'] not in f_here.get(q['program'], set()):
                free[q['program']].add(q['line'])
    out = defaultdict(dict)
    for p, ls in call_mock.items():
        for ln in ls - call_real[p]:
            out[p][ln] = 'chamada de programa mockada (retorno definido pelo cenário)'
    for p, ls in forced.items():
        for ln in ls - free[p]:
            out[p].setdefault(ln, 'consulta de dados ou chamada CICS com status forçado pelo cenário (SQLCODE/EIBRESP definido)')
    return out


def table_qualifier(ctx):
    """Função que devolve o nome da tabela com o esquema (ESQUEMA.TABELA) do jeito que o mapeamento da análise o conhece: nome qualificado no SQL
    do código (fase 1) ou no DCLGEN (fase 3). Nada fixo: sem esquema no mapeamento, o nome fica como está."""
    names = set()
    for d in ((ctx['phase'].get('01-discovery-dependencies') or {}).get('programs') or {}).values():
        names |= {a['table'] for a in d.get('table_access', [])}
    names |= set(((ctx['phase'].get('03-data-schema') or {}).get('tables')) or {})
    by_short = {}
    for n in sorted(names, key=lambda n: ('.' not in n, n)):
        by_short.setdefault(n.split('.')[-1], n)
    return lambda t: t if '.' in t else by_short.get(t, t)


def executed_tables(dyn, dependencies):
    """{tabela: {programas que a acessaram em execução}} pelo par (programa, linha) do SQL executado."""
    out = defaultdict(set)
    for p, lines in dyn['sql_lines'].items():
        for a in (dependencies.get(p) or {}).get('table_access', []):
            if a['line'] in lines:
                out[a['table']].add(p)
    return out


def scenario_tables_seen(ctx):
    """{tabela: {'cenarios': n, 'colunas': {nome}}} das tabelas que os cenários preenchem (linhas de entrada) ou terminam com linhas."""
    out = defaultdict(lambda: {'scenarios': set(), 'columns': set(), 'types': defaultdict(lambda: {'tipos': set(), 'max': 0})})
    for x in ctx.get('scenarios') or []:
        d, r = x.get('def') or {}, x.get('res') or {}
        name = r.get('name') or d.get('name')
        for src in (d.get('tables') or {}, r.get('final_tables') or {}):
            for t, rows in src.items():
                out[t]['scenarios'].add(name)
                for row in rows if isinstance(rows, list) else []:
                    if isinstance(row, dict):
                        out[t]['columns'] |= {str(k).upper() for k in row}
                        for k, v in row.items():
                            ty = out[t]['types'][str(k).upper()]
                            if v is None:
                                continue
                            if isinstance(v, bool):
                                ty['tipos'].add('lógico')
                            elif isinstance(v, int):
                                ty['tipos'].add('inteiro'); ty['max'] = max(ty['max'], len(str(abs(v))))
                            elif isinstance(v, float):
                                ty['tipos'].add('decimal')
                            else:
                                ty['tipos'].add('texto'); ty['max'] = max(ty['max'], len(str(v)))
    return out


def _digitos(g):
    m = re.fullmatch(r'9\((\d+)\)|(9+)', g or '')
    return int(m.group(1) or len(m.group(2))) if m else 0


def tipo_db2(t):
    """Tipo de coluna deduzido (PIC, tipo observado ou texto livre) no padrão DB2: DECIMAL(p,s), SMALLINT/INTEGER/BIGINT (binário), CHAR(n); sem tamanho conhecido fica DECIMAL ou CHAR sem
    argumentos; sem nenhuma pista, 'indeterminado'. Já em DB2, volta igual."""
    t = str(t or '').replace('≈', '').strip()
    if re.fullmatch(r'(DECIMAL|CHAR|VARCHAR|SMALLINT|INTEGER|BIGINT)(\(\d+(,\d+)?\))?', t):
        return t
    m = re.match(r'inteiro \(até (\d+) dígitos', t)
    if m:
        return f'DECIMAL({int(m.group(1))},0)'
    m = re.match(r'texto \(até (\d+) caracteres', t)
    if m:
        return f'CHAR({int(m.group(1))})'
    if t.startswith('numérico'):
        return 'DECIMAL'
    if t.startswith('alfanumérico'):
        return 'CHAR'
    pic = re.sub(r'^PIC\s+', '', t).upper()
    m = re.match(r'[XA](?:\((\d+)\))?(?:\s|$)', pic)
    if m:
        return f'CHAR({int(m.group(1) or 1)})'
    m = re.match(r'[S+\-]?((?:9\(\d+\)|9+)?)(?:V((?:9\(\d+\)|9+))?)?(?:\.((?:9\(\d+\)|9+)))?(?:\s+(.*))?$', pic)
    if m and (m.group(1) or m.group(2)):
        n, d = _digitos(m.group(1)), _digitos(m.group(2) or m.group(3))
        uso = m.group(4) or ''
        if re.search(r'COMP(-4|-5)?\b|BINARY', uso) and 'COMP-3' not in uso and d == 0:
            return 'SMALLINT' if n <= 4 else 'INTEGER' if n <= 9 else 'BIGINT'
        return f'DECIMAL({n + d},{d})'
    return 'indeterminado'


def inf(t):
    """Tipo inferido para exibir: padrão DB2 e a marca de que não vem de DCLGEN."""
    return tipo_db2(t) + ' (inferido)'


def observed_type(seen, table, col):
    """Tipo observado nos valores que as análises viram para a coluna (linhas dos cenários), no padrão DB2: inteiro até N dígitos = DECIMAL(N,0), texto até N caracteres = CHAR(N); só nulos = indeterminado."""
    ty = ((seen.get(table) or {}).get('types') or {}).get(col)
    if not ty or not ty['tipos']:
        return 'indeterminado (inferido)'
    ts = sorted(ty['tipos'])
    if ts == ['inteiro']:
        return inf(f'inteiro (até {ty["max"]} dígitos observados)')
    if ts == ['texto']:
        return inf(f'texto (até {ty["max"]} caracteres observados)')
    if ts == ['decimal']:
        return 'DECIMAL (inferido)'
    return 'indeterminado (inferido)'


def _short(t):
    return t.split('.')[-1]


def _match(t, names):
    """Nome da tabela em `names` que corresponde a t (igual ou só o qualificador difere)."""
    if t in names:
        return t
    return next((n for n in names if _short(n) == _short(t)), None)


# ----------------------------------------------------------------------------- 01 dependências
def _dependencias_tudo(r, ctx):
    sm = ctx['static']
    ps = r['programs']
    dyn = dynamic(ctx)
    prog_ids = set(ps) | set(sm.get('programs', {}))
    cls = {p['program']: p['classification'] for p in ctx['phase'].get('00-program-classification', {}).get('programs', [])}
    cg = sm.get('call_graph', [])
    seen, edges = set(), []
    for c in cg:
        if c.get('target'):
            k = (c['caller'], c['target'], c['mechanism'])
            if k not in seen:
                seen.add(k)
                edges.append({'from': c['caller'], 'to': c['target'], 'label': f'{c["mechanism"]} @{c["line"]}'})
    ends = {e['from'] for e in edges} | {e['to'] for e in edges}

    def pstate(p):
        if dyn is None:
            return None
        if p in dyn['real']:
            return 'executado'
        if p in dyn['mock']:
            return 'chamado só como mock (não executado de verdade)'
        return 'não chamado'
    nodes = []
    for p in sorted(ends | prog_ids):
        st = pstate(p)
        nodes.append({'id': p, 'label': p, 'group': cls.get(p, 'externo (fora do código analisado)'), 'inactive': st == 'não chamado', 'mocked': bool(st) and st.startswith('chamado só'),
                      'detail': f'{p} ({cls.get(p, "externo")})' + (f' — {st}' if st else '')})
    tn, te, acc_rows = {}, [], []
    used_tabs = executed_tables(dyn, ps) if dyn else {}
    for p, d in ps.items():
        agg = defaultdict(lambda: {'ops': set(), 'cur': set()})
        for a in d['table_access']:
            agg[a['table']]['ops'].add(a['operation'])
            if a['via_cursor']:
                agg[a['table']]['cur'].add(a['via_cursor'])
        for t, x in sorted(agg.items()):
            tn[t] = {'id': 'T:' + t, 'label': t, 'group': 'tabela DB2', 'inactive': bool(dyn) and t not in used_tabs, 'detail': t}
            te.append({'from': p, 'to': 'T:' + t, 'label': '/'.join(sorted(x['ops'])) + (' via ' + ', '.join(sorted(x['cur'])) if x['cur'] else '')})
            acc_rows.append((p, t, ', '.join(sorted(x['ops'])), ', '.join(sorted(x['cur'])) or 'acesso direto'))
    cur_rows = [(p, c['cursor'], c['declared_line'], ', '.join(c['tables']), ', '.join(f'{o["operation"]}@{o["line"]}' for o in c['operations'])) for p, d in ps.items() for c in d['cursors']]
    cbn, cbe, cb_by = {}, [], defaultdict(set)
    for p, d in ps.items():
        for cb in d['copybooks']:
            cb_by[cb].add(p)
    for cb, incl in sorted(cb_by.items()):
        cbn[cb] = {'id': 'C:' + cb, 'label': cb, 'group': 'copybook', 'inactive': bool(dyn) and not (incl & dyn['real']), 'detail': cb}
    for cb, incl in sorted(cb_by.items()):
        for p in sorted(incl):
            cbe.append({'from': p, 'to': 'C:' + cb, 'label': 'COPY'})
    rows = [(p, len(d['program_calls']), len(d['sql_commands']), len({a['table'] for a in d['table_access']}), len(d['cursors']), len(d['cics']), len(d['files']), len(d['copybooks'])) for p, d in ps.items()]
    calls = [(c['caller'], c['line'], c['mechanism'], c.get('target') or c.get('raw') or '(não resolvido)', c.get('statement') or '', c.get('commarea_copybook') or '') for c in cg]
    unres = sum(1 for c in cg if not c.get('target'))
    sections = []
    prog_nodes = [n for n in nodes if n['id'] in prog_ids]
    lab = {'inactive_label': 'cinza tracejado = objeto não chamado em nenhum cenário executado', 'mocked_label': 'fundo amarelo = programa chamado só como mock'} if dyn else {}
    # O diagrama de chamadas não repete a tabela: "Todas as chamadas" logo abaixo é a tabela dele (e traz também o comando e o copybook da área de comunicação).
    sections.append(S('arvore', 'Árvore de chamadas', [{**G('Chamadas entre programas (LINK/CALL)', nodes, edges, note='Cores = classe do programa (azul coordenador, verde funcional, laranja corporativo, vermelho infraestrutura).'), **lab, 'sem_tabela': True},
                                                       T('Todas as chamadas', ['Programa chamador', 'Linha', 'Mecanismo', 'Programa chamado', 'Comando', 'Copybook da área de comunicação'], calls)]))
    sections.append(S('copybooks', 'Programas e copybooks', [{**G('Programa → copybook', prog_nodes + list(cbn.values()), cbe), **lab}]))
    campos = []
    for p, x in sorted(sm.get('programs', {}).items()):
        fs = x.get('copybook_fields') or []
        if not any(f['read'] or f['written'] for f in fs):
            continue
        executado = dyn is None or p in dyn['real']
        por_cb = defaultdict(list)
        for f in fs:
            por_cb[f['copybook']].append(f)
        pid = 'P:' + p
        nds = [{'id': pid, 'label': p, 'group': cls.get(p, 'externo (fora do código analisado)'), 'inactive': not executado, 'detail': p + ('' if executado else ' — não executado em nenhum cenário')}]
        eds = []
        for cb, lst in sorted(por_cb.items()):
            if not any(f['read'] or f['written'] for f in lst):
                continue   # copybook sem nenhum campo lido nem escrito pelo programa
            ev = lst[0].get('evidencia', '')
            esq = [f for f in lst if f['read']]
            dir_ = [f for f in lst if f['written']]
            nao = [f for f in lst if not (f['read'] or f['written'])]
            for lado, usados in (('left', esq), ('right', dir_)):
                if not usados:
                    continue
                dominante = (lado == 'left') == (len(esq) >= len(dir_))
                cols = []
                for f in usados + (nao if dominante else []):
                    r, w = bool(f['read']), bool(f['written'])
                    uso = ('entrada' if lado == 'left' else 'saída') if (r or w) else 'não usado'
                    outro = ' (também ' + ('saída' if lado == 'left' else 'entrada') + ')' if (r and w) else ''
                    motivo = {'entrada': 'lido pelo programa', 'saída': 'escrito pelo programa', 'não usado': 'não usado: nenhum comando do programa lê ou grava este campo (nem o grupo dele)'}[uso] + outro
                    if f.get('via_grupo'):
                        motivo += '; só o grupo dele é lido/escrito'
                    if not executado:
                        motivo += '; não alcançado: o programa não foi executado em nenhum cenário'
                    pic = f['pic'] or 'sem PIC'
                    tipo = pic if f['declared'] else f'{pic} (inferido pelo uso)'   # tipo do campo no copybook; sem o copybook, o tipo que a análise deduziu do uso
                    sit = motivo + ('' if f['declared'] else '; copybook ausente: tipo e campo deduzidos pelo uso (' + ('lido' if r else 'escrito' if w else 'sem uso') + ' no programa)') + ('' if f.get('declarado_em', cb) == cb else f'; declarado em {f["declarado_em"]}, incluído por {cb}')
                    cols.append({'name': f['name'], 'type': tipo, 'dashed': (not (r or w)) or not executado, 'state': sit})
                nid = f'C:{p}:{cb}:{lado}'
                nds.append({'id': nid, 'label': f'{cb} ({"entrada" if lado == "left" else "saída"})', 'group': 'copybook', 'columns': cols, 'side': lado, 'inactive': not executado,
                            'detail': f'{cb}: {len(usados)} campo(s) de {"entrada" if lado == "left" else "saída"}; {ev}'})
                eds.append({'from': nid, 'to': pid, 'label': f'entrada: {len(usados)} campo(s) lido(s) — {ev}'} if lado == 'left' else {'from': pid, 'to': nid, 'label': f'saída: {len(usados)} campo(s) escrito(s) — {ev}'})
        if len(nds) == 1:
            continue
        campos.append({**G(f'{p}: campos de entrada e saída dos copybooks', nds, eds, kind='er'), 'cap': 9999, 'per_row': 1,
                       'dashed_label': 'tracejado = campo não usado pelo programa' + (' ou programa não alcançado por nenhum cenário' if dyn is not None else ''),
                       **({'inactive_label': lab['inactive_label']} if (dyn is not None and not executado) else {})})
    if campos:
        sections.append(S('campos-copybooks', 'Campos de entrada e saída dos copybooks por programa', campos,
                          'Um diagrama por programa: as entradas à esquerda do programa e as saídas à direita. Entrada = campo lido pelo programa; saída = campo escrito (um copybook com os dois aparece nos dois lados, cada campo no lado em que é usado; se só o grupo do campo é lido ou escrito, vale o uso do grupo). '
                          'Campo tracejado = não usado (nenhum comando do programa o lê ou grava) ou, quando há execução dinâmica, programa que nenhum cenário alcançou. '
                          'Só os copybooks do próprio programa (COPY no fonte dele) que são entrada ou saída dele: pela estrutura (área de comunicação ou de chamada a programa de negócio) ou, sem evidência estrutural, inferidos pelo uso (campos só lidos ou só escritos); dentro dos que aparecem, os campos não usados ficam tracejados; o que um copybook inclui aparece no copybook que o programa inclui). Copybook ausente: só aparecem os campos deduzidos pelo uso; campo sem copybook identificado não aparece.'))
    # "Acesso por programa e tabela" é a tabela do diagrama (inclui o cursor de cada acesso).
    sections.append(S('tabelas', 'Programas e tabelas DB2', [{**G('Programa → tabela (cursor resolvido até a tabela)', prog_nodes + list(tn.values()), te), **lab, 'sem_tabela': True},
                                                              T('Acesso por programa e tabela', ['Programa', 'Tabela', 'Operações', 'Acesso'], acc_rows)]))
    cards = [card('programas', len(ps)), card('chamadas', len(cg)), card('tabelas DB2', len(tn)), card('cursores', len(cur_rows)), card('copybooks', len(cbn)), card('chamadas não resolvidas', unres)]
    if dyn:
        prow = [(n['id'], cls.get(n['id'], 'externo'), pstate(n['id']),
                 'nenhum cenário executa nem chama este programa' if pstate(n['id']) == 'não chamado' else ('só aparece como destino de chamada mockada' if 'mock' in pstate(n['id']) else '')) for n in nodes]
        trow = []
        for t in sorted(tn):
            name = t
            users = sorted({p for p, x in ps.items() if any(a['table'] == name for a in x['table_access'])})
            ex = sorted(used_tabs.get(name, ()))
            why = '' if ex else ('nenhum programa que a acessa foi executado' if not (set(users) & dyn['real']) else 'programas que a acessam foram executados, mas nenhum comando SQL sobre ela foi executado')
            trow.append((name, 'usada' if ex else 'não usada', ', '.join(ex), ', '.join(users), why))
        crow = [(cb, 'usado' if incl & dyn['real'] else 'não usado', ', '.join(sorted(incl & dyn['real'])), ', '.join(sorted(incl)),
                 '' if incl & dyn['real'] else 'nenhum programa que o inclui foi executado') for cb, incl in sorted(cb_by.items())]
        sections.append(S('dinamico', 'O que a execução dos cenários chamou', [
            T('Programas: chamados ou não', ['Programa', 'Classe', 'Situação', 'Motivo'], prow),
            T('Tabelas: usadas ou não', ['Tabela', 'Situação', 'Programas que a acessaram na execução', 'Programas que a acessam no código', 'Motivo'], trow),
            T('Copybooks: usados ou não', ['Copybook', 'Situação', 'Programas executados que o incluem', 'Programas que o incluem', 'Motivo'], crow)],
            'Depois da análise dinâmica: o que nenhum cenário chamou ou executou aparece acinzentado nos diagramas.'))
        cards += [card('programas chamados', f'{sum(1 for n in nodes if pstate(n["id"]) != "não chamado")}/{len(nodes)}'),
                  card('tabelas usadas', f'{sum(1 for t in tn if not tn[t]["inactive"])}/{len(tn)}'),
                  card('copybooks usados', f'{sum(1 for c in cbn.values() if not c["inactive"])}/{len(cbn)}')]
    sections.append(S('resumo', 'Consumo por programa', [T('Recursos por programa', ['Programa', 'Chamadas', 'Comandos SQL', 'Tabelas', 'Cursores', 'Comandos CICS', 'Arquivos', 'Copybooks'], rows)]))
    return model('Fase 1 — Dependências', 'Quem chama quem, quais tabelas (inclusive via cursor) e copybooks cada programa usa; depois da execução, o que foi realmente chamado.', cards, sections)


def _dinamicos(m, *titulos):
    """Blocos da seção 'dinamico' da visão completa de dependências cujo título começa com um dos prefixos (some se não houve execução dinâmica)."""
    return [b for sec in m['sections'] if sec['id'] == 'dinamico' for b in sec['blocks'] if b.get('title', '').startswith(titulos)]


def _cards(m, *rotulos):
    return [c for c in m['summary'] if c['label'].startswith(rotulos)]


def m_dependencies(r, ctx):
    """Fase 1: árvore de chamadas, programa → copybook, tabelas por programa e consumo de recursos."""
    m = _dependencias_tudo(r, ctx)
    secs = []
    for sec in m['sections']:
        if sec['id'] == 'campos-copybooks':
            continue
        secs.append(S(sec['id'], sec['title'], [b for b in sec['blocks'] if not b.get('title', '').startswith('Copybooks: usados')], sec.get('text')) if sec['id'] == 'dinamico' else sec)
    m['sections'] = secs
    m['title'] = 'Fase 1 — Dependências'
    m['subtitle'] = 'Quem chama quem e quais tabelas (inclusive via cursor) cada programa usa; depois da execução, o que foi realmente chamado. O diagrama Programa → copybook mostra os copybooks de cada programa; os campos de entrada e saída estão na fase 2 (Esquema de programas).'
    return m


def m_program_schema(r, ctx):
    """Fase 2: programas, copybooks e atributos de entrada e saída de cada programa; mesmos dados da fase 1, em relatório próprio."""
    m = _dependencias_tudo(r, ctx)
    secs = [sec for sec in m['sections'] if sec['id'] == 'campos-copybooks']
    din = _dinamicos(m, 'Copybooks: usados')
    if din:
        secs.append(S('dinamico', 'O que a execução dos cenários chamou', din, 'Depois da análise dinâmica: o copybook que nenhum programa executado inclui aparece acinzentado nos diagramas.'))
    m['sections'] = secs
    m['summary'] = _cards(m, 'programas', 'copybooks')
    m['title'] = 'Fase 2 — Esquema de programas'
    m['subtitle'] = 'Mapeamento de programas, copybooks e atributos de entrada e saída: quais copybooks cada programa inclui, quais campos entram (lidos) e saem (escritos) e quais não são usados.'
    return m


# ----------------------------------------------------------------------------- 02 mapa de decisão
EXTRA_WHY = {
    'PROGRAMA_NAO_EXECUTADO': 'Nenhum cenário executa este programa de verdade (só mock ou nunca chamado).',
    'MOCKADO_NO_ENTRY_POINT': 'Os cenários mockam este programa; ele não roda de verdade em nenhum deles.',
    'PARAGRAFO_NAO_EXECUTADO': 'Nenhum cenário passou por este parágrafo (nenhum PERFORM executado o alcançou).',
    'RAMO_ANTERIOR_NAO_EXECUTADO': 'Este trecho está dentro de um ramo que nenhum cenário executou.',
    'SEM_EXECUCAO_REGISTRADA': 'O fluxo chegou ao ramo, mas a execução terminou antes deste trecho.',
    'FALTA_CENARIO': 'Alcançável e sem impedimento estático: falta um cenário com entradas/tabelas que decidam este lado.',
}


def _paragraph_order(dm):
    return [p['name'] for p in dm['paragraphs']]


def marks(dm, rt):
    """{código: {'ok': bool, 'reason': código do motivo, 'why': texto}} para cada decisão e caixa; None sem execução.
    Executado = linha do comando no rastro (caixa) ou ramo tomado (decisão); herda 'não executado' do ramo em volta."""
    if not rt:
        return None
    p = dm['program']
    cov = rt.get('coverage_by_program', {}).get(p, {})
    ba = rt.get('branch_analysis') or {}
    desc = {**EXTRA_WHY, **(ba.get('descricao') or {})}
    lines = {ln for ln, _n in rt.get('executed_lines', {}).get(p, [])}
    taken = {(d, k) for d, k in rt.get('taken_branches', {}).get(p, [])}
    order = _paragraph_order(dm)
    performed = set()
    for a, b in rt.get('executed_paragraphs', {}).get(p, []):
        if a in order:
            i = order.index(a)
            j = order.index(b) if b in order else i
            performed |= set(order[i:max(i, j) + 1])
    reasons = {(x['decision_id'], x['branch']): x for x in (ba.get('por_programa') or {}).get(p, [])}
    prog_exec = bool(cov.get('executed_in_scenarios')) or bool(lines)
    out = {}

    def hit_inside(items):
        for it in items:
            if it['kind'] == 'box':
                if any(l in lines for l in it['stmt_lines']):
                    return True
            else:
                if any((it['decision_id'], k) in taken for k in it['true_keys'] + it['false_keys']):
                    return True
                if hit_inside(it['then']) or hit_inside(it['else']):
                    return True
        return False

    def put(it, ok, code, why=None):
        out[it['code']] = {'ok': ok, 'reason': '' if ok else code, 'why': '' if ok else (why or desc.get(code, code))}

    def why_branch(did, keys):
        for k in keys:
            x = reasons.get((did, k))
            if x:
                return x['reason'], x['explanation']
        return 'FALTA_CENARIO', desc['FALTA_CENARIO']

    def walk(items, ok, code, why):
        for it in items:
            if it['kind'] == 'box':
                if not ok:
                    put(it, False, code, why)
                elif it['stmt_lines'] and not any(l in lines for l in it['stmt_lines']):
                    put(it, False, 'SEM_EXECUCAO_REGISTRADA')
                else:
                    put(it, True, '')
                continue
            if not ok:
                put(it, False, code, why)
                walk(it['then'], False, code, why)
                walk(it['else'], False, code, why)
                continue
            if it['construct'] == 'LOOP':
                put(it, True, '')
                walk(it['then'], True, '', '')
                continue
            t_ok = any((it['decision_id'], k) in taken for k in it['true_keys'])
            f_ok = any((it['decision_id'], k) in taken for k in it['false_keys'])
            if not (t_ok or f_ok):
                put(it, False, 'SEM_EXECUCAO_REGISTRADA')
                walk(it['then'], False, 'SEM_EXECUCAO_REGISTRADA', desc['SEM_EXECUCAO_REGISTRADA'])
                walk(it['else'], False, 'SEM_EXECUCAO_REGISTRADA', desc['SEM_EXECUCAO_REGISTRADA'])
                continue
            put(it, True, '')
            out[it['code']]['ramos'] = {'Sim': t_ok, 'Não': f_ok}   # ramo efetivamente tomado por algum cenário: uma regra só é alcançada se o resultado dela foi tomado
            for side, okk, keys in (('then', t_ok, it['true_keys']), ('else', f_ok, it['false_keys'])):
                if okk:
                    walk(it[side], True, '', '')
                else:
                    c, w = why_branch(it['decision_id'], keys)
                    walk(it[side], False, c, w)
    for i, par in enumerate(dm['paragraphs']):
        if not prog_exec:
            c = 'MOCKADO_NO_ENTRY_POINT' if cov.get('mocked_in_scenarios') else 'PROGRAMA_NAO_EXECUTADO'
            walk(par['items'], False, c, desc[c])
        elif i == 0 or par['name'] in performed or hit_inside(par['items']):
            walk(par['items'], True, '', '')
        else:
            walk(par['items'], False, 'PARAGRAFO_NAO_EXECUTADO', desc['PARAGRAFO_NAO_EXECUTADO'])
    return out


def _box_group(it):
    ef = [{'type': t, 'resolved_detail': {'operation': o}} for t, o in it['effects']]
    return 'encerra o programa' if it['ends'] else effect_group(ef)


def mock_code_texts(items, mock_lines):
    """{código da caixa: [texto do mock]} das caixas que têm algum comando de linha mockada em mock_lines ({linha: texto})."""
    out = {}
    for it in _boxes(items):
        t = sorted({mock_lines[l] for l in it['stmt_lines'] if l in (mock_lines or {})})
        if t:
            out[it['code']] = t
    return out


def dm_flowchart(title, par, items, mk, rules_of, mock_lines=None):
    """Fluxograma de um parágrafo: caixa de execução (Enn) e decisão (Dnn) na ordem do código, ramos Sim/Não, junção quando os ramos voltam."""
    nodes, edges, cnt = [], [], [0]
    mock_codes = mock_code_texts(items, mock_lines)

    def new(shape, label, group, detail, code=None):
        cnt[0] += 1
        nid = f'n{cnt[0]}'
        n = {'id': nid, 'label': label, 'shape': shape, 'group': group, 'detail': detail}
        if mk is not None and code in mk:
            mocked = mk[code]['reason'] == 'MOCKADO_NO_ENTRY_POINT'
            n['inactive'] = not mk[code]['ok'] and not mocked
            n['mocked'] = mocked or (mk[code]['ok'] and code in mock_codes)
            if mocked:
                n['detail'] = detail + ' — MOCKADO: ' + mk[code]['why']
            elif not mk[code]['ok']:
                n['detail'] = detail + ' — NÃO EXECUTADO: ' + mk[code]['why']
            elif n['mocked']:
                n['detail'] = detail + ' — executado, mas com mock: ' + '; '.join(mock_codes[code])
        nodes.append(n)
        return nid

    def emit(seq, tails):
        for it in seq:
            if it['kind'] == 'box':
                nid = new('action', it['code'] + '\n' + '\n'.join(it['lines']), _box_group(it), f'{it["code"]} linha {it["source_line"]}', it['code'])
                for s, lab in tails:
                    edges.append({'from': s, 'to': nid, 'label': lab})
                tails = [] if it['ends'] else [(nid, '')]
                continue
            kw = {'IF': 'IF', 'EVALUATE': 'IF', 'ELSIF': 'ELSIF', 'LOOP': 'LOOP'}[it['construct']]
            head = f'{it["code"]} {kw}'
            text = it['cond'] if it['construct'] == 'LOOP' else it['cond'] + '?'
            dn = new('decision', head + '\n' + text, 'decisão', f'{it["code"]} linha {it["source_line"]}: {it["cond"]}', it['code'])
            for s, lab in tails:
                edges.append({'from': s, 'to': dn, 'label': lab})
            yes, no = ('corpo', 'segue') if it['construct'] == 'LOOP' else ('Sim', 'Não')
            t1 = emit(it['then'], [(dn, yes)])
            t2 = emit(it['else'], [(dn, no)])
            tails = t1 + t2
            if len(tails) > 1 and it['construct'] != 'ELSIF':
                jn = new('join', '', '', 'junção')
                for s, lab in tails:
                    edges.append({'from': s, 'to': jn, 'label': lab})
                tails = [(jn, '')]
        return tails
    st = new('start', par, 'início', 'início do parágrafo')
    tails = emit(items, [(st, '')])
    if tails:
        en = new('end', 'fim do parágrafo', 'início', 'fim do parágrafo')
        for s, lab in tails:
            edges.append({'from': s, 'to': en, 'label': lab})
    g = G(title, nodes, edges, kind='flowchart')
    if mk is not None:
        g['inactive_label'] = 'cinza tracejado = trecho não executado por nenhum cenário (motivo na tabela abaixo)'
        g['mocked_label'] = 'fundo amarelo = mockado (programa não executado de verdade neste entry point, ou chamada com retorno definido pelo cenário)'
    return g


def _has_decision(items):
    return any(it['kind'] == 'decision' for it in items)


def m_static(r, ctx):
    dms = r['decision_map']
    rt = ctx.get('rt')
    rules = (ctx['phase'].get('06-deterministic-rules') or {}).get('data_rules', {})
    sections, tot_d, tot_b, tot_off = [], 0, 0, 0
    per = []
    mlines = mocked_lines(ctx.get('scenarios'))
    for p, dm in dms.items():
        mk = marks(dm, rt)
        mline = mlines.get(p, {})
        mtext = {}
        for par in dm['paragraphs']:
            mtext.update(mock_code_texts(par['items'], mline))
        ruleof = defaultdict(list)
        for x in (rules.get(p) or {}).get('rules', []):
            for c in x.get('references', []):
                if x['code'] not in ruleof[c]:
                    ruleof[c].append(x['code'])
        blocks = []
        # chamadas entre parágrafos (PERFORM)
        pcalls = {(par['name'], t) for par in dm['paragraphs'] for it in _boxes(par['items']) for t in it['performs'] if t}
        names = {par['name'] for par in dm['paragraphs']}
        if pcalls:
            state = {}
            if mk is not None:
                for par in dm['paragraphs']:
                    its = list(_all(par['items']))
                    state[par['name']] = any(mk[i['code']]['ok'] for i in its) if its else True
            def pmock(par):
                its = list(_all(par['items']))
                return mk is not None and bool(its) and all(mk[i['code']]['reason'] == 'MOCKADO_NO_ENTRY_POINT' for i in its)
            nn = [{'id': par['name'], 'label': par['name'], 'group': 'parágrafo', 'inactive': mk is not None and not state[par['name']] and not pmock(par), 'mocked': pmock(par),
                   'detail': f'{par["name"]} (linha {par["source_line"]})'}
                  for par in dm['paragraphs'] if any(par['name'] in c for c in pcalls)]
            ee = [{'from': a, 'to': b, 'label': 'PERFORM'} for a, b in sorted(pcalls) if b in names]
            blocks.append({**G(f'Chamadas entre parágrafos — {p}', nn, ee), **({'inactive_label': 'cinza tracejado = parágrafo não executado por nenhum cenário', 'mocked_label': 'fundo amarelo = programa mockado neste entry point'} if mk is not None else {})})
        for par in dm['paragraphs']:
            if _has_decision(par['items']) or any(b['lines'] and [x.strip().rstrip('.').upper() for x in b['lines']] != ['EXIT'] for b in _boxes(par['items'])):   # parágrafo só com comandos também tem diagrama (nada do código fica sem desenho)
                blocks.append(dm_flowchart(f'{p} — {par["name"]}', par['name'], par['items'], mk, ruleof, mline))
        rows, off = [], []
        for row in dm['rows']:
            m = (mk or {}).get(row['code'])
            state = '' if m is None else (('executado com mock' if row['code'] in mtext else 'executado') if m['ok'] else 'mockado' if m['reason'] == 'MOCKADO_NO_ENTRY_POINT' else 'não executado')
            text = row['text'] if row['kind'] == 'execução' else [('IF ' if row['construct'] in ('IF', 'EVALUATE') else 'ELSIF ' if row['construct'] == 'ELSIF' else '') + row['text'][0]]
            sq = ((rules.get(p) or {}).get('status_commands') or {}).get(row['code'])
            ctext = with_links('; '.join(text), [sql_link(sq)] if sq and sq.get('id') else []) if row['kind'] != 'execução' else '; '.join(text)
            if sq and not sq.get('id'):
                ctext = f'{ctext} · {sq["op"]} linha {sq["line"]}: {" ".join(str(sq["text"]).split())[:80]}'
            rows.append((f'{p}:{row["code"]}', row['kind'], row['paragraph'], row['source_line'], ctext, row.get('then_first') or '', row.get('else_first') or '',
                         ', '.join(f'{p}:{r}' for r in ruleof.get(row['code'], [])), state, '; '.join(mtext.get(row['code'], [])) if m is None or m['ok'] else m['why']))
            if m is not None and not m['ok'] and m['reason'] != 'MOCKADO_NO_ENTRY_POINT':
                off.append((f'{p}:{row["code"]}', row['kind'], row['paragraph'], row['source_line'], m['reason'], m['why']))
        blocks.append(T(f'Mapa de decisão — {p}', ['Código', 'Tipo', 'Parágrafo', 'Linha', 'Condição ou comandos', 'Se sim segue em', 'Se não segue em', 'Regras que usam', 'Execução', 'Motivo'] if mk is not None else
                        ['Código', 'Tipo', 'Parágrafo', 'Linha', 'Condição ou comandos', 'Se sim segue em', 'Se não segue em', 'Regras que usam', 'Execução', 'Motivo'], rows))
        if mk is not None:
            blocks.append(T(f'Trechos não executados — {p}', ['Código', 'Tipo', 'Parágrafo', 'Linha', 'Motivo', 'Explicação'], off))
        s = dm['summary']
        tot_d += s['decisions']
        tot_b += s['boxes']
        tot_off += len(off)
        per.append({'label': p, 'parts': [{'name': 'decisões', 'value': s['decisions']}, {'name': 'caixas de execução', 'value': s['boxes']}]})
        sections.append(S('prog-' + p, f'Mapa de decisão — {p}', blocks,
                          f'{s["decisions"]} decisões e {s["boxes"]} caixas de execução em {s["paragraphs"]} parágrafos. Losango = decisão (IF/ELSIF; EVALUATE vira cadeia IF/ELSIF); retângulo = comandos do trecho, na ordem do código; cor = tipo do que o trecho faz.'
                          + (f' {len(off)} trechos não executados pelos cenários.' if mk is not None else '')))
    cs = r['catalog_summary']
    head = [S('resumo', 'Resumo por programa', [B('Decisões e caixas de execução por programa', per)])]
    if rt:
        head.append(S('como', 'Como ler o que não foi executado', [X('Cada decisão (Dnnn) e caixa de execução (Ennn) aparece cinza tracejada quando nenhum cenário passou por ela, e com fundo amarelo claro quando é mockada (programa não executado de verdade neste entry point, ou caixa executada cuja chamada tem retorno definido pelo cenário). O motivo vem da análise dos ramos sem cobertura: '
                                                                   'parágrafo não executado, ramo anterior não executado, dependência de status externo (SQLCODE/EIBRESP), falta de cenário etc.')]))
    tail = [S('catalogo', 'Catálogo', [T('Contagens do catálogo', ['Item', 'Valor'], [(k, v) for k, v in cs.items() if not isinstance(v, (dict, list))]),
                                       T('Classes da fase 0', ['Classe', 'Programas'], list(cs['phase0'].items())),
                                       T('Recomendações', ['Recomendação', 'Programas'], list(cs['recommendations'].items()))])]
    cards = [card('programas', len(dms)), card('decisões', tot_d), card('caixas de execução', tot_b)]
    if rt:
        cards.append(card('trechos não executados', tot_off))
    return model('Fase 5 — Mapa de decisões', 'Análise estática: para cada parágrafo, a sequência de comandos e decisões do código em texto legível (EVALUATE vira IF/ELSIF); depois da execução, o que nenhum cenário alcançou fica cinza e o que foi mockado (programa, chamada de programa ou consulta de dados com retorno definido pelo cenário) fica com fundo amarelo.',
                 cards, head + sections + tail)


def _boxes(items):
    for it in items:
        if it['kind'] == 'box':
            yield it
        else:
            yield from _boxes(it['then'])
            yield from _boxes(it['else'])


def _all(items):
    for it in items:
        yield it
        if it['kind'] == 'decision':
            yield from _all(it['then'])
            yield from _all(it['else'])


# ----------------------------------------------------------------------------- 03 esquema de dados
def _coltype(c):
    return c['sql_type'] + (f'({c["precision"]},{c["scale"]})' if c.get('precision') is not None else (f'({c["length"]})' if c.get('length') else ''))


def m_schema(r, ctx):
    usage, roles, sch = r['usage'], r['roles'], r['schema']
    members = {d['table']: (m, d) for m, d in r['members'].items() if d.get('table')}
    dyn = dynamic(ctx)
    deps = {p: {'table_access': []} for p in usage}
    seen_tabs = scenario_tables_seen(ctx) if dyn else {}
    for d_ in sch['deduced_columns']:   # sem PIC nem literal: o tipo dos valores que os cenários colocaram na coluna
        if d_['type'] == 'sem declaração' and seen_tabs:
            o_ = observed_type(seen_tabs, _match(d_['table'], seen_tabs), d_['column'])
            if not o_.startswith('indeterminado'):
                d_['type'] = o_.replace(' (inferido)', '', 1)
                d_['basis'] = d_['basis'].replace(' (campo sem declaração)', '') + ' + tipo dos valores vistos nos cenários'
    static_tabs = {t['table'] for t in roles}
    used_tabs = {}
    if dyn:
        deps = ctx['phase'].get('01-discovery-dependencies', {}).get('programs', {})
        used_tabs = executed_tables(dyn, deps)
    role_of = {t['table']: t for t in roles}
    ded = defaultdict(list)
    for d in sch['deduced_columns']:
        ded[d['table']].append(d)
    cu = defaultdict(dict)
    for u in sch['column_usage']:
        cu[u['table']][u['column']] = u
    # uso do campo COBOL por programa (do campo mapeado à coluna)
    field_use = {p: {f['name']: f['status'] for f in d['fields']} for p, d in usage.items()}
    binds = r['program_bindings']
    inc_by_member = defaultdict(set)
    for p, b in binds.items():
        for i in b['includes']:
            if i.get('status') not in ('MISSING', 'SYSTEM'):
                inc_by_member[i['name']].add(p)
    # tabelas descobertas só na fase dinâmica
    dyn_only = sorted(t for t in seen_tabs if not _match(t, static_tabs))
    def seen_cols(name):
        k = _match(name, seen_tabs) if seen_tabs else None
        return sorted(seen_tabs[k]['columns']) if k else []
    # ---- nós do ER
    nodes, edges, colsof = [], [], defaultdict(list)
    for t in roles:
        name = t['table']
        grp = t['role'] + ('' if t['has_dclgen'] else ' (sem DCLGEN)')
        det = f'{name}: {t["role"]}, nível {t["level"]}, entry points: {", ".join(t["entry_points"])}'
        inactive = bool(dyn) and not (name in used_tabs or _match(name, seen_tabs))
        if name in members:
            m, d = members[name]
            cols = [{'name': c['name'], 'type': _coltype(c), 'key': c['position'] == 1} for c in d['columns']]
            nodes.append({'id': name, 'label': _short(name), 'group': grp, 'columns': cols, 'detail': det, 'inactive': inactive})
            for c in d['columns']:
                colsof[c['name']].append(name)
        else:
            cols = [{'name': d['column'], 'type': inf(d['type']), 'key': False} for d in ded.get(name, [])]
            if not cols:   # sem DCLGEN e sem dedução pelo SQL: as colunas vistas nas linhas dos cenários também entram no diagrama
                cols = [{'name': c, 'type': observed_type(seen_tabs, _match(name, seen_tabs), c), 'key': False} for c in seen_cols(name)]
            nodes.append({'id': name, 'label': _short(name), 'group': grp, 'columns': cols, 'detail': det, 'inactive': inactive} if cols else {'id': name, 'label': _short(name), 'group': grp, 'detail': det, 'inactive': inactive})
    for t in dyn_only:
        cols = [{'name': c, 'type': observed_type(seen_tabs, t, c), 'key': False} for c in sorted(seen_tabs[t]['columns'])]
        nodes.append({'id': t, 'label': _short(t), 'group': 'descoberta na análise dinâmica', 'columns': cols, 'detail': f'{t}: só aparece nos cenários'})
    for col, ts in colsof.items():
        for i in range(len(ts) - 1):
            edges.append({'from': ts[i], 'to': ts[i + 1], 'label': col})
    er = {**G('Tabelas do sistema por papel', nodes, edges, kind='er',
              note='Papel: protagonista = alguma operação INSERT, UPDATE, DELETE ou MERGE a altera; coadjuvante = só consultada, mas aparece bastante (vários programas ou entry points, ou mais consultas que a mediana); figurante = só consultada e aparece pouco. Tipo com "(inferido)" não vem de DCLGEN: é deduzido do uso no SQL, da PIC do campo ou dos valores vistos nos cenários (tabela sem DCLGEN) e escrito no padrão DB2; "indeterminado" = nenhuma pista.')}
    if dyn:
        er['inactive_label'] = 'cinza tracejado = tabela que nenhum cenário usou'
    # ---- colunas por tabela
    colrows, unused_series = [], []
    percol = defaultdict(list)          # tabela -> [coluna do diagrama por tabela]
    real_p = (dyn['real'] | dyn['mock']) if dyn else set()

    ran_ops = defaultdict(set)         # (programa, tabela sem qualificador) -> comandos SQL executados pelos cenários
    if dyn:
        for pg, lines in dyn['sql_lines'].items():
            for a in (deps.get(pg) or {}).get('table_access', []):
                if a['line'] in lines:
                    ran_ops[(pg, _short(a['table']))].add(a['operation'])
    EXEC_OF = {'DECLARE': ('OPEN', 'FETCH'), 'FETCH': ('FETCH',)}

    def _state(t, cname, static_used, u, used_in):
        """Situação da coluna: usada; usada no código mas nenhum cenário a usou; nunca usada. Execução = comando SQL que cita a coluna
        do mesmo tipo (SELECT, INSERT, UPDATE, DELETE; DECLARE vale por OPEN ou FETCH) que algum cenário executou naquele programa e tabela, ou programa executado que usa o campo mapeado."""
        if not static_used:
            return 'nunca usada (nem no código)', True
        if not dyn:
            return 'usada no código', False
        ran = any(set(EXEC_OF.get(op, (op,))) & ran_ops[(pg, _short(t))] for pg, op in (u or {}).get('statements', ())) or any(pg in real_p for pg in used_in)
        return ('usada na execução', False) if ran else ('usada no código, nenhum cenário a usou', True)
    for t in sorted(members):
        m, d = members[t]
        mp = {x['column']: x for x in d['mapping']}
        prs = sorted(inc_by_member.get(m, ()))
        n_used = 0
        for c in d['columns']:
            x = mp.get(c['name'], {})
            f = x.get('field')
            u = cu.get(t, {}).get(c['name'])
            used_in = [p for p in prs if f and field_use.get(p, {}).get(f, '').endswith('AND_USED')]
            unused_in = [p for p in prs if f and p not in used_in]
            sql_use = '; '.join(f'{lab}: {", ".join(u[k])}' for k, lab in (('read', 'lê'), ('write', 'grava'), ('filter', 'filtra')) if u and u[k])
            used = bool(used_in or sql_use)
            n_used += used
            st, off = _state(t, c['name'], used, u, used_in)
            percol[t].append({'name': c['name'], 'type': _coltype(c), 'key': c['position'] == 1, 'inactive': off, 'state': st})
            colrows.append((_short(t), c['name'], _coltype(c), 'sim' if c['nullable'] else 'não', 'DCLGEN', f or '', x.get('pic') or '', ', '.join(used_in), ', '.join(unused_in), sql_use, 'usada' if used else 'não usada'))
        unused_series.append({'label': _short(t), 'parts': [{'name': 'usadas', 'value': n_used}, {'name': 'não usadas', 'value': len(d['columns']) - n_used}]})
    for t in sorted(ded):
        for d in ded[t]:
            u = cu.get(t, {}).get(d['column'], {})
            sql_use = '; '.join(f'{lab}: {", ".join(u[k])}' for k, lab in (('read', 'lê'), ('write', 'grava'), ('filter', 'filtra')) if u and u[k])
            st, off = _state(t, d['column'], True, u, [])
            percol[t].append({'name': d['column'], 'type': inf(d['type']), 'key': False, 'inactive': off, 'state': st})
            colrows.append((_short(t), d['column'], inf(d['type']), '', 'deduzida do SQL', ', '.join(d['host_fields']), '', '', '', sql_use, 'usada'))
    for t in roles:   # tabela sem DCLGEN e sem dedução: colunas vistas nos cenários
        if not percol.get(t['table']) and seen_cols(t['table']):
            percol[t['table']] = [{'name': c, 'type': observed_type(seen_tabs, _match(t['table'], seen_tabs), c), 'key': False, 'inactive': False, 'state': 'vista nas linhas dos cenários'} for c in seen_cols(t['table'])]
    colrows.sort(key=lambda x: (x[0], x[4] != 'DCLGEN', x[1]))
    # ---- deduções
    dedrows = [(_short(d['table']), d['column'], inf(d['type']), ', '.join(d['host_fields']), ', '.join(d['modes']), ', '.join(d['programs']), ', '.join(f'{p}@{ln}' for p, ln in d['lines']), d['basis']) for d in sch['deduced_columns']]
    # ---- papéis
    role_c = Counter(t['role'] for t in roles)
    rows = [(t['table'], t['role'], t['why'], t['write_commands'], t['read_commands'], len(t['programs']), len(t['entry_points']), t['level'], ', '.join(t['entry_points']), 'sim' if t['has_dclgen'] else 'não',
             '; '.join(f'{x["program"]} ({x["class"]}, nível {x["depth"]}: {"/".join(x["operations"])}{" via " + ",".join(x["cursors"]) if x["cursors"] else ""})' for x in t['programs'])) for t in roles]
    sm = r['summary']
    # ---- um diagrama por tabela com todas as colunas
    pt_graphs = []
    for t in roles:
        name = t['table']
        cols = percol.get(name) or []
        off = bool(dyn) and not (name in used_tabs or _match(name, seen_tabs))
        n_off = sum(1 for c in cols if c['inactive'])
        ttl = f'{_short(name)}: {t["role"]}' + (' — tabela que nenhum cenário alcançou' if off else '') + (f' — {n_off} de {len(cols)} colunas sem uso' if cols else ' — sem colunas conhecidas')
        node = {'id': name, 'label': _short(name), 'group': t['role'] + ('' if t['has_dclgen'] else ' (sem DCLGEN)'), 'columns': cols, 'inactive': off,
                'detail': f'{name}: {t["role"]}, entry points: {", ".join(t["entry_points"])}'}
        pt_graphs.append({**G(ttl, [node], [], kind='er'), 'cap': 9999, 'per_row': 1,
                          'inactive_label': 'cinza tracejado = tabela que nenhum cenário alcançou', 'column_label': 'vermelho riscado ✕ = coluna sem uso' + (' (nunca usada no código ou nenhum cenário a usou)' if dyn else ' no código')})
    for t in dyn_only:
        node = {'id': t, 'label': _short(t), 'group': 'descoberta na análise dinâmica', 'columns': [{'name': c, 'type': observed_type(seen_tabs, t, c), 'key': False} for c in sorted(seen_tabs[t]['columns'])], 'detail': f'{t}: só aparece nos cenários'}
        pt_graphs.append({**G(f'{_short(t)}: só aparece nos cenários', [node], [], kind='er'), 'cap': 9999, 'per_row': 1})

    # ---- as colunas de cada tabela logo abaixo do diagrama dela (âncora tabela-<nome> na primeira linha, destino dos links das outras fases)
    COLUNAS = ['Tabela', 'Coluna', 'Tipo', 'Aceita nulo', 'Origem da coluna', 'Campo COBOL', 'PIC', 'Programas que usam o campo', 'Programas que declaram e não usam', 'Uso no SQL', 'Situação']
    por_tab = defaultdict(list)
    for r_ in colrows:
        por_tab[r_[0]].append(r_[1:])
    pt_blocos = []
    for g_ in pt_graphs:
        pt_blocos.append(g_)
        nome = g_['nodes'][0]['label']
        if por_tab.get(nome):
            pt_blocos.append(T(f'Colunas de {nome}: tipo, campo COBOL e uso', COLUNAS[1:], por_tab[nome], ids=[f'tabela-{nome}'] + [''] * (len(por_tab[nome]) - 1)))
    papel = S('papel', 'Papel de cada tabela', [B('Tabelas por papel', counter_series(role_c, 'tabelas')),
                                                 T('Critérios dos papéis das tabelas', ['Papel ou conceito', 'Critério', 'De onde vem'], CRITERIOS_PAPEL),
                                                 T('Tabelas, papel e o que justifica o papel', ['Tabela', 'Papel', 'Por quê', 'Comandos de gravação', 'Comandos de consulta', 'Programas', 'Qtd. entry points', 'Nível', 'Entry points que a alcançam', 'DCLGEN', 'Programas (classe, nível, operações)'], rows)])
    sections = [papel,
                S('er', 'Diagrama entidade-relacionamento', [er]),
                S('por-tabela', 'Uma tabela por diagrama: colunas e o que nunca é usado', pt_blocos,
                  'Cada diagrama mostra uma tabela e todas as suas colunas. Coluna vermelha riscada (✕) = nunca usada: nenhum programa cita a coluna no SQL nem usa o campo COBOL mapeado a ela'
                  + ('; ou usada no código, mas nenhum cenário executou, naquele programa e tabela, um comando SQL do mesmo tipo que cita a coluna, nem rodou um programa que usa o campo' if dyn else '') + '. Tabela cinza tracejada = nenhum cenário a alcançou.'),
                dict(S('colunas', 'Colunas de cada tabela e o uso', [T('Colunas por tabela: tipo, campo COBOL e uso', COLUNAS, colrows),   # consolidada: lida pelo gerar_contracts e pelos prompts 7 e 11
                                                                B('Colunas usadas x não usadas por tabela', unused_series)],
                       'Situação: usada = algum programa usa o campo mapeado ou cita a coluna no SQL. Campos mapeados vêm do DCLGEN; colunas deduzidas vêm do SQL.'),
                     so_ia='Só na visão para IA: na página, as colunas de cada tabela ficam abaixo do diagrama dela.'),
                S('deducoes', 'Deduções para esquemas ausentes', [T('Colunas deduzidas do uso no SQL (tabela sem DCLGEN)', ['Tabela', 'Coluna', 'Tipo', 'Campo hospedeiro', 'Uso', 'Programas', 'Onde (programa@linha)', 'Base da dedução'], dedrows)],
                  'Sem o DCLGEN o esquema é deduzido: nome da coluna pelo SQL, campo COBOL pela variável hospedeira, tipo pela declaração PIC do campo (quando o copybook existe).')]
    n_used = sum(x['parts'][0]['value'] for x in unused_series)
    n_all = sum(x['parts'][0]['value'] + x['parts'][1]['value'] for x in unused_series)
    cards = [card('tabelas', len(nodes)), card('com DCLGEN', len(members)), card('sem DCLGEN (deduzidas)', sum(1 for t in roles if not t['has_dclgen'])), card('colunas deduzidas', len(sch['deduced_columns'])),
             card('colunas usadas', f'{n_used}/{n_all}'), card('cobertura de linhas DCLGEN %', sm['coverage_percent'])] + ([card('tabelas só nos cenários', len(dyn_only))] if dyn else []) + [card(k, role_c[k]) for k in rm.ROLE_ORDER if role_c.get(k)]
    return model('Fase 3 — Esquema de dados', 'Tabelas DB2 do sistema: colunas, uso de cada coluna, deduções onde o DCLGEN falta, tabelas achadas na execução e as operações que cada programa faz nelas.', cards, sections)
