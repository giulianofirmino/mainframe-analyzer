#!/usr/bin/env python3
"""Relatório business-flows: funcionalidades e fluxos de negócio por entry point, lidos ÚNICA E EXCLUSIVAMENTE dos relatórios gerados
(<fase>/ia/report.json das fases 0, 1, 5, 6 e 7).

  python3 gerar_fluxos.py <pasta-da-analise> [pasta-de-saida] [--interpretacao PASTA]   (padrão da saída: a pasta da análise)

Saída: <saida>/12 - business-flows/human/report.html e <saida>/12 - business-flows/ia/report.json (o mesmo modelo de visão, como as fases da análise).
Evidência calculada pelo script: por entry point, os programas que ele alcança (com caminho de chamada e classe da fase 0), tabelas gravadas e
consultadas, regras por tipo, retornos observados, entradas e cenários da fase 7, cobertura. A interpretação (interpretacao-fluxos/funcionalidades.json)
dá nome, resumo, passos e fluxos de negócio; o script confere que todo entry point foi descrito, que cada literal citado existe na evidência e que os
cenários citados existem. Mesma entrada, mesma saída."""
import ast
import html
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import gerar_simulacao as S
import report_model as rm  # noqa: E402
import gerar_sql as Q  # noqa: E402   (mapeamento SQL da fase 10: consultas dinâmicas)

E = html.escape
AQUI = Path(__file__).resolve().parent
VERBO = re.compile(r'^[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+(ar|er|ir|or|ôr)$')
BASE = Path(os.environ['ANALISE_INTERPRETACOES']) if os.environ.get('ANALISE_INTERPRETACOES') else AQUI   # pasta das interpretações (a análise); o pipeline a informa


def coletar(ana):
    """Tudo que o relatório de fluxos usa, lido das fases 0, 1, 6 e 7."""
    f0, f1, f2, f5, f6 = S.fase(ana, '00-'), S.fase(ana, '01-'), S.fase(ana, '05-'), S.fase(ana, '06-'), S.fase(ana, '07-')
    classe = {r['Programa']: r['Classe'] for _s, _b, rs in S.tabelas(f0) for r in rs if 'Classe' in r and 'Programa' in r}
    regras, cob, cen = [], {}, []
    for st, bt, rs in S.tabelas(f5):
        if st.startswith('Regras — ') and bt.startswith('Regras de '):
            for r in rs:
                r['programa'] = st.split(' — ', 1)[1]
                regras.append(r)
    mapa = [(st.split(' — ', 1)[1], r) for st, bt, rs in S.tabelas(f2) if st.startswith('Mapa de decisão — ') for r in rs]
    ramos = [r for st, bt, rs in S.tabelas(f6) if 'Constantes do chamador' in (rs[0] if rs else {}) for r in rs]
    for st, bt, rs in S.tabelas(f6):
        if bt == 'Entry points':
            cob = {r['Entry point']: r for r in rs}
        elif bt == 'Cenários':
            cen = rs
    chamadas = [r for _s, bt, rs in S.tabelas(f1) if bt == 'Todas as chamadas' for r in rs]
    dyn_prog = {r['Programa']: r['Situação'] for _s, bt, rs in S.tabelas(f1) if bt.startswith('Programas: chamados') for r in rs}
    dyn_tab = {r['Tabela']: r['Situação'] for _s, bt, rs in S.tabelas(f1) if bt.startswith('Tabelas: usadas') for r in rs}
    if not dyn_prog or not dyn_tab:
        raise SystemExit('fase 1 sem as tabelas "Programas: chamados ou não" e "Tabelas: usadas ou não": a análise dinâmica não foi executada')
    fluxo = fluxo_de(f1, regras, classe)
    if not fluxo:
        raise SystemExit('fase 1 sem as tabelas "Todas as chamadas" e "Recursos por programa": rode a análise com a versão atual dos scripts')
    alc_prog = {p for p, st in dyn_prog.items() if st != 'não chamado'}
    alc_tab = {t for t, st in dyn_tab.items() if st == 'usada'}
    corp = sorted(p for p, c in classe.items() if c == 'CORPORATIVO' and p in alc_prog)
    din = [r for r in S.regras_dinamicas(Q.carregar_mapeamento(BASE), Q.caixas_efetivas(r_ for _p, r_ in mapa)) if r['programa'] in alc_prog]   # comandos SQL dinâmicos internalizados (fase 10) viram regras do serviço
    return {'classe': classe, 'corp': corp, 'fluxo': fluxo, 'regras': [r for r in regras if r['programa'] in alc_prog] + din, 'cob': cob, 'cen': cen, 'chamadas': chamadas, 'mapa': mapa, 'ramos': ramos,
            'dyn_prog': dyn_prog, 'dyn_tab': dyn_tab, 'alc_prog': alc_prog, 'alc_tab': alc_tab}


def fluxo_de(f1, regras, classe):
    """Linhas (raiz, programa) com o caminho de chamada, as regras e as tabelas de cada programa alcançado, calculadas da fase 1 (chamadas e acesso às tabelas) e 6 (regras).
    Raízes: os entry points (ninguém os chama) e os programas classificados como corporativos na fase 0, que viram funcionalidade própria."""
    progs = [r['Programa'] for _s, bt, rs in S.tabelas(f1) if bt == 'Recursos por programa' for r in rs]
    callees = defaultdict(list)
    called = set()
    for _s, bt, rs in S.tabelas(f1):
        if bt == 'Todas as chamadas':
            for r in rs:
                a, b = r['Programa chamador'], r['Programa chamado']
                if b in progs and b != a:
                    called.add(b)
                    if b not in callees[a]:
                        callees[a].append(b)
    acesso = defaultdict(lambda: ([], []))
    for _s, bt, rs in S.tabelas(f1):
        if bt == 'Acesso por programa e tabela':
            for r in rs:
                ops = set(lista(r['Operações']))
                if ops & {'INSERT', 'UPDATE', 'DELETE', 'MERGE'}:
                    acesso[r['Programa']][0].append(r['Tabela'])
                if ops & {'SELECT', 'FETCH', 'OPEN'}:
                    acesso[r['Programa']][1].append(r['Tabela'])
    por_prog = defaultdict(list)
    for r in regras:
        por_prog[r['programa']].append(r)
    raizes = [p for p in sorted(progs) if p not in called] + [p for p in sorted(progs) if classe.get(p) == 'CORPORATIVO']
    out = []
    for raiz in dict.fromkeys(raizes):
        pai, ordem = {raiz: None}, [raiz]
        for q in ordem:
            for c in sorted(callees[q]):
                if c not in pai:
                    pai[c] = q
                    ordem.append(c)
        for q in ordem:
            caminho, c = [], q
            while c is not None:
                caminho.append(c)
                c = pai[c]
            rs = por_prog.get(q, [])
            corp_no_caminho = [c for c in reversed(caminho[:-1]) if classe.get(c) == 'CORPORATIVO']   # corporativos entre a raiz (excluída) e o programa (incluído)
            out.append({'Via corporativo': 'sim' if corp_no_caminho else 'não', 'Corporativo direto': 'sim' if corp_no_caminho and corp_no_caminho[0] == q else 'não',
                        'Entry point': raiz, 'Programa': q, 'Caminho de chamada': ' → '.join(reversed(caminho)), 'Regras': str(len(rs)),
                        'Regras por tipo': ', '.join(f'{k} {n}' for k, n in sorted(Counter(x['Tipo'] for x in rs).items())),
                        'Tabelas gravadas': ', '.join(sorted(set(acesso[q][0]))), 'Tabelas consultadas': ', '.join(sorted(set(acesso[q][1]))),
                        'Programas chamados nas regras': ', '.join(sorted({c2 for x in rs for c2 in lista(x['Programas chamados'])}))})
    return out


def chave(f):
    """Raiz da funcionalidade: o entry point ou o programa corporativo em que ela se baseia (um programa desdobrado em várias funcionalidades usa programa#id)."""
    return f.get('_chave') or f.get('entry') or f.get('programa')


def _usa(eps, ep, f):
    """`usada_por` pode citar o programa que de fato chama o serviço (o chamador do mapeamento SQL); o entry point cujo fluxo alcança esse programa também a usa."""
    return ep in eps and any(p['programa'] in f.get('usada_por', []) for p in eps[ep]['programas'])


def desdobrar(d, eps, interp):
    """Desdobramento decidido pela IA: um programa corporativo que executa consulta dinâmica e é usado por chamadores com finalidades distintas de negócio vira várias funcionalidades
    (várias entradas de `funcionalidades` com o mesmo `programa`, cada uma com `usada_por` (quem a chama) e `grupos` (as regras de negócio da finalidade que ela atende)).
    Cada uma ganha uma raiz própria `programa#id`, com os mesmos programas alcançados e regras do programa; quem chamava o programa passa a chamar só as funcionalidades de que usa. Devolve os erros."""
    erros = []
    por = defaultdict(list)
    for f in interp['funcionalidades']:
        if f.get('programa'):
            por[f['programa']].append(f)
    for prog, fs in por.items():
        if len(fs) < 2:
            continue
        if prog not in eps:
            erros.append(f'{prog}: funcionalidades desdobradas de programa que não foi alcançado')
            continue
        base = eps.pop(prog)
        d['corp'] = set(d['corp'])   # o programa continua corporativo: as regras dele pertencem às funcionalidades corporativas, nunca às de entry point
        chamadores = [ep for ep, e in eps.items() if prog in e['corp_chamadas']]
        for f in fs:
            if not (f.get('usada_por') and f.get('grupos')):
                erros.append(f'{f.get("id")}: funcionalidade desdobrada do programa {prog} precisa de `usada_por` e `grupos` (as regras de negócio da finalidade que atende)')
                continue
            k = f'{prog}#{f["id"]}'
            f['_chave'] = k
            e = dict(base)
            e['regras'] = list(base['regras'])
            e['tipos'] = Counter(r['Tipo'] for r in e['regras'])
            e['negocio'] = sum(1 for r in e['regras'] if r['Escopo'] == 'negócio' and r['programa'] not in base['infra'])
            e['donos'] = sorted(x for x in base['donos'] if x in f['usada_por'] or _usa(eps, x, f))
            eps[k] = e
            d['corp'].add(k)
        for ep in chamadores:
            eps[ep]['corp_chamadas'].discard(prog)
            novos = [f['_chave'] for f in fs if (ep in f.get('usada_por', []) or _usa(eps, ep, f)) and f.get('_chave')]
            if not novos:
                erros.append(f'{ep} chama {prog}, mas nenhuma funcionalidade desdobrada o lista em usada_por')
            eps[ep]['corp_chamadas'] |= set(novos)
    return erros


def lista(t):
    return [x.strip() for x in t.split(',') if x.strip()]


def dict_texto(t):
    """'a=1; b=2' (coluna Entradas) -> {'a': '1', 'b': '2'}."""
    out = {}
    for p in t.split('; '):
        if '=' in p:
            k, v = p.split('=', 1)
            out[k.strip()] = v.strip()
    return out


def saidas(t):
    """'outputs={...}; calls=[...]; not_calls=[...]' (coluna Saídas esperadas) -> dict de partes."""
    out = {}
    for p in re.split(r'; (?=[a-z_]+=)', t):
        if '=' in p:
            k, v = p.split('=', 1)
            try:
                out[k.strip()] = ast.literal_eval(v)
            except (ValueError, SyntaxError):
                out[k.strip()] = v
    return out


def por_entry(d):
    """Evidência determinística de cada entry point."""
    infra = {p for p, c in d['classe'].items() if c == 'INFRAESTRUTURA'}
    eps = {}
    for r in d['fluxo']:
        if r['Programa'] not in d['alc_prog']:
            continue
        e = eps.setdefault(r['Entry point'], {'programas': [], 'gravadas': set(), 'lidas': set(), 'chamados': set(), 'corp_chamadas': set()})
        via = r.get('Via corporativo') == 'sim'   # programa alcançado por dentro de um corporativo: as tabelas dele pertencem à funcionalidade corporativa
        if r.get('Corporativo direto') == 'sim':
            e['corp_chamadas'].add(r['Programa'])
        e['programas'].append({'via_corp': via, 'tabelas_via': sorted((set(lista(r['Tabelas gravadas'])) | set(lista(r['Tabelas consultadas']))) & d['alc_tab']) if via else [], 'tabelas': [] if via else sorted((set(lista(r['Tabelas gravadas'])) | set(lista(r['Tabelas consultadas']))) & d['alc_tab']), 'situacao': d['dyn_prog'].get(r['Programa'], ''), 'programa': r['Programa'], 'caminho': r['Caminho de chamada'], 'regras': int(r['Regras']), 'tipos': r['Regras por tipo'], 'classe': d['classe'].get(r['Programa'], 'não classificado')})
        if not via:
            e['gravadas'] |= set(lista(r['Tabelas gravadas'])) & d['alc_tab']
            e['lidas'] |= set(lista(r['Tabelas consultadas'])) & d['alc_tab']
        e['chamados'] |= set(lista(r['Programas chamados nas regras'])) & d['alc_prog']
    corp = set(d['corp'])

    def completar(e, regras, cenarios, cob):
        e['regras'] = regras
        e['tipos'] = Counter(r['Tipo'] for r in e['regras'])
        e['negocio'] = sum(1 for r in e['regras'] if r['Escopo'] == 'negócio' and r['programa'] not in infra)
        e['cenarios'] = cenarios
        e['entradas'] = Counter(k for r in e['cenarios'] for k in dict_texto(r['Entradas']))
        ret = Counter()
        for r in e['cenarios']:
            o = saidas(r['Saídas esperadas']).get('outputs', {})
            if isinstance(o, dict):
                for k, v in o.items():
                    if k.endswith('COD-RETORNO'):
                        ret[str(v)] += 1
        e['retornos'] = ret
        e['cob'] = cob
        e['infra'] = infra
        e['negocio_progs'] = [p['programa'] for p in e['programas'] if p['programa'] not in infra]
    for ep, e in eps.items():
        if ep not in corp:
            completar(e, [r for r in d['regras'] if ep in lista(r['Entry points'])], [r for r in d['cen'] if r['Entry point'] == ep], d['cob'].get(ep, {}))
    for ep, e in eps.items():   # funcionalidade de programa corporativo: o que ele alcança, e os cenários dos entry points que o chamam
        if ep in corp:
            alc = {p['programa'] for p in e['programas'] if not p['via_corp']}
            e['donos'] = sorted(x for x, y in eps.items() if x not in corp and any(p['programa'] == ep for p in y['programas']))
            completar(e, [r for r in d['regras'] if r['programa'] in alc], [r for r in d['cen'] if r['Entry point'] in e['donos']], {})
    return eps


def grupos_de(eps):
    """Entry points ligados por tabela gravada por algum deles (componentes conexos) e dados de referência (só lidos)."""
    pai = {ep: ep for ep in eps}

    def raiz(x):
        while pai[x] != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x
    tabelas = sorted({t for e in eps.values() for t in e['gravadas'] | e['lidas']})
    ligacao = {}
    for t in tabelas:
        gr = sorted(ep for ep, e in eps.items() if t in e['gravadas'])
        lei = sorted(ep for ep, e in eps.items() if t in e['lidas'])
        ligacao[t] = (gr, lei)
        if gr:
            for ep in lei + gr:
                pai[raiz(ep)] = raiz(gr[0])
    comp = defaultdict(list)
    for ep in sorted(eps):
        comp[raiz(ep)].append(ep)
    return ligacao, sorted(comp.values(), key=lambda v: (-len(v), v))


def compartilhados(eps):
    """Programas alcançados por mais de um entry point: (programa, entry points, classe)."""
    por = defaultdict(set)
    for ep, e in eps.items():
        for p in e['programas']:
            por[p['programa']].add(ep)
    cls = {p['programa']: p['classe'] for e in eps.values() for p in e['programas']}
    return sorted(((p, sorted(v), cls[p]) for p, v in por.items() if len(v) > 1), key=lambda x: (-len(x[1]), x[0]))


def evidencia(ep, e, d):
    """Texto de evidência de um entry point: onde cada literal citado pela IA precisa existir."""
    partes = [ep, json.dumps(e['programas'], ensure_ascii=False), ' '.join(sorted(e['gravadas'] | e['lidas'])), ' '.join(sorted(e['chamados']))]
    partes += [json.dumps(r, ensure_ascii=False) for r in e['regras']]
    partes += [json.dumps(r, ensure_ascii=False) for r in e['cenarios']]
    prog = {p['programa'] for p in e['programas']}
    partes += [json.dumps(c, ensure_ascii=False) for c in d['chamadas'] if c['Programa chamador'] in prog]
    partes += [r['Condição ou comandos'] for p, r in d['mapa'] if p in prog and 'Condição ou comandos' in r]
    partes += [json.dumps(r, ensure_ascii=False) for r in d['ramos'] if r.get('Entry point') == ep]
    return '\n'.join(partes)


def grupos_do_entry(e, grupos_refs):
    """Grupos de regras da simulação de regras (ids V01...) cujas regras alcançam este entry point."""
    ids = {r['programa'] + ':' + r['Regra'] for r in e['regras']}
    return sorted(g for g, refs in grupos_refs.items() if ids & set(refs))


def carregar_grupos(d):
    """Regras de negócio (interpretacao/*.json), uma por entry point (mesma expansão do relatório business-rules), só para ligar funcionalidade e regra por id."""
    brutos = []
    for f in sorted((BASE / 'interpretacao').glob('*.json')):
        brutos += S.carregar(f).get('grupos', [])
    inst, erros = S.expandir_por_programa(brutos, {r['programa'] + ':' + r['Regra']: lista(r['Entry points']) for r in d['regras']}, S.carregar_compartilhados(), d['corp'])
    if erros:
        raise SystemExit('regras de negócio que cruzam programas:\n  ' + '\n  '.join(erros))
    return {g['id']: g for g in inst}


def rotulo(g):
    """Id exibido: sempre '<código>.<programa>', que mostra de onde a regra vem."""
    return g


def unicos(ids):
    """Ids base sem repetição, na ordem (um id com várias regras de negócio no mesmo entry point aparece uma vez no diagrama)."""
    return list(dict.fromkeys(rotulo(g) for g in ids))


CAT = {'V': 'Validações', 'C': 'Consultas', 'A': 'Alterações', 'D': 'Derivações e valores padrão', 'U': 'Auditoria', 'S': 'Retorno de sucesso', 'E': 'Tratamento de erro'}
COLUNAS = [('Funcionalidade', 150), ('Validações', 120), ('Consultas DB2', 245), ('Alterações de estado DB2', 245), ('Derivações e valores padrão', 150), ('Auditoria', 130), ('Retorno de sucesso', 130), ('Tratamento de erro', 120), ('Outras regras', 110), ('Chamadas Corporativas', 190)]
from cores import COR_REGRA  # noqa: E402  (padrão único de cores: SQL que lê e SQL que grava só aparecem nestas duas colunas)
COR = [None] + [COR_REGRA[n] for n, _w in COLUNAS[1:]]   # cores por categoria de regra em semantic_core/cores.py (as mesmas dos fluxos de regras)


def curto(t):
    """Nome da tabela sem o qualificador (o qualificador vem do mapeamento e continua nas tabelas do relatório)."""
    return t.split('.')[-1]


def por_categoria(ids, grupos):
    c = defaultdict(list)
    for g in ids:
        c[grupos[g]['cat'] if grupos[g]['cat'] in CAT else 'O'].append(g)
    return c


def unidade(rotulo, titulo, ids, grupos, lidas, gravadas, compart, dinamicas=(), corp=(), corp_rot=''):
    """Linha do diagrama: grupos de regras por categoria, tabelas DB2 lidas e gravadas e a relação com as funcionalidades corporativas
    (corp = [(id, nome)]; corp_rot diz se a funcionalidade 'chama' as corporativas ou 'é chamada por' funcionalidades de entry point)."""
    c = por_categoria(ids, grupos)
    return {'rotulo': rotulo, 'titulo': titulo, 'V': c['V'], 'C': c['C'], 'A': c['A'], 'D': c['D'], 'U': c['U'], 'S': sorted(c['S']), 'E': c['E'], 'O': c['O'], 'lidas': sorted(lidas), 'gravadas': sorted(gravadas), 'compart': sorted(compart),
            'dinamicas': sorted(dinamicas), 'corp': list(corp), 'corp_rot': corp_rot}


COLUNA_CAT = {}   # coluna do diagrama que é de uma categoria de regras: some quando a IA filtra todas as regras dela
OMITIDAS = set()


def _filtra(lista):
    """Tira as colunas omitidas (na ordem de COLUNAS)."""
    return [x for x, (n, _w) in zip(lista, COLUNAS) if n not in OMITIDAS]


def celulas(u):
    return _filtra([[u['rotulo']] + ([u['titulo']] if u['titulo'] else []), [' '.join(unicos(u['V']))], [' '.join(unicos(u['C']))] + [curto(t) for t in u['lidas']] + ['◇ ' + t for t in u['dinamicas']],
            [' '.join(unicos(u['A']))] + [curto(t) for t in u['gravadas']], [' '.join(unicos(u['D']))], [' '.join(unicos(u['U']))], [' '.join(unicos(u['S']))], [' '.join(unicos(u['E']))], [' '.join(unicos(u['O']))],
            ([u['corp_rot']] if u['corp'] else []) + [f'{i} {n}' for i, n in u['corp']]])


def bandas(unidades, titulo, nota=None):
    """Diagrama em faixas (bloco 'bands'): cada linha é uma funcionalidade; da esquerda para a direita, validação, consulta, alteração de estado, derivações e valores padrão e retorno de
    sucesso em ordem de execução, e ao lado o tratamento de erro, outras regras e as chamadas corporativas (relação entre funcionalidades de entry point e de programa corporativo)."""
    return {'type': 'bands', 'title': titulo, 'note': nota, 'arrows': 6 - sum(1 for n, _w in COLUNAS[:7] if n in OMITIDAS),
            'columns': [{'name': n, 'width': w, 'color': COR[k] or '#888888'} for k, (n, w) in enumerate(COLUNAS) if n not in OMITIDAS],
            'rows': [{'cells': celulas(u)} for u in unidades]}


def tabela_unidades(titulo, unidades, grupos):
    """Tabela do diagrama em faixas: mesma informação, com link para a regra de negócio de cada id e para a funcionalidade corporativa."""
    rows = []
    for u in unidades:
        def cel(ids, tabs, qs=()):
            return rm.with_links(' '.join(tabs), [rm.link(g if sum(1 for x in ids if rotulo(x) == rotulo(g)) > 1 else rotulo(g), '11 - business-rules', g) for g in ids] + [rm.link('◇ ' + q, '12 - business-flows', q) for q in qs])
        corp = rm.with_links(u['corp_rot'] if u['corp'] else '', [rm.link(f'{i} {n}', '12 - business-flows', i) for i, n in u['corp']])
        rows.append(_filtra([u['rotulo'] + (f' {u["titulo"]}' if u['titulo'] else ''), cel(u['V'], []), cel(u['C'], [curto(t) for t in u['lidas']], u['dinamicas']),
                             cel(u['A'], [curto(t) for t in u['gravadas']]), cel(u['D'], []), cel(u['U'], []), cel(u['S'], []), cel(u['E'], []), cel(u['O'], []), corp]))
    return rm.T(titulo, [n for n, _w in COLUNAS if n not in OMITIDAS], rows)


GENERICAS = ['serviço comum', 'serviço corporativo', 'serviço genérico', 'genérico', 'genérica', 'variante', 'módulo', 'utilitário', 'rotina', 'função comum']


def _sem_acento(t):
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFD', t.lower()) if unicodedata.category(c) != 'Mn')


def palavras(t):
    return re.findall(r'[a-z0-9]+', _sem_acento(t))


def termos_tabela(t):
    """Radicais (4 letras) dos componentes do nome da tabela, sem o qualificador e sem o T de tabela."""
    out = set()
    for i, c in enumerate(curto(t).lower().split('_')):
        c = _sem_acento(c)
        if i == 0 and c.startswith('t') and len(c) > 4:
            c = c[1:]
        if len(c) >= 4:
            out.add(c[:4])
    return out


def validar(d, eps, interp, grupos):
    """(erros que impedem o relatório, afirmações sem evidência)."""
    erros, falhas = [], []
    for x in interp['funcionalidades']:
        if not VERBO.match(x['nome'].split()[0]):
            falhas.append(f'{x["id"]}: o nome deve ser uma ação de negócio no infinitivo (por exemplo "Consultar dados do ..."): {x["nome"]}')
    funcs = {chave(f): f for f in interp['funcionalidades']}
    ids_f = Counter(f.get('id') for f in interp['funcionalidades'])
    for i, n in ids_f.items():
        if not i or n > 1:
            erros.append(f'id de funcionalidade ausente ou repetido: {i}')
    for f in interp['funcionalidades']:
        if ('entry' in f) == ('programa' in f):
            erros.append(f'{f.get("id")}: a funcionalidade parte de um entry point ("entry") ou de um programa corporativo ("programa"), um só')
        for p in d['classe']:
            if re.search(r'(?<![A-Z0-9-])' + re.escape(p) + r'(?![A-Z0-9-])', f['nome']):
                falhas.append(f'{f["id"]}: o nome da funcionalidade não pode citar programa ({p}); o programa vai na descrição, como referência base')
    for f in interp['funcionalidades']:
        nome = f['nome'].lower()
        for g in GENERICAS:
            if g in nome:
                falhas.append(f'{f["id"]}: o nome da funcionalidade não pode ser genérico ("{g}"); use o que as tabelas que o fluxo acessa dizem sobre o propósito: {f["nome"]}')
    nomes = Counter(f['nome'].strip().lower() for f in interp['funcionalidades'])
    for n, c in nomes.items():
        if c > 1:
            falhas.append(f'nome de funcionalidade repetido: {n}')
    for f in interp['funcionalidades']:
        k = chave(f)
        if k not in eps:
            continue
        tabs = set(eps[k]['gravadas']) | set(eps[k]['lidas'])
        for q in eps[k]['programas']:
            tabs |= set(q['tabelas_via'])
        for x in (Q.carregar_mapeamento(BASE) or {}).get('consultas_dinamicas', []):   # só para validar o nome: as tabelas das consultas dinâmicas não aparecem nesta fase (estão no mapeamento SQL)
            if any(q['programa'] == x['servico'] for q in eps[k]['programas']):
                tabs |= {t['nome'] for t in x['tabelas']}
        radicais = {r for t in tabs for r in termos_tabela(t)}
        if radicais and not any(w[:4] in radicais for w in palavras(f['nome'])):
            falhas.append(f'{f["id"]}: o nome deve refletir as tabelas que o fluxo acessa ({", ".join(sorted(curto(t) for t in tabs))}): {f["nome"]}')
    ocultas = {}
    for ep in sorted(eps):
        if ep not in funcs:
            erros.append(f'{"programa corporativo" if ep in d["corp"] else "entry point"} sem funcionalidade descrita: {ep}')
    for ep in funcs:
        if ep not in eps:
            erros.append(f'funcionalidade de entry point ou programa corporativo que não existe (ou não foi alcançado) nos relatórios: {ep}')
    evid = {ep: evidencia(ep, e, d) for ep, e in eps.items()}
    deriv = {ep: grupos_do_entry(e, {g: x['regras'] for g, x in grupos.items()}) for ep, e in eps.items()}
    for ep, f in funcs.items():
        if ep not in eps:
            continue
        for c in f['cita']:
            if S.sem_copybook(c) not in S.sem_copybook(evid[ep]):
                falhas.append(f'{ep}: literal sem evidência: {c}')
        for g in f['grupos']:
            if g not in grupos:
                erros.append(f'{ep}: grupo de regras inexistente {g}')
            elif g not in deriv[ep]:
                falhas.append(f'{ep}: grupo {g} citado sem regra que alcance o entry point')
        diretas = {(c['Programa chamador'], c['Programa chamado']) for c in d['chamadas']}
        for i_, p_ in enumerate(f['passos'], 1):   # "A → B": B tem de ser chamado por A na fase 1 (chamada direta), senão o passo atribui a chamada ao programa errado
            esq, _, dir_ = p_['programas'].partition('→')
            a_ = esq.strip()
            for b_ in [x.strip() for x in dir_.split(',') if x.strip()]:
                if a_ in d['alc_prog'] and b_ in d['alc_prog'] and a_ != b_ and (a_, b_) not in diretas:
                    quem = sorted({c for (c, t) in diretas if t == b_})
                    falhas.append(f'{ep}: passo {i_} liga {a_} → {b_}, mas a fase 1 não tem essa chamada direta (quem chama {b_}: {", ".join(quem) or "ninguém"})')
        f['_cen'] = []
        for trecho in f['cenarios_contem']:
            achou = [r for r in eps[ep]['cenarios'] if trecho in r['Cenário']]
            if not achou:
                falhas.append(f'{ep}: nenhum cenário contém "{trecho}"')
            f['_cen'] += [r for r in achou if r not in f['_cen']]
    todos_prog = {p['programa'] for e in eps.values() for p in e['programas']}
    mapa_txt = defaultdict(str)
    for pr_, r_ in d['mapa']:
        mapa_txt[pr_] += '\n' + r_.get('Condição ou comandos', '')
    fcd = interp.get('filtro_consulta_dinamica') or {}
    servicos = sorted({x['servico'] for x in (Q.carregar_mapeamento(BASE) or {}).get('consultas_dinamicas', []) if x['servico'] in d['alc_prog']})
    desd = {x.get('programa'): x for x in interp.get('desdobramentos', [])}
    for k_ in desd:
        if k_ not in servicos:
            erros.append(f'`desdobramentos` cita programa que não executa consulta dinâmica alcançada: {k_}')
    for sv in servicos:   # a descoberta e a internalização são da fase 10 (gerar_sql.py); aqui só a decisão de desdobrar as funcionalidades pelas regras de negócio
        deco_ = desd.get(sv) or {}
        filhas_ = [f_ for f_ in interp['funcionalidades'] if f_.get('programa') == sv]
        if deco_.get('decisao') not in ('separar', 'manter') or not str(deco_.get('criterio', '')).strip():
            falhas.append(f'{sv}: `desdobramentos` precisa de programa, decisao (separar ou manter) e criterio (por que há ou não finalidades de negócio distintas entre os chamadores)')
        elif deco_['decisao'] == 'separar' and len(filhas_) < 2:
            falhas.append(f'{sv}: desdobramento decidido (separar), mas há {len(filhas_)} funcionalidade(s) do programa; descreva uma por finalidade')
        elif deco_['decisao'] == 'manter' and len(filhas_) > 1:
            falhas.append(f'{sv}: desdobramento "manter", mas há {len(filhas_)} funcionalidades do programa')
        if len(filhas_) > 1:
            conj_ = [frozenset(f_.get('grupos', [])) for f_ in filhas_]
            if len(set(conj_)) < len(conj_):
                falhas.append(f'{sv}: funcionalidades desdobradas com o mesmo conjunto de regras de negócio (`grupos`); cada finalidade tem as suas')
        if sv in deriv and fcd:
            for g_ in fcd.get('grupos', []):
                if not any(q.split('.')[0] == g_ for q in deriv[sv]) and all(not any(q.split('.')[0] == g_ for q in deriv[o]) for o in deriv):
                    falhas.append(f'filtro_consulta_dinamica cita grupo {g_} que nenhuma funcionalidade alcança')
    return erros, falhas, funcs, ocultas, deriv


def escrever(saida, nome, mod):
    """Grava <saida>/<nome>/human/report.html e <saida>/<nome>/ia/report.json a partir do mesmo modelo."""
    S.escrever(saida, nome, mod)

CHAVES_FILTRO = ('filtro_paginacao', 'filtro_consulta_dinamica')   # um filtro por assunto, cada um na sua chave da interpretação


def aplicar_filtros(interp, funcs, grupos):
    """Filtros que a IA decidiu (interpretacao-fluxos/funcionalidades.json, chaves 'filtro_paginacao' e 'filtro_consulta_dinamica'): cada filtro tem id, tema, grupos (ids de regra de negócio do prompt 1) e o motivo.
    As regras filtradas saem do diagrama macro e da lista de regras de cada funcionalidade e ficam na seção "Regras filtradas das funcionalidades", com o motivo.
    Devolve (filtros válidos, {funcionalidade: [ids de regra filtrados]}, erros). Sem filtros na interpretação, nada é filtrado."""
    erros, filtros = [], []
    bases = {i.split('.')[0] for i in grupos}
    vistos = set()
    for x in [interp[c] for c in CHAVES_FILTRO if interp.get(c)]:
        fid_ = x.get('id') or '?'
        if not x.get('id') or not (x.get('tema') or '').strip() or not x.get('grupos'):
            erros.append(f'filtro sem id, tema ou grupos: {fid_}')
            continue
        if not (x.get('motivo') or '').strip():
            erros.append(f'filtro {fid_} sem motivo: o filtro precisa de justificativa')
            continue
        for g in x['grupos']:
            if g not in bases:
                erros.append(f'filtro {fid_} cita regra de negócio inexistente: {g}')
            elif g in vistos:
                erros.append(f'regra de negócio {g} em mais de um filtro')
            vistos.add(g)
        filtros.append(x)
    removidas = {}
    por_base = {g for x in filtros for g in x['grupos']}
    for k, f in funcs.items():
        removidas[k] = [g for g in f['grupos'] if g.split('.')[0] in por_base]
        f['grupos'] = [g for g in f['grupos'] if g.split('.')[0] not in por_base]
    return filtros, removidas, erros


def modelo(d, eps, interp, grupos):
    falhas_sep = []
    for x in interp['funcionalidades']:
        if 'entry' in x:
            # funcionalidade de entry point: só regras dos programas do próprio fluxo; as dos programas corporativos pertencem às funcionalidades corporativas
            prop = [i for i in grupos.values() if not all(r.split(':')[0] in set(d['corp']) for r in i['regras'])]
            antes = list(x['grupos'])
            x['grupos'] = [i for g in x['grupos'] for i in S.ids_do_entry(g, x['entry'], prop) if i in grupos]
            vazios_ = [g for g in antes if not any(i.split('.')[0] == g for i in x['grupos'])]
        else:
            antes = list(x['grupos'])
            x['grupos'] = [i for g in x['grupos'] for i in S.ids_do_programa(g, x['programa'], grupos.values())]
            vazios_ = [g for g in antes if not any(r.split(':')[0] == x['programa'] for i in grupos.values() if i['base'] == g for r in i['regras'])]
        for g in vazios_:   # nunca incorporar regras de funcionalidade corporativa em funcionalidade de entry point, nem o contrário
            falhas_sep.append(f'{x["id"]}: o grupo {g} não tem regras dos programas desta funcionalidade ({"entry point" if "entry" in x else "programa corporativo"}); regras de programas corporativos pertencem às funcionalidades corporativas e as de entry point, às de entry point')
    erros, falhas, funcs, ocultas, deriv = validar(d, eps, interp, grupos)
    falhas += falhas_sep
    filtros, removidas, erros_f = aplicar_filtros(interp, funcs, grupos)
    erros += erros_f
    if erros:
        raise SystemExit('interpretação inconsistente com os relatórios:\n  ' + '\n  '.join(erros))
    OMITIDAS.clear()
    for nome, cat in COLUNA_CAT.items():   # a coluna de uma categoria some quando a IA filtrou as regras dela e nenhuma sobrou nas funcionalidades
        if any(grupos[g]['cat'] == cat for rs in removidas.values() for g in rs) and not any(grupos[g]['cat'] == cat for f in funcs.values() for g in f['grupos']):
            OMITIDAS.add(nome)
    n = len(eps)
    corp = set(d['corp'])
    fid = {k: f['id'] for k, f in funcs.items()}
    ordem_ep = sorted((k for k in eps if k not in corp), key=lambda k: fid[k])
    ordem_cp = sorted((k for k in eps if k in corp), key=lambda k: fid[k])
    for c in ordem_cp:
        eps[c]['donos'] = sorted(eps[c]['donos'], key=lambda x: fid[x])   # na ordem dos ids das funcionalidades
    chama = {k: [c for c in ordem_cp if c in eps[k]['corp_chamadas'] and c != k] for k in eps}   # corporativas que o fluxo chama (nunca ele mesmo)
    un = {}
    for ep in ordem_ep:
        un[ep] = unidade(fid[ep], funcs[ep]['nome'], funcs[ep]['grupos'], grupos, eps[ep]['lidas'], eps[ep]['gravadas'], [], [], [(fid[c], funcs[c]['nome']) for c in chama[ep]], 'chama')
    for c in ordem_cp:
        un[c] = unidade(fid[c], funcs[c]['nome'], funcs[c]['grupos'], grupos, eps[c]['lidas'], eps[c]['gravadas'], [], [], [(fid[x], funcs[x]['nome']) for x in chama[c]], 'chama')
    L = rm.link
    ordem = ordem_ep + ordem_cp
    base = lambda k: (f'entry point {k}' if k not in corp else f'programa corporativo {k.split("#")[0]}')
    secoes = []
    secoes.append(rm.S('cobertura', 'Cobertura', [
        rm.X(f'{len(ordem_ep)} entry points e {len(ordem_cp)} programas corporativos alcançados; {len(funcs)} funcionalidades descritas. '
             f'Afirmações sem evidência: {len(falhas)}. Só entram programas e tabelas que algum cenário alcançou na análise dinâmica. A funcionalidade é identificada pelo id e pelo nome de negócio; o programa em que ela se baseia aparece na descrição, como referência base.'),
        rm.T('Funcionalidades', ['Id', 'Funcionalidade', 'Base (referência)', 'Tipo', 'Confiança'], [(fid[k], funcs[k]['nome'], base(k), funcs[k]['tipo'], funcs[k]['confianca']) for k in ordem])]))
    liga = [(k, c) for k in ordem for c in chama[k]]
    rel_ids = {fid[x] for par in liga for x in par}
    nos = [{'id': fid[k], 'label': f'{fid[k]} · {funcs[k]["nome"]}', 'group': 'CORPORATIVO' if k in corp else 'COORDENADOR'} for k in ordem]
    arestas = [{'from': fid[k], 'to': fid[c], 'label': 'chama'} for k, c in liga]
    sem_rel = [fid[k] for k in ordem if fid[k] not in rel_ids]
    secoes.append(rm.S('hierarquia', 'Hierarquia das funcionalidades', [
        rm.G('Relação entre as funcionalidades: quem chama quem', nos, arestas, kind='flow',
             note='Todas as funcionalidades aparecem; as que não chamam nem são chamadas ficam sem ligação. Cada ligação é uma funcionalidade de entry point (borda azul, F) que chama uma funcionalidade corporativa (borda laranja, FC). Uma corporativa chamada por mais de uma funcionalidade recebe uma ligação de cada uma.')],
        'Todas as funcionalidades e só a relação entre elas, calculada das chamadas corporativas das fases 1 e 6.' + (f' Sem relação com outra funcionalidade: {", ".join(sem_rel)}.' if sem_rel else '')))
    secoes.append(rm.S('diagrama', 'Diagrama macro das funcionalidades', [
        bandas([un[k] for k in ordem], 'Diagrama macro das funcionalidades',
               'Cada linha é uma funcionalidade: F = baseada em entry point, FC = baseada em programa corporativo. Da esquerda para a direita: validação, consulta, alteração de estado e retorno de sucesso, na ordem em que acontecem, e ao lado o tratamento de erro, outras regras e as chamadas corporativas '
               '(a coluna lista as funcionalidades corporativas que o fluxo chama, nunca ele mesmo; as tabelas de uma funcionalidade são só as dos seus próprios programas, as dos fluxos corporativos que ela chama ficam na funcionalidade corporativa). Os ids de regra são regras de negócio (business-rules); as tabelas DB2 são as alcançadas na análise dinâmica. Padrão de cores: comando SQL que lê em azul-petróleo (coluna Consultas DB2, nó de consulta nos fluxos), comando SQL que grava em roxo (coluna Alterações de estado DB2); nenhuma outra categoria usa essas cores, e as bordas azul, verde, laranja e vermelho são as classes de programa em todos os diagramas.'),
        tabela_unidades('Tabela do diagrama macro das funcionalidades', [un[k] for k in ordem], grupos)]))
    if filtros:
        lin = []
        for x in filtros:
            for g in sorted(i for i in grupos if i.split('.')[0] in x['grupos']):
                usos = [k for k in ordem if g in removidas.get(k, [])]
                lin.append([x['id'], x['tema'], rm.with_links('', [L(g, '11 - business-rules', g)]), grupos[g]['titulo'],
                            rm.with_links('', [L(f'{fid[k]} {funcs[k]["nome"]}', '12 - business-flows', fid[k]) for k in usos]) if usos else '—', x['motivo']])
        secoes.append(rm.S('filtros', 'Regras filtradas das funcionalidades', [
            rm.T('Regras de negócio filtradas e o motivo', ['Filtro', 'Tema', 'Regra de negócio', 'Título', 'Funcionalidades em que apareciam', 'Motivo do filtro (IA)'], lin)],
            'A IA decidiu, com justificativa, quais regras de negócio não descrevem o que a funcionalidade faz para o negócio (por exemplo, paginação). Elas continuam no relatório de regras de negócio, mas saem do diagrama macro e da lista de regras de cada funcionalidade.'
            + (' Colunas retiradas do diagrama macro: ' + ', '.join(sorted(OMITIDAS)) + '.' if OMITIDAS else '')))
    desd_ = {x.get('programa'): x for x in interp.get('desdobramentos', [])}
    if desd_:
        lin = []
        for pg_, x in sorted(desd_.items()):
            fs_ = [k for k in ordem if k.split('#')[0] == pg_ and k in corp]
            lin.append([pg_, x.get('decisao', ''), x.get('criterio', ''), rm.with_links('', [L(f'{fid[k]} {funcs[k]["nome"]}', '12 - business-flows', fid[k]) for k in fs_])])
        secoes.append(rm.S('desdobramentos', 'Desdobramento de funcionalidades por finalidade de negócio', [
            rm.T('Decisão de desdobramento por programa corporativo que executa consulta dinâmica', ['Programa', 'Decisão (IA)', 'Critério (IA)', 'Funcionalidades'], lin)],
            'A descoberta das consultas dinâmicas e seus comandos SQL é da fase 10 (sql-mapping) e não se repete aqui. Esta seção só registra se o programa vira uma funcionalidade ou várias, conforme as regras de negócio (fase 11) que cada finalidade aplica.'))
    for k in ordem:
        e, f = eps[k], funcs[k]
        i = fid[k]
        if k in corp:
            ref = f'Referência base: programa corporativo {k.split("#")[0]} (chamado por mais de um programa{"; desdobrado em funcionalidades por finalidade de negócio: esta atende as regras de negócio " + ", ".join(f.get("grupos", [])) if "#" in k else ""}); usado pelos entry points {", ".join(e["donos"])}, nas funcionalidades {", ".join(fid[x] for x in e["donos"])}.'
        else:
            ref = f'Referência base: entry point {k}' + (f'; chama as funcionalidades corporativas {", ".join(fid[c] for c in chama[k])}.' if chama[k] else '.')
        b = [rm.X(ref), rm.X(f['resumo']), rm.X(f'tipo: {f["tipo"]} · confiança: {f["confianca"]}')]
        rel = [('chama', fid[c], funcs[c]['nome'], c) for c in chama[k]] + ([('é chamada por', fid[x], funcs[x]['nome'], x) for x in e['donos']] if k in corp else [])
        if rel:
            b.append(rm.T(f'{i}: relação com as chamadas corporativas', ['Relação', 'Funcionalidade', 'Nome', 'Base (referência)'],
                          [(r, rm.with_links('', [L(i2, '12 - business-flows', i2)]), nm, base(bs)) for r, i2, nm, bs in rel]))
        b += [rm.X('Entradas de negócio: ' + f['entradas']),
              rm.T(f'{i}: fluxo passo a passo', ['Passo', 'O que acontece', 'Programas'], [(j + 1, p['texto'], p['programas']) for j, p in enumerate(f['passos'])]),
              rm.X('Saídas: ' + f['saidas']),
              bandas([un[k]], f'Fluxo de {i}'), tabela_unidades(f'Tabela do fluxo de {i}', [un[k]], grupos)]
        b.append(rm.T(f'{i}: programas alcançados, e regras', ['Programa', 'Classe', 'Situação na execução', 'Caminho de chamada', 'Regras', 'Regras por tipo'],
                      [(p['programa'], p['classe'], p['situacao'], p['caminho'], p['regras'], p['tipos']) for p in e['programas']]))
        b.append(rm.T(f'{i}: cenários que sustentam o texto', ['Cenário', 'Status', 'Entradas', 'Saídas esperadas'], [(r['Cenário'], r['Status'], r['Entradas'], r['Saídas esperadas']) for r in f['_cen']]))
        b.append(dict(rm.T(f'{i}: regras de negócio relacionadas', ['Regra de negócio', 'Título'], [(rm.with_links('', [L(g, '11 - business-rules', g)]), grupos[g]['titulo']) for g in f['grupos']]),
                      so_ia='Só na visão para IA: lida pelo gerar_sequencia e pelo prompt 4; na página, as regras aparecem no fluxo interno e na coluna Funcionalidades das regras de negócio.'))
        if f['lacunas']:
            b.append(rm.X(' | '.join(f['lacunas']), title=f'{i}: lacunas'))
        secoes.append(rm.S(i, f'{i} · {f["nome"]}', b))
    cards = [rm.card('funcionalidades', len(funcs)), rm.card('de entry point', len(ordem_ep)), rm.card('de programa corporativo', len(ordem_cp)), rm.card('tabelas alcançadas', len({t for e in eps.values() for t in e['gravadas'] | e['lidas']}))]
    return rm.model('Funcionalidades', 'Funcionalidades baseadas em entry points e em programas corporativos: o que cada uma faz, em que ordem, com que dados e regras de negócio, só com o que algum cenário alcançou na análise dinâmica.', cards, secoes), falhas


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
    S.definir_copybooks(ana)
    d = coletar(ana)
    eps = por_entry(d)
    if not (BASE / 'interpretacao-fluxos' / 'funcionalidades.json').exists():
        print('funcionalidades: sem interpretacao-fluxos/funcionalidades.json (prompt 2); a fase 12 não é gerada')
        return
    interp = S.carregar(BASE / 'interpretacao-fluxos' / 'funcionalidades.json')
    grupos = carregar_grupos(d)
    erros_d = desdobrar(d, eps, interp)
    if erros_d:
        raise SystemExit('desdobramento inconsistente:\n  ' + '\n  '.join(erros_d))
    mod, falhas = modelo(d, eps, interp, grupos)
    escrever(saida, '12 - business-flows', mod)
    print(f'{len(eps)} entry points, {len(interp["funcionalidades"])} funcionalidades; afirmações sem evidência: {len(falhas)}')
    for x in falhas:
        print('  ' + x)
    sys.exit(1 if falhas else 0)


if __name__ == '__main__':
    main()
