#!/usr/bin/env python3
"""Relatório responsibility-segregation (fase 17, evidência determinística + análise por funcionalidade da IA): propriedade dos dados entre funcionalidades, lida ÚNICA E EXCLUSIVAMENTE dos relatórios gerados
(<fase>/ia/report.json das fases 0, 3, 4, 10 sql-mapping, 12 business-flows e 16 domain-model). Mesma entrada → mesma saída, sem IA.

  python3 gerar_responsibility_segregation.py <pasta-da-analise> [pasta-de-saida]   (padrão da saída: a pasta da análise)

Saída: <saida>/17 - responsibility-segregation/human/report.html e <saida>/17 - responsibility-segregation/ia/report.json (o mesmo modelo de visão, com as mesmas informações).
A análise por funcionalidade (chamadas, latência e N+1) usa a interpretação interpretacao-relacao/*.json (prompt 8), validada contra a evidência; opção --interpretacao PASTA.
Estratégia de acesso aos dados: queries de uma tabela e gravações executadas pelos agregados; queries de várias tabelas em Query Legacy dentro de Group Query; os agregados
corporativos chamam os programas corporativos originais por meio de LEGACY, em vez de executar SQL.
Escopo: só as tabelas atingidas pela execução dinâmica (fase 4) já mapeadas no data-schema (fase 3), mais as tabelas dinâmicas do sql-mapping (fase 10).
Conteúdo:
  - a propriedade de cada tabela: PROPRIETÁRIO_EXCLUSIVO (uma só funcionalidade executa INSERT/UPDATE/DELETE/MERGE), COMPARTILHADO (duas ou mais), SOMENTE_LEITURA (nenhuma
    funcionalidade do escopo grava: o dono está fora da análise), e o papel de cada funcionalidade (proprietária, compartilha, apenas lê);
  - os JOINs multi-owner (SELECT sobre duas ou mais tabelas de donos diferentes), com o dono suposto de cada tabela: a funcionalidade que grava ou, sem gravação no escopo,
    o agregado da fase 16 (dono fora da análise);
  - para cada JOIN multi-owner, se fica em um agregado ou se vira Query Legacy (dentro de um Group Query)."""
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import gerar_simulacao as S
import report_model as rm  # noqa: E402
import report_resumo as rs  # noqa: E402
from cores import COR_CLASSE, COR_SQL_GRAVA, COR_SQL_LE  # noqa: E402

AQUI = Path(__file__).resolve().parent
BASE = Path(os.environ['ANALISE_INTERPRETACOES']) if os.environ.get('ANALISE_INTERPRETACOES') else AQUI   # pasta das interpretações (a análise); o pipeline a informa
FASE = '17 - responsibility-segregation'
EXCL, COMP, LEIT = 'PROPRIETÁRIO_EXCLUSIVO', 'COMPARTILHADO', 'SOMENTE_LEITURA'
GRAVA = ('INSERT', 'UPDATE', 'DELETE', 'MERGE')
VEREDITOS = {'sim', 'mitigado', 'nao', 'sem_cursor'}
GRAVIDADES = {'alta', 'média', 'baixa', 'nenhuma'}
CHAVES_RAIZ = {'funcionalidades', 'premissas', 'lacunas'}
COR_VEREDITO = {'sim': '#C62828', 'mitigado': '#EF6C00', 'nao': '#2E7D32', 'sem_cursor': '#546E7A'}
LACO = re.compile(r'(?i)(para cada|\bcada\b|a cada|percorre[mn]? (?:por cursor )?(?:os|as)|itera|repet|enquanto|do anterior|da anterior|um a um|linha a linha|registro a registro)')
NUM_PROIBIDO = re.compile(r'(?i)\b\d+([.,]\d+)?\s*(ms|s|seg|segundos|milissegundos|minutos|registros|linhas|mil)\b')
MAX_COMPOSICOES = 2   # no máximo 2 composições (chamadas) para a query ainda valer como Composition
COR_PASSO_E = {'API_COMPOSITION': '#00695C', 'QUERY_SERVICE': '#1565C0'}
EXPLICA = {
    'SELECT_CURSOR': ('lê', 'SELECT sobre uma tabela que percorre várias linhas por cursor (OPEN, FETCH em laço, CLOSE): lista de resultados, sem limitar a uma linha'),
    'FILTERED_SELECT': ('lê', 'SELECT com WHERE que devolve só as linhas que atendem ao filtro'),
    'DIRECT_SELECT': ('lê', 'SELECT direto, sem filtro adicional, de uma linha ou de uma tabela de referência'),
    'AGGREGATION': ('lê', 'SELECT com função de agregação (COUNT, SUM, MAX, MIN) ou GROUP BY'),
    'SELF_JOIN': ('lê', 'SELECT que junta a tabela com ela mesma'),
    'ANALYTICAL_QUERY': ('lê', 'SELECT analítico (funções de janela, ranking ou acumulados)'),
    'MULTI_TABLE_JOIN': ('lê', 'SELECT que junta duas ou mais tabelas'),
    'DIRECT_INSERT': ('grava', 'INSERT de uma linha'),
    'BATCH_INSERT': ('grava', 'INSERT de várias linhas de uma vez'),
    'UPSERT_PATTERN': ('grava', 'INSERT ou UPDATE conforme a linha já exista (MERGE)'),
    'DIRECT_UPDATE': ('grava', 'UPDATE sem condição seletiva'),
    'CONDITIONAL_UPDATE': ('grava', 'UPDATE com WHERE'),
    'DIRECT_DELETE': ('grava', 'DELETE de linhas'),
    'CASCADE_DELETE': ('grava', 'DELETE em tabela que é o todo de uma associação em cascata do domínio'),
}
COR_DONO = {EXCL: '#2E7D32', COMP: '#C62828', LEIT: '#546E7A'}
SQL_VERBO = re.compile(r'(?is)^\s*(SELECT|WITH|INSERT|UPDATE|DELETE|MERGE|CALL)\b')


def curto(t):
    return str(t).split('.')[-1].strip()


def norm(t):
    return ' '.join(str(t).split())


# ----------------------------------------------------------------------------- análise do texto SQL
def sem_literais(sql):
    return re.sub(r"'[^']*'", "''", norm(sql))


def tabelas_do_sql(sql, conhecidas):
    """Tabelas (na ordem de aparição, com repetição) das cláusulas FROM/JOIN/UPDATE/INTO/DELETE FROM/MERGE INTO do comando."""
    s = sem_literais(sql).upper()
    achadas = []
    nome = r'(?:[A-Z0-9_#@$]+\.)?[A-Z0-9_#@$]+'
    alias = r'(?:\s+(?:AS\s+)?(?!(?:WHERE|JOIN|INNER|LEFT|RIGHT|FULL|CROSS|ON|GROUP|ORDER|FETCH|WITH|UNION|SET|VALUES|USING|INTO)\b)[A-Z][A-Z0-9_]*)?'
    for m in re.finditer(r'\b(?:FROM|JOIN|UPDATE|INSERT\s+INTO|DELETE\s+FROM|MERGE\s+INTO|USING)\s+(' + nome + alias + r'(?:\s*,\s*' + nome + alias + r')*)', s):
        for parte in re.split(r'\s*,\s*', m.group(1)):
            n = curto(parte.split()[0])
            if n in conhecidas:
                achadas.append(n)
    return achadas


def padrao_sql(sql, tabela, conhecidas, cursor, cascata_pais):
    """(padrão principal, todos os padrões, tabelas do comando, tabelas distintas, natureza)."""
    s = sem_literais(sql).upper()
    verbo = (s.split() or [''])[0]
    tabs = tabelas_do_sql(sql, conhecidas) or ([tabela] if tabela else [])
    distintas = list(dict.fromkeys(tabs))
    onde = bool(re.search(r'\bWHERE\b', s))
    if verbo in GRAVA:
        if verbo == 'INSERT':
            lote = bool(re.search(r'\bINSERT\s+INTO\s+\S+[^()]*(\([^)]*\))?\s*SELECT\b', s)) or bool(re.search(r'\bFOR\s+\d+\s+ROWS\b|\bFOR\s+:\S+\s+ROWS\b', s))
            p = 'BATCH_INSERT' if lote else 'DIRECT_INSERT'
        elif verbo == 'UPDATE':
            p = 'CONDITIONAL_UPDATE' if onde else 'DIRECT_UPDATE'
        elif verbo == 'DELETE':
            p = 'CASCADE_DELETE' if (distintas and distintas[0] in cascata_pais) else 'DIRECT_DELETE'
        else:
            p = 'UPSERT_PATTERN'
        return p, [p], tabs, distintas, 'grava'
    pad = []
    agreg = bool(re.search(r'\b(COUNT|SUM|AVG|MIN|MAX)\s*\(|\bGROUP\s+BY\b|\bHAVING\b', s))
    juncao = len(distintas) >= 2 or bool(re.search(r'\bJOIN\b', s))
    auto = len(tabs) != len(distintas)
    if len(distintas) >= 2 or (juncao and not auto):
        pad.append('MULTI_TABLE_JOIN')
    if auto or (re.search(r'\bJOIN\b', s) and len(distintas) == 1):
        pad.append('SELF_JOIN')
    if agreg:
        pad.append('AGGREGATION')
    if agreg and (juncao or re.search(r'\bGROUP\s+BY\b|\bHAVING\b|\bOVER\s*\(', s)) and ('MULTI_TABLE_JOIN' in pad or 'SELF_JOIN' in pad or re.search(r'\bHAVING\b|\bOVER\s*\(', s)):
        pad.append('ANALYTICAL_QUERY')
    if cursor:
        pad.append('CURSOR_FETCH')
    pad.append('FILTERED_SELECT' if onde else 'DIRECT_SELECT')
    ordem = ['ANALYTICAL_QUERY', 'MULTI_TABLE_JOIN', 'SELF_JOIN', 'AGGREGATION', 'CURSOR_FETCH', 'FILTERED_SELECT', 'DIRECT_SELECT']
    principal = next(o for o in ordem if o in pad)
    return principal, [o for o in ordem if o in pad], tabs, distintas, 'lê'


def volume_do_sql(sql, cursor, padroes):
    """Volume estimado do comando pelo próprio texto (só o que o texto mostra): FETCH FIRST n ROWS, ausência de cursor (1 linha) ou cursor sem limite."""
    m = re.search(r'(?i)FETCH\s+FIRST\s+(\d+)\s+ROWS?\s+ONLY', sql)
    if m:
        return int(m.group(1)), f'até {m.group(1)} linhas (FETCH FIRST)'
    if 'AGGREGATION' in padroes or 'ANALYTICAL_QUERY' in padroes:
        return None, 'agregação: lê todas as linhas que casam'
    if cursor:
        return None, 'cursor sem limite de linhas'
    return 1, 'uma linha (SELECT INTO sem cursor)'


# ----------------------------------------------------------------------------- evidência
CMD_CIT = re.compile(r'\b([A-Z][A-Z0-9]{7}-Q\d+)(?:\.\d+)?\b')


def comandos_do_fluxo(ana, funcs, cmds):
    """Comandos que o fluxo de negócio (fase 12) de cada funcionalidade executa: os nós do fluxo (`C14.PROG`, `E26.PROG`...) têm a linhagem consultada na fase 11 (`PROG@linha`) e a linha identifica o comando;
    os programas de consulta dinâmica não têm linha, e as ligações do fluxo citam o comando na evidência."""
    nos = {}
    for _s, bt, rows in S.tabelas(S.fase(ana, '11 ')):
        m = re.match(r'([A-Z]\d+\.\S+): linhagem', bt)
        if m:
            for r in rows:
                mm = re.match(r'(\S+)@(\d+):', str(r.get('Id', '')))
                if mm:
                    nos.setdefault(m.group(1), set()).add((mm.group(1), mm.group(2)))
    out = {}
    for _s, bt, rows in S.tabelas(S.fase(ana, '12 ')):
        m = re.match(r'(\S+): ligações do fluxo interno', bt)
        if not m:
            continue
        acc = out.setdefault(m.group(1), set())
        for r in rows:
            for x in (r['De'], r['Para']):
                acc |= nos.get(x, set())
            for c in CMD_CIT.findall(str(r.get('Evidência citada', ''))):
                acc.add(('cmd', c))
    return out


def cod_em_fluxo(cod, c, itens):
    for it in itens:
        if it[0] == 'cmd':
            if it[1] == cod:
                return True
        elif it[0] in c['programas'] and it[1] in re.findall(r'\d+', c['linhas']):
            return True
    return False


def fecho_chama(corp, f):
    out, pend = [], list(corp.get(f, {}).get('chama', []))
    while pend:
        g = pend.pop(0)
        if g not in out:
            out.append(g)
            pend += corp.get(g, {}).get('chama', [])
    return out


def coletar(ana):
    f0, f10, f12, f16 = S.fase(ana, '00-'), S.fase(ana, '10 '), S.fase(ana, '12 '), S.fase(ana, '16 ')
    classe = {}
    for _s, bt, rows in S.tabelas(f0):
        if bt == 'Programas':
            classe.update({r['Programa']: r['Classe'] for r in rows})
    # funcionalidades (fase 12): id, nome, base (entry point ou programa corporativo)
    funcs = {}
    for _s, bt, rows in S.tabelas(f12):
        if bt == 'Funcionalidades':
            for r in rows:
                m = re.match(r'(entry point|programa corporativo)\s+(\S+)', r['Base (referência)'])
                funcs[r['Id']] = {'id': r['Id'], 'nome': r['Funcionalidade'], 'tipo': r['Tipo'], 'base': r['Base (referência)'], 'programa': m.group(2) if m else '', 'natureza': m.group(1) if m else ''}
    if not funcs:
        raise SystemExit('fase 12: tabela de funcionalidades não encontrada')
    fluxo = {}
    for _s, bt, rows in S.tabelas(f12):
        m = re.match(r'(\S+): fluxo passo a passo$', bt)
        if m:
            fluxo[m.group(1)] = [(str(r['Passo']), str(r['O que acontece']), str(r['Programas'])) for r in rows]
    por_entry = defaultdict(list)
    por_corp = defaultdict(list)
    for i, f in funcs.items():
        (por_entry if f['natureza'] == 'entry point' else por_corp)[f['programa']].append(i)
    corp = {}
    for _s, bt, rows in S.tabelas(f12):
        m = re.match(r'(\S+): relação com as chamadas corporativas$', bt)
        if m:
            d_ = corp.setdefault(m.group(1), {'chama': [], 'chamada_por': []})
            por_nome = {v['nome']: k for k, v in funcs.items()}
            for r in rows:
                mb = re.match(r'(entry point|programa corporativo)\s+(\S+)', str(r.get('Base (referência)', '')))
                if mb:
                    # a função chamada/chamadora é a do Nome da linha (um programa corporativo reúne várias funcionalidades: FC03 e FC04 são do mesmo programa); sem o nome, todas as do programa
                    alvo = [por_nome[r['Nome']]] if r.get('Nome') in por_nome else (por_corp if mb.group(1) == 'programa corporativo' else por_entry).get(mb.group(2), [])
                    d_['chama' if r.get('Relação') == 'chama' else 'chamada_por'] += alvo
    # domínio (fase 16): classe, categoria, agregado, natureza de cada tabela e associações com cascata
    dominio, cascata_pais = {}, set()
    for _s, bt, rows in S.tabelas(f16):
        if bt.startswith('Classes de domínio: tabela física'):
            for r in rows:
                dominio[curto(r['Tabela'])] = {'classe': r['Classe'], 'categoria': r.get('Categoria', ''), 'agregado': r.get('Agregado', ''), 'natureza': r.get('Natureza no domínio', '')}
    cls2tab = {v['classe']: t for t, v in dominio.items()}
    assoc = set()
    raiz = {}
    for _s, bt, rows in S.tabelas(f16):
        if bt == 'Agregados':
            for r in rows:
                m = re.search(r'\(([^)]+)\)\s*$', str(r.get('Raiz', '')))
                if m:
                    raiz[r['Agregado']] = curto(m.group(1))
    for _s, bt, rows in S.tabelas(f16):
        if bt.startswith('Associações entre as classes'):
            for r in rows:
                if r.get('Cascata') == 'sim' and r['De (todo)'] in cls2tab:
                    cascata_pais.add(cls2tab[r['De (todo)']])
                if r['De (todo)'] in cls2tab and r['Para (parte)'] in cls2tab:
                    assoc.add(frozenset((cls2tab[r['De (todo)']], cls2tab[r['Para (parte)']])))
    # escopo: só as tabelas atingidas pela execução dinâmica (fase 4) já mapeadas no data-schema (fase 3) e as dinâmicas do sql-mapping (fase 10)
    atingidas, todas = set(), set()
    for _s, bt, rows in S.tabelas(S.fase(ana, '04-')):
        if rows and 'Alcançada pela execução dinâmica' in rows[0] and 'Comandos que gravam' in rows[0]:
            for r in rows:
                todas.add(curto(r['Tabela']))
                if not r['Alcançada pela execução dinâmica'].upper().startswith('NÃO'):
                    atingidas.add(curto(r['Tabela']))
    for _s, bt, rows in S.tabelas(f10):
        if bt == 'Tabelas passadas por parâmetro':
            atingidas |= {curto(r['Tabela descoberta']) for r in rows}
    fora_escopo = sorted(todas - atingidas)
    conhecidas = set(dominio)
    # comandos (fase 10): texto SQL por (programa, linha) e os comandos Q-nn
    sql_por_linha = {}
    for _s, bt, rows in S.tabelas(f10):
        if bt.startswith('Todos os comandos SQL'):
            for r in rows:
                sql_por_linha.setdefault((r['Programa'], str(r['Linha'])), r['SQL'])
                conhecidas.add(curto(r['Tabela']))
    estatico_dinamico, dinamicos_sql = {}, []
    for _s, bt, rows in S.tabelas(f10):
        if bt.endswith('comando SQL estático que substitui a execução dinâmica'):
            for r in rows:
                estatico_dinamico[r['Código']] = r['Comando SQL estático']
                dinamicos_sql.append(r['Comando SQL estático'])
    alias = {}   # comando original -> query única (fase 10: comandos SELECT com o mesmo FROM e WHERE são uma query só)
    for _s, bt, rows in S.tabelas(f10):
        if bt == 'Queries equivalentes unificadas':
            for r in rows:
                ms = [x.strip() for x in str(r['Comandos unificados']).split(',') if x.strip()]
                for m_ in ms[1:]:
                    alias[m_] = ms[0]
    cmds = {}
    for st, bt, rows in S.tabelas(f10):
        if bt.endswith(': onde e quando executa') and rows and ('Programa' in rows[0] or 'Programa que executa' in rows[0]):
            cod = bt.split(':')[0]
            r = rows[0]
            prog = cod.split('-Q')[0]
            progs_q = list(dict.fromkeys(str(x.get('Comando original') or cod).split('-Q')[0] for x in rows))   # programas que executam a query única
            uniao = lambda k: list(dict.fromkeys(y.strip() for x in rows for y in re.split(r'[,;]', str(x.get(k, ''))) if y.strip()))   # noqa: E731
            linhas = [n_ for x in rows for n_ in re.findall(r'\d+', x.get('Linhas', ''))]
            sql = estatico_dinamico.get(cod, '')
            if not sql:
                for ln in linhas:
                    if (prog, ln) in sql_por_linha:
                        sql = sql_por_linha[(prog, ln)]
                        break
            tabela = curto(r.get('Tabela', ''))
            cmds[cod] = {'cod': cod, 'programa': prog, 'classe': classe.get(prog, r.get('Classe', '')), 'operacao': r.get('Operação', ''), 'tabela': tabela, 'linhas': ', '.join(linhas), 'paragrafo': r.get('Parágrafo', ''),
                         'cursor': next((x['Cursor'] for x in rows if x.get('Cursor')), ''), 'natureza': r.get('Natureza', ''), 'quando': ' | '.join(dict.fromkeys(str(x.get('Executa quando (condições de negócio)', x.get('Executa quando', ''))) for x in rows)),
                         'entry_points': uniao('Entry points'), 'sql': sql, 'programas': progs_q,
                         'recebe': uniao('Recebe dado de'), 'entrega': uniao('Entrega dado a')}
    for q in dinamicos_sql:   # a coluna Código vem sem texto: o SQL fixado vai para o primeiro comando dinâmico sem SQL da mesma tabela
        ts = tabelas_do_sql(q, conhecidas)
        alvo = next((c for k, c in sorted(cmds.items()) if not c['sql'] and ts and c['tabela'] == ts[0]), None)
        if alvo:
            alvo['sql'] = q
    for k in [k for k, c in cmds.items() if c['tabela'] not in atingidas]:   # comando sobre tabela fora do escopo não entra
        del cmds[k]
    fluxo_cmds = comandos_do_fluxo(ana, funcs, cmds)
    for c in cmds.values():
        c['padrao'], c['padroes'], c['tabelas_cmd'], c['tabelas'], nat = padrao_sql(c['sql'], c['tabela'], conhecidas, c['cursor'], cascata_pais)
        if not c['sql']:
            c['padrao'], c['padroes'], c['tabelas'], nat = ('DIRECT_SELECT' if c['natureza'] == 'lê' else 'DIRECT_INSERT'), [], [c['tabela']], c['natureza']
        c['tabelas'] = [t for t in c['tabelas'] if t in atingidas]
        c['natureza_sql'] = nat
        c['grava'] = c['operacao'].split()[0].upper() in GRAVA if c['operacao'] else nat == 'grava'
        c['volume_n'], c['volume'] = volume_do_sql(c['sql'], c['cursor'], c['padroes'])
        # funcionalidade executora: a do programa corporativo que executa; senão, as dos entry points que alcançam o comando
        exec_f = list(dict.fromkeys(f for pg in c['programas'] for f in por_corp.get(pg, [])))
        inv = sorted({f for ep in c['entry_points'] for f in por_entry.get(ep, [])}, key=lambda x: (len(x), x))
        # o fluxo de negócio (fase 12) diz quais funcionalidades executam o comando: o programa corporativo reúne várias funcionalidades e cada uma executa só os seus comandos
        no_fluxo = [f for f in funcs if cod_em_fluxo(c['cod'], c, fluxo_cmds.get(f, ()))]
        if no_fluxo:
            corp_ = [f for f in no_fluxo if funcs[f]['natureza'] == 'programa corporativo']
            if corp_:
                exec_f = corp_
                inv = sorted({a_ for a_ in funcs if funcs[a_]['natureza'] == 'entry point' and set(fecho_chama(corp, a_)) & set(corp_)}, key=lambda x: (len(x), x))
            else:
                exec_f, inv = [], sorted(no_fluxo, key=lambda x: (len(x), x))
        c['func_invocam'] = inv
        c['func_exec'] = exec_f or inv
        c['via_corp'] = bool(exec_f)
    return {'classe': classe, 'funcs': funcs, 'dominio': dominio, 'cascata_pais': cascata_pais, 'cmds': cmds, 'conhecidas': conhecidas, 'assoc': assoc, 'raiz': raiz, 'fluxo': fluxo, 'corp': corp, 'escopo': sorted(atingidas), 'fora_escopo': fora_escopo, 'alias': alias}


def deduzir(ev):
    cmds = ev['cmds']
    dml = defaultdict(lambda: defaultdict(list))     # tabela -> funcionalidade -> comandos que gravam
    leit = defaultdict(lambda: defaultdict(list))    # tabela -> funcionalidade -> comandos que leem
    for c in cmds.values():
        for t in c['tabelas']:
            for f in c['func_exec']:
                (dml if c['grava'] else leit)[t][f].append(c['cod'])
            if not c['grava']:   # as funcionalidades que invocam o corporativo também leem o dado (por intermédio dele)
                for f in c['func_invocam']:
                    leit[t][f].append(c['cod'])
    tabs = sorted({t for c in cmds.values() for t in c['tabelas']} | (set(ev['dominio']) & set(ev['escopo'])))
    prop = {}
    for t in tabs:
        donos = sorted(dml[t], key=lambda x: (len(x), x))
        leitores = sorted((set(leit[t]) - set(donos)), key=lambda x: (len(x), x))
        prop[t] = {'classificacao': EXCL if len(donos) == 1 else COMP if len(donos) >= 2 else LEIT, 'donos': donos, 'leitores': leitores,
                   'cmds_dml': sorted({q for f in donos for q in dml[t][f]}), 'cmds_leitura': sorted({q for f in leit[t] for q in leit[t][f]})}
    # papel de cada funcionalidade
    papel = {f: {'proprietaria': [], 'compartilha': [], 'le': []} for f in ev['funcs']}
    for t, p in prop.items():
        for f in p['donos']:
            papel[f]['proprietaria' if p['classificacao'] == EXCL else 'compartilha'].append(t)
        for f in p['leitores']:
            papel[f]['le'].append(t)
    # JOINs multi-owner: SELECT com duas ou mais tabelas cujas propriedades não coincidem
    joins = []
    for c in sorted(cmds.values(), key=lambda x: x['cod']):
        if c['grava'] or len(c['tabelas']) < 2:
            continue
        # dono de cada tabela: a funcionalidade que grava; sem gravação no escopo, o agregado de domínio (fase 16) é o proxy do dono externo
        dono = {t: (tuple(prop[t]['donos']) or ('agregado ' + (ev['dominio'].get(t, {}).get('agregado') or t),)) for t in c['tabelas']}
        cruza = len(set(dono.values())) > 1 or any(prop[t]['classificacao'] == COMP for t in c['tabelas'])
        if not cruza:
            continue
        motivos = []
        for t in c['tabelas']:
            p = prop[t]
            motivos.append(f'{t}: ' + ('dono ' + ', '.join(p['donos']) if p['classificacao'] == EXCL else 'compartilhada entre ' + ', '.join(p['donos']) if p['classificacao'] == COMP else
                                       'somente leitura, dono externo no ' + dono[t][0]))
        n = c['volume_n']
        cand = 'API_COMPOSITION' if (n is not None and n <= 1000) else 'QUERY_SERVICE' if n is None else 'a decidir'
        joins.append({'cod': c['cod'], 'tabelas': c['tabelas'], 'motivos': motivos, 'candidata': cand})
    # resumo por padrão
    return {'prop': prop, 'papel': papel, 'joins': joins, 'tabelas': tabs, 'dml': dml, 'leit': leit}



def analisa_sql(sql, tabelas):
    """Por tabela do SELECT: colunas entregues (lista do SELECT) e usadas só em filtro; e as ligações entre tabelas (igualdades A.X = B.Y)."""
    u = sem_literais(sql).upper()
    ali = {}
    nome = r'(?:[A-Z0-9_#@$]+\.)?[A-Z0-9_#@$]+'
    alias = r'(?:\s+(?:AS\s+)?(?!(?:WHERE|JOIN|INNER|LEFT|RIGHT|FULL|CROSS|ON|GROUP|ORDER|FETCH|WITH|UNION|SET|VALUES|USING|INTO)\b)[A-Z][A-Z0-9_]*)?'
    for m in re.finditer(r'\b(?:FROM|JOIN)\s+(' + nome + alias + r'(?:\s*,\s*' + nome + alias + r')*)', u):
        for parte in re.split(r'\s*,\s*', m.group(1)):
            tk = [x for x in parte.split() if x != 'AS']
            t = curto(tk[0])
            ali[t] = t
            if len(tk) > 1:
                ali[tk[1]] = t
    ref = re.compile(r'\b([A-Z][A-Z0-9_]*)\.([A-Z][A-Z0-9_]*)\b')
    corte = re.search(r'\bFROM\b', u)
    sel = u[:corte.start()] if corte else u
    resto = u[corte.start():] if corte else ''
    ligacoes = []
    for m in re.finditer(r'\b([A-Z][A-Z0-9_]*)\.([A-Z][A-Z0-9_]*)\s*=\s*([A-Z][A-Z0-9_]*)\.([A-Z][A-Z0-9_]*)\b', resto):
        ta, tb = ali.get(m.group(1)), ali.get(m.group(3))
        if ta and tb and ta != tb:
            ligacoes.append(f'{ta}.{m.group(2)} = {tb}.{m.group(4)}')
    sem_lig = re.sub(r'\b[A-Z][A-Z0-9_]*\.[A-Z][A-Z0-9_]*\s*=\s*[A-Z][A-Z0-9_]*\.[A-Z][A-Z0-9_]*\b', '', resto)
    entrega = {t: [] for t in tabelas}
    filtro = {t: [] for t in tabelas}
    for m in ref.finditer(sel):
        t = ali.get(m.group(1))
        if t in entrega and m.group(2) not in entrega[t]:
            entrega[t].append(m.group(2))
    for m in ref.finditer(sem_lig):
        t = ali.get(m.group(1))
        if t in filtro and m.group(2) not in filtro[t] and m.group(2) not in entrega[t]:
            filtro[t].append(m.group(2))
    return entrega, filtro, list(dict.fromkeys(ligacoes))


def consulta_por_agregado(j, ev, de):
    """Como obter o mesmo resultado de uma query multi-owner consultando os agregados (fase 16) em vez de juntar as tabelas."""
    c, dom, raiz = ev['cmds'][j['cod']], ev['dominio'], ev['raiz']
    entrega, filtro, ligacoes = analisa_sql(c['sql'], j['tabelas'])
    ags = {}
    for t in j['tabelas']:
        ag = dom.get(t, {}).get('agregado') or '(sem agregado)'
        x = ags.setdefault(ag, {'agregado': ag, 'raiz': raiz.get(ag, '—'), 'tabelas': [], 'entrega': [], 'filtro': [], 'dono': set()})
        x['tabelas'].append(t)
        x['entrega'] += [f'{t}.{k}' for k in entrega[t]]
        x['filtro'] += [f'{t}.{k}' for k in filtro[t]]
        x['dono'].add(dono_suposto(t, ev, de)[0])
    for x in ags.values():
        x['dono'] = ', '.join(sorted(x['dono']))
        x['papel'] = 'entrega colunas' if x['entrega'] else 'só filtra ou liga'
    partes = []
    for x in ags.values():
        if x['entrega']:
            partes.append(f'consultar {x["agregado"]} (raiz {x["raiz"]}) para obter {", ".join(x["entrega"])}' + (f', filtrando por {", ".join(x["filtro"])}' if x['filtro'] else ''))
        else:
            partes.append(f'{x["agregado"]} (raiz {x["raiz"]}) só participa para filtrar ou ligar' + (f' ({", ".join(x["filtro"])})' if x['filtro'] else '') + ': basta uma consulta por chave ao agregado, sem entregar colunas')
    if len(ags) == 1:
        como = 'todas as tabelas pertencem ao mesmo agregado: uma só consulta ao agregado devolve o resultado'
    else:
        como = f'{len(ags)} agregados: ' + '; '.join(partes) + ('. Combinar os resultados na aplicação pelas ligações ' + ', '.join(ligacoes) if ligacoes else '. Combinar os resultados na aplicação')
    n_ag = len(ags)
    n_reg = c.get('volume_n')
    um = n_reg == 1
    chamadas = n_ag
    if um and chamadas <= MAX_COMPOSICOES:
        estrategia = 'API_COMPOSITION'
        porque = f'retorna no máximo 1 registro e exige {chamadas} chamada(s) (limite de {MAX_COMPOSICOES} composições): Composition é viável'
    elif um:
        estrategia = 'QUERY_SERVICE'
        porque = f'retorna 1 registro, mas exigiria {chamadas} chamadas (acima do limite de {MAX_COMPOSICOES} composições): usar Query Legacy'
    else:
        estrategia = 'QUERY_SERVICE'
        porque = f'retorna {c.get("volume") or "mais de um registro"}: compor chamando os agregados multiplicaria as chamadas (uma ou mais por registro, o problema N+1): usar Query Legacy'
    seq = n_ag > 1 and bool(ligacoes)
    if estrategia == 'API_COMPOSITION':
        lat_api = (f'{chamadas} chamadas síncronas; a chave de um agregado alimenta o outro, então a latência soma as chamadas' if seq else f'{chamadas} chamada(s) síncrona(s) independentes, em paralelo')
    else:
        lat_api = f'{chamadas} chamadas por registro retornado: a latência cresce com o número de registros'
    lat_q = 'uma leitura local sobre dados replicados, sem chamadas de rede entre serviços; os dados chegam com algum atraso em relação aos donos'
    cx_api = f'baixa a média: orquestrar {chamadas} chamada(s), com timeout e tratamento de falha parcial' if estrategia == 'API_COMPOSITION' else 'média a alta: orquestração com N+1 chamadas, paginação e falha parcial por registro'
    cx_q = 'alta: pipeline de replicação (data lake), modelo de leitura e serviço de consulta para manter e operar'
    return {'agregados': list(ags.values()), 'ligacoes': ligacoes, 'como': como, 'estrategia': estrategia, 'porque': porque, 'chamadas': chamadas, 'registros': c.get('volume') or '—',
            'lat_api': lat_api, 'lat_q': lat_q, 'cx_api': cx_api, 'cx_q': cx_q}


def _divide_top(t, sep):
    """Divide `t` pelo separador (regex) só fora de parênteses."""
    partes, nivel, ini = [], 0, 0
    for m in re.finditer(r'\(|\)|' + sep, t, re.I):
        if m.group() == '(':
            nivel += 1
        elif m.group() == ')':
            nivel -= 1
        elif nivel == 0:
            partes.append(t[ini:m.start()].strip())
            ini = m.end()
    partes.append(t[ini:].strip())
    return [x for x in partes if x]


def pexib(p):
    return 'SELECT_CURSOR' if p == 'CURSOR_FETCH' else p


def ordem_f(x):
    return (len(x), x)


def plano(ev, de):
    """Cada query multi-owner: manter no agregado (Composition) ou separar em Query (uma por query, sem agrupar)."""
    cmds, funcs = ev['cmds'], ev['funcs']
    dec = {}
    for j in de['joins']:
        q = consulta_por_agregado(j, ev, de)
        ags = q['agregados']
        princ = max(ags, key=lambda x: len(x['entrega']))
        dec[j['cod']] = {'cod': j['cod'], 'q': q, 'estrategia': q['estrategia'], 'principal': princ['agregado'], 'agregados': [x['agregado'] for x in ags],
                         'secundarios': [x['agregado'] for x in ags if x['agregado'] != princ['agregado']], 'funcs': list(cmds[j['cod']]['func_exec']), 'invocam': list(cmds[j['cod']]['func_invocam']), 'tabelas': j['tabelas']}
    qs, nfs = [], []
    for k, cod in enumerate(sorted(c for c, d in dec.items() if d['estrategia'] == 'QUERY_SERVICE'), 1):
        d = dec[cod]
        c = cmds[cod]
        entrega, filtro, _lig = analisa_sql(c['sql'], d['tabelas'])
        cols = [x for t in d['tabelas'] for x in entrega[t]]
        fil = [x for t in d['tabelas'] for x in filtro[t]]
        f0 = d['funcs'][0] if d['funcs'] else None
        base = funcs[f0]['nome'] if f0 else f'consulta {cod}'
        qid, nid = f'QS{k:02d}', f'NF{k:02d}'
        d['qs'], d['nf'] = qid, nid
        qs.append({'id': qid, 'query': cod, 'tabelas': d['tabelas'], 'funcs': d['funcs'], 'nf': nid})
        nfs.append({'id': nid, 'nome': f'{base} (leitura via Query: ' + ' + '.join(ev['dominio'].get(t, {}).get('classe') or t for t in d['tabelas']) + ')', 'tipo': funcs[f0]['tipo'] if f0 else 'consulta', 'qs': qid, 'query': cod, 'funcs': d['funcs'], 'base_func': f0, 'tabelas': d['tabelas'], 'colunas': cols, 'filtros': fil,
                    'resp': f'responde a consulta de "{base}" ({cod}) a partir de um modelo de leitura próprio, com {", ".join(d["tabelas"])} já juntas, sem acessar os donos das tabelas',
                    'motivo': d['q']['porque'], 'fluxo': [
                        ('1', f'Recebe de {f0 or cod} os parâmetros da consulta' + (f' (filtros: {lista(fil, 6)})' if fil else ''), 'síncrono'),
                        ('2', f'Consulta o modelo de leitura {qid}, que já traz juntas as colunas de {", ".join(d["tabelas"])}, sem juntar tabelas de donos diferentes', 'síncrono'),
                        ('3', f'Devolve as linhas a {f0 or cod}' + (f' ({lista(cols, 6)})' if cols else ''), 'síncrono'),
                        ('4', f'Mantém o modelo de leitura: recebe as alterações dos donos de {", ".join(d["tabelas"])} e as aplica; os dados chegam com algum atraso em relação aos donos', 'assíncrono')]})
    return {'dec': dec, 'qs': qs, 'nfs': nfs}


def dono_suposto(t, ev, de):
    p, ag = de['prop'][t], ev['dominio'].get(t, {}).get('agregado') or '—'
    if p['donos']:
        return ', '.join(p['donos']), f'{", ".join(p["donos"])} (grava no escopo)'
    return 'fora da análise', f'fora da análise (sem gravação no escopo; agregado {ag} na fase 16)'


# ----------------------------------------------------------------------------- relatório
def lk(t):
    return rm.link(t, '03-data-schema', 'tabela-' + t)


def lista(xs, n=4):
    xs = list(xs)
    return ', '.join(xs[:n]) + (f' (+{len(xs) - n})' if len(xs) > n else '') if xs else '—'


def passo_da_funcionalidade(ev, f, c):
    """Passo do fluxo da fase 12 em que a query executa (pelo programa do comando; senão, o primeiro passo de consulta)."""
    passos = ev['fluxo'].get(f) or []
    for n, txt, progs in passos:
        if any(pg in progs for pg in c['programas']):
            return n, txt
    for n, txt, _p in passos:
        if re.search(r'consult|pesquis|list|busc', txt, re.I):
            return n, txt
    return None, None


def cenarios(ev, de):
    """Decisões por query multi-owner (base): agregados donos das tabelas de cada query, usados para saber que agregado executa cada comando."""
    base = plano(ev, de)['dec']
    A = {cod: {**d, 'estrategia': 'API_COMPOSITION'} for cod, d in base.items()}
    B = {cod: {**d, 'estrategia': 'QUERY_SERVICE'} for cod, d in base.items()}
    return base, A, B


def agregados_do_cmd(ev, c, dec_a):
    if c['cod'] in dec_a:
        return list(dec_a[c['cod']]['agregados'])
    dom = ev['dominio']
    ags = list(dict.fromkeys(dom.get(t, {}).get('agregado') or t for t in c['tabelas']))
    return ags or [dom.get(c['tabela'], {}).get('agregado') or c['tabela']]


def evidencia_chamadas(ev, dec_a, _dec_b=None):
    """Por funcionalidade: queries executadas, cursores, candidatas a chamada por linha (dado encadeado entre comandos), chamadas corporativas e a fórmula de chamadas
    (uma por query de uma tabela no agregado, por Legacy Query ou por chamada ao programa corporativo)."""
    funcs, cmds = ev['funcs'], ev['cmds']
    progs_corp = {i: f['programa'] for i, f in funcs.items() if f['natureza'] == 'programa corporativo'}
    out = {}
    for f in funcs:
        cf = [c for c in sorted(cmds.values(), key=lambda x: x['cod']) if f in c['func_exec'] or f in c['func_invocam']]
        cursores = [c for c in cf if c['cursor']]
        simples = [c for c in cf if not c['cursor']]
        cods = {c['cod'] for c in cf}
        cand, antes = {}, {}
        for cu in cursores:
            cand[cu['cod']], antes[cu['cod']] = [], []
            for q in simples:
                recebe_do_cursor = q['cod'] in cu['entrega'] or cu['cod'] in q['recebe']
                entrega_ao_cursor = cu['cod'] in q['entrega'] or q['cod'] in cu['recebe']
                if recebe_do_cursor:
                    cand[cu['cod']].append(q['cod'] + (' (e também entrega dado ao cursor)' if entrega_ao_cursor else ''))
                elif entrega_ao_cursor:
                    antes[cu['cod']].append(q['cod'])
        passos = [(pa, tx, pg) for pa, tx, pg in ev['fluxo'].get(f, []) if LACO.search(tx)]
        corp_chama = list(dict.fromkeys(ev['corp'].get(f, {}).get('chama', [])))

        def no_laco(i):
            for _pa, tx, pg in passos:
                if re.search(r'\b' + i + r'\b', tx):
                    return True
                if progs_corp[i] in (pg + ' ' + tx) and not any(re.search(r'\b' + j + r'\b', tx) for j in progs_corp if progs_corp[j] == progs_corp[i]):
                    return True
            return False
        corp_laco = [i for i in corp_chama if no_laco(i)]
        cand_cods = {x.split(' ')[0] for v in cand.values() for x in v}
        fix = sum(1 for c in simples if c['cod'] not in cand_cods) + len(corp_chama) - len(corp_laco)
        n_linha = len(cand_cods) + len(corp_laco)
        formula = f'{fix} fixas + {len(cursores)} cursor(es) + N × {n_linha} por linha' if n_linha else f'{fix} fixas + {len(cursores)} cursor(es); nenhuma chamada por linha'
        # a chave 'C' é a da estratégia adotada (o agregado corporativo chama o programa em vez de executar o SQL: uma chamada no lugar de uma execução)
        out[f] = {'cods': cods, 'simples': [c['cod'] for c in simples], 'cursores': cursores, 'cand': cand, 'antes': antes, 'passos': passos, 'corp': corp_chama, 'corp_laco': corp_laco,
                  'cen': {'C': {'fixas': fix, 'n_linha': n_linha, 'formula': formula}}}
    return out


def ler_interp(base):
    d = Path(base) / 'interpretacao-relacao'
    arqs = sorted(f for f in d.glob('*.json') if f.name not in ('PROVENIENCIA.json',)) if d.exists() else []
    if not arqs:
        return None
    out = {k: [] for k in CHAVES_RAIZ}
    for f in arqs:
        x = json.loads(f.read_text(encoding='utf-8'))
        for k, v in x.items():
            out.setdefault(k, [])
            out[k] += v if isinstance(v, list) else [v]
    return out


def normalizar_interp(interp, alias):
    """A interpretação pode citar o código de um comando unificado na fase 10: vale o código da query única."""
    if not alias:
        return
    for x in interp.get('funcionalidades', []):
        for k in ('cursores', 'por_linha', 'evidencia'):
            if isinstance(x.get(k), list):
                x[k] = list(dict.fromkeys(alias.get(q, q) if isinstance(q, str) else q for q in x[k]))


RE_QUERY = re.compile(r'(?i)\bqueries\b|\bquery\b|\b\w{6,8}-Q\d{2}\b')
RE_AGREGADO = re.compile(r'(?i)agregad')


def validar(ev, evid, interp):
    erros, falhas = [], []
    for k in sorted(set(interp) - CHAVES_RAIZ):
        erros.append(f'chave desconhecida na interpretação: {k}')
    ids = set(ev['funcs'])
    vistos = {}
    for x in interp['funcionalidades']:
        f = x.get('funcionalidade')
        if f not in ids:
            erros.append(f'funcionalidade inexistente: {f}')
            continue
        if 'cenario' in x:
            erros.append(f'{f}: o campo cenario não existe (a estratégia de acesso aos dados é uma só)')
            continue
        if f in vistos:
            erros.append(f'análise repetida: {f}')
            continue
        vistos[f] = x
        e = evid[f]
        t = f
        if 'agregados_por_linha' in x:
            falhas.append(f'{t}: o campo agregados_por_linha não existe; use por_linha')
        cur_ids = {c['cod'] for c in e['cursores']}
        v = x.get('veredito')
        if v not in VEREDITOS:
            falhas.append(f'{t}: veredito deve ser um de {sorted(VEREDITOS)}')
            continue
        curs, pl = x.get('cursores') or [], x.get('por_linha') or []
        if v == 'sem_cursor':
            if cur_ids:
                falhas.append(f'{t}: tem cursor ({", ".join(sorted(cur_ids))}); o veredito não pode ser sem_cursor')
            if pl or curs:
                falhas.append(f'{t}: sem_cursor não tem cursores nem chamadas por linha')
            if x.get('gravidade') != 'nenhuma':
                falhas.append(f'{t}: sem_cursor tem gravidade "nenhuma"')
        else:
            if not cur_ids:
                falhas.append(f'{t}: não há cursor nesta funcionalidade; o veredito é sem_cursor')
            if not curs or any(c not in cur_ids for c in curs):
                falhas.append(f'{t}: cursores deve listar as queries com cursor da funcionalidade ({", ".join(sorted(cur_ids)) or "nenhum"}); veio {curs}')
            validos = set(e['simples']) | set(e['corp'])
            for q in pl:
                if q not in validos:
                    falhas.append(f'{t}: por_linha cita {q}, que não é query simples nem chamada corporativa da funcionalidade')
            if v in ('sim', 'mitigado') and not pl:
                falhas.append(f'{t}: veredito {v} exige por_linha (as chamadas repetidas a cada linha)')
            if v == 'nao' and pl:
                falhas.append(f'{t}: veredito nao não tem chamadas por linha; use sim ou mitigado')
            if v == 'mitigado' and not str(x.get('mitigacao', '')).strip():
                falhas.append(f'{t}: veredito mitigado exige mitigacao')
            if x.get('gravidade') not in GRAVIDADES:
                falhas.append(f'{t}: gravidade deve ser um de {sorted(GRAVIDADES)}')
        evs = x.get('evidencia') or []
        for k in ('chamadas', 'latencia', 'recomendacao'):
            if not str(x.get(k, '')).strip():
                falhas.append(f'{t}: falta {k}')
            elif NUM_PROIBIDO.search(str(x[k])):
                falhas.append(f'{t}: {k} usa número de tempo ou de volume, que não existe nos relatórios')
        if x.get('confianca') not in {'alta', 'média', 'media', 'baixa'}:
            falhas.append(f'{t}: confianca deve ser alta, média ou baixa')
        if not evs:
            falhas.append(f'{t}: falta evidencia')
        for q in evs:
            m = re.fullmatch(r'(F\w*\d+) passo (\S+)', str(q))
            if m:
                if m.group(1) not in ev['fluxo'] or m.group(2) not in {pa for pa, _t, _g in ev['fluxo'][m.group(1)]}:
                    falhas.append(f'{t}: evidência {q} não existe na fase 12')
            elif q not in ev['cmds'] and q not in ids:
                falhas.append(f'{t}: evidência {q} deve ser comando, funcionalidade ou passo de fluxo')
    for f in sorted(ids - set(vistos)):
        falhas.append(f'{f}: sem análise (toda funcionalidade precisa de uma)')
    for l in interp['lacunas'] + interp['premissas']:
        if not (str(l.get('assunto', l.get('item', ''))).strip() and str(l.get('detalhe', '')).strip()):
            falhas.append(f'lacuna ou premissa incompleta: {l}')
    return erros, falhas


VER = {'sim': 'sim: N+1', 'mitigado': 'mitigado', 'nao': 'não', 'sem_cursor': 'sem cursor'}


def _ix(interp):
    return {x['funcionalidade']: x for x in interp['funcionalidades']} if interp else {}


def _legenda_veredito():
    return [{'texto': 'N+1', 'cor': COR_VEREDITO['sim']}, {'texto': 'N+1 mitigado', 'cor': COR_VEREDITO['mitigado']}, {'texto': 'sem chamada por linha', 'cor': COR_VEREDITO['nao']}, {'texto': 'sem análise (evidência apenas)', 'cor': '#546E7A'}]


NOTA_GRAFO = ('Cada seta para a chamada a cada linha é uma chamada repetida para cada linha lida: com N linhas, são N chamadas além da leitura da lista (caso N+1). '
              'Vermelho: N+1 sem mitigação; laranja: N+1 mitigado pelo próprio fluxo; verde: sem chamada por linha; cinza: sem análise.')


def analise_q(ev, interp, evid, onde=None, mapa=None):
    """Análise por funcionalidade sobre as queries: simples dentro dos agregados, de várias tabelas como descobertas (Query Legacy); o agregado corporativo chama o programa corporativo."""
    funcs, cmds = ev['funcs'], ev['cmds']
    cen = 'C'   # a evidência de chamadas da estratégia adotada (agregados, Query Legacy com Group Query e LEGACY nos agregados corporativos)
    ix = _ix(interp)
    ai = lambda f, k, d='—': (ix[f].get(k) if f in ix and ix[f].get(k) not in (None, '') else d)   # noqa: E731
    fn_prog = (lambda q: funcs[q]['programa'] if (q in funcs and funcs[q]['natureza'] == 'programa corporativo') else None) if mapa is not None else (lambda q: None)   # noqa: E731
    mapa = mapa or {}   # a query do agregado corporativo é mostrada como o programa corporativo que o agregado chama
    M = lambda s: (str(s).replace(str(s).split(' ')[0], mapa[str(s).split(' ')[0]], 1) if str(s).split(' ')[0] in mapa else s)   # noqa: E731
    MJ = lambda xs: ', '.join(dict.fromkeys((fn_prog(x) or M(x)) for x in xs)) or '—'   # noqa: E731
    lin = []
    for f in funcs:
        e = evid[f]
        x = ix.get(f)
        lin.append((f, funcs[f]['nome'], len(e['cods']), MJ(c['cod'] for c in e['cursores']), MJ(e['corp']),
                    MJ(sorted({y.split(' ')[0] for v in e['cand'].values() for y in v}) + e['corp_laco']), e['cen'][cen]['fixas'], e['cen'][cen]['formula'],
                    VER[x['veredito']] if x else '—', MJ(x.get('por_linha') or []) if x else '—', ai(f, 'chamadas'), ai(f, 'latencia'), ai(f, 'gravidade')))
    cur = []
    for f in funcs:
        e = evid[f]
        x = ix.get(f)
        pas = ' | '.join(f'{pa}: {tx}' for pa, tx, _g in e['passos']) or '—'
        for cu in e['cursores']:
            cur.append((f, M(cu['cod']), cu['tabela'], *([onde(cu['cod'])] if onde else []), MJ(q for q in cu['entrega'] if q in e['cods']), MJ(e['cand'][cu['cod']]), MJ(e['antes'][cu['cod']]), pas,
                        VER[x['veredito']] if x else '—', ai(f, 'mitigacao'), ai(f, 'recomendacao'), ai(f, 'confianca'), ', '.join(ai(f, 'evidencia', [])) or '—'))
    fn, fa, fv = [], {}, set()
    for f in funcs:
        e = evid[f]
        if not e['cursores']:
            continue
        x = ix.get(f)
        cor = COR_VEREDITO[x['veredito']] if x else '#546E7A'
        fn.append({'id': 'f-' + f, 'col': 0, 'label': f, 'sub': (VER[x['veredito']] if x else funcs[f]['tipo']), 'detail': f'{f} · {funcs[f]["nome"]}: {e["cen"][cen]["formula"]}' + (f'. {x.get("chamadas", "")}' if x else ''), 'cor': cor})
        alvos = list(x.get('por_linha') or []) if x else sorted({y.split(' ')[0] for v in e['cand'].values() for y in v}) + e['corp_laco']
        for cu in e['cursores']:
            cid = f'c-{f}-{cu["cod"]}'
            if onde:   # a funcionalidade não liga direto ao comando SQL: liga ao Group Query ou ao agregado que o executa
                cid = f'c-{f}-{onde(cu["cod"])}'
                if not any(n_['id'] == cid for n_ in fn):
                    if cu['cod'] in mapa:
                        fn.append({'id': cid, 'col': 1, 'label': onde(cu['cod']), 'sub': 'chama o programa corporativo ' + mapa[cu['cod']] + ' (lista) · ' + cu['tabela'], 'detail': f'{onde(cu["cod"])} chama o programa corporativo {mapa[cu["cod"]]}, que lê a lista de {cu["tabela"]}', 'cor': cor})
                    else:
                        fn.append({'id': cid, 'col': 1, 'label': onde(cu['cod']), 'sub': 'executa o cursor ' + cu['cod'] + ' · ' + cu['tabela'], 'detail': f'{onde(cu["cod"])} executa {cu["cod"]} ({cu["programa"]}): {cu["sql"]}', 'cor': cor})
                fa[('f-' + f, cid)] = 'chama'
            else:
                fn.append({'id': cid, 'col': 1, 'label': cu['cod'], 'sub': 'cursor · ' + cu['tabela'], 'detail': f'{cu["cod"]} ({cu["programa"]}): {cu["sql"]}', 'cor': cor})
                fa[('f-' + f, cid)] = 'abre o cursor'
            for q in alvos:
                tid = f't-{f}-{mapa[q] if q in mapa else fn_prog(q) or (onde(q) if (onde and q in cmds) else q)}'
                if tid not in fv:
                    fv.add(tid)
                    if q in mapa:
                        fn.append({'id': tid, 'col': 2, 'label': mapa[q], 'sub': 'chama o programa corporativo a cada linha', 'detail': f'{onde(q) if onde else ""} chama o programa corporativo {mapa[q]} a cada linha', 'cor': cor})
                    elif q in cmds and onde:
                        fn.append({'id': tid, 'col': 2, 'label': onde(q), 'sub': f'executa {q} a cada linha', 'detail': f'{onde(q)} executa {q} ({cmds[q]["programa"]}): {cmds[q]["sql"]}', 'cor': cor})
                    elif q in cmds:
                        fn.append({'id': tid, 'col': 2, 'label': q, 'sub': 'query a cada linha', 'detail': f'{q} ({cmds[q]["programa"]}): {cmds[q]["sql"]}', 'cor': cor})
                    elif fn_prog(q):
                        fn.append({'id': tid, 'col': 2, 'label': fn_prog(q), 'sub': 'chama o programa corporativo a cada linha', 'detail': f'{q} · {funcs[q]["nome"]}: chamada ao programa corporativo {fn_prog(q)} ({funcs[q]["base"]})', 'cor': cor})
                    else:
                        fn.append({'id': tid, 'col': 2, 'label': q, 'sub': 'chamada corporativa a cada linha', 'detail': f'{q} · {funcs[q]["nome"]} ({funcs[q]["base"]})', 'cor': cor})
                fa[(cid, tid)] = 'chamada a cada linha' + (' (candidata)' if not x else '')
    g = rs._grafo('Cursor → chamada a cada linha (cor = veredito de N+1)', ['Funcionalidade', 'Group Query ou Agregado que executa o cursor' if onde else 'Query com cursor', 'Chamada a cada linha do cursor'], fn,
                  [{'from': a_, 'to': b_, 'label': lab} for (a_, b_), lab in sorted(fa.items())], NOTA_GRAFO.replace('leitura da lista', 'cursor'), nw=230)
    g['legenda'] = _legenda_veredito()
    return [g,
            rm.T('Chamadas por funcionalidade', ['Id', 'Funcionalidade', 'Queries executadas', 'Queries com cursor', 'Chamadas corporativas', 'Candidatas a chamada por linha (evidência)', 'Chamadas fixas', 'Fórmula de chamadas',
                                                         'N+1 (IA)', 'Chamadas por linha confirmadas (IA)', 'Resumo das chamadas (IA)', 'Latência (IA)', 'Gravidade (IA)'], lin),
            rm.T('Cursores e candidatas a N+1', ['Funcionalidade', 'Query com cursor', 'Tabela', *(['Executa em'] if onde else []), 'Dado entregue a', 'Candidatas por linha (evidência)', 'Executam antes do cursor (evidência)', 'Passos com laço (fase 12)', 'N+1 (IA)',
                                                         'Mitigação (IA)', 'Recomendação (IA)', 'Confiança (IA)', 'Evidência (IA)'], cur)]


def secao_analise(evid, interp, comp_pc):
    """Vereditos de N+1, prós e contras da estratégia, premissas e lacunas da análise da IA."""
    ix = _ix(interp)
    n = lambda c, v: sum(1 for x in ix.values() if x.get(c) == v) if ix else '—'   # noqa: E731
    tot = lambda c: sum(e['cen']['C'][c] for e in evid.values())   # noqa: E731
    resumo = [('Soma das chamadas fixas das funcionalidades', tot('fixas')),
              ('Soma das chamadas repetidas por linha (multiplicadas por N)', tot('n_linha')),
              ('Funcionalidades com N+1 sem mitigação (IA)', n('veredito', 'sim')),
              ('Funcionalidades com N+1 mitigado (IA)', n('veredito', 'mitigado')),
              ('Funcionalidades com gravidade alta (IA)', n('gravidade', 'alta'))]
    blocos = [rm.T('Resumo das chamadas', ['Medida', 'Valor'], resumo),
              comp_pc,
              rm.T('Vereditos de N+1', ['Veredito', 'Significado'], [
                  ('sim: N+1', 'a cada linha lida o fluxo faz mais uma consulta ou chamada: com N linhas, 1 leitura + N chamadas, e a latência cresce com N'),
                  ('mitigado', 'a repetição existiria, mas o próprio fluxo a reduz (por exemplo, só consulta quando o valor muda em relação à linha anterior, ou reaproveita o resultado)'),
                  ('não', 'a leitura percorre as linhas sem chamar nada a cada linha: o custo é o da leitura e das chamadas fixas'),
                  ('sem cursor', 'a funcionalidade não percorre linhas por cursor: o número de chamadas é fixo')])]
    if interp:
        blocos.append(rm.T('Premissas assumidas pela IA', ['Premissa', 'Detalhe'], [(l.get('item', l.get('assunto', '')), l.get('detalhe', '')) for l in interp['premissas']]))
        blocos.append(rm.T('Lacunas', ['Assunto', 'Detalhe'], [(l.get('assunto', ''), l.get('detalhe', '')) for l in interp['lacunas']]))
    else:
        blocos.append(rm.X('AVISO: sem interpretação (interpretacao-relacao/*.json, prompt 8). A seção mostra só a evidência calculada.'))
    return rm.S('analise', 'Desempenho da estratégia: chamadas, latência e N+1', blocos,
                'Resume as chamadas e o N+1 das funcionalidades na estratégia adotada (queries de uma tabela e gravações nos agregados; queries de várias tabelas em Query Legacy, ligadas a um Group Query; agregados corporativos chamando os programas corporativos originais por meio de LEGACY). A evidência é calculada dos relatórios; o julgamento é da IA, sem tempos nem volumes, que os relatórios não trazem.')


def modelo(ev, de, interp=None):
    funcs, cmds, prop, dom = ev['funcs'], ev['cmds'], de['prop'], ev['dominio']
    pl = plano(ev, de)
    dec, qs, nfs = pl['dec'], pl['qs'], pl['nfs']
    tabs = de['tabelas']
    unicas = [c for c in sorted(cmds.values(), key=lambda x: x['cod']) if c['cod'] not in dec]
    cards = [rm.card('funcionalidades', len(funcs)), rm.card('comandos SQL', len(cmds)), rm.card('tabelas', len(tabs)), rm.card('queries multi-owner', len(dec)),
             ]
    secs = []
    classe_ag = {}
    ordem_cl = [LEIT, EXCL, COMP]
    for t in tabs:
        ag = dom.get(t, {}).get('agregado') or t
        classe_ag[ag] = max(classe_ag.get(ag, LEIT), prop[t]['classificacao'], key=ordem_cl.index)
    ordem_func = {f: k for k, f in enumerate(list(funcs) + [n['id'] for n in nfs])}
    cat_ag = {}   # categoria do agregado (fase 16): Business core ou Corporativo
    for t in tabs:
        cat_ag.setdefault(dom.get(t, {}).get('agregado') or t, dom.get(t, {}).get('categoria') or 'Business core')
    corp_ag = lambda ag: cat_ag.get(ag) == 'Corporativo'   # noqa: E731
    sub_ag = lambda ag: 'Agregado corporativo' if corp_ag(ag) else 'Agregado Business core'   # noqa: E731

    def no_func(f, fn, fv):
        if 'f-' + f not in fv:
            fv.add('f-' + f)
            fn.append({'id': 'f-' + f, 'col': 0, 'label': f, 'sub': funcs[f]['tipo'], 'detail': f'{f} · {funcs[f]["nome"]} ({funcs[f]["base"]})', 'cor': rs.NEUTRA})

    def no_agregado(ag, fn, fv):
        if 'ag-' + ag not in fv:
            fv.add('ag-' + ag)
            fn.append({'id': 'ag-' + ag, 'col': 2, 'label': ag, 'sub': 'Agregado', 'detail': f'{ag}: raiz {ev["raiz"].get(ag, "—")}; {classe_ag.get(ag, "")}', 'cor': COR_DONO[classe_ag.get(ag, LEIT)]})

    # decisões por query (base de cálculo das chamadas) e evidência de chamadas por funcionalidade
    _b, dA, dB = cenarios(ev, de)
    evid = evidencia_chamadas(ev, dA, dB)
    todos = sorted(cmds.values(), key=lambda x: x['cod'])
    func_do = lambda c: sorted(set(c['func_exec']) | set(c['func_invocam']), key=lambda x: ordem_func[x])   # noqa: E731
    cor_cmd = lambda c: COR_SQL_GRAVA if c['grava'] else COR_SQL_LE   # noqa: E731
    classif = lambda c: pexib(c['padrao'])   # classificação: AGGREGATION, CONDITIONAL_UPDATE, DIRECT_INSERT, DIRECT_SELECT, FILTERED_SELECT, MULTI_TABLE_JOIN ou SELECT_CURSOR   # noqa: E731
    tab_ag = lambda c, ag: ', '.join(t for t in c['tabelas'] if (dom.get(t, {}).get('agregado') or t) == ag) or ', '.join(c['tabelas'])   # noqa: E731

    def liga_corp(fn, fa, fv, no_f):
        """Ligações entre funcionalidades (só as que existem na fase 12): entry point -> corporativa e corporativa -> corporativa. Reposiciona as colunas: entry points à esquerda, corporativas em seguida
        (as chamadas por outra corporativa mais à direita da que chama) e, depois delas, as colunas de col >= 2. Devolve (linhas da tabela, nomes das colunas das funcionalidades)."""
        rows = []
        for f in funcs:
            for g in dict.fromkeys(ev['corp'].get(f, {}).get('chama', [])):
                if g != f and funcs[g]['natureza'] == 'programa corporativo' and 'f-' + g in fv:
                    no_f(f)
                    fa[('f-' + f, 'f-' + g)] = 'chama a funcionalidade corporativa'
                    rows.append((f, funcs[f]['nome'], 'entry point' if funcs[f]['natureza'] == 'entry point' else 'corporativa', g, funcs[g]['nome']))
        nivel = {f: 0 for f in funcs if 'f-' + f in fv and funcs[f]['natureza'] == 'programa corporativo'}
        cc = [(f, g) for f, _n, nat, g, _ng in rows if nat == 'corporativa']
        for _ in range(len(nivel) + 1):
            for f, g in cc:
                if nivel[g] < nivel[f] + 1 and nivel[f] + 1 < len(nivel):
                    nivel[g] = nivel[f] + 1
        ncp = max(nivel.values(), default=0) + 1
        for n_ in fn:
            if n_['id'].startswith('f-') and n_['id'][2:] in nivel:
                n_['col'] = 1 + nivel[n_['id'][2:]]
            elif n_['col'] >= 2:
                n_['col'] += ncp - 1
        return rows, ['Funcionalidade entry point', 'Funcionalidade corporativa'] + [f'Funcionalidade corporativa chamada por outra corporativa (nível {k + 1})' if k > 1 else 'Funcionalidade corporativa chamada por outra corporativa' for k in range(1, ncp)]

    leg_ag = [{'texto': 'agregado ' + k.lower().replace('_', ' '), 'cor': v} for k, v in COR_DONO.items()]

    usados = Counter(pexib(c['padrao']) for c in cmds.values())
    # a funcionalidade nunca liga direto a um comando SQL: liga a um Group Query ou a um Agregado, e esses executam os comandos ou chamam o programa corporativo.
    # Leituras de uma só tabela e gravações: executadas pelo agregado dono. Leituras de várias tabelas: Legacy Query dentro de um Group Query
    # (um Group Query reúne Legacy Queries com as mesmas tabelas ou usadas por mais de uma funcionalidade; a Legacy Query sem par tem um Group Query só dela).
    por_tab = defaultdict(list)
    for c in todos:
        if not c['grava'] and len({dom.get(t_, {}).get('agregado') or t_ for t_ in c['tabelas']}) > 1:   # várias tabelas do MESMO agregado são consulta do agregado, não Group Query
            por_tab[tuple(sorted(c['tabelas']))].append(c)
    grupos, gq_info = {}, {}
    k_ = 0
    compart = [(t_, v_) for t_, v_ in sorted(por_tab.items()) if len(v_) > 1 or any(len(func_do(c)) > 1 for c in v_)]
    sozinhas = [(t_, v_) for t_, v_ in sorted(por_tab.items()) if (t_, v_) not in compart]
    for tabs_, cs_ in compart + sozinhas:
        k_ += 1
        gid = 'GQ_' + '_'.join(sorted(dom.get(t_, {}).get('classe') or t_ for t_ in tabs_))   # nome coeso: as classes de domínio (fase 16) das tabelas que a Group Query consulta
        motivo = []
        if len(cs_) > 1:
            motivo.append('Legacy Queries com as mesmas tabelas')
        if any(len(func_do(c)) > 1 for c in cs_):
            motivo.append('query usada por mais de uma funcionalidade')
        gq_info[gid] = {'tabelas': list(tabs_), 'queries': [c['cod'] for c in cs_], 'motivo': ' e '.join(motivo) or 'Legacy Query sem par: o Group Query é só dela, porque a funcionalidade não liga direto ao comando SQL',
                        'funcs': sorted({f for c in cs_ for f in func_do(c)}, key=lambda x: ordem_func[x])}
        for c in cs_:
            grupos[c['cod']] = gid
    cen_ = 'C'   # a estratégia adotada (os nomes internos da evidência de chamadas usam esta chave)
    fn, fa, fv, rel = [], {}, set(), []

    def simples_ag_(c):
        return (not c['grava']) and len({dom.get(t_, {}).get('agregado') or t_ for t_ in c['tabelas']}) == 1

    def no_func_b(f):
        if 'f-' + f not in fv:
            fv.add('f-' + f)
            cp = funcs[f]['natureza'] == 'programa corporativo'
            fn.append({'id': 'f-' + f, 'col': 1 if cp else 0, 'label': f, 'sub': (('chamada ao programa corporativo ' + funcs[f]['programa'] + ' · ') if cp else 'entry point · ') + funcs[f]['tipo'], 'detail': f'{f} · {funcs[f]["nome"]} ({funcs[f]["base"]})' + (f': chamada ao programa corporativo {funcs[f]["programa"]}' if cp else ''), 'cor': rs.NEUTRA})
    LEGACY = 'LEGACY'
    COR_PROG_CORP = '#6A1B9A'

    def ags_exec(c):
        simples_ = (not c['grava']) and len({dom.get(t_, {}).get('agregado') or t_ for t_ in c['tabelas']}) == 1
        return agregados_do_cmd(ev, c, dA) if (c['grava'] or simples_) else []
    # o comando que o agregado CORPORATIVO executaria passa a ser uma chamada ao programa corporativo original (atrás de uma LEGACY)
    # programa corporativo que nenhum entry point chama e que outro programa corporativo chama (CICS LINK) roda por dentro dele: o agregado não o chama
    entry_chama = {g for h in funcs if funcs[h]['natureza'] == 'entry point' for g in ev['corp'].get(h, {}).get('chama', [])}
    interno_f = {g for g in funcs if funcs[g]['natureza'] == 'programa corporativo' and g not in entry_chama and any(g in ev['corp'].get(h, {}).get('chama', []) for h in funcs if h != g)}
    chamador = {funcs[g]['programa']: sorted({funcs[h]['programa'] for h in funcs if g in ev['corp'].get(h, {}).get('chama', []) and h != g}) for g in interno_f}
    internos = {p_ for p_ in chamador if not any(funcs[g]['programa'] == p_ and g not in interno_f for g in funcs)}
    interno_c = {c['cod'] for c in todos if c['programa'] in internos}
    corp_c = {c['cod'] for c in todos if c['cod'] not in interno_c and ags_exec(c) and not grupos.get(c['cod']) and all(corp_ag(a_) for a_ in ags_exec(c))}
    prog_tabs, prog_grava, prog_cmds = defaultdict(set), defaultdict(bool), defaultdict(list)
    for c in todos:
        if c['cod'] in corp_c:
            prog_tabs[c['programa']] |= set(c['tabelas'])
            prog_grava[c['programa']] = prog_grava[c['programa']] or c['grava']
            prog_cmds[c['programa']].append(c['cod'])
    vistas_c = set()
    for c in todos:
        if c['cod'] in interno_c:
            continue   # roda por dentro do programa corporativo que o chama
        ags_c = ags_exec(c)
        gid = grupos.get(c['cod'])
        cc = c['cod'] in corp_c
        if cc:
            qid = 'q-' + c['programa']
            if qid not in fv:
                fv.add(qid)
                fn.append({'id': qid, 'col': 5, 'label': c['programa'], 'sub': LEGACY, 'detail': f'programa corporativo {c["programa"]}: chamado pelo agregado corporativo por meio de LEGACY; executa os comandos SQL do agregado ({", ".join(sorted(prog_cmds[c["programa"]]))})', 'cor': COR_PROG_CORP})
        else:
            qid = 'q-' + c['cod']
            fn.append({'id': qid, 'col': 5, 'label': c['cod'], 'sub': classif(c), 'detail': f'{c["cod"]} ({c["programa"]}, {"grava" if c["grava"] else "lê"}): {c["sql"]}', 'cor': cor_cmd(c)})
        for ag in ags_c:
            if 'as-' + ag not in fv:
                fv.add('as-' + ag)
                fn.append({'id': 'as-' + ag, 'col': 4 if corp_ag(ag) else 3, 'label': ag, 'sub': sub_ag(ag), 'detail': f'{ag} ({sub_ag(ag).lower()}): raiz {ev["raiz"].get(ag, "—")}; {classe_ag.get(ag, "")}. ' + ('Chama o programa corporativo original por meio de LEGACY' if corp_ag(ag) else 'Executa dentro dele as queries de uma só tabela e as gravações'), 'cor': COR_DONO[classe_ag.get(ag, LEIT)]})
            fa[('as-' + ag, qid)] = 'chama o programa corporativo (LEGACY)' if cc else 'executa dentro do agregado'
        if gid:
            if 'g-' + gid not in fv:
                fv.add('g-' + gid)
                gi = gq_info[gid]
                fn.append({'id': 'g-' + gid, 'col': 2, 'label': gid, 'sub': f'Group Query · {len(gi["queries"])} Legacy Quer{"ies" if len(gi["queries"]) > 1 else "y"}', 'detail': f'{gid}: executa as Legacy Queries {", ".join(gi["queries"])} ({", ".join(gi["tabelas"])}); {gi["motivo"]}', 'cor': COR_PASSO_E['QUERY_SERVICE']})
            fa[('g-' + gid, qid)] = 'executa a Legacy Query'
        for f in c['func_exec']:   # só a funcionalidade que executa o comando liga ao Group Query ou ao agregado; quem a invoca liga a ela
            no_func_b(f)
            for ag in ags_c:
                fa[('f-' + f, 'as-' + ag)] = 'chama o agregado'
            if gid:
                fa[('f-' + f, 'g-' + gid)] = 'chama o Group Query'
            if cc:
                if f in interno_f:
                    continue   # função que só roda por dentro de outro programa corporativo
                if (f, c['programa']) in vistas_c:
                    continue
                vistas_c.add((f, c['programa']))
                rel.append((f, funcs[f]['nome'], c['programa'], c['programa'], 'CALL', 'grava' if prog_grava[c['programa']] else 'lê', LEGACY, ', '.join(sorted(prog_tabs[c['programa']])), '—', ', '.join(ags_c),
                            'a funcionalidade chama o agregado corporativo, que chama o programa corporativo original por meio de LEGACY; o programa executa o SQL'))
                continue
            rel.append((f, funcs[f]['nome'], c['cod'], ', '.join(c['programas']), c['operacao'], 'grava' if c['grava'] else 'lê', pexib(c['padrao']), ', '.join(c['tabelas']), gid or '—', ', '.join(ags_c) or '—',
                        ('a funcionalidade chama o agregado, que executa o comando' if (c['grava'] or simples_ag_(c)) else f'a funcionalidade chama o Group Query {gid}, que executa a Legacy Query (mantida como descoberta)')))
    internos_rows = [(p_, ', '.join(chamador[p_]), ', '.join(f_ for f_ in funcs if funcs[f_]['programa'] == p_), ', '.join(c['cod'] for c in todos if c['programa'] == p_)) for p_ in sorted(internos)]
    padr_c = [x_ for x_ in [(p_, EXPLICA.get(p_, ('—', '—'))[0], EXPLICA.get(p_, ('—', '—'))[1], sum(1 for c in todos if pexib(c['padrao']) == p_ and c['cod'] not in corp_c), ', '.join(c['cod'] for c in todos if pexib(c['padrao']) == p_ and c['cod'] not in corp_c) or '—') for p_, _n in sorted(usados.items())] if x_[3]] + [(LEGACY, 'chama', 'camada que isola o agregado corporativo do programa corporativo original: traduz a chamada do domínio para a interface do programa e devolve o resultado no modelo do domínio', len(prog_cmds), ', '.join(sorted(prog_cmds)) or '—')]
    chama_corp, cols_fb = liga_corp(fn, fa, fv, no_func_b)
    gB = rs._grafo('Funcionalidade → Group Query ou Agregado → comando SQL ou programa corporativo (LEGACY)', cols_fb + ['Group Query (Legacy Queries)', 'Agregado Business core', 'Agregado corporativo', 'Comando SQL (Legacy Query, query de uma tabela ou gravação) ou programa corporativo original (LEGACY)'], fn,
                   [{'from': a_, 'to': b_, 'label': lab} for (a_, b_), lab in sorted(fa.items())],
                   'Só aparecem ligações diretas. A funcionalidade que executa o comando liga ao agregado ou ao Group Query; o entry point que usa um programa corporativo liga à funcionalidade corporativa, nunca ao comando, e a corporativa que chama outra corporativa liga a ela. As queries de uma só tabela e as gravações (INSERT, UPDATE, DELETE) são executadas pelo agregado dono (Business core ou corporativo). As queries de várias tabelas são mantidas como descobertas, cada uma em Query Legacy, dentro de um Group Query que reúne as Legacy Queries com as mesmas tabelas ou usadas por mais de uma funcionalidade (a Legacy Query sem par tem um Group Query só dela). Cor do comando: verde-água lê, roxo grava. O agregado corporativo não executa SQL: chama o programa corporativo original por meio de LEGACY, em roxo escuro.', nw=230)
    gB['legenda'] = [{'texto': 'Group Query', 'cor': COR_PASSO_E['QUERY_SERVICE']}, {'texto': 'query que lê', 'cor': COR_SQL_LE}, {'texto': 'comando de gravação', 'cor': COR_SQL_GRAVA}] + [{'texto': 'programa corporativo (LEGACY)', 'cor': COR_PROG_CORP}] + leg_ag
    gq_rows = [(gid, ', '.join(gi['tabelas']), ', '.join(gi['queries']), ', '.join(gi['funcs']), gi['motivo']) for gid, gi in sorted(gq_info.items())]
    secs.append(rm.S('estrategia', 'Estratégia de acesso aos dados: a funcionalidade chama Group Query ou Agregado; queries de uma tabela e gravações nos agregados, queries de várias tabelas em Legacy Query dentro de Group Query; os agregados corporativos chamam os programas corporativos originais (LEGACY)', [
        gB, rm.T('Relação por funcionalidade', ['Funcionalidade', 'Nome', 'Query', 'Programa', 'Operação', 'Natureza', 'Padrão SQL', 'Tabelas', 'Group Query', 'Agregado', 'Como é executada'], rel),
        rm.T('Group Queries', ['Group Query', 'Tabelas', 'Legacy Queries ligadas', 'Funcionalidades', 'Por que'], gq_rows),
        *([rm.T('Programas corporativos chamados por outro programa corporativo', ['Programa corporativo', 'Chamado por', 'Funcionalidade', 'Comandos SQL que executa'], internos_rows)] if internos_rows else []),
    rm.T('Funcionalidades que chamam funcionalidades corporativas', ['Funcionalidade que chama', 'Nome', 'Tipo de quem chama', 'Funcionalidade corporativa chamada', 'Nome da corporativa'], chama_corp),
        rm.T('Padrões de query', ['Padrão', 'Natureza', 'O que é', 'Comandos', 'Quais'], padr_c)] + ([rm.T('Queries únicas (comandos equivalentes unificados na fase 10)', ['Query', 'Comandos unificados'],
        [(q_, ', '.join([q_] + sorted(a_ for a_, b_ in ev['alias'].items() if b_ == q_))) for q_ in sorted(set(ev['alias'].values()))])] if ev['alias'] else []) + analise_q(ev, interp, evid, mapa=({c_['cod']: c_['programa'] for c_ in todos if c_['cod'] in corp_c} | {c_['cod']: chamador[c_['programa']][0] for c_ in todos if c_['cod'] in interno_c}), onde=lambda q_: grupos.get(q_) or ', '.join(agregados_do_cmd(ev, cmds[q_], dA))),
        f'As leituras de uma só tabela são executadas pelos agregados; as de várias tabelas ficam em Query Legacy, e {sum(len(g["queries"]) for g in gq_info.values())} delas foram agrupadas em {len(gq_info)} Group Queries (mesmas tabelas ou uso por mais de uma funcionalidade). As gravações (INSERT, UPDATE, DELETE) são executadas dentro dos agregados, e os agregados corporativos chamam os programas corporativos originais por meio de LEGACY. Depois, por funcionalidade, analisa chamadas, latência e N+1.'))


    comp_pc = rm.T('Prós, contras, latência e complexidade da estratégia', ['Critério', 'Avaliação'], [
        ('Prós', 'nada é redesenhado nas leituras de várias tabelas (Query Legacy); leitura em uma consulta só, boa para listas, paginação e lotes; o Group Query agrupa as Legacy Queries das mesmas tabelas ou usadas por várias funcionalidades; reaproveita os programas corporativos já testados e mantidos por outra equipe, e a camada LEGACY protege o modelo novo do legado'),
        ('Contras', 'mantém o acoplamento ao modelo legado nas Legacy Queries; depende dos programas corporativos originais (mainframe) e da camada LEGACY, mais um componente a operar; o Group Query é mais um componente a manter'),
        ('Latência', 'uma chamada por consulta: as leituras de uma tabela vão ao agregado, as de várias tabelas executam localmente na Query Legacy, e nos agregados corporativos a chamada ao programa corporativo substitui a execução do SQL, somando o tempo do programa e da camada LEGACY'),
        ('Complexidade', 'baixa de início (nada é reescrito no domínio corporativo nem nas leituras de várias tabelas); a complexidade passa para a camada LEGACY e para o contrato com os programas originais')])
    secs.append(secao_analise(evid, interp, comp_pc))
    cards.append(rm.card('funcionalidades com cursor', sum(1 for e in evid.values() if e['cursores'])))
    if interp:
        cards.append(rm.card('com N+1', sum(1 for x in interp['funcionalidades'] if x.get('veredito') == 'sim')))
    return rm.model('Segregação de Responsabilidades', 'Queries de uma tabela e gravações nos agregados, queries de várias tabelas em Query Legacy com Group Query e os agregados corporativos chamando os programas corporativos originais (LEGACY), com a análise de chamadas, latência e N+1', cards, secs)


def main():
    global BASE
    args = sys.argv[1:]
    if '--interpretacao' in args:
        i = args.index('--interpretacao')
        BASE = Path(args[i + 1]).resolve()
        del args[i:i + 2]
    if not args:
        sys.exit(__doc__)
    ana = Path(args[0])
    saida = Path(args[1]) if len(args) > 1 else ana
    ev = coletar(ana)
    de = deduzir(ev)
    interp = ler_interp(BASE)
    if interp is not None:
        normalizar_interp(interp, ev['alias'])
    erros, falhas = [], []
    if interp is None:
        print('AVISO: sem interpretacao-relacao/*.json (prompt 8): a análise por funcionalidade mostra só a evidência calculada')
    else:
        _b, dA, dB = cenarios(ev, de)
        erros, falhas = validar(ev, evidencia_chamadas(ev, dA, dB), interp)
        if erros:
            raise SystemExit('interpretação inconsistente com os relatórios:\n  ' + '\n  '.join(erros))
    S.escrever(saida, FASE, modelo(ev, de, interp))
    print(f'{len(ev["funcs"])} funcionalidades, {len(ev["cmds"])} comandos, {len(de["tabelas"])} tabelas, {len(de["joins"])} JOINs multi-owner; afirmações sem evidência: {len(falhas)}')
    for x in falhas:
        print('  ' + x)
    sys.exit(1 if falhas else 0)


if __name__ == '__main__':
    main()
