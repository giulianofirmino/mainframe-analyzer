#!/usr/bin/env python3
"""Relatório contracts (fase 20, evidência determinística + nomes e decisões da IA): contratos de integração da arquitetura alvo da fase 19.

  python3 gerar_contracts.py <pasta-da-analise> [pasta-de-saida] [--interpretacao PASTA] [--planilha]   (padrão da saída: a pasta da análise)

Lê a arquitetura alvo (fase 19, reaproveitando o cálculo dela para manter os comandos, filas e programas idênticos), a estratégia CQRS e os contextos (fases 17 e 18) e a linhagem de campos
(fase 10, mapeamento SQL, e fase 3, esquema de dados). Um contrato por fronteira:
  contracts/delivery/<contexto>.openapi.yaml    um OpenAPI 3.1 por BFMF e por VAS
  contracts/domain/<contexto>.openapi.yaml      um OpenAPI 3.1 por Domain Microservice
  contracts/mainframe/<SISTEMA>W<3 letras>.cpy   um copybook por mensagem (pedido e resposta), trafegando nas filas de baixa (FR…REQ, FL…RSP) e de alta (<SISTEMA>.QL.REQ…, <SISTEMA>.QR.RSP…), com o nome de 8 posições
A interpretação da IA (prompt 11, interpretacao-contratos/*.json) dá o nome em camelCase e a descrição de cada campo, o caminho e o método das operações do BFMF, e as decisões, premissas e lacunas.
--planilha lista as chaves que a interpretação precisa cobrir (colunas e operações) e sai.
Saída: <saida>/20 - contracts/human/report.html, <saida>/20 - contracts/ia/report.json e os contratos em <saida>/20 - contracts/ia/contracts/."""
import json
import re
import shutil
import sys
import textwrap
import unicodedata
from collections import defaultdict
from pathlib import Path

import gerar_target_architecture as TA
import report_model as rm  # noqa: E402
import projeto_config  # noqa: E402

S = TA.S
FASE = '20 - contracts'
BASE = TA.BASE
CONF = {'CONFIRMED', 'UNCERTAIN', 'UNKNOWN'}
STOP = TA.STOP
HOST = re.compile(r':(?:[A-Z0-9]+\.)?([A-Z0-9][A-Z0-9\-]*)')
COLUNA_PRED = re.compile(r'(?:\b[A-Z]\.)?\b([A-Z][A-Z0-9]*_[A-Z0-9_]+)\b')
CAMPO_E = re.compile(r'\b(E-[A-Z0-9\-]+)')
ENTRADA = re.compile(r'entry point (\S+?):\s*(.*)$')
CAMPO_S = re.compile(r'no campo (S-[A-Z0-9\-]+)')
SET_PAR = re.compile(r'^([A-Z0-9_]+) ← ([A-Z0-9\-]+)$')
CAMEL_OK = re.compile(r'^[a-z][a-zA-Z0-9]*$')
FIXOS = {'valor fixo', 'valor inicial'}
NAO_RASTREADO = 'não rastreado'   # campo de entrada obrigatório cuja origem a linhagem não alcançou
MAX_LINHAS = 100          # ocorrências máximas de uma lista no copybook de resposta (premissa registrada nas lacunas)
LIM_COBOL = 30            # tamanho máximo de nome de dado COBOL


def sem_acento(t):
    return unicodedata.normalize('NFKD', str(t)).encode('ascii', 'ignore').decode()


def camel(slug_):
    ws = [w for w in slug_.split('-') if w]
    return ws[0].lower() + ''.join(w.capitalize() for w in ws[1:]) if ws else ''


def pascal(c):
    return c[:1].upper() + c[1:]


def _txt(v):
    return v.get('text', '') if isinstance(v, dict) else str(v or '')


# ---------------------------------------------------------------- leitura (fases 3 e 10)
def ler_lineage(ana):
    """Por comando original (ex.: X-Q02): colunas lidas ou gravadas, predicados com parâmetro (WHERE) e campos gravados (VALUES/SET), com a origem de cada valor (fase 10)."""
    out = defaultdict(lambda: {'cols': [], 'where': [], 'set': [], 'inf': []})
    for _s, bt, rows in S.tabelas(S.fase(ana, '10 ')):
        m = re.match(r'(\S+): (colunas explicadas|condições do WHERE explicadas|campos como parâmetro \(VALUES e SET\)|colunas e condições inferidas dos chamadores)$', bt)
        if not m:
            continue
        k = {'colunas explicadas': 'cols', 'condições do WHERE explicadas': 'where', 'colunas e condições inferidas dos chamadores': 'inf'}.get(m.group(2), 'set')
        out[m.group(1)][k] = [{a: _txt(b) for a, b in r.items()} for r in rows]
    return out


def ler_colunas(ana):
    """(tabela, coluna) → tipo, aceita nulo, campo COBOL e PIC (fase 3)."""
    cols = {}
    for _s, bt, rows in S.tabelas(S.fase(ana, '03-')):
        if bt.startswith('Colunas por tabela'):
            for r in rows:
                cols[(r['Tabela'].split('.')[-1], r['Coluna'])] = {'tipo': r['Tipo'], 'nulo': r.get('Aceita nulo', ''), 'cobol': r.get('Campo COBOL', ''), 'pic': r.get('PIC', '')}
    return cols


def tipo_coluna(C, tabelas, col):
    """Tipo da coluna: primeiro nas tabelas do comando, depois em qualquer tabela (a coluna de uma junção pode vir de outra)."""
    for t in tabelas:
        if (t, col) in C:
            return dict(C[(t, col)], tabela=t)
    for t in sorted({t for t, c in C if c == col}):   # coluna de uma junção: o tipo vem da tabela que a tem, mas a tabela não é do comando
        return dict(C[(t, col)], tabela='')
    return {'tipo': '', 'nulo': '', 'cobol': '', 'pic': '', 'tabela': ''}


def campos_comando(q, L, classif=''):
    """Campos de entrada (parâmetros do SQL, agrupados pelo campo de entrada de onde o valor vem) e de saída (colunas lidas) de um comando original, pela linhagem da fase 10.
    Entrada: `chave` identifica o campo (campo do entry point E-..., ou a coluna); `dic` é a chave do dicionário de nomes da IA (coluna, com #inicio ou #fim nas faixas);
    `entradas` = (programa, campo do entry point); `origens` = tipos de origem do valor. Saída: chave = coluna; `destinos` = campos do programa (S-...) que recebem o valor."""
    d = L.get(q, {'cols': [], 'where': [], 'set': [], 'inf': []})
    brutos = {}
    for papel, rows in (('filtro', d['where']), ('grava', d['set'])):
        for r in rows:
            if papel == 'filtro':
                hosts = HOST.findall(r['Trecho do SQL'])
                m = COLUNA_PRED.search(r['Trecho do SQL'])
                col = m.group(1) if m else ''
            else:
                m = SET_PAR.match(r['Trecho do SQL'])
                if not m:
                    continue
                col, hosts = m.group(1), [m.group(2)]
            for h in hosts:
                e = brutos.setdefault(h, {'host': h, 'coluna': col, 'entradas': [], 'origens': set(), 'trechos': [], 'papel': papel})
                e['coluna'] = e['coluna'] or col
                # "valor inicial do campo (PIC/VALUE)" é variável que a linhagem não rastreou (preenchida por MOVE de grupo, área de comunicação ou FETCH anterior), não constante do programa
                e['origens'].add(NAO_RASTREADO if r['Tipo da origem'] == 'valor fixo' and 'valor inicial do campo' in r['Origem mais distante'] else r['Tipo da origem'])
                mm = ENTRADA.search(r['Origem mais distante'])
                if mm:
                    for f in CAMPO_E.findall(mm.group(2)):
                        if (mm.group(1), f) not in e['entradas']:
                            e['entradas'].append((mm.group(1), f))
                if r['Trecho do SQL'] not in e['trechos']:
                    e['trechos'].append(r['Trecho do SQL'])
    ent = {}
    for h, e in brutos.items():
        ef = sorted({f for _p, f in e['entradas']})
        sfx = '#inicio' if re.search(r'-(INI|MIN)$', h) else '#fim' if re.search(r'-(FIM|MAX)$', h) else ''
        if len(ef) == 1:
            chave, dic = ef[0] + sfx, ef[0][2:].replace('-', '_') + sfx
        else:
            chave = e['coluna'] or h
            dic = (e['coluna'] or h.replace('-', '_')) + sfx
        g = ent.setdefault(chave, {'chave': chave, 'dic': dic, 'coluna': e['coluna'], 'hosts': [], 'entradas': [], 'origens': set(), 'trechos': [], 'papel': e['papel'], 'opcional': False})
        g['hosts'].append(h)
        g['coluna'] = g['coluna'] or e['coluna']
        g['entradas'] += [x for x in e['entradas'] if x not in g['entradas']]
        g['origens'] |= e['origens']
        g['trechos'] += [t for t in e['trechos'] if t not in g['trechos']]
        g['opcional'] = g['opcional'] or h.startswith('WRK-0-')
    for g in ent.values():
        g['fixo'] = not g['entradas'] and bool(g['origens']) and g['origens'] <= {'valor fixo'}   # constante do programa; "valor inicial" é valor que a linhagem não conseguiu rastrear
        if g['papel'] == 'filtro' and ((g['origens'] & (FIXOS | {NAO_RASTREADO}) and g['entradas']) or (not g['entradas'] and g['origens'] == {'valor inicial'})):
            g['opcional'] = True   # o filtro tem valor padrão no programa quando o usuário não informa
        g['coluna'] = g['coluna'] or g['dic'].split('#')[0]
    sai = {}
    for r in d['cols']:
        if r['Papel'] != 'lê':
            continue
        e = sai.setdefault(r['Coluna'], {'chave': r['Coluna'], 'dic': r['Coluna'], 'coluna': r['Coluna'], 'destinos': [], 'sig': r['Significado (IA)']})
        e['destinos'] += [x for x in CAMPO_S.findall(r['Destino do dado (fase 4b)']) if x not in e['destinos']]
    if not d['cols'] and d['inf']:   # consulta montada em tempo de execução: só há colunas e posições inferidas dos chamadores (sem linhagem para o programa)
        for r in d['inf']:
            if r['Parte do SQL'] == 'SELECT':
                sai.setdefault(r['Coluna'], {'chave': r['Coluna'], 'dic': r['Coluna'], 'coluna': r['Coluna'], 'destinos': [], 'sig': 'inferida dos chamadores', 'inferido': True})
        if classif == 'FILTERED_SELECT' and not ent and sai:   # consulta por código: o primeiro campo devolvido é a chave de busca
            col = next(iter(sai))
            ent['#chave'] = {'chave': col, 'dic': col, 'coluna': col, 'hosts': [], 'entradas': [], 'origens': set(), 'trechos': [], 'papel': 'filtro', 'opcional': False, 'fixo': False, 'inferido': True}
    return list(ent.values()), list(sai.values())


# ---------------------------------------------------------------- interpretação (prompt 11)
CHAVES_RAIZ = {'campos', 'operacoes', 'servicos', 'paginacao', 'decisoes', 'premissas', 'lacunas'}
VERBOS = {'consultar', 'listar', 'pesquisar', 'incluir', 'alterar', 'verificar', 'obter', 'buscar', 'criar', 'atualizar', 'excluir', 'remover', 'gravar', 'salvar', 'validar', 'calcular',
          'processar', 'enviar', 'registrar', 'recuperar', 'apagar', 'inserir', 'editar', 'exibir', 'mostrar', 'get', 'list', 'search', 'find', 'fetch', 'create', 'update', 'delete', 'set', 'add', 'remove',
          'read', 'write', 'check', 'query', 'select', 'insert', 'save', 'load', 'do', 'run', 'execute', 'executar'}


def verbos_no_caminho(cam):
    """Segmentos do caminho que começam por verbo: o endpoint é um recurso (substantivo), a ação está no método HTTP."""
    return sorted({seg for seg in cam.strip('/').split('/') if not seg.startswith('{') and seg.split('-')[0].lower() in VERBOS})


def ler_interp(base):
    d = Path(base) / 'interpretacao-contratos'
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


# ---------------------------------------------------------------- montagem dos contratos
def tabelas_do_comando(P, m, ev, f18, C, cod):
    """Tabelas que o comando (ou a parte dele, quando foi desdobrado por domínio) toca."""
    base = cod.split('.')[0]
    tabs = list(P['info'].get(base, {}).get('tabelas', []))
    for gq in ev['gqs'].values():
        if base in gq['queries']:
            tabs += [t.split('.')[-1] for t in gq['tabelas']]
    if '.' in cod:
        r = next(r for r in m['recursos'] if r['id'] == m['dono'][cod])
        dm = next((d for d in f18['dom'] if d['id'] == r['origem']), None)
        tabs = sorted({t for t, c in P['simb'].classe.items() if c and dm and c in dm['comps']} & ({t for t, _c in C}))
    return sorted(set(tabs))


def montar_comandos(P, m, ev, f18, L, C):
    """Campos de entrada e de saída de cada comando (um por fila de pedido e de resposta)."""
    cmds = {}
    classif = dict(ev['padrao'])   # classificação SQL de cada comando (fase 17; no domínio corporativo, a dos comandos que o programa corporativo executa)
    classif.update({c[0]: c[1] for c in f18['cmds'] if c[0] not in m['corp']})
    for cod, (req, rsp, prg) in sorted(m['cmd_res'].items()):
        base = cod.split('.')[0]
        i = P['info'].get(base, {})
        op = (i.get('operacoes') or ['SELECT'])[0]
        tabs = tabelas_do_comando(P, m, ev, f18, C, cod)
        ent, sai = campos_comando(base, L, classif.get(cod, ''))
        if '.' in cod:   # comando desdobrado: cada parte fica só com as colunas das tabelas dela; coluna sem tabela conhecida fica na primeira parte
            primeira = cod.endswith('.1')
            pertence = lambda col: any((t, col) in C for t in tabs) if any(c == col for _t, c in C) else primeira
            ent = [e for e in ent if pertence(e['coluna'])]
            sai = [e for e in sai if pertence(e['coluna'])]
        for e in ent + sai:
            e.update({k: v for k, v in tipo_coluna(C, tabs, e['coluna']).items()})
        for e in ent:
            e['opcional'] = e['opcional'] or (e['papel'] == 'grava' and e['nulo'] == 'sim')
        cmds[cod] = {'classif': classif.get(cod, ''), 'cod': cod, 'base': base, 'sim': P['simb'].cmd[cod], 'op': op, 'lista': bool(i.get('cursor')), 'ent': [e for e in ent if not e['fixo']], 'fixos': [e for e in ent if e['fixo']],
                     'sai': sai, 'req': req, 'rsp': rsp, 'areq': m['alta'][req][0], 'arsp': m['alta'][req][1], 'prg': prg, 'cpy_req': next(r for r in m['recursos'] if r['id'] == req)['copybook'], 'cpy_rsp': next(r for r in m['recursos'] if r['id'] == rsp)['copybook'], 'dono': m['dono'][cod], 'tabelas': tabs, 'proposito': P['props'][cod],
                     'corp': next((k for k, x in m['corp'].items() if cod in x['cmds']), None)}
    return cmds


def alcance(ev, g):
    """Funcionalidades cujos programas de entrada alimentam g: ela mesma e quem a chama (direta ou indiretamente)."""
    s, novo = {g}, True
    while novo:
        novo = False
        for a, b in ev['chama']:
            if b in s and a not in s:
                s.add(a)
                novo = True
    return s


def programas_de(ev, gs):
    return {ev['funcs'][g]['programa'] for g in gs if ev['funcs'][g]['programa']}


def entradas_da_op(cmds, cods, progs, tipo, ftipo):
    """Entradas de um conjunto de comandos para uma operação: o valor vem do chamador quando é campo de entrada de um programa de entrada que alcança a operação, ou quando vem de outro comando
    e a coluna não é devolvida pelos próprios comandos da operação (nesse caso a operação mesma obtém o valor)."""
    dml = any(cmds[c]['op'] != 'SELECT' for c in cods)
    devolvidas = {e['coluna'] for c in cods for e in cmds[c]['sai']} if dml else set()   # numa gravação, o valor que a própria operação leu não vem do chamador
    out = {}
    for c in cods:
        for e in cmds[c]['ent']:
            if e.get('inferido') and (tipo == 'BFMF' or eh_lista(ftipo)):   # chave de busca inferida: só vale para o serviço de consulta por código
                continue
            if e['entradas']:
                if not any(p in progs for p, _f in e['entradas']):
                    continue
            elif e['coluna'] in devolvidas and not e.get('inferido'):
                continue
            x = out.setdefault(e['chave'], dict(e, cmds=[]))
            x['cmds'].append(c)
            x['opcional'] = x['opcional'] and e['opcional']
    return list(out.values())


def saidas_da_op(cmds, cods, ftipo):
    """Saídas: colunas lidas pelos comandos. Funcionalidade de inclusão ou alteração devolve só o que os comandos de agregação calculam (por exemplo o próximo número)."""
    if ftipo in ('inclusão', 'alteração'):
        cods = [c for c in cods if cmds[c]['classif'] == 'AGGREGATION']
    out = {}
    for c in cods:
        for e in cmds[c]['sai']:
            x = out.setdefault(e['chave'], dict(e, cmds=[]))
            x['cmds'].append(c)
    return list(out.values())


def eh_lista(ftipo):
    return 'lista' in ftipo or 'paginada' in ftipo


def montar_operacoes(P, m, ev, f18, cmds, interp, cen=None):
    """Operações dos contratos: BFMF = uma por funcionalidade de entrada; VAS e Domain Microservice = uma por funcionalidade que os usa (as corporativas também)."""
    ops = []
    dc_de = {c: d for d in f18['dcs'] for c in d['comps']}
    ag_res = {d['agregado']: m['dm_res'][d['id']] for d in f18['dom']}
    ov = {x['funcionalidade']: x for x in (interp or {}).get('operacoes', [])}
    sv = {}
    for x in (interp or {}).get('servicos', []):
        sv[(x.get('recurso'), x.get('funcionalidade'))] = x
    servicos = {}
    for f in sorted(ev['funcs'], key=lambda x: (not ev['funcs'][x]['entry'], x)):
        v = ev['funcs'][f]
        dc = dc_de.get(f)
        if not dc or dc['tipo'] != 'Presentation':
            continue
        bff = m['dc_res'][dc['id']]['bff']
        exe = TA.exe_de(f)
        chamadas = []
        for g_ in exe:
            gv = ev['funcs'][g_]
            progs = programas_de(ev, alcance(ev, g_))
            for ag in sorted(ev['use_ag'].get(g_, {})):
                d = ag_res.get(ag)
                cs = TA.cmds_de([c for c, fs in ev['cmds'].get(ag, {}).items() if g_ in fs and c in cmds], g_)
                if d and cs:
                    chamadas.append({'app': d, 'tipo': 'DOMAIN_MICROSERVICE', 'func': g_, 'nome': gv['nome'], 'ftipo': gv['tipo'], 'cmds': cs, 'progs': progs})
            for gq in sorted(ev['use_gq'].get(g_, ())):
                dcq = dc_de.get(gq)
                vas = (m['dc_res'].get(dcq['id']) or {}).get('vas') if dcq else None
                cs = TA.cmds_de([c for c in ev['gqs'][gq]['queries'] if c in cmds], g_)
                if vas and cs:
                    chamadas.append({'app': vas, 'tipo': 'VAS', 'func': g_, 'nome': gv['nome'], 'ftipo': gv['tipo'], 'cmds': cs, 'progs': progs})
        for c in chamadas:
            k = (c['app'], c['func'])
            if k in servicos:   # a mesma funcionalidade chama o serviço por mais de um caminho (por exemplo, dois Group Queries do mesmo VAS): uma operação com os comandos dos dois
                servicos[k]['cmds'] = sorted(set(servicos[k]['cmds']) | set(c['cmds']))
                continue
            c['regras'] = list(TA.REGRAS.get(c['func'], []))
            c['entry'] = False
            servicos[k] = c
            ops.append(c)
        if v['entry']:
            cods = sorted({x for c in chamadas for x in c['cmds']})
            ops.append({'app': bff, 'tipo': 'BFMF', 'func': f, 'nome': v['nome'], 'ftipo': v['tipo'], 'cmds': cods, 'progs': programas_de(ev, set(exe)),
                        'regras': [r for g_ in exe for r in TA.REGRAS.get(g_, [])], 'entry': True, 'chama': [(c['app'], c['func']) for c in chamadas]})
    for o in ops:
        o['ent'] = entradas_da_op(cmds, o['cmds'], o['progs'], o['tipo'], o['ftipo'])
        o['sai'] = saidas_da_op(cmds, o['cmds'], o['ftipo'])
        o['oper'] = sorted({cmds[c]['op'] for c in o['cmds']})
        o['lista'] = eh_lista(o['ftipo']) or (o['tipo'] != 'BFMF' and o['ftipo'] not in ('inclusão', 'alteração') and any(cmds[c]['lista'] for c in o['cmds']) and o['ftipo'] != 'consulta de detalhe')
        o['ov'] = ov.get(o['func']) if o['tipo'] == 'BFMF' else sv.get((o['app'], o['func']))
        o['inferido_entrada'] = False
    por = {(o['app'], o['func']): o for o in ops}
    for o in ops:   # BFMF sem entrada identificada: usa as chaves do primeiro serviço chamado (inferido, vira lacuna)
        if o['tipo'] == 'BFMF' and not o['ent'] and o['chama'] and not eh_lista(o['ftipo']):
            melhor = max((por[k] for k in o['chama']), key=lambda q: len(q['ent']))
            if melhor['ent']:
                o['ent'] = [dict(e, cmds=list(e['cmds'])) for e in melhor['ent']]
                o['inferido_entrada'] = True
        if o['tipo'] == 'BFMF':
            o['partes'] = [por[k] for k in o['chama']]
    D = Dic(interp) if interp else None
    nm = (lambda k: (D.nome(k) if D else None) or k)
    for o in ops:   # entrada que um serviço devolve para outro não é entrada do BFMF: ele a obtém da resposta (ex.: código do produto que o plano devolve)
        if o['tipo'] == 'BFMF' and len(o['partes']) > 1:
            gera = {}
            for p in o['partes']:
                if p['lista']:
                    continue
                ks = {nm(e['dic']) for e in p['ent']}
                for e in p['sai']:
                    if nm(e['dic']) not in ks:
                        gera.setdefault(nm(e['dic']), p)
            o['ent'] = [e for e in o['ent'] if not (nm(e['dic']) in gera and any(nm(e['dic']) in {nm(x['dic']) for x in p['ent']} for p in o['partes'] if p is not gera[nm(e['dic'])]) and not e.get('entradas'))]
    for o in ops:   # entradas que a IA marca como obtidas da resposta de uma chamada anterior
        if o['ov'] and o['ov'].get('dispensar'):
            o['ent'] = [e for e in o['ent'] if nm(e['dic']) not in set(o['ov']['dispensar'])]
    return unificar_servicos(ops)


def paginar(ops, cmds, interp):
    """Listas paginadas (decisão da IA, `paginacao`): a operação recebe página e tamanho e devolve página, tamanho, total de itens e de páginas; nos serviços,
    os comandos de lista (cursor) da operação passam a ter os campos de paginação no copybook (pedido) e o total do filtro no cabeçalho da resposta."""
    pg = {(x.get('recurso'), x.get('funcionalidade')): x for x in (interp or {}).get('paginacao', [])}
    for c in cmds.values():
        c['paginado'] = False
    for o in ops:   # programa corporativo que um serviço expõe como lista devolve a lista inteira numa chamada (ex.: lista de uma tabela corporativa); o SELECT de uma linha, o serviço chama várias vezes.
        if o['tipo'] != 'BFMF' and o['lista']:   # o copybook mantém os campos da consulta de detalhe e acrescenta a lista no fim (RSP-LINHA-<campo>), num pedido só
            for c in o['cmds']:
                if cmds[c]['corp'] and not cmds[c]['lista']:
                    cmds[c]['lista_anexa'] = True
    for o in ops:
        o['pag'] = next((pg[(o['app'], f)] for f in o.get('funcs', [o['func']]) if (o['app'], f) in pg), None)
        if o['pag'] and o['tipo'] != 'BFMF':
            for c in o['cmds']:
                if cmds[c]['lista']:
                    cmds[c]['paginado'] = True
    return ops


def unificar_servicos(ops):
    """Um endpoint por recurso: operações do mesmo serviço com o mesmo método e caminho viram uma só (união de entradas, saídas, comandos e regras). O BFMF passa a apontar para a operação unificada."""
    grupos, novos, destino = {}, [], {}
    for o in ops:
        if o['tipo'] == 'BFMF':
            novos.append(o)
            continue
        chave = (o['app'], metodo_de(o), caminho_de(o))
        grupos.setdefault(chave, []).append(o)
    for chave, mem in grupos.items():
        mem.sort(key=lambda x: x['func'])
        if len(mem) == 1:
            u = mem[0]
            u['funcs'] = [u['func']]
        else:
            u = dict(mem[0])
            u['funcs'] = [x['func'] for x in mem]
            u['nome'] = ' / '.join(dict.fromkeys(x['nome'] for x in mem))
            u['cmds'] = sorted({c for x in mem for c in x['cmds']})
            u['progs'] = sorted({c for x in mem for c in x['progs']})
            u['oper'] = sorted({c for x in mem for c in x['oper']})
            vist, regras = set(), []
            for x in mem:
                for r in x['regras']:
                    if (r['nome'], r['tipo']) not in vist:
                        vist.add((r['nome'], r['tipo']))
                    else:
                        continue
                    regras.append(r)
            u['regras'] = regras
            em_todos = set.intersection(*[{e['dic'] for e in x['ent']} for x in mem])
            u['ent'] = [dict(e, opcional=True if e['dic'] not in em_todos else e.get('opcional', False)) for x in mem for e in x['ent']]
            u['sai'] = [e for x in mem for e in x['sai']]
            u['lista'] = any(x['lista'] for x in mem)
        for x in mem:
            destino[(x['app'], x['func'])] = u
        novos.append(u)
    for o in novos:
        if o['tipo'] == 'BFMF':
            o['chama_ops'] = list(dict.fromkeys(id(destino[k]) for k in o['chama']))
            o['chama_ops'] = [next(u for u in destino.values() if id(u) == i) for i in o['chama_ops']]
            o['partes'] = list(o['chama_ops'])
            o['chama'] = [(u['app'], u['func']) for u in o['chama_ops']]
    ids = {}
    for o in sorted(novos, key=lambda x: (x['app'], x['func'])):
        o['operationId'] = id_op(dict(o, operationId=None), ids.setdefault(o['app'], set()))
    return novos


# ---------------------------------------------------------------- tipos
DEC = re.compile(r'^DECIMAL\((\d+),(\d+)\)')
TXT = re.compile(r'^(?:VAR)?CHAR\((\d+)\)')


def tipo_info(f):
    """Tipo do campo no JSON e no copybook, a partir do tipo SQL da fase 3 (DECIMAL, CHAR, DATE...). Tipo sem tamanho (deduzido do uso) usa um valor padrão e fica marcado como UNCERTAIN."""
    t = (f.get('tipo') or '').strip()
    inf = '(inferido)' in t or not t
    base = re.sub(r'\s*\(inferido\)', '', t).strip()
    m, c = DEC.match(base), TXT.match(base)
    if m:
        p, sc = int(m.group(1)), int(m.group(2))
        if sc:
            return {'json': 'number', 'multipleOf': 10 ** -sc, 'pic': f'S9({p - sc})V9({sc})', 'tam': p, 'inferido': inf, 'x-precisao': p, 'x-escala': sc}
        return {'json': 'integer', 'format': 'int32' if p <= 9 else 'int64', 'minimum': -(10 ** p - 1), 'maximum': 10 ** p - 1, 'pic': f'S9({p})', 'tam': p, 'inferido': inf}
    if c:
        n = int(c.group(1))
        return {'json': 'string', 'maxLength': n, 'pic': f'X({n})', 'tam': n, 'inferido': inf}
    if base == 'DATE':
        return {'json': 'string', 'format': 'date', 'pic': 'X(10)', 'tam': 10, 'inferido': inf}
    if base.startswith('TIMESTAMP'):
        return {'json': 'string', 'format': 'date-time', 'pic': 'X(26)', 'tam': 26, 'inferido': inf}
    if base in ('INTEGER', 'INT'):
        return {'json': 'integer', 'format': 'int32', 'pic': 'S9(9)', 'tam': 9, 'inferido': inf}
    if base == 'SMALLINT':
        return {'json': 'integer', 'format': 'int32', 'pic': 'S9(4)', 'tam': 4, 'inferido': inf}
    if base.startswith('DECIMAL'):   # sem tamanho: valor padrão, a confirmar
        return {'json': 'integer', 'format': 'int32', 'pic': 'S9(9)', 'tam': 9, 'inferido': True}
    return {'json': 'string', 'pic': 'X(50)', 'tam': 50, 'inferido': True}   # CHAR sem tamanho ou tipo indeterminado


def ascii_up(t):
    return sem_acento(t).upper()


# ---------------------------------------------------------------- nomes (dicionário da IA)
class Dic:
    def __init__(self, interp):
        self.d = {x['coluna']: x for x in (interp or {}).get('campos', [])}

    def nome(self, k):
        return self.d[k]['nome'] if k in self.d else None

    def desc(self, k):
        return self.d[k].get('descricao', '') if k in self.d else ''


def unir(campos, D):
    """Une campos pelo nome do contrato (a mesma informação vinda de comandos diferentes aparece uma vez)."""
    out = {}
    for e in campos:
        n = D.nome(e['dic'])
        if n in out:
            x = out[n]
            x['cmds'] = sorted(set(x['cmds']) | set(e.get('cmds', [])))
            x['colunas'] |= {e['coluna']}
            x['dics'] |= {e['dic']}
            x['entradas'] = x['entradas'] + [i for i in e.get('entradas', []) if i not in x['entradas']]
            x['destinos'] = x['destinos'] + [i for i in e.get('destinos', []) if i not in x['destinos']]
            x['opcional'] = x['opcional'] and e.get('opcional', False)
        else:
            out[n] = dict(e, nome=n, colunas={e['coluna']}, dics={e['dic']}, cmds=sorted(set(e.get('cmds', []))), entradas=list(e.get('entradas', [])), destinos=list(e.get('destinos', [])), opcional=e.get('opcional', False))
    return list(out.values())


def schema_campo(e, D):
    ti = tipo_info(e)
    nul = e.get('nulo') == 'sim'
    sc = {'type': [ti['json'], 'null'] if nul else ti['json']}
    for k in ('format', 'minimum', 'maximum', 'maxLength', 'multipleOf', 'x-precisao', 'x-escala'):
        if k in ti:
            sc[{'x-precisao': 'x-precision', 'x-escala': 'x-scale'}.get(k, k)] = ti[k]
    sc['description'] = D.desc(sorted(e['dics'])[0])
    if ti['inferido']:
        sc['x-confidence'] = 'UNCERTAIN'
    sc['x-legacy'] = {'columns': sorted(e['colunas']), 'tables': [e['tabela']] if e.get('tabela') else [], 'program-fields': sorted({f for _p, f in e.get('entradas', [])} | set(e.get('destinos', []))),
                      'commands': e['cmds']}
    return sc


def pr_objeto(campos, D, obrig):
    props = {c['nome']: schema_campo(c, D) for c in campos}
    o = {'type': 'object', 'properties': props}
    req = [c['nome'] for c in campos if obrig(c)]
    if req:
        o['required'] = req
    return o


def forma_resposta(o):
    """Forma da resposta: lista de itens, ou objeto (com listas aninhadas, uma por serviço que devolve várias linhas). Devolve (tipo, campos do item/objeto, [(nome da lista, campos)])."""
    if o['tipo'] == 'BFMF' and o['ftipo'] not in ('inclusão', 'alteração'):
        planos = [p for p in o['partes']]
        if o['lista']:
            return 'lista', [c for p in planos for c in p['sai']], []
        inline = [c for p in planos if not p['lista'] for c in p['sai']]
        listas = [(camel(p['app'].split('-', 2)[2]) if p['app'].count('-') >= 2 else 'itens', p['sai']) for p in planos if p['lista']]
        return 'objeto', inline, listas
    return ('lista' if o['lista'] else 'objeto'), o['sai'], []


def metodo_de(o):
    if o['ov'] and o['ov'].get('metodo'):
        return o['ov']['metodo'].lower()
    return 'put' if 'UPDATE' in o['oper'] else 'post' if 'INSERT' in o['oper'] else 'get'


def id_op(o, usados):
    if o.get('operationId'):
        usados.add(o['operationId'])
        return o['operationId']
    base = (o['ov'] or {}).get('operationId') or camel(TA.slug(o['nome']))
    n, i = base, 2
    while n in usados:
        n, i = f'{base}{i}', i + 1
    usados.add(n)
    return n


def versao_api():
    """Versão da API do projeto (analise.config.json, chave `api`: {"versao": "v1"}, com "prefixo" opcional na frente). Todo caminho de contrato fica
    sob /<versão>; uma mudança incompatível de contrato cria a versão seguinte ao lado da atual. Sem a chave, os caminhos ficam sem versão. Prefixos
    de plataforma (como o da Nova Intranet) são decisão de arquitetura, aplicados na implementação, não no contrato."""
    a = projeto_config.carregar().get('api') or {}
    return (a.get('prefixo') or '').rstrip('/'), a.get('versao') or ''


def base_api():
    prefixo, versao = versao_api()
    return prefixo + (f'/{versao}' if versao else '')


def caminho_de(o):
    return base_api() + ((o['ov'] or {}).get('caminho') or '/' + TA.slug(o['nome']))


def doc_openapi(cen, app, ops, cen_d, P, D, simb):
    """Contrato OpenAPI 3.1 de uma aplicação (BFMF, VAS ou Domain Microservice): uma operação por funcionalidade que a usa."""
    m, cmds = cen_d['m'], cen_d['cmds']
    r = next(x for x in m['recursos'] if x['id'] == app)
    tipo = r['tipo']
    doc = {'openapi': '3.1.0',
           'info': {'title': r['nome'], 'version': (re.sub(r'\D', '', versao_api()[1]) or '0') + '.0.0' if versao_api()[1] else '0.1.0', 'summary': TA.TIPOS[tipo],
                    'description': f'Contrato de integração do recurso {app}. Uma operação por funcionalidade de negócio; nenhum modelo de persistência é exposto.'
                                   + (f' Todos os caminhos ficam sob {base_api()} (versão {versao_api()[1]} da API).' if versao_api()[1] else ''),
                    'x-resource': app},
           'paths': {}, 'components': {'schemas': {}}}
    schemas = doc['components']['schemas']
    schemas['Problem'] = {'type': 'object', 'description': 'Erro no formato de detalhes de problema (application/problem+json).',
                          'properties': {'type': {'type': 'string', 'format': 'uri-reference'}, 'title': {'type': 'string'}, 'status': {'type': 'integer', 'format': 'int32'}, 'detail': {'type': 'string'}, 'code': {'type': 'string', 'description': 'Código de negócio do erro, quando a regra devolve um.'}},
                          'required': ['title', 'status']}
    usados = set()
    prob = lambda d: {'description': d, 'content': {'application/problem+json': {'schema': {'$ref': '#/components/schemas/Problem'}}}}
    for o in sorted([x for x in ops if x['app'] == app], key=lambda x: x['func']):
        oid = id_op(o, usados)
        o['operationId'] = oid
        met, cam = metodo_de(o), caminho_de(o)
        P_ = pascal(oid)
        req = unir(o['ent'], D)
        op = {'operationId': oid, 'summary': o['nome'], 'description': ('Funcionalidade ' if len(o.get('funcs', [o['func']])) == 1 else 'Funcionalidades ') + ', '.join(o.get('funcs', [o['func']])) + ': ' + o['nome'] + '.'}
        if o['tipo'] == 'BFMF' and o['inferido_entrada']:
            op['description'] += ' Os campos de entrada foram inferidos das chaves do primeiro serviço chamado.'
        pars_path = re.findall(r'\{(\w+)\}', cam)
        if met in ('get', 'delete'):
            if req:
                op['parameters'] = [{'name': c['nome'], 'in': 'path' if c['nome'] in pars_path else 'query', 'required': c['nome'] in pars_path or (not c['opcional'] and not o['lista']), 'description': D.desc(sorted(c['dics'])[0]), 'schema': {k: v for k, v in schema_campo(c, D).items() if k not in ('description',)}} for c in req]
        else:
            if pars_path:
                op['parameters'] = [{'name': c['nome'], 'in': 'path', 'required': True, 'description': D.desc(sorted(c['dics'])[0]), 'schema': {k: v for k, v in schema_campo(c, D).items() if k not in ('description',)}} for c in req if c['nome'] in pars_path]
            corpo = [c for c in req if c['nome'] not in pars_path]
            if corpo:
                schemas[P_ + 'Request'] = pr_objeto(corpo, D, lambda c: not c['opcional'])
                op['requestBody'] = {'required': True, 'content': {'application/json': {'schema': {'$ref': f'#/components/schemas/{P_}Request'}}}}
        for nome in pars_path:
            if nome not in {c['nome'] for c in req}:
                raise SystemExit(f'{app} {o["func"]}: o caminho {cam} tem {{{nome}}}, que não é campo de entrada da operação')
        pg = o.get('pag')
        if pg:   # lista paginada: página e tamanho na entrada (nomes fixos do gerador)
            op.setdefault('parameters', []).extend([
                {'name': 'pagina', 'in': 'query', 'required': False, 'description': 'Página pedida (1 = primeira).', 'schema': {'type': 'integer', 'format': 'int32', 'minimum': 1, 'maximum': 99999, 'default': 1}},
                {'name': 'tamanhoPagina', 'in': 'query', 'required': False, 'description': f'Itens por página (1 a {pg["tamanho_maximo"]}; padrão {pg["tamanho_padrao"]}).',
                 'schema': {'type': 'integer', 'format': 'int32', 'minimum': 1, 'maximum': pg['tamanho_maximo'], 'default': pg['tamanho_padrao']}}])
        forma, campos, listas = forma_resposta(o)
        campos_u = unir(campos, D)
        resp = {}
        ok = '201' if met == 'post' else '200'
        if not campos_u and not listas:
            resp['204' if met != 'get' else '200'] = {'description': 'Operação executada; não há dados a devolver' if met != 'get' else 'Sem dados a devolver'}
        else:
            if forma == 'lista':
                schemas[P_ + 'Item'] = pr_objeto(campos_u, D, lambda c: c.get('nulo') != 'sim' and not tipo_info(c)['inferido'])
                schemas[P_ + 'Response'] = {'type': 'object', 'properties': {'itens': {'type': 'array', 'items': {'$ref': f'#/components/schemas/{P_}Item'}}}, 'required': ['itens']}
                if pg:   # resposta paginada: itens da página, página, tamanho e totais do filtro
                    schemas[P_ + 'Response']['properties'].update({
                        'pagina': {'type': 'integer', 'format': 'int32', 'description': 'Página devolvida (1 = primeira).'},
                        'tamanhoPagina': {'type': 'integer', 'format': 'int32', 'description': 'Quantidade máxima de itens por página.'},
                        'totalItens': {'type': 'integer', 'format': 'int64', 'description': 'Total de itens que atendem ao filtro, em todas as páginas.'},
                        'totalPaginas': {'type': 'integer', 'format': 'int32', 'description': 'Total de páginas (zero quando não há itens).'}})
                    schemas[P_ + 'Response']['required'] = ['itens', 'pagina', 'tamanhoPagina', 'totalItens', 'totalPaginas']
            else:
                obj = pr_objeto(campos_u, D, lambda c: c.get('nulo') != 'sim' and not tipo_info(c)['inferido'])
                for nome, cs in listas:
                    cu = unir(cs, D)
                    schemas[P_ + pascal(nome) + 'Item'] = pr_objeto(cu, D, lambda c: c.get('nulo') != 'sim' and not tipo_info(c)['inferido'])
                    obj['properties'][nome] = {'type': 'array', 'items': {'$ref': f'#/components/schemas/{P_}{pascal(nome)}Item'}}
                    obj.setdefault('required', []).append(nome)
                schemas[P_ + 'Response'] = obj
            resp[ok] = {'description': 'Operação executada', 'content': {'application/json': {'schema': {'$ref': f'#/components/schemas/{P_}Response'}}}}
        resp['400'] = prob('Requisição inválida')
        if met == 'get' and forma == 'objeto' and (campos_u or listas) and o['ftipo'].startswith('consulta'):
            resp['404'] = prob('Registro não encontrado')
        erros = [simb.texto(x['nome']) for x in o['regras'] if x['tipo'] == 'erro']
        if erros:
            resp['422'] = prob('Regra de negócio recusou a operação. Recusas possíveis: ' + '; '.join(dict.fromkeys(erros)))
        resp['500'] = prob('Falha interna')
        op['responses'] = resp
        op['x-legacy'] = {'feature': ', '.join(o.get('funcs', [o['func']])), 'commands': o['cmds']}
        if pg:
            op['x-pagination'] = {'default-page-size': pg['tamanho_padrao'], 'max-page-size': pg['tamanho_maximo'],
                                  **({'mainframe': {'request': ['REQ-NUM-PAGINA', 'REQ-QTD-POR-PAGINA'], 'response-total': 'RSP-QTD-TOTAL'}} if o['tipo'] != 'BFMF' else {})}
        regras = [simb.texto(x['nome']) for x in o['regras'] if x['tipo'] == 'regra']
        if regras:
            op['x-business-rules'] = list(dict.fromkeys(regras))
        if o['tipo'] == 'BFMF':
            op['x-calls'] = [{'service': u['app'], 'operation': u['operationId'], 'method': metodo_de(u).upper(), 'path': caminho_de(u)} for u in o['chama_ops']]
        else:
            op['x-integration'] = [{'command': cmds[c]['corp'] or cmds[c]['sim'], 'request-queue': cmds[c]['req'], 'request-queue-high': cmds[c]['areq'], 'response-queue-high': cmds[c]['arsp'], 'response-queue': cmds[c]['rsp'], 'program': cmds[c]['prg'], **({'corporate-program': cmds[c]['corp']} if cmds[c].get('corp') else {})} for c in o['cmds']]
        doc['paths'].setdefault(cam, {})[met] = op
    return doc


# ---------------------------------------------------------------- YAML
CHAVE_PLANA = re.compile(r'^[A-Za-z_$][A-Za-z0-9_$\-]*$')


def yq(k):
    return str(k) if CHAVE_PLANA.match(str(k)) else json.dumps(str(k), ensure_ascii=False)


def yesc(v):
    if isinstance(v, (dict, list)):
        return '{}' if isinstance(v, dict) else '[]'
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        return repr(v) if isinstance(v, float) else str(v)
    return json.dumps(str(v), ensure_ascii=False)


def ydump(x, n=0):
    pad = '  ' * n
    if isinstance(x, dict):
        out = []
        for k, v in x.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f'{pad}{yq(k)}:\n' + ydump(v, n + 1))
            else:
                out.append(f'{pad}{yq(k)}: {yesc(v)}')
        return '\n'.join(out)
    if isinstance(x, list):
        out = []
        for v in x:
            if isinstance(v, dict) and v:
                linhas = ydump(v, n + 1).split('\n')
                out.append(f'{pad}- ' + linhas[0].lstrip() + ('\n' + '\n'.join(linhas[1:]) if len(linhas) > 1 else ''))
            elif isinstance(v, list) and v:
                linhas = ydump(v, n + 1).split('\n')
                out.append(f'{pad}- ' + linhas[0].lstrip() + ('\n' + '\n'.join(linhas[1:]) if len(linhas) > 1 else ''))
            else:
                out.append(f'{pad}- {yesc(v)}')
        return '\n'.join(out)
    return pad + yesc(x)


# ---------------------------------------------------------------- copybooks
PIC_OK = re.compile(r'^(S?9\(\d+\)(V9\(\d+\))?|X\(\d+\))$')
LINHA_OK = re.compile(r'^ {7,15}(?P<n>01|05|10) {2}(?P<nome>[A-Z][A-Z0-9\-]{0,29})(?: +PIC (?P<pic>[SX9()V0-9]+))?(?P<occ> OCCURS 1 TO \d+ TIMES DEPENDING ON [A-Z][A-Z0-9\-]*)?\.$')


def tam_pic(pic):
    m = re.match(r'^S?9\((\d+)\)(?:V9\((\d+)\))?$', pic)
    if m:
        return int(m.group(1)) + int(m.group(2) or 0)
    return int(re.match(r'^X\((\d+)\)$', pic).group(1))


def nome_cobol(prefixo, core, usados, indicador=False):
    core = re.sub(r'[^A-Z0-9]+', '-', ascii_up(core)).strip('-')
    lim = LIM_COBOL - len(prefixo) - (4 if indicador else 0)
    base = core[:lim].rstrip('-')
    n, k = prefixo + base, 2
    while n in usados or (indicador and n + '-NUL' in usados):
        suf = str(k)
        n, k = prefixo + base[:lim - len(suf)] + suf, k + 1
    usados.add(n)
    return n


def core_req(e):
    if e.get('entradas'):
        base, fonte = sorted({f for _p, f in e['entradas']})[0][2:], 'linhagem (campo de entrada)'
    elif e.get('hosts'):
        base, fonte = re.sub(r'^WRK-(0|CH)-', '', e['hosts'][0]), 'linhagem (campo do programa)'
    else:
        base, fonte = e['coluna'].replace('_', '-'), 'coluna (sem linhagem)'
    sfx = '-INI' if e['dic'].endswith('#inicio') else '-FIM' if e['dic'].endswith('#fim') else ''
    return base + (sfx if not re.search(r'-(INI|FIM|MIN|MAX)$', base) else ''), fonte


def core_rsp(e):
    cand = [d[2:] for d in e.get('destinos', [])]
    col = e['coluna'].replace('_', '-')
    if cand:
        return (col if col in cand else cand[0]), 'linhagem (campo de saída)'
    return col, 'coluna (sem linhagem)'


def linha_campo(nivel, nome, pic, occ=''):
    cab = ' ' * (7 + {'01': 0, '05': 4, '10': 8}[nivel]) + f'{nivel}  {nome}'
    if pic:
        cab = cab.ljust(46) + f'PIC {pic}'
    return (cab + occ + '.')


def comentario(t, n=72):
    return ('      * ' + ascii_up(t))[:n]


def montar_copybook(c, lado, D, fila, simb):
    """Copybook de uma fila (requisição ou resposta) de um comando. Os nomes dos campos vêm da linhagem (campo de entrada ou de saída do programa), em caixa alta; o contrato OpenAPI guarda o nome em camelCase."""
    req = lado == 'req'
    grupo = c['cpy_req'] if req else c['cpy_rsp']   # o registro 01 tem o nome do copybook (<SISTEMA>W + 3 letras, 8 posições)
    usados, linhas, layout = {grupo}, [], []
    off = 0
    campos = unir(c['ent'] if req else c['sai'], D)
    cab = ['*' * 66, f'* COPYBOOK DA FILA DE {"REQUISICAO" if req else "RESPOSTA"}', f'* COPYBOOK: {grupo}', f'* FILA BAIXA: {fila}', f'* FILA ALTA: {c["areq"] if req else c["arsp"]}', f'* PROGRAMA: {c["prg"]}   ' + (f'CHAMA O PROGRAMA CORPORATIVO: {c["corp"]}' if c.get('corp') else f'COMANDO: {c["sim"]}'), f'* PROPOSITO: {c["proposito"]}',
           f'* OPERACAO: {c["op"]}' + ((' PAGINADO (REQ-NUM-PAGINA, REQ-QTD-POR-PAGINA)' if req else ' PAGINADO (RSP-QTD-TOTAL = TOTAL DO FILTRO)') if c.get('paginado') else ''), '*' * 66]
    texto = [('      ' + x) if x.startswith('*' * 10) else comentario(x[2:]) for x in cab]
    texto.append(linha_campo('01', grupo, ''))
    layout.append(('01', grupo, '', 0, 0, '', ''))
    nivel = '05'

    def add(nome, pic, desc='', contrato='', fonte='', lvl=None):
        nonlocal off
        lv = lvl or nivel
        for ln in textwrap.wrap(ascii_up(desc), 62):
            texto.append('      * ' + ln)
        texto.append(linha_campo(lv, nome, pic))
        t = tam_pic(pic)
        layout.append((lv, nome, pic, off, t, contrato, fonte))
        off += t
    corpo = []
    if not req:
        add(nome_cobol('RSP-', 'CODIGO-RETORNO', usados), '9(4)', 'CODIGO DE RETORNO: 0000 = EXECUTADO', 'resposta HTTP', 'cabeçalho técnico')
        add(nome_cobol('RSP-', 'SQLCODE', usados), 'S9(9)', 'SQLCODE DO DB2 (100 = NAO ENCONTRADO)', 'resposta HTTP', 'cabeçalho técnico')
        add(nome_cobol('RSP-', 'MENSAGEM', usados), 'X(80)', 'MENSAGEM DE ERRO, EM BRANCO QUANDO NAO HA', 'resposta HTTP', 'cabeçalho técnico')
        if c['op'] != 'SELECT':
            add(nome_cobol('RSP-', 'LINHAS-AFETADAS', usados), '9(9)', 'LINHAS INCLUIDAS OU ALTERADAS', 'resposta HTTP', 'cabeçalho técnico')
        if c['lista'] and c['op'] == 'SELECT':
            if c.get('paginado'):
                add(nome_cobol('RSP-', 'QTD-TOTAL', usados), '9(9)', 'QUANTIDADE TOTAL DE LINHAS QUE ATENDEM AO FILTRO (TODAS AS PAGINAS).', 'totalItens', 'paginação')
            add(nome_cobol('RSP-', 'QTD-LINHAS', usados), '9(4)', f'QUANTIDADE DE LINHAS DEVOLVIDAS NESTA PAGINA (MAXIMO {MAX_LINHAS})' if c.get('paginado') else f'QUANTIDADE DE LINHAS DEVOLVIDAS (MAXIMO {MAX_LINHAS})', 'itens', 'cabeçalho técnico')
            texto.append(linha_campo('05', 'RSP-LINHA', '')[:-1])
            texto.append(' ' * 15 + f'OCCURS 1 TO {MAX_LINHAS} TIMES DEPENDING ON RSP-QTD-LINHAS.')
            layout.append(('05', 'RSP-LINHA', '', off, 0, 'itens', f'OCCURS 1 TO {MAX_LINHAS}'))
            usados.add('RSP-LINHA')
            nivel = '10'
    pre = 'REQ-' if req else 'RSP-'
    for e in campos:
        core, fonte = core_req(e) if req else core_rsp(e)
        ind = bool(e['opcional']) if req else e.get('nulo') == 'sim'
        nome = nome_cobol(pre, core, usados, ind)
        ti = tipo_info(e)
        add(nome, ti['pic'], D.desc(sorted(e['dics'])[0]), e['nome'], fonte + (' · tipo deduzido do uso' if ti['inferido'] else ''))
        if ind:
            nome_i = nome + '-NUL'
            usados.add(nome_i)
            add(nome_i, 'X(1)', f'NULO DE {nome}: S = SIM, N = NAO', e['nome'], 'indicador de nulo')
    if not req and c.get('lista_anexa'):   # programa corporativo que também lista: os mesmos campos, um por linha, depois dos campos da consulta de detalhe
        add(nome_cobol('RSP-', 'QTD-LINHAS', usados), '9(4)', f'QUANTIDADE DE LINHAS DEVOLVIDAS (MAXIMO {MAX_LINHAS}); CODIGO ZERO NO PEDIDO LISTA TODOS', 'itens', 'cabeçalho técnico')
        texto.append(linha_campo('05', 'RSP-LINHA', '')[:-1])
        texto.append(' ' * 15 + f'OCCURS 1 TO {MAX_LINHAS} TIMES DEPENDING ON RSP-QTD-LINHAS.')
        layout.append(('05', 'RSP-LINHA', '', off, 0, 'itens', f'OCCURS 1 TO {MAX_LINHAS}'))
        usados.add('RSP-LINHA')
        for e in campos:
            core, fonte = core_rsp(e)
            ti = tipo_info(e)
            add(nome_cobol('RSP-LINHA-', core, usados, False), ti['pic'], '', e['nome'], fonte + ' · lista', '10')
    if req and c.get('paginado'):   # lista paginada: página e tamanho no fim do pedido (zero = primeira página, com o máximo de linhas)
        add(nome_cobol('REQ-', 'NUM-PAGINA', usados), '9(5)', 'PAGINA PEDIDA (1 = PRIMEIRA; ZERO = PRIMEIRA).', 'pagina', 'paginação')
        add(nome_cobol('REQ-', 'QTD-POR-PAGINA', usados), '9(3)', f'QUANTIDADE DE LINHAS POR PAGINA (1 A {MAX_LINHAS}; ZERO = {MAX_LINHAS}).', 'tamanhoPagina', 'paginação')
    return {'texto': '\n'.join(texto) + '\n', 'layout': layout, 'tam': off, 'grupo': grupo, 'campos': campos}


def validar_copybook(nome, texto):
    erros, nomes = [], []
    for i, l in enumerate(texto.split('\n'), 1):
        if not l:
            continue
        if len(l) > 72:
            erros.append(f'{nome}:{i}: linha com mais de 72 colunas')
        if l.startswith('      *'):
            continue
        if re.match(r'^ {7,15}05  RSP-LINHA$', l):
            nomes.append('RSP-LINHA')
            continue
        if re.match(r'^ {15}OCCURS 1 TO \d+ TIMES DEPENDING ON [A-Z][A-Z0-9\-]*\.$', l):
            continue
        m = LINHA_OK.match(l)
        if not m:
            erros.append(f'{nome}:{i}: linha fora do formato do copybook: {l.strip()}')
            continue
        if m.group('pic') and not PIC_OK.match(m.group('pic')):
            erros.append(f'{nome}:{i}: PIC inválido {m.group("pic")}')
        nomes.append(m.group('nome'))
    if len(nomes) != len(set(nomes)):
        erros.append(f'{nome}: nomes de dados repetidos')
    if texto != ascii_up(texto):
        erros.append(f'{nome}: o copybook precisa estar em caixa alta e sem acento')
    return erros


# ---------------------------------------------------------------- validação dos contratos
def sem_legacy(x):
    """Cópia do contrato sem os blocos x-legacy: só neles o nome do sistema atual pode aparecer."""
    if isinstance(x, dict):
        return {k: sem_legacy(v) for k, v in x.items() if k != 'x-legacy'}
    if isinstance(x, list):
        return [sem_legacy(v) for v in x]
    return x


def refs(x, acc):
    if isinstance(x, dict):
        for k, v in x.items():
            if k == '$ref':
                acc.append(v)
            else:
                refs(v, acc)
    elif isinstance(x, list):
        for v in x:
            refs(v, acc)
    return acc


def validar_openapi(nome, doc, simb):
    erros = []
    if doc.get('openapi') != '3.1.0':
        erros.append(f'{nome}: openapi precisa ser 3.1.0')
    if not doc.get('info', {}).get('title') or not doc.get('info', {}).get('version'):
        erros.append(f'{nome}: info.title e info.version são obrigatórios')
    if not doc.get('paths'):
        erros.append(f'{nome}: contrato sem operações')
    ids = []
    esq = doc.get('components', {}).get('schemas', {})
    for cam, mets in doc.get('paths', {}).items():
        if not cam.startswith('/'):
            erros.append(f'{nome}: caminho sem barra inicial: {cam}')
        if base_api() and not cam.startswith(base_api() + '/'):
            erros.append(f'{nome}: o caminho {cam} não está sob {base_api()} (versão da API)')
        for v in verbos_no_caminho(cam[len(base_api()):] if base_api() and cam.startswith(base_api()) else cam):
            erros.append(f'{nome}: o caminho {cam} tem verbo ({v}); o endpoint é um recurso')
        for met, op in mets.items():
            ids.append(op.get('operationId'))
            if not CAMEL_OK.match(op.get('operationId', '')):
                erros.append(f'{nome}: operationId fora de camelCase: {op.get("operationId")}')
            if not any(c.startswith('2') for c in op.get('responses', {})):
                erros.append(f'{nome}: {met} {cam} sem resposta 2xx')
            declarados = {p['name'] for p in op.get('parameters', []) if p['in'] == 'path'}
            if set(re.findall(r'\{(\w+)\}', cam)) != declarados:
                erros.append(f'{nome}: parâmetros de caminho de {cam} não conferem com os declarados')
            if met == 'get' and op.get('requestBody'):
                erros.append(f'{nome}: GET {cam} não pode ter corpo')
    if len(ids) != len(set(ids)):
        erros.append(f'{nome}: operationId repetido')
    for r in refs(doc, []):
        if not r.startswith('#/components/schemas/') or r.rsplit('/', 1)[-1] not in esq:
            erros.append(f'{nome}: $ref sem destino: {r}')
    for sn, sc in esq.items():
        for pn, pv in (sc.get('properties') or {}).items():
            if not CAMEL_OK.match(pn):
                erros.append(f'{nome}: propriedade fora de camelCase em {sn}: {pn}')
            partes = [w.lower() for w in re.findall(r'[A-Z]?[a-z0-9]+', pn)]
            if set(partes) & STOP:
                erros.append(f'{nome}: palavra de ligação no identificador {pn}')
            for c in (pv.get('x-legacy') or {}).get('columns', []):
                if pn.lower() == camel(c.lower().replace('_', '-')).lower():
                    erros.append(f'{nome}: {sn}.{pn} é a coluna {c} em camelCase; o nome precisa vir do significado (linhagem)')
    sobras = sorted(set(simb.residuos(sem_legacy(doc))))
    if sobras:
        erros.append(f'{nome}: cita o sistema atual fora de x-legacy: ' + ', '.join(sobras[:8]))
    return erros


# ---------------------------------------------------------------- validação da interpretação
def validar_interp(interp, cen):
    erros = []
    for k in sorted(set(interp) - CHAVES_RAIZ):
        erros.append(f'chave desconhecida na interpretação: {k}')
    D = Dic(interp)
    precisa = {}
    for c, x in cen.items():
        for o in x['ops']:
            for e in o['ent'] + o['sai']:
                precisa.setdefault(e['dic'], e)
    for k in sorted(set(precisa) - set(D.d)):
        erros.append(f'campos: falta o nome do campo {k}')
    for x in interp['campos']:
        if x.get('coluna') not in precisa:
            erros.append(f'campos: chave desconhecida {x.get("coluna")}')
        if not CAMEL_OK.match(str(x.get('nome') or '')):
            erros.append(f'campos: nome fora de camelCase em {x.get("coluna")}: {x.get("nome")}')
        if not str(x.get('descricao') or '').strip():
            erros.append(f'campos: falta a descrição de {x.get("coluna")}')
    bff = {(c, o['func']): o for c, x in cen.items() for o in x['ops'] if o['tipo'] == 'BFMF'}
    feitos = set()
    vistos = set()
    for x in interp['operacoes']:
        f = x.get('funcionalidade')
        if f not in {k[1] for k in bff}:
            erros.append(f'operacoes: funcionalidade desconhecida ou que não é entrada do BFMF: {f}')
            continue
        feitos.add(f)
        if not CAMEL_OK.match(str(x.get('operationId') or '')):
            erros.append(f'operacoes: operationId fora de camelCase em {f}')
        if str(x.get('metodo') or '').upper() not in ('GET', 'POST', 'PUT', 'DELETE'):
            erros.append(f'operacoes: método inválido em {f}')
        if not str(x.get('caminho') or '').startswith('/'):
            erros.append(f'operacoes: o caminho de {f} precisa começar com /')
        if base_api() and str(x.get('caminho') or '').startswith(base_api()):
            erros.append(f'operacoes: o caminho de {f} já traz {base_api()}; o gerador acrescenta a versão da API (informe só o recurso)')
        k = (str(x.get('metodo')).upper(), x.get('caminho'))
        if k in vistos:
            erros.append(f'operacoes: {k[0]} {k[1]} repetido')
        vistos.add(k)
    for f in sorted({k[1] for k in bff} - feitos):
        erros.append(f'operacoes: falta a operação da funcionalidade {f}')
    for x in interp['operacoes']:
        for v in verbos_no_caminho(str(x.get('caminho') or '')):
            erros.append(f'operacoes: o caminho de {x.get("funcionalidade")} tem verbo ({v}); use o recurso (substantivo) e deixe a ação no método HTTP')
    svc = {(c, o['app'], f): o for c, x in cen.items() for o in x['ops'] if o['tipo'] != 'BFMF' for f in o.get('funcs', [o['func']])}
    cobertos, vistos_s = set(), {}
    for x in interp['servicos']:
        if 'cenario' in x:
            erros.append(f'servicos: o campo cenario não existe ({x.get("recurso")} {x.get("funcionalidade")})')
        ch = [k for k in svc if k[1] == x.get('recurso') and k[2] == x.get('funcionalidade')]
        if not ch:
            erros.append(f'servicos: recurso/funcionalidade desconhecidos: {x.get("recurso")} {x.get("funcionalidade")}')
            continue
        cobertos |= set(ch)
        if not CAMEL_OK.match(str(x.get('operationId') or '')):
            erros.append(f'servicos: operationId fora de camelCase em {x.get("recurso")} {x.get("funcionalidade")}')
        if str(x.get('metodo') or '').upper() not in ('GET', 'POST', 'PUT', 'DELETE'):
            erros.append(f'servicos: método inválido em {x.get("recurso")} {x.get("funcionalidade")}')
        cam = str(x.get('caminho') or '')
        if base_api() and cam.startswith(base_api()):
            erros.append(f'servicos: o caminho {cam} já traz {base_api()}; o gerador acrescenta a versão da API (informe só o recurso)')
        if not cam.startswith('/'):
            erros.append(f'servicos: o caminho de {x.get("recurso")} {x.get("funcionalidade")} precisa começar com /')
        for v in verbos_no_caminho(cam):
            erros.append(f'servicos: o caminho {cam} tem verbo ({v}); use o recurso (substantivo) e deixe a ação no método HTTP')
        for seg in re.findall(r'[a-z0-9]+', cam.replace('{', ' ').replace('}', ' ')):
            if seg in {w.lower() for w in STOP}:
                erros.append(f'servicos: palavra de ligação no caminho {cam}')
        for k in ch:
            kk = (k[0], k[1], str(x.get('metodo')).upper(), cam)
            if kk in vistos_s and vistos_s[kk] != x.get('operationId'):
                erros.append(f'servicos: {kk[2]} {cam} em {k[1]} tem operationId diferentes ({vistos_s[kk]} e {x.get("operationId")})')
            vistos_s[kk] = x.get('operationId')
    for k in sorted(set(svc) - cobertos):
        erros.append(f'servicos: falta o caminho de {k[1]} para a funcionalidade {k[2]}')
    todas = [(c, o) for c, x in cen.items() for o in x['ops']]
    pags = {}
    for x in interp.get('paginacao', []):
        k = (x.get('recurso'), x.get('funcionalidade'))
        alvo = [o for _c, o in todas if o['app'] == k[0] and k[1] in o.get('funcs', [o['func']])]
        if not alvo:
            erros.append(f'paginacao: recurso/funcionalidade desconhecidos: {k[0]} {k[1]}')
            continue
        if k in pags:
            erros.append(f'paginacao: repetida para {k[0]} {k[1]}')
        o = alvo[0]
        pags[k] = (o, x)
        tp, tm = x.get('tamanho_padrao'), x.get('tamanho_maximo')
        if not (isinstance(tp, int) and isinstance(tm, int) and 1 <= tp <= tm <= MAX_LINHAS):
            erros.append(f'paginacao: {k[0]} {k[1]}: precisa de 1 ≤ tamanho_padrao ≤ tamanho_maximo ≤ {MAX_LINHAS} (o limite de ocorrências do copybook)')
        if not o['lista']:
            erros.append(f'paginacao: {k[0]} {k[1]} não é operação de lista')
        if o['tipo'] != 'BFMF' and not any(cen['C']['cmds'][c]['lista'] for c in o['cmds']):
            erros.append(f'paginacao: {k[0]} {k[1]} não executa lista por cursor no mainframe')
        if not str(x.get('justificativa') or '').strip():
            erros.append(f'paginacao: falta justificativa ({k[0]} {k[1]})')
    for (app, f), (o, _x) in pags.items():
        if o['tipo'] == 'BFMF' and not any((u['app'], g) in pags for u in o['chama_ops'] for g in u.get('funcs', [u['func']])):
            erros.append(f'paginacao: o BFMF {app} {f} é paginado, mas nenhum serviço que ele chama é paginado')
        if o['tipo'] != 'BFMF' and not any((b['app'], b['func']) in pags and any(u is o for u in b['chama_ops']) for _c, b in todas if b['tipo'] == 'BFMF'):
            erros.append(f'paginacao: o serviço {app} {f} é paginado, mas nenhum BFMF paginado o chama')
    for k in ('decisoes', 'lacunas'):
        for x in interp[k]:
            if x.get('confianca') not in CONF:
                erros.append(f'{k}: confianca deve ser CONFIRMED, UNCERTAIN ou UNKNOWN ({x.get("assunto")})')
            if 'cenario' in x:
                erros.append(f'{k}: o campo cenario não existe (os contratos são de uma só arquitetura) ({x.get("assunto")})')
            if not str(x.get('assunto') or '').strip() or not str(x.get('detalhe') or x.get('decisao') or '').strip():
                erros.append(f'{k}: cada item precisa de assunto e {"detalhe" if k == "lacunas" else "decisao"}')
    for x in interp['decisoes']:
        if not str(x.get('justificativa') or '').strip():
            erros.append(f'decisoes: falta justificativa ({x.get("assunto")})')
    return erros


# ---------------------------------------------------------------- arquivos dos contratos
def pasta_do(tipo):
    return 'domain' if tipo == 'DOMAIN_MICROSERVICE' else 'delivery'


def gerar_cenario(cen, x, P, D):
    """Todos os arquivos de contrato: {caminho relativo: texto} e as estruturas que o relatório mostra."""
    simb, m, cmds = P['simb'], x['m'], x['cmds']
    arquivos, docs, cpys, erros = {}, {}, {}, []
    for app in sorted({o['app'] for o in x['ops']}):
        r = next(r for r in m['recursos'] if r['id'] == app)
        doc = doc_openapi(cen, app, x['ops'], x, P, D, simb)
        nome = f'{pasta_do(r["tipo"])}/{app}.openapi.yaml'
        texto = ydump(doc) + '\n'
        erros += validar_openapi(nome, doc, simb)
        arquivos[nome] = texto
        docs[nome] = (r, doc, texto)
    grupos = defaultdict(list)   # os comandos de um programa corporativo compartilham as filas e os copybooks: um copybook por fila, com a união dos campos
    for cod, c in sorted(cmds.items()):
        grupos[(c['cpy_req'], c['cpy_rsp'])].append(c)
    for _chave, lst in sorted(grupos.items()):
        c = lst[0]
        if len(lst) > 1:
            c = dict(lst[0], ent=[e for z in lst for e in z['ent']], sai=[e for z in lst for e in z['sai']], fixos=[e for z in lst for e in z['fixos']], lista=any(z['lista'] for z in lst), lista_anexa=any(z.get('lista_anexa') for z in lst), paginado=any(z.get('paginado') for z in lst),
                     sim=lst[0]['corp'] or ', '.join(z['sim'] for z in lst), proposito=P['props'].get(lst[0].get('corp'), lst[0]['proposito']))
        for lado, fila in (('req', c['req']), ('rsp', c['rsp'])):
            nome = f'mainframe/{c["cpy_req"] if lado == "req" else c["cpy_rsp"]}.cpy'
            cp = montar_copybook(c, lado, D, fila, simb)
            erros += validar_copybook(nome, cp['texto'])
            arquivos[nome] = cp['texto']
            cpys[nome] = (c, lado, fila, cp)
    return {'arquivos': arquivos, 'docs': docs, 'cpys': cpys, 'erros': erros}


def operacoes_linhas(cen, x, g):
    rows = []
    cmds = x['cmds']
    for nome, (r, doc, _t) in g['docs'].items():
        for cam, mets in doc['paths'].items():
            for met, op in mets.items():
                o = next(o for o in x['ops'] if o['app'] == r['id'] and o.get('operationId') == op['operationId'])
                rows.append((nome, met.upper(), cam, op['operationId'], ', '.join(o.get('funcs', [o['func']])), len(o['ent']), len(o['sai']), ', '.join(sorted({cmds[c]['sim'] for c in o['cmds']}, key=lambda z: (len(z), z)))))
    return rows


def pendencias_calc(cen, x, g, D):
    out = []
    infer = {}
    for c in x['cmds'].values():
        for e in c['ent'] + c['sai']:
            if tipo_info(e)['inferido']:
                infer.setdefault(D.nome(e['dic']) or e['dic'], (e.get('tipo') or 'sem tipo', tipo_info(e)['pic']))
    if infer:
        out.append(('Campos com tipo deduzido do uso no SQL', 'O tipo não traz tamanho; o contrato usa o padrão indicado: ' + '; '.join(f'{k} ({t[0]} → {t[1]})' for k, t in sorted(infer.items())), 'UNCERTAIN'))
    nomes_sem = sorted({(cp_c['sim'], row[1]) for _n, (cp_c, _l, _f, cp) in g['cpys'].items() for row in cp['layout'] if 'sem linhagem' in row[6]})
    if nomes_sem:
        out.append(('Campos de copybook sem linhagem de campo', 'O nome do campo foi tirado da coluna porque a linhagem não traz o campo do programa: ' + '; '.join(f'{a}: {b}' for a, b in nomes_sem[:40]) + (f' (e mais {len(nomes_sem) - 40})' if len(nomes_sem) > 40 else ''), 'UNCERTAIN'))
    if x['m']['corp']:
        out.append(('Interface dos programas corporativos', 'Os relatórios não trazem a área de comunicação dos programas corporativos: o copybook de cada fila do programa corporativo reúne os campos de entrada e de saída de todos os comandos SQL do programa corporativo, e a interface real de chamada (parâmetros, formato, retorno) precisa ser confirmada com o dono do programa corporativo: ' + ', '.join(sorted(x['m']['corp'])), 'UNCERTAIN'))
    fixos = sorted({(c['sim'], f['dic']) for c in x['cmds'].values() for f in c['fixos']})
    if fixos:
        out.append(('Parâmetros com valor fixo que não trafegam', f'{len(fixos)} parâmetros SQL só recebem constantes (ex.: {", ".join(a + ":" + b for a, b in fixos[:6])}); ficam dentro do programa mainframe.', 'CONFIRMED'))
    for o in x['ops']:
        if o['tipo'] == 'BFMF' and o['inferido_entrada']:
            out.append((f'Entrada inferida em {o["func"]}', 'A linhagem não liga nenhum campo de entrada a esta funcionalidade; os campos de entrada são as chaves do primeiro serviço chamado.', 'UNCERTAIN'))
    sem_op = [r['id'] for r in x['m']['recursos'] if r['tipo'] in TA.APPS and r['id'] not in {o['app'] for o in x['ops']} and r['tipo'] != 'BFMF']
    if sem_op:
        out.append(('Recursos sem operação', 'Nenhuma funcionalidade chama estes recursos nos relatórios, então não têm contrato OpenAPI: ' + ', '.join(sem_op), 'UNCERTAIN'))
    return out


def ev_dos_contratos(P, ana):
    """O contrato REST dos serviços usa os comandos SQL: no domínio corporativo (onde a fase 17 mostra o programa corporativo chamado por meio de LEGACY), entram os comandos
    que o programa corporativo executa (e os do programa corporativo que ele chama por dentro), com as funcionalidades que executam cada um e a classificação da fase 17."""
    QS = TA.QS
    qs = QS.coletar(ana)
    de = QS.deduzir(qs)
    _b, dA, _dB = QS.cenarios(qs, de)
    ev = P['evs']['C']
    cmds = {a: {k: set(v) for k, v in cs.items() if k not in TA.CORP} for a, cs in ev['cmds'].items()}
    padrao = {k: v for k, v in ev['padrao'].items() if k not in TA.CORP}
    for cod in [o for v in TA.CORP.values() for o in v] + [o for cs_, _q in TA.INTERNOS.values() for o in cs_]:
        c = qs['cmds'][cod]
        for ag in QS.agregados_do_cmd(qs, c, dA):
            cmds.setdefault(ag, {})[cod] = set(c['func_exec'])
        padrao[cod] = QS.pexib(c['padrao'])
    return dict(ev, cmds=cmds, padrao=padrao)


def contexto(ana, base):
    P = TA.preparar(ana, TA.BASE if base is None else base)
    L, C = ler_lineage(ana), ler_colunas(ana)
    interp = ler_interp(Path(base) if base else TA.BASE)
    m, f18 = P['modelos']['C'], P['f18s']['C']
    ev = ev_dos_contratos(P, ana)
    cmds = montar_comandos(P, m, ev, f18, L, C)
    cen = {'C': {'m': m, 'ev': ev, 'f18': f18, 'cmds': cmds, 'ops': paginar(montar_operacoes(P, m, ev, f18, cmds, interp), cmds, interp)}}
    return P, cen, interp, L, C


def planilha(cen):
    campos = {}
    for c, x in cen.items():
        for o in x['ops']:
            for e in o['ent'] + o['sai']:
                d = campos.setdefault(e['dic'], {'tipo': e['tipo'], 'nulo': e['nulo'], 'sig': '', 'e': set(), 's': set(), 'cmds': set()})
                d['sig'] = d['sig'] or e.get('sig', '')
                d['e'] |= {f for _p, f in e.get('entradas', [])}
                d['s'] |= set(e.get('destinos', []))
                d['cmds'] |= set(e['cmds'])
    print('# campos (chave do dicionário)')
    for k in sorted(campos):
        d = campos[k]
        print(f"  {k} | {d['tipo']} | nulo={d['nulo']} | E={sorted(d['e'])[:2]} S={sorted(d['s'])[:2]} | {d['sig'][:170]}")
    for c, x in cen.items():
        print('# operações')
        for o in x['ops']:
            print(f"  {o['tipo'][:4]} {o['app'][-30:]:30} {o['func']:5} {o['nome'][:50]:50} cmds={len(o['cmds'])} ent={len(o['ent'])} sai={len(o['sai'])} {o['oper']} lista={o['lista']}")


# ---------------------------------------------------------------- relatório
def secoes_cenario(cen, x, g, D, P):
    m = x['m']
    secs = []
    inv = []
    for nm, (r, doc, _t) in g['docs'].items():
        nops = sum(len(v) for v in doc['paths'].values())
        inv.append((nm, 'OpenAPI 3.1', r['tipo'], r['id'], nops, len(doc['components']['schemas']) - 1))
    secs.append(rm.S('openapi', 'Contratos OpenAPI 3.1 (um por BFMF, VAS e Domain Microservice)', [
        rm.X('Cada contrato é mostrado como página de documentação (clique numa operação para abrir parâmetros, corpo, respostas e regras de negócio); o arquivo YAML está recolhido no fim de cada um. '
             'Os nomes do sistema atual aparecem só em x-legacy, como rastreabilidade.'),
        rm.T('Contratos OpenAPI', ['Arquivo', 'Formato', 'Tipo do recurso', 'Recurso', 'Operações', 'Schemas'], inv),
        rm.T('Operações dos contratos', ['Arquivo', 'Método', 'Caminho', 'operationId', 'Funcionalidade', 'Campos de entrada', 'Campos de saída', 'Comandos SQL'], operacoes_linhas(cen, x, g))]
        + [rm.OPENAPI(doc, texto, title=nm) for nm, (r, doc, texto) in g['docs'].items()]))
    cp_rows, lay_rows = [], []
    for nm, (c, lado, fila, cp) in sorted(g['cpys'].items(), key=lambda kv: (kv[1][0]['sim'], kv[1][1])):
        cp_rows.append((nm, 'requisição (MQ_REQ / MQ_REQ_ALTA)' if lado == 'req' else 'resposta (MQ_RSP_ALTA / MQ_RSP)', fila, c['areq'] if lado == 'req' else c['arsp'], c['prg'], c['sim'], c['op'], len([r for r in cp['layout'] if r[0] != '01']), cp['tam']))
        for row in cp['layout']:
            lay_rows.append((nm,) + (row[0], row[1], row[2] or '—', row[3], row[4], row[5] or '—', row[6] or '—'))
    secs.append(rm.S('copybooks', 'Copybooks das filas IBM MQ (um por fila)', [
        rm.X('Application → MQ REQ baixa → MQ REQ alta [copybook de requisição] → programa mainframe → MQ RSP alta [copybook de resposta] → MQ RSP baixa → Application. Texto em formato fixo (colunas 8 a 72), caixa alta, sem acentos. '
             'O nome de cada campo vem do campo de entrada ou de saída da linhagem; o campo correspondente do contrato REST está no layout.'),
        rm.T('Copybooks', ['Arquivo', 'Lado', 'Fila de baixa', 'Fila de alta', 'Programa', 'Comando SQL', 'Operação', 'Campos', 'Tamanho do registro (bytes, com 1 ocorrência)'], cp_rows),
        rm.T('Layout dos copybooks', ['Arquivo', 'Nível', 'Nome', 'PIC', 'Posição inicial', 'Bytes', 'Campo do contrato REST', 'Origem do nome'], lay_rows)]
        + [rm.COD(cp['texto'], title=nm) for nm, (c, lado, fila, cp) in sorted(g['cpys'].items(), key=lambda kv: (kv[1][0]['sim'], kv[1][1]))]))
    return secs


def modelo(cen_d, G, P, D, interp, validacoes):
    x, g = cen_d['C'], G['C']
    secs = secoes_cenario('C', x, g, D, P)
    pend = [(a, b, conf, 'calculada pelo gerador') for a, b, conf in pendencias_calc('C', x, g, D)]
    pend += [(y['assunto'], y['detalhe'], y['confianca'], 'IA (prompt 11)') for y in (interp or {}).get('lacunas', [])]
    blocos = [rm.T('Lacunas e decisões pendentes', ['Assunto', 'Detalhe', 'Confiança', 'Origem'], pend)]
    if interp and interp['decisoes']:
        blocos.append(rm.T('Decisões registradas pela IA', ['Assunto', 'Decisão', 'Justificativa', 'Confiança'], [(y['assunto'], y['decisao'], y['justificativa'], y['confianca']) for y in interp['decisoes']]))
    if interp and interp['premissas']:
        blocos.append(rm.T('Premissas assumidas pela IA', ['Premissa', 'Detalhe'], [(y['assunto'], y['detalhe']) for y in interp['premissas']]))
    secs.append(rm.S('lacunas-e-decisoes-pendentes', 'Lacunas e decisões pendentes', blocos))
    secs.append(rm.S('validacoes', 'Validações dos contratos', [
        rm.X('Cada contrato é conferido antes de gravar: estrutura do OpenAPI 3.1, referências, nomes em camelCase sem palavras de ligação, nome que não é a coluna do banco, ausência de nomes do sistema atual fora de x-legacy; formato fixo e PIC dos copybooks, nomes únicos e tamanho de dado até 30 caracteres.'),
        rm.T('Resultado das validações', ['Verificação', 'Resultado'], validacoes)]))
    secs.append(rm.S('criterio', 'Como os contratos foram montados', [rm.X(
        'Calculados dos relatórios das fases 03 (tipos das colunas), 10 (colunas lidas, parâmetros e linhagem de cada valor), 12 (funcionalidades e regras de negócio), 17 e 18 (contextos) e 19 (recursos, filas e programas, reaproveitando o mesmo cálculo). '
        'Uma operação por funcionalidade de negócio em cada BFMF, VAS e Domain Microservice; os campos de entrada são os que a linhagem liga a um campo do programa de entrada (ou, no serviço, a outro comando que ele não devolve) e os de saída são as colunas lidas. '
        'Os nomes em camelCase e as descrições vêm da interpretação da IA (prompt 11), validada contra os campos calculados; sem eles o gerador recusa. Os copybooks usam o nome do campo da linhagem; o nome da coluna só entra quando a linhagem não tem o campo. '
        'As listas paginadas (decisão da IA em paginacao) recebem página e tamanho na entrada e devolvem página, tamanho, total de itens e total de páginas; nos copybooks, os campos de paginação são acrescentados ao pedido e o total do filtro ao cabeçalho da resposta. '
        + (f'Todos os caminhos ficam sob {base_api()}: versão da API do projeto (analise.config.json, chave api), acrescentada pelo gerador ao caminho '
           f'do recurso que a IA define; uma mudança incompatível de contrato cria a versão seguinte ao lado da atual. ' if base_api() else '')
        + 'Os arquivos dos contratos estão em ia/contracts/.')]))
    cards = [rm.card('contratos OpenAPI', len(g['docs'])), rm.card('copybooks', len(g['cpys'])), rm.card('operações', sum(sum(len(v) for v in d['paths'].values()) for _r, d, _t in g['docs'].values()))]
    return rm.model('Contratos de Integração', 'OpenAPI 3.1 por BFMF, VAS e Domain Microservice e copybooks por fila IBM MQ da arquitetura alvo', cards, secs)


def rastreabilidade(cen_d, D):
    """Campos dos contratos com a coluna e o campo do programa de onde saem (traz o sistema atual de propósito: é a rastreabilidade pedida em x-legacy)."""
    campos = {}
    for c in cen_d:
        for o in cen_d[c]['ops']:
            for e in unir(o['ent'] + o['sai'], D):
                d = campos.setdefault(e['nome'], {'col': set(), 'tab': set(), 'prog': set(), 'cmds': set()})
                d['col'] |= e['colunas']
                d['tab'] |= {e['tabela']} if e.get('tabela') else set()
                d['prog'] |= {f for _p, f in e.get('entradas', [])} | set(e.get('destinos', []))
                d['cmds'] |= set(e['cmds'])
    rows = [(n, ', '.join(sorted(d['col'])), ', '.join(sorted(d['tab'])) or '—', ', '.join(sorted(d['prog'])) or '—', ', '.join(sorted(d['cmds']))) for n, d in sorted(campos.items())]
    return rm.S('rastreabilidade', 'Rastreabilidade com o sistema atual (x-legacy)', [
        rm.X('Cada campo dos contratos REST com a coluna do banco, a tabela, o campo do programa de entrada ou de saída (linhagem da fase 10) e os comandos de onde vem. É a única seção do relatório que cita o sistema atual; os contratos o citam só em x-legacy.'),
        rm.T('Campos dos contratos e sua origem', ['Campo do contrato', 'Colunas', 'Tabelas', 'Campos do programa (linhagem)', 'Comandos SQL'], rows)])


def main():
    args = sys.argv[1:]
    base = None
    if '--interpretacao' in args:
        i = args.index('--interpretacao')
        base = args[i + 1]
        del args[i:i + 2]
    plan = '--planilha' in args
    args = [a for a in args if a != '--planilha']
    if not args:
        sys.exit(__doc__)
    ana = Path(args[0])
    saida = Path(args[1]) if len(args) > 1 else ana
    P, cen, interp, L, C = contexto(ana, base)
    if plan:
        return planilha(cen)
    if interp is None:
        raise SystemExit('sem interpretacao-contratos/*.json (prompt 11): os nomes dos campos vêm da interpretação da IA')
    erros = validar_interp(interp, cen)
    if erros:
        raise SystemExit('interpretação inconsistente:\n  ' + '\n  '.join(erros))
    D = Dic(interp)
    G = {'C': gerar_cenario('C', cen['C'], P, D)}
    erros = G['C']['erros']
    if erros:
        raise SystemExit('contratos inconsistentes:\n  ' + '\n  '.join(erros[:40]))
    validacoes = []
    for rot, f in (('contratos OpenAPI 3.1 válidos', lambda g: len(g['docs'])), ('copybooks válidos', lambda g: len(g['cpys']))):
        validacoes.append((rot, f(G['C'])))
    validacoes.append(('problemas encontrados', len(G['C']['erros'])))
    rep = modelo(cen, G, P, D, interp, validacoes)
    simb = P['simb']
    rep['sections'] = [{**sec, 'blocks': [b if b['type'] == 'openapi' or b.get('pre') else simb.walk(b) for b in sec['blocks']]} for sec in rep['sections']]
    sobras = sorted(set(simb.residuos([{k: v for k, v in sec.items() if k != 'blocks'} for sec in rep['sections']] + [[b for b in sec['blocks'] if b['type'] != 'openapi' and not b.get('pre')] for sec in rep['sections']])))
    if sobras:
        raise SystemExit('o relatório ainda cita o sistema atual: ' + ', '.join(sobras[:20]))
    rep['sections'].insert(len(rep['sections']) - 1, rastreabilidade(cen, D))
    S.escrever(saida, FASE, rep)
    raiz = Path(saida) / FASE / 'ia' / 'contracts'
    if raiz.exists():   # só arquivos gerados por esta fase: contratos de serviços que deixaram de existir não podem sobrar
        shutil.rmtree(raiz)
    for nome, texto in G['C']['arquivos'].items():
        f = raiz / nome
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(texto, encoding='utf-8')
    print(f'{len(G["C"]["docs"])} contratos OpenAPI, {len(G["C"]["cpys"])} copybooks')


if __name__ == '__main__':
    main()
