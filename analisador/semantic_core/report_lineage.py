"""Modelos de visão das fases 4 e 6: linhagem de dados por campo (entre programas) e regras determinísticas.

Tudo sai dos resultados estruturados das fases (field_lineage.build e rule_paths.build); nada é gerado por interpretação."""
from collections import Counter, defaultdict

from report_model import T, B, G, S, card, model, sql_link, with_links


def _short(t):
    return t.split('.')[-1]


# ----------------------------------------------------------------------------- 04 linhagem por campo, entre programas
def _paths_text(paths):
    if not paths:
        return '(sempre)'
    return ' OU '.join(' E '.join(f'{c["code"]} {c["condition"]} → {c["result"]}' for c in p) or '(sempre)' for p in paths)


def _paths_cell(paths):
    """Condições do caminho em texto; as de teste de status (SQLCODE...) levam o link para o SQL cujo status elas testam."""
    seen, conds = set(), []
    for pth in paths or []:
        for c in pth:
            if c.get('sql') and c.get('code') not in seen:
                seen.add(c.get('code'))
                conds.append(c)
    links, extra = sql_links(conds)
    return with_links(_paths_text(paths) + ''.join(f' · {e}' for e in extra), links)


def _sql_rows(t, v, dyn, cmd_ran):
    """Uma linha por comando SQL da tabela, inclusive os de cursor: [(id, rótulo, cursor, programa, linha, parágrafo, sql, entry points, execução)]."""
    rows = {}
    for x in v['sql']:
        lab = f'DECLARE CURSOR ({x["statement"]})' if x['cursor'] else x['statement']
        ran = ('executado' if cmd_ran(x) else 'NÃO EXECUTADO') if dyn else ''
        rows.setdefault(x['id'], (x['id'], lab, x['cursor'] or '', x['program'], x['line'] or '', x['paragraph'] or '', x['sql'], ', '.join(x['entry_points']), ran))
        for a in x['associated']:
            ran_a = ('executado' if a['line'] in dyn['sql_lines'].get(x['program'], ()) else 'NÃO EXECUTADO') if dyn else ''
            rows.setdefault(a['id'], (a['id'], a['statement'], x['cursor'] or '', x['program'], a['line'], a['paragraph'] or '', x['sql'], ', '.join(x['entry_points']), ran_a))
    return sorted(rows.values(), key=lambda r: (r[3], r[4] if isinstance(r[4], int) else 0, r[1]))


def _chain_text(steps):
    if not steps:
        return ''
    out = steps[0]['from']
    for s in steps:
        loc = f'{s["program"]}@{s["line"]}' if s.get('line') else s['program']
        out += f' —{s["op"] or s["kind"]} {loc}→ {s["to"]}'
    return out


def _origin_text(o):
    return f'{o["kind"]}: {o["name"]}'


def _origin_status(o):
    """Separa a origem esperada (valor fixo, tabela, comando CICS, entrada do entry point, valor inicial) da origem que o rastreio não conseguiu explicar."""
    if o.get('kind') == '-':
        return ''
    return 'esperada' if o.get('expected') else 'não rastreada'


def _progs_of(steps, default):
    seq = []
    for s in steps:
        for pn in str(s['program']).split('→'):
            if not seq or seq[-1] != pn:
                seq.append(pn)
    if not seq or seq[-1] != default:
        seq.append(default)
    return seq


def _field_label(name):
    """'PROG · CAMPO (ÁREA)' -> 'CAMPO · PROG'; coluna de tabela 'ESQ.TAB.COL' -> 'TAB.COL'."""
    name = str(name)
    if ' · ' in name:
        prog, campo = name.split(' · ', 1)
        return campo.split(' (')[0] + ' · ' + prog
    parts = name.split('.')
    return '.'.join(parts[-2:]) if len(parts) >= 3 else name


def _origin_label(o):
    if o['kind'] == 'valor fixo':
        return 'valor: ' + str(o['name'])
    return _field_label(o['name'])


TRANSFORM_OPS = {'COMPUTE', 'ADD', 'SUBTRACT', 'MULTIPLY', 'DIVIDE', 'STRING', 'UNSTRING', 'INSPECT'}


def _snip(text, n=100):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= n else text[:n - 1] + '…'


def _cond_text(c):
    return (f'{c["program"]}:{c["code"]} (linha {c["line"]}): ' if c.get('code') else '') + (('se ' + c['condition']) if c['result'] == 'Sim' else f'senão ({c["condition"]})')


def sql_links(conds):
    """Links para o SQL de que as condições de status (SQLCODE, SQLWARN0...) testam o resultado; texto do CICS quando o status é de comando CICS."""
    links, extra, seen = [], [], set()
    for c in conds:
        sq = c.get('sql')
        if not sq or c.get('code') in seen:
            continue
        seen.add(c.get('code'))
        if sq.get('id'):
            links.append(sql_link(sq))
        else:
            extra.append(f'{sq["op"]} linha {sq["line"]}: {_snip(sq["text"], 80)}')
    return links, extra


def _table_graph(t, tv, off=frozenset(), sqltxt=None):
    """Rastreio do dado, uma caixa por campo. Gravação (INSERT/UPDATE/DELETE): origem -> cada campo por onde o valor passa
    (MOVE, SET, cálculo, CALL/LINK entre programas) -> TABELA.COLUNA; o valor de cada predicado do WHERE faz o mesmo caminho até TABELA.CAMPO -> WHERE -> comando.
    Consulta (SELECT/FETCH): o valor do WHERE vem do mesmo jeito; a volta sai do comando -> TABELA.COLUNA -> campo que recebe -> campos por onde passa -> destino.
    Transformação (COMPUTE, ADD, SUBTRACT, MULTIPLY, DIVIDE, STRING, UNSTRING, INSPECT) vira uma caixa própria entre os campos que entram e o campo que sai.
    Cada ligação guarda os comandos que a criam (op, programa@linha, texto do comando) e, no campo com mais de uma fonte, a condição que escolhe a fonte."""
    sqltxt = sqltxt or {}
    nodes, edges = {}, {}
    cur_off = [False]

    def node(i, label, group, detail=None):
        nodes.setdefault(i, {'id': i, 'label': label, 'group': group, 'detail': detail or label, 'inactive': cur_off[0]})
        return i

    def ligar(a, b, cmd=None):
        if a == b:
            return
        lst = edges.setdefault((a, b), [])
        if cmd and cmd not in lst:
            lst.append(cmd)
    tshort = _short(t)

    def campo(name):
        name = str(name)
        if ' · ' in name:
            return node('N:' + name, _field_label(name), 'campo do programa', name)
        return node('N:' + name, _field_label(name), 'coluna de tabela', name)

    def onde(o):
        st = o['steps'][0] if o.get('steps') else None
        return f' · atribuído em {st["program"]}@{st["line"]} ({st["op"] or st["kind"]})' if st and st.get('line') else ''

    def origem(o):
        if o['kind'] == 'valor fixo':
            return node(f'N:{o["name"]}', 'valor: ' + str(o['name']), 'origem: valor fixo', str(o['name']) + onde(o))
        return node('N:' + str(o['name']), _field_label(o['name']), 'origem: ' + o['kind'], str(o['name']) + onde(o))

    def cmd_step(st):
        return {'op': st['op'] or st['kind'], 'at': f'{st["program"]}@{st["line"]}' if st.get('line') else str(st['program']), 'text': st.get('text') or '', 'line': st.get('line')}

    def cmd_sql(r, op=None, text=None):
        return {'op': op or r['statement'], 'at': f'{r["program"]}@{r["line"]}', 'text': text if text is not None else sqltxt.get(r['id'], ''), 'line': r['line']}

    alt = defaultdict(dict)

    def trilha(cur, steps):
        for st in steps:
            c = cmd_step(st)
            a = campo(st['from'])
            ligar(cur, a)
            b = campo(st['to'])
            if a != b:
                if st['op'] in TRANSFORM_OPS:
                    xn = node(f'X:{st["program"]}@{st["line"]}:{st["op"]}:{st["to"]}', f'{st["op"]} · {st["program"]}@{st["line"]}', 'transformação', st.get('text') or st['op'])
                    ligar(a, xn, c)
                    ligar(xn, b, c)
                    src = xn
                else:
                    ligar(a, b, c)
                    src = a
                alt[b].setdefault((src, st.get('line')), st.get('when_conds') or [])
            cur = b
        return cur

    def destino(d):
        if d['kind'] == 'chave de consulta':
            return node(f'D:{d["name"]}', 'chave de consulta: ' + _short(d['name']), 'destino: chave de consulta', d['name'])
        if d['kind'] == 'gravação':
            return node(f'N:{d["name"]}', _field_label(d['name']), 'destino: gravação', d['name'])
        if d['kind'] == 'envio':
            return node(f'D:{d["name"]}', 'envio a ' + _field_label(d['name']), 'destino: envio', d['name'])
        return campo(d['name'])

    def cmd_dest(d):
        return {'op': d.get('op') or d['kind'], 'at': f'{d["program"]}@{d["line"]}' if d.get('line') else str(d.get('program') or ''), 'text': d.get('text') or '', 'line': d.get('line')}

    def where(r, sn):
        if not r.get('where'):
            return
        wn = node(f'W:{r["id"]}', 'WHERE', 'condição SQL (WHERE)', r['id'])
        ligar(wn, sn, cmd_sql(r))
        for i, w in enumerate(r['where']):
            tab = (_short(w['table']) + '.') if w.get('table') else ''
            pred = ' '.join(x for x in (f'{tab}{w["field"]}', w['op'], w.get('value') or '') if x)
            fn = node(f'F:{r["id"]}:{i}', pred, 'campo do WHERE', f'{r["program"]}@{r["line"]}:{pred}')
            cw = cmd_sql(r, 'WHERE', pred)
            ligar(fn, wn, cw)
            if w.get('value_kind') == 'coluna' and w.get('value_table'):
                other = node(f'N:{w["value_table"]}.{w["value_field"]}', f'{_short(w["value_table"])}.{w["value_field"]}', 'coluna de tabela (ligação entre tabelas)', f'{w["value_table"]}.{w["value_field"]}')
                ligar(other, fn, cmd_sql(r, 'JUNÇÃO', pred))
            for o in w['origins']:
                ligar(trilha(origem(o), o['steps']), fn, cw)

    def comando(r):
        return node('S:' + r['id'], f'{r["statement"]} {tshort} · {r["program"]}@{r["line"]}', 'comando SQL', f'{r["program"]}@{r["line"]}:{t}')
    for r in tv['writes']:
        cur_off[0] = r['id'] in off
        sn = comando(r)
        where(r, sn)
        for c in r['columns']:
            cn = node(f'C:{r["id"]}:{c["column"]}', f'{tshort}.{c["column"]}', f'coluna gravada ({r["statement"]})', f'{t}.{c["column"]} · {r["id"]}')
            ligar(cn, sn, cmd_sql(r))
            for o in c['origins']:
                ligar(trilha(origem(o), o['steps']), cn, cmd_sql(r, text=f'{c["column"]} = {c["value"]}'))
    for r in tv['reads']:
        cur_off[0] = r['id'] in off
        sn = comando(r)
        where(r, sn)
        for c in r['returns']:
            cn = node(f'C:{r["id"]}:{c["column"]}', f'{tshort}.{c["column"]}', f'coluna lida ({r["statement"]})', f'{t}.{c["column"]} · {r["id"]}')
            ligar(sn, cn, cmd_sql(r))
            for d in c['destinations']:
                ligar(trilha(cn, d['steps']), destino(d), cmd_dest(d))
    cond = {}
    for b, alts in alt.items():
        if len({a for a, _ln in alts}) < 2 and len(alts) < 2:
            continue
        sets = {k: {(c['code'], c['result']) for c in cs} for k, cs in alts.items()}
        common = set.intersection(*sets.values()) if sets else set()
        for key, cs in alts.items():
            outros = [o for k2, o in alts.items() if k2 != key]
            # decisão que separa esta fonte das outras: o mesmo código com resultado oposto; sem ela, a última decisão própria deste caminho
            dif = [c for c in cs if any(x['code'] == c['code'] and x['result'] != c['result'] for o in outros for x in o)]
            if not dif:
                prop = [c for c in cs if (c['code'], c['result']) not in common]
                dif = prop[-1:]
            txt = []
            for c in dif:
                x = _cond_text(c)
                if x not in txt:
                    txt.append(x)
            links, extra = sql_links(dif)
            if txt:
                cond[(key[0], b, key[1])] = (' e '.join(txt) + ''.join(f' · {e}' for e in extra), links)
    out = []
    for (a, b), cmds in sorted(edges.items()):
        cs = []
        for c in cmds:
            c = dict(c)
            hit = cond.get((a, b, c.get('line')))
            if hit:
                c['cond'], c['cond_links'] = hit[0], hit[1]
            cs.append({k: v for k, v in c.items() if k != 'line' or True})
        out.append({'from': a, 'to': b, **({'label': ', '.join(sorted({c['op'] for c in cs}))} if cs else {}), **({'cmds': cs} if cs else {})})
    return list(nodes.values()), out


NONE_ORIGIN = {'kind': '-', 'name': '', 'steps': []}


def m_lineage(r, ctx):
    lin = r['lineage']
    fl = r['programs']
    tabs = lin['tables']
    import report_maps as mp
    dyn = mp.dynamic(ctx)
    seen_tabs = mp.scenario_tables_seen(ctx) if dyn else {}

    def cmd_ran(x):
        ls = {x['line']} | {a['line'] for a in x.get('associated', [])}
        return bool(ls & set(dyn['sql_lines'].get(x['program'], ())))

    def ran_ids(v):
        if not dyn:
            return set()
        return {x['id'] for x in v['sql'] if cmd_ran(x)} | {x['id'] for x in v['writes'] + v['reads'] if cmd_ran(x)}

    def reached(t, v):
        return (not dyn) or bool(ran_ids(v)) or bool(mp._match(t, seen_tabs))
    summ = []
    for t, v in tabs.items():
        w, rd = v['writes'], v['reads']
        eps = sorted({e for x in w + rd for e in x['entry_points']})
        row = (t, len(w), ', '.join(sorted({x['program'] for x in w})), len(rd), ', '.join(sorted({x['program'] for x in rd})), ', '.join(eps))
        if dyn:
            nran = len(ran_ids(v))
            row += ('sim' if nran else ('só pelos dados do cenário' if reached(t, v) else 'NÃO ALCANÇADA'), nran)
        summ.append(row)
    summ_cols = ['Tabela', 'Comandos que gravam', 'Programas que gravam', 'Comandos que consultam', 'Programas que consultam', 'Entry points'] + (['Alcançada pela execução dinâmica', 'Comandos executados'] if dyn else [])
    sections = [S('resumo', 'Resumo por tabela', [T('Quem grava e quem consulta cada tabela', summ_cols, summ)],
                  'Só as tabelas com comando SQL no código. Cada comando tem um id (programa@linha:tabela) usado abaixo e nas regras.')]
    nw = nr = 0
    sqlcount = {}
    for t, v in tabs.items():
        blocks = []
        for pg in sorted({x['program'] for x in v['writes'] + v['reads']}):
            sub = {'writes': [x for x in v['writes'] if x['program'] == pg], 'reads': [x for x in v['reads'] if x['program'] == pg]}
            off = {x['id'] for x in sub['writes'] + sub['reads'] if dyn and not cmd_ran(x)}
            if dyn and not reached(t, v):
                off = {x['id'] for x in sub['writes'] + sub['reads']}
            sqltxt = {}
            for q in v['sql']:
                sqltxt.setdefault(q['id'], q['sql'])
                for a in q['associated']:
                    sqltxt.setdefault(a['id'], q['sql'])
            nodes, edges = _table_graph(t, sub, off, sqltxt)
            if dyn and not reached(t, v):
                for n in nodes:
                    n['inactive'] = True
            blocks.append({**G(f'Fluxo de dados — {_short(t)} no programa {pg}' + (' [NÃO ALCANÇADA pela execução dinâmica]' if dyn and not reached(t, v) else ''), nodes, edges),
                           **({'inactive_label': 'cinza tracejado = comando (e seus campos) que nenhum cenário executou'} if dyn else {}),
                           'note': f'Só os comandos de {pg} sobre {_short(t)}. Rastreio do dado, uma caixa por campo, sem condições de decisão (elas estão nas tabelas abaixo). Gravação: origem → campos por onde o valor passa → TABELA.COLUNA. WHERE: origem → campos por onde passa → TABELA.CAMPO → WHERE → comando. Consulta: comando → TABELA.COLUNA → campo que recebe → campos por onde passa → destino (gravação, chave de outra consulta, saída do programa). O caminho pelos programas e as condições estão nas tabelas abaixo; as áreas entre programas estão no relatório de dependências.'})
        wr, ky, rdr, rt = [], [], [], []
        for x in v['writes']:
            cond = _paths_cell(x['conditions'])
            for c in x['columns']:
                for o in c['origins'] or [NONE_ORIGIN]:
                    wr.append((x['id'], x['statement'], x['program'], x['line'], f'{_short(t)}.{c["column"]}', c['value'], _origin_text(o), _origin_status(o), o.get('when', ''), _chain_text(o['steps']), c['flow'], cond, ', '.join(x['entry_points'])))
            for k in x['keys']:
                for o in k['origins'] or [NONE_ORIGIN]:
                    ky.append((x['id'], x['statement'], k['field'], _origin_text(o), _origin_status(o), o.get('when', ''), _chain_text(o['steps']), k['flow'], cond))
            nw += 1
        for x in v['reads']:
            cond = _paths_cell(x['conditions'])
            rdr.append((x['id'], x['statement'] + (f' (cursor {x["cursor"]})' if x['cursor'] else ''), x['program'], x['line'], cond, ', '.join(x['entry_points']),
                        ', '.join(k['field'] for k in x['keys']) or '(sem chave)'))
            for k in x['keys']:
                for o in k['origins'] or [NONE_ORIGIN]:
                    ky.append((x['id'], x['statement'], k['field'], _origin_text(o), _origin_status(o), o.get('when', ''), _chain_text(o['steps']), k['flow'], cond))
            for c in x['returns']:
                for d in c['destinations'] or [{'kind': '(sem destino identificado)', 'name': '', 'program': '', 'line': '', 'steps': [], 'flow': ''}]:
                    rt.append((x['id'], f'{_short(t)}.{c["column"]}', c['host'], c.get('use', ''), d['kind'], d['name'], d['program'], d['line'], _chain_text(d['steps']), c['flow']))
            nr += 1
        if wr:
            blocks.append(T(f'Gravações em {_short(t)}: valor de cada coluna e origem', ['Comando', 'Operação', 'Programa', 'Linha', 'Coluna', 'Valor gravado', 'Origem', 'Origem esperada ou não rastreada', 'Vale quando', 'Cadeia até a coluna', 'Fluxo',
                                                                                           'Condições (decisão → resultado)', 'Entry points'], wr))
        srows = _sql_rows(t, v, dyn, cmd_ran)
        if srows:
            blocks.append(T(f'Comandos SQL sobre {_short(t)}: SELECT, INSERT, UPDATE, DELETE e comandos de cursor (DECLARE, OPEN, FETCH, CLOSE)', ['Id', 'Comando', 'Cursor', 'Programa', 'Linha', 'Parágrafo', 'SQL', 'Entry points'] + (['Execução dinâmica'] if dyn else []),
                            [r if dyn else r[:-1] for r in srows], ids=['sql-' + r[0] for r in srows]))
        sqlcount[t] = Counter(r[1] for r in srows)
        wh = []
        for x in v['writes'] + v['reads']:
            for w in x.get('where', []):
                for o in w['origins'] or [NONE_ORIGIN]:
                    wh.append((f'{x["program"]}@{x["line"]}:' + ' '.join(q for q in ((_short(w['table']) + '.' if w.get('table') else '') + w['field'], w['op'], w['value']) if q), x['id'], x['statement'] + (f' (cursor {x["cursor"]})' if x['cursor'] else ''), w['connector'] or '', w['group'], (_short(w['table']) + '.' if w.get('table') else '') + w['field'], w['op'], w['value'], w.get('value_resolved') or w['value'], w.get('role', ''), _origin_text(o), _origin_status(o), o.get('when', ''), _chain_text(o['steps'])))
        if wh:
            blocks.append(T(f'Condições SQL (WHERE) dos comandos sobre {_short(t)}', ['Critério', 'Comando', 'Operação', 'Conector', 'Grupo', 'Coluna', 'Operador', 'Valor', 'Valor com a tabela resolvida', 'Papel do predicado', 'Origem do valor', 'Origem esperada ou não rastreada', 'Vale quando', 'Cadeia até o valor'], wh))
        if ky:
            blocks.append(T(f'Chaves de busca em {_short(t)}: campo e origem', ['Comando', 'Operação', 'Campo da chave', 'Origem', 'Origem esperada ou não rastreada', 'Vale quando', 'Cadeia até a chave', 'Fluxo', 'Condições'], ky))
        if rdr:
            blocks.append(T(f'Consultas a {_short(t)} e o caminho de decisão que leva a elas', ['Comando', 'Operação', 'Programa', 'Linha', 'Condições (decisão → resultado)', 'Entry points', 'Chaves'], rdr))
        if rt:
            blocks.append(T(f'Colunas retornadas por {_short(t)} e para onde vão', ['Comando', 'Coluna', 'Campo que recebe', 'Uso no código', 'Tipo de destino', 'Destino', 'Programa', 'Linha', 'Cadeia até o destino', 'Fluxo'], rt))
        sections.append(S('tab-' + _short(t), f'Tabela {_short(t)}', blocks, f'{len(v["writes"])} comando(s) que gravam e {len(v["reads"])} que consultam. {t}'))
    order = ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'DECLARE CURSOR (SELECT)', 'OPEN', 'FETCH', 'CLOSE']
    kinds = [k for k in order if any(k in c for c in sqlcount.values())] + sorted({k for c in sqlcount.values() for k in c} - set(order))
    sections[0]['blocks'].append(T('Comandos SQL por tabela e tipo (todos os SELECT, INSERT, UPDATE, DELETE e comandos de cursor)', ['Tabela'] + kinds + ['Total'],
                                   [(t,) + tuple(c.get(k, 0) for k in kinds) + (sum(c.values()),) for t, c in sqlcount.items()]))
    sm = lin['summary']
    return model('Fase 4 — Linhagem de dados', 'Para cada tabela: o que grava e o que consulta, com o mapeamento coluna a coluna, a origem de cada dado atravessando os programas, as condições que levam ao comando e o destino dos dados lidos.',
                 [card('tabelas', sm['tables']), card('comandos SQL', sm['sql']), card('comandos que gravam', nw), card('comandos que consultam', nr), card('programas', len(fl))] + ([card('tabelas não alcançadas', sum(1 for t, v in tabs.items() if not reached(t, v)))] if dyn else []), sections)


# ----------------------------------------------------------------------------- 05 regras determinísticas
KIND_ORDER = ['validação', 'tratamento de erro', 'retorno de sucesso', 'consulta de dados', 'alteração de estado', 'roteamento', 'derivação']
KIND_DESC = {'validação': 'A condição só depende de dado de entrada, o caminho atribui valor fixo de retorno e encerra o programa.',
             'tratamento de erro': 'A condição testa status de execução (SQLCODE, EIBRESP...) ou dado lido/calculado e o caminho atribui valor fixo de retorno (com ou sem encerrar).',
             'retorno de sucesso': 'O caminho atribui valor fixo de retorno e as decisões de status de execução (SQLCODE, EIBRESP...) seguem o ramo de sucesso, ou só restam validações já superadas (o ramo oposto encerra o programa): é a resposta de quando a operação deu certo, não tratamento de falha.',
             'consulta de dados': 'O caminho consulta tabela (SELECT ou FETCH de cursor): colunas devolvidas, condições do WHERE e as decisões que levam à consulta.',
             'alteração de estado': 'O caminho insere, altera ou exclui em tabela (ou grava arquivo): colunas gravadas com o valor, condições do WHERE e as decisões que levam ao comando.',
             'roteamento': 'A condição decide a chamada de outro programa; não há gravação nem retorno fixo.',
             'derivação': 'A condição só depende de dado de entrada e o caminho atribui valor fixo a campo de saída, sem encerrar o programa.'}


SUBTYPE_ORDER = ['validação de entrada', 'exceção de negócio', 'exceção de negócio com pré-condição', 'condição sobre campo calculado', 'valor padrão por coluna nula', 'retorno de sucesso', 'falha técnica de execução']
SUBTYPE_DESC = {'validação de entrada': 'todos os campos testados chegam de fora do programa (entrada) e o caminho atribui valor fixo de retorno',
                'exceção de negócio': 'a condição depende do resultado de um comando de dados (coluna lida de tabela ou status específico de SQL/CICS) e não testa dado de entrada',
                'exceção de negócio com pré-condição': 'a condição testa ao mesmo tempo dado de entrada e resultado de comando de dados',
                'condição sobre campo calculado': 'a condição depende só de campos calculados no próprio programa (nem entrada nem resultado direto de comando de dados)',
                'valor padrão por coluna nula': 'a condição testa o indicador de nulo de uma coluna lida e o caminho atribui valor fixo',
                'retorno de sucesso': 'as decisões de status seguem o ramo de sucesso e as demais só são validações já superadas',
                'falha técnica de execução': 'o caminho segue o ramo de falha de uma decisão genérica de status de execução (plataforma)'}


def name_parts(names):
    """Componentes de cada nome (campo, tabela, coluna) separados por hífen ou sublinhado, sem interpretar: `A-B_C` -> `A-B_C = A | B | C`."""
    seen, out = set(), []
    for n in names:
        n = str(n).split(' (')[0].split('.')[-1].strip()
        if n and n not in seen and ('-' in n or '_' in n):
            seen.add(n)
            out.append(f'{n} = ' + ' | '.join(x for x in n.replace('_', '-').split('-') if x))
    return '; '.join(out)


def _where_text(e):
    w = e.get('where') or []
    if not w:
        return ''
    return ' WHERE ' + ' '.join((x['connector'] + ' ' if x['connector'] else '') + ((x['table'].split('.')[-1] + '.') if x.get('table') else '') + x['field'] + f' {x["op"]} {x["value"]}'.rstrip() for x in w)


def rule_effect_text(e):
    if e['nature'] == 'consulta':
        cols = ', '.join(f'{c["column"]}→{c["host"]}' for c in e['columns'])
        lp = e.get('loop')
        return (f'{e["lineage_id"]} {e["op"]} {e["target"]}' + (f' (cursor {e["cursor"]})' if e.get('cursor') else '') + f' retorna {cols}' + _where_text(e) + f' (linha {e["line"]})'
                + (f' [repete: {lp["perform"]} (linha {lp["line"]})]' if lp else ''))
    if e['nature'] == 'gravação' and e.get('columns') is not None and e.get('lineage_id'):
        cols = ', '.join(f'{c["column"]}={c["value"]}' for c in e['columns'])
        return f'{e["lineage_id"]} {e["op"]} {e["target"]}' + (f' grava {cols}' if cols else '') + _where_text(e) + f' (linha {e["line"]})'
    if e['nature'] == 'gravação':
        return f'{e["flow"]} {e["op"]} {e["target"]}' + (f' = {e["value"]}' if e['value'] and e['op'] != 'DELETE' else '') + f' (linha {e["line"]})'
    if e['nature'] == 'chamada':
        return f'{e["flow"]} {e["op"]} {e["target"]} envia {e["value"]} (linha {e["line"]})'
    return f'{e["flow"]} {e["target"]} = {e["value"]}' + (f' [{e["value_name"]}]' if e.get('value_name') else '') + f' (linha {e["line"]})'


def _rule_cond_cell(x, sqltxt):
    """Condições da regra; a que testa status (SQLCODE...) leva o link para o SQL de que testa o status (lineage_id da condição)."""
    seen, links, extra = set(), [], []
    for f in x['condition_fields']:
        if f['role'] != 'status' or f['decision'] in seen:
            continue
        seen.add(f['decision'])
        if f.get('lineage_id'):
            links.append(sql_link({'id': f['lineage_id'], 'text': sqltxt.get(f['lineage_id'], '')}))
        else:
            extra.append(f['detail'])
    return with_links(rule_conditions_text(x) + ''.join(f' · {e}' for e in extra), links)


def rule_conditions_text(x):
    return ' E '.join(f'{x["program"]}:{c["code"]} {c["condition"]} → {c["result"]} (linha {c["line"]})' + (' [técnica]' if c.get('technical') else '') + (f' (critério de infraestrutura retirado: {"; ".join(c["removed_criteria"])})' if c.get('removed_criteria') else '') for c in x['conditions']) or '(sempre)'


ESCOPO_FORA = 'fora da abrangência'


def m_rules(r, ctx):
    from table_roles import reach_by_root
    dr = r['data_rules']
    allr = [x for d in dr.values() for x in d['rules']]
    kinds = Counter(x['kind'] for x in allr)
    edges = [{'caller': c['caller'], 'target': c.get('target')} for c in ctx['static'].get('call_graph', [])]
    roots = reach_by_root(edges, set(dr))
    lin = (ctx['phase'].get('04-data-lineage') or {}).get('lineage', {})
    sqlid = defaultdict(list)
    for t, v in lin.get('tables', {}).items():
        for x in v['writes'] + v['reads']:
            sqlid[(x['program'], x['line'])].append(x['id'])
    sqltxt = {}
    for t_, v_ in lin.get('tables', {}).items():
        for q in v_['sql']:
            sqltxt.setdefault(q['id'], q['sql'])
            for a in q['associated']:
                sqltxt.setdefault(a['id'], q['sql'])
    ordem = [k for k in KIND_ORDER if kinds.get(k)]   # mesma ordem (e portanto mesma cor) de cada tipo nos dois gráficos
    per = [{'label': p, 'parts': [{'name': k, 'value': v} for k, v in Counter(x['kind'] for x in d['rules']).items()]} for p, d in dr.items() if d['rules']]
    per_ep = []
    for ep, seen in sorted(roots.items()):
        c = Counter(x['kind'] for p in seen if p in dr for x in dr[p]['rules'])
        if c:
            per_ep.append({'label': ep, 'parts': [{'name': k, 'value': c[k]} for k in KIND_ORDER if c.get(k)]})
    sections = [S('tipos', 'Tipos de regra', [T('Como cada tipo é decidido', ['Tipo', 'Critério', 'Regras'], [(k, KIND_DESC[k], kinds.get(k, 0)) for k in KIND_ORDER]),
                                              {**B('Regras por tipo e programa', per), 'names': ordem},
                                              {**B('Regras por entry point (um programa entra em todos os entry points que o alcançam)', per_ep), 'names': ordem}],
                  'Regra determinística = caminho de decisão + efeitos de negócio (gravação, chamada, valor fixo de retorno). Extraída do código por script, sem interpretação de negócio; serve de base para virar regra de negócio com ajuda de IA.')]
    from report_maps import marks
    dms = (ctx['phase'].get('05-decision-map') or {}).get('decision_map', {})
    for p, d in dr.items():
        if not d['rules']:
            continue
        rows = []
        mk = marks(dms[p], ctx.get('rt')) if p in dms else None
        for x in d['rules']:
            if mk is not None and x['scope']['scope'] == 'negócio':   # decisão marcada "não executado" no decision-map: nenhum cenário alcança a regra
                nao = [c for c in x['references'] if c in mk and not mk[c]['ok'] and mk[c]['reason'] != 'MOCKADO_NO_ENTRY_POINT']
                if not nao:   # as decisões foram alcançadas, mas a regra só vale se o resultado dela (Sim/Não) foi tomado por algum cenário
                    nao = [c['code'] + ' → ' + c['result'] for c in x['conditions'] if c['code'] in mk and mk[c['code']].get('ramos') and not mk[c['code']]['ramos'].get(c['result'], True)]
                if nao:
                    x['scope'] = {**x['scope'], 'scope': ESCOPO_FORA, 'reason': 'fora da abrangência: nenhum cenário de execução dinâmica alcança ' + ', '.join(f'{p}:{c}' for c in nao[:4]) + (f' e mais {len(nao) - 4}' if len(nao) > 4 else '') + ' (marcada "não executado" no decision-map)'}
            eps = ', '.join(ep for ep, seen in sorted(roots.items()) if p in seen)
            sql = sorted({e['lineage_id'] for e in x['effects'] if e.get('lineage_id')} | {i for e in x['effects'] if e['nature'] == 'gravação' for i in sqlid.get((p, e['line']), [])} | {q['lineage_id'] for q in x['reads'] if q.get('lineage_id')})
            rd = '; '.join(f'{q["table"]}' + (f'.{q["column"]}' if q.get('column') else '') + f' ({q["via"]}, {q["lineage_id"]})' for q in x['reads'])
            rows.append((x['code'], ', '.join(f'{p}:{c}' for c in x['references']) or '—', x['kind'], x.get('subtype', ''), x['scope']['scope'], x['scope']['reason'], x['basis'], '; '.join(x['signals']), 'sim' if x['ends_flow'] else 'não', _rule_cond_cell(x, sqltxt),
                         '; '.join(f'{p}:{c["decision"]} {c["field"]}: {c["role"]} — {c["detail"]}' + (f' · papel final: {c["final_role"]} ({"; ".join(c["origin_names"])})' if c.get('final_role') else '') for c in x['condition_fields']),
                         '; '.join(rule_effect_text(e) for e in x['effects']), ', '.join(x['tables']), ', '.join(x['called']), rd, ', '.join(sql), name_parts([c['field'] for c in x['condition_fields']] + [e['target'] for e in x['effects']] + [t for t in x['tables'] + x['tables_read']] + [c['column'] for e in x['effects'] for c in (e.get('columns') or [])]), eps))
        sections.append(S('reg-' + p, f'Regras — {p}', [
            T(f'Regras de {p}', ['Regra', 'Decisões', 'Tipo', 'Subtipo', 'Escopo', 'Motivo do escopo', 'Critério', 'Sinais', 'Encerra', 'Condições (decisão → resultado)', 'Campos testados: papel e origem', 'Efeitos de negócio (fluxo, natureza)', 'Tabelas gravadas',
                                 'Programas chamados', 'Consultas que alimentam a condição', 'Comandos SQL na linhagem', 'Componentes dos nomes', 'Entry points'], rows)],
            f'Saídas do programa: {", ".join(d["outputs"]) or "-"}. Entradas: {", ".join(d["inputs"]) or "-"}.'))
    return model('Fase 6 — Regras determinísticas', 'Cada regra = caminho de decisão + efeitos de negócio, com o tipo e o critério que o decidiu, o papel e a origem dos campos testados, as consultas que alimentam a condição e as ligações ao decision-map (Dnnn) e à linhagem (Fnnnn e comandos SQL).',
                 [card('regras', len(allr)), card('de negócio', sum(1 for x in allr if x['scope']['scope'] == 'negócio')), card('de infraestrutura', sum(1 for x in allr if x['scope']['scope'] == 'infraestrutura')), card('mecanismos implícitos', sum(1 for x in allr if x['scope']['scope'] == 'mecanismos implícitos'))] + [card(k, kinds.get(k, 0)) for k in KIND_ORDER] + [card('programas com regras', len(per))], sections)
