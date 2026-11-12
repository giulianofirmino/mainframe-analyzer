#!/usr/bin/env python3
"""Relatório target-architecture (fase 19, evidência determinística + decisões da IA): arquitetura alvo do sistema modernizado, na estratégia de acesso aos dados da fase 17 (agregados, Query Legacy com Group Query e LEGACY nos agregados corporativos),
lida ÚNICA E EXCLUSIVAMENTE dos relatórios gerados (<fase>/ia/report.json das fases 03 data-schema, 10 sql-mapping, 12 business-flows, 15 user-interface-mapping,
16 domain-model, 17 responsibility-segregation e 18 context-discovery). Mesma entrada → mesma saída, sem IA.

  python3 gerar_target_architecture.py <pasta-da-analise> [pasta-de-saida] [--interpretacao PASTA]   (padrão da saída: a pasta da análise)

Saída: <saida>/19 - target-architecture/human/report.html, <saida>/19 - target-architecture/ia/report.json (o mesmo modelo de visão) e
<saida>/19 - target-architecture/ia/architecture-resource-model.yaml (o modelo de recursos canônico; todos os diagramas saem dele).
Transformação:
  Delivery Context Presentation → MFE + BFMF; Delivery Context Query → VAS; Domain Context → DOMAIN_MICROSERVICE;
  cada comando SQL → MQ_REQ + MQ_RSP + PROGRAM_DB2 (o programa mainframe que observa a fila de pedido e responde na fila de resposta); cada programa corporativo chamado
  pelo domínio corporativo → as mesmas filas + PROGRAM_CORP (programa mainframe novo que chama o programa corporativo original).
Os nomes de programas e copybooks já atribuídos ficam em nomes-atribuidos.json (pasta da interpretação) e são mantidos; só comando novo recebe nome pela regra.
Conteúdo: modelo de recursos e protocolos, diagramas C4 (níveis 1, 2 e 3), diagramas de sequência (um por funcionalidade) e especificações UX.
A interpretação da IA (prompt 10, interpretacao-arquitetura/*.json) traz decisões, premissas e lacunas com confiança; é validada contra o modelo."""
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import gerar_context_discovery as CD
import gerar_responsibility_segregation as QS
import gerar_simulacao as S
import report_model as rm  # noqa: E402
import report_resumo as rs  # noqa: E402

AQUI = Path(__file__).resolve().parent
BASE = Path(os.environ['ANALISE_INTERPRETACOES']) if os.environ.get('ANALISE_INTERPRETACOES') else AQUI   # pasta das interpretações (a análise); o pipeline a informa
FASE = '19 - target-architecture'
# um só modelo de arquitetura; 'C' é só a chave interna do modelo (as fases 20 e 21 reaproveitam os modelos em memória)
CENARIOS = {'C': 'estratégia de acesso aos dados da fase 17'}
PREF_TITULO = {'C': ''}
GQS = set()   # nomes dos Group Queries (fase 17): só agrupam queries, não contam nos diagramas
PROGRAMA_COL = 'PROGRAM_DB2'
INTERNOS = {}   # programas corporativos chamados por outro programa corporativo
INFO = {}   # comando original → operações e tabelas (fase 10)
CORP = {}   # programa corporativo → comandos SQL originais que ele executa (preenchido em preparar)
TIPOS = {'HOST': 'Shell de microfrontends', 'MFE': 'Micro Frontend', 'BFMF': 'Backend for Micro Frontend', 'VAS': 'Value-Added Service',
         'DOMAIN_MICROSERVICE': 'Microserviço Java/Spring Boot, um por Domain Context',
         'MQ_REQ': 'Fila IBM MQ de baixa de pedido: a aplicação envia nela a informação do comando SQL a ser executado por um programa mainframe; a fila de alta de pedido a recebe daí',
         'MQ_REQ_ALTA': 'Fila IBM MQ de alta de pedido: recebe da fila de baixa de pedido e o programa mainframe lê dela',
         'MQ_RSP_ALTA': 'Fila IBM MQ de alta de resposta: o programa mainframe responde nela e a fila de baixa de resposta recebe daí',
         'MQ_RSP': 'Fila IBM MQ de baixa de resposta: recebe da fila de alta de resposta e a aplicação lê dela o retorno da informação do comando SQL executado por um programa mainframe',
         'PROGRAM_DB2': 'Programa mainframe que recebe a informação e executa o comando SQL no DB2',
         'PROGRAM_CORP': 'Programa mainframe novo que recebe a informação e chama o programa corporativo original, que executa o SQL',
         'PROGRAM_COORD': 'Programa mainframe coordenador: lê a fila de alta de pedido, chama o programa funcional (PROGRAM_DB2 ou PROGRAM_CORP) e responde na fila de alta de resposta'}
APPS = ('BFMF', 'VAS', 'DOMAIN_MICROSERVICE')   # aplicações que têm MQ_ADAPTER por dentro e falam direto com as filas
PERMITIDOS = {('MFE', 'BFMF', 'REST'), ('BFMF', 'VAS', 'REST'), ('BFMF', 'DOMAIN_MICROSERVICE', 'REST'), ('DOMAIN_MICROSERVICE', 'DOMAIN_MICROSERVICE', 'REST'),
              ('MQ_REQ', 'MQ_REQ_ALTA', 'ENCAMINHA'), ('MQ_REQ_ALTA', 'PROGRAM_DB2', 'RECEIVE_ALTA'), ('PROGRAM_DB2', 'MQ_RSP_ALTA', 'SEND_ALTA'), ('MQ_RSP_ALTA', 'MQ_RSP', 'ENCAMINHA'),
              ('MQ_REQ_ALTA', 'PROGRAM_CORP', 'RECEIVE_ALTA'), ('PROGRAM_CORP', 'MQ_RSP_ALTA', 'SEND_ALTA'), ('HOST', 'MFE', 'HOSPEDA'),
              ('MQ_REQ_ALTA', 'PROGRAM_COORD', 'RECEIVE_ALTA'), ('PROGRAM_COORD', 'MQ_RSP_ALTA', 'SEND_ALTA'), ('PROGRAM_COORD', 'PROGRAM_DB2', 'LINK'), ('PROGRAM_COORD', 'PROGRAM_CORP', 'LINK')} | {(a, 'MQ_REQ', 'SEND_BAIXA') for a in APPS} | {('MQ_RSP', a, 'RECEIVE_BAIXA') for a in APPS}
FILA_OK = re.compile(r'^(FR\.[A-Z0-9]+\.[A-Z0-9]+\.NI[A-Z0-9]+\.REQ|FL\.[A-Z0-9]+\.[A-Z0-9]+\.NI[A-Z0-9]+\.RSP)$')   # filas de baixa: FR...REQ e FL...RSP
FILA_ALTA_OK = re.compile(r'^[A-Z0-9]+\.Q[LR]\.(REQ|RSP)\.[A-Z0-9]+\.NI[A-Z0-9]+\.\d{2}$')   # filas de alta: <SISTEMA>.QL.REQ.<SISTEMA>.NI<PROPÓSITO>.nn e <SISTEMA>.QR.RSP.<SISTEMA>.NI<PROPÓSITO>.nn
PROG_OK = re.compile(r'^[A-Z]{4}\d[A-Z]{3}$')   # padrão do programa mainframe: sistema (4 letras) + dígito + 3 letras
VERBOS = {'consulta': 'cons', 'lista': 'list', 'pesquisa': 'pesq', 'inclui': 'incl', 'altera': 'alt', 'exclui': 'excl', 'verifica': 'verif'}
VERBO_OP = {'SELECT': 'consulta', 'INSERT': 'inclui', 'UPDATE': 'altera', 'DELETE': 'exclui'}
CONF = {'CONFIRMED', 'UNCERTAIN', 'UNKNOWN'}
CHAVES_RAIZ = {'decisoes', 'premissas', 'lacunas', 'comandos', 'telas'}
STOP = {'de', 'e', 'para', 'do', 'da', 'dos', 'das', 'o', 'a', 'os', 'as', 'em', 'no', 'na', 'com', 'por', 'of', 'and', 'for', 'the'}
COR = {'HOST': '#546E7A', 'MFE': '#00695C', 'BFMF': '#2E7D32', 'VAS': '#1565C0', 'DOMAIN_MICROSERVICE': '#6A1B9A', 'MQ_REQ': '#C62828', 'MQ_REQ_ALTA': '#AD1457', 'MQ_RSP_ALTA': '#F9A825', 'MQ_RSP': '#EF6C00', 'PROGRAM_DB2': '#4E342E', 'PROGRAM_CORP': '#795548', 'PROGRAM_COORD': '#8D6E63', 'USER': '#455A64'}
PROGS = ('PROGRAM_DB2', 'PROGRAM_CORP', 'PROGRAM_COORD')


def digito_funcional():
    """Coordenador e funcional (analise.config.json, `programas_mainframe.funcional`): com o dígito, cada comando tem um coordenador <sistema>1 + 3 letras,
    que lê e responde nas filas, e um funcional <sistema><dígito> + as mesmas 3 letras, que executa o SQL ou chama o programa corporativo. Sem a chave, um só programa faz tudo."""
    import projeto_config
    return str((projeto_config.carregar().get('programas_mainframe') or {}).get('funcional') or '')
COR_CORP = '#EF6C00'
ID_OK = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')


def slug(t):
    t = unicodedata.normalize('NFKD', str(t)).encode('ascii', 'ignore').decode().lower()
    return '-'.join(x for x in re.split(r'[^a-z0-9]+', t) if x and x not in STOP)


def prefixo(ev):
    progs = [v['programa'] for v in ev['funcs'].values() if v['entry'] and v['programa']]
    p = progs[0] if progs else 'sis'
    for q in progs[1:]:
        k = 0
        while k < min(len(p), len(q)) and p[k] == q[k]:
            k += 1
        p = p[:k]
    p = re.sub(r'\d+$', '', p) or (progs[0][:4] if progs else 'sis')
    return p.lower()


def itens(t):
    return CD.itens(t)


def ler_fase18(ana):
    f18 = S.fase(ana, '18 ')
    # os Group Queries (fase 17) são só um agrupamento: não entram nas contagens nem nos diagramas, valem as queries que eles agrupam
    gqs = {r['Group Query'] for _s, bt, rows in S.tabelas(S.fase(ana, '17 ')) if bt.endswith('Group Queries') for r in rows}
    GQS.clear(), GQS.update(gqs)
    d = {'dcs': [], 'dom': [], 'rels': [], 'cmds': []}
    for _s, bt, rows in S.tabelas(f18):
        if bt == 'Delivery Contexts':
            d['dcs'] = [{'id': r['Contexto'], 'nome': r['Nome'], 'tipo': r['Tipo'], 'comps': itens(r['Componentes']), 'telas': itens(r['Telas mantidas (fase 15)']), 'consumido': itens(r['Consumido por']),
                         'estrategia': r['Estratégia de leitura'], 'jornada': r['Jornada ou finalidade (IA)']} for r in rows]
        elif bt == 'Domain Contexts':
            d['dom'] = [{'id': r['Contexto'], 'nome': r['Nome'], 'raiz': r['Agregado raiz'], 'agregado': r['Agregado raiz'].split(' (')[0], 'categoria': r['Categoria'], 'comps': itens(r['Componentes (classes e comandos)']),
                         'funcs': itens(r['Funcionalidades que o usam'])} for r in rows]
        elif bt == 'Relacionamentos do mapa de contextos':
            d['rels'] = [{'de': r['De'], 'para': r['Para'], 'tipo_de': r['Tipo de origem'], 'tipo_para': r['Tipo de destino'], 'relacao': r['Relação'], 'protocolo': r['Protocolo (IA)']} for r in rows]
        elif bt == 'Comandos SQL mapeados dentro dos contextos':
            d['cmds'] = [(r['Comando'], r['Classificação'], r['Contexto'], r['Nome do contexto'], r['Tipo do contexto']) for r in rows]
    if not d['dom'] or not d['cmds']:
        raise SystemExit('fase 18: tabelas do mapa de contextos não encontradas (rode a fase 18 antes)')
    return {'C': d}


def ler_fase10(ana):
    """Comando (código da query) → operação e tabelas, lidas das tabelas '<query>: onde e quando executa'."""
    info = {}
    for _s, bt, rows in S.tabelas(S.fase(ana, '10 ')):
        m = re.match(r'(\S+): onde e quando executa$', bt)
        if m:
            info[m.group(1)] = {'operacoes': sorted({r.get('Operação','') for r in rows}), 'tabelas': sorted({r.get('Tabela','').split('.')[-1] for r in rows}), 'cursor': any(r.get('Cursor','') not in ('', '—') for r in rows), 'programas': sorted({r.get('Programa', '') for r in rows})}
    return info


def ler_fase3(ana):
    papel = {}
    for _s, bt, rows in S.tabelas(S.fase(ana, '03-')):
        if bt.startswith('Tabelas, papel e o que justifica o papel'):
            for r in rows:
                papel[r['Tabela']] = r['Papel']
    return papel


TAB_CLASSE = {}   # tabela → classe de domínio, preenchido em main
REGRAS = {}   # funcionalidade → regras de negócio do fluxo interno (fase 12), preenchido em main


def ler_regras(ana, simb):
    """Regras de negócio de cada funcionalidade, na ordem do fluxo interno (fase 12): título, tipo (regra ou erro) e as classes de domínio que o texto da regra toca."""
    out = {}
    for _s, bt, rows in S.tabelas(S.fase(ana, '12 ')):
        m = re.match(r'(\S+): nós do fluxo interno', bt)
        if not m:
            continue
        for r in rows:
            if r.get('Tipo') not in ('regra', 'erro'):
                continue
            texto = ' '.join(str(r.get(k, '')) for k in ('Nome', 'Entra', 'Sai'))
            classes = sorted({simb.classe[t] for t in simb.classe if simb.classe[t] and re.search(r'\b' + re.escape(t) + r'\b', texto)})
            out.setdefault(m.group(1), []).append({'etapa': int(str(r.get('Etapa') or 0) or 0), 'tipo': r['Tipo'], 'nome': r.get('Nome', ''), 'classes': classes})
    return out


FLUXO = {}      # funcionalidade → nós SQL do fluxo interno (fase 12): [{'id', 'nome', 'cmds': comandos originais, 'alt': grupo de alternativas ou None}]
CHAMA_FLUXO = {}   # funcionalidade → funcionalidades corporativas que o fluxo chama (ligações "chama" da fase 12), na ordem do fluxo
CHAMA_NOS = {}   # funcionalidade → {nó do fluxo que chama uma função corporativa: função chamada}
FLUXO_IDS = {}   # funcionalidade → {nome da regra: id do nó no fluxo (V04.PROG, C14.PROG, E26.PROG...)}
CITADOS = {}    # funcionalidade → comandos citados como evidência nas ligações do fluxo (programas corporativos de consulta dinâmica, sem linhagem por linha)
CMD_RE = re.compile(r'\b([A-Z][A-Z0-9]{7}-Q\d+)(?:\.\d+)?\b')


def ler_fluxo(ana):
    """Liga o fluxo de negócio (fase 12) aos comandos SQL: cada nó SQL do fluxo (`C14.PROG`) tem a linhagem consultada na fase 11 (`PROG@linha`), e a linha identifica o comando original da fase 10.
    Alternativas: nós SQL que saem da mesma decisão por condições diferentes (só um deles executa em cada pedido)."""
    ev = QS.coletar(ana)
    nos = {}
    for _s, bt, rows in S.tabelas(S.fase(ana, '11 ')):
        m = re.match(r'([A-Z]\d+\.\S+): linhagem', bt)
        if m:
            for r in rows:
                mm = re.match(r'(\S+)@(\d+):', str(r.get('Id', '')))
                if mm:
                    nos.setdefault(m.group(1), []).append((mm.group(1), mm.group(2)))
        m2 = re.match(r'([A-Z]\d+\.\S+): evidência, condições e efeitos', bt)   # a gravação (INSERT, UPDATE) cita o comando no efeito da regra
        if m2:
            for r in rows:
                for pg, ln in re.findall(r'(\w+)@(\d+):', str(r.get('Efeitos e comandos', ''))):
                    if (pg, ln) not in nos.setdefault(m2.group(1), []):
                        nos[m2.group(1)].append((pg, ln))
    nome_no = {}
    for _s, bt, rows in S.tabelas(S.fase(ana, '11 ')):
        if bt == 'Regras de negócio reunidas':
            for r in rows:
                mm = re.match(r'([A-Z]\d+\.\S+)\s+(.*)$', str(r.get('Regra de negócio', '')))
                if mm:
                    nome_no[mm.group(1)] = mm.group(2)
    ids = set(ev['funcs'])
    fluxo, chama, citados = {}, {}, {}
    for _s, bt, rows in S.tabelas(S.fase(ana, '12 ')):
        m = re.match(r'(\S+): ligações do fluxo interno', bt)
        if not m:
            continue
        f = m.group(1)
        ordem, de_cond, arestas = [], defaultdict(list), []
        for r in rows:
            arestas.append((r['De'], r['Para'], r['Tipo']))
            for x in (r['De'], r['Para']):
                if re.match(r'^[A-Z]\d+\.\S+$', x) and x not in ordem:
                    ordem.append(x)
            if r['Tipo'] == 'chama' and r['Para'] in ids:
                chama.setdefault(f, [])
                if r['Para'] not in chama[f]:
                    chama[f].append(r['Para'])
            if r['Tipo'] == 'chama' and r['De'] in ids and r['Para'] in ids:
                chama.setdefault(r['De'], [])
                if r['Para'] not in chama[r['De']]:
                    chama[r['De']].append(r['Para'])
            if r['Tipo'] == 'condicao' and re.match(r'^[CA]\d+\.', r['Para']) and re.match(r'^(V\d+\.|ENTRADA)', r['De']):   # alternativas: saem da mesma validação por condições diferentes
                de_cond[r['De']].append(r['Para'])
            for c in CMD_RE.findall(str(r.get('Evidência citada', ''))):
                citados.setdefault(f, set()).add(c)
        alt = {}
        for de, ps in de_cond.items():
            ps = list(dict.fromkeys(ps))
            if len(ps) > 1:
                for n in ps:
                    alt[n] = de
        lista = []
        for n in ordem:
            if n not in nos:
                continue
            cm = []
            for prog, ln in nos[n]:
                for k, c in sorted(ev['cmds'].items()):
                    if prog in c['programas'] and ln in re.findall(r'\d+', c['linhas']) and k not in cm:
                        cm.append(k)
            if cm:
                lista.append({'id': n, 'nome': nome_no.get(n, ''), 'cmds': cm, 'alt': alt.get(n), 'sql': bool(re.match(r'^[CA]\d+\.', n))})
        # regra do mesmo programa que um passo de dados vizinho no fluxo (derivação da entrada, erro devolvido pelo dado) é invariante desse comando
        com_cmd = {x['id']: x for x in lista if x['sql']}
        prog_ = lambda n_: n_.split('.', 1)[1] if '.' in n_ else ''   # noqa: E731
        for n in ordem:
            if n in {x['id'] for x in lista} or not re.match(r'^[A-Z]\d+\.', n):
                continue
            viz = [b if a_ == n else a_ for a_, b, _t in arestas if n in (a_, b)]
            cm = list(dict.fromkeys(c for v in viz if v in com_cmd and prog_(v) == prog_(n) for c in com_cmd[v]['cmds']))
            if cm:
                lista.append({'id': n, 'nome': nome_no.get(n, ''), 'cmds': cm, 'alt': None, 'sql': False})
        for a_, b, t in arestas:   # passo do BFMF que chama uma função corporativa: a regra é a leitura que o serviço dessa função executa
            if t == 'chama' and b in ids and re.match(r'^[A-Z]\d+\.', a_):
                CHAMA_NOS.setdefault(f, {})[a_] = b
        fluxo[f] = lista
        FLUXO_IDS[f] = {nome_no[n]: n for n in ordem if n in nome_no}
    return fluxo, chama, citados


PASSOS = {}     # funcionalidade → passos do fluxo interno na ordem das etapas (fase 12): regra, erro ou corporativa, com o nó SQL e os comandos quando há


def ler_passos(ana, funcs):
    """Passos do fluxo de negócio de cada funcionalidade, na ordem das etapas. Passo com nó SQL (ou, numa função corporativa de consulta dinâmica, regra sobre dados com comandos citados) carrega os comandos originais."""
    por_nome = {v['nome']: k for k, v in funcs.items()}
    out = {}
    for _s, bt, rows in S.tabelas(S.fase(ana, '12 ')):
        m = re.match(r'(\S+): nós do fluxo interno', bt)
        if not m:
            continue
        f = m.group(1)
        nos_f = {n['nome']: n for n in FLUXO.get(f, [])}
        lista = []
        for r in rows:
            tipo = r.get('Tipo')
            if tipo not in ('regra', 'erro', 'corporativa'):
                continue
            nome = r.get('Nome', '')
            texto = ' '.join(str(r.get(k, '')) for k in ('Nome', 'Entra', 'Sai'))
            no = nos_f.get(nome)
            lista.append({'etapa': int(str(r.get('Etapa') or 0) or 0), 'tipo': tipo, 'nome': nome, 'no': no['id'] if no else '', 'sql': bool(no and no['sql']), 'cmds': list(no['cmds']) if no else [], 'alt': no['alt'] if no else None,
                          'chama': por_nome.get(nome) if tipo == 'corporativa' else None, 'texto': texto, 'func': f,
                          'id': FLUXO_IDS.get(f, {}).get(nome, '').split('.')[0],
                          'chama_fn': CHAMA_NOS.get(f, {}).get(FLUXO_IDS.get(f, {}).get(nome, ''), None),
                          'classes': next((q['classes'] for q in REGRAS.get(f, []) if q['nome'] == nome), [])})
        if f in CITADOS and not any(x['cmds'] for x in lista):   # corporativa de consulta dinâmica: a regra sobre os dados executa o comando citado no fluxo
            ori = sorted({c.split('.')[0] for c in CITADOS[f]})
            for x in lista:
                if x['tipo'] == 'regra' and 'tabela' in x['nome'].lower() and ('lido' in x['nome'].lower() or 'lida' in x['nome'].lower()):
                    x['cmds'] = ori
                    x['sql'] = True
        out[f] = lista
    return out


def exe_de(f):
    """Funcionalidades que rodam quando a entrega f é executada: ela e as chamadas pelo fluxo (diretas ou por dentro de outra função), na ordem do fluxo."""
    out = [f]

    def desce(x):
        for y in CHAMA_FLUXO.get(x, []):
            if y not in out:
                out.append(y)
                desce(y)
    desce(f)
    return out


def rotulo_regra(x):
    return (x['id'] + ' · ' if x.get('id') else '') + x['nome']


DONO_REGRA = {}
REG = {}   # regras que as notas dos diagramas de sequência levam a cada aplicação e caso de uso (a fonte dos diagramas de casos de uso e do rastreio)


def _nat(c):
    return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', c)]


def servicos_regra(m, ev, x):
    """Dono único por regra: o mesmo código e nome de regra vai para o mesmo serviço em todas as funcionalidades (o mais frequente entre os que as funcionalidades indicam), para que sequências e componentes coincidam."""
    k = id(m)
    if k not in DONO_REGRA:
        c_ = defaultdict(Counter)
        for g_, ps_ in PASSOS.items():
            for y in ps_:
                if y['tipo'] in ('regra', 'erro'):
                    c_[rotulo_regra(y)][_servicos_regra(m, ev, y)] += 1
        DONO_REGRA[k] = {l_: (next((s_ for s_, _n in cs_.most_common() if s_), None)) for l_, cs_ in c_.items()}
    loc = _servicos_regra(m, ev, x)
    if x['tipo'] in ('regra', 'erro') and rotulo_regra(x) in DONO_REGRA[k] and loc:
        g_ = DONO_REGRA[k][rotulo_regra(x)]
        usados = {m['dono'][c] for y in achata_passos(x['func']) for c in m['cmd_res'] if y['cmds'] and c.split('.')[0] in y['cmds'] and c in m['dono']}
        return g_ if g_ in usados else loc   # só usa o dono comum se a funcionalidade chama esse serviço
    return loc


def _servicos_regra(m, ev, x):
    """Serviço (Domain Microservice ou VAS) a que a regra do fluxo pertence, ou None quando ela fica no BFMF:
    regra ligada a um comando SQL pela linhagem → serviço dono do comando; regra sobre uma classe de domínio → o único serviço dono dessa classe;
    regra de uma função corporativa que só consulta dados de um serviço → esse serviço. Validação do pedido, decisão e composição de serviços diferentes ficam no BFMF."""
    R_ = {r['id']: r for r in m['recursos']}
    if x.get('chama_fn') and not x['cmds']:
        sv = {m['dono'][c] for y in PASSOS.get(x['chama_fn'], []) for c in m['cmd_res'] if y['cmds'] and c.split('.')[0] in y['cmds'] and c in m['dono']}
        return next(iter(sv)) if len(sv) == 1 else None
    if x['cmds']:
        cods = [c for c in m['cmd_res'] if c.split('.')[0] in x['cmds'] and c in m['dono']]
        dono = list(dict.fromkeys(m['dono'][c] for c in sorted(cods)))
        return dono[0] if dono else None
    if x['classes']:
        sv = {m['dono'][c] for c, (req, _r, _p) in m['cmd_res'].items() if c in m['dono'] and set(x['classes']) <= set(R_[req]['tabelas'])}
        return next(iter(sv)) if len(sv) == 1 else None
    g_ = x['func']
    if not ev['funcs'][g_]['entry']:
        sv = {m['dono'][c] for y in PASSOS.get(g_, []) for c in m['cmd_res'] if y['cmds'] and c.split('.')[0] in y['cmds'] and c in m['dono']}
        if len(sv) == 1:
            return next(iter(sv))
    return None


def comando_da_regra(m, x, svc):
    """Comando SQL do serviço a que a regra está ligada: o dela, o de uma classe que ela toca ou o primeiro passo de dados da função."""
    R_ = {r['id']: r for r in m['recursos']}
    nat = lambda c: [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', c)]   # noqa: E731
    cods = sorted((c for c in m['cmd_res'] if m['dono'].get(c) == svc), key=nat)
    if x.get('chama_fn') and not x['cmds']:
        for y in PASSOS.get(x['chama_fn'], []):
            ok = [c for c in cods if y['cmds'] and c.split('.')[0] in y['cmds']]
            if ok:
                return ok[0]
    if x['cmds']:
        ok = [c for c in cods if c.split('.')[0] in x['cmds']]
        if ok:
            return ok[0]
    if x['classes']:
        ok = [c for c in cods if set(x['classes']) <= set(R_[m['cmd_res'][c][0]]['tabelas'])]
        if ok:
            return ok[0]
    for y in PASSOS.get(x['func'], []):
        ok = [c for c in cods if y['cmds'] and c.split('.')[0] in y['cmds']]
        if ok:
            return ok[0]
    return cods[0] if cods else None


def achata_passos(g_, vistos=()):
    """Passos do fluxo de g_ com as funções corporativas chamadas expandidas no lugar da chamada."""
    r_ = []
    for x in PASSOS.get(g_, []):
        if x['tipo'] == 'corporativa' and x['chama'] and x['chama'] not in vistos:
            r_ += achata_passos(x['chama'], vistos + (x['chama'],))
        else:
            r_.append(x)
    return r_


def justificar(m, ev, x, app):
    """Por que a regra x do fluxo (fase 12) fica na aplicação app: o mesmo critério de servicos_regra, dito em palavras."""
    R_ = {r['id']: r for r in m['recursos']}
    if tipo_de(m, app) == 'BFMF':
        if x.get('chama_fn') and not x['cmds']:
            return f'decide chamar a funcionalidade corporativa {x["chama_fn"]}, cujos dados não são de um único serviço: o BFMF conduz a chamada'
        if x['cmds']:
            return 'toca comandos que não têm um único serviço dono: a composição é do BFMF'
        if x['classes']:
            return 'junta classes de domínio de serviços diferentes: a composição é do BFMF'
        return 'não toca os dados de um serviço (validação do pedido, derivação, decisão ou tratamento do erro devolvido): o BFMF conduz o fluxo de negócio'
    if x.get('chama_fn') and not x['cmds']:
        return f'chama a funcionalidade corporativa {x["chama_fn"]}, que só consulta dados deste serviço'
    if x['cmds']:
        cods = [c for c in m['cmd_res'] if c.split('.')[0] in x['cmds'] and m['dono'].get(c) == app]
        props = list(dict.fromkeys(R_[m['cmd_res'][c][0]]['proposito'] for c in cods))
        base = 'a linhagem da fase 11 liga a regra' if x['sql'] else 'a regra é do mesmo programa do passo de dados e ligada a ele por aresta do fluxo (fase 12), que executa'
        return f'{base} ao comando «{"; ".join(props[:2])}», executado por este serviço, dono do comando' if x['sql'] else f'{base} o comando «{"; ".join(props[:2])}», dono deste serviço'
    if x['classes']:
        return f'rege a classe de domínio {", ".join(x["classes"])}, acessada só por este serviço'
    return 'função corporativa que só consulta dados deste serviço'


def regras_do_caso(m, app, caso):
    """Regras de negócio que as notas dos diagramas de sequência levam a este caso de uso da aplicação (uma regra fica em um só caso de uso de cada aplicação: o primeiro em que aparece)."""
    vistas, r_ = {}, []
    for e in REG.get(id(m), []):
        if e['app'] == app and e['regra'] not in vistas:
            vistas[e['regra']] = e['caso']
    return [rg for rg, c in vistas.items() if c == caso]


def regras_riscadas(m, app, caso):
    """Regras do caso de uso que não serão implementadas (ficam dentro do programa corporativo)."""
    return {e['regra'] for e in REG.get(id(m), []) if e['app'] == app and e['caso'] == caso and e.get('riscada')}


def originais_de(g_):
    """Comandos originais (fase 10) que a funcionalidade executa pelo seu fluxo; None quando o fluxo não traz essa evidência."""
    cm = {c for n in FLUXO.get(g_, []) for c in n['cmds']}   # inclui as invariantes (erros e derivações) que a linhagem liga aos mesmos comandos
    if g_ in CITADOS:
        cm |= {c.split('.')[0] for c in CITADOS[g_]}
    return cm or None


def cmds_de(cands, g_):
    """Do que o alcance dos programas oferece, só o que o fluxo de g_ executa: o comando original do nó e todos os comandos em que ele foi desdobrado."""
    ori = originais_de(g_)
    return sorted(c for c in cands if ori is None or c.split('.')[0] in ori)


def ler_ux(ana):
    ux = {'telas': {}, 'acoes': {}, 'grupos': {}}
    for _s, bt, rows in S.tabelas(S.fase(ana, '15 ')):
        if bt.startswith('Telas: finalidade, jornada e layout sugerido'):
            for r in rows:
                ux['telas'][r['Tela']] = r
        elif bt.startswith('Ações de '):
            ux['acoes'][bt[len('Ações de '):]] = rows
        elif bt.startswith('Agrupamentos de '):
            ux['grupos'][bt[len('Agrupamentos de '):]] = rows
    return ux


def ler_interp(base):
    d = Path(base) / 'interpretacao-arquitetura'
    arqs = sorted(f for f in d.glob('*.json') if f.name != 'PROVENIENCIA.json') if d.exists() else []
    if not arqs:
        return None
    out = {k: [] for k in CHAVES_RAIZ}
    for f in arqs:
        x = json.loads(f.read_text(encoding='utf-8'))
        for k, v in x.items():
            out.setdefault(k, [])
            out[k] += v if isinstance(v, list) else [v]
    return out


def do_cenario(interp, chave, cen):
    return [x for x in (interp or {}).get(chave, []) if x.get('cenario') in (None, cen)]


def curto_cmds(cs, n=3):
    cs = list(cs)
    return ', '.join(cs[:n]) + (f' +{len(cs) - n}' if len(cs) > n else '')


def proposito_de(cod, info, interp, classes):
    """Propósito do comando SQL (texto de negócio): vem da interpretação (`comandos`); sem ela, verbo da operação + classe de domínio."""
    for x in (interp or {}).get('comandos', []):
        if x['comando'] in (cod, cod.split('.')[0]) and x['comando'] == cod:
            return x['proposito']
    for x in (interp or {}).get('comandos', []):
        if x['comando'] == cod.split('.')[0]:
            return x['proposito']
    ti = info.get(cod.split('.')[0], {})
    op = (ti.get('operacoes') or ['SELECT'])[0]
    return VERBO_OP.get(op, 'consulta') + ' ' + ' '.join(re.findall(r'[A-Z][a-z]+', classes[0])) if classes else VERBO_OP.get(op, 'consulta')


def palavras(t):
    return [w for w in slug(t).split('-') if w]


def _corta(ws, limite, desde=0):
    ws = list(ws)
    while len(''.join(ws)) > limite:
        cand = [(len(w), i) for i, w in enumerate(ws) if len(w) > 4 and i >= desde]
        if not cand:
            return None
        _l, i = max(cand)
        ws[i] = ws[i][:4]
    return ''.join(ws).upper()


def _verbo(pw):
    pw = list(pw)
    if pw and pw[0] in VERBOS:
        pw[0] = VERBOS[pw[0]]
    return pw


def nome_contexto(ctx_nome, propositos, pref):
    """Nome do contexto nas filas: o mesmo em todas as filas do contexto, com o maior tamanho (até 20 caracteres) em que todos os propósitos do contexto ainda cabem em 48 caracteres; palavras longas cortadas em 4 letras, da mais longa para a menor."""
    cw = palavras(ctx_nome)
    for lim in range(20, 5, -1):
        ctx = _corta(cw, lim)
        if ctx is None:
            break
        if all(_corta(_verbo(palavras(p)), 48 - (3 + len(pref) + 1 + len(ctx) + 1 + 2 + 4), 1) for p in propositos):
            return ctx
    raise SystemExit(f'os nomes de fila do contexto "{ctx_nome}" não cabem em 48 caracteres; dê propósitos mais curtos')


PROPOSITOS_FILAS = {}   # propósito já atribuído às filas de cada comando (nomes-atribuidos.json): mantido para o nome da fila não mudar


def nome_fila(ctx_nome, ctx, proposito, pref, abrev, fixo=None):
    """Filas de baixa: FR.<SISTEMA>.<CONTEXTO>.NI<PROPÓSITO DO COMANDO>.REQ e FL.<SISTEMA>.<CONTEXTO>.NI<PROPÓSITO DO COMANDO>.RSP; filas de alta: <SISTEMA>.QL.REQ.<SISTEMA>.NI<PROPÓSITO>.nn e <SISTEMA>.QR.RSP.<SISTEMA>.NI<PROPÓSITO>.nn; em caixa alta e sem separadores dentro de cada parte, no máximo 48 caracteres (o propósito sai do mesmo cálculo das filas de baixa)."""
    pw = _verbo(palavras(proposito))
    pur = fixo or _corta(pw, 48 - (3 + len(pref) + 1 + len(ctx) + 1 + 2 + 4), 1)
    ctx_cheio, pur_cheio = ''.join(palavras(ctx_nome)).upper(), ''.join(_verbo(palavras(proposito))).upper()
    if ctx != ctx_cheio:
        abrev[ctx_cheio] = ctx
    if pur != pur_cheio:
        abrev[f'{ctx}.{pur_cheio}'] = f'{ctx}.{pur}'
    return ctx, pur


def nomes_atribuidos(base):
    """Nomes já atribuídos (e usados no código gerado) aos programas mainframe novos e aos copybooks das filas: {'programas': {cmd: nome}, 'copybooks': {cmd: [req, rsp]}}."""
    f = Path(base) / 'nomes-atribuidos.json'
    return json.loads(f.read_text(encoding='utf-8')) if f.exists() else {'programas': {}, 'copybooks': {}}


def nomes_programas(cods, props, pref, legados, fixos=None):
    """Programa mainframe: <SISTEMA>1 + 3 letras tiradas do propósito (iniciais das palavras), 8 posições, sem repetir nome nem coincidir com programa que já existe.
    O nome já atribuído (fixos) é mantido; só comando novo recebe nome pela regra."""
    fixos = {c: n for c, n in (fixos or {}).items() if c in set(cods)}
    usados, out = set(legados) | set(fixos.values()), dict(fixos)
    for cod in sorted(c for c in cods if c not in fixos):
        pw = palavras(props[cod])
        letras = [w[0] for w in pw][:3]
        resto = [c for w in pw for c in w[1:] if c not in 'aeiou'] + [c for w in pw for c in w[1:]]
        while len(letras) < 3:
            letras.append(resto.pop(0) if resto else 'x')
        base = pref.upper() + '1'
        nome = base + ''.join(letras).upper()
        k = 0
        while nome in usados:
            k += 1
            l3 = list(''.join(letras).upper())
            l3[2] = chr((ord(l3[2]) - 65 + k) % 26 + 65)
            nome = base + ''.join(l3)
        usados.add(nome)
        out[cod] = nome
    return out


CPY = {}   # comando → (copybook de requisição, copybook de resposta)


def nomes_copybooks(cods, progs, legados_cpy, pref, fixos=None):
    """Copybooks das filas: <SISTEMA>W + 3 letras (8 posições), um de requisição e um de resposta por comando. O de requisição usa as 3 letras do programa; o de resposta, as mesmas letras com a última trocada pela próxima livre; nenhum repete nome nem coincide com copybook que já existe.
    O par já atribuído (fixos) é mantido; só comando novo recebe nome pela regra."""
    fixos = {c: tuple(n) for c, n in (fixos or {}).items() if c in set(cods)}
    usados, out = set(legados_cpy) | {n for par in fixos.values() for n in par}, dict(fixos)
    base = pref.upper() + 'W'

    def livre(l3):
        l3, k = list(l3), 0
        while base + ''.join(l3) in usados:
            k += 1
            l3[2] = chr((ord(l3[2]) - 65 + 1) % 26 + 65)
            if k > 26:
                raise SystemExit(f'sem nome de copybook livre a partir de {base}{"".join(l3)}')
        usados.add(base + ''.join(l3))
        return base + ''.join(l3)
    for cod in sorted(c for c in cods if c not in fixos):
        l3 = progs[cod][-3:]
        out[cod] = (livre(l3), livre(l3[:2] + chr((ord(l3[2]) - 65 + 1) % 26 + 65)))
    return out


def construir(f18, ev, info, papel_tab, pref, simb, props, progs, ctx_curto):
    """Modelo de recursos: recursos aprovados, integrações e o elemento lógico (Logic Database)."""
    R, I = [], []

    def add(tipo, id_, nome, origem, conf, evid, **extra):
        R.append(dict({'id': id_, 'tipo': tipo, 'nome': nome, 'origem': origem, 'confianca': conf, 'evidencia': evid}, **extra))
        return id_
    abrev = {}
    host = add('HOST', f'{pref}-host', 'Shell de microfrontends', '—', 'UNCERTAIN', 'Sem evidência de shell nos relatórios; é necessário para hospedar os MFEs, mas o desenho do shell não foi decidido')
    dc_res, dm_res = {}, {}
    for d in f18['dcs']:
        sl = slug(d['nome'])
        if d['tipo'] == 'Presentation':
            mfe = add('MFE', f'{pref}-fed-{sl}', f'Micro Frontend: {d["nome"]}', d['id'], 'CONFIRMED' if d['telas'] else 'UNCERTAIN',
                      'Telas mantidas no funil da fase 15: ' + (', '.join(d['telas']) or 'nenhuma (sem tela analisada)'), telas=d['telas'])
            bff = add('BFMF', f'{pref}-bff-{sl}', f'Backend for Micro Frontend: {d["nome"]}', d['id'], 'CONFIRMED', 'Delivery Context Presentation com funcionalidades da fase 12: ' + ', '.join(c for c in d['comps'] if c in ev['funcs']), funcs=[c for c in d['comps'] if c in ev['funcs']])
            dc_res[d['id']] = {'mfe': mfe, 'bff': bff}
            I.append({'de': host, 'para': mfe, 'protocolo': 'HOSPEDA', 'base': 'o shell hospeda o microfrontend'})
            I.append({'de': mfe, 'para': bff, 'protocolo': 'REST', 'base': 'o microfrontend chama o seu BFMF'})
        else:
            vas_ctx = d
            vas = add('VAS', f'{pref}-vas-{sl}', f'Value-Added Service: {d["nome"]}', d['id'], 'CONFIRMED', 'Delivery Context Query com queries: ' + curto_cmds([c for c in d['comps'] if c not in ev['funcs'] and c not in GQS], 4), estrategia=d['estrategia'])
            dc_res[d['id']] = {'vas': vas}
    for d in f18['dom']:
        dm_res[d['id']] = add('DOMAIN_MICROSERVICE', f'{pref}-srv-{slug(d["nome"])}', f'Microserviço de domínio: {d["nome"]}', d['id'], 'CONFIRMED', f'Domain Context do agregado raiz {d["raiz"]} ({d["categoria"]})', categoria=d['categoria'])
    dono = {}
    for cod, cl, ctx, nome, tipo in f18['cmds']:
        dono[cod] = dm_res.get(ctx) or (dc_res.get(ctx) or {}).get('vas')
    cmd_res, corp, alta, alta_usadas, funcs = {}, {}, {}, set(), {}
    for cod in sorted(dono):
        base = cod.split('.')[0]
        ti = info.get(base, {})
        ex = {'comando': cod, 'operacoes': ti.get('operacoes', []), 'tabelas': ti.get('tabelas', []),
              'papel_tabelas': sorted({papel_tab.get(t, '—') for t in ti.get('tabelas', [])})}
        pg = progs[cod]
        ctx_nome = next(r['nome'].split(': ', 1)[1] for r in R if r['id'] == dono[cod])
        ctx, pur = nome_fila(ctx_nome, ctx_curto[ctx_nome], props[cod], pref, abrev, PROPOSITOS_FILAS.get(cod))
        q_req, q_rsp = f'FR.{pref.upper()}.{ctx}.NI{pur}.REQ', f'FL.{pref.upper()}.{ctx}.NI{pur}.RSP'
        seq_ = 1   # a fila de alta não leva o contexto: se outro contexto já usa o mesmo propósito, o sufixo sequencial sobe
        while f'{pref.upper()}.QL.REQ.{pref.upper()}.NI{pur}.{seq_:02d}' in alta_usadas:
            seq_ += 1
        q_areq, q_arsp = f'{pref.upper()}.QL.REQ.{pref.upper()}.NI{pur}.{seq_:02d}', f'{pref.upper()}.QR.RSP.{pref.upper()}.NI{pur}.{seq_:02d}'
        alta_usadas.add(q_areq)
        ex['proposito'] = props[cod]
        eh_corp = cod in CORP
        alvo_ = f'o programa corporativo {cod}' if eh_corp else f'o comando {cod}'
        req = add('MQ_REQ', q_req, f'Fila de pedido d{alvo_}', dono[cod], 'UNCERTAIN', 'Nome pelo padrão FR.<sistema>.<contexto>.NI<propósito do comando SQL>.REQ (fila de baixa); formato da mensagem e propriedade ainda não decididos', **ex, copybook=CPY[cod][0])
        rsp = add('MQ_RSP', q_rsp, f'Fila de resposta d{alvo_}', dono[cod], 'UNCERTAIN', 'Nome pelo padrão FL.<sistema>.<contexto>.NI<propósito do comando SQL>.RSP (fila de baixa); formato da mensagem e propriedade ainda não decididos', **ex, copybook=CPY[cod][1])
        areq = add('MQ_REQ_ALTA', q_areq, f'Fila de alta de pedido d{alvo_}', dono[cod], 'UNCERTAIN', 'Nome pelo padrão <sistema>.QL.REQ.<sistema>.NI<propósito do comando SQL>.nn (fila de alta); recebe da fila de baixa de pedido e o programa mainframe lê dela', **ex, copybook=CPY[cod][0])
        arsp = add('MQ_RSP_ALTA', q_arsp, f'Fila de alta de resposta d{alvo_}', dono[cod], 'UNCERTAIN', 'Nome pelo padrão <sistema>.QR.RSP.<sistema>.NI<propósito do comando SQL>.nn (fila de alta); o programa mainframe responde nela e a fila de baixa de resposta recebe daí', **ex, copybook=CPY[cod][1])
        alta[req] = (areq, arsp)
        dig = digito_funcional()
        coord, pg = (pg, pref.upper() + dig + pg[len(pref) + 1:]) if dig else (None, pg)
        if coord:
            add('PROGRAM_COORD', coord, f'Programa coordenador {coord} d{alvo_}', dono[cod], 'UNCERTAIN', f'Programa mainframe coordenador, pelo padrão <sistema>1 + 3 letras do propósito (8 posições) ({props[cod]}): lê a fila de alta de pedido, chama o programa funcional {pg} (EXEC CICS LINK) e responde na fila de alta de resposta; a disponibilidade do nome não foi confirmada', funcional=pg, **ex)
        if eh_corp:
            prg = add('PROGRAM_CORP', pg, f'Programa {pg} que chama o programa corporativo {cod}', dono[cod], 'UNCERTAIN', f'Programa mainframe novo, pelo padrão <sistema>1 + 3 letras do propósito (8 posições) ({props[cod]}); em vez de executar SQL, chama o programa corporativo original {cod}, que executa o SQL; a disponibilidade do nome e a interface de chamada do programa corporativo não foram confirmadas', chama=cod, comandos_originais=CORP[cod], **ex)
        else:
            prg = add('PROGRAM_DB2', pg, f'Programa {pg} que executa o comando {cod} no DB2', dono[cod], 'UNCERTAIN', f'Programa mainframe proposto pelo padrão <sistema>1 + 3 letras do propósito (8 posições) ({props[cod]}); a disponibilidade do nome e se vira programa novo ou reuso de programa existente não foram decididos', **ex)
        if coord:   # o funcional não lê fila: recebe o pedido do coordenador
            R[-1]['nome'] = R[-1]['nome'].replace('Programa ', 'Programa funcional ', 1) + f', chamado pelo coordenador {coord}'
            R[-1]['evidencia'] = R[-1]['evidencia'].replace('<sistema>1 + 3 letras', f'<sistema>{dig} + as 3 letras do coordenador')
            funcs[coord] = prg
            I.append({'de': coord, 'para': prg, 'protocolo': 'LINK', 'base': f'{"programa corporativo" if eh_corp else "comando"} {cod}'})
            prg = coord
        bs_ = f'{"programa corporativo" if eh_corp else "comando"} {cod}'
        I.append({'de': dono[cod], 'para': req, 'protocolo': 'SEND_BAIXA', 'base': bs_})
        I.append({'de': req, 'para': areq, 'protocolo': 'ENCAMINHA', 'base': bs_})
        I.append({'de': areq, 'para': prg, 'protocolo': 'RECEIVE_ALTA', 'base': bs_})
        I.append({'de': prg, 'para': arsp, 'protocolo': 'SEND_ALTA', 'base': bs_})
        I.append({'de': arsp, 'para': rsp, 'protocolo': 'ENCAMINHA', 'base': bs_})
        I.append({'de': rsp, 'para': dono[cod], 'protocolo': 'RECEIVE_BAIXA', 'base': bs_})
        if eh_corp:
            corp[cod] = {'cmds': CORP[cod], 'res': (req, rsp, prg), 'dono': dono[cod]}
        else:
            cmd_res[cod] = (req, rsp, prg)
    for cod, x in corp.items():   # os comandos SQL originais do programa corporativo apontam para as mesmas filas e o mesmo programa novo
        for o in x['cmds']:
            cmd_res[o] = x['res']
            dono[o] = x['dono']
    for cod in corp:
        del dono[cod]
    donos_cmd = defaultdict(list)
    for cod, o in dono.items():
        donos_cmd[o].append(cod)
    pend = []
    if abrev:
        pend.append(('Nomes de contexto abreviados nas filas', 'O nome de fila IBM MQ tem no máximo 48 caracteres; estes nomes de contexto e pares contexto.propósito foram abreviados para caber (o nome do contexto é o mesmo em todas as filas dele): ' + '; '.join(f'{a} → {b}' for a, b in sorted(abrev.items())), 'UNCERTAIN', ['MQ_REQ', 'MQ_RSP', 'MQ_REQ_ALTA', 'MQ_RSP_ALTA']))
    refs_id = []
    for r in f18['rels']:
        a, b = r['de'], r['para']
        if r['tipo_de'] == 'Delivery · Presentation' and r['tipo_para'] == 'Domain':
            I.append({'de': dc_res[a]['bff'], 'para': dm_res[b], 'protocolo': 'REST', 'base': 'a funcionalidade do BFMF usa o agregado (' + r['relacao'] + ')'})
        elif r['tipo_de'] == 'Delivery · Presentation' and r['tipo_para'] == 'Delivery · Query':
            I.append({'de': dc_res[a]['bff'], 'para': dc_res[b]['vas'], 'protocolo': 'REST', 'base': 'o BFMF consulta o VAS (' + r['relacao'] + ')'})
        elif r['tipo_de'] == 'Domain' and r['tipo_para'] == 'Domain':
            if r['protocolo'] == 'sincrono':
                refs_id.append(f'{dm_res[a]} → {dm_res[b]} ({r["relacao"]})')   # referência por identidade: nenhum caminho de funcionalidade passa de um serviço para outro; o BFMF chama cada um direto
            else:
                pend.append(('Relacionamento assíncrono entre domínios', f'{dm_res[a]} → {dm_res[b]} é {r["protocolo"]} na fase 18; a tabela de protocolos da arquitetura só prevê REST síncrono entre microsserviços de domínio e não há mensageria entre eles no modelo', 'UNKNOWN', ['DOMAIN_MICROSERVICE']))
        elif r['tipo_de'] == 'Delivery · Query':
            pass   # o VAS lê os dados pelo Logic Database (comandos do próprio VAS), sem chamada direta ao domínio
        else:
            pend.append(('Relacionamento sem protocolo previsto', f'{r["de"]} → {r["para"]} ({r["tipo_de"]} → {r["tipo_para"]}) não tem protocolo na tabela de integrações', 'UNKNOWN', ['BFMF']))
    if refs_id:
        pend.append(('Referências por identidade entre domínios não viram chamada REST', 'A fase 18 mostra estas referências entre agregados: ' + '; '.join(refs_id) + '. Nenhum caminho percorrido por uma funcionalidade passa de um Domain Microservice para outro: o BFMF (ou o VAS) chama cada serviço direto e compõe a resposta, sem serviço intermediário fazendo papel de proxy. Por isso a arquitetura não tem integração REST entre domínios; cada agregado guarda só o identificador do outro. Se uma regra futura exigir validar o outro agregado dentro do próprio serviço, essa chamada precisa ser decidida e justificada.', 'CONFIRMED', ['DOMAIN_MICROSERVICE']))
    vistos, I2 = set(), []
    for i in I:
        k = (i['de'], i['para'], i['protocolo'], i['base'])
        if k not in vistos:
            vistos.add(k)
            I2.append(i)
    return {'recursos': R, 'integracoes': I2, 'cmd_res': cmd_res, 'corp': corp, 'dc_res': dc_res, 'dm_res': dm_res, 'dono': dono, 'pend': pend, 'alta': alta, 'func': funcs}


def uni(m, cods):
    """Comandos sem repetir o trio (MQ_REQ, MQ_RSP, programa): vários comandos SQL do mesmo programa corporativo compartilham as mesmas filas e o mesmo programa novo."""
    vistos, out = set(), []
    for c in cods:
        if m['cmd_res'][c] not in vistos:
            vistos.add(m['cmd_res'][c])
            out.append(c)
    return out


def tipo_de(m, i):
    return next(r['tipo'] for r in m['recursos'] if r['id'] == i)


def validar_modelo(m, f18):
    erros = []
    ids = set()
    for r in m['recursos']:
        if r['tipo'] not in TIPOS:
            erros.append(f'{r["id"]}: tipo inválido {r["tipo"]}')
        if r['id'] in ids:
            erros.append(f'id repetido {r["id"]}')
        ids.add(r['id'])
        if r['tipo'] in PROGS and not PROG_OK.match(r['id']):
            erros.append(f'{r["id"]}: o nome do programa precisa seguir <SISTEMA> + dígito + 3 letras (8 posições)')
        if r['tipo'] in ('MQ_REQ', 'MQ_RSP', 'MQ_REQ_ALTA', 'MQ_RSP_ALTA'):
            if r['tipo'] in ('MQ_REQ', 'MQ_RSP') and (not FILA_OK.match(r['id']) or r['id'][:2] != ('FR' if r['tipo'] == 'MQ_REQ' else 'FL')):
                erros.append(f'{r["id"]}: o nome da fila de baixa precisa seguir FR.<SISTEMA>.<CONTEXTO>.NI<PROPÓSITO>.REQ (pedido) ou FL.<SISTEMA>.<CONTEXTO>.NI<PROPÓSITO>.RSP (resposta) em caixa alta')
            if r['tipo'] in ('MQ_REQ_ALTA', 'MQ_RSP_ALTA') and (not FILA_ALTA_OK.match(r['id']) or ('.QL.REQ.' if r['tipo'] == 'MQ_REQ_ALTA' else '.QR.RSP.') not in r['id']):
                erros.append(f'{r["id"]}: o nome da fila de alta precisa seguir <SISTEMA>.QL.REQ.<SISTEMA>.NI<PROPÓSITO>.nn (pedido) ou <SISTEMA>.QR.RSP.<SISTEMA>.NI<PROPÓSITO>.nn (resposta) em caixa alta')
            if len(r['id']) > 48:
                erros.append(f'{r["id"]}: nome de fila com mais de 48 caracteres')
        elif r['tipo'] not in PROGS and not ID_OK.match(r['id']):
            erros.append(f'{r["id"]}: o identificador precisa ser kebab-case')
        if any(w in r['id'].split('-') for w in STOP) and r['tipo'] in ('MFE', 'BFMF', 'VAS', 'DOMAIN_MICROSERVICE'):
            erros.append(f'{r["id"]}: o identificador tem stop word')
        if r['confianca'] not in CONF:
            erros.append(f'{r["id"]}: confiança inválida')
    for i in m['integracoes']:
        if i['de'] not in ids or i['para'] not in ids:
            erros.append(f'integração com recurso ausente do modelo: {i["de"]} → {i["para"]}')
            continue
        if (tipo_de(m, i['de']), tipo_de(m, i['para']), i['protocolo']) not in PERMITIDOS:
            erros.append(f'integração fora da tabela de protocolos: {tipo_de(m, i["de"])} → {tipo_de(m, i["para"])} ({i["protocolo"]})')
    for cod, *_ in f18['cmds']:
        if cod not in m['cmd_res'] and cod not in m['corp']:
            erros.append(f'o comando SQL ou programa corporativo {cod} não tem as filas de baixa e de alta e o programa mainframe')
    return erros


def yaml_dump(x, n=0):
    pad = '  ' * n
    if isinstance(x, dict):
        out = []
        for k, v in x.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f'{pad}{k}:\n' + yaml_dump(v, n + 1))
            else:
                out.append(f'{pad}{k}: {yaml_dump(v, n + 1) if isinstance(v, (dict, list)) else yaml_escalar(v)}')
        return '\n'.join(out)
    if isinstance(x, list):
        out = []
        for v in x:
            if isinstance(v, dict) and v:
                linhas = yaml_dump(v, n + 1).split('\n')
                out.append(f'{pad}- ' + linhas[0].lstrip() + ('\n' + '\n'.join(linhas[1:]) if len(linhas) > 1 else ''))
            else:
                out.append(f'{pad}- {yaml_escalar(v)}')
        return '\n'.join(out)
    return pad + yaml_escalar(x)


def yaml_escalar(v):
    if isinstance(v, (dict, list)):
        return '{}' if isinstance(v, dict) else '[]'
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        return str(v)
    return json.dumps(str(v), ensure_ascii=False)


def modelo_yaml(modelos):
    m = modelos['C']
    y = {'architecture_resource_model': {'version': 2, 'name': 'Arquitetura alvo (' + CENARIOS['C'] + ')',
                                         'resources': [{k: v for k, v in r.items() if k not in ('evidencia', 'confianca')} | {'confidence': r['confianca'], 'evidence': r['evidencia']} for r in m['recursos']],
                                         'integrations': [{'from': i['de'], 'to': i['para'], 'protocol': i['protocolo'], 'basis': i['base']} for i in m['integracoes']]}}
    return yaml_dump(y) + '\n'


# ---------------------------------------------------------------- diagramas
def nome_curto(m, i):
    return next((r['nome'] for r in m['recursos'] if r['id'] == i), i)


_LIGA = {'de', 'da', 'do', 'das', 'dos', 'e', 'a', 'o', 'as', 'os', 'para', 'com', 'em', 'no', 'na', 'nos', 'nas', 'por', 'ao', 'aos'}


def pascal(t):
    """Nome de caso de uso em Pascal Case (sem acentos nem conectivos): «Consulta item por chave e tipo» → ConsultaItemChaveTipo."""
    import unicodedata
    t = unicodedata.normalize('NFKD', str(t)).encode('ascii', 'ignore').decode()
    ws = [w for w in re.findall(r'[A-Za-z0-9]+', t)]
    ws = [w for w in ws if w.lower() not in _LIGA] or ws
    return ''.join(w[:1].upper() + w[1:].lower() for w in ws)


def checa_ids(m, g, livres=('u-', 'sistema', 'mainframe', 'grp-', 'l3-')):
    """Nenhum diagrama pode introduzir recurso ausente do modelo: todo nó é um recurso, o Logic Database ou um nó auxiliar (usuário, sistema, grupo, camada)."""
    ids = {r['id'] for r in m['recursos']}
    for n in g['nodes']:
        if n['id'].split('::')[0] not in ids and not n['id'].startswith(livres):
            raise SystemExit(f'diagrama "{g.get("title")}": o nó {n["id"]} não existe no modelo de recursos')
        for c in n.get('componentes') or []:
            if c.get('rid') and c['rid'] not in ids:
                raise SystemExit(f'diagrama "{g.get("title")}": o componente {c["rid"]} não existe no modelo de recursos')
    return g


def grafo_contextos(titulo, nos, arestas, cols, nota, legenda, nw=250):
    g = rm.G(titulo, nos, arestas, kind='contextos', note=nota)
    g['columns'] = [{'name': c, 'color': k} for c, k in cols]
    g['nw'] = nw
    g['legenda'] = legenda
    return g


def c4_l1(m, f18, cen):
    nos = [{'id': 'u-' + d['id'], 'col': 0, 'label': 'Usuário', 'sub': d['nome'], 'cor': COR['USER'], 'detail': f'Usuário da entrega {d["nome"]}'} for d in f18['dcs'] if d['tipo'] == 'Presentation']
    nos.append({'id': 'sistema', 'col': 1, 'label': 'Sistema modernizado', 'sub': f'{len(m["recursos"])} recursos aprovados', 'cor': COR['BFMF'], 'detail': 'Micro frontends, backends, serviços de valor agregado e microsserviços de domínio'})
    nos.append({'id': 'mainframe', 'col': 2, 'label': 'Mainframe', 'sub': 'DB2 e IBM MQ' + (' · programas corporativos' if m['corp'] else ''), 'cor': COR['PROGRAM_DB2'], 'detail': 'Programas mainframe que executam os comandos SQL no DB2' + (' e, no domínio corporativo, programas novos que chamam os programas corporativos originais' if m['corp'] else '')})
    ar = [{'from': 'u-' + d['id'], 'to': 'sistema', 'label': 'usa'} for d in f18['dcs'] if d['tipo'] == 'Presentation'] + [{'from': 'sistema', 'to': 'mainframe', 'label': 'executa SQL e chama programas corporativos por filas MQ' if cen == 'C' else 'executa SQL por filas MQ'}]
    g = rs._grafo('C4 nível 1 (contexto do sistema)', ['Usuários', 'Sistema modernizado', 'Mainframe'], nos, ar,
                  'Usuários, sistema modernizado e mainframe. Sem provedor de identidade nem observabilidade, e sem sistemas externos: os relatórios não mostram nenhum.', 230)
    return checa_ids(m, g)


def pl(n, um, varios):
    return f'{n} {um if n == 1 else varios}'


def c4_l2(m, f18, ev, cen):
    R = {r['id']: r for r in m['recursos']}
    cmds = set(m['cmd_res']) | set(m['corp'])
    nos = []
    host = next(r for r in m['recursos'] if r['tipo'] == 'HOST')
    nos.append({'id': host['id'], 'col': 0, 'label': 'HOST', 'sub': host['id'], 'cor': COR['HOST'], 'componentes': [{'label': pl(sum(1 for r in m['recursos'] if r['tipo'] == 'MFE'), 'micro frontend', 'micro frontends'), 'sub': ''}], 'detail': host['evidencia']})
    for r in m['recursos']:
        t = r['tipo']
        if t == 'MFE':
            nos.append({'id': r['id'], 'col': 1, 'label': r['id'], 'sub': 'MFE', 'cor': COR['MFE'], 'componentes': [{'label': pl(len(r['telas']), 'tela', 'telas'), 'sub': ''}], 'detail': r['nome'] + ': ' + ', '.join(r['telas'])})
        elif t == 'BFMF':
            nos.append({'id': r['id'], 'col': 2, 'label': r['id'], 'sub': 'BFMF', 'cor': COR['BFMF'], 'componentes': [{'label': pl(len(r['funcs']), 'feature', 'features'), 'sub': ''}], 'detail': r['nome'] + ': ' + ', '.join(r['funcs'])})
        elif t == 'VAS':
            dc = next(d for d in f18['dcs'] if d['id'] == r['origem'])
            nos.append({'id': r['id'], 'col': 3, 'label': r['id'], 'sub': 'VAS · ' + (r.get('estrategia') or ''), 'cor': COR['VAS'], 'componentes': [{'label': pl(sum(1 for x in dc['comps'] if x not in ev['funcs'] and x not in GQS), 'query', 'queries'), 'sub': ''}], 'detail': r['nome']})
        elif t == 'DOMAIN_MICROSERVICE':
            dm = next(d for d in f18['dom'] if d['id'] == r['origem'])
            nos.append({'id': r['id'], 'col': 3, 'label': r['id'], 'sub': 'Domain · ' + r['categoria'], 'cor': COR['DOMAIN_MICROSERVICE'] if r['categoria'] == 'Business core' else COR_CORP,
                        'componentes': [{'label': pl(sum(1 for x in dm['comps'] if x not in cmds), 'classe', 'classes'), 'sub': ''}, {'label': (pl(sum(1 for x in dm['comps'] if x in cmds), 'programa corporativo', 'programas corporativos') if any(x in m['corp'] for x in dm['comps']) else pl(sum(1 for x in dm['comps'] if x in cmds), 'comando SQL', 'comandos SQL')), 'sub': ''}], 'detail': r['nome']})
    ar = []
    for o in [r for r in m['recursos'] if r['tipo'] in ('VAS', 'DOMAIN_MICROSERVICE')]:
        meus = sorted(c for c, d in m['dono'].items() if d == o['id'])
        if not meus:
            continue
        sfx = o['id']
        fun_ = lambda c: m['func'].get(m['cmd_res'][c][2], m['cmd_res'][c][2])   # noqa: E731  (o programa que executa: o funcional, quando há coordenador)
        tprg = 'PROGRAM_CORP' if any(fun_(c) in {x['id'] for x in m['recursos'] if x['tipo'] == 'PROGRAM_CORP'} for c in meus) else 'PROGRAM_DB2'
        pos_ = {'MQ_REQ': lambda c: m['cmd_res'][c][0], 'MQ_RSP': lambda c: m['cmd_res'][c][1], 'PROGRAM_DB2': fun_, 'PROGRAM_CORP': fun_, 'PROGRAM_COORD': lambda c: m['cmd_res'][c][2],
                'MQ_REQ_ALTA': lambda c: m['alta'][m['cmd_res'][c][0]][0], 'MQ_RSP_ALTA': lambda c: m['alta'][m['cmd_res'][c][0]][1]}
        sing_ = {'MQ_REQ': 'fila de baixa de pedido', 'MQ_REQ_ALTA': 'fila de alta de pedido', 'PROGRAM_DB2': 'programa', 'PROGRAM_CORP': 'programa', 'PROGRAM_COORD': 'coordenador', 'MQ_RSP_ALTA': 'fila de alta de resposta', 'MQ_RSP': 'fila de baixa de resposta'}
        plur_ = {'MQ_REQ': 'filas de baixa de pedido', 'MQ_REQ_ALTA': 'filas de alta de pedido', 'PROGRAM_DB2': 'programas', 'PROGRAM_CORP': 'programas', 'PROGRAM_COORD': 'coordenadores', 'MQ_RSP_ALTA': 'filas de alta de resposta', 'MQ_RSP': 'filas de baixa de resposta'}
        cd_ = 1 if m['func'] else 0   # com coordenador, uma coluna a mais antes do programa que executa
        rot_prg = ('Programas funcionais DB2' if tprg == 'PROGRAM_DB2' else 'Programas funcionais que chamam programas corporativos') if cd_ else ('Programas DB2' if tprg == 'PROGRAM_DB2' else 'Programas que chamam programas corporativos')
        for t, col, rot, k in (('MQ_REQ', 4, 'Filas de baixa de pedido', 'req'), ('MQ_REQ_ALTA', 5, 'Filas de alta de pedido', 'areq'),
                               *((('PROGRAM_COORD', 6, 'Programas coordenadores', 'coord'),) if cd_ else ()),
                               (tprg, 6 + cd_, rot_prg, 'db2'),
                               ('MQ_RSP_ALTA', 7 + cd_, 'Filas de alta de resposta', 'arsp'), ('MQ_RSP', 8 + cd_, 'Filas de baixa de resposta', 'rsp')):
            rs_ = [m['recursos'][[x['id'] for x in m['recursos']].index(pos_[t](c))] for c in uni(m, meus)]
            nos.append({'id': f'grp-{sfx}-{k}', 'col': col, 'label': f'{rot} de {o["id"]}', 'sub': f'{t} · {len(rs_)} recursos', 'cor': COR[t], 'componentes': [{'label': pl(len(rs_), sing_[t], plur_[t]), 'sub': ''}], 'detail': TIPOS[t] + ': ' + ', '.join(r['id'] for r in rs_)})
        le_ = f'grp-{sfx}-coord' if cd_ else f'grp-{sfx}-db2'   # quem lê e responde nas filas de alta
        ar += [{'from': sfx, 'to': f'grp-{sfx}-req', 'label': 'SEND_BAIXA'}, {'from': f'grp-{sfx}-req', 'to': f'grp-{sfx}-areq', 'label': 'ENCAMINHA'}, {'from': f'grp-{sfx}-areq', 'to': le_, 'label': 'RECEIVE_ALTA'},
               *([{'from': le_, 'to': f'grp-{sfx}-db2', 'label': 'LINK'}] if cd_ else []),
               {'from': le_, 'to': f'grp-{sfx}-arsp', 'label': 'SEND_ALTA'}, {'from': f'grp-{sfx}-arsp', 'to': f'grp-{sfx}-rsp', 'label': 'ENCAMINHA'}, {'from': f'grp-{sfx}-rsp', 'to': sfx, 'label': 'RECEIVE_BAIXA'}]
    vistos = set()
    for i in m['integracoes']:
        if i['protocolo'] in ('REST', 'HOSPEDA'):
            k = (i['de'], i['para'], i['protocolo'])
            if k not in vistos:
                vistos.add(k)
                ar.append({'from': i['de'], 'to': i['para'], 'label': i['protocolo']})
    leg = [{'texto': 'HOST', 'cor': COR['HOST']}, {'texto': 'MFE', 'cor': COR['MFE']}, {'texto': 'BFMF', 'cor': COR['BFMF']}, {'texto': 'VAS', 'cor': COR['VAS']}, {'texto': 'Domain Microservice', 'cor': COR['DOMAIN_MICROSERVICE']},
           {'texto': 'Domain Microservice corporativo', 'cor': COR_CORP}, {'texto': 'Filas e programas do mainframe', 'cor': COR['MQ_REQ']}]
    cols = [('HOST', COR['HOST']), ('Micro Frontends', COR['MFE']), ('Backends for Micro Frontend', COR['BFMF']), ('VAS e Domain Microservices', COR['DOMAIN_MICROSERVICE']), ('MQ REQ baixa', COR['MQ_REQ']), ('MQ REQ alta', COR['MQ_REQ_ALTA'])] + ([('PROGRAM_COORD', COR['PROGRAM_COORD'])] if m['func'] else []) + [('PROGRAM_DB2 / PROGRAM_CORP' if m['corp'] else 'PROGRAM_DB2', COR['PROGRAM_DB2']), ('MQ RSP alta', COR['MQ_RSP_ALTA']), ('MQ RSP baixa', COR['MQ_RSP'])]
    g = grafo_contextos('C4 nível 2 (containers)', nos, ar, cols,
                        'Cada caixa é um container do modelo de recursos, com um resumo do que tem dentro (por exemplo, 13 features); o detalhe está nas tabelas e nos diagramas de nível 3. O rótulo da seta é o protocolo. Kafka, projeções, bancos próprios e ReadStores não aparecem: nenhum relatório os decide (ver lacunas e decisões pendentes).', leg, 260)
    return checa_ids(m, g)


def _l3(m, rid, entrada, camadas, saidas, ligacoes, cen, nota):
    """Devolve o diagrama de componentes (sem as regras) e, logo abaixo, o diagrama dos casos de uso com as regras de negócio dentro de cada um."""
    casos = next((c[3] for c in camadas if c[0] == 'Camada de casos de uso'), [])
    camadas = [(c[0], c[1], c[2], [{k: v for k, v in x.items() if k not in ('regras', 'tracejar', 'riscadas')} for x in c[3]]) if c[0] == 'Camada de casos de uso' else c for c in camadas]
    g = _l3_componentes(m, rid, entrada, camadas, saidas, ligacoes, cen, nota)
    nos = [{'id': f'l3-{rid}-uc{i}', 'col': i % 3, 'label': x['label'], 'sub': x.get('sub', ''), 'cor': COR['BFMF'] if rid.split('-')[1] == 'bff' else COR['VAS'],
            'componentes': [({'label': rg, 'sub': 'mantida no programa corporativo', 'dashed': True} if (rg in x.get('riscadas', ()) or x.get('tracejar')) else {'label': rg, 'sub': ''}) for rg in x.get('regras', [])] or [{'label': 'sem regra de negócio própria', 'sub': ''}]} for i, x in enumerate(casos)]
    cols = [('Casos de uso e regras de negócio', COR['BFMF'])] + [('', COR['BFMF'])] * 2
    g2 = grafo_contextos(f'Casos de uso e regras de negócio de {rid}', nos, [], cols,
                         'Cada caixa é um caso de uso do componente, e as caixas amarelas dentro dele são as regras de negócio do fluxo que ele aplica (código e nome). Uma regra aparece em um só caso de uso: no BFMF ficam validação do pedido, decisão e composição de serviços; no serviço de dados, as regras ligadas aos comandos SQL dele (nos corporativos, aos programas corporativos).'
                         + (' Tracejadas: regras que o agregado corporativo não usa, porque continuam dentro dos programas corporativos originais.' if any(x.get('tracejar') for x in casos) else ''), [], 300)
    if any(x.get('riscadas') for x in casos):
        g2['note'] += ' Tracejadas: regras das funcionalidades corporativas, que continuam dentro dos programas corporativos e não serão implementadas no BFMF.'
    if any(x.get('tracejar') or x.get('riscadas') for x in casos):
        g2['dashed_label'] = 'tracejado = regra mantida dentro do programa corporativo (não usada no agregado)'
    return [g, checa_ids(m, g2)]


def _l3_componentes(m, rid, entrada, camadas, saidas, ligacoes, cen, nota):
    """C4 nível 3 de uma aplicação: caixa de entrada (quem chama), as camadas da aplicação e caixas de saída (serviços, filas e programas), todas ligadas.
    Os serviços de fora da aplicação ficam sempre em caixas próprias, nunca dentro dos endpoints ou das portas de saída.
    `saidas` = [(chave, rótulo, subtítulo, cor, componentes, deslocamento de coluna)]; `ligacoes` = [(chave de origem, chave de destino, rótulo)], com 'ad' para a última camada da aplicação."""
    nos, cols, ids = [], [], []
    for k, (rot, sub, cor, comps) in enumerate([entrada] + camadas):
        nid = f'l3-{rid}-{k}'
        ids.append(nid)
        nos.append({'id': nid, 'col': k, 'label': rot, 'sub': sub, 'cor': cor, 'componentes': comps})
        cols.append((rot, cor))
    ar = [{'from': ids[k], 'to': ids[k + 1], 'label': ''} for k in range(len(ids) - 1)]
    chave = {'ad': ids[-1]}
    base = len(ids)
    ncols = max((x[5] for x in saidas), default=0) + 1
    titulos = {0: 'Serviços e filas de baixa de pedido (saída)'}
    for x in saidas:   # o título de cada coluna de saída é o rótulo da caixa que fica nela
        titulos.setdefault(x[5], x[1])
    for off in range(ncols):
        cols.append((titulos.get(off, 'Saída'), COR['HOST']))
    for ch, rot, sub, cor, comps, off in saidas:
        nid = f'l3-{rid}-s-{ch}'
        chave[ch] = nid
        nos.append({'id': nid, 'col': base + off, 'label': rot, 'sub': sub, 'cor': cor, 'componentes': comps})
    for a, b, rot in ligacoes:
        ar.append({'from': chave[a], 'to': chave[b], 'label': rot})
    g = grafo_contextos(f'C4 nível 3 (componentes) de {rid}', nos, ar, cols, nota, [], 300)
    g['fronteiras'] = [{'label': f'Dentro da aplicação {rid} (o que está fora do tracejado está fora dela)', 'nodes': ids[1:]}]
    return checa_ids(m, g)


def l3_bffs(m, f18, ev, cen):
    out = []
    for r in [x for x in m['recursos'] if x['tipo'] == 'BFMF']:
        entra = sorted({i['de'] for i in m['integracoes'] if i['para'] == r['id'] and i['protocolo'] == 'REST'})
        alvos = sorted({i['para'] for i in m['integracoes'] if i['de'] == r['id'] and i['protocolo'] == 'REST'})
        ctrl = [{'label': f'Endpoint {f}', 'sub': ev['funcs'][f]['nome']} for f in r['funcs'] if ev['funcs'][f]['entry']]
        # regras do fluxo (fase 12) que o BFMF aplica: validação do pedido, decisão e composição de serviços diferentes (as que tocam os dados de um serviço ficam no caso de uso desse serviço)
        casos = [{'label': f'Caso de uso {f}', 'sub': 'compõe a resposta' if ev['funcs'][f]['entry'] else 'funcionalidade corporativa',
                  'regras': regras_do_caso(m, r['id'], f'Caso de uso {f}'), 'riscadas': regras_riscadas(m, r['id'], f'Caso de uso {f}')} for f in r['funcs']]
        portas = [{'label': 'RestClient → ' + a, 'sub': tipo_de(m, a) + ' · REST'} for a in alvos]
        out += (_l3(m, r['id'],
                       ('Quem chama (entrada)', 'chamadores REST do BFMF', COR['MFE'], [{'label': a, 'sub': tipo_de(m, a), 'rid': a} for a in entra]),
                       [('Endpoints REST', 'entrada do MFE', COR['MFE'], ctrl), ('Camada de casos de uso', 'composição das chamadas', COR['BFMF'], casos),
                        ('Portas de saída', 'clientes REST', COR['VAS'], portas)],
                       [('rest', 'Serviços chamados', 'VAS e Domain Microservices, por REST', COR['DOMAIN_MICROSERVICE'], [{'label': a, 'sub': tipo_de(m, a), 'rid': a} for a in alvos], 0)],
                       [('ad', 'rest', '')],
                       cen, 'O que está fora do BFMF (quem o chama e os serviços que ele chama) aparece em caixas próprias, à esquerda e à direita. Dentro do BFMF: endpoints REST, casos de uso (as regras de negócio ficam no diagrama de casos de uso logo abaixo) e portas de saída (os clientes REST). Sem camada de domínio nem Kafka: nada nos relatórios os pede.'))
    return out


def l3_domains(m, f18, ev, cen):
    out = []
    cmds = set(m['cmd_res']) | set(m['corp'])
    R = {x['id']: x for x in m['recursos']}
    for r in [x for x in m['recursos'] if x['tipo'] in ('DOMAIN_MICROSERVICE', 'VAS')]:
        ehc = r['id'] in {x['dono'] for x in m['corp'].values()}   # serviço de domínio corporativo: chama programas corporativos, não executa comandos SQL
        opx = (lambda ops: 'chamada ao programa corporativo') if ehc else (lambda ops: ', '.join(ops))   # no domínio corporativo não há SELECT/INSERT: o agregado chama o programa
        dm = next((d for d in f18['dom'] if d['id'] == r['origem']), None)   # o VAS (Query) não tem camada de domínio
        entra = sorted({i['de'] for i in m['integracoes'] if i['para'] == r['id'] and i['protocolo'] == 'REST'})
        sai = sorted({i['para'] for i in m['integracoes'] if i['de'] == r['id'] and i['protocolo'] == 'REST'})
        meus = sorted(c for c, o in m['dono'].items() if o == r['id'])
        # as funcionalidades terminam nos BFMFs: o domínio expõe recursos sobre os seus comandos SQL (um endpoint e um caso de uso por propósito de comando), sem o id da funcionalidade
        props_m = list(dict.fromkeys((R[m['cmd_res'][c][0]]['proposito'], opx(R[m['cmd_res'][c][0]]['operacoes'])) for c in meus))
        prop_funcs = defaultdict(list)    # funcionalidades que usam cada propósito de comando (referência, sem desenhar a relação)
        for g_, ps_ in PASSOS.items():
            for c in meus:
                p_ = R[m['cmd_res'][c][0]]['proposito']
                if any(y['cmds'] and c.split('.')[0] in y['cmds'] for y in ps_) and g_ not in prop_funcs[p_]:
                    prop_funcs[p_].append(g_)
        fn = lambda p_: ' · ' + ', '.join(sorted(prop_funcs[p_])) if prop_funcs.get(p_) else ''   # noqa: E731
        ctrl = [{'label': f'Endpoint: {p_}', 'sub': o_ + fn(p_)} for p_, o_ in props_m] or [{'label': 'Endpoint de consulta', 'sub': 'chamado por outras aplicações'}]
        casos = [{'label': f'Caso de uso: {p_}', 'sub': 'invariantes do agregado' + fn(p_), 'regras': regras_do_caso(m, r['id'], f'Caso de uso: {p_}'), 'tracejar': ehc} for p_, o_ in props_m] or [{'label': 'Caso de uso de consulta', 'sub': 'chamado por outro domínio'}]
        dom = [{'label': x, 'sub': 'classe'} for x in dm['comps'] if x not in cmds] if dm else []
        portas = [{'label': 'MQAdapter → ' + R[m['cmd_res'][c][0]]['comando'], 'sub': opx(R[m['cmd_res'][c][0]]['operacoes']) + ' · ' + R[m['cmd_res'][c][0]]['proposito'], 'detail': 'SEND_ALTA e RECEIVE_ALTA · ' + R[m['cmd_res'][c][0]]['comando'] + ': ' + opx(R[m['cmd_res'][c][0]]['operacoes']) + ' · ' + R[m['cmd_res'][c][0]]['proposito'] + ' · classes: ' + ', '.join(R[m['cmd_res'][c][0]]['tabelas'])} for c in uni(m, meus)] + [{'label': 'RestClient → ' + a, 'sub': 'REST'} for a in sai]
        curta = lambda q: q.split('.', 2)[2].rsplit('.', 1)[0]   # contexto.propósito, sem o prefixo e o sufixo da fila
        filas_req = [{'label': R[m['cmd_res'][c][0]]['comando'], 'sub': curta(m['cmd_res'][c][0]), 'rid': m['cmd_res'][c][0], 'detail': m['cmd_res'][c][0] + ' · ' + R[m['cmd_res'][c][0]]['proposito']} for c in uni(m, meus)]
        progs = [{'label': R[m['cmd_res'][c][2]]['comando'], 'sub': m['cmd_res'][c][2] + ' · ' + R[m['cmd_res'][c][2]]['proposito'], 'rid': m['cmd_res'][c][2]} for c in uni(m, meus)]
        filas_rsp = [{'label': R[m['cmd_res'][c][1]]['comando'], 'sub': curta(m['cmd_res'][c][1]), 'rid': m['cmd_res'][c][1], 'detail': m['cmd_res'][c][1] + ' · ' + R[m['cmd_res'][c][1]]['proposito']} for c in uni(m, meus)]
        mk_ = lambda c, i_: m['alta'][m['cmd_res'][c][0]][i_]   # noqa: E731  (0 = fila de alta de pedido, 1 = de resposta)
        filas_areq = [{'label': R[m['cmd_res'][c][0]]['comando'], 'sub': mk_(c, 0), 'rid': mk_(c, 0), 'detail': mk_(c, 0) + ' · ' + R[m['cmd_res'][c][0]]['proposito']} for c in uni(m, meus)]
        filas_arsp = [{'label': R[m['cmd_res'][c][0]]['comando'], 'sub': mk_(c, 1), 'rid': mk_(c, 1), 'detail': mk_(c, 1) + ' · ' + R[m['cmd_res'][c][0]]['proposito']} for c in uni(m, meus)]
        cd_ = 1 if m['func'] else 0
        desc_prg = 'recebem o pedido e chamam o programa corporativo original (que executa o SQL)' if m['corp'] and r['origem'] in {x['dono'] and next((d['id'] for d in f18['dom'] if m['dm_res'][d['id']] == x['dono']), None) for x in m['corp'].values()} else 'recebem o pedido e executam o SQL no DB2'
        coords = progs
        funcs_ = [{'label': R[m['cmd_res'][c][2]]['comando'], 'sub': m['func'][m['cmd_res'][c][2]] + ' · ' + R[m['cmd_res'][c][2]]['proposito'], 'rid': m['func'][m['cmd_res'][c][2]]} for c in uni(m, meus)] if cd_ else []
        saidas = [('req', 'Filas de baixa de pedido', ('MQ_REQ de cada programa corporativo' if ehc else 'MQ_REQ de cada comando'), COR['MQ_REQ'], filas_req, 0),
                  ('areq', 'Filas de alta de pedido', 'recebem da fila de baixa; o programa lê delas', COR['MQ_REQ_ALTA'], filas_areq, 1),
                  *((('prg', 'Programas coordenadores', 'leem a fila de alta, chamam o funcional e respondem', COR['PROGRAM_COORD'], coords, 2),
                     ('fn', 'Programas funcionais', desc_prg.replace('recebem o pedido e ', 'recebem o pedido do coordenador e '), COR['PROGRAM_DB2'], funcs_, 3)) if cd_ else
                    (('prg', 'Programas mainframe', desc_prg, COR['PROGRAM_DB2'], progs, 2),)),
                  ('arsp', 'Filas de alta de resposta', 'o programa responde nelas; a fila de baixa recebe daí', COR['MQ_RSP_ALTA'], filas_arsp, 3 + cd_),
                  ('rsp', 'Filas de baixa de resposta', ('MQ_RSP de cada programa corporativo' if ehc else 'MQ_RSP de cada comando'), COR['MQ_RSP'], filas_rsp, 4 + cd_)]
        lig = [('ad', 'req', 'SEND_BAIXA'), ('req', 'areq', 'ENCAMINHA'), ('areq', 'prg', 'RECEIVE_ALTA'), *([('prg', 'fn', 'LINK')] if cd_ else []), ('prg', 'arsp', 'SEND_ALTA'), ('arsp', 'rsp', 'ENCAMINHA'), ('rsp', 'ad', 'RECEIVE_BAIXA')]
        if sai:
            saidas.insert(0, ('rest', 'Serviços chamados', 'outros Domain Microservices, por REST', COR['DOMAIN_MICROSERVICE'], [{'label': a, 'sub': tipo_de(m, a), 'rid': a} for a in sai], 0))
            lig.insert(0, ('ad', 'rest', ''))
        out += (_l3(m, r['id'],
                       ('Quem chama (entrada)', 'chamadores REST do microserviço', COR['BFMF'], [{'label': a, 'sub': tipo_de(m, a), 'rid': a} for a in entra]),
                       [('Endpoints REST', 'entrada', COR['BFMF'], ctrl), ('Camada de casos de uso', 'orquestra o domínio', COR['VAS'], casos),
                        *([('Camada de domínio', dm['raiz'], COR['DOMAIN_MICROSERVICE'], dom)] if dm else []), ('Portas de saída', ('MQAdapter por programa corporativo e RestClient' if ehc else 'MQAdapter por comando SQL e RestClient'), COR['MQ_REQ'], portas)],
                       saidas, lig, cen,
                       'O que está fora do microserviço aparece em caixas próprias: quem o chama, outros serviços REST e, para cada ' + ('programa corporativo chamado' if ehc else 'comando SQL') + ', as filas de baixa e de alta de pedido, o programa mainframe ' + ('novo que recebe o pedido e chama o programa corporativo original' if ehc else 'que recebe o pedido e executa o SQL') + ' e as filas de alta e de baixa de resposta. ' + ('Os programas corporativos aparecem nas portas de saída, no MQAdapter de cada programa (nome e propósito)' if ehc else 'Os comandos SQL aparecem expandidos nas portas de saída, no MQAdapter de cada comando (query original, operação e propósito)') + ' e voltam em cada fila e programa. Dentro dele: endpoints REST, casos de uso, camada de domínio, portas de saída (um MQAdapter por ' + ('programa corporativo' if ehc else 'comando SQL') + ', direto com as filas, e os clientes REST). Sem publicadores e consumidores Kafka: nenhum relatório os decide.'))
    return out


# ---------------------------------------------------------------- referências simbólicas
class Simbolos:
    """Telas, programas, tabelas e comandos do sistema atual não aparecem no relatório: cada um vira um símbolo (TELA-nn, CMD-nn, PGM-nn) ou, no caso das tabelas, o nome da classe de domínio."""
    RE_CMD = r'\b[A-Z][A-Z0-9]{3,7}-Q\d+(?:\.\d+)?\b'
    RE_CMD_LOW = r'\b[a-z][a-z0-9]{3,7}-q\d+(?:-\d+)?\b'
    RE_JSP = r'[\w/]+\.jsp\b'
    RE_PROG = r'(?!)'   # definido em __init__ a partir dos programas conhecidos
    RE_TAB = r'(?!)'   # definido em __init__ a partir das tabelas conhecidas (um padrão genérico pegaria nomes de negócio escritos com sublinhado)

    def __init__(self, f18s, info, papel_tab, ux, ana, interp=None, programas=(), comandos=()):
        cods = sorted({c for f in f18s.values() for c, *_ in f['cmds']} | set(comandos))   # comandos: os originais executados dentro dos programas corporativos
        bases = sorted({c.split('.')[0] for c in cods})
        # o comando é citado pelo código da query original mapeada na fase 10 (sql-mapping); o desdobrado leva o sufixo .k. O link para a referência completa é posto pelo ligar
        self.cmd = {b: b for b in bases}
        for c in cods:
            if '.' in c:
                self.cmd[c] = c
        self.cmd_low = {}
        for c, sym in self.cmd.items():
            self.cmd_low[c.lower()] = c.lower()
            self.cmd_low[slug(c)] = slug(c)
        telas = sorted({t for f in f18s.values() for d in f['dcs'] for t in d['telas']} | set(ux['telas']))
        nomes = {x['tela']: x['nome'] for x in (interp or {}).get('telas', [])}
        self.tela = {t: nomes.get(t) or f'TELA-{i:02d}' for i, t in enumerate(telas, 1)}
        progs = sorted({c.split('-')[0] for c in cods} | set(programas))
        self.prog = {p: f'PGM-{i:02d}' for i, p in enumerate(progs, 1)}
        self.RE_PROG = r'\b(?:' + '|'.join(re.escape(x) for x in sorted(progs, key=len, reverse=True)) + r')\b(?!-Q\d)' if progs else r'(?!)'   # o programa dentro do código da query (PROG-Qnn) fica: é a referência à query original
        self.classe = {}
        for _s, bt, rows in S.tabelas(S.fase(ana, '16 ')):
            if bt.startswith('Classes de domínio: tabela física → classe'):
                for r in rows:
                    self.classe[r['Tabela'].split('.')[-1]] = r['Classe']
        for t in [t for b in bases for t in info.get(b, {}).get('tabelas', [])]:
            self.classe.setdefault(t.split('.')[-1], None)
        self.tab = {t: cl or f'TAB-{i:02d}' for i, (t, cl) in enumerate(sorted(self.classe.items()), 1)}
        self.extra = {}
        self.novos = set()
        conhecidas = set(self.classe)
        for t in list(papel_tab):
            conhecidas.add(t.split('.')[-1])
        self.RE_TAB = r'\b(?:' + '|'.join(re.escape(t) for t in sorted(conhecidas, key=len, reverse=True)) + r')\b' if conhecidas else r'(?!)'

    def _um(self, m):
        t = m.group(0)
        if t in self.novos:
            return t
        for d in (self.cmd, self.tela, self.prog, self.tab):
            if t in d:
                return d[t]
        pref = 'TELA' if t.endswith('.jsp') else 'PGM' if re.fullmatch(self.RE_PROG, t) else 'TAB' if re.fullmatch(self.RE_TAB, t) else 'CMD'
        return self.extra.setdefault(t, f'{pref}-X{len(self.extra) + 1:02d}')

    def texto(self, t):
        t = re.sub(r' \(' + self.RE_TAB + r'\)', '', t)
        t = re.sub(r'consulta legada', 'consulta original', t)
        t = re.sub(self.RE_CMD + '|' + self.RE_JSP + '|' + self.RE_PROG + '|' + self.RE_TAB, self._um, t)
        return re.sub(self.RE_CMD_LOW, lambda m: self.cmd_low.get(m.group(0), m.group(0)), t)

    def walk(self, x):
        if isinstance(x, str):
            return self.texto(x)
        if isinstance(x, dict):
            return {k: self.walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [self.walk(v) for v in x]
        if isinstance(x, tuple):
            return tuple(self.walk(v) for v in x)
        return x

    def residuos(self, x, acc=None):
        """Textos que ainda citam o sistema atual: comandos, telas, programas, tabelas ou a palavra legado."""
        acc = [] if acc is None else acc
        if isinstance(x, str):
            for p in (self.RE_CMD, self.RE_CMD_LOW, self.RE_JSP, self.RE_PROG, self.RE_TAB, r'(?i)\blegad[oa]s?\b'):
                acc += [t for t in re.findall(p, x) if t not in self.novos]
        elif isinstance(x, dict):
            for v in x.values():
                self.residuos(v, acc)
        elif isinstance(x, (list, tuple)):
            for v in x:
                self.residuos(v, acc)
        return acc

    def secao(self, modelos, info, ux):
        cmds = []
        for b, sym in sorted(self.cmd.items(), key=lambda kv: _nat(kv[1])):
            if '.' in b or b in CORP:
                continue
            ops = ', '.join(info.get(b, {}).get('operacoes', [])) or '—'
            tabs = ', '.join(sorted({self.tab[t] for t in info.get(b, {}).get('tabelas', []) if t in self.tab})) or '—'
            cmds.append((sym, ops, tabs))
        telas = [(sym, (ux['telas'].get(t) or {}).get('Finalidade') or '—') for t, sym in sorted(self.tela.items(), key=lambda kv: kv[1])]
        return rm.S('simbolos', 'Referências simbólicas', [
            rm.X('O sistema atual será substituído: telas, programas e tabelas dele não são citados neste relatório. Cada comando SQL é citado pelo código da query original mapeada na fase 10 (sql-mapping), com link para a sua referência completa e cada tela pelo nome próprio que a interpretação deu a ela (TELA-nn só quando falta o nome); as tabelas aparecem pelo nome da classe de domínio da fase 16.'),
            rm.T('Comandos SQL', ['Query original (fase 10)', 'Operação', 'Classes de domínio acessadas'], cmds),
            rm.T('Telas', ['Nome da tela', 'Finalidade (fase 15)'], telas)])


def sequencias(m, f18, ev, cen):
    """Um diagrama por funcionalidade entry point de uma entrega Presentation (as corporativas aparecem dentro dos diagramas das entry points que as chamam). As regras de negócio da fase 12 entram em notas, no serviço que as executa depois da quebra em chamadas:
    regra só de uma classe (ou de classes de um Group Query) → no Domain Microservice (ou no VAS) dono dos dados; regra que junta classes de serviços diferentes → no BFMF, que compõe;
    regra sem dados (validação do pedido, derivação, decisão de chamar função corporativa) → no BFMF antes das chamadas; erro devolvido → no BFMF depois delas."""
    out = []
    LQ, LQA, LP, LRA, LR = 'mainframe-req', 'mainframe-req-alta', 'mainframe-prg', 'mainframe-rsp-alta', 'mainframe-rsp'   # fila de baixa de pedido → fila de alta de pedido → programa → fila de alta de resposta → fila de baixa de resposta
    dc_de = {c: d for d in f18['dcs'] for c in d['comps']}
    ag_res = {d['agregado']: m['dm_res'][d['id']] for d in f18['dom']}
    dm_de_classe = {x: m['dm_res'][d['id']] for d in f18['dom'] for x in d['comps']}
    for f in sorted(ev['funcs'], key=lambda x: (not ev['funcs'][x]['entry'], x)):
        v = ev['funcs'][f]
        dc = dc_de.get(f)
        if not dc or dc['tipo'] != 'Presentation':
            continue
        res = m['dc_res'][dc['id']]
        bff, mfe = res['bff'], res['mfe']
        parts = ['usuario', mfe]
        passos = []
        grupo_de = {}

        def lf(app, uc=None):
            """Linha de vida: o próprio participante ou, dentro de uma aplicação, um caso de uso (as linhas da mesma aplicação ficam juntas, dentro de uma caixa tracejada)."""
            lid = app if uc is None else f'{app}::{uc}'
            if lid not in parts:
                if uc is not None:
                    grupo_de[lid] = app
                ult = max((i for i, q in enumerate(parts) if grupo_de.get(q) == app), default=None) if uc is not None else None
                parts.insert(ult + 1, lid) if ult is not None else parts.append(lid)
            return lid

        def ucb(o_):
            return lf(bff, pascal(ev['funcs'][o_]['nome']))
        atual = [f]

        def entra(o_):
            """O caso de uso da entry point chama o da funcionalidade corporativa o_ (no BFMF) e recebe o retorno quando ela termina."""
            if atual[0] == o_:
                return
            if atual[0] != f:
                passos.append((ucb(atual[0]), ucb(f), 'retorna', True))
            if o_ != f:
                passos.append((ucb(f), ucb(o_), f'chama a funcionalidade corporativa {o_}', False))
            atual[0] = o_

        def via_fila(app, cods):
            """A aplicação envia o pedido à fila de baixa, que o passa à fila de alta; o programa mainframe o processa e responde na fila de alta de resposta, que encaminha à fila de baixa de resposta, de onde a aplicação a lê."""
            r_, por = [], {}
            for c in cods:
                if c not in m['cmd_res']:
                    r_ += [(app, LQ, f'SEND_BAIXA: {c}', False), (LR, app, 'RECEIVE_BAIXA: resposta', True)]
                    continue
                por.setdefault(m['cmd_res'][c], []).append(c)   # comandos do mesmo programa corporativo vão numa só chamada à fila
            o2p = {o: k for k, x in m['corp'].items() for o in x['cmds']}
            for (req, rsp, prg), cs_ in por.items():
                lab = ', '.join(dict.fromkeys(o2p.get(c, c) for c in cs_))   # o domínio corporativo chama o programa corporativo, não o comando SQL
                areq, arsp = m['alta'][req]
                r_ += [(app, LQ, f'SEND_BAIXA: {req} ({lab})', False), (LQ, LQA, f'ENCAMINHA: {areq}', False), (LQA, LP, (f'RECEIVE_ALTA: coordenador {prg} → funcional {m["func"][prg]} ({lab})' if prg in m['func'] else f'RECEIVE_ALTA: programa {prg} ({lab})'), False),
                       (LP, LRA, f'SEND_ALTA: {arsp}', False), (LRA, LR, f'ENCAMINHA: {rsp}', False), (LR, app, f'RECEIVE_BAIXA: {rsp} ({lab})', True)]
            return r_
        if True:
            passos += [('usuario', mfe, f'aciona: {v["nome"]}', False), (mfe, ucb(f), f'REST: {v["nome"]}', False)]
        R_ = {r['id']: r for r in m['recursos']}

        def cmds_corp(g_, vistos=()):
            """Comandos originais de toda a função corporativa g_ (inclusive as que ela chama)."""
            r_ = []
            for x in PASSOS.get(g_, []):
                if x['tipo'] == 'corporativa' and x['chama'] and x['chama'] not in vistos:
                    r_ += cmds_corp(x['chama'], vistos + (x['chama'],))
                else:
                    r_ += x['cmds']
            return list(dict.fromkeys(r_))

        def chamada_corp(g_, base):
            """A função corporativa é mantida dentro dos programas corporativos; o fluxo dela (regras e passos internos) não aparece e vira uma única chamada a cada programa."""
            cs_ = cmds_corp(g_, (g_,))
            return [{**base, 'func': g_, 'tipo': 'corporativa', 'sql': True, 'cmds': cs_, 'chama': None, 'alt': None}] if cs_ else []

        def achata(g_, vistos=()):
            """Passos do fluxo de negócio de g_, com as funções corporativas que ele chama expandidas no lugar da chamada: o BFMF conduz tudo, o domínio só executa os dados.
            A função corporativa não é expandida: vira só a chamada ao programa corporativo."""
            r_ = []
            for x in PASSOS.get(g_, []):
                if x['tipo'] == 'corporativa' and x['chama'] and x['chama'] not in vistos:
                    r_ += chamada_corp(x['chama'], x) if cen == 'C' else achata(x['chama'], vistos + (x['chama'],))
                else:
                    r_.append(x)
            return r_
        if cen == 'C' and not v['entry']:   # regras da função corporativa: continuam no programa corporativo, não serão implementadas (aparecem riscadas no caso de uso do BFMF)
            for x in PASSOS.get(f, []):
                if x['tipo'] in ('regra', 'erro'):
                    REG.setdefault(id(m), []).append({'seq': f, 'origem': x['func'], 'regra': rotulo_regra(x), 'nome': x['nome'], 'app': bff, 'caso': f'Caso de uso {f}', 'tracejada': True, 'riscada': True,
                                                      'por_regra': 'a regra é do fluxo da funcionalidade corporativa, que continua dentro do programa corporativo e não será implementada no BFMF',
                                                      'por_caso': f'ele é o da funcionalidade corporativa {f}'})
        etapas = chamada_corp(f, PASSOS[f][0]) if (cen == 'C' and not v['entry'] and PASSOS.get(f)) else achata(f, (f,))

        def codigos(x):
            out_ = []
            for o in x['cmds']:
                out_ += sorted((c for c in m['cmd_res'] if c.split('.')[0] == o), key=lambda c: [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', c)])
            return list(dict.fromkeys(out_))
        # as regras que tocam os dados de um serviço ficam no serviço, dentro do passo de dados dele (invariantes ligadas aos comandos); o resto fica no BFMF
        sqls = [x for x in etapas if x['sql'] and codigos(x)]
        inv = defaultdict(list)
        soltos = set()
        for i_, x in enumerate(etapas):
            if x['sql'] or x['tipo'] not in ('regra', 'erro'):
                continue
            svc_ = servicos_regra(m, ev, x)
            alvo = next((y for y in sqls if svc_ and svc_ in {m['dono'][c] for c in codigos(y) if c in m['dono']}), None) if svc_ else None
            if alvo:
                inv[(id(alvo), svc_)].append(x)
                soltos.add(i_)
        feitos = set()
        vistas = set()
        notas_svc = set()
        for i_, x in enumerate(etapas):
            if i_ in soltos:
                continue
            if not (x['sql'] and codigos(x)):
                if x['nome'] not in vistas:
                    entra(x['func'])
                    passos += [(ucb(x['func']), ucb(x['func']), rotulo_regra(x), 'nota')]
                    vistas.add(x['nome'])
                    if x['tipo'] in ('regra', 'erro'):
                        REG.setdefault(id(m), []).append({'seq': f, 'origem': x['func'], 'regra': rotulo_regra(x), 'nome': x['nome'], 'app': bff, 'caso': f'Caso de uso {x["func"]}',
                                                          'por_regra': justificar(m, ev, x, bff), 'por_caso': f'ele é o da funcionalidade {x["func"]}, que define a regra no fluxo e a conduz no BFMF'})
                continue
            entra(x['func'])
            cods = [c for c in codigos(x) if c in m['dono']]
            por_dono = defaultdict(list)
            for c in cods:
                por_dono[m['dono'][c]].append(c)
            primeiro = True
            dono_x = servicos_regra(m, ev, x)
            for svc, cs_ in sorted(por_dono.items(), key=lambda kv: kv[0] != dono_x):   # a regra do passo fica no serviço dono dela (o mesmo dos casos de uso)
                for p in (LQ, LQA, LP, LRA, LR):
                    if p not in parts:
                        parts.append(p)
                novos = [c for c in cs_ if c not in feitos]
                feitos.update(novos)
                props = list(dict.fromkeys(R_[m['cmd_res'][c][0]]['proposito'] for c in cs_))
                rot = ('Alternativa: ' if x['alt'] else '') + '; '.join(props[:2]) + (f' (+{len(props) - 2})' if len(props) > 2 else '')
                suc = lf(svc, pascal(props[0]))
                passos += [(ucb(x['func']), suc, 'REST: ' + rot, False)]
                caso_ = 'Caso de uso: ' + props[0]
                ns_ = ([x] if (svc == dono_x or (primeiro and dono_x not in por_dono)) else []) + list(inv[(id(x), svc)])
                for y in ns_:
                    if (svc, rotulo_regra(y)) not in notas_svc:
                        notas_svc.add((svc, rotulo_regra(y)))
                        tracej_ = svc in {x_['dono'] for x_ in m['corp'].values()}   # a regra do domínio corporativo fica dentro do programa corporativo, não entra na sequência
                        if not tracej_:
                            passos += [(suc, suc, rotulo_regra(y), 'nota')]
                        if y['tipo'] in ('regra', 'erro'):
                            REG.setdefault(id(m), []).append({'seq': f, 'origem': y['func'], 'regra': rotulo_regra(y), 'nome': y['nome'], 'app': svc, 'caso': caso_,
                                                              'tracejada': tracej_, 'por_regra': justificar(m, ev, y, svc), 'por_caso': f'o passo em que a regra aparece chama o comando «{props[0]}», o propósito deste caso de uso'})
                primeiro = False
                passos += via_fila(suc, novos)
                passos += [(suc, ucb(x['func']), 'resposta REST', True)]
        if True:
            entra(f)
            passos += [(ucb(f), mfe, 'resposta REST', True), (mfe, 'usuario', 'exibe o resultado', True)]
        suf_ = ' dos comandos SQL' + (' e dos programas corporativos' if m['corp'] else '')
        LG = {LQ: ('Filas de baixa de pedido', 'MQ_REQ', 'Filas IBM MQ de baixa de pedido' + suf_), LQA: ('Filas de alta de pedido', 'MQ_REQ_ALTA', 'Filas IBM MQ de alta de pedido' + suf_),
              LP: ('Programas mainframe', 'PROGRAM_COORD' if m['func'] else 'PROGRAM_DB2', ('Programas coordenadores, que leem a fila e chamam o programa funcional, e programas funcionais, que ' if m['func'] else 'Programas mainframe que processam o pedido (') + ('executam o SQL ou chamam o programa corporativo' if m['corp'] else 'executam o SQL') + ('' if m['func'] else ')')),
              LRA: ('Filas de alta de resposta', 'MQ_RSP_ALTA', 'Filas IBM MQ de alta de resposta' + suf_), LR: ('Filas de baixa de resposta', 'MQ_RSP', 'Filas IBM MQ de baixa de resposta' + suf_)}
        ordem = [p for p in parts if p not in LG] + [p for p in (LQ, LQA, LP, LRA, LR) if p in parts]
        nos = [({'id': p, 'label': p.split('::')[1], 'sub': 'caso de uso', 'cor': COR[tipo_de(m, grupo_de[p])], 'grupo': grupo_de[p], 'grupo_sub': tipo_de(m, grupo_de[p]),
                 'detail': f'Caso de uso {p.split("::")[1]} da aplicação {grupo_de[p]}'} if p in grupo_de else
                {'id': p, 'label': LG[p][0] if p in LG else 'Usuário' if p == 'usuario' else p, 'sub': LG[p][1] if p in LG else '' if p == 'usuario' else tipo_de(m, p), 'cor': COR[LG[p][1]] if p in LG else COR['USER'] if p == 'usuario' else COR[tipo_de(m, p)], 'detail': LG[p][2] if p in LG else 'Usuário' if p == 'usuario' else nome_curto(m, p)}) for p in ordem]
        g = rm.G(f'Sequência de {f} · {v["nome"]}', nos, [({'from': a, 'to': b, 'label': t, 'nota': True, **({'nota_tipo': x[0]} if x else {})} if r == 'nota' else {'from': a, 'to': b, 'label': t, 'retorno': r}) for a, b, t, r, *x in passos], kind='sequencia',
                 note='O BFMF conduz o fluxo de negócio da fase 12, na ordem das etapas: valida o pedido, chama cada serviço de dados só pelo que precisa obter, decide e trata o erro devolvido (notas no BFMF). O Domain Microservice (ou o VAS) não repete a funcionalidade: executa só os comandos SQL do passo e cuida das invariantes ligadas a esses comandos (notas amarelas no serviço: a regra de leitura ou gravação, o registro que deve existir, a chave que não pode duplicar). Cada passo traz só os comandos que o fluxo executa, com todos os comandos em que o original foi desdobrado; passos marcados como alternativa saem da mesma validação por condições diferentes, e só um deles executa em cada pedido. As funções corporativas chamadas pelo fluxo entram no lugar da chamada. As aplicações falam direto com as filas pelo MQ_ADAPTER interno: a fila de pedido (MQ_REQ) em que a aplicação publica e a fila de resposta (MQ_RSP) pela qual a resposta volta; o programa mainframe que executa o comando aparece nos diagramas da seção de programas mainframe. ' + ('O serviço de domínio corporativo envia o pedido à fila do programa corporativo: o programa mainframe novo chama o programa corporativo original, que executa o SQL. ' if m['corp'] else '') + ('' if v['entry'] else 'Funcionalidade corporativa: o diagrama mostra a função isolada, acionada pelo usuário pelo micro frontend e conduzida pelo BFMF; no sistema ela também é chamada por outras funcionalidades.'))
        g['nw'] = 200
        if v['entry']:   # o fluxo das funcionalidades corporativas está nos diagramas das entry points que as chamam: elas não têm diagrama próprio
            out.append(checa_ids(m, g, livres=('usuario', 'mainframe')))
    return out


def sequencias_mainframe(m, cen):
    """Um diagrama por programa mainframe (um por comando SQL ou por programa corporativo chamado): a aplicação dona envia o pedido à fila de baixa, que o encaminha à fila de alta; o programa o recebe, executa o comando no DB2 (ou chama o programa corporativo) e responde na fila de alta de resposta, que encaminha à fila de baixa de resposta."""
    R = {r['id']: r for r in m['recursos']}
    out, vistos = [], set()
    corp_de = {x['res']: (k, x) for k, x in m['corp'].items()}
    for cod, (req, rsp, prg) in sorted(m['cmd_res'].items(), key=lambda kv: (m['dono'][kv[0]], [int(x) if x.isdigit() else x for x in re.split(r'(\d+)', kv[0])])):
        if (req, rsp, prg) in vistos:
            continue
        vistos.add((req, rsp, prg))
        app = m['dono'][cod]
        rq = R[req]
        ops = ', '.join(rq['operacoes']) or 'operação não identificada'
        classes = ', '.join(rq['tabelas']) or '—'
        corp = corp_de.get((req, rsp, prg))
        areq, arsp = m['alta'][req]
        if corp:
            nome_c, x_ = corp
            alvo_ = f'programa corporativo {nome_c}'
            nota_ = f'Chama o programa corporativo {nome_c}: {ops} · {rq["proposito"]} · classes de domínio: {classes}'
            fim_ = 'o programa mainframe novo chama o programa corporativo original (que executa o SQL no DB2)'
        else:
            alvo_ = f'comando {cod}'
            nota_ = f'Executa o comando {cod}: {ops} · {rq["proposito"]} · classes de domínio: {classes}'
            fim_ = 'o programa mainframe executa o SQL no DB2'
        fn_ = m['func'].get(prg)   # com coordenador: o funcional executa e devolve ao coordenador, que responde
        if fn_:
            fim_ = fim_.replace('o programa mainframe novo chama', f'o coordenador {prg} chama (LINK) o funcional {fn_}, que chama').replace('o programa mainframe executa', f'o coordenador {prg} chama (LINK) o funcional {fn_}, que executa') + '; o coordenador recebe o retorno'
        passos = [(app, req, f'SEND_BAIXA: pedido do {alvo_}', False),
                  (req, areq, 'ENCAMINHA: da fila de baixa para a fila de alta de pedido', False),
                  (areq, prg, f'RECEIVE_ALTA: {rq["proposito"]}', False),
                  *([(prg, fn_, f'LINK: pedido do {alvo_}', False), (fn_, fn_, nota_, 'nota'), (fn_, prg, 'retorno do funcional', True)] if fn_ else [(prg, prg, nota_, 'nota')]),
                  (prg, arsp, f'SEND_ALTA: resposta do {alvo_}', False),
                  (arsp, rsp, 'ENCAMINHA: da fila de alta para a fila de baixa de resposta', False),
                  (rsp, app, 'RECEIVE_BAIXA: resposta', True)]
        note = f'{alvo_.capitalize()} a pedido de {app}: o MQ_ADAPTER da aplicação envia o pedido à fila de baixa, que o encaminha à fila de alta de pedido; {fim_} e responde na fila de alta de resposta, que encaminha à fila de baixa de resposta, de onde a aplicação lê. O formato das mensagens (copybooks) é definido na fase de contratos.'
        nos = [{'id': p, 'label': p, 'sub': tipo_de(m, p), 'cor': COR[tipo_de(m, p)], 'detail': R[p]['nome']} for p in (app, req, areq, prg, *((fn_,) if fn_ else ()), arsp, rsp)]
        g = rm.G(f'Programa mainframe {prg}' + (f' → {fn_}' if fn_ else '') + f' · {rq["proposito"]}', nos,
                 [({'from': a_, 'to': b_, 'label': t, 'nota': True, 'nota_tipo': 'comando SQL'} if r_ == 'nota' else {'from': a_, 'to': b_, 'label': t, 'retorno': r_}) for a_, b_, t, r_ in passos], kind='sequencia', note=note)
        g['nw'] = 210
        out.append(checa_ids(m, g))
    return out


def secoes_ux(m, f18, ux, cen):
    k = cen.lower()
    blocos = []
    for r in [x for x in m['recursos'] if x['tipo'] == 'MFE']:
        tel = r['telas']
        rows = []
        for t in tel:
            x = ux['telas'].get(t, {})
            rows.append((r['id'], t, CD.curto(x.get('Finalidade', '—'), 400), CD.curto(x.get('Jornada', '—'), 400), CD.curto(x.get('Layout sugerido', '—'), 500), x.get('Confiança', '—')))
        blocos.append(rm.T(f'Especificação UX de {r["id"]}: telas', ['Micro Frontend', 'Tela', 'Finalidade', 'Jornada', 'Layout sugerido', 'Confiança'], rows or [(r['id'], '—', 'sem tela analisada', '—', '—', '—')]))
        acoes = [(r['id'], t, a.get('Ação', ''), a.get('Significado', ''), a.get('Resultado', '')) for t in tel for a in ux['acoes'].get(t, [])]
        grupos = [(r['id'], t, a.get('Grupo', ''), a.get('Descrição', ''), a.get('Componentes (em ordem)', '')) for t in tel for a in ux['grupos'].get(t, [])]
        if acoes:
            blocos.append(rm.T(f'Especificação UX de {r["id"]}: ações', ['Micro Frontend', 'Tela', 'Ação', 'Significado', 'Resultado'], acoes))
        if grupos:
            blocos.append(rm.T(f'Especificação UX de {r["id"]}: agrupamentos de campos', ['Micro Frontend', 'Tela', 'Grupo', 'Descrição', 'Componentes (em ordem)'], grupos))
    blocos.append(rm.X('As especificações UX vêm da fase 15 (finalidade, jornada, layout sugerido, ações e agrupamentos das telas mantidas no funil). Cada MFE herda as telas do Delivery Context Presentation que o originou.'))
    return rm.S('ux', 'Especificações UX dos micro frontends', blocos)


def pendencias(m, f18, interp, cen):
    P = []
    for tipo, conf in (('HOST', 'UNCERTAIN'), ('MQ_REQ', 'UNCERTAIN'), ('MQ_REQ_ALTA', 'UNCERTAIN'), ('MQ_RSP_ALTA', 'UNCERTAIN'), ('MQ_RSP', 'UNCERTAIN'), ('PROGRAM_COORD', 'UNCERTAIN'), ('PROGRAM_DB2', 'UNCERTAIN'), ('PROGRAM_CORP', 'UNCERTAIN')):
        rs_ = [r for r in m['recursos'] if r['tipo'] == tipo]
        if rs_:
            P.append((f'Recursos {tipo} sem decisão', f'{len(rs_)} recurso(s) propostos a partir de {("cada programa corporativo chamado" if tipo == "PROGRAM_CORP" else "cada comando SQL") if tipo != "HOST" else "uma necessidade de hospedar os MFEs"}; {rs_[0]["evidencia"]}', conf, [tipo], 'calculado'))
    P.append(('Nomes dos programas mainframe e copybooks', 'Os nomes dos programas seguem o padrão <sistema>1 + 3 letras do propósito do comando' + (f' (coordenador) e, para o programa funcional que ele chama, <sistema>{digito_funcional()} + as mesmas 3 letras' if m['func'] else '') + ' e os dos copybooks, <sistema>W + 3 letras (8 posições, um de requisição e um de resposta por comando); foram propostos pelo gerador e a disponibilidade de cada nome no mainframe não foi confirmada. As filas da plataforma alta não são geradas: só as da baixa (FR.<sistema>.<contexto>.NI<propósito>.REQ e .RSP). Os copybooks são detalhados na fase de contratos.', 'UNCERTAIN', ['PROGRAM_DB2', 'MQ_REQ', 'MQ_RSP'], 'calculado'))
    P.append(('Kafka, projeções, bancos próprios e ReadStores', 'O nível 2 do C4 prevê esses containers, mas os relatórios não trazem nenhuma decisão de projeção, evento ou banco próprio; eles não foram modelados.', 'UNKNOWN', ['DOMAIN_MICROSERVICE', 'VAS'], 'calculado'))
    P += [(a, b, c, d, 'calculado') for a, b, c, d in m['pend']]
    if any(r['tipo_de'] == 'Delivery · Query' and r['tipo_para'] == 'Domain' for r in f18['rels']):
        P.append(('VAS lê pelas filas', 'A fase 18 mostra Query → Domain; na arquitetura o VAS executa os seus comandos pelo MQ_ADAPTER interno, direto com as filas, e não chama o Domain Microservice, então não há integração REST VAS → Domain.', 'CONFIRMED', ['VAS'], 'calculado'))
    for x in do_cenario(interp, 'lacunas', cen):
        P.append((x['assunto'], x['detalhe'], x['confianca'], x.get('tipos', []), 'IA'))
    return P


def validar_interp(interp, modelos):
    erros = []
    for k in sorted(set(interp) - CHAVES_RAIZ):
        erros.append(f'chave desconhecida na interpretação: {k}')
    for k in ('decisoes', 'lacunas'):
        for x in interp[k]:
            if x.get('confianca') not in CONF:
                erros.append(f'{k}: confianca deve ser CONFIRMED, UNCERTAIN ou UNKNOWN ({x.get("assunto")})')
            if 'cenario' in x:
                erros.append(f'{k}: o campo cenario não existe (a arquitetura alvo é uma só) ({x.get("assunto")})')
            for t in x.get('tipos') or []:
                if t not in TIPOS:
                    erros.append(f'{k}: tipo de recurso inexistente {t} ({x.get("assunto")})')
            if not str(x.get('assunto') or '').strip() or not str(x.get('detalhe') or x.get('decisao') or '').strip():
                erros.append(f'{k}: cada item precisa de assunto e {"detalhe" if k == "lacunas" else "decisao"}')
    for cen, m in modelos.items():
        cob = {t for x in do_cenario(interp, 'lacunas', cen) for t in x.get('tipos') or []}
        for t in sorted({r['tipo'] for r in m['recursos'] if r['confianca'] != 'CONFIRMED'}):
            if t not in cob:
                erros.append(f'os recursos {t} têm confiança UNCERTAIN ou UNKNOWN e precisam de uma lacuna com tipos: ["{t}"]')
    conhecidos = {c for m in modelos.values() for c in m['cmd_res']} | {c for m in modelos.values() for c in m['corp']}
    prop_de = {}
    for x in interp.get('comandos', []):
        if not str(x.get('comando') or '').strip() or not str(x.get('proposito') or '').strip():
            erros.append('comandos: cada item precisa de comando e proposito')
            continue
        if x['comando'] not in conhecidos and x['comando'] not in {c.split('.')[0] for c in conhecidos}:
            erros.append(f'comandos: comando desconhecido {x["comando"]}')
        prop_de[x['comando']] = x['proposito']
    for c in sorted(conhecidos):
        if c not in prop_de and c.split('.')[0] not in prop_de:
            erros.append(f'comandos: falta o propósito do comando {c}')
    conhecidas = {t for m in modelos.values() for r in m['recursos'] if r['tipo'] == 'MFE' for t in r['telas']}
    nomes_t = {}
    for x in interp.get('telas', []):
        if not str(x.get('tela') or '').strip() or not str(x.get('nome') or '').strip():
            erros.append('telas: cada item precisa de tela e nome')
            continue
        if x['tela'] not in conhecidas:
            erros.append(f'telas: tela desconhecida {x["tela"]}')
        nomes_t[x['tela']] = x['nome']
    for t in sorted(conhecidas - set(nomes_t)):
        erros.append(f'telas: falta o nome da tela {t}')
    if len(set(nomes_t.values())) != len(nomes_t):
        erros.append('telas: dois nomes de tela iguais')
    for x in interp['decisoes']:
        if not str(x.get('justificativa') or '').strip():
            erros.append(f'decisoes: falta justificativa ({x.get("assunto")})')
    return erros


def rastreio(m, ev, cen, k, pre):
    """Rastreio funcionalidade × regra de negócio × caso de uso: de onde a regra vem (fluxo da fase 12), em que diagramas de sequência aparece e em que caso de uso de que aplicação ela fica."""
    reg = REG.get(id(m), [])
    app_caso = {}
    for e in reg:
        app_caso.setdefault((e['app'], e['regra']), e['caso'])
    seqs = defaultdict(list)
    for e in reg:
        if e['seq'] not in seqs[(e['origem'], e['regra'], e['app'])] and not e.get('tracejada'):
            seqs[(e['origem'], e['regra'], e['app'])].append(e['seq'])
        else:
            seqs[(e['origem'], e['regra'], e['app'])]
    rows = [(o, rg, app, app_caso[(app, rg)], ', '.join(sorted(ss)) or 'não aparece: regra mantida no programa corporativo (tracejada no caso de uso)') for (o, rg, app), ss in seqs.items()]
    achadas = {(o, rg) for (o, rg, _a) in seqs}
    pres = {e['seq'] for e in reg}
    sem = []
    for f in ev['funcs']:
        for y in PASSOS.get(f, []):
            if y['tipo'] in ('regra', 'erro') and (f, rotulo_regra(y)) not in achadas and (f, rotulo_regra(y)) not in {(o, rg) for o, rg, *_ in sem}:
                sem.append((f, rotulo_regra(y), '—', 'não aparece em diagrama de sequência', '—'))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    ntot = len({(o, rg) for o, rg, *_ in rows})
    return rm.S(f'rastreio', f'Rastreio: funcionalidade × regra de negócio × caso de uso', [
        rm.T(f'Rastreio das regras de negócio', ['Funcionalidade de origem da regra', 'Regra de negócio', 'Aplicação', 'Caso de uso', 'Aparece nos diagramas de sequência de'], rows + sem),
        rm.X(f'Cada linha liga a regra do fluxo de negócio da fase 12 (funcionalidade de origem) à nota que a mostra nos diagramas de sequência e ao caso de uso, da aplicação em que a nota está, onde a regra aparece nos diagramas de casos de uso. '
             f'No BFMF o caso de uso é o da funcionalidade de origem; no serviço, o do propósito de comando chamado no passo em que a nota aparece. Uma regra fica em um só caso de uso de cada aplicação. '
             f'{ntot} regras de negócio aparecem nos diagramas de sequência; {len(sem)} do fluxo não aparecem em nenhum (linhas "não aparece em diagrama de sequência").')])


def tabelas_modelo(m):
    """Como o modelo de recursos é montado, em três tabelas: a transformação dos contextos em recursos, a convenção de nomes e o fluxo de integração
    com o mainframe (com o par coordenador e funcional e os programas corporativos quando o modelo os tem)."""
    dig = digito_funcional()
    import projeto_config
    pre = projeto_config.carregar().get('prefixo_core') or '<sistema>'   # prefixo dos programas do sistema (analise.config.json, prefixo_core)
    transf = [('Delivery Context de apresentação', 'MFE e BFMF', 'Um micro frontend e o backend dele por contexto de entrega de apresentação.'),
              ('Delivery Context de consulta', 'VAS', 'Um serviço de consulta (Value-Added Service) por contexto de entrega de consulta.'),
              ('Domain Context', 'DOMAIN_MICROSERVICE', 'Um microsserviço por contexto de domínio.'),
              ('Comando SQL', 'MQ_REQ e MQ_RSP (filas de baixa), MQ_REQ_ALTA e MQ_RSP_ALTA (filas de alta), ' + ('PROGRAM_COORD e PROGRAM_DB2' if m['func'] else 'PROGRAM_DB2'),
               'Cada comando SQL ganha as quatro filas e o programa mainframe que o executa.')]
    if m['corp']:
        transf.append(('Programa corporativo', 'as quatro filas, ' + ('PROGRAM_COORD e PROGRAM_CORP' if m['func'] else 'PROGRAM_CORP'),
                       'O programa mainframe novo chama o programa corporativo original em vez de executar SQL.'))
    nomes = [('MFE', 'tcap-fed-<contexto de entrega>', 'Identificadores em kebab-case, sem stop words; o prefixo vem dos entry points.'),
             ('BFMF', 'tcap-bff-<contexto de entrega>', ''), ('VAS', 'tcap-vas-<contexto de entrega>', ''), ('DOMAIN_MICROSERVICE', 'tcap-srv-<contexto de domínio>', ''),
             ('MQ_REQ', 'FR.TCAP.<CONTEXTO>.NI<PROPÓSITO>.REQ', 'Filas em caixa alta, com no máximo 48 posições.'),
             ('MQ_RSP', 'FL.TCAP.<CONTEXTO>.NI<PROPÓSITO>.RSP', ''),
             ('MQ_REQ_ALTA', 'TCAP.QL.REQ.TCAP.NI<PROPÓSITO>.01', 'O sufixo sobe quando outro contexto usa o mesmo propósito.'),
             ('MQ_RSP_ALTA', 'TCAP.QR.RSP.TCAP.NI<PROPÓSITO>.01', ''),
             ('PROGRAM_COORD' if m['func'] else 'PROGRAM_DB2', f'{pre}1 + 3 letras', 'Programa mainframe com 8 posições.')]
    if m['func']:
        nomes.append(('PROGRAM_DB2 ou PROGRAM_CORP', f'{pre}{dig} + as mesmas 3 letras do coordenador', 'O funcional do par.'))
    nomes.append(('Copybook', f'{pre}W + 3 letras', '8 posições.'))
    fluxo = [('1', 'Aplicação (MQ_ADAPTER no BFMF, no VAS ou no Domain Microservice)', 'MQ_REQ', 'Envia o pedido à fila de baixa de pedido.'),
             ('2', 'MQ_REQ', 'MQ_REQ_ALTA', 'O IBM MQ encaminha o pedido à fila de alta de pedido.')]
    if m['func']:
        fluxo += [('3', 'MQ_REQ_ALTA', 'PROGRAM_COORD', 'O coordenador lê o pedido da fila de alta.'),
                  ('4', 'PROGRAM_COORD', 'PROGRAM_DB2 ou PROGRAM_CORP', 'Chama o funcional com EXEC CICS LINK: ele executa o comando SQL ou chama o programa corporativo.'),
                  ('5', 'PROGRAM_COORD', 'MQ_RSP_ALTA', 'Responde na fila de alta de resposta.')]
    else:
        fluxo += [('3', 'MQ_REQ_ALTA', 'PROGRAM_DB2', 'O programa lê o pedido e executa o comando SQL.'), ('4', 'PROGRAM_DB2', 'MQ_RSP_ALTA', 'Responde na fila de alta de resposta.')]
    n = len(fluxo)
    fluxo += [(str(n + 1), 'MQ_RSP_ALTA', 'MQ_RSP', 'O IBM MQ encaminha a resposta à fila de baixa de resposta.'),
              (str(n + 2), 'MQ_RSP', 'Aplicação', 'A aplicação lê a resposta.')]
    # o mesmo fluxo em diagrama: uma coluna por tipo de recurso, ligações numeradas pelos passos
    cols = [('Aplicação', COR['BFMF']), ('Filas de baixa', COR['MQ_REQ']), ('Filas de alta', COR['MQ_REQ_ALTA']),
            ('Coordenador' if m['func'] else 'Programa mainframe', COR['PROGRAM_COORD'] if m['func'] else COR['PROGRAM_DB2'])] + \
           ([('Funcional', COR['PROGRAM_DB2'])] if m['func'] else [])
    nos = [{'id': 'f-app', 'label': 'Aplicação', 'sub': 'MQ_ADAPTER no BFMF, VAS ou Domain Microservice', 'col': 0},
           {'id': 'f-req', 'label': 'MQ_REQ', 'sub': 'fila de baixa de pedido', 'col': 1}, {'id': 'f-rsp', 'label': 'MQ_RSP', 'sub': 'fila de baixa de resposta', 'col': 1},
           {'id': 'f-areq', 'label': 'MQ_REQ_ALTA', 'sub': 'fila de alta de pedido', 'col': 2}, {'id': 'f-arsp', 'label': 'MQ_RSP_ALTA', 'sub': 'fila de alta de resposta', 'col': 2}]
    if m['func']:
        nos += [{'id': 'f-coord', 'label': 'PROGRAM_COORD', 'sub': 'coordenador', 'col': 3},
                {'id': 'f-func', 'label': 'PROGRAM_DB2 ou PROGRAM_CORP', 'sub': 'funcional: SQL ou programa corporativo', 'col': 4}]
        ar = [('f-app', 'f-req', '1 pedido'), ('f-req', 'f-areq', '2 encaminha'), ('f-areq', 'f-coord', '3 lê'), ('f-coord', 'f-func', '4 LINK'),
              ('f-coord', 'f-arsp', '5 responde'), ('f-arsp', 'f-rsp', '6 encaminha'), ('f-rsp', 'f-app', '7 lê a resposta')]
    else:
        nos += [{'id': 'f-coord', 'label': 'PROGRAM_DB2', 'sub': 'executa o comando SQL', 'col': 3}]
        ar = [('f-app', 'f-req', '1 pedido'), ('f-req', 'f-areq', '2 encaminha'), ('f-areq', 'f-coord', '3 lê e executa'), ('f-coord', 'f-arsp', '4 responde'),
              ('f-arsp', 'f-rsp', '5 encaminha'), ('f-rsp', 'f-app', '6 lê a resposta')]
    g = rm.G('Fluxo de integração com o mainframe', nos, [{'from': a_, 'to': b_, 'label': l_} for a_, b_, l_ in ar], kind='colunas',
             note='Os números das ligações são os passos da tabela do fluxo.')
    g['columns'] = [{'name': c, 'color': k} for c, k in cols]
    g['nw'] = 210
    return [rm.T('Transformação dos contextos em recursos', ['Origem', 'Recursos gerados', 'Como'], transf),
            rm.T('Convenção de nomes dos recursos', ['Recurso', 'Padrão do nome', 'Regra'], nomes),
            rm.T('Fluxo de integração com o mainframe', ['Passo', 'De', 'Para', 'O que acontece'], fluxo,
                 note='O MQ_ADAPTER fica dentro de cada aplicação e fala só com as filas de baixa.'), g]


def secoes_cenario(ana, m, f18, ev, ux, interp, cen):
    nome = CENARIOS[cen]
    pre = PREF_TITULO[cen]
    k = cen.lower()
    secs = []
    # recursos
    nome_r = {r['id']: r['id'] for r in m['recursos']}
    t_r = {r['id']: r['tipo'] for r in m['recursos']}
    rec_rows = [(r['id'], r['tipo'], r['nome'], r['origem'], r['confianca'], r['evidencia']) for r in m['recursos'] if r['tipo'] in ('HOST', 'MFE', 'BFMF', 'VAS', 'DOMAIN_MICROSERVICE')]
    R_ = {r['id']: r for r in m['recursos']}
    o2p = {o for x in m['corp'].values() for o in x['cmds']}
    cmd_rows = [(cod, m['dono'][cod], req, m['alta'][req][0], R_[req]['copybook'], prg, m['alta'][req][1], rsp, R_[rsp]['copybook'], ', '.join(R_[req]['operacoes']) or '—', ', '.join(R_[req]['tabelas']) or '—')
                for cod, (req, rsp, prg) in sorted(m['cmd_res'].items()) if cod not in o2p]
    cmd_rows += [(k_, x_['dono'], x_['res'][0], m['alta'][x_['res'][0]][0], R_[x_['res'][0]]['copybook'], x_['res'][2], m['alta'][x_['res'][0]][1], x_['res'][1], R_[x_['res'][1]]['copybook'], 'programa corporativo (chamada)', ', '.join(R_[x_['res'][0]]['tabelas']) or '—') for k_, x_ in sorted(m['corp'].items())]
    # os comandos originais que passaram a rodar dentro de um programa corporativo continuam na tabela, riscados
    prog_de = {o: k_ for k_, x_ in m['corp'].items() for o in x_['cmds']}
    por_int = {o: (p_, q_) for p_, (cs_, q_) in INTERNOS.items() for o in cs_ if m['corp']}
    def _dono_r(cod):
        return m['corp'][prog_de[cod]]['dono'] if cod in prog_de else m['corp'][por_int[cod][1][0]]['dono'] if por_int[cod][1][0] in m['corp'] else '—'
    riscados = [(cod, _dono_r(cod), '—', '—', '—', ('não será implementado: executado dentro do programa corporativo ' + prog_de[cod]) if cod in prog_de else f'não será implementado: executado dentro do programa corporativo {por_int[cod][0]}, chamado por {", ".join(por_int[cod][1])}', '—', '—', '—',
                 ', '.join(INFO.get(cod, {}).get('operacoes', [])) or '—', ', '.join(INFO.get(cod, {}).get('tabelas', [])) or '—') for cod in sorted(set(prog_de) | set(por_int), key=lambda c: [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', c)])]
    cmd_rows = riscados + cmd_rows
    cmd_risc = [True] * len(riscados) + [False] * (len(cmd_rows) - len(riscados))
    COORD_COL = 'Coordenador (PROGRAM_COORD)'
    def com_coord(rows, i):   # com coordenador: a coluna do programa mostra o funcional, e o coordenador vem numa coluna antes dela
        if not m['func']:
            return rows
        return [r[:i] + ((r[i] if r[i] in m['func'] else '—'), m['func'].get(r[i], r[i])) + r[i + 1:] for r in rows]
    cmd_rows = com_coord(cmd_rows, 5)
    # queries segregadas (desdobradas por agregado): cada nova query com a referência à query original da fase 10
    seg_rows = com_coord([(cod, cod.split('.')[0], m['dono'][cod], ', '.join(R_[req]['operacoes']) or '—', ', '.join(R_[req]['tabelas']) or '—', req, m['alta'][req][0], prg)
                for cod, (req, rsp, prg) in sorted(m['cmd_res'].items(), key=lambda kv: _nat(kv[0])) if '.' in cod and cod not in o2p], 7)
    seg_tab = [rm.T(f'Queries segregadas: nova query e query original', ['Nova query (segregada)', 'Query original (fase 10)', 'Executada por', 'Operação', 'Classes de domínio acessadas', 'MQ_REQ', 'MQ_REQ alta', *([COORD_COL] if m['func'] else []), PROGRAMA_COL],
                    seg_rows, note='A query original acessa mais de um agregado e foi desdobrada em uma query por agregado; cada linha liga a nova query à original, com link para a referência completa na fase 10 (sql-mapping).')] if seg_rows else []
    secs.append(rm.S(f'recursos', f'Modelo de recursos e protocolos de integração', [
        rm.T(f'Modelo de recursos aprovados', ['Id', 'Tipo', 'Nome', 'Contexto de origem (fase 18)', 'Confiança', 'Evidência'], rec_rows),
        rm.T(f'Comandos SQL: fila de pedido, programa DB2 e fila de resposta' if not m['corp'] else f'Comandos SQL: fila de pedido, programa e fila de resposta', ['Comando' if not m['corp'] else 'Comando (ou programa corporativo chamado)', 'Executado por', 'MQ_REQ', 'MQ_REQ alta', 'Copybook de requisição', *([COORD_COL] if m['func'] else []), 'PROGRAM_DB2' if not m['corp'] else 'PROGRAM_DB2 ou PROGRAM_CORP', 'MQ_RSP alta', 'MQ_RSP', 'Copybook de resposta', 'Operação', 'Classes de domínio acessadas'], cmd_rows, riscadas=cmd_risc)]
        + seg_tab
        + ([rm.T(f'Programas corporativos chamados pelos programas mainframe novos', ['Programa corporativo', 'Executado por', 'MQ_REQ', 'MQ_REQ alta', 'Copybook de requisição', *([COORD_COL] if m['func'] else []), 'PROGRAM_CORP', 'MQ_RSP alta', 'MQ_RSP', 'Copybook de resposta'],
             com_coord([(k_, x_['dono'], x_['res'][0], m['alta'][x_['res'][0]][0], next(r for r in m['recursos'] if r['id'] == x_['res'][0])['copybook'], x_['res'][2], m['alta'][x_['res'][0]][1], x_['res'][1], next(r for r in m['recursos'] if r['id'] == x_['res'][1])['copybook']) for k_, x_ in sorted(m['corp'].items())], 5))] if m['corp'] else [])
        + [
        rm.T(f'Integrações e protocolos', ['De', 'Tipo de origem', 'Para', 'Tipo de destino', 'Protocolo', 'Base'], [(i['de'], t_r[i['de']], i['para'], t_r[i['para']], i['protocolo'], i['base']) for i in m['integracoes']]),
        *tabelas_modelo(m)]))
    # C4
    g1 = c4_l1(m, f18, cen)
    g2 = c4_l2(m, f18, ev, cen)
    seqs = sequencias(m, f18, ev, cen)   # antes dos componentes: as regras de cada caso de uso vêm das notas destes diagramas
    gs3 = l3_bffs(m, f18, ev, cen) + l3_domains(m, f18, ev, cen)
    secs.append(rm.S(f'c4', f'Diagramas C4 (níveis 1, 2 e 3)', [rm.T(f'Tabela do diagrama: elementos e relacionamentos: {g1["title"]}', ['Elemento', 'Detalhe', 'Descrição', 'Liga-se a'], [(n['label'], n.get('sub', ''), n.get('detail', ''), '; '.join(f'{e["label"]} → ' + {x['id']: x['label'] for x in g1['nodes']}[e['to']] for e in g1['edges'] if e['from'] == n['id'])) for n in g1['nodes']]), g1, g2] + gs3 + [rm.X('Todos os diagramas saem do modelo de recursos (architecture-resource-model.yaml): o gerador recusa um diagrama com recurso que o modelo não tem.')]))
    secs.append(rm.S(f'sequencia', f'Diagramas de sequência (um por funcionalidade entry point; o fluxo das corporativas está nos das entry points que as chamam)', seqs))
    secs.append(rastreio(m, ev, cen, k, pre))
    secs.append(rm.S(f'sequencia_mainframe', f'Diagramas de sequência dos programas mainframe (um por ' + ('comando SQL ou programa corporativo chamado' if m['corp'] else 'comando SQL') + ')', sequencias_mainframe(m, cen)))
    secs.append(secoes_ux(m, f18, ux, cen))
    return secs


# Padrões arquiteturais que a arquitetura alvo adota, pelos tipos de recurso que ela tem: (padrão, tipos de recurso, o que é). Genérico: um padrão
# aparece quando o modelo de recursos tem recursos daqueles tipos.
PADROES_ARQ = [
    ('Micro Frontends', ('HOST', 'MFE'), 'A interface é dividida em micro frontends independentes, um por área de negócio (contexto de entrega de '
                                         'apresentação), carregados por um shell (host) em tempo de execução.'),
    ('Backend For Micro Frontend', ('BFMF',), 'Cada micro frontend tem um backend próprio que compõe as chamadas aos serviços no formato que a tela precisa, '
                                               'sem regra de negócio de domínio.'),
    ('Microservices', ('DOMAIN_MICROSERVICE',), 'Cada contexto de domínio é um serviço implantado de forma independente, dono dos seus casos de uso e exposto '
                                                 'por API REST.'),
    ('Legacy Database Indirect Access', ('MQ_REQ', 'MQ_REQ_ALTA', 'MQ_RSP_ALTA', 'MQ_RSP', 'PROGRAM_COORD', 'PROGRAM_DB2', 'PROGRAM_CORP'),
     'As aplicações não acessam o banco de dados do mainframe (DB2): cada comando SQL é pedido por uma fila IBM MQ e executado no mainframe por um programa, que devolve o '
     'resultado pela fila de resposta (e o programa corporativo é chamado do mesmo jeito, sem ser modernizado).'),
    ('Legacy Join Queries', ('VAS',), 'A consulta que junta dados de mais de um contexto continua sendo uma junção no banco de dados do mainframe (DB2), num serviço de consulta '
                                      '(Value-Added Service), em vez de ser montada por chamadas entre serviços.')]


def padroes_arquiteturais(m):
    """Primeira seção do relatório: os padrões arquiteturais adotados, com uma linha por tipo de recurso (descrição do tipo, recursos desta arquitetura e
    quantidade), agrupada pelo padrão que o tipo aplica. Substitui a tabela de tipos de recurso."""
    por_tipo = defaultdict(list)
    for r in m['recursos']:
        por_tipo[r['tipo']].append(r['id'])
    linhas, adotados = [], []
    for nome, tipos, oque in PADROES_ARQ:
        presentes = [t for t in tipos if por_tipo.get(t)]
        if not presentes:
            continue
        adotados.append(nome)
        for i, t in enumerate(presentes):
            ids = por_tipo[t]
            recursos = ', '.join(ids) if t in ('HOST', 'MFE', 'BFMF', 'DOMAIN_MICROSERVICE', 'VAS') else ', '.join(ids[:3]) + (f' e mais {len(ids) - 3}' if len(ids) > 3 else '')
            linhas.append((nome if i == 0 else '', oque if i == 0 else '', t, TIPOS[t], recursos, len(ids)))
    sem = [t for t in TIPOS if por_tipo.get(t) and not any(t in tp for _n, tp, _o in PADROES_ARQ)]
    linhas += [('—', 'tipo de recurso sem padrão arquitetural associado', t, TIPOS[t], ', '.join(por_tipo[t]), len(por_tipo[t])) for t in sem]
    frase = ('A arquitetura alvo adota os padrões arquiteturais ' + (', '.join(adotados[:-1]) + ' e ' + adotados[-1] if len(adotados) > 1 else adotados[0]) +
             '. Cada padrão vem dos tipos de recurso do modelo de recursos; as seções seguintes detalham os recursos, as integrações, os diagramas e o rastreio.')
    return rm.S('padroes-arquiteturais', 'Padrões arquiteturais adotados', [
        rm.X(frase),
        rm.T('Padrões arquiteturais e tipos de recurso', ['Padrão', 'O que é o padrão', 'Tipo de recurso', 'Descrição do tipo', 'Recursos desta arquitetura', 'Quantidade'],
             linhas, note='Uma linha por tipo de recurso do modelo, agrupada pelo padrão arquitetural que ele aplica.')])


def modelo(ana, modelos, f18s, evs, ux, interp):
    m, f18 = modelos['C'], f18s['C']
    secs = secoes_cenario(ana, m, f18, evs['C'], ux, interp, 'C')
    secs.insert(0, padroes_arquiteturais(m))
    pend_rows = [(a, b, c, ', '.join(t) or '—', o) for a, b, c, t, o in pendencias(m, f18, interp, 'C')]
    blocos = [rm.T('Lacunas e decisões pendentes', ['Assunto', 'Detalhe', 'Confiança', 'Tipos de recurso', 'Origem'], pend_rows)]
    if interp and interp['decisoes']:
        blocos.append(rm.T('Decisões arquiteturais registradas pela IA', ['Assunto', 'Decisão', 'Justificativa', 'Confiança'], [(x['assunto'], x.get('decisao', ''), x['justificativa'], x['confianca']) for x in interp['decisoes']]))
    if interp and interp['premissas']:
        blocos.append(rm.T('Premissas assumidas pela IA', ['Premissa', 'Detalhe'], [(x['assunto'], x['detalhe']) for x in interp['premissas']]))
    secs.append(rm.S('lacunas-e-decisoes-pendentes', 'Lacunas e decisões pendentes', blocos))
    secs.append(rm.S('criterio', 'Como a arquitetura foi montada', [rm.X(
        'Calculada só dos relatórios das fases 03 (papel das tabelas), 10 (comandos SQL), 12 (funcionalidades), 15 (telas e UX), 16 (domínio), 17 (responsibility-segregation) e 18 (contextos e relacionamentos). '
        'Nenhum recurso existe sem evidência: recurso sem decisão registrada tem confiança UNCERTAIN ou UNKNOWN e aparece em "Lacunas e decisões pendentes". '
        'Os nomes de programas mainframe e copybooks já atribuídos (e usados no código gerado) são mantidos; só comando novo recebe nome pela regra. '
        'Fora do escopo: identidade, observabilidade e segurança de plataforma. O modelo de recursos canônico está em architecture-resource-model.yaml, na pasta ia da fase.')]))
    linhas_rastreio = [r for s in secs if s['id'] == 'rastreio' for bl in s['blocks'] if bl['type'] == 'table' for r in bl['rows']]
    casos_uso = {(r[2], r[3]) for r in linhas_rastreio if r[2] != '—'}   # aplicação × caso de uso do rastreio (regra sem caso de uso fica de fora)
    cards = [rm.card('recursos', len(m['recursos'])), rm.card('integrações', len(m['integracoes'])), rm.card('comandos SQL', len(m['cmd_res'])),
             rm.card('casos de uso', len(casos_uso))]
    return rm.model('Arquitetura Alvo', 'Recursos, protocolos, diagramas C4, domínio, sequência e UX do sistema modernizado, na estratégia de acesso aos dados da fase 17 (responsibility-segregation)', cards, secs)


def preparar(ana, base):
    """Tudo o que a fase 19 calcula antes de escrever o relatório (modelo de recursos, símbolos, nomes, interpretação); as fases 20 (contratos) e 21 reaproveitam."""
    global BASE
    BASE = Path(base).resolve()
    evs = {'C': CD.coletar(ana)}
    f18s = ler_fase18(ana)
    info, papel_tab, ux = ler_fase10(ana), ler_fase3(ana), ler_ux(ana)
    INFO.clear(), INFO.update(info)
    pref = prefixo(evs['C'])
    interp = ler_interp(BASE)
    qs_ev = QS.coletar(ana)
    CORP.clear()
    cmds17 = set(qs_ev['cmds'])   # todos os comandos SQL da fase 17 (no domínio corporativo, os que o programa corporativo executa)
    for c_, *_ in f18s['C']['cmds']:   # no domínio corporativo o comando SQL dá lugar ao programa corporativo original
        if c_ not in qs_ev['cmds']:
            orig = sorted((k for k, v in qs_ev['cmds'].items() if v['programa'] == c_ and k in cmds17), key=_nat)
            CORP[c_] = orig
    INTERNOS.clear()   # programas corporativos chamados por outro programa corporativo (sem fila, programa nem copybook próprios): programa → (comandos originais, chamadores)
    fn_ = qs_ev['funcs']
    for g_ in fn_:
        p_ = fn_[g_]['programa']
        if p_ in CORP or p_ in INTERNOS:
            continue
        cs_ = sorted((k for k, v in qs_ev['cmds'].items() if v['programa'] == p_ and k in cmds17), key=_nat)
        quem = sorted({fn_[h]['programa'] for h in fn_ if g_ in qs_ev['corp'].get(h, {}).get('chama', []) and fn_[h]['programa'] != p_})
        if cs_ and quem:
            INTERNOS[p_] = (cs_, quem)
            info[c_] = {'operacoes': sorted({o for k in orig for o in info.get(k, {}).get('operacoes', [])}), 'tabelas': sorted({tb for k in orig for tb in info.get(k, {}).get('tabelas', [])}),
                        'cursor': any(info.get(k, {}).get('cursor') for k in orig), 'programas': [c_]}
    cods = sorted({c for f in f18s.values() for c, *_ in f['cmds']})
    legados = {c.split('-')[0] for c in cods} | {p for v in info.values() for p in v.get('programas', []) if p} | {c.split('-')[0] for c in info}
    simb = Simbolos(f18s, info, papel_tab, ux, ana, interp, legados, {o for v in CORP.values() for o in v} | {o for cs_, _q in INTERNOS.values() for o in cs_})
    classes = lambda c: [simb.tab.get(t, t) for t in info.get(c.split('.')[0], {}).get('tabelas', [])]
    props = {c: proposito_de(c, info, interp, classes(c)) for c in cods + sorted({o for v in CORP.values() for o in v} - set(cods))}   # também os comandos que os programas corporativos executam (filas do programa)
    fixos = nomes_atribuidos(BASE)
    progs = nomes_programas(cods, props, pref, legados, fixos['programas'])
    dm_ = json.loads((Path(ana) / 'dependency-map.json').read_text(encoding='utf-8')) if (Path(ana) / 'dependency-map.json').exists() else {}
    legados_cpy = {(c if isinstance(c, str) else (c.get('name') or c.get('copybook') or '')).upper() for v in dm_.values() if isinstance(v, dict) for c in v.get('copybooks', [])}
    CPY.clear()
    CPY.update(nomes_copybooks(cods, progs, legados_cpy, pref, fixos['copybooks']))
    props_ctx = defaultdict(list)
    for f in f18s.values():
        for cod, _cl, _ctx, nome_ctx, _t in f['cmds']:
            props_ctx[nome_ctx].append(props[cod])
    ctx_curto = {n: fixos.get('contextos_filas', {}).get(n) or nome_contexto(n, ps, pref) for n, ps in props_ctx.items()}   # abreviação já atribuída nas filas é mantida
    PROPOSITOS_FILAS.clear()
    PROPOSITOS_FILAS.update(fixos.get('propositos_filas', {}))
    simb.novos = set(progs.values()) | {n for par in CPY.values() for n in par} | set(CORP) | set(INTERNOS) | set(simb.cmd) | set(simb.cmd_low) | {c.lower() for c in simb.cmd}   # os programas corporativos originais continuam existindo: são citados pelo nome
    modelos = {'C': construir(f18s['C'], evs['C'], info, papel_tab, pref, simb, props, progs, ctx_curto)}
    erros = validar_modelo(modelos['C'], f18s['C'])
    if interp is None:
        print('AVISO: sem interpretacao-arquitetura/*.json (prompt 10): o relatório traz só a parte calculada')
    else:
        erros += validar_interp(interp, modelos)
    if erros:
        raise SystemExit('modelo ou interpretação inconsistente:\n  ' + '\n  '.join(erros))
    TAB_CLASSE.update({t: c for t, c in simb.classe.items() if c})
    REGRAS.update(ler_regras(ana, simb))
    FLUXO.clear(), CHAMA_FLUXO.clear(), CITADOS.clear(), FLUXO_IDS.clear(), CHAMA_NOS.clear(), DONO_REGRA.clear(), REG.clear()
    fl, ch, ci = ler_fluxo(ana)
    FLUXO.update(fl), CHAMA_FLUXO.update(ch), CITADOS.update(ci)
    PASSOS.clear()
    PASSOS.update(ler_passos(ana, evs['C']['funcs']))
    return {'evs': evs, 'f18s': f18s, 'info': info, 'papel_tab': papel_tab, 'ux': ux, 'pref': pref, 'interp': interp, 'simb': simb, 'props': props, 'progs': progs,
            'modelos': modelos, 'legados': legados}


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
    P = preparar(ana, BASE)
    evs, f18s, info, ux, interp, simb, modelos = (P[k] for k in ('evs', 'f18s', 'info', 'ux', 'interp', 'simb', 'modelos'))
    rep_ = modelo(ana, modelos, f18s, evs, ux, interp)
    rep_ = simb.walk(rep_)
    yml = simb.texto(modelo_yaml(modelos))
    sobras = sorted(set(simb.residuos(rep_) + simb.residuos(yml)))
    if sobras:
        raise SystemExit('o relatório ainda cita o sistema atual: ' + ', '.join(sobras[:20]))
    S.escrever(saida, FASE, rep_)
    (Path(saida) / FASE / 'ia' / 'architecture-resource-model.yaml').write_text(yml, encoding='utf-8')
    m = modelos['C']
    print(f'{len(m["recursos"])} recursos, {len(m["integracoes"])} integrações, {len(m["cmd_res"])} comandos SQL')


if __name__ == '__main__':
    main()
