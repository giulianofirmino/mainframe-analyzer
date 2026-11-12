#!/usr/bin/env python3
"""Relatório user-interface-mapping (fase 15): do processo PDC à tela, passando por classes, métodos e endpoints da aplicação web, e dos campos da tela aos campos da transação mainframe.

  python3 gerar_interface.py <pasta-da-analise> [pasta-de-saida] --aplicacao <pasta-da-aplicacao> --pdc <pasta-dos-xml> [--interpretacao PASTA] [--cache ARQUIVO]

Saída: <saida>/15 - user-interface-mapping/human/report.html e <saida>/15 - user-interface-mapping/ia/report.json (o mesmo modelo de visão das outras fases).

Evidência 100% calculada dos arquivos (nenhum nome de projeto no código): o adaptador Spring de cada processo (propriedade `processName`), os métodos que o usam, os chamadores até um managed bean JSF, as
telas (JSP) que usam o bean, as regras de navegação e os tiles (endpoints), a árvore de componentes visuais de cada tela, o mapeamento VO <-> request/response nos métodos de serviço e a ação do
processo (pre/post) que liga cada campo do processo ao campo da transação mainframe (com PIC e tamanho do layout).
Levantamento completo (classes, métodos, telas, campos, componentes) só para os processos das transações cujo programa a análise dinâmica executou (fase 14); para os demais, só a relação
processo -> classes -> telas. A interpretação opcional (interpretacao-interface/telas.json, prompt 6) dá o sentido de negócio de cada tela e campo e a sugestão de componente para a remodelagem."""
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import gerar_pdc as G
import gerar_simulacao as S
import intranet_indice as IX
import report_model as rm  # noqa: E402
import report_resumo as rs  # noqa: E402
from cores import COR_CLASSE  # noqa: E402

FASE = '15 - user-interface-mapping'
ENTRADA_VIS_ = {'caixa de texto', 'área de texto', 'calendário (data)', 'caixa de senha', 'combobox', 'seleção múltipla', 'checkbox', 'radio', 'upload de arquivo'}
AQUI = Path(__file__).resolve().parent
BASE = Path(os.environ['ANALISE_INTERPRETACOES']) if os.environ.get('ANALISE_INTERPRETACOES') else AQUI   # pasta das interpretações (a análise); o pipeline a informa
norm = lambda s: re.sub(r'[^a-z0-9]', '', str(s).lower())
ENTRADA_VIS = {'caixa de texto', 'área de texto', 'calendário (data)', 'caixa de senha', 'combobox', 'seleção múltipla', 'checkbox', 'radio', 'upload de arquivo'}
ACOES = ('action', 'actionListener', 'valueChangeListener', 'onclick', 'listener')


# ------------------------------------------------------------------ indexação (com cache)
def indexar(raiz, cache=None, limite=150):
    """Indexa em lotes retomáveis (a leitura da pasta pode ser lenta): `cache` é uma pasta com a lista de arquivos e um .jsonl por tipo.
    Devolve o índice completo ou None se o tempo `limite` (segundos) acabou antes (rode de novo para continuar)."""
    raiz = Path(raiz)
    t0 = time.time()
    pasta = Path(cache) if cache else None
    if pasta:
        pasta.mkdir(parents=True, exist_ok=True)
    lista = pasta / 'lista.json' if pasta else None
    if lista and lista.exists():
        todos = json.loads(lista.read_text(encoding='utf-8'))
    else:
        todos = [str(f) for f in IX.arquivos(raiz, ('.xml', '.java', '.jsp', '.properties'))]
        if lista:
            lista.write_text(json.dumps(todos), encoding='utf-8')
    feitos = {}
    for k in ('xml', 'java', 'jsp', 'props'):
        f = pasta / f'{k}.jsonl' if pasta else None
        feitos[k] = set()
        if f and f.exists():
            for ln in f.read_text(encoding='utf-8').splitlines():
                feitos[k].add(json.loads(ln)['f'])
    saidas = {k: open(pasta / f'{k}.jsonl', 'a', encoding='utf-8') if pasta else None for k in feitos}
    gerados_cache = pasta / 'gerados.json' if pasta else None
    pend = 0
    prefixos = None
    # 1ª passada: XML (define os pacotes gerados)
    for f in todos:
        if not f.lower().endswith('.xml') or f in feitos['xml']:
            continue
        if time.time() - t0 > limite:
            pend += 1
            continue
        xf = Path(f)
        a_, r_ = IX.spring([xf])
        b_, n_, t_ = IX.faces([xf])
        w_ = IX.web_xml([xf])
        saidas['xml'].write(json.dumps({'f': f, 'ad': a_, 'refs': r_, 'beans': b_, 'nav': n_, 'tiles': t_, 'web': w_}, ensure_ascii=False) + '\n')
        saidas['xml'].flush()
    if pend:
        print(f'XML pendentes: {pend}')
        return None
    xmls = [json.loads(ln) for ln in (pasta / 'xml.jsonl').read_text(encoding='utf-8').splitlines()] if pasta else []
    adaptadores = {}
    for x in xmls:
        adaptadores.update(x['ad'])
    gerados = {p for a in adaptadores.values() for p in (a['pacote_request'], a['pacote_response'], a['pacote_adaptador']) if p}
    prefixos = sorted({'.'.join(p.split('.')[:-1]) if p.endswith(('request', 'response')) else p for p in gerados})

    def fqn_de(f):
        partes = Path(f).relative_to(raiz).parts
        i = next((k for k, x in enumerate(partes) if x in ('br', 'com', 'org')), 0)
        return '.'.join(partes[i:])[:-5]
    for f in todos:
        if f.lower().endswith('.java') and f not in feitos['java']:
            if time.time() - t0 > limite:
                pend += 1
                continue
            fq = fqn_de(f)
            gerada = any(fq.startswith(p + '.') for p in prefixos if p)
            c = None if gerada else IX.classe_java(f)
            if c:
                c['fqn'] = fq
            saidas['java'].write(json.dumps({'f': f, 'fqn': fq, 'classe': c}, ensure_ascii=False) + '\n')
            saidas['java'].flush()
        elif f.lower().endswith('.properties') and f not in feitos['props']:
            if time.time() - t0 > limite:
                pend += 1
                continue
            saidas['props'].write(json.dumps({'f': f, 'p': IX.properties(f)}, ensure_ascii=False) + '\n')
            saidas['props'].flush()
        elif f.lower().endswith('.jsp') and f not in feitos['jsp']:
            if time.time() - t0 > limite:
                pend += 1
                continue
            saidas['jsp'].write(json.dumps({'f': f, 'jsp': IX.jsp(f)}, ensure_ascii=False) + '\n')
            saidas['jsp'].flush()
    for s_ in saidas.values():
        s_ and s_.close()
    if pend:
        print(f'pendentes: {pend}')
        return None
    refs, beans, nav, tiles, web = defaultdict(set), {}, [], {}, {'servlets': [], 'padroes': [], 'filtros': []}
    for x in xmls:
        for k, v in x['refs'].items():
            refs[k].update(v)
        beans.update(x['beans'])
        nav += x['nav']
        tiles.update(x['tiles'])
        for k in web:
            web[k] += x['web'][k]
    classes, fqn_arq, jsps = {}, {}, {}
    for ln in (pasta / 'java.jsonl').read_text(encoding='utf-8').splitlines():
        d = json.loads(ln)
        fqn_arq[d['fqn']] = d['f']
        if d['classe']:
            classes[d['fqn']] = d['classe']
    for ln in (pasta / 'jsp.jsonl').read_text(encoding='utf-8').splitlines():
        d = json.loads(ln)
        jsps[str(Path(d['f']).relative_to(raiz)).replace('\\', '/')] = d['jsp']
    rotulos = defaultdict(list)
    prop_regs = [json.loads(ln) for ln in (pasta / 'props.jsonl').read_text(encoding='utf-8').splitlines()]
    prop_regs.sort(key=lambda d: (0 if '_pt' in d['f'].lower() else 2 if re.search(r'_[a-z]{2}\.properties$', d['f'].lower()) else 1, d['f']))
    for d in prop_regs:
        for k, v in d['p'].items():
            if v not in rotulos[k]:
                rotulos[k].append(v)
    return {'rotulos': dict(rotulos), 'adaptadores': adaptadores, 'refs': {k: sorted(v) for k, v in refs.items()}, 'beans': beans, 'nav': nav, 'tiles': tiles, 'web': web, 'classes': classes,
            'fqn_arq': fqn_arq, 'jsps': jsps, 'prefixos_gerados': prefixos, 'segundos': round(time.time() - t0)}


# ------------------------------------------------------------------ análise
import intranet_analise as A  # noqa: E402


def jsps_do_bean(idx, bean):
    """JSP que usam o bean (qualquer expressão EL que comece por ele): {arquivo: [(ordem do componente, atributo, expressão)]}."""
    inv = idx.get('_bj')
    if inv is None:
        inv = defaultdict(lambda: defaultdict(list))
        for caminho, j in idx['jsps'].items():
            for c in j['componentes']:
                for atr, v in c['atributos'].items():
                    for e in IX.EL.findall(v):
                        for cabeca in set(re.findall(r'(?<![\w.])([A-Za-z_]\w*)(?=[.\[]|\s*$)', e)):
                            if cabeca in idx['beans']:
                                inv[cabeca][caminho].append((c['ordem'], atr, e.strip()))
        idx['_bj'] = inv
    return inv.get(bean, {})


def tela_info(idx, jsp):
    """Endpoints da tela: tiles que a têm como corpo, casos de navegação que levam a eles."""
    tiles = [n for n, t in idx['tiles'].items() if any(v and jsp.endswith(v.lstrip('/')) and v.lower().endswith('.jsp') for v in t['puts'].values())]
    nav = [x for x in idx['nav'] if x['para'] in tiles or (x['para'] and jsp.endswith(x['para'].lstrip('/')))]
    return {'tiles': tiles, 'navegacao': nav}


def bean_de_classe(idx, f):
    """Managed beans cuja classe é `f` ou herda de `f`."""
    out = []
    for cls, nomes in idx['_classe_bean'].items():
        cf = A.fq(idx, cls) or cls
        if cf == f or f in A.hierarquia(idx, cf):
            out += nomes
    return sorted(set(out))


def analisar(idx, procs_pdc, corr, sit, pdc):
    """Uma entrada por processo distinto: adaptadores e cadeia até os managed beans (relação leve para todos)."""
    A.preparar(idx)
    por_proc = defaultdict(lambda: {'transacoes': set()})
    for p in procs_pdc:
        por_proc[p['nome']]['transacoes'].add(p['transacao'])
    adap_de = defaultdict(list)
    for a in idx['adaptadores'].values():
        adap_de[a['processo']].append(a)
    resultado = {}
    for nome in sorted(por_proc):
        trans = sorted(por_proc[nome]['transacoes'])
        progs = sorted({x[0] for t in trans for x in corr.get(t, [])})
        executado = any(sit.get(x) == G.EXEC for x in progs)
        r = {'processo': nome, 'transacoes': trans, 'programas': progs, 'executado': executado, 'adaptadores': [a['bean'] for a in adap_de.get(nome, [])], 'detalhe': executado}
        r['cadeias'] = [A.cadeia(idx, a['bean']) for a in adap_de.get(nome, [])]
        r['beans'] = sorted({b for c in r['cadeias'] for b in c['beans']})
        r['telas_bean'] = sorted({jp for b in r['beans'] for jp in jsps_do_bean(idx, b)})
        resultado[nome] = r
    return resultado


def detalhar(idx, r, corr, sit, pdc):
    """Levantamento completo de um processo de transação executada: serviço, caminhos, telas, campos (tela -> VO -> processo -> layout -> programa)."""
    versoes = A.pdc_processo(G, pdc, r['processo'])
    det = {'processo': r['processo'], 'versoes': [v['versao'] for v in versoes], 'servicos': [], 'caminhos': [], 'telas': {}, 'campos': [], 'acoes': []}
    progs_exec = {t: sorted({x[0] for x in corr.get(t, []) if sit.get(x[0]) == G.EXEC}) for t in r['transacoes']}
    beans_proc = set()
    for b, cad in zip(r['adaptadores'], r['cadeias']):
        ad = idx['adaptadores'][b]
        getters = {'get' + IX.CAP(n) for n in idx['refs'].get(b, [])}
        versao = A.escolher_versao(versoes, ad['versao'])
        det.setdefault('versao_usada', versao['versao'] if versao else '')
        servicos = []
        for f, n in cad['servico']:
            ms = A.mapa_servico(idx, f, n, ad, getters)
            servicos.append({'fqn': f, 'classe': idx['classes'][f]['nome'], 'metodo': n, 'mapa': ms})
            det['servicos'].append({'adaptador': b, 'classe': idx['classes'][f]['nome'], 'metodo': n, 'assinatura': ms['assinatura'], 'request': ad['request'], 'response': ad['response'], 'versao': ad['versao']})
        # nós de managed bean (com a chamada ao próximo nó em direção ao serviço)
        locais = []   # (bean, fqn classe, método, caminho, chamadas)
        for (f, n), d in cad['dist'].items():
            for bean in bean_de_classe(idx, f):
                cam = A.caminho_ate_servico(cad, (f, n))
                chamadas = A.chamadas_no_bean(idx, A.fq(idx, idx['beans'][bean]['classe']) or f, n, cam[1][0], cam[1][1]) if len(cam) > 1 else []
                locais.append((bean, f, n, cam, chamadas))
        # só os métodos do bean que chamam o serviço mais de perto (os que chegam por outro método do bean são navegação/reuso, não o fluxo do processo)
        menor = {}
        for bean, f, n, cam, ch in locais:
            menor[bean] = min(menor.get(bean, 99), cad['dist'][(f, n)])
        locais = [l for l in locais if cad['dist'][(l[1], l[2])] == menor[l[0]]]
        for bean, f, n, cam, chamadas in locais:
            if True:
                beans_proc.add(bean)
                det['caminhos'].append({'bean': bean, 'metodo': n, 'fqn': f, 'caminho': [(idx['classes'][x]['nome'], y) for x, y in cam], 'servico': [(idx['classes'][cam[-1][0]]['nome'], cam[-1][1])],
                                        'alvo': sorted({c['alvo'] for c in chamadas if c['alvo']}), 'args': [[a['caminho'] or a['expr'] for a in c['args']] for c in chamadas]})
        # restrições por managed bean: onde o bean guarda o retorno (alvos) e de onde tira os argumentos (entradas); sem a informação, vale a regra por tipo
        ent_bean, alvo_bean = defaultdict(set), defaultdict(set)
        for bean, f, n, cam, chamadas in locais:
            for c in chamadas:
                if c['alvo']:
                    alvo_bean[bean].add(c['alvo'])
                for a_ in c['args']:
                    if a_['caminho']:
                        ent_bean[bean].add(a_['caminho'])
        dentro = lambda caminho, bases: any(caminho == b_ or caminho.startswith(b_ + '.') or caminho.startswith(b_ + '[]') for b_ in bases)
        # telas: ação do botão no método do caminho; ou campo ligado ao alvo/argumento da chamada
        sel = defaultdict(lambda: {'acoes': [], 'ligacoes': []})
        acoes = A.indice_acoes(idx)
        for bean, f, n, cam, chamadas in locais:
            for jsp, ordem in acoes.get((bean, n), []):
                sel[jsp]['acoes'].append((ordem, bean, n))
            alvos = {c['alvo'] for c in chamadas if c['alvo']} | {a['caminho'] for c in chamadas for a in c['args'] if a['caminho']}
            if alvos:
                for jsp in jsps_do_bean(idx, bean):
                    for ordem, info in A.liga_jsp(idx, jsp).items():
                        for x in (info['valor'],):
                            if x and x['bean'] == bean and any(x['caminho'] == al or x['caminho'].startswith(al + '.') for al in alvos):
                                sel[jsp]['ligacoes'].append((ordem, bean, n))
        # campos
        for sv in servicos:
            mp = sv['mapa']
            tx_prog = lambda tx: ', '.join(progs_exec.get(tx) or sorted({x[0] for x in corr.get(tx, [])})) or '—'
            alvo_de = {}
            for bean, f, n, cam, chamadas in locais:
                for c in chamadas:
                    if c['alvo']:
                        alvo_de.setdefault((bean, c['alvo']), (n, cam))
            for grupo, campo, origem in mp['ent']:
                lay = A.campo_layout(versao, grupo, campo, 'ent')
                if origem == 'constante' or not origem:
                    det['campos'].append(linha_campo(r, b, '—', None, 'entrada', f'(valor fixo/derivado no serviço)', (grupo + '.' if grupo else '') + campo, lay, tx_prog))
                    continue
                for tvo, prop in origem:
                    achou = False
                    if tvo == '@param':   # parâmetro do serviço: vem do argumento da chamada no bean; liga ao campo da tela que está nesse caminho
                        pos = [p_[1] for p_ in mp['params']].index(prop) if prop in [p_[1] for p_ in mp['params']] else -1
                        for bean, f_, n_, cam, chamadas in locais:
                            if len(cam) != 2 or cam[1] != (sv['fqn'], sv['metodo']) or pos < 0:
                                continue
                            for ch_ in chamadas:
                                caminho = ch_['args'][pos]['caminho'] if pos < len(ch_['args']) else ''
                                for jsp, s_ in sel.items():
                                    for ordem, info in A.liga_jsp(idx, jsp).items():
                                        x = info['valor']
                                        if caminho and x and x['bean'] == bean and x['caminho'] == caminho and idx['jsps'][jsp]['componentes'][ordem]['visual'] != 'núcleo':
                                            achou = True
                                            det['campos'].append(linha_campo(r, b, jsp, (ordem, x), 'entrada', f'{A.base(x["dono"])}.{x["prop"]}', (grupo + '.' if grupo else '') + campo, lay, tx_prog, idx))
                        if not achou:
                            det['campos'].append(linha_campo(r, b, '—', None, 'entrada', f'(parâmetro {prop} do serviço)', (grupo + '.' if grupo else '') + campo, lay, tx_prog))
                        continue
                    for jsp, s_ in sel.items():
                        for ordem, info in A.liga_jsp(idx, jsp).items():
                            x = info['valor']
                            if x and x['dono'] == A.base(tvo) and x['prop'] == prop and x['bean'] in {l[0] for l in locais} and idx['jsps'][jsp]['componentes'][ordem]['visual'] != 'núcleo' \
                                    and (not ent_bean.get(x['bean']) or dentro(x['caminho'], ent_bean[x['bean']])):
                                achou = True
                                det['campos'].append(linha_campo(r, b, jsp, (ordem, x), 'entrada', f'{A.base(tvo)}.{prop}', (grupo + '.' if grupo else '') + campo, lay, tx_prog, idx))
                    if not achou:
                        det['campos'].append(linha_campo(r, b, '—', None, 'entrada', f'{A.base(tvo)}.{prop}', (grupo + '.' if grupo else '') + campo, lay, tx_prog))
            for grupo, campo, alvo in mp['sai']:
                tvo, prop = alvo
                if not tvo and not prop:
                    continue
                lay = A.campo_layout(versao, grupo, campo, 'sai')
                achou = False
                for jsp, s_ in sel.items():
                    for ordem, info in A.liga_jsp(idx, jsp).items():
                        x = info['valor']
                        comp = idx['jsps'][jsp]['componentes'][ordem]
                        if not x or comp['visual'] == 'núcleo' and not info['opcoes']:
                            continue
                        if tvo == 'SelectItem':
                            if info['opcoes'] and any(x['bean'] == bean and (x['caminho'] == al) for (bean, al) in alvo_de):
                                pai = comp['pai']
                                achou = True
                                det['campos'].append(linha_campo(r, b, jsp, (pai if pai is not None else ordem, x), 'saída', f'(opções) {prop}', (grupo + '.' if grupo else '') + campo, lay, tx_prog, idx))
                        elif x['dono'] == A.base(tvo) and x['prop'] == prop and x['bean'] in {l[0] for l in locais} \
                                and (dentro(x['caminho'], alvo_bean[x['bean']]) if alvo_bean.get(x['bean']) else comp['visual'] not in ENTRADA_VIS_):
                            achou = True
                            det['campos'].append(linha_campo(r, b, jsp, (ordem, x), 'saída', f'{A.base(tvo)}.{prop}', (grupo + '.' if grupo else '') + campo, lay, tx_prog, idx))
                if not achou:
                    det['campos'].append(linha_campo(r, b, '—', None, 'saída', f'{A.base(tvo)}.{prop}' if tvo != 'SelectItem' else f'(opções) {prop}', (grupo + '.' if grupo else '') + campo, lay, tx_prog))
        for jsp, s_ in sel.items():
            t = det['telas'].setdefault(jsp, {'acoes': [], 'ligacoes': [], 'info': tela_info(idx, jsp)})
            t['acoes'] += s_['acoes']
            t['ligacoes'] += s_['ligacoes']
    com_campo = {c['tela'] for c in det['campos'] if c['tela'] != '—'}
    if com_campo:
        det['telas'] = {j: t for j, t in det['telas'].items() if j in com_campo}
    det['beans'] = sorted(beans_proc)
    # resultados de navegação por bean.método de ação
    for jsp, t in det['telas'].items():
        t['destinos'] = []
        for ordem, bean, n in t['acoes']:
            cls = A.fq(idx, idx['beans'][bean]['classe']) or ''
            for res in A.resultados_do_metodo(idx, cls, n) if cls else []:
                for nv in idx['nav']:
                    if nv['resultado'] == res and nv['de'] in ('*', '', jsp) or (nv['resultado'] == res and jsp.endswith(nv['de'].lstrip('/'))):
                        t['destinos'].append((f'{bean}.{n}', res, nv['para']))
    det['campos'] = dedup(det['campos'])
    return det


def dedup(linhas):
    vistos, out = set(), []
    for l in linhas:
        k = json.dumps(l, sort_keys=True, ensure_ascii=False)
        if k not in vistos:
            vistos.add(k)
            out.append(l)
    return out


def linha_campo(r, adaptador, jsp, comp, direcao, vo, elemento, lay, tx_prog, idx=None):
    d = {'processo': r['processo'], 'tela': jsp, 'ordem': None, 'visual': '', 'id': '', 'rotulo': '', 'el': '', 'direcao': direcao, 'vo': vo, 'elemento': elemento,
         'transacao': '', 'campo_layout': '', 'caminho_layout': '', 'pic': '', 'bytes': '', 'tipo': '', 'programa': ''}
    if comp and idx:
        ordem, x = comp
        c = idx['jsps'][jsp]['componentes'][ordem]
        d.update(ordem=ordem, visual=c['visual'], id=c['id'], rotulo=A.rotulo_do_componente(idx, jsp, ordem), el=x['expressao'])
    if lay:
        tx, caminho, leaf, pic, nb, tp = lay
        d.update(transacao=tx, campo_layout=leaf, caminho_layout=caminho, pic=pic, bytes=nb, tipo=tp, programa=tx_prog(tx))
    else:
        d['programa'] = tx_prog(r['transacoes'][0]) if r['transacoes'] else '—'
        d['transacao'] = r['transacoes'][0] if len(r['transacoes']) == 1 else ''
    return d


# ------------------------------------------------------------------ modelo
COR_TELA, COR_ENDPOINT, COR_ACAO, COR_BEAN, COR_SERVICO, COR_PROCESSO, COR_TRANSACAO = '#3F51B5', '#AD1457', '#F9A825', '#6D4C41', '#9E9D24', '#455A64', '#00695C'
curto = lambda s, n=60: s if len(s) <= n else s[:n - 1] + '…'
nome_tela = lambda jsp: '/'.join(jsp.split('/')[-2:])
sem_ext = lambda s: s.rsplit('.', 1)[0]
dir_cod = {'entrada': 'entrada', 'saída': 'saída'}


LEG_CAMINHO = [('tela', COR_TELA), ('ação da tela (botão/evento)', COR_ACAO), ('managed bean . método', COR_BEAN), ('serviço . método', COR_SERVICO), ('processo PDC', COR_PROCESSO),
               ('transação', COR_TRANSACAO), ('programa mainframe (coordenador)', COR_CLASSE['COORDENADOR'])]
LEG_CAMPOS = [('campo da tela (componente visual)', COR_TELA), ('propriedade do VO', COR_BEAN), ('campo do processo', COR_PROCESSO), ('campo da transação (layout, PIC, bytes)', COR_TRANSACAO), ('programa mainframe (coordenador)', COR_CLASSE['COORDENADOR'])]


def legenda(g, itens):
    g['legenda'] = [{'texto': t, 'cor': c} for t, c in itens]
    return g


def ordenar_tiles(jsp, info, destinos):
    """Tiles relevantes da tela: os que são destino de uma ação do fluxo ou cujo nome é o da própria tela; sem nenhum, só o tile único (se houver um só)."""
    alvo = {p for _a, _r, p in destinos}
    base_ = norm(sem_ext(jsp.split('/')[-1]))
    rel = sorted((t for t in info['tiles'] if t in alvo or (base_ and base_ in norm(t))), key=lambda t: (0 if t in alvo else 1, t))
    return rel or (info['tiles'] if len(info['tiles']) == 1 else [])


def fluxo_campo(c):
    """Relação do campo da tela com a transação, sempre com setas no sentido do dado."""
    lay = f'{c["campo_layout"]} ({c["pic"]}, {c["bytes"]} bytes)' if c['campo_layout'] else ''
    if c['direcao'] == 'entrada':
        return ' → '.join(['este campo', c['elemento']] + ([lay, c['programa']] if lay else []))
    return ' → '.join(([c['programa'], lay] if lay else []) + [c['elemento'], 'este campo'])


def texto_relacao(c):
    if not c['campo_layout']:
        return c['elemento']
    return f'{c["elemento"]} ← {c["caminho_layout"].split(".")[-1]}' if c['direcao'] == 'saída' else f'{c["elemento"]} → {c["campo_layout"]}'


def grafo_caminho(idx, det, r):
    """Tela -> ação -> bean.método -> serviço -> processo -> transação -> programa (a tela aciona o managed bean direto; o endpoint/tile fica na seção Endpoints)."""
    nos, arestas, ids = [], [], set()

    def no(id_, col, label, sub, detail, cor, inactive=False):
        if id_ not in ids:
            ids.add(id_)
            nos.append({'id': id_, 'col': col, 'label': curto(label, 34), 'sub': curto(sub, 40), 'detail': detail, 'cor': cor, 'inactive': inactive})

    def lig(a, b_):
        e = {'from': a, 'to': b_}
        if e not in arestas:
            arestas.append(e)
    progs = sorted({x for t in r['transacoes'] for x in r['programas']})
    for t in r['transacoes']:
        no('t-' + t, 5, t, 'transação', f'transação {t}', COR_TRANSACAO)
    for p in r['programas']:
        no('g-' + p, 6, p, 'programa mainframe', f'programa {p}', COR_CLASSE['COORDENADOR'])
    no('p', 4, r['processo'].split('.')[-1], 'processo PDC', r['processo'], COR_PROCESSO)
    for t in r['transacoes']:
        lig('p', 't-' + t)
        for p in r['programas']:
            lig('t-' + t, 'g-' + p)
    for sv in det['servicos']:
        sid = 's-' + sv['classe'] + '.' + sv['metodo']
        no(sid, 3, f'{sv["classe"]}.{sv["metodo"]}', 'serviço', sv['assinatura'], COR_SERVICO)
        lig(sid, 'p')
    for cm in det['caminhos']:
        bid = 'b-' + cm['bean'] + '.' + cm['metodo']
        no(bid, 2, f'{cm["bean"]}.{cm["metodo"]}', 'managed bean', ' → '.join(f'{c}.{m}' for c, m in cm['caminho']), COR_BEAN)
        lig(bid, 's-' + cm['servico'][0][0] + '.' + cm['servico'][0][1])
    for jsp, t in det['telas'].items():
        tid = 'j-' + jsp
        info = t['info']
        no(tid, 0, nome_tela(jsp), 'tela', jsp, COR_TELA)
        for ordem, bean, n in t['acoes']:
            c = idx['jsps'][jsp]['componentes'][ordem]
            aid = f'a-{jsp}-{ordem}'
            rot = A.texto_rotulo(idx, c['atributos'].get('value', '')) or c['id'] or c['tag']
            no(aid, 1, rot, c['visual'], f'{c["tag"]} id={c["id"]} {c["atributos"].get("action", "")}', COR_ACAO)
            lig(tid, aid)
            bid = f'b-{bean}.{n}'
            if bid in ids:
                lig(aid, bid)
        for ordem, bean, n in t['ligacoes']:
            bid = f'b-{bean}.{n}'
            if bid in ids:
                lig(tid, bid)
    return legenda(rs._grafo(f'Caminho de {r["processo"]}: da tela ao programa mainframe', ['Tela', 'Ação (botão/evento)', 'Managed bean . método', 'Serviço . método', 'Processo PDC', 'Transação', 'Programa'],
                     nos, arestas, 'Azul-índigo = tela; laranja = ação da tela (a tela aciona o managed bean diretamente; os tiles/endpoints estão na seção Endpoints); verde-água = managed bean; marrom = serviço; cinza-azulado = processo PDC; azul = transação e programa (coordenador). Tela sem botão do fluxo aparece ligada ao bean por um campo vinculado (seta direta tela → bean).', nw=210), LEG_CAMINHO)


def grafo_campos(det, r):
    """Campos em dois grafos, sempre da esquerda para a direita e com seta no sentido do dado.
    Entrada: campo da tela -> propriedade do VO -> campo do processo -> campo da transação -> programa.
    Saída: programa -> campo da transação -> campo do processo -> propriedade do VO -> campo da tela."""
    out = []
    for direcao, titulo, colunas, nota in (
            ('entrada', 'entrada (a tela alimenta a transação)', ['Campo da tela', 'Propriedade (VO)', 'Campo do processo', 'Campo da transação', 'Programa'],
             'Cada seta vai do dado que sai para o dado que recebe: o que o usuário informa na tela chega ao campo da transação mainframe e ao programa.'),
            ('saída', 'saída (a transação alimenta a tela)', ['Programa', 'Campo da transação', 'Campo do processo', 'Propriedade (VO)', 'Campo da tela'],
             'Cada seta vai do dado que sai para o dado que recebe: o programa devolve o campo da transação, que passa pelo campo do processo e pela propriedade até aparecer na tela.')):
        nos, arestas, ids = [], [], set()
        for c in det['campos']:
            if c['tela'] == '—' or not c['campo_layout'] or c['direcao'] != direcao:
                continue
            ent = direcao == 'entrada'
            tid = f'c-{c["tela"]}-{c["ordem"]}'
            vid, eid, lid, pid = 'v-' + c['vo'], 'e-' + c['elemento'] + c['direcao'], 'l-' + c['campo_layout'], 'g-' + c['programa']
            specs = [(tid, 0, c['rotulo'] or c['id'] or c['el'], f'{c["visual"]} · {nome_tela(c["tela"])}', c['el'], COR_TELA), (vid, 1, c['vo'], 'propriedade do VO', c['vo'], COR_BEAN),
                     (eid, 2, c['elemento'], 'campo do processo', f'{c["elemento"]} ({c["direcao"]})', COR_PROCESSO), (lid, 3, c['campo_layout'], f'{c["pic"]} · {c["bytes"]} bytes', c['caminho_layout'], COR_TRANSACAO),
                     (pid, 4, c['programa'], 'programa', c['programa'], COR_CLASSE['COORDENADOR'])]
            for id_, col, lab, sub, det_, cor in specs:
                if id_ not in ids:
                    ids.add(id_)
                    nos.append({'id': id_, 'col': col if ent else 4 - col, 'label': curto(lab, 30), 'sub': curto(sub, 44), 'detail': det_, 'cor': cor})
            seq = [tid, vid, eid, lid, pid] if ent else [pid, lid, eid, vid, tid]
            for x, y in zip(seq, seq[1:]):
                e = {'from': x, 'to': y}
                if e not in arestas:
                    arestas.append(e)
        if nos:
            out.append(legenda(rs._grafo(f'Campos de {r["processo"]}: {titulo}', colunas, nos, arestas, nota, nw=210), LEG_CAMPOS))
    return out


# ------------------------------------------------------------------ interpretação (prompt 6)
OBRIG = ('obrigatório', 'opcional', 'não determinado')
TIPOS_DADO = ('código', 'descrição', 'texto livre', 'número', 'valor monetário', 'data', 'indicador sim/não', 'outro')
CONF = ('alta', 'média', 'baixa')
COMPONENTES_SUGERIDOS = ('caixa de texto', 'área de texto', 'campo numérico', 'campo monetário', 'campo de data', 'seleção única (lista)', 'seleção única com busca', 'seleção múltipla', 'caixa de marcação',
                         'opção exclusiva (radio)', 'interruptor sim/não', 'texto somente leitura', 'tabela', 'tabela com paginação', 'botão primário', 'botão secundário', 'link', 'mensagem', 'aba', 'outro')


def chaves_tela(idx, jsp):
    """Componentes de uma tela que o prompt 6 precisa explicar: {'campos': {chave: componente}, 'acoes': {chave: componente}, 'todas': conjunto de ids e rótulos}."""
    j = idx['jsps'][jsp]
    liga = A.liga_jsp(idx, jsp)
    campos, acoes, todas = {}, {}, set()
    for c in j['componentes']:
        rot = A.rotulo_do_componente(idx, jsp, c['ordem']) if c['visual'] in A.ENTRADA_VIS | {'rótulo / texto', 'coluna da listagem'} else A.texto_rotulo(idx, c['atributos'].get('value', '')) if c['visual'] in ('botão', 'link') else ''
        for k in (c['id'], rot):
            if k:
                todas.add(k)
        v = liga[c['ordem']]
        chave = c['id'] or rot
        if not chave:
            continue
        if c['visual'] in ('botão', 'link') and v['acao']:
            acoes.setdefault(chave, c)
        elif c['visual'] in A.ENTRADA_VIS or (c['visual'] == 'rótulo / texto' and v['valor'] and not v['opcoes']):
            campos.setdefault(chave, c)
    return {'campos': campos, 'acoes': acoes, 'todas': todas}


def ler_interp(base):
    """Junta os JSON de `interpretacao-interface/` (a IA pode dividir as telas em vários arquivos): telas e processos somam; visao_geral vem do arquivo que a trouxer."""
    pasta = Path(base) / 'interpretacao-interface'
    arqs = sorted(f for f in pasta.glob('*.json') if f.name not in ('PROVENIENCIA.json', ORIGENS_ARQ)) if pasta.exists() else []
    if not arqs:
        return None
    out = {'telas': [], 'processos': [], 'visao_geral': ''}
    for f in arqs:
        d = json.loads(f.read_text(encoding='utf-8'))
        out['telas'] += d.get('telas', [])
        out['processos'] += d.get('processos', [])
        out['visao_geral'] = out['visao_geral'] or d.get('visao_geral', '')
    nomes = [t.get('tela') for t in out['telas']]
    dup = sorted({n for n in nomes if nomes.count(n) > 1})
    if dup:
        sys.exit('tela analisada em mais de um arquivo: ' + ', '.join(dup))
    return out


ORIGENS_ARQ = 'origens-complementares.json'


def ler_origens(base, idx):
    """Origens de campos que vêm de processos sem programa analisado, confirmadas com fontes entregues depois (interpretacao-interface/origens-complementares.json).
    Cada item aponta para um componente da tela (tela como aparece no relatório + id); devolve {jsp: [(ordem, item)]}."""
    f = Path(base) / 'interpretacao-interface' / ORIGENS_ARQ
    if not f.exists():
        return {}
    por_nome = {nome_tela(jsp): jsp for jsp in idx['jsps']}
    out, erros = defaultdict(list), []
    for o in json.loads(f.read_text(encoding='utf-8')).get('origens', []):
        jsp = por_nome.get(o.get('tela'))
        ordem = next((c['ordem'] for c in idx['jsps'][jsp]['componentes'] if c['id'] == o.get('id')), None) if jsp else None
        if ordem is None:
            erros.append(f'{o.get("tela")} #{o.get("id")}: componente não encontrado')
        else:
            out[jsp].append((ordem, o))
    if erros:
        sys.exit(f'{ORIGENS_ARQ} inválido:\n' + '\n'.join(erros))
    return out


def validar_interp(d, telas, procs):
    """telas = {nome da tela: chaves_tela(...)}; procs = nomes dos processos detalhados. Devolve a lista de erros."""
    erros = []
    por_tela = {t.get('tela'): t for t in d.get('telas', [])}
    for nome, ch in telas.items():
        t = por_tela.get(nome)
        if not t:
            erros.append(f'tela sem análise: {nome}')
            continue
        for k in ('finalidade', 'jornada', 'layout_sugerido'):
            if not str(t.get(k) or '').strip():
                erros.append(f'{nome}: {k} vazio')
        if t.get('confianca') not in CONF:
            erros.append(f'{nome}: confianca inválida {t.get("confianca")!r}')
        if not isinstance(t.get('lacunas'), list):
            erros.append(f'{nome}: lacunas deve ser lista')
        explicados = set()
        for c in t.get('campos') or []:
            k = c.get('campo')
            if k not in ch['todas']:
                erros.append(f'{nome}: campo inexistente na tela: {k!r}')
            explicados.add(k)
            if c.get('obrigatoriedade') not in OBRIG:
                erros.append(f'{nome}.{k}: obrigatoriedade inválida {c.get("obrigatoriedade")!r}')
            if c.get('tipo_dado') not in TIPOS_DADO:
                erros.append(f'{nome}.{k}: tipo_dado inválido {c.get("tipo_dado")!r}')
            if c.get('componente_sugerido') not in COMPONENTES_SUGERIDOS:
                erros.append(f'{nome}.{k}: componente_sugerido fora do vocabulário {c.get("componente_sugerido")!r}')
            if not str(c.get('significado') or '').strip():
                erros.append(f'{nome}.{k}: significado vazio')
        for k in ch['campos']:
            if k not in explicados:
                erros.append(f'{nome}: campo sem explicação: {k!r}')
        ac = {a.get('acao') for a in t.get('acoes') or []}
        for a in ac:
            if a not in ch['todas']:
                erros.append(f'{nome}: ação inexistente na tela: {a!r}')
        for k in ch['acoes']:
            if k not in ac:
                erros.append(f'{nome}: ação sem explicação: {k!r}')
        ok_comp = lambda k: k in ch['todas'] or re.sub(r'\s*\(.*\)$', '', str(k)) in ch['todas']
        for e in t.get('eventos') or []:   # opcionais para compatibilidade com interpretações antigas; se vierem, são conferidas
            if not (ok_comp(e.get('disparador')) or str(e.get('disparador') or '').lower().startswith(('abertura', 'entrada'))):
                erros.append(f'{nome}: evento {e.get("evento")!r} cita disparador inexistente {e.get("disparador")!r}')
            for k in ('evento', 'significado', 'afetados', 'remodelagem'):
                if not str(e.get(k) or '').strip():
                    erros.append(f'{nome}: evento {e.get("disparador")!r}: {k} vazio')
        for rg in t.get('regras_apresentacao') or []:
            if not ok_comp(rg.get('componente')):
                erros.append(f'{nome}: regra cita componente inexistente {rg.get("componente")!r}')
            for k in ('regra', 'significado', 'remodelagem'):
                if not str(rg.get(k) or '').strip():
                    erros.append(f'{nome}: regra {rg.get("componente")!r}: {k} vazio')
        for g in t.get('agrupamentos') or []:
            for k in g.get('componentes') or []:
                if k not in ch['todas']:
                    erros.append(f'{nome}: agrupamento {g.get("nome")!r} cita componente inexistente {k!r}')
    pp = {p.get('processo'): p for p in d.get('processos', [])}   # telas/processos fora do relatório (o escopo encolheu) são ignorados
    for n in procs:
        p = pp.get(n)
        if not p:
            erros.append(f'processo sem análise: {n}')
            continue
        for k in ('finalidade', 'entradas', 'saidas'):
            if not str(p.get(k) or '').strip():
                erros.append(f'{n}: {k} vazio')
        if p.get('confianca') not in CONF:
            erros.append(f'{n}: confianca inválida')
    if not str(d.get('visao_geral') or '').strip():
        erros.append('visao_geral vazio')
    return erros


def secao_interp(idx, d, telas_info, ligados_tela, procs_ok):
    bl = [rm.X(d['visao_geral'], 'Visão geral da remodelagem')]
    d = dict(d, telas=[t for t in d['telas'] if t['tela'] in telas_info], processos=[p for p in d['processos'] if p['processo'] in procs_ok])
    bl.append(rm.T('Telas: finalidade, jornada e layout sugerido', ['Tela', 'Finalidade', 'Jornada', 'Layout sugerido', 'Confiança', 'Lacunas'],
                   [(t['tela'], t['finalidade'], t['jornada'], t['layout_sugerido'], t['confianca'], '; '.join(t['lacunas']) or '—') for t in d['telas']]))
    for t in d['telas']:
        jsp = telas_info[t['tela']]['jsp']
        ch = chaves_tela(idx, jsp)
        rel = {}
        for ordem, vs in ligados_tela.get(jsp, {}).items():
            c = idx['jsps'][jsp]['componentes'][ordem]
            rel[c['id'] or A.rotulo_do_componente(idx, jsp, ordem)] = ' | '.join(vs)
        linhas = []
        for c in t['campos']:
            comp = ch['campos'].get(c['campo'])
            linhas.append((c['campo'], comp['visual'] if comp else '—', 'entrada' if comp and comp['visual'] in A.ENTRADA_VIS else 'saída', c['significado'], c['obrigatoriedade'], c['tipo_dado'], c['componente_sugerido'], rel.get(c['campo'], '—')))
        bl.append(rm.T(f'Campos de {t["tela"]}: significado e componente sugerido', ['Campo', 'Componente atual', 'Direção', 'Significado', 'Obrigatoriedade', 'Tipo do dado', 'Componente sugerido', 'Relação com a transação'], linhas))
        if t.get('agrupamentos'):
            bl.append(rm.T(f'Agrupamentos de {t["tela"]}', ['Grupo', 'Descrição', 'Componentes (em ordem)'], [(g['nome'], g['descricao'], ', '.join(g['componentes'])) for g in t['agrupamentos']]))
        if t.get('eventos'):
            bl.append(rm.T(f'Eventos de {t["tela"]}: significado e remodelagem', ['Evento', 'Disparador', 'Significado', 'Afetados', 'Remodelagem'], [(e['evento'], e['disparador'], e['significado'], e['afetados'], e['remodelagem']) for e in t['eventos']]))
        if t.get('regras_apresentacao'):
            bl.append(rm.T(f'Regras de apresentação de {t["tela"]}: significado e remodelagem', ['Componente', 'Regra', 'Significado', 'Remodelagem'], [(r_['componente'], r_['regra'], r_['significado'], r_['remodelagem']) for r_ in t['regras_apresentacao']]))
        if t.get('acoes'):
            bl.append(rm.T(f'Ações de {t["tela"]}', ['Ação', 'Significado', 'Resultado'], [(a['acao'], a['significado'], a['resultado']) for a in t['acoes']]))
    sem = [t['tela'] for t in d['telas'] if 'eventos' not in t or 'regras_apresentacao' not in t]
    if sem:
        print('AVISO: interpretação sem eventos/regras de apresentação em ' + ', '.join(sem) + ' (rode o prompt 6 de novo para preenchê-los)', file=sys.stderr)
    bl.append(rm.T('Processos: finalidade, entradas e saídas', ['Processo', 'Finalidade', 'Entradas', 'Saídas', 'Confiança', 'Lacunas'],
                   [(p['processo'], p['finalidade'], p['entradas'], p['saidas'], p['confianca'], '; '.join(p['lacunas']) or '—') for p in d['processos']]))
    sec = rm.S('interpretacao', 'Remodelagem das telas legadas', bl, 'Texto escrito pela IA a partir deste relatório (prompt 6); o script confere cada tela, campo e ação contra a evidência.')
    sec['so_ia'] = 'Exibida no Design das Aplicações de Frontend (20a), seção Telas; aqui fica na visão para IA, lida pelas fases 18 e 19 e pelos prompts 9, 10 e 13.'
    return sec


# ------------------------------------------------------------------ funil por cobertura de programas
LIMIAR_FUNIL = 0.8   # fração do universo de programas que a tela precisa usar para ficar no relatório


def funil(an, dets, corr, sit):
    """Quais telas usam os programas analisados da fase pdc-mapping (todos ou quase todos).

    Universo = programas correlacionados a transações do PDC na fase 14. Por tela: programas usados pela relação direta (campos/ações dos processos detalhados) e pela relação
    por managed bean (processos sem detalhe). Mantém as telas com cobertura >= LIMIAR_FUNIL do universo (ou, se nenhuma chegar, as de maior cobertura); omite as sem programa."""
    universo = sorted({x[0] for t in corr for x in corr[t]})
    direto, bean, sem_prog = defaultdict(set), defaultdict(set), defaultdict(set)
    proc_direto, proc_bean = defaultdict(set), defaultdict(set)
    for nome, r in an.items():
        progs = set(r['programas'])
        for jsp in r['telas_bean']:
            if progs:
                bean[jsp].update(progs)
                proc_bean[jsp].add(nome)
            else:
                sem_prog[jsp].add(nome)
    for nome, d in dets.items():
        for jsp in d['telas']:
            direto[jsp] |= set(an[nome]['programas'])
            proc_direto[jsp].add(nome)
    telas = sorted(set(direto) | set(bean))
    cob = {j: len((direto[j] | bean[j]) & set(universo)) for j in telas}
    cob_dir = {j: len(direto[j] & set(universo)) for j in telas}
    n = len(universo)
    com_prog = [j for j in telas if cob[j]]
    alvo = max([cob[j] for j in telas] or [0])
    minimo = max(1, -(-int(LIMIAR_FUNIL * n * 100) // 100)) if n else 1
    minimo = min(minimo, alvo) if alvo else minimo
    mantidas = [j for j in com_prog if cob[j] >= minimo]
    ordem = sorted(com_prog, key=lambda j: (-cob[j], -cob_dir[j], j))
    return {'proc_direto': proc_direto, 'proc_bean': proc_bean, 'universo': universo, 'direto': direto, 'bean': bean, 'sem_prog': sem_prog, 'cob': cob, 'cob_dir': cob_dir, 'minimo': minimo,
            'mantidas': set(mantidas), 'ordem': ordem, 'omitidas_sem_programa': [j for j in telas if not cob[j]]}


def aplicar_funil(dets, fu):
    """Remove dos processos detalhados as telas (e as linhas de campo) que ficaram fora do funil."""
    for d in dets.values():
        d['telas'] = {j: t for j, t in d['telas'].items() if j in fu['mantidas']}
        d['campos'] = [c for c in d['campos'] if c['tela'] == '—' or c['tela'] in fu['mantidas']]
        # só os managed beans que as telas mantidas acionam (por botão ou por campo ligado); os outros pertencem a telas omitidas
        usados = {(b, n) for t in d['telas'].values() for _o, b, n in t['acoes'] + t['ligacoes']}
        if usados:
            d['caminhos'] = [c for c in d['caminhos'] if (c['bean'], c['metodo']) in usados]
            d['beans'] = sorted({c['bean'] for c in d['caminhos']})
            # só os serviços que esses beans chamam (os demais pertencem a telas omitidas)
            chamados = {tuple(c['servico'][0]) for c in d['caminhos']}
            d['servicos'] = [sv for sv in d['servicos'] if (sv['classe'], sv['metodo']) in chamados]


def secao_funil(idx, an, fu, sit, dets):
    L = fu['universo']
    n = len(L)
    sit_txt = {p: sit.get(p, G.NAO) for p in L}
    sem_exec = [p for p in L if sit_txt[p] != G.EXEC]
    linhas = []
    for j in fu['ordem']:
        usa = fu['direto'][j] | fu['bean'][j]
        usados = [p for p in L if p in usa]
        faltam = [p for p in L if p not in usa]
        nao_exec = [p for p in usados if sit_txt[p] != G.EXEC]
        so_bean = [p for p in usados if p not in fu['direto'][j]]
        estado = 'mantida' if j in fu['mantidas'] else 'omitida (cobertura abaixo do limiar)'
        linhas.append((nome_tela(j), estado, f'{fu["cob_dir"][j]}/{n}', f'{len(usados)}/{n}', ', '.join(usados) or '—', ', '.join(faltam) or '—',
                       ', '.join(nao_exec) or '—', ', '.join(so_bean) or '—', len(fu['sem_prog'][j])))
    fora = fu['omitidas_sem_programa']
    ret = [j for j in fu['ordem'] if j in fu['mantidas']]
    bl = [rm.X(f'Universo: {n} programa(s) correlacionado(s) a transações do PDC na fase pdc-mapping ({", ".join(L)}); {n - len(sem_exec)} executado(s) na análise dinâmica'
               + (f' e {len(sem_exec)} analisado(s) mas não executado(s) ({", ".join(sem_exec)})' if sem_exec else '') + '. Só esses programas contam; processos sem programa mapeado não entram na cobertura.'),
          rm.X(f'Critério do funil: cada tela recebe os programas dos processos que ela usa (relação direta = campo ou botão ligado ao processo; relação por bean = a tela usa um managed bean que chega ao serviço do processo). '
               f'Ficam as telas que usam pelo menos {fu["minimo"]} dos {n} programas (relação direta ou por bean; {int(LIMIAR_FUNIL * 100)}% do universo, ou a maior cobertura encontrada); as telas sem nenhum programa mapeado ({len(fora)}) são omitidas; '
               f'as com cobertura menor aparecem só na tabela abaixo. Resultado: {len(ret)} tela(s) mantida(s), {len(fu["ordem"]) - len(ret)} omitida(s) por cobertura baixa, {len(fora)} omitida(s) sem programa.')]
    todas_usadas = set().union(*[fu['direto'][j] | fu['bean'][j] for j in ret]) if ret else set()
    sobra = [p for p in L if p not in todas_usadas]
    bl.append(rm.X('Programas analisados que nenhuma tela mantida usa: ' + (', '.join(sobra) if sobra else 'nenhum (as telas mantidas, juntas, usam todos os programas do universo).')))
    if ret:
        nos, arestas, vistos = [], [], set()
        for j in ret:
            nos.append({'id': 't-' + j, 'col': 0, 'label': curto(nome_tela(j), 34), 'sub': f'{len(fu["direto"][j] | fu["bean"][j])}/{n} programas', 'detail': j, 'cor': COR_TELA})
            for pn in sorted(fu['proc_direto'][j] | fu['proc_bean'][j]):
                if 'p-' + pn not in vistos:
                    vistos.add('p-' + pn)
                    nos.append({'id': 'p-' + pn, 'col': 1, 'label': curto(pn.split('.')[-1], 34), 'sub': 'processo PDC · ' + ', '.join(an[pn]['transacoes']), 'detail': pn, 'cor': COR_PROCESSO})
                    for pg in an[pn]['programas']:
                        if 'g-' + pg not in vistos:
                            vistos.add('g-' + pg)
                            nos.append({'id': 'g-' + pg, 'col': 2, 'label': pg, 'sub': 'programa · ' + sit_txt.get(pg, G.NAO), 'detail': pg, 'cor': COR_CLASSE['COORDENADOR'], 'inactive': sit_txt.get(pg, G.NAO) != G.EXEC})
                        arestas.append({'from': 'p-' + pn, 'to': 'g-' + pg})
                arestas.append({'from': 't-' + j, 'to': 'p-' + pn})
        bl.append(legenda(rs._grafo('Telas → Processos → Programas', ['Tela', 'Processo PDC', 'Programa mainframe'], nos, arestas,
                                    'Cada seta vai da tela para o processo que ela usa e do processo para o programa da transação. Programa apagado = não executado na análise dinâmica.', nw=250),
                          [('Tela', COR_TELA), ('Processo PDC', COR_PROCESSO), ('Programa mainframe (coordenador)', COR_CLASSE['COORDENADOR'])]))
        trel = []
        for j in ret:
            for pn in sorted(fu['proc_direto'][j] | fu['proc_bean'][j]):
                d_ = dets.get(pn)
                servs = sorted({f'{s_["classe"]}.{s_["metodo"]}' for s_ in d_['servicos']}) if d_ else []
                trel.append((nome_tela(j), pn, ', '.join(an[pn]['transacoes']), ', '.join(an[pn]['programas']), ', '.join(sit_txt.get(pg, G.NAO) for pg in an[pn]['programas']),
                             'direta (campo ou botão)' if pn in fu['proc_direto'][j] else 'só por managed bean', ', '.join(servs) or '—', ', '.join(d_['beans']) if d_ else '—'))
        bl.append(rm.T('Telas → Processos → Programas', ['Tela', 'Processo', 'Transação', 'Programa mainframe', 'Execução', 'Relação com a tela', 'Serviços', 'Managed beans'], trel,
                       'Telas mantidas no funil e os processos PDC que elas usam, com o programa mainframe de cada transação (só programas da fase pdc-mapping).'))
    bl.append(rm.T('Cobertura de programas por tela', ['Tela', 'Situação no funil', 'Programas (relação direta)', 'Programas (direta + bean)', 'Programas que a tela usa',
                                                     'Analisados que a tela não usa', 'Usados mas não executados', 'Usados só por bean (sem campo/ação)', 'Processos da tela sem programa mapeado'], linhas,
                   'Programas "usados mas não executados" e "analisados que a tela não usa" são os pontos de atenção da cobertura. A última coluna conta processos que a tela usa mas que não têm programa na fase pdc-mapping (ignorados).'))
    if fora:
        bl.append(rm.X(f'{len(fora)} tela(s) usam managed beans que chegam a processos, mas nenhum com programa mapeado na fase pdc-mapping; foram omitidas do relatório.'))
    return rm.S('funil', 'Funil de telas por cobertura de programas', bl, 'Afunilamento por dedução: só telas ligadas aos programas analisados e executados da fase pdc-mapping.')


# ------------------------------------------------------------------ eventos e origem dos dados (quando e por que cada combo/tabela/campo é carregado)
NORM_EVENTO = {'onclick': 'onClick', 'onchange': 'onChange', 'onselect': 'onSelect', 'onblur': 'onBlur', 'onfocus': 'onFocus', 'onkeyup': 'onKeyUp', 'onkeydown': 'onKeyDown', 'onsubmit': 'onSubmit',
               'ondblclick': 'onDblClick', 'oncomplete': 'onComplete', 'onmouseover': 'onMouseOver', 'prerenderview': 'onLoad', 'postaddtoview': 'onLoad', 'clique': 'onClick',
               'alteração do valor': 'onChange (valor alterado)', 'temporizador (poll)': 'poll (temporizador)'}


def rot_comp(idx, jsp, ordem):
    j = idx['jsps'][jsp]
    c = j['componentes'][ordem]
    v = c['visual']
    r = A.rotulo_do_componente(idx, jsp, ordem) if v in A.ENTRADA_VIS | {'rótulo / texto', 'coluna da listagem'} else A.texto_rotulo(idx, c['atributos'].get('value', '')) if v in ('botão', 'link') else ''
    return r or c['id'] or c['tag']


def evento_norm(e):
    ev = e['evento']
    n = NORM_EVENTO.get(ev.lower(), ev)
    if n == 'onClick' and not e['ajax']:
        return 'onClick → onSubmit (envio do formulário)'
    return n


def gatilhos(idx, f0, n0, profundidade=5):
    """Quem faz o método do bean rodar: evento de componente da tela, ciclo de vida do bean (construtor / @PostConstruct), getter lido na renderização. Sobe pelos chamadores até achar."""
    ev = A.indice_eventos(idx)
    cache_get = idx.setdefault('_getter_usado', {})
    vistos, nivel, todos = {(f0, n0)}, [((f0, n0), [(f0, n0)])], []
    for _ in range(profundidade + 1):
        prox = []
        for (f, n), cad in nivel:
            txt = [f'{idx["classes"][x]["nome"]}.{y}' for x, y in cad]
            cls = [x for x, _y in cad]
            beans = bean_de_classe(idx, f)
            achou = False
            for b in beans:
                for e in ev.get((b, n), []):
                    achou = True
                    todos.append({'tipo': 'evento', 'e': e, 'bean': b, 'handler': f'{b}.{n}', 'cadeia': txt, 'classes': cls})
            cv = A.ciclo_vida(idx, f)
            if n in cv['posconstruct'] or n in cv['construtor']:
                achou = True
                todos.append({'tipo': 'abertura', 'origem': '@PostConstruct do bean' if n in cv['posconstruct'] else 'construtor do bean (criação ao abrir a tela)', 'bean': beans[0] if beans else '',
                              'handler': f'{idx["classes"][f]["nome"]}.{n}', 'cadeia': txt, 'classes': cls})
            if n.startswith('get') and len(n) > 3:
                prop = n[3].lower() + n[4:]
                for b in beans:
                    chave = (b, prop)
                    if chave not in cache_get:
                        rx = re.compile(r'\b' + re.escape(b) + r'\.(?:\w+\.)*' + re.escape(prop) + r'\b')
                        cache_get[chave] = any(rx.search(' '.join(c['atributos'].values())) for jp in jsps_do_bean(idx, b) for c in idx['jsps'][jp]['componentes'])
                    if cache_get[chave]:
                        achou = True
                        todos.append({'tipo': 'abertura', 'origem': f'getter {n}() lido na renderização', 'bean': b, 'handler': f'{b}.{n}', 'cadeia': txt, 'classes': cls})
            chamam = A.chamadores(idx, f, n)
            if not chamam and not achou and beans:
                abre = re.search(r'abrir|pagina|inicializ|init|carreg', n, re.I)
                todos.append({'tipo': 'abertura' if abre else 'entrada', 'origem': f'método de entrada {n}() sem chamador no código analisado (chamado pelo menu/navegação fora da aplicação ou pelo framework)', 'bean': beans[0],
                              'handler': f'{beans[0]}.{n}', 'cadeia': txt, 'classes': cls})
            for c in chamam:
                if c not in vistos:
                    vistos.add(c)
                    prox.append((c, cad + [c]))
        nivel = prox
        if not nivel:
            break
    return todos


def ancestral_listagem(j, ordem):
    k = j['componentes'][ordem]['pai']
    while k is not None:
        if j['componentes'][k]['visual'] == 'listagem (tabela)':
            return k
        k = j['componentes'][k]['pai']
    return None


def origem_dados(idx, dets, an, telas_ok):
    """Por tela mantida: dados carregados (combo, tabela, campo de saída) com o gatilho, e os eventos agrupados (disparador, afetados, beans)."""
    dados, eventos = defaultdict(list), defaultdict(dict)
    for pnome, d in dets.items():
        r = an[pnome]
        grupos = defaultdict(list)
        for c in d['campos']:
            if c['tela'] != '—' and c['direcao'] == 'saída' and c['ordem'] is not None:
                lst = ancestral_listagem(idx['jsps'][c['tela']], c['ordem'])
                grupos[(c['tela'], lst if lst is not None else c['ordem'])].append(c)
        for (jsp, ordem), cs in grupos.items():
            j = idx['jsps'][jsp]
            comp = j['componentes'][ordem]
            lista = ancestral_listagem(j, ordem)
            if comp['visual'] == 'listagem (tabela)':
                lista = ordem
            tipo = 'combo (opções)' if (comp['visual'] == 'combobox' or A.liga_jsp(idx, jsp)[ordem]['opcoes']) else 'tabela' if lista is not None else 'campo de saída'
            alvo_ord = lista if (tipo == 'tabela') else ordem
            rotulo = rot_comp(idx, jsp, alvo_ord)
            if tipo == 'tabela':
                cols = sorted({c_['rotulo'] for c_ in cs if c_['rotulo']})
                rotulo = f'{rotulo} (colunas: {", ".join(cols[:6])}{"…" if len(cols) > 6 else ""})' if cols else rotulo
            val = A.liga_jsp(idx, jsp)[alvo_ord]['valor']
            if val and val.get('bean') in idx['beans']:
                bean, tail = val['bean'], val['caminho']
                tail = tail[len(bean) + 1:] if tail.startswith(bean + '.') else tail
            else:
                bean = re.sub(r'^[#$]?\{?\s*', '', cs[0]['el']).split('.')[0]
                tail = '.'.join(re.sub(r'^[#$]?\{?\s*', '', cs[0]['el']).split('.')[1:])
            loaders = [cm for cm in d['caminhos'] if cm['bean'] == bean]
            fino = [cm for cm in loaders if any(a_ and (tail == a_ or tail.startswith(a_ + '.') or tail.startswith(a_ + '[]') or a_.startswith(tail)) for a_ in cm['alvo'])]
            loaders = fino or loaders
            programas = sorted({c_['programa'] for c_ in cs})
            lays = sorted({c_['campo_layout'] for c_ in cs if c_['campo_layout']})
            quando = []
            for cm in sorted(loaders, key=lambda x: x['metodo']):
                for g in gatilhos(idx, cm['fqn'], cm['metodo']) or [{'tipo': 'indef', 'handler': f'{cm["bean"]}.{cm["metodo"]}', 'cadeia': [f'{cm["bean"]}.{cm["metodo"]}'], 'classes': [cm['fqn']]}]:
                    quando.append((cm, g))
                    if g['tipo'] == 'evento':
                        e = g['e']
                        chave = (evento_norm(e), e['jsp'], e['ordem'], g['handler'])
                        dono = e['jsp'] if e['jsp'] in telas_ok else jsp
                        ev_ = eventos[dono].setdefault(chave, {'evento': evento_norm(e), 'jsp_disp': e['jsp'], 'disparador': rot_comp(idx, e['jsp'], e['alvo']) + (f' ({idx["jsps"][e["jsp"]]["componentes"][e["ordem"]]["tag"]})' if e['ajax'] else ''),
                                                              'atributo': e['atributo'], 'handler': g['handler'], 'beans': set(), 'afeta': set(), 'rerender': set(), 'procs': set(), 'cadeias': set()})
                        ev_['rerender'] |= {x for x in re.split(r'[\s,]+', e['rerender'] or '') if x}
                    else:
                        origem = g.get('origem', 'sem gatilho encontrado (sem chamador nem evento na tela)')
                        chave = ('onLoad', jsp, None, g['handler'] + '|' + origem)
                        ev_ = eventos[jsp].setdefault(chave, {'evento': 'onLoad' if g['tipo'] == 'abertura' else 'entrada externa (menu/navegação)', 'jsp_disp': jsp, 'disparador': origem, 'atributo': '—', 'handler': g['handler'],
                                                              'beans': set(), 'afeta': set(), 'rerender': set(), 'procs': set(), 'cadeias': set()})
                    ids_ = {g['bean']} if g.get('bean') else set()
                    ev_['beans'] |= ids_ | {idx['classes'][x]['nome'] for x in g['classes'] if idx['classes'][x]['nome'].lower() not in {i.lower() for i in ids_}}
                    ev_['afeta'].add(f'{rotulo} [{tipo}]' + ('' if ev_['jsp_disp'] == jsp else f' na tela {nome_tela(jsp)} (após navegação)'))
                    ev_['procs'].add(f'{pnome.split(".")[-1]} ({", ".join(programas)})')
                    ev_['cadeias'].add(' → '.join(g['cadeia']))
            def txt_quando(g):
                if g['tipo'] == 'evento':
                    e = g['e']
                    return f'{evento_norm(e)} em «{rot_comp(idx, e["jsp"], e["alvo"])}»' + ('' if e['jsp'] == jsp else f' da tela {nome_tela(e["jsp"])} (navegação)')
                return ('onLoad — ' if g['tipo'] == 'abertura' else 'entrada externa — ') + g.get('origem', 'sem gatilho encontrado') if g['tipo'] in ('abertura', 'entrada') else 'não determinado (sem chamador nem evento na tela)'
            dados[jsp].append((rotulo, tipo, f'{pnome.split(".")[-1]} → {", ".join(sorted({c_["transacao"] for c_ in cs}))} → {", ".join(programas)}', ', '.join(lays) or '—',
                               ', '.join(sorted({f'{cm["bean"]}.{cm["metodo"]}' for cm in loaders})) or '—', ' | '.join(sorted({txt_quando(g) for _cm, g in quando})) or '—',
                               ' | '.join(sorted({' → '.join(g['cadeia']) for _cm, g in quando})) or '—'))
    return dados, eventos


def rotulos_ids(idx, jsp, ids):
    por_id = {c['id']: c['ordem'] for c in idx['jsps'][jsp]['componentes'] if c['id']}
    return [f'{rot_comp(idx, jsp, por_id[i])} ({i})' if i in por_id else i for i in sorted(ids)]


# ------------------------------------------------------------------ regras de apresentação (exibir/ocultar, ativar/desativar, obrigatório, máscara...)
PRES_ATR = {'rendered': 'exibir / ocultar', 'visible': 'exibir / ocultar', 'disabled': 'ativar / desativar', 'enabled': 'ativar / desativar', 'readonly': 'somente leitura',
            'required': 'obrigatoriedade', 'maxlength': 'limite de tamanho', 'mask': 'máscara de entrada', 'converter': 'conversão / formato', 'validator': 'validação', 'requiredmessage': 'mensagem de obrigatoriedade',
            'styleclass': 'estilo condicional', 'style': 'estilo condicional'}
PRES_JS = ('onkeypress', 'onkeyup', 'onkeydown', 'onblur', 'onfocus', 'onchange', 'oninput', 'onpaste')


def onde_muda(idx, bean, dono, prop):
    """Onde a propriedade que comanda a regra recebe valor: métodos que chamam setProp(...) (valor atribuído e condição `if` mais próxima) e getter calculado."""
    cls = {f_ for f_, c in idx['classes'].items() if c['nome'] == dono}
    fb = A.fq(idx, idx['beans'][bean]['classe']) if bean in idx['beans'] else None
    if fb:
        cls.add(fb)
    cap = IX.CAP(prop)
    out = []
    for f_ in sorted(cls):
        c = idx['classes'][f_]
        for n, ms in c['metodos'].items():
            for m in ms:
                corpo = m.get('corpo', '')
                if n in ('set' + cap, 'get' + cap, 'is' + cap):
                    if n != 'set' + cap and not re.fullmatch(r'\{\s*return\s+(?:this\.)?\w+\s*;\s*\}', corpo.strip()):
                        out.append(f'{c["nome"]}.{n}() calcula: {" ".join(corpo.split())[:120]}')
                    continue
                for mm in re.finditer(r'\bset' + re.escape(cap) + r'\s*\(', corpo):
                    arg = " ".join(A.chamada_ate(corpo, mm.end() - 1).split())[:50]
                    cond = re.findall(r'if\s*\(([^{};]*?)\)\s*\{?[^{};]*$', corpo[:mm.start()])
                    out.append(f'{c["nome"]}.{n} → {arg}' + (f' (se {" ".join(cond[-1].split())[:70]})' if cond else ''))
    return sorted(set(out))


def regras_apresentacao(idx, jsp):
    """Linhas da tabela de regras de apresentação de uma tela."""
    j = idx['jsps'][jsp]
    env = A.ambientes(idx, j)
    comps = j['componentes']
    filhos = defaultdict(list)
    for c in comps:
        if c['pai'] is not None:
            filhos[c['pai']].append(c['ordem'])

    def desc(o):
        out, pilha = [], list(filhos[o])
        while pilha:
            k = pilha.pop(0)
            out.append(k)
            pilha += filhos[k]
        return out
    linhas = []
    for c in comps:
        a = c['atributos']
        tag = c['tag'].lower()
        for atr, valor in a.items():
            chave = atr.lower()
            if chave in PRES_ATR:
                tipo = PRES_ATR[chave]
                el = IX.EL.findall(valor)
                if chave in ('style', 'styleclass') and not el:
                    continue
                if chave == 'maxlength':
                    pass
            elif chave in PRES_JS and not tag.startswith(('a4j:', 'f:', 'rich:')) and valor.strip():
                tipo, el = 'script no navegador (máscara / restrição de entrada)', []
            else:
                continue
            cond, onde = '', []
            if el:
                r_ = A.resolver_el(idx, el[0], env[c['ordem']])
                cond = f'{r_["bean"]}.{r_["caminho"]}' if r_ else el[0].strip()
                if r_ and r_.get('dono') and r_.get('prop'):
                    onde = onde_muda(idx, r_['bean'], A.base(r_['dono']), r_['prop'])
            elif chave in ('rendered', 'visible', 'disabled', 'enabled', 'readonly', 'required'):
                cond = 'valor fixo'
            ds = desc(c['ordem'])
            afeta = ''
            if ds and c['visual'] in ('contêiner', 'grade de layout', 'outro', 'listagem (tabela)', 'abas / painel recolhível'):
                nomes = [rot_comp(idx, jsp, k) for k in ds if comps[k]['visual'] in A.ENTRADA_VIS | {'botão', 'link', 'rótulo / texto', 'coluna da listagem'}][:5]
                afeta = f'{len(ds)} componente(s) dentro' + (': ' + ', '.join(nomes) if nomes else '')
            linhas.append((rot_comp(idx, jsp, c['ordem']), f'{c["tag"]}' + (f' ({c["id"]})' if c['id'] else ''), tipo, atr, valor.strip()[:90], cond or '—', ' | '.join(onde[:6]) or ('—' if el else 'não depende de bean'), afeta or '—'))
    return linhas


def modelo(idx, an, dets, corr, sit, interp=None, origens=None):
    L = rm.link
    total = len(an)
    ligados = [r for r in an.values() if r['adaptadores']]
    com_servico = [r for r in an.values() if any(c['servico'] for c in r['cadeias'])]
    com_bean = [r for r in an.values() if r['beans']]
    det_l = [r for r in an.values() if r['detalhe'] and r['adaptadores']]
    secs = []
    fu = funil(an, dets, corr, sit)
    aplicar_funil(dets, fu)
    det_l = [r for r in det_l if dets[r['processo']]['telas']]   # processo sem relação com tela mantida é omitido
    # ---- cobertura
    nt = set()
    for d in dets.values():
        nt |= set(d['telas'])
    linhas_cob = []
    for r in sorted(det_l, key=lambda r: r['processo']):
        d = dets[r['processo']]
        servs = sorted({f'{s["classe"]}.{s["metodo"]}' for s in d['servicos']})
        linhas_cob.append((r['processo'], ', '.join(r['transacoes']), ', '.join(r['programas']), ', '.join(servs), len(d['beans']), len(d['telas']), sum(1 for c in d['campos'] if c['tela'] != '—'),
                           sum(1 for c in d['campos'] if c['tela'] == '—')))
    cards = [rm.card('processos PDC', total), rm.card('com adaptador na aplicação', len(ligados)), rm.card('chamados por serviço', len(com_servico)), rm.card('chegam a managed bean', len(com_bean)),
             rm.card('processos detalhados (programa executado)', len(det_l)), rm.card('telas mantidas no funil', len(fu['mantidas'])), rm.card('telas omitidas (sem programa ou cobertura baixa)', len(fu['omitidas_sem_programa']) + len(fu['ordem']) - len(fu['mantidas'])), rm.card('JSP na aplicação', len(idx['jsps'])),
             rm.card('campos de tela ligados a campos de transação', sum(1 for d in dets.values() for c in d['campos'] if c['tela'] != '—' and c['campo_layout']))]
    secs.append(secao_funil(idx, an, fu, sit, dets))
    # ---- processos detalhados
    for r in sorted(det_l, key=lambda r: r['processo']):
        d = dets[r['processo']]
        bl = []
        servs = d['servicos']
        bl.append(rm.X(f'Processo {r["processo"]} (versão do PDC usada: {d.get("versao_usada", "") or "—"}). Transação {", ".join(r["transacoes"])}, programa {", ".join(r["programas"])}. '
                       f'Serviço: {", ".join(sorted({s["classe"] + "." + s["metodo"] for s in servs})) or "—"}. {len(d["beans"])} managed bean(s), {len(d["telas"])} tela(s) com relação direta.'))
        g = grafo_caminho(idx, d, r)
        bl.append(g)
        if d['caminhos']:
            bl.append(rm.T('Caminho no backend: managed bean até o serviço', ['Managed bean', 'Método do bean', 'Cadeia de chamadas até o serviço', 'Onde o bean guarda o retorno', 'Argumentos passados'],
                           [(c['bean'], c['metodo'], ' → '.join(f'{x}.{y}' for x, y in c['caminho']), ', '.join(c['alvo']) or '—', ' | '.join(', '.join(a) for a in c['args']) or '—') for c in sorted(d['caminhos'], key=lambda c: (c['bean'], c['metodo']))]))
        bl.extend(grafo_campos(d, r))
        bl.append(rm.T('Campos: tela ↔ propriedade ↔ campo do processo ↔ campo da transação',
                       ['Tela', 'Componente', 'Id', 'Rótulo', 'Ligação (EL)', 'Direção', 'Propriedade (VO)', 'Campo do processo', 'Transação', 'Campo do layout', 'PIC', 'Bytes', 'Programa'],
                       [(nome_tela(c['tela']) if c['tela'] != '—' else '—', c['visual'] or '—', c['id'], c['rotulo'], c['el'], c['direcao'], c['vo'], c['elemento'], c['transacao'], c['campo_layout'] or '—', c['pic'], c['bytes'], c['programa'])
                        for c in sorted(d['campos'], key=lambda c: (c['tela'] == '—', c['tela'], c['direcao'], c['elemento']))],
                       'Tela "—" = o campo do serviço não tem componente de tela relacionado (valor fixo ou derivado no serviço, ou propriedade que a tela não exibe).'))
        secs.append(rm.S('proc-' + norm(r['processo']), f'Processo {r["processo"]}', bl))
    # ---- telas
    tl = []
    todas_telas = sorted(nt)
    ligados_tela = defaultdict(lambda: defaultdict(list))
    for p, d in dets.items():
        for c in d['campos']:
            if c['tela'] != '—' and c['ordem'] is not None:
                ligados_tela[c['tela']][c['ordem']].append(f'{p.split(".")[-1]}: {fluxo_campo(c)}')
    dados_tela, eventos_tela = origem_dados(idx, dets, an, set(todas_telas))
    for jsp, itens in (origens or {}).items():   # campos de processos sem programa analisado, confirmados com fontes entregues depois
        for ordem, o in itens:
            ligados_tela[jsp][ordem].append(o['relacao'])
            dados_tela[jsp].append((o['componente'], o['tipo'], o['processos'], o['campos_layout'], o['metodo'], o['quando'], o['cadeia']))
    for jsp in todas_telas:
        j = idx['jsps'][jsp]
        info = tela_info(idx, jsp)
        acoes = []
        for p, d in dets.items():
            t = d['telas'].get(jsp)
            if t:
                for ordem, bean, n in t['acoes']:
                    acoes.append((ordem, f'{bean}.{n}', p.split('.')[-1]))
        arv = A.arvore_tela(idx, jsp, {o: v for o, v in ligados_tela[jsp].items()})
        tl.append({'type': 'wire', 'title': f'Tela {nome_tela(jsp)}', 'arvore': arv, 'arquivo': jsp, 'tiles': info['tiles'],
                   'note': 'Wireframe da disposição: grades de layout aparecem com suas colunas; o selo mostra a ligação com a propriedade e a transação mainframe.'})
        liga = A.liga_jsp(idx, jsp)
        rows = []
        for c in j['componentes']:
            if c['visual'] in ('núcleo',) and not liga[c['ordem']]['opcoes']:
                continue
            if c['visual'] in ('contêiner', 'outro') and not (liga[c['ordem']]['valor'] or liga[c['ordem']]['acao']):
                continue
            pos = A.posicao_na_grade(j, c['ordem'])
            v = liga[c['ordem']]
            rows.append((c['ordem'], '  ' * min(c['nivel'], 6) + c['visual'] + (' (opções)' if v['opcoes'] else ''), c['tag'], c['id'], A.rotulo_do_componente(idx, jsp, c['ordem']) if c['visual'] in A.ENTRADA_VIS | {'rótulo / texto', 'coluna da listagem'} else A.texto_rotulo(idx, c['atributos'].get('value', '')) if c['visual'] in ('botão', 'link') else '',
                         (v['valor'] or {}).get('expressao', ''), f'linha {pos[0]}, coluna {pos[1]} de {pos[2]}' if pos else '—', f'{v["acao"]["bean"]}.{v["acao"]["metodo"]}' if v['acao'] else '',
                         ' | '.join(ligados_tela[jsp].get(c['ordem'], [])) or '—', '; '.join(A.opcoes_fixas(idx, jsp, c['ordem'])) or '—'))
        tl.append(rm.T(f'Componentes de {nome_tela(jsp)}', ['#', 'Componente', 'Tag', 'Id', 'Rótulo / texto', 'Ligação (EL)', 'Posição na grade', 'Ação', 'Relação com a transação', 'Opções fixas (valor = texto)'], rows,
                       'Opções fixas: itens <f:selectItem> do próprio combo (valor enviado = texto exibido); as opções carregadas por um processo aparecem como (opções) nas tabelas de campos.'))
        evs = sorted(eventos_tela.get(jsp, {}).values(), key=lambda e: (0 if e['evento'] == 'onLoad' else 1, e['evento'], e['disparador']))
        if evs:
            tl.append(rm.T(f'Eventos de {nome_tela(jsp)}', ['Evento', 'Componente que dispara', 'Atributo', 'Método do bean acionado', 'Beans relacionados', 'Componentes afetados (dados carregados)', 'Atualizados na tela (reRender)', 'Processo (programa)', 'Cadeia de chamadas'],
                           [(e['evento'], e['disparador'], e['atributo'], e['handler'], ', '.join(sorted(e['beans'])) or '—', ' | '.join(sorted(e['afeta'])), ', '.join(rotulos_ids(idx, e['jsp_disp'], e['rerender'])) or '—',
                             ' | '.join(sorted(e['procs'])), ' | '.join(sorted(e['cadeias']))) for e in evs],
                           'Eventos que fazem a tela carregar dados dos processos analisados: onLoad = ao abrir a tela (construtor/@PostConstruct do bean ou getter lido na renderização); onClick/onSubmit = botão ou link; onChange/onSelect = evento ajax do campo.'))
        reg = regras_apresentacao(idx, jsp)
        if reg:
            tl.append(rm.T(f'Regras de apresentação de {nome_tela(jsp)}', ['Componente', 'Tag (id)', 'Tipo de regra', 'Atributo', 'Expressão ou valor', 'Propriedade que comanda a regra', 'Onde a propriedade muda (método → valor atribuído)', 'Componentes afetados'],
                           reg, 'Regras que escondem/exibem, ativam/desativam ou restringem componentes: atributos rendered, disabled, readonly, required, maxlength, máscaras em script e estilos condicionais. Quem comanda a regra é a propriedade do bean; a coluna seguinte mostra onde ela recebe valor (se = condição mais próxima, aproximada).'))
        if dados_tela.get(jsp):
            tl.append(rm.T(f'Origem dos dados de {nome_tela(jsp)}', ['Componente', 'Tipo', 'Processo → transação → programa', 'Campos do layout', 'Método do bean que carrega', 'Quando é carregado (evento)', 'Cadeia de chamadas'],
                           sorted(dados_tela[jsp], key=lambda x: (x[1], x[0])), ' '.join(['Combos, tabelas e campos de saída com a origem (processo/transação/programa) e o evento que provoca a carga.']
                                                                                         + [o['nota'] for _o, o in (origens or {}).get(jsp, []) if o.get('nota')])))
    if tl:
        secs.append(rm.S('telas', 'Telas: disposição, componentes e campos', tl))
    telas_info = {nome_tela(jsp): {'jsp': jsp} for jsp in todas_telas}
    if interp is not None:
        erros = validar_interp(interp, {nome: chaves_tela(idx, i['jsp']) for nome, i in telas_info.items()}, [r['processo'] for r in det_l])
        if erros:
            sys.exit('interpretação inválida (' + str(len(erros)) + '):\n' + '\n'.join(erros[:60]))
        secs.append(secao_interp(idx, interp, telas_info, ligados_tela, {r['processo'] for r in det_l}))
    # ---- endpoints
    er = []
    for jsp in todas_telas:
        info = tela_info(idx, jsp)
        destinos = sorted({x for d in dets.values() for x in (d['telas'].get(jsp, {}).get('destinos') or [])})
        entradas = sorted({f'{n["de"]} --{n["resultado"] or n["acao"]}--> {n["para"]}' for n in info['navegacao']})
        er.append((nome_tela(jsp), ', '.join(ordenar_tiles(jsp, info, destinos)[:5]) or '—', '; '.join(entradas[:4]) or '—', '; '.join(f'{a} → {res} → {pg}' for a, res, pg in destinos[:4]) or '—', '; '.join(sorted({p.get("padrao", "") for p in idx['web']['padroes']})) or '—'))
    secs.append(rm.S('endpoints', 'Endpoints: tiles, navegação e padrões de URL', [rm.T('Endpoints das telas relacionadas', ['Tela', 'Tile(s)', 'Chegada (regras de navegação)', 'Saída (ação → resultado → destino)', 'Padrões de URL do servlet'], er)] if er else [rm.X('Nenhuma tela relacionada.')],
                    'Endpoint = o tile (ou view-id) que exibe a JSP; a URL é o view-id com um dos padrões do servlet (web.xml).'))
    # ---- relação leve
    lin = []
    for nome, r in sorted(an.items()):
        if not r['telas_bean']:
            continue   # processo sem relação com telas é omitido
        servs = sorted({f'{idx["classes"][f]["nome"]}.{n}' for c in r['cadeias'] for f, n in c['servico']})
        beans = sorted(r['beans'])
        lin.append((nome, ', '.join(r['transacoes']), ', '.join(r['programas']) or '—', 'sim' if r['executado'] else 'não', ', '.join(r['adaptadores']) or '—', ', '.join(servs[:3]) or '—', ', '.join(beans[:3]) + (f' (+{len(beans) - 3})' if len(beans) > 3 else '') or '—',
                    len(r['telas_bean']), ', '.join(nome_tela(t) for t in r['telas_bean'][:3]) or '—'))
    cols = ['Processo', 'Transação', 'Programa mainframe', 'Programa executado', 'Adaptador', 'Serviço (classe.método)', 'Managed beans', 'Telas', 'Exemplos de tela']
    analisados = [x for x in lin if x[2] != '—']   # processo cujo programa mainframe está entre os analisados
    nao_analisados = [x for x in lin if x[2] == '—']
    titulo = 'Processo → transação → programa → adaptador → serviço → bean → telas'
    secs.append(rm.S('relacao', 'Relação de todos os processos: classes e telas', [
        rm.T(f'{titulo}: processos analisados', cols, analisados,
             note=f'{len(analisados)} processo(s) cujo programa mainframe foi analisado; Programa executado diz se a análise dinâmica o executou.'),
        rm.T(f'{titulo}: processos não analisados', cols, nao_analisados,
             note=f'{len(nao_analisados)} processo(s) cujo programa mainframe não está entre os fontes analisados (ver os processos fora da análise na fase 14).')],
        'Relação leve para todos os processos: telas = JSP que usam algum managed bean que chega ao serviço do processo (relação por bean; a relação direta campo a campo só existe para os processos detalhados).'))
    # a relação de todos os processos abre o relatório; a lista de processos sem tela não é mais gerada
    secs.sort(key=lambda x: 0 if x['id'] == 'relacao' else 1)
    return secs, cards, det_l


def main():
    args = sys.argv[1:]
    opcoes = {}
    for k in ('--aplicacao', '--pdc', '--interpretacao', '--cache', '--limite'):
        if k in args:
            i = args.index(k)
            opcoes[k] = args[i + 1]
            del args[i:i + 2]
    if not args or '--aplicacao' not in opcoes or '--pdc' not in opcoes:
        sys.exit(__doc__)
    global BASE
    if '--interpretacao' in opcoes:
        BASE = Path(opcoes['--interpretacao']).resolve()
    ana = Path(args[0])
    saida = Path(args[1]) if len(args) > 1 else ana
    S.definir_copybooks(ana)
    idx = indexar(opcoes['--aplicacao'], opcoes.get('--cache'), int(opcoes.get('--limite', 150)))
    if idx is None:
        sys.exit('indexação parcial: rode de novo para continuar')
    procs, n_arq = G.ler_pdc(opcoes['--pdc'])
    classe, sit, motivo, copy, ep = G.ler_analise(ana)
    corr = G.correlacionar(procs, classe, copy)
    an = analisar(idx, procs, corr, sit, opcoes['--pdc'])
    dets = {nome: detalhar(idx, r, corr, sit, opcoes['--pdc']) for nome, r in an.items() if r['detalhe'] and r['adaptadores']}
    interp = ler_interp(BASE)
    secs, cards, det_l = modelo(idx, an, dets, corr, sit, interp, ler_origens(BASE, idx))
    mod = rm.model('Interfaces com o Usuário', 'Do processo PDC às classes, métodos, endpoints e telas da aplicação, e dos campos da tela aos campos da transação mainframe.', cards, secs)
    S.escrever(saida, FASE, mod)
    print(f'{len(an)} processos, {len(det_l)} detalhados; {sum(len(d["campos"]) for d in dets.values())} linhas de campo; índice em {idx["segundos"]}s')


if __name__ == '__main__':
    main()
