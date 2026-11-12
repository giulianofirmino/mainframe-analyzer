"""Experimento (análise separada): relação completa entre programas, comandos SQL e tabelas, a partir da fase 1 (dependências) e do modelo estático.

Um comando SQL é uma instrução do fonte (EXEC SQL) ou um cursor inteiro (DECLARE + OPEN/FETCH/CLOSE são um comando só); o id é programa@linha (linha do comando ou do DECLARE).
Execução dinâmica: o comando foi executado se alguma das suas linhas está entre as linhas de SQL executadas pelos cenários; a tabela foi usada se algum comando executado a acessa
ou se os cenários a preenchem; o programa foi chamado se algum cenário o executou (ou o mockou). O que não foi executado fica em cinza tracejado e o checkbox da seção o esconde.
Só tokens e resultados estruturados das fases anteriores; nenhum nome fixo; gerado por script."""
from collections import defaultdict

from report_model import T, S, card, model
import report_resumo as rs

GRAV = {'INSERT', 'UPDATE', 'DELETE', 'MERGE'}
TG = 'Mostrar o que nenhum cenário executou (em cinza)'


def _curta(t):
    return str(t).split('.')[-1]


def comandos(ps, dyn, fontes=None):
    """Comandos SQL de todos os programas, estáticos e dinâmicos: id, linhas, operação, tabelas, natureza, SQL e se foi executado.
    Cursor não é item à parte: vale o comando SQL do DECLARE (as linhas de OPEN, FETCH e CLOSE entram só para saber se foi executado).
    Comando dinâmico (PREPARE/EXECUTE): o SQL é montado rastreando os valores atribuídos ao campo que o carrega (dynamic_sql). Só entram comandos que acessam tabela."""
    import re
    import dynamic_sql
    from dependency_map import declared_cursors
    fontes = fontes or {}
    out = []
    for p, d in sorted(ps.items()):
        por_linha = defaultdict(list)
        for a in d['table_access']:
            por_linha[a['line']].append(a)
        texto = fontes.get(p)
        decl = declared_cursors(texto) if texto else {}
        din = dynamic_sql.analisar(texto) if texto and re.search(r'\b(PREPARE|EXECUTE)\b', texto, re.I) else []
        linhas_din = {l for x in din for l in x['linhas']}
        em_cursor = set()
        for c in d['cursors']:
            linhas = sorted({c['declared_line']} | {o['line'] for o in c['operations']})
            em_cursor |= set(linhas)
            sql = (decl.get(c['cursor'].upper()) or {}).get('sql', '')
            op = (re.match(r'\s*([A-Za-z]+)', sql).group(1).upper() if sql else 'SELECT')
            out.append({'id': f'{p}@{c["declared_line"]}', 'programa': p, 'linhas': linhas, 'operacao': op, 'tabelas': sorted(c['tables']), 'natureza': 'lê', 'sql': sql, 'dinamico': False, 'montagens': []})
        vistos = set()
        for s in d['sql_commands']:
            if s['line'] in em_cursor or s['line'] in vistos or s['line'] in linhas_din:
                continue
            vistos.add(s['line'])
            tabs = sorted({a['table'] for a in por_linha.get(s['line'], [])})
            if tabs:   # SET de registrador, INCLUDE, COMMIT etc. não acessam tabela
                out.append({'id': f'{p}@{s["line"]}', 'programa': p, 'linhas': [s['line']], 'operacao': s['operation'], 'tabelas': tabs,
                            'natureza': 'grava' if s['operation'] in GRAV else 'lê', 'sql': s.get('sql', ''), 'dinamico': False, 'montagens': []})
        for x in din:
            out.append({'id': f'{p}@{x["linha"]}', 'programa': p, 'linhas': x['linhas'], 'operacao': x['operacao'], 'tabelas': x['tabelas'], 'natureza': 'grava' if x['operacao'] in GRAV else 'lê',
                        'sql': ' || '.join(x['montagens']), 'dinamico': True, 'montagens': x['montagens'], 'campo': x['campo']})
    for c in out:
        c['executado'] = dyn is None or bool(set(c['linhas']) & set(dyn['sql_lines'].get(c['programa'], ())))
    return out


def _cor_cmd(c):
    return rs.COR_GRAVA if c['natureza'] == 'grava' else rs.COR_LEITURA


def _rot(c):
    return f'{c["operacao"]} ' + (', '.join(_curta(t) for t in c['tabelas']) or '(tabela não identificada)')


def _sub(c):
    return ('SQL dinâmico · ' if c['dinamico'] else '') + 'linha ' + c['id'].split('@')[1]


def _detalhe(c):
    if c['dinamico']:
        return f'{c["id"]} — SQL dinâmico montado a partir de {c.get("campo", "")}: ' + (' || '.join(c['montagens']) or '(não foi possível montar o texto)')
    return f'{c["id"]} ({c["natureza"]}): {c["sql"]}'


def m_dependencias_sql(deps, ctx):
    """Modelo de visão do experimento. `deps` é o resultado da fase 1 ({'programs': ...})."""
    import report_maps as mp
    ps = deps['programs']
    sm = ctx['static']
    dyn = mp.dynamic(ctx)
    seen = mp.scenario_tables_seen(ctx) if dyn else {}
    cls = {p['program']: p['classification'] for p in ctx['phase'].get('00-program-classification', {}).get('programs', [])}
    cmds = comandos(ps, dyn, ctx.get('fontes'))
    prog_ok = lambda p: dyn is None or p in dyn['real'] or p in dyn['mock']
    tab_ok = defaultdict(bool)
    for c in cmds:
        for t in c['tabelas']:
            tab_ok[t] |= c['executado']
    tab_usada = lambda t: dyn is None or tab_ok[t] or bool(mp._match(t, seen))
    chamadas, vistos = [], set()
    for c in sm.get('call_graph', []):
        if c.get('target'):
            k = (c['caller'], c['target'], c['mechanism'], c['line'])
            if k not in vistos:
                vistos.add(k)
                chamadas.append(c)
    por_prog = defaultdict(list)
    for c in cmds:
        por_prog[c['programa']].append(c)
    chamadas = [c for c in chamadas if c['caller'] in por_prog and c['target'] in por_prog]   # só programas que têm comando SQL (estático ou dinâmico)

    # --- diagrama geral: programa -> comando SQL -> tabela
    nos, ar, tn = [], [], {}
    for p in sorted(por_prog):
        nos.append({'id': 'p-' + p, 'col': 0, 'label': p, 'sub': cls.get(p, '') + ('' if prog_ok(p) else ' · não chamado'), 'detail': f'programa {p} ({cls.get(p, "")})', 'cor': rs._cor_prog(cls, p),
                    'inactive': not prog_ok(p)})
    for c in cmds:
        nos.append({'id': 'q-' + c['id'], 'col': 1, 'label': _rot(c), 'sub': _sub(c), 'sub2': '' if c['executado'] else 'NÃO EXECUTADO',
                    'detail': _detalhe(c), 'cor': _cor_cmd(c), 'inactive': not c['executado']})
        ar.append({'from': 'p-' + c['programa'], 'to': 'q-' + c['id']})
        for t in c['tabelas']:
            tn.setdefault(t, {'id': 't-' + t, 'col': 2, 'label': _curta(t), 'sub': 'tabela' + ('' if tab_usada(t) else ' · não usada'), 'detail': t, 'cor': rs.NEUTRA, 'inactive': not tab_usada(t)})
            ar.append({'from': 'q-' + c['id'], 'to': 't-' + t})
    g_geral = rs._grafo('Programas, comandos SQL e tabelas', ['Programa', 'Comando SQL', 'Tabela'], nos + list(tn.values()), ar,
                        'Só aparecem programas com comando SQL (estático ou dinâmico). Cor do programa = classe (azul coordenador, verde funcional, laranja corporativo, vermelho infraestrutura). Comando SQL: verde-água lê, roxo grava (cursor = o SQL do DECLARE; dinâmico = o SQL montado). '
                        'Cinza tracejado: nenhum cenário executou o comando, usou a tabela ou chamou o programa. A tabela com o mesmo conteúdo está em "Comandos SQL".', nw=250)
    g_geral['toggle_label'] = TG

    # --- um diagrama por programa: quem o chama, quem ele chama, comandos SQL e tabelas
    graf_prog = []
    for p in sorted(por_prog):
        entra = [c for c in chamadas if c['target'] == p]
        sai = [c for c in chamadas if c['caller'] == p]
        nos_p = [{'id': 'p', 'col': 1, 'label': p, 'sub': cls.get(p, 'externo') + ('' if prog_ok(p) else ' · não chamado'), 'detail': f'programa {p}', 'cor': rs._cor_prog(cls, p)}]
        ar_p, tabs = [], {}
        for c in entra:
            i = 'a-' + c['caller']
            if not any(n['id'] == i for n in nos_p):
                nos_p.append({'id': i, 'col': 0, 'label': c['caller'], 'sub': cls.get(c['caller'], 'externo'), 'detail': f'{c["caller"]} chama {p} ({c["mechanism"]}, linha {c["line"]})',
                              'cor': rs._cor_prog(cls, c['caller']), 'inactive': not prog_ok(c['caller'])})
                ar_p.append({'from': i, 'to': 'p'})
        for c in sai:
            i = 'b-' + c['target']
            if not any(n['id'] == i for n in nos_p):
                nos_p.append({'id': i, 'col': 2, 'label': c['target'], 'sub': 'chamado · ' + cls.get(c['target'], 'externo'), 'detail': f'{p} chama {c["target"]} ({c["mechanism"]}, linha {c["line"]})',
                              'cor': rs._cor_prog(cls, c['target']), 'inactive': not prog_ok(c['target'])})
                ar_p.append({'from': 'p', 'to': i})
        for c in por_prog.get(p, []):
            i = 'q-' + c['id']
            nos_p.append({'id': i, 'col': 2, 'label': _rot(c), 'sub': _sub(c), 'detail': _detalhe(c), 'cor': _cor_cmd(c), 'inactive': not c['executado']})
            ar_p.append({'from': 'p', 'to': i})
            for t in c['tabelas']:
                if t not in tabs:
                    tabs[t] = True
                    nos_p.append({'id': 't-' + t, 'col': 3, 'label': _curta(t), 'sub': 'tabela', 'detail': t, 'cor': rs.NEUTRA, 'inactive': not tab_usada(t)})
                ar_p.append({'from': i, 'to': 't-' + t})
        graf_prog.append(rs._grafo(f'{p}: quem chama, quem é chamado, comandos SQL e tabelas', ['Chamado por', 'Programa', 'Chama programa ou executa comando SQL', 'Tabela'], nos_p, ar_p, None, nw=230))
    rs._um_toggle(graf_prog)
    for g in graf_prog:
        g['toggle_label'] = TG

    # --- tabelas
    n_ex = sum(1 for c in cmds if c['executado'])
    rows = [[c['id'], c['programa'], ', '.join(str(x) for x in c['linhas']), c['operacao'], ', '.join(c['tabelas']), c['natureza'], 'dinâmico' if c['dinamico'] else 'estático',
             c['sql'] or '(não foi possível montar o texto)'] + ([('sim' if c['executado'] else 'NÃO')] if dyn is not None else []) for c in cmds]
    cols = ['Id', 'Programa', 'Linhas', 'Operação', 'Tabelas', 'Natureza', 'Tipo', 'Comando SQL (no dinâmico, o texto montado; alternativas separadas por ||)'] + (['Executado'] if dyn is not None else [])
    t_cmd = T('Comandos SQL: programa, comando e tabelas (o mesmo conteúdo do diagrama geral)', cols, rows, ids=['cmd-' + c['id'] for c in cmds],
              descartadas=[not c['executado'] for c in cmds] if dyn is not None else None,
              note='Id = programa@linha. Só entram programas e comandos que acessam tabela. Comando de cursor é o SQL do DECLARE (OPEN, FETCH e CLOSE só entram em "Linhas", para saber se foi executado). '
                   'Comando dinâmico: o texto é montado rastreando os valores atribuídos ao campo que o carrega (MOVE, STRING, valor inicial); campo sem origem literal aparece como <NOME>.')
    tab_rows, tab_desc = [], []
    por_tab = defaultdict(list)
    for c in cmds:
        for t in c['tabelas']:
            por_tab[t].append(c)
    for t in sorted(por_tab):
        cs = por_tab[t]
        ex = [c['id'] for c in cs if c['executado']]
        tab_rows.append([t, ', '.join(sorted({c['programa'] for c in cs})), ', '.join(c['id'] for c in cs), len(cs)]
                        + ([('sim' if ex else ('só pelos dados do cenário' if tab_usada(t) else 'NÃO')), ', '.join(ex)] if dyn is not None else []))
        tab_desc.append(not tab_usada(t))
    t_tab = T('Tabelas e os comandos que as acessam', ['Tabela', 'Programas', 'Comandos', 'Qtd'] + (['Usada na execução', 'Comandos executados'] if dyn is not None else []), tab_rows,
              descartadas=tab_desc if dyn is not None else None)
    cr, cd = [], []
    for c in sorted(chamadas, key=lambda c: (c['caller'], c['line'])):
        cr.append([c['caller'], c['line'], c['mechanism'], c['target'], cls.get(c['target'], 'externo')] + ([('sim' if prog_ok(c['target']) else 'NÃO')] if dyn is not None else []))
        cd.append(not prog_ok(c['target']))
    t_cham = T('Chamadas entre programas', ['Chamador', 'Linha', 'Mecanismo', 'Chamado', 'Classe do chamado'] + (['Chamado na execução'] if dyn is not None else []), cr,
               descartadas=cd if dyn is not None else None)
    secs = [S('leitura', 'Como ler', [], 'Experimento sobre a fase 1: além da relação programa → tabela, mostra o comando SQL que liga os dois (estático ou dinâmico, este com o texto montado) e destaca o que a execução dos cenários não alcançou. '
              'O checkbox da seção alterna entre o diagrama completo e só o executado.'),
            S('geral', 'Programas, comandos SQL e tabelas', [g_geral]),
            S('programas', 'Por programa', graf_prog, 'Um diagrama por programa: quem o chama, quem ele chama, seus comandos SQL e as tabelas.'),
            S('comandos', 'Comandos SQL', [t_cmd]), S('tabelas', 'Tabelas', [t_tab]), S('chamadas', 'Chamadas', [t_cham])]
    cards = [card('programas com SQL', len(por_prog)), card('comandos SQL', len(cmds))] + ([card('comandos executados', f'{n_ex}/{len(cmds)}')] if dyn is not None else []) + [card('tabelas', len(por_tab))] + (
        [card('tabelas usadas', f'{sum(1 for t in por_tab if tab_usada(t))}/{len(por_tab)}')] if dyn is not None else [])
    return model('Experimento — Programas, comandos SQL e tabelas (sobre a fase 1)', 'Relação completa entre programas, comandos SQL e tabelas, com o que a execução dinâmica não alcançou em cinza.', cards, secs)
