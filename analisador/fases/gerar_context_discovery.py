#!/usr/bin/env python3
"""Relatório context-discovery (fase 18, evidência determinística + interpretação da IA): Domain Contexts e Delivery Contexts (DDMS, Delivery and Domain Model Segregation)
da estratégia de acesso aos dados da fase 17 (agregados, Query Legacy com Group Query e LEGACY nos agregados corporativos), lidos ÚNICA E EXCLUSIVAMENTE dos relatórios gerados (<fase>/ia/report.json das fases
12 business-flows, 15 user-interface-mapping, 16 domain-model e 17 responsibility-segregation). Mesma entrada → mesma saída, sem IA.

  python3 gerar_context_discovery.py <pasta-da-analise> [pasta-de-saida] [--interpretacao PASTA]   (padrão da saída: a pasta da análise)

Saída: <saida>/18 - context-discovery/human/report.html e <saida>/18 - context-discovery/ia/report.json (o mesmo modelo de visão, com as mesmas informações).
A interpretação da IA (prompt 9) fica em interpretacao-contextos/*.json; é validada contra a evidência.
Sem ela, o relatório traz só a parte calculada. As etapas do refinamento:
  1. Capability Modernization Options: cada capacidade de negócio (grupo coeso de funcionalidades) recebe uma opção de modernização (IA);
  2. DDMS Classification: cada capacidade é Domain, Delivery ou Mixed_Unresolved (IA);
  3. Domain Contexts: cada agregado da fase 16 (uma raiz) é um Domain Context (calculado), com as classes e os comandos que o constituem;
  4. Delivery Contexts: funcionalidades entry point → Presentation; funcionalidades corporativas e Group Queries → Query (agrupamento pela IA);
  5. Semantic Context Map: relacionamentos diretos entre os contextos (calculados) e o protocolo síncrono ou assíncrono de cada um (IA); no diagrama,
     cada contexto mostra por dentro os componentes que o constituem."""
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import gerar_simulacao as S
import report_model as rm  # noqa: E402
import report_resumo as rs  # noqa: E402

AQUI = Path(__file__).resolve().parent
BASE = Path(os.environ['ANALISE_INTERPRETACOES']) if os.environ.get('ANALISE_INTERPRETACOES') else AQUI   # pasta das interpretações (a análise); o pipeline a informa
FASE = '18 - context-discovery'
LEGACY = 'LEGACY'
OPCOES = {
    'Retain': 'manter como está: ainda entrega o valor esperado e não há ganho em mexer agora',
    'Rehost': 'mover para outra infraestrutura sem alterar o código (lift and shift)',
    'Replatform': 'mover para outra plataforma com ajustes pequenos, sem mudar a arquitetura',
    'Refactor': 'reorganizar o código existente, mantendo o comportamento e o desenho geral',
    'Rearchitect': 'mudar o desenho (contextos, agregados, separação de leitura e escrita) preservando as regras',
    'Rebuild': 'reescrever do zero a partir das regras de negócio extraídas',
    'Replace': 'trocar por produto ou serviço pronto (ou por serviço corporativo já existente)',
    'Retire': 'desligar: a capacidade não é mais necessária ou está duplicada',
}
DDMS = {'Domain': 'o contexto é lógica de negócio pura: regras e funcionalidades sobre agregados',
        'Delivery': 'o contexto é entrega: jornada do usuário, operações e estratégia de leitura próprias',
        'Mixed_Unresolved': 'a evidência mostra negócio e entrega misturados e ainda não dá para separar'}
TIPOS_DC = {'Presentation': 'jornada do usuário iniciada por funcionalidades entry point', 'Query': 'leitura: contexto que tem queries (Group Queries com Legacy Queries); funcionalidade sem query fica no Presentation'}
ESTRATEGIAS = {'consulta_original': 'a consulta legada continua sendo executada como está (Legacy Query)', 'projecao': 'a leitura vem de uma projeção (modelo de leitura) mantida a partir dos domínios',
               'api_composition': 'a resposta é composta chamando os domínios (agregados)'}
PROTOCOLOS = {'sincrono': 'chamada com espera da resposta', 'assincrono': 'mensagem ou evento sem espera da resposta'}
CONF = {'alta', 'média', 'baixa'}
CHAVES_RAIZ = {'capacidades', 'entregas', 'dominios', 'protocolos_padrao', 'protocolos', 'premissas', 'lacunas'}
RELACOES = ['Presentation→Presentation', 'Presentation→Query', 'Presentation→Domain', 'Query→Query', 'Query→Domain', 'Domain→Domain']
COR_PRES, COR_QRY, COR_CORE, COR_CORP = '#00695C', '#1565C0', '#6A1B9A', '#EF6C00'


def itens(t):
    return [x.strip() for x in str(t).split(',') if x.strip() and x.strip() != '—']


def curto(t, n=40):
    t = str(t)
    return t if len(t) <= n else t[:n - 1] + '…'


def coletar(ana):
    f12, f15, f16, f17 = S.fase(ana, '12 '), S.fase(ana, '15 '), S.fase(ana, '16 '), S.fase(ana, '17 ')
    funcs = {}
    for _s, bt, rows in S.tabelas(f12):
        if bt == 'Funcionalidades':
            for r in rows:
                m = re.match(r'(entry point|programa corporativo)\s+(\S+)', r['Base (referência)'])
                funcs[r['Id']] = {'id': r['Id'], 'nome': r['Funcionalidade'], 'entry': bool(m) and m.group(1) == 'entry point', 'programa': m.group(2) if m else '', 'tipo': r['Tipo']}
    if not funcs:
        raise SystemExit('fase 12: tabela de funcionalidades não encontrada')
    telas = {}
    for _s, bt, rows in S.tabelas(f15):
        if bt == 'Cobertura de programas por tela':
            for r in rows:
                telas.setdefault(r['Tela'], {}).update({'situacao': r['Situação no funil'], 'programas': set(itens(r['Programas que a tela usa']))})
        elif bt.startswith('Telas: finalidade'):
            for r in rows:
                telas.setdefault(r['Tela'], {}).update({'finalidade': r['Finalidade'], 'jornada': r['Jornada']})
    for t in telas.values():
        t.setdefault('situacao', '—')
        t.setdefault('programas', set())
    pai = {f: f for f, v in funcs.items() if v['entry']}

    def raiz(x):
        while pai[x] != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x
    for f, v in funcs.items():
        if v['entry']:
            v['telas'] = sorted(t for t, x in telas.items() if v['programa'] in x['programas'])
            v['telas_mantidas'] = [t for t in v['telas'] if telas[t]['situacao'].startswith('mantida')]
    for t, x in telas.items():
        if x['situacao'].startswith('mantida'):
            fs = [f for f, v in funcs.items() if v['entry'] and v['programa'] in x['programas']]
            for f in fs[1:]:
                pai[raiz(f)] = raiz(fs[0])
    grupos_tela = defaultdict(set)
    for f in pai:
        if funcs[f]['telas_mantidas']:
            grupos_tela[raiz(f)].add(f)
    blocos = sorted((sorted(g) for g in grupos_tela.values()), key=lambda g: g[0])
    ags, tab_ag, cls_ag, assoc, classes = {}, {}, {}, [], defaultdict(list)
    for _s, bt, rows in S.tabelas(f16):
        if bt == 'Agregados':
            for r in rows:
                ags[r['Agregado']] = {'categoria': r['Categoria'], 'raiz': r['Raiz'], 'fronteira': r['Por que esta fronteira']}
        elif bt.startswith('Classes de domínio'):
            for r in rows:
                tab_ag[r['Tabela']] = r['Agregado']
                cls_ag[r['Classe']] = r['Agregado']
                classes[r['Agregado']].append((r['Classe'], r['Tabela'], r['Papel no agregado']))
        elif bt.startswith('Associações entre as classes'):
            assoc = rows
    if not ags:
        raise SystemExit('fase 16: tabela de agregados não encontrada')
    comum = {'telas': telas, 'blocos': blocos, 'funcs': funcs, 'ags': ags, 'tab_ag': tab_ag, 'cls_ag': cls_ag, 'assoc': assoc, 'classes': dict(classes)}
    C = dict(comum, use_ag=defaultdict(dict), use_gq=defaultdict(set), gqs={}, chama=[], cmds=defaultdict(dict), padrao={})
    for _s, bt, rows in S.tabelas(f17):
        if bt == 'Relação por funcionalidade':
            for r in rows:
                f = r['Funcionalidade']
                C['padrao'][r['Query']] = r['Padrão SQL']
                if r['Group Query'] not in ('—', ''):
                    C['use_gq'][f].add(r['Group Query'])
                for a in itens(r['Agregado']):
                    C['use_ag'][f].setdefault(a, set()).add(r['Natureza'])
                    C['cmds'][a].setdefault(r['Query'], set()).add(f)
        elif bt == 'Group Queries':
            for r in rows:
                C['gqs'][r['Group Query']] = {'tabelas': itens(r['Tabelas']), 'queries': itens(r['Legacy Queries ligadas']), 'funcs': itens(r['Funcionalidades']), 'por_que': r['Por que']}
        elif bt == 'Funcionalidades que chamam funcionalidades corporativas':
            C['chama'] += [(r['Funcionalidade que chama'], r['Funcionalidade corporativa chamada']) for r in rows]
    if not (C['use_ag'] or C['gqs']):
        raise SystemExit('fase 17: tabelas da estratégia de acesso aos dados não encontradas (rode a fase 17 antes)')
    C['chama'] = sorted(set(C['chama']))
    return C


def ler_interp(base):
    d = Path(base) / 'interpretacao-contextos'
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


def da_ia(interp, chave):
    return list((interp or {}).get(chave, []))


def contextos(ev, interp):
    """Domain Contexts (um por agregado, com as classes e os comandos que o constituem) e Delivery Contexts (da IA; sem ela, entry points com o mesmo conjunto de agregados,
    um contexto por programa corporativo e um por Group Query)."""
    ia_dom = {x.get('agregado'): x for x in da_ia(interp, 'dominios')}
    dom = {}
    for nome, a in sorted(ev['ags'].items()):
        funcs = sorted(f for f in ev['funcs'] if nome in ev['use_ag'].get(f, {}))
        ops = sorted({n for f in funcs for n in ev['use_ag'][f][nome]})
        x = ia_dom.get(nome, {})
        corp_c = a['categoria'] == 'Corporativo'
        if corp_c:   # domínio corporativo: só o agregado e os nomes dos programas corporativos originais (atrás da camada LEGACY)
            comps = [{'label': nome, 'sub': 'agregado · raiz ' + a['raiz'], 'detail': f'Agregado {nome} (raiz {a["raiz"]}); classes: ' + ', '.join(c for c, _t, _p in ev['classes'].get(nome, [])), 'cor': COR_CORE}]
        else:
            comps = [{'label': c, 'sub': ('raiz' if 'raiz' in p else p), 'detail': f'{c} (tabela {t}), {p}', 'cor': COR_CORE if 'raiz' in p else None} for c, t, p in sorted(ev['classes'].get(nome, []), key=lambda z: ('raiz' not in z[2], z[0]))]
        for cod in sorted(ev['cmds'].get(nome, {})):
            if corp_c:
                comps.append({'label': cod, 'sub': LEGACY, 'detail': f'programa corporativo {cod}, chamado pelo agregado {nome} por meio de {LEGACY}; funcionalidades {", ".join(sorted(ev["cmds"][nome][cod]))}'})
            else:
                comps.append({'label': cod, 'sub': ev['padrao'].get(cod, ''), 'detail': f'{cod}: {ev["padrao"].get(cod, "")}; funcionalidades {", ".join(sorted(ev["cmds"][nome][cod]))}'})
        dom['DM-' + nome] = {'id': 'DM-' + nome, 'agregado': nome, 'nome': x.get('nome') or nome, 'categoria': a['categoria'], 'raiz': a['raiz'], 'valor': x.get('valor_de_negocio', ''),
                             'comps': comps, 'funcs': funcs, 'ops': ops}
    dcs = []
    if interp and da_ia(interp, 'entregas'):
        for x in da_ia(interp, 'entregas'):
            dcs.append({'id': x.get('id'), 'tipo': x.get('tipo'), 'nome': x.get('nome'), 'funcs': list(x.get('funcionalidades') or []), 'gqs': list(x.get('group_queries') or []),
                        'estrategia': x.get('estrategia_leitura', ''), 'jornada': x.get('jornada', ''), 'valor': x.get('valor_de_entrega', ''), 'fonte': 'IA'})
    else:
        noblocos = {f for b in ev['blocos'] for f in b}
        entries = [f for f, v in sorted(ev['funcs'].items()) if v['entry'] and f not in noblocos]
        sig = defaultdict(list)
        for f in entries:
            sig[tuple(sorted(ev['use_ag'].get(f, {})) + sorted(ev['use_gq'].get(f, ())))].append(f)
        grupos_p = [('Entrega das telas ' + ', '.join(sorted({t for f in b for t in ev['funcs'][f]['telas_mantidas']})), b) for b in ev['blocos']]
        grupos_p += [('Jornada de ' + (' + '.join(s_) if s_ else 'chamadas a funcionalidades corporativas'), fs) for s_, fs in sorted(sig.items(), key=lambda kv: kv[1][0])]
        n = 0
        for nome_, fs in grupos_p:
            n += 1
            dcs.append({'id': f'DC-P{n:02d}', 'tipo': 'Presentation', 'nome': nome_, 'funcs': fs, 'gqs': [], 'estrategia': '', 'jornada': '', 'valor': '', 'fonte': 'calculado'})
        pres = [d for d in dcs if d['tipo'] == 'Presentation']
        onde = {f: d for d in pres for f in d['funcs']}
        pend = sorted(f for f, v in ev['funcs'].items() if not v['entry'])
        for _ in range(len(pend) + 1):
            for f in list(pend):
                quem = [a_ for a_, b_ in ev['chama'] if b_ == f and a_ in onde]
                if quem:
                    d_ = onde[quem[0]]
                    d_['funcs'].append(f)
                    onde[f] = d_
                    pend.remove(f)
        for f in pend:
            if pres:
                pres[0]['funcs'].append(f)
        n = len(dcs)
        for g in sorted(ev['gqs']):
            n += 1
            dcs.append({'id': f'DC-Q{n:02d}', 'tipo': 'Query', 'nome': g, 'funcs': [], 'gqs': [g], 'estrategia': '', 'jornada': '', 'valor': '', 'fonte': 'calculado'})
    for d in dcs:
        comps = [{'label': f, 'sub': ev['funcs'][f]['nome'] if f in ev['funcs'] else '', 'detail': f'{f} · {ev["funcs"][f]["nome"] if f in ev["funcs"] else ""}'} for f in d['funcs']]
        for g in d['gqs']:
            gi = ev['gqs'].get(g, {})
            comps.append({'label': g, 'sub': 'Group Query', 'detail': f'{g}: tabelas {", ".join(gi.get("tabelas", []))}; {gi.get("por_que", "")}', 'cor': COR_QRY})
            for q in gi.get('queries', []):
                comps.append({'label': q, 'sub': 'Legacy Query · ' + ev['padrao'].get(q, ''), 'detail': f'{q} em {g}'})
        d['comps'] = comps
    return dom, dcs


def relacoes(ev, dom, dcs):
    """Relacionamentos DIRETOS entre contextos: Delivery → Domain (a funcionalidade usa o agregado), Delivery → Delivery (chama funcionalidade corporativa ou consulta Group Query),
    Group Query → Domain (lê as tabelas) e Domain → Domain (associação entre classes de agregados diferentes, fase 16). Nada é deduzido por transitividade."""
    de_f = {f: d['id'] for d in dcs for f in d['funcs']}
    de_g = {g: d['id'] for d in dcs for g in d['gqs']}
    rel = {}

    def add(a, b, tipo, ev_):
        if a == b:
            return
        r = rel.setdefault((a, b), {'de': a, 'para': b, 'tipos': set(), 'evid': set()})
        r['tipos'].add(tipo)
        r['evid'].add(ev_)
    for f in sorted(ev['funcs']):
        d = de_f.get(f)
        if not d:
            continue
        for ag, nat in sorted(ev['use_ag'].get(f, {}).items()):
            add(d, 'DM-' + ag, 'grava' if 'grava' in nat else 'lê', f)
        for g in sorted(ev['use_gq'].get(f, ())):
            if g in de_g:
                add(d, de_g[g], 'consulta Group Query', f)
    for a, b in ev['chama']:
        if a in de_f and b in de_f:
            add(de_f[a], de_f[b], 'chama funcionalidade corporativa', f'{a} → {b}')
    for d in dcs:
        for g in d['gqs']:
            for t in ev['gqs'].get(g, {}).get('tabelas', []):
                if t in ev['tab_ag']:
                    add(d['id'], 'DM-' + ev['tab_ag'][t], 'lê', f'{g} ({t})')
    for r in ev['assoc']:
        a, b = ev['cls_ag'].get(r['De (todo)']), ev['cls_ag'].get(r['Para (parte)'])
        if a and b and a != b:
            add('DM-' + a, 'DM-' + b, 'referência por identidade', f'{r["De (todo)"]} {r["Cardinalidade"]} {r["Para (parte)"]}')
    return [rel[k] for k in sorted(rel)]


def acopla_legado(ev, nome, agregado=None):
    """Motivo pelo qual o nome de um contexto ainda é do legado (programa, tabela, código de query, Group Query, tela, nome técnico do agregado); '' se está desacoplado."""
    n = str(nome or '')
    norm = lambda t: re.sub(r'[^a-z0-9]', '', t.lower())
    for x in sorted({v['programa'] for v in ev['funcs'].values() if v['programa']} | set(ev['tab_ag'])):
        if x.lower() in n.lower():
            return f'cita o nome do legado {x}'
    if re.search(r'\b[A-Z]{4}\d[A-Z0-9]{3}\b|-Q\d|GQ_|\bDC-|\bDM-|\.jsp|\b[A-Z]{2,}_[A-Z_]{2,}\b', n):
        return 'cita identificador técnico do legado (programa, query, Group Query ou tabela)'
    if re.search(r'(?i)legacy|\bcobol\b|\bdb2\b|\bcics\b|\bjsp\b', n):
        return 'cita tecnologia ou conceito do legado'
    if norm(n) in {norm(a) for a in ev['ags']} | {norm(g) for g in ev['gqs']} | {norm(c) for cs in ev['classes'].values() for c, _t, _p in cs}:
        return 'repete o nome técnico de um agregado, classe ou Group Query do legado'
    return ''


def comandos_nos_contextos(ev, dom, dcs):
    """[(comando, classificação, id do contexto, nome do contexto, tipo do contexto, papel)] de cada comando SQL da fase 17 e do contexto em que ele aparece como componente."""
    achados = []
    for i, d in dom.items():
        for c in d['comps']:
            if c['label'] in ev['padrao']:
                achados.append((c['label'], ev['padrao'][c['label']], i, d['nome'], 'Domain', 'programa corporativo chamado pelo agregado por meio de LEGACY' if ev['padrao'][c['label']] == LEGACY else 'executado dentro do agregado'))
    for d in dcs:
        for c in d['comps']:
            if c['label'] in ev['padrao']:
                achados.append((c['label'], ev['padrao'][c['label']], d['id'], d['nome'], 'Delivery · ' + d['tipo'], 'Legacy Query dentro de Group Query'))
    return sorted(achados)


def faltam_comandos(ev, dom, dcs):
    """Comandos SQL da fase 17 que não aparecem em nenhum contexto (deve ser vazio: todos os comandos precisam estar mapeados dentro dos contextos)."""
    return sorted(set(ev['padrao']) - {a[0] for a in comandos_nos_contextos(ev, dom, dcs)})


def tipo_rel(r, dom, dcs):
    """Tipo do relacionamento pelo tipo dos contextos: Presentation→Query, Presentation→Domain, Query→Query, Query→Domain ou Domain→Domain."""
    t = {d['id']: d['tipo'] for d in dcs}
    t.update({i: 'Domain' for i in dom})
    return f'{t[r["de"]]}→{t[r["para"]]}'


def protocolo_de(r, dom, dcs, interp):
    """(protocolo, justificativa, origem): a exceção por par vale mais que o protocolo padrão do tipo de relacionamento."""
    exc = {(x.get('de'), x.get('para')): x for x in da_ia(interp, 'protocolos')}
    pad = {x.get('relacao'): x for x in da_ia(interp, 'protocolos_padrao')}
    x = exc.get((r['de'], r['para']))
    if x:
        return x.get('protocolo'), x.get('justificativa'), 'exceção do par'
    x = pad.get(tipo_rel(r, dom, dcs))
    return (x.get('protocolo'), x.get('justificativa'), 'padrão do tipo ' + tipo_rel(r, dom, dcs)) if x else (None, None, None)


def validar(ev, dom, dcs, rels, interp):
    erros = []
    p = ''
    todas = set(ev['funcs'])
    vistos = defaultdict(int)
    ids_cap = set()
    for x in da_ia(interp, 'capacidades'):
        cid = x.get('id')
        if not cid or cid in ids_cap:
            erros.append(f'{p}capacidade sem id ou repetida: {cid}')
        ids_cap.add(cid)
        if x.get('opcao') not in OPCOES:
            erros.append(f'{p}{cid}: opcao deve ser uma de {sorted(OPCOES)}')
        if x.get('classe_ddms') not in DDMS:
            erros.append(f'{p}{cid}: classe_ddms deve ser uma de {sorted(DDMS)}')
        if x.get('confianca') not in CONF:
            erros.append(f'{p}{cid}: confianca deve ser alta, média ou baixa')
        for k in ('nome', 'descricao', 'justificativa_opcao', 'justificativa_ddms'):
            if not str(x.get(k) or '').strip():
                erros.append(f'{p}{cid}: falta {k}')
        if acopla_legado(ev, x.get('nome')):
            erros.append(f'{p}{cid}: o nome "{x.get("nome")}" {acopla_legado(ev, x.get("nome"))}; dê um nome próprio, do negócio')
        if not x.get('funcionalidades'):
            erros.append(f'{p}{cid}: sem funcionalidades')
        for f in x.get('funcionalidades') or []:
            if f not in todas:
                erros.append(f'{p}{cid}: funcionalidade inexistente {f}')
            vistos[f] += 1
    for f in sorted(todas):
        if vistos[f] != 1:
            erros.append(f'{p}{f}: deve estar em exatamente uma capacidade (está em {vistos[f]})')
    ids = set()
    por_f, por_g = defaultdict(list), defaultdict(list)
    for d in dcs:
        i = d['id']
        if not i or i in ids or str(i).startswith('DM-'):
            erros.append(f'{p}contexto de entrega sem id válido ou repetido: {i}')
        ids.add(i)
        if d['tipo'] not in TIPOS_DC:
            erros.append(f'{p}{i}: tipo deve ser Presentation ou Query')
            continue
        if not str(d['nome'] or '').strip():
            erros.append(f'{p}{i}: falta nome')
        for f in d['funcs']:
            if f not in todas:
                erros.append(f'{p}{i}: funcionalidade inexistente {f}')
                continue
            por_f[f].append(i)
            if d['tipo'] == 'Query' and ev['funcs'][f]['entry']:
                erros.append(f'{p}{i}: Query só recebe funcionalidades corporativas e Group Queries ({f} é entry point)')
        for g in d['gqs']:
            if g not in ev['gqs']:
                erros.append(f'{p}{i}: Group Query inexistente {g}')
            por_g[g].append(i)
        if acopla_legado(ev, d['nome']):
            erros.append(f'{p}{i}: o nome "{d["nome"]}" {acopla_legado(ev, d["nome"])}; dê um nome próprio, do negócio, que represente o contexto de forma coesa e fechada')
        if d['tipo'] == 'Presentation' and not any(ev['funcs'][f]['entry'] for f in d['funcs'] if f in ev['funcs']):
            erros.append(f'{p}{i}: Presentation precisa de ao menos uma funcionalidade entry point')
        if d['tipo'] == 'Query':
            if not str(d.get('valor') or '').strip():
                erros.append(f'{p}{i}: Query separada precisa de valor_de_entrega (que valor entrega por si só ao usuário)')
            if d['estrategia'] not in ESTRATEGIAS:
                erros.append(f'{p}{i}: estrategia_leitura deve ser uma de {sorted(ESTRATEGIAS)}')
            if not d['gqs']:
                erros.append(f'{p}{i}: Query precisa ter queries (Group Queries); contexto só com funcionalidades fica no Presentation que as usa')
    for f in sorted(todas):
        if len(por_f[f]) != 1:
            erros.append(f'{p}{f}: deve estar em exatamente um Delivery Context (está em {len(por_f[f])})')
    dc_f = {f: v[0] for f, v in por_f.items() if v}
    dc_g = {g: v[0] for g, v in por_g.items() if v}
    tipo_dc = {d['id']: d['tipo'] for d in dcs}
    for b in ev['blocos']:
        onde = {dc_f.get(f) for f in b}
        if len(onde) > 1:
            erros.append(f'{p}as funcionalidades {", ".join(b)} aparecem nas mesmas telas mantidas (fase 15) e precisam estar no mesmo Delivery Context (estão em {sorted(str(x) for x in onde)})')
    for g in sorted(ev['gqs']):
        if dc_g.get(g) and tipo_dc.get(dc_g[g]) == 'Presentation':
            erros.append(f'{p}{g}: Group Query (queries de várias tabelas) não fica dentro de um Presentation ({dc_g[g]}); ela fica em um Delivery Context do tipo Query')
    for g in sorted(ev['gqs']):
        if len(por_g[g]) != 1:
            erros.append(f'{p}{g}: Group Query deve estar em exatamente um Delivery Context (está em {len(por_g[g])})')
    dm_ia = [x.get('agregado') for x in da_ia(interp, 'dominios')]
    for a in sorted(ev['ags']):
        if dm_ia.count(a) != 1:
            erros.append(f'{p}{a}: deve ter exatamente uma entrada em dominios (tem {dm_ia.count(a)})')
    for a in sorted(set(dm_ia) - set(ev['ags'])):
        erros.append(f'{p}dominios: agregado inexistente {a}')
    for x in da_ia(interp, 'dominios'):
        if acopla_legado(ev, x.get('nome'), x.get('agregado')) or not str(x.get('nome') or '').strip():
            erros.append(f'{p}{x.get("agregado")}: o nome "{x.get("nome")}" {acopla_legado(ev, x.get("nome")) or "está vazio"}; dê um nome próprio, do negócio')
        if not str(x.get('valor_de_negocio') or '').strip():
            erros.append(f'{p}{x.get("agregado")}: falta valor_de_negocio')
    tipos = {tipo_rel(r, dom, dcs) for r in rels}
    padrao = {}
    for x in da_ia(interp, 'protocolos_padrao'):
        k = x.get('relacao')
        if k not in RELACOES:
            erros.append(f'{p}protocolos_padrao: relacao deve ser uma de {RELACOES} ({k})')
        if k in padrao:
            erros.append(f'{p}protocolos_padrao repetido: {k}')
        padrao[k] = x
        if x.get('protocolo') not in PROTOCOLOS:
            erros.append(f'{p}{k}: protocolo deve ser sincrono ou assincrono')
        if not str(x.get('justificativa') or '').strip():
            erros.append(f'{p}{k}: falta justificativa')
    for k in sorted(tipos - set(padrao)):
        erros.append(f'{p}falta o protocolo padrão do tipo de relacionamento {k}')
    chaves = {(r['de'], r['para']) for r in rels}
    vistas = set()
    for x in da_ia(interp, 'protocolos'):
        k = (x.get('de'), x.get('para'))
        if k in vistas:
            erros.append(f'{p}exceção de protocolo repetida: {k[0]} → {k[1]}')
        vistas.add(k)
        if k not in chaves:
            erros.append(f'{p}exceção de protocolo para relacionamento que não existe diretamente: {k[0]} → {k[1]}')
        if x.get('protocolo') not in PROTOCOLOS:
            erros.append(f'{p}{k[0]} → {k[1]}: protocolo deve ser sincrono ou assincrono')
        if not str(x.get('justificativa') or '').strip():
            erros.append(f'{p}{k[0]} → {k[1]}: falta justificativa')
    return erros


def secoes(ev, dom, dcs, rels, interp):
    nm = {d['id']: d['nome'] for d in dcs}
    nm.update({i: d['nome'] for i, d in dom.items()})
    tp = {d['id']: 'Delivery · ' + d['tipo'] for d in dcs}
    tp.update({i: 'Domain' for i in dom})
    prot = {(r['de'], r['para']): protocolo_de(r, dom, dcs, interp) for r in rels}
    cap = da_ia(interp, 'capacidades')
    secs = []
    if cap:
        secs.append(rm.S('capacidades', 'Etapa 1, Capability Modernization Options: opção de modernização de cada capacidade de negócio', [
            rm.T('Capacidades de negócio e opção de modernização', ['Capacidade', 'Nome', 'O que entrega', 'Funcionalidades', 'Opção de modernização (IA)', 'Por que (IA)', 'Confiança (IA)'],
                 [(x['id'], x['nome'], x['descricao'], ', '.join(x['funcionalidades']), x['opcao'], x['justificativa_opcao'], x['confianca']) for x in cap]),
            rm.T('Opções de modernização', ['Opção', 'Significado', 'Capacidades'], [(o, s, ', '.join(x['id'] for x in cap if x['opcao'] == o) or '—') for o, s in OPCOES.items()]),
            rm.X('Capacidade de negócio é um grupo coeso de funcionalidades que entrega valor a um stakeholder, sem depender da forma técnica (programa, tabela ou arquivo). Cada funcionalidade da fase 12 está em uma só capacidade.')]))
        secs.append(rm.S('ddms', 'Etapa 2, DDMS Classification: Domain, Delivery ou Mixed_Unresolved', [
            rm.T('Classificação DDMS das capacidades', ['Capacidade', 'Nome', 'Classe DDMS (IA)', 'Por que (IA)'], [(x['id'], x['nome'], x['classe_ddms'], x['justificativa_ddms']) for x in cap]),
            rm.T('Classes DDMS', ['Classe', 'Significado', 'Capacidades'], [(o, s, ', '.join(x['id'] for x in cap if x['classe_ddms'] == o) or '—') for o, s in DDMS.items()]),
            rm.T('Classificação DDMS dos contextos descobertos nas etapas 3 e 4', ['Contexto', 'Nome', 'Tipo', 'Classe DDMS', 'Base'],
                 [(i, d['nome'], 'Domain Context', 'Domain', 'baseado em agregado (fase 16)') for i, d in dom.items()]
                 + [(d['id'], d['nome'], 'Delivery Context · ' + d['tipo'], 'Delivery', 'baseado em funcionalidades' + (' e Group Queries' if d['gqs'] else '') + ' (fases 12 e 17)') for d in dcs])]))
    secs.append(rm.S('dominios', 'Etapa 3, Domain Contexts: um por agregado (limite de entrega de valor de negócio)', [
        rm.T('Domain Contexts', ['Contexto', 'Nome', 'Agregado raiz', 'Categoria', 'Componentes (classes e comandos)', 'Funcionalidades que o usam', 'Operações', 'Valor de negócio (IA)'],
             [(i, d['nome'], d['raiz'], d['categoria'], ', '.join(c['label'] for c in d['comps']) or '—', ', '.join(d['funcs']) or '—', ', '.join(d['ops']) or '—', d['valor'] or '—') for i, d in dom.items()]),
        rm.X('Cada agregado da fase 16 (uma raiz) é um Domain Context. Os componentes são as classes do agregado e os comandos SQL que ele executa (no domínio corporativo, os programas corporativos que ele chama por meio de LEGACY). As funcionalidades que o usam são as que o chamam diretamente (as chamadas a funcionalidades corporativas não entram).')]))
    ent_rows = []
    for d in dcs:
        agr = sorted({r['para'][3:] for r in rels if r['de'] == d['id'] and r['para'] in dom})
        telas = sorted({t for f in d['funcs'] if f in ev['funcs'] and ev['funcs'][f]['entry'] for t in ev['funcs'][f]['telas_mantidas']})
        cons = sorted({r['de'] for r in rels if r['para'] == d['id']})
        ent_rows.append((d['id'], d['nome'], d['tipo'], ', '.join(c['label'] for c in d['comps']) or '—', ', '.join(telas) or '—', ', '.join(cons) or '—',
                         ESTRATEGIAS.get(d['estrategia'], d['estrategia']) or '—' if d['tipo'] == 'Query' else '—', ', '.join(agr) or '—', d['jornada'] or '—', d['valor'] or '—', d['fonte']))
    secs.append(rm.S('entregas', 'Etapa 4, Delivery Contexts: valor entregue ao usuário (telas e funcionalidades usadas juntas formam uma só entrega)', [
        rm.T('Delivery Contexts', ['Contexto', 'Nome', 'Tipo', 'Componentes', 'Telas mantidas (fase 15)', 'Consumido por', 'Estratégia de leitura', 'Domain Contexts que usa', 'Jornada ou finalidade (IA)', 'Valor entregue ao usuário (IA)', 'Origem'], ent_rows),
        rm.T('Tipos de Delivery Context e estratégias de leitura', ['Item', 'Significado'], [('Presentation', TIPOS_DC['Presentation']), ('Query', TIPOS_DC['Query'])] + list(ESTRATEGIAS.items())),
        rm.X('Funcionalidades usadas na mesma tela, ou em telas que dependem uma da outra, formam uma só entrega: entregues separadas, não dariam valor ao usuário. Funcionalidades (entry points e corporativas) ficam no Presentation que as usa. Um Delivery Context do tipo Query só existe quando tem queries: as queries de várias tabelas (Group Queries) ficam sempre nele, nunca no Presentation, e ele precisa entregar valor por si só. Os nomes dos contextos são próprios do negócio, sem os nomes do legado (programas, tabelas e queries).'
             + ('' if cap else ' Sem a interpretação da IA (prompt 9), o agrupamento é o calculado: entry points que aparecem nas mesmas telas mantidas formam um Presentation, e as funcionalidades corporativas ficam no Presentation de quem as chama' + ('; cada Group Query vira um contexto Query.' if ev['gqs'] else '.')))]))
    nivel = {i: 0 for i in dom}
    dd = [(r['de'], r['para']) for r in rels if r['de'] in dom and r['para'] in dom]
    for _ in range(len(dom) + 1):
        for a, b in dd:
            if nivel[b] < nivel[a] + 1 and nivel[a] < len(dom):
                nivel[b] = nivel[a] + 1
    nmax = max(nivel.values()) if nivel else 0
    cols = ['Delivery Context · Presentation', 'Delivery Context · Query'] + ['Domain Context' + ('' if nmax == 0 else f' (nível {j + 1} de dependência)') for j in range(nmax + 1)]
    cores = [COR_PRES, COR_QRY] + [COR_CORE] * (nmax + 1)
    nos = []
    for d in dcs:
        nos.append({'id': d['id'], 'col': 0 if d['tipo'] == 'Presentation' else 1, 'label': f'{d["id"]} · {d["nome"]}', 'sub': 'Delivery · ' + d['tipo'], 'cor': COR_PRES if d['tipo'] == 'Presentation' else COR_QRY, 'componentes': d['comps'],
                    'detail': f'{d["id"]} · {d["nome"]} ({d["tipo"]})'})
    for i, d in sorted(dom.items(), key=lambda kv: (kv[1]['categoria'] != 'Business core', kv[0])):
        nos.append({'id': i, 'col': 2 + nivel[i], 'label': d['nome'], 'sub': 'Domain · ' + d['categoria'], 'cor': COR_CORE if d['categoria'] == 'Business core' else COR_CORP, 'componentes': d['comps'], 'detail': f'{i} · raiz {d["raiz"]}'})
    arestas = [{'from': r['de'], 'to': r['para'], 'label': 'async' if prot[(r['de'], r['para'])][0] == 'assincrono' else ''} for r in rels]
    try:
        nos = rs._ordenar(nos, arestas, {})
    except Exception:  # noqa: BLE001
        pass
    g = rm.G('Semantic Context Map (cada contexto mostra os componentes que o constituem)', nos, arestas, kind='contextos',
             note='Só relacionamentos diretos: Presentation → Query (chama funcionalidade corporativa ou consulta Group Query), Presentation e Query → Domain (usam o agregado) e Domain → Domain (associação entre agregados). '
                  'Dentro de cada caixa estão os componentes: funcionalidades' + (', Group Queries e Legacy Queries' if ev['gqs'] else '') + ' nos Delivery Contexts; classes do agregado e comandos SQL nos Domain Contexts (os Domain Contexts corporativos trazem só o agregado e os nomes dos programas corporativos, chamados por meio de LEGACY).' + ' Seta sem rótulo é protocolo síncrono; a seta rotulada async é assíncrona (protocolo julgado pela IA, na tabela de relacionamentos).')
    g['columns'] = [{'name': c, 'color': cor} for c, cor in zip(cols, cores)]
    g['nw'] = 260
    g['legenda'] = [{'texto': 'Delivery Context · Presentation', 'cor': COR_PRES}, {'texto': 'Delivery Context · Query', 'cor': COR_QRY}, {'texto': 'Domain Context · Business core', 'cor': COR_CORE}, {'texto': 'Domain Context · Corporativo', 'cor': COR_CORP}]
    rrows = []
    for r in rels:
        p = prot[(r['de'], r['para'])]
        rrows.append((r['de'], nm[r['de']], tp[r['de']], r['para'], nm[r['para']], tp[r['para']], ', '.join(sorted(r['tipos'])), '; '.join(sorted(r['evid'])), p[0] or '—', p[1] or '—', p[2] or '—'))
    secs.append(rm.S('mapa', 'Etapa 5, Semantic Context Map: contextos, componentes, relacionamentos e protocolo de integração', [
        g, rm.T('Comandos SQL mapeados dentro dos contextos', ['Comando', 'Classificação', 'Contexto', 'Nome do contexto', 'Tipo do contexto', 'Como está no contexto'], comandos_nos_contextos(ev, dom, dcs)),
        rm.T('Relacionamentos do mapa de contextos', ['De', 'Nome de origem', 'Tipo de origem', 'Para', 'Nome de destino', 'Tipo de destino', 'Relação', 'Evidência', 'Protocolo (IA)', 'Por que (IA)', 'Origem do protocolo'], rrows),
        rm.T('Protocolos', ['Protocolo', 'Significado'], list(PROTOCOLOS.items()))]))
    return secs


def modelo(ev, contexto, interp):
    dom, dcs, rels = contexto
    secs = []
    secs.append(rm.S('telas', 'Evidência das telas (fase 15): o que é usado junto vira uma só entrega', [
        rm.T('Telas e situação no funil', ['Tela', 'Situação no funil', 'Funcionalidades entry point que a tela usa', 'Finalidade (fase 15)', 'Jornada (fase 15)'],
             [(t, x['situacao'], ', '.join(f for f, v in sorted(ev['funcs'].items()) if v['entry'] and t in v['telas']) or '—', curto(x.get('finalidade', '—'), 260), curto(x.get('jornada', '—'), 260)) for t, x in sorted(ev['telas'].items())]),
        rm.T('Telas de cada funcionalidade entry point', ['Funcionalidade', 'Nome', 'Telas mantidas', 'Outras telas (omitidas do funil)', 'Entrega mínima (mesmas telas mantidas)'],
             [(f, v['nome'], ', '.join(v['telas_mantidas']) or '—', ', '.join(t for t in v['telas'] if t not in v['telas_mantidas']) or '—',
               next((', '.join(b) for b in ev['blocos'] if f in b), '—')) for f, v in sorted(ev['funcs'].items()) if v['entry']]),
        rm.X('Telas mantidas no funil da fase 15 são as analisadas em detalhe. Entry points que aparecem na mesma tela mantida (e, por transitividade, em telas que compartilham funcionalidades) formam a entrega mínima: o gerador exige que fiquem no mesmo Delivery Context. A IA pode juntar mais entregas quando a jornada das telas mostra que uma depende da outra.')]))
    secs += secoes(ev, dom, dcs, rels, interp)
    linhas = [('Domain Contexts', len(dom)), ('Delivery Contexts · Presentation', sum(1 for x in dcs if x['tipo'] == 'Presentation')),
              ('Delivery Contexts · Query', sum(1 for x in dcs if x['tipo'] == 'Query')), ('Group Queries dentro de Delivery Contexts', sum(len(x['gqs']) for x in dcs)),
              ('relacionamentos Delivery → Domain', sum(1 for x in rels if x['para'] in dom and x['de'] not in dom)), ('relacionamentos Delivery → Delivery', sum(1 for x in rels if x['para'] not in dom)),
              ('relacionamentos Domain → Domain', sum(1 for x in rels if x['de'] in dom)), ('componentes nos Domain Contexts', sum(len(x['comps']) for x in dom.values()))]
    if interp:
        for nome_, pr in (('relacionamentos síncronos (IA)', 'sincrono'), ('relacionamentos assíncronos (IA)', 'assincrono')):
            linhas.append((nome_, sum(1 for r in rels if protocolo_de(r, dom, dcs, interp)[0] == pr)))
        for o in OPCOES:
            linhas.append((f'capacidades com a opção {o} (IA)', sum(1 for x in da_ia(interp, 'capacidades') if x['opcao'] == o)))
        for o in DDMS:
            linhas.append((f'capacidades {o} (IA)', sum(1 for x in da_ia(interp, 'capacidades') if x['classe_ddms'] == o)))
    secs.append(rm.S('resumo', 'Resumo do mapa de contextos', [
        rm.T('Resumo do mapa de contextos', ['Medida', 'Quantidade'], linhas),
        rm.X('As queries de várias tabelas continuam como Legacy Query dentro de uma Group Query, que vira (ou entra em) um Delivery Context do tipo Query. Nos Domain Contexts corporativos, em vez dos comandos SQL (FILTERED_SELECT, DIRECT_SELECT e semelhantes), cada caixa traz só o agregado e os nomes dos programas corporativos originais, chamados por meio de LEGACY.')]))
    if interp and (interp['premissas'] or interp['lacunas']):
        blocos = []
        if interp['premissas']:
            blocos.append(rm.T('Premissas assumidas pela IA', ['Premissa', 'Detalhe'], [(x['assunto'], x['detalhe']) for x in interp['premissas']]))
        if interp['lacunas']:
            blocos.append(rm.T('Lacunas', ['Assunto', 'Detalhe'], [(x['assunto'], x['detalhe']) for x in interp['lacunas']]))
        secs.append(rm.S('lacunas', 'Premissas e lacunas', blocos))
    secs.append(rm.S('criterio', 'Como o mapa foi montado', [rm.X(
        'Calculado só dos relatórios das fases 12 (funcionalidades, entry points e corporativas), 15 (telas), 16 (agregados, classes e associações) e 17 (agregado ou Group Query que cada funcionalidade usa, Group Queries, programas corporativos chamados pelos agregados corporativos e chamadas entre funcionalidades). '
        'Domain Contexts: um por agregado. Delivery Contexts: entry points em Presentation; funcionalidades corporativas e Group Queries em Query. '
        'Relacionamentos: somente ligações que existem diretamente nas fases de origem; nenhuma é deduzida por transitividade. No diagrama, cada contexto traz por dentro os componentes que o constituem. '
        'O que depende de julgamento (capacidades, opção de modernização, classe DDMS, agrupamento dos Delivery Contexts, valor de negócio, estratégia de leitura e protocolo) vem da interpretação da IA, validada contra esta evidência.')]))
    cards = [rm.card('comandos SQL mapeados', len({a[0] for a in comandos_nos_contextos(ev, dom, dcs)})), rm.card('Domain Contexts', len(dom)), rm.card('Delivery Contexts', len(dcs)), rm.card('relacionamentos', len(rels))]
    if interp:
        cards.insert(0, rm.card('capacidades', len(interp['capacidades'])))
    return rm.model('Contextualização', 'Mapa semântico de contextos, com a separação entre o modelo de domínio e a entrega, na estratégia de acesso aos dados da fase 17', cards, secs)


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
    interp = ler_interp(BASE)
    erros = []
    if interp is not None:
        for k in sorted(set(interp) - CHAVES_RAIZ):
            erros.append(f'chave desconhecida na interpretação: {k}')
        for k in CHAVES_RAIZ:
            for x in interp[k]:
                if isinstance(x, dict) and 'cenario' in x:
                    erros.append(f'{k}: o campo cenario não existe (o mapa é um só) ({x.get("id") or x.get("agregado") or x.get("relacao") or x.get("de") or x.get("assunto")})')
        for k in ('premissas', 'lacunas'):
            for x in interp[k]:
                if not isinstance(x, dict) or not x.get('assunto') or not x.get('detalhe'):
                    erros.append(f'{k}: cada item precisa de assunto e detalhe')
    dom, dcs = contextos(ev, interp)
    rels = relacoes(ev, dom, dcs)
    erros += [f'o comando SQL {c} não está em nenhum contexto' for c in faltam_comandos(ev, dom, dcs)]
    if interp is not None:
        erros += validar(ev, dom, dcs, rels, interp)
    if interp is None:
        print('AVISO: sem interpretacao-contextos/*.json (prompt 9): o relatório traz só a parte calculada')
    elif erros:
        raise SystemExit('interpretação inconsistente com os relatórios:\n  ' + '\n  '.join(erros))
    S.escrever(saida, FASE, modelo(ev, (dom, dcs, rels), interp))
    print(f'{len(dom)} Domain Contexts, {len(dcs)} Delivery Contexts, {len(rels)} relacionamentos')


if __name__ == '__main__':
    main()
