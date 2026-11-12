#!/usr/bin/env python3
"""Relatório architecture-decision-records (fase 22): as decisões de arquitetura tomadas sobre a arquitetura alvo, cada uma completa com as evidências.

  python3 gerar_architecture_decisions.py <pasta-da-analise> [pasta-de-saida] --projeto <repositório> [--interpretacao PASTA]
  (padrão da saída: a pasta da análise; da interpretação: a pasta deste script)

As decisões vêm de `interpretacao-adr/adr.json` (registro do dono da arquitetura, não é saída de IA): contexto, decisão, alternativas, consequências,
os repositórios do DDA, o encaixe das aplicações da fase 19 nos repositórios, o de-para das filas e o prefixo da API. O gerador completa cada decisão com:
  - fase 10: tabela de cada comando SQL; fase 19: comandos SQL e programas corporativos com filas, programas e copybooks; fase 20: operações dos contratos;
  - repositório: filas de cada módulo (application.yml), filas definidas no gerenciador local (config.mqsc), endpoints implementados (@RequestMapping da
    classe + @GetMapping/@PostMapping/@PutMapping do método), clientes Feign do BFF e âncoras de evidência (arquivo:linha).
Nada é inventado: fila nova que o projeto não usa, fila antiga que ainda aparece, módulo diferente do repositório do encaixe, endpoint sem o prefixo,
operação do contrato sem endpoint ou âncora que não existe recusam o relatório.
Saída: <saida>/22 - architecture-decision-records/human/report.html e <saida>/22 - architecture-decision-records/ia/report.json."""
import glob
import os
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

import gerar_simulacao as S
import report_model as rm  # noqa: E402

FASE = '22 - architecture-decision-records'
F10, F19, F20 = '10 - sql-mapping', '19 - target-architecture', '20 - contracts'
INTERP = 'interpretacao-adr'
TAB_CMD = 'Comandos SQL: fila de pedido, programa e fila de resposta'
TAB_REC = 'Modelo de recursos aprovados'
USOS = {'INFRAESTRUTURA': 'Infraestrutura', 'POC': 'Usado pela POC', 'FORA_DO_RECORTE': 'Será utilizado (fora do recorte da POC)',
        'EXISTENTE': 'Aplicação já existente', 'NAO_UTILIZADO': 'Não utilizado pela POC'}
COR = {'antes': '#8a6d00', 'depois': '#1E8E3E', 'app': '#0072B2', 'fila': '#7B3FA0', 'alta': '#B04A9B', 'prog': '#D55E00', 'dado': '#555555', 'fora': '#9E9E9E', 'fora_dda': '#B00020'}
COR_USO = {'INFRAESTRUTURA': '#555555', 'POC': '#1E8E3E', 'FORA_DO_RECORTE': '#0072B2', 'EXISTENTE': '#D55E00', 'NAO_UTILIZADO': '#B00020'}
METODOS = ('Get', 'Post', 'Put', 'Delete', 'Patch')


def texto(c):
    if isinstance(c, dict):
        return c.get('text') or ', '.join(l['text'] for l in c.get('links', []) if isinstance(l, dict))
    return '' if c is None else str(c)


def rsp(fila_req):
    """Fila de resposta do mesmo comando: FR → FL, .REQ → .RSP (o restante do nome é igual)."""
    return 'FL' + fila_req[2:-4] + '.RSP'


def curto(fila):
    """Nome sem o sistema e o sufixo: <contexto>.NI<propósito>."""
    return '.'.join(fila.split('.')[2:-1])


# ── relatórios das fases anteriores ──────────────────────────────────────────
def tabela(ana, fase, titulo):
    d = json.loads((Path(ana) / fase / 'ia' / 'report.json').read_text(encoding='utf-8'))
    for sec in d['sections']:
        for b in sec['blocks']:
            if b['type'] == 'table' and b['title'] == titulo:
                col = {n: i for i, n in enumerate(b['columns'])}
                return [{n: texto(r[i]) for n, i in col.items()} for r in b['rows']]
    raise SystemExit(f'sem a tabela «{titulo}» na fase {fase}')


def tabelas_sql(ana):
    """Comando SQL -> (operação, tabela), dos títulos das seções da fase 10 («<PROGRAMA>-Q01 · SELECT <TABELA>»)."""
    d = json.loads((Path(ana) / F10 / 'ia' / 'report.json').read_text(encoding='utf-8'))
    out = {}
    for s in d['sections']:
        m = re.match(r'^([A-Z0-9]+-Q\d+) · (SELECT|INSERT|UPDATE|DELETE) (\w+)', s['title'])
        if m:
            out[m.group(1)] = (m.group(2), m.group(3))
    return out


def contratos(ana):
    ops = []
    for f in sorted(glob.glob(str(Path(ana) / F20 / 'ia' / 'contracts' / '*' / '*.yaml'))):
        doc = yaml.safe_load(Path(f).read_text(encoding='utf-8'))
        app = Path(f).name.replace('.openapi.yaml', '')
        for caminho, metodos in doc.get('paths', {}).items():
            for metodo, op in metodos.items():
                if metodo in ('get', 'post', 'put', 'delete', 'patch'):
                    ops.append({'app': app, 'metodo': metodo.upper(), 'caminho': caminho, 'operationId': op.get('operationId', ''),
                                'func': str(op.get('x-legacy', {}).get('feature') or '')})
    if not ops:
        raise SystemExit('sem contratos OpenAPI na fase 20')
    return ops


# ── repositório ──────────────────────────────────────────────────────────────
MODULOS = []   # pastas do projeto que são repositórios do DDA (preenchido em main a partir de adr.json)


def modulos_do_projeto(projeto, adr):
    """Repositórios do DDA que têm código no projeto (pasta com pom.xml ou package.json)."""
    return sorted(r['repositorio'] for r in adr['repositorios_dda']
                  if (Path(projeto) / r['repositorio'] / 'pom.xml').exists() or (Path(projeto) / r['repositorio'] / 'package.json').exists())


def _glob(projeto, padrao):
    return sorted(f for m in MODULOS for f in (Path(projeto) / m).glob(padrao))


def filas_dos_modulos(projeto):
    """fila de baixa -> (módulo, comando, copybook de requisição, copybook de resposta), de ibm.mq.comandos de cada application.yml."""
    out = {}
    for f in _glob(projeto, 'src/main/resources/application.yml'):
        mod = f.parts[-5]
        cfg = yaml.safe_load(f.read_text(encoding='utf-8')) or {}
        for cmd, c in ((cfg.get('ibm') or {}).get('mq') or {}).get('comandos', {}).items():
            for chave in ('fila-requisicao', 'fila-resposta'):
                if c[chave] in out:
                    raise SystemExit(f'fila {c[chave]} em dois módulos: {out[c[chave]][0]} e {mod}')
                out[c[chave]] = (mod, cmd, c['copybook-requisicao'], c['copybook-resposta'])
    return out


def filas_mqsc(projeto):
    """(filas de baixa definidas no gerenciador distribuído, ligações alta <-> baixa).
    Com dois gerenciadores (config.mqsc distribuído e o TCAPMQSC do Mainframe), a fila de baixa do pedido é uma QREMOTE cujo RNAME é a
    fila de alta, e a fila de alta da resposta é uma QREMOTE cujo RNAME é a fila de baixa; com um gerenciador só, a ligação é por QALIAS."""
    p = Path(projeto)
    s = (p / 'local' / 'docker' / 'mq-init' / 'config.mqsc').read_text(encoding='utf-8')
    mainframe = p / 'programas-mainframe' / 'RECURSOS' / 'TCAPMQSC.txt'
    m = mainframe.read_text(encoding='utf-8') if mainframe.exists() else ''
    definidas = set(re.findall(r"DEFINE Q(?:LOCAL|REMOTE)\('([^']+)'\)", s))
    alias = {}
    for texto in (s, m):
        for a, b in re.findall(r"DEFINE QALIAS\('([^']+)'\)(?:(?!DEFINE).)*?TARGET\('([^']+)'\)", texto, re.S):
            alias[a] = b
        for a, b in re.findall(r"DEFINE QREMOTE\('([^']+)'\)(?:(?!DEFINE).)*?RNAME\('([^']*)'\)", texto, re.S):
            if b.strip():
                alias[a] = b
                alias[b] = a
    return definidas, alias


IGNORADAS = {'target', 'node_modules', 'coverage', '.git', 'db2-init', 'dist', 'evidencias', 'docs'}   # docs: documentação e cópias de relatórios, não é código nem configuração


def arquivos_texto(projeto):
    """Arquivos de código e configuração do repositório; as pastas ignoradas nem são percorridas (no disco do Windows, percorrer node_modules leva minutos)."""
    for raiz, pastas, nomes in os.walk(projeto):
        pastas[:] = [p for p in pastas if p not in IGNORADAS]
        for n in nomes:
            if n.lower().endswith(('.yml', '.yaml', '.mqsc', '.cpy', '.cbl', '.txt', '.java', '.ts', '.tsx', '.py', '.md', '.properties')):
                yield Path(raiz) / n


def endpoints(projeto):
    """Endpoints implementados: módulo, método, caminho completo, prefixo da classe, operationId, arquivo e linha."""
    out = []
    for f in _glob(projeto, 'src/main/java/**/*.java'):
        linhas = f.read_text(encoding='utf-8').splitlines()
        if not any(l.strip() == '@RestController' for l in linhas):
            continue
        prefixo, opid = '', ''
        for i, l in enumerate(linhas):
            m = re.match(r'\s*@RequestMapping\("([^"]*)"\)', l)
            if m and i < next((k for k, x in enumerate(linhas) if 'public class' in x), len(linhas)):
                prefixo = m.group(1)
            m = re.search(r'operationId = "([^"]+)"', l)
            if m:
                opid = m.group(1)
            m = re.match(r'\s*@(' + '|'.join(METODOS) + r')Mapping\(value = "([^"]+)"', l)
            if m:
                out.append({'modulo': f.relative_to(projeto).parts[0], 'metodo': m.group(1).upper(), 'caminho': prefixo + m.group(2), 'prefixo': prefixo,
                            'sem_prefixo': m.group(2), 'operationId': opid, 'arquivo': str(f.relative_to(projeto)), 'linha': i + 1, 'classe': f.stem})
                opid = ''
    return out


def clientes_feign(projeto):
    out = []
    for f in _glob(projeto, 'src/main/java/**/*Client.java'):
        s = f.read_text(encoding='utf-8')
        m = re.search(r'@FeignClient\(name = "([^"]+)", url = "\$\{([^}]+)\}"(?:, path = "([^"]*)")?\)', s)
        if not m:
            continue
        for i, l in enumerate(s.splitlines()):
            mm = re.match(r'\s*@(' + '|'.join(METODOS) + r')Mapping\(value = "([^"]+)"', l)
            if mm:
                out.append({'modulo': f.relative_to(projeto).parts[0], 'cliente': f.stem, 'url': m.group(2), 'path': m.group(3) or '',
                            'metodo': mm.group(1).upper(), 'caminho': (m.group(3) or '') + mm.group(2), 'arquivo': str(f.relative_to(projeto)), 'linha': i + 1})
    return out


def localizar(projeto, a):
    f = Path(projeto) / a['arquivo']
    if not f.exists():
        return None
    for i, l in enumerate(f.read_text(encoding='utf-8').splitlines()):
        if a['ancora'] in l:
            return i + 1, l.strip()
    return None


# ── validação e cálculo ──────────────────────────────────────────────────────
def calcular(ana, projeto, adr):
    erros = []
    cmds = tabela(ana, F19, TAB_CMD)
    recursos = {r['Id']: r for r in tabela(ana, F19, TAB_REC)}
    sqlt = tabelas_sql(ana)
    ops = contratos(ana)
    repo_de = {e['aplicacao']: e['repositorio'] for e in adr['encaixe']}
    prefixo_de = {e['aplicacao']: e.get('prefixo_caminho') or '' for e in adr['encaixe']}   # caminho base da aplicação dentro do repositório que a recebe
    dda = {r['repositorio']: r for r in adr['repositorios_dda']}
    usadas_mod = filas_dos_modulos(projeto)
    locais, alias = filas_mqsc(projeto)
    eps = endpoints(projeto)
    feign = clientes_feign(projeto)
    prefixo = adr['prefixo_api']

    for app in recursos:
        if app not in repo_de and recursos[app]['Tipo'] != 'HOST':
            erros.append(f'aplicação {app} da fase 19 sem repositório no encaixe')
    for app, repo in repo_de.items():
        if app not in recursos:
            erros.append(f'encaixe cita a aplicação {app}, que não está na fase 19')
        if repo not in dda:
            erros.append(f'encaixe usa o repositório {repo}, que não está no DDA')
    for r in adr['repositorios_dda']:
        if r['uso'] not in USOS:
            erros.append(f'repositório {r["repositorio"]}: uso {r["uso"]} inválido')

    # filas: de-para (pedido e resposta) contra a fase 19 e o projeto
    depara = {}
    for x in adr['filas']:
        depara[x['de']] = x['para']
        depara[rsp(x['de'])] = rsp(x['para'])
    inverso = {v: k for k, v in depara.items()}
    # programas executores: de-para dos nomes da fase 19 para os que serão criados (quando houver)
    progs = {x['de']: x['para'] for x in adr.get('programas', [])}
    progs_inv = {v: k for k, v in progs.items()}
    linhas_filas = []
    for c in cmds:
        req = c['MQ_REQ']
        if req in ('—', ''):
            continue
        # a fase 19 pode mostrar o nome anterior ou já o novo (quando foi regerada depois da decisão): o de-para vale nos dois sentidos
        if req in inverso:
            req = inverso[req]
        if req not in depara:
            erros.append(f'fila {c["MQ_REQ"]} da fase 19 sem de-para')
            continue
        if rsp(c['MQ_REQ']) != c['MQ_RSP']:
            erros.append(f'fila de resposta {c["MQ_RSP"]} não corresponde a {c["MQ_REQ"]}')
        novo_req, novo_rsp = depara[req], depara[rsp(req)]
        repo = repo_de.get(c['Executado por'])
        for fila in (novo_req, novo_rsp):
            if fila not in locais:
                erros.append(f'fila {fila} não está definida no config.mqsc')
            if fila not in usadas_mod:
                erros.append(f'fila {fila} não é usada por nenhum módulo')
            elif usadas_mod[fila][0] != repo:
                erros.append(f'fila {fila} usada por {usadas_mod[fila][0]}, mas o encaixe põe {c["Executado por"]} em {repo}')
        if alias.get(c['MQ_REQ alta']) != novo_req or alias.get(c['MQ_RSP alta']) != novo_rsp:
            erros.append(f'filas de alta de {c["PROGRAM_DB2 ou PROGRAM_CORP"]} não apontam para as filas novas no config.mqsc')
        mod = usadas_mod.get(novo_req)
        if mod and (mod[2], mod[3]) != (c['Copybook de requisição'], c['Copybook de resposta']):
            erros.append(f'copybooks de {novo_req} no projeto ({mod[2]}/{mod[3]}) diferentes da fase 19')
        corp = c['Operação'] == 'programa corporativo (chamada)'
        # com coordenador e funcional (fase 19), quem lê as filas é o coordenador e quem executa o SQL ou chama o corporativo é o funcional
        coord_ = c.get('Coordenador (PROGRAM_COORD)') or ''
        fila_prog = coord_ if coord_ not in ('', '—') else c['PROGRAM_DB2 ou PROGRAM_CORP']
        op, tab = sqlt.get(c['Comando (ou programa corporativo chamado)'], (c['Operação'], ''))
        linhas_filas.append({'cmd': c['Comando (ou programa corporativo chamado)'], 'corp': corp, 'op': 'CALL' if corp else op, 'tabela': tab,
                             'classes': c['Classes de domínio acessadas'], 'app': c['Executado por'], 'repo': repo, 'comando_mod': mod[1] if mod else '—',
                             'req_de': req, 'req_para': novo_req, 'req_alta': c['MQ_REQ alta'], 'cpy_req': c['Copybook de requisição'],
                             'prog': progs.get(fila_prog, fila_prog), 'prog_de': progs_inv.get(fila_prog, fila_prog), 'func': c['PROGRAM_DB2 ou PROGRAM_CORP'], 'rsp_alta': c['MQ_RSP alta'], 'rsp_de': rsp(req), 'rsp_para': novo_rsp,
                             'cpy_rsp': c['Copybook de resposta']})
    if len(linhas_filas) != len(adr['filas']):
        erros.append(f'{len(adr["filas"])} filas no de-para e {len(linhas_filas)} comandos com fila na fase 19')
    nomes_19 = {c['prog_de'] for c in linhas_filas}
    for de, para in progs.items():
        if de not in nomes_19:
            erros.append(f'programa {de} do de-para não está na fase 19')
        if len(para) != len(de) or para in nomes_19 or list(progs.values()).count(para) > 1:
            erros.append(f'programa novo {para}: precisa ter {len(de)} posições e não repetir outro programa')
    antigas = set(depara) - set(depara.values())
    funcs_esperados, funcs_vistos = {c['func'] for c in linhas_filas if c['func'] != c['prog']}, set()
    trans = {x['de']: x['para'] for x in adr.get('transacoes', [])}   # transações CICS: de-para dos nomes
    for de, para in trans.items():
        if not re.fullmatch(r'[A-Z0-9]{4}', para) or list(trans.values()).count(para) > 1:
            erros.append(f'transação {para}: precisa ter 4 posições e não repetir outra')
    trans_vistas = set()
    for f in arquivos_texto(projeto):
        try:
            s = f.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
        for a in antigas:
            if a in s:
                erros.append(f'fila antiga {a} ainda aparece em {f.relative_to(projeto)}')
        funcs_vistos.update(x for x in funcs_esperados if x in s)
        trans_vistas.update(x for x in trans.values() if re.search(rf'\b{x}\b', s))
        for a in trans:
            if re.search(rf'\b{a}\b', s):
                erros.append(f'transação {a} (renomeada para {trans[a]}) ainda aparece em {f.relative_to(projeto)}')
        for a in progs:
            if re.search(rf'\b{a}\b', s, re.I):
                erros.append(f'programa {a} (renomeado para {progs[a]}) ainda aparece em {f.relative_to(projeto)}')
    for x in sorted(set(trans.values()) - trans_vistas):
        erros.append(f'transação {x} não aparece no código')
    for x in sorted(funcs_esperados - funcs_vistos):
        erros.append(f'programa funcional {x} da fase 19 não aparece no código')
    corp_internos = [c for c in cmds if c['MQ_REQ'] in ('—', '')]

    # endpoints: prefixo e contrato
    for e in eps:
        if not e['caminho'].startswith(prefixo + '/'):
            erros.append(f'endpoint {e["metodo"]} {e["caminho"]} ({e["arquivo"]}:{e["linha"]}) sem o prefixo {prefixo}')
    for c in feign:
        if not c['caminho'].startswith(prefixo + '/'):
            erros.append(f'cliente Feign {c["cliente"]} chama {c["caminho"]} sem o prefixo {prefixo}')
    impl_de = {}
    for o in ops:
        repo = repo_de.get(o['app'])
        # o VAS da consulta consolidada fica no mesmo repositório do serviço de liberação, sob /consulta-consolidada (ADR-004)
        # o contrato traz só a versão (/v1/...); o código acrescenta o prefixo da plataforma (ADR-007)
        caminho = prefixo_de.get(o['app'], '') + re.sub(r'^/v\d+(?=/)', '', o['caminho'])
        cands = [e for e in eps if e['modulo'] == repo and e['metodo'] == o['metodo'] and e['sem_prefixo'] == caminho]
        if not cands:
            erros.append(f'operação {o["metodo"]} {o["caminho"]} ({o["app"]}) sem endpoint implementado em {repo}')
        else:
            impl_de[(o['app'], o['metodo'], o['caminho'])] = cands[0]

    evid = {}
    for a in adr['adrs']:
        for x in a.get('evidencias', []):
            loc = localizar(projeto, x)
            if loc is None:
                erros.append(f'{a["id"]}: âncora não encontrada em {x["arquivo"]}: {x["ancora"]}')
            evid[(a['id'], x['arquivo'], x['ancora'])] = loc
    if erros:
        raise SystemExit('registro de decisões recusado:\n  ' + '\n  '.join(erros))
    antigas_nas_fases, progs_nas_fases = {}, {}
    for fase in ('19 - target-architecture', '20 - contracts', '21 - traceability-to-be'):
        txt = (Path(ana) / fase / 'ia' / 'report.json').read_text(encoding='utf-8') if (Path(ana) / fase / 'ia' / 'report.json').exists() else ''
        antigas_nas_fases[fase] = sum(txt.count(a) for a in antigas)
        progs_nas_fases[fase] = sum(txt.count(a) for a in progs)
    return {'antigas_nas_fases': antigas_nas_fases, 'progs_nas_fases': progs_nas_fases, 'progs': progs, 'trans': trans, 'cmds': linhas_filas, 'corp_internos': corp_internos, 'recursos': recursos, 'repo_de': repo_de, 'dda': dda, 'ops': ops, 'impl_de': impl_de,
            'eps': eps, 'feign': feign, 'evid': evid, 'usadas_mod': usadas_mod, 'sqlt': sqlt}


# ── blocos ───────────────────────────────────────────────────────────────────
def colunas(titulo, nomes, nos, arestas, nota, nw=330):
    g = rm.G(titulo, nos, arestas, kind='colunas', note=nota)
    g['columns'] = [{'name': n, 'color': c} for n, c in nomes]
    g['nw'] = nw
    return g


def diagrama_registrado(k, dg, C):
    """Diagrama em colunas registrado na ADR. Nó com 'pdc' cita um processo do PDC, conferido na fase 14; nó com 'pdc_contar' (expressão regular) troca {n}
    no rótulo pela quantidade de processos distintos que casam, sem os citados em outros nós. Processo citado que não existe recusa o relatório."""
    import gerar_enhancement_proposals as EP
    procs = {p: tr for p, tr, _ in EP.processos_pdc(C['ana']) if p}
    citados = {n['pdc'] for n in dg['nos'] if n.get('pdc')}
    falta = sorted(c for c in citados if c not in procs)
    if falta:
        raise SystemExit(f'registro de decisões recusado:\n  {k}: processo do PDC citado no diagrama não está na fase 14: {", ".join(falta)}')
    nos = []
    for n in dg['nos']:
        n = dict(n)
        if n.get('pdc'):
            n['sub'] = f'{n["pdc"]} ({procs[n["pdc"]]})' + (f' · {n["sub"]}' if n.get('sub') else '')
        if n.get('pdc_contar'):
            qt = str(sum(1 for p in procs if re.search(n['pdc_contar'], p) and p not in citados))
            n['label'], n['sub'] = n['label'].replace('{n}', qt), (n.get('sub') or '').replace('{n}', qt)
        if n.get('cor') in COR:
            n['cor'] = COR[n['cor']]
        nos.append({x: v for x, v in n.items() if x not in ('pdc', 'pdc_contar')})
    g = colunas(f'{k} · {dg["titulo"]}', [(c, COR.get(cor, cor)) for c, cor in dg['colunas']], nos, dg['arestas'], dg.get('nota'), nw=dg.get('largura', 220))
    if dg.get('legenda'):
        g['legenda'] = [{'texto': x[0], 'cor': COR.get(x[1], x[1]), 'tracejado': len(x) > 2 and x[2] == 'tracejado'} for x in dg['legenda']]
    return g


def ficha(a, adr):
    return rm.T(f'{a["id"]} · ficha', ['Campo', 'Conteúdo'], [
        ('Título', a['titulo']), ('Status', a['status']), ('Data', a.get('data', adr['data'])), ('Registrada por', adr['registrado_por']),
        ('Fases de origem', ', '.join(a['fases']))])


def corpo(a, C, projeto):
    blocos = [rm.X(a['contexto'], 'Contexto')] + [rm.X(n['texto'], n['titulo']) for n in a.get('notas', [])] + \
             [rm.T(f'{a["id"]} · {t["titulo"]}', t['colunas'], [tuple(l) for l in t['linhas']], note=t.get('nota')) for t in a.get('tabelas', [])] + \
             [diagrama_registrado(a['id'], dg, C) for dg in a.get('diagramas', [])] + [rm.X(a['decisao'], 'Decisão'),
              rm.T(f'{a["id"]} · alternativas consideradas', ['Alternativa', 'Por que não foi escolhida'], [(x['alternativa'], x['motivo']) for x in a['alternativas']]),
              rm.T(f'{a["id"]} · consequências', ['Tipo', 'Consequência'], [(x['tipo'], x['texto']) for x in a['consequencias']])]
    return blocos


def evidencias(a, C):
    rows = []
    for x in a.get('evidencias', []):
        ln, trecho = C['evid'][(a['id'], x['arquivo'], x['ancora'])]
        rows.append((x['arquivo'], ln, trecho, x['papel']))
    return rm.T(f'{a["id"]} · evidências no repositório', ['Arquivo', 'Linha', 'Trecho', 'O que mostra'], rows,
                note='Linhas procuradas no repositório na geração deste relatório; uma âncora que não existe recusa o relatório.')


def blocos_adr001(C):
    cmds = [c for c in C['cmds'] if not c['corp']]
    nos, ar = [], []
    for r in sorted({c['repo'] for c in cmds}):
        nos.append({'id': 'r:' + r, 'label': r, 'col': 0, 'sub': 'repositório (DDA)'})
    tabs = sorted({c['tabela'] for c in cmds})
    for c in cmds:
        k = c['cmd']
        nos += [{'id': 'q:' + k, 'label': curto(c['req_para']), 'col': 1, 'sub': 'FR … .REQ / FL … .RSP', 'detail': f'{c["req_para"]} / {c["rsp_para"]}'},
                {'id': 'a:' + k, 'label': re.sub(r'^\w+\.QL\.REQ\.\w+\.', '', c['req_alta']), 'col': 2, 'sub': 'QL.REQ / QR.RSP (alta)', 'detail': f'{c["req_alta"]} / {c["rsp_alta"]}'},
                {'id': 'p:' + k, 'label': c['func'] if c['func'] == c['prog'] else f'{c["prog"]} → {c["func"]}', 'col': 3, 'sub': f'{k} · {c["op"]}', 'sub2': f'{c["cpy_req"]} / {c["cpy_rsp"]}'}]
        ar += [{'from': 'r:' + c['repo'], 'to': 'q:' + k}, {'from': 'q:' + k, 'to': 'a:' + k}, {'from': 'a:' + k, 'to': 'p:' + k}, {'from': 'p:' + k, 'to': 't:' + c['tabela']}]
    nos += [{'id': 't:' + t, 'label': t, 'col': 4, 'sub': 'tabela DB2'} for t in tabs]
    g = colunas('Comandos SQL pelas filas: repositório → fila de baixa → fila de alta → PROGRAM_DB2 → tabela DB2',
                [('Repositório (DDA)', COR['app']), ('Fila de baixa (pedido e resposta)', COR['fila']), ('Fila de alta', COR['alta']),
                 ('PROGRAM_DB2 (copybooks)', COR['prog']), ('Tabela DB2', COR['dado'])], nos, ar,
                'O pedido segue da esquerda para a direita; a resposta volta pelo par de resposta de cada nó (FL … .RSP e … .QR.RSP …). Nomes das filas de baixa já com a ADR-005.', nw=250)
    co = any(c['func'] != c['prog'] for c in cmds)   # coordenador (lê as filas) separado do funcional (executa o SQL)
    t = rm.T('Comandos SQL executados por PROGRAM_DB2', ['Comando SQL (fase 10)', 'Operação', 'Tabela DB2', 'Classes de domínio', 'Aplicação (fase 19)', 'Repositório (DDA)',
                                                         'Comando no repositório', *(['Coordenador (PROGRAM_COORD)'] if co else []), 'PROGRAM_DB2', 'Copybook de requisição', 'Copybook de resposta'],
             [(c['cmd'], c['op'], c['tabela'], c['classes'], c['app'], c['repo'], c['comando_mod'], *((c['prog'],) if co else ()), c['func'], c['cpy_req'], c['cpy_rsp']) for c in cmds])
    return [g, t]


def blocos_adr002(C):
    corp = [c for c in C['cmds'] if c['corp']]
    nos, ar = [], []
    for r in sorted({c['repo'] for c in corp}):
        nos.append({'id': 'r:' + r, 'label': r, 'col': 0, 'sub': 'repositório (DDA)'})
    for c in corp:
        k = c['cmd']
        nos += [{'id': 'q:' + k, 'label': curto(c['req_para']), 'col': 1, 'sub': 'FR … .REQ / FL … .RSP', 'detail': f'{c["req_para"]} / {c["rsp_para"]}'},
                {'id': 'p:' + k, 'label': c['func'] if c['func'] == c['prog'] else f'{c["prog"]} → {c["func"]}', 'col': 2, 'sub': 'PROGRAM_CORP', 'sub2': f'{c["cpy_req"]} / {c["cpy_rsp"]}'},
                {'id': 'c:' + k, 'label': k, 'col': 3, 'sub': 'programa corporativo original'}]
        ar += [{'from': 'r:' + c['repo'], 'to': 'q:' + k}, {'from': 'q:' + k, 'to': 'p:' + k}, {'from': 'p:' + k, 'to': 'c:' + k}]
    internos = []
    for c in C['corp_internos']:
        cmd = c['Comando (ou programa corporativo chamado)']
        m = re.search(r'programa corporativo (\w+)(?:, chamado por (\w+))?', c['PROGRAM_DB2 ou PROGRAM_CORP'])
        dono, chamador = m.group(1), m.group(2) or m.group(1)
        op, tab = C['sqlt'].get(cmd, (c['Operação'], ''))
        nos.append({'id': 's:' + cmd, 'label': cmd, 'col': 4, 'sub': f'{op} {tab}', 'sub2': f'no {dono}' + (f' (CICS LINK do {chamador})' if dono != chamador else '')})
        ar.append({'from': 'c:' + chamador, 'to': 's:' + cmd})
        internos.append((cmd, op, tab, c['Classes de domínio acessadas'], dono, '' if dono == chamador else f'{dono}, chamado por {chamador} (CICS LINK)', c['Executado por'],
                         C['repo_de'][c['Executado por']]))
    g = colunas('Programas corporativos pelas filas: repositório → fila de baixa → PROGRAM_CORP → programa corporativo → comandos SQL que ele executa',
                [('Repositório (DDA)', COR['app']), ('Fila de baixa (pedido e resposta)', COR['fila']), ('PROGRAM_CORP (copybooks)', COR['prog']),
                 ('Programa corporativo', COR['antes']), ('Comando SQL do corporativo (sem fila)', COR['dado'])], nos, ar,
                'Os comandos SQL da última coluna continuam dentro do programa corporativo: não ganham fila nem programa novo.', nw=250)
    co = any(c['func'] != c['prog'] for c in corp)
    t1 = rm.T('Programas corporativos chamados por PROGRAM_CORP', ['Programa corporativo', 'Aplicação (fase 19)', 'Repositório (DDA)', 'Comando no repositório',
                                                                   *(['Coordenador (PROGRAM_COORD)'] if co else []), 'PROGRAM_CORP', 'Fila de baixa de pedido', 'Fila de baixa de resposta', 'Copybook de requisição', 'Copybook de resposta'],
              [(c['cmd'], c['app'], c['repo'], c['comando_mod'], *((c['prog'],) if co else ()), c['func'], c['req_para'], c['rsp_para'], c['cpy_req'], c['cpy_rsp']) for c in corp])
    t2 = rm.T('Comandos SQL dos corporativos que não ganham fila nem programa', ['Comando SQL (fase 10)', 'Operação', 'Tabela', 'Classes de domínio', 'Executado no programa',
                                                                                'Chamada interna', 'Aplicação (fase 19)', 'Repositório (DDA)'], internos)
    return [g, t1, t2]


def blocos_adr003(C, adr, projeto):
    usos = [u for u in USOS if any(r['uso'] == u for r in adr['repositorios_dda'])]
    nos = [{'id': 'u:' + u, 'label': USOS[u], 'col': 0, 'cor': COR_USO[u]} for u in usos]
    ar = []
    apps_de = defaultdict(list)
    for app, repo in C['repo_de'].items():
        apps_de[repo].append(app)
    for r in adr['repositorios_dda']:
        nos.append({'id': 'd:' + r['repositorio'], 'label': r['repositorio'], 'col': 1, 'sub': r['tipo'], 'cor': COR_USO[r['uso']]})
        ar.append({'from': 'u:' + r['uso'], 'to': 'd:' + r['repositorio']})
    g = colunas('Repositórios do DDA por uso na POC', [('Uso na POC', COR['dado']), ('Repositório do DDA', COR['app'])], nos, ar,
                'A cor da borda é a do uso. O encaixe das aplicações da fase 19 em cada repositório está na ADR-004.')
    g['legenda'] = [{'texto': USOS[u], 'cor': COR_USO[u]} for u in usos]
    rows = []
    for r in adr['repositorios_dda']:
        rows.append((r['repositorio'], r['tipo'], USOS[r['uso']], r['detalhe'], ', '.join(sorted(apps_de.get(r['repositorio'], []))) or '—',
                     'sim' if r['repositorio'] in C['modulos'] else 'não'))
    t = rm.T('Repositórios do DDA', ['Repositório', 'Tipo', 'Uso na POC', 'Detalhe', 'Aplicações da fase 19 que contempla', f'Módulo no {projeto.name}'], rows,
             note=f'Módulo no {projeto.name}: há uma pasta com o nome do repositório, com pom.xml ou package.json.')
    return [g, t]


def blocos_adr004(C, adr, a, projeto):
    rec, repo_de = C['recursos'], C['repo_de']
    obs = {e['aplicacao']: e['observacao'] for e in adr['encaixe']}
    nos, ar = [], []
    for app in repo_de:
        nos.append({'id': 'a:' + app, 'label': app, 'col': 0, 'sub': f'{rec[app]["Tipo"]} · {rec[app]["Contexto de origem (fase 18)"]}', 'cor': COR['antes']})
    for repo in dict.fromkeys(repo_de.values()):
        nos.append({'id': 'r:' + repo, 'label': repo, 'col': 1, 'sub': 'repositório do DDA', 'cor': COR['depois']})
    ar = [{'from': 'a:' + a, 'to': 'r:' + r} for a, r in repo_de.items()]
    g = colunas('De-para: aplicação da arquitetura alvo (fase 19) → repositório do DDA', [('Aplicação (fase 19)', COR['antes']), ('Repositório do DDA', COR['depois'])],
                nos, ar, 'Um repositório pode contemplar mais de uma aplicação da fase 19.', nw=360)
    ops_de = defaultdict(list)
    for o in C['ops']:
        ops_de[o['app']].append(o)
    filas_de = defaultdict(list)
    for c in C['cmds']:
        filas_de[c['app']].append(c['req_para'])
    rows = []
    for app, repo in repo_de.items():
        eps = [C['impl_de'][(o['app'], o['metodo'], o['caminho'])] for o in ops_de.get(app, [])]
        rows.append((app, rec[app]['Tipo'], rec[app]['Nome'], rec[app]['Contexto de origem (fase 18)'], repo, 'sim' if repo in C['modulos'] else 'não (criado depois)',
                     '; '.join(f'{e["metodo"]} {e["caminho"]}' for e in eps) or '—', '; '.join(filas_de.get(app, [])) or '—', obs.get(app) or ''))
    t = rm.T('Encaixe das aplicações da fase 19 nos repositórios do DDA', ['Aplicação (fase 19)', 'Tipo', 'Nome', 'Contexto (fase 18)', 'Repositório do DDA',
                                                                           f'Módulo no {projeto.name}', 'Endpoints implementados', 'Filas de baixa de pedido', 'Observação'], rows)
    mv = a.get('codigo_movido')
    if not mv:
        return [g, t]
    t2 = rm.T('Código movido no repositório por causa do encaixe', ['Item', 'De (módulo)', 'Para (módulo)'], [(m, mv['de'], mv['para']) for m in mv['itens']],
              note=mv.get('observacao'))
    return [g, t, t2]


def blocos_adr005(C):
    cmds = C['cmds']
    nos, ar = [], []
    for c in cmds:
        k = c['cmd']
        nos += [{'id': 'de:' + k, 'label': c['req_de'], 'col': 0, 'sub': c['rsp_de'], 'cor': COR['antes']},
                {'id': 'pa:' + k, 'label': c['req_para'], 'col': 1, 'sub': c['rsp_para'], 'sub2': f'{c["repo"]} · {c["prog"]}', 'cor': COR['depois']}]
        ar.append({'from': 'de:' + k, 'to': 'pa:' + k})
    g = colunas('De-para das filas de baixa: pedido (FR … .REQ) e resposta (FL … .RSP)', [('Antes (contexto da fase 19)', COR['antes']), ('Depois (aplicação dona)', COR['depois'])],
                nos, ar, 'Cada caixa traz a fila de pedido e, abaixo, a de resposta, que recebe o mesmo nome. Na caixa da direita: o repositório dono e o programa mainframe.', nw=420)
    ctx = defaultdict(set)
    for c in cmds:
        ctx[(c['req_de'].split('.')[2], c['req_para'].split('.')[2])].add(c['repo'])
    t0 = rm.T('De-para do segmento de contexto', ['Antes', 'Depois', 'Repositório dono'], [(a, b, ', '.join(sorted(r))) for (a, b), r in sorted(ctx.items())])
    rows = [(c['cmd'], 'programa corporativo' if c['corp'] else 'comando SQL', c['op'], c['tabela'] or '—', c['app'], c['repo'], c['comando_mod'],
             c['req_de'], c['req_para'], c['req_alta'], c['cpy_req'], c['prog'], ('PROGRAM_CORP' if c['corp'] else 'PROGRAM_DB2') if c['func'] == c['prog'] else f'PROGRAM_COORD (funcional {c["func"]}, {"PROGRAM_CORP" if c["corp"] else "PROGRAM_DB2"})', c['rsp_alta'], c['rsp_de'], c['rsp_para'],
             c['cpy_rsp'], len(c['req_para'])) for c in cmds]
    t = rm.T('Filas, programas e copybooks de cada comando SQL e programa corporativo',
             ['Comando SQL ou programa corporativo', 'Tipo', 'Operação', 'Tabela DB2', 'Aplicação (fase 19)', 'Repositório (DDA)', 'Comando no repositório',
              'MQ_REQ baixa (antes)', 'MQ_REQ baixa (depois)', 'MQ_REQ alta', 'Copybook de requisição', 'Programa executor', 'Tipo do executor', 'MQ_RSP alta',
              'MQ_RSP baixa (antes)', 'MQ_RSP baixa (depois)', 'Copybook de resposta', 'Posições do nome novo'], rows,
             note='Fluxo do pedido: repositório → MQ_REQ baixa → MQ_REQ alta → programa executor; a resposta volta por MQ_RSP alta → MQ_RSP baixa. As filas de alta, '
                  'os programas e os copybooks não mudam. Conferido no repositório: cada fila nova está definida no config.mqsc, as filas de alta e de baixa estão ligadas (QREMOTE nos dois gerenciadores) e só o '
                  'módulo do repositório dono a usa, com os mesmos copybooks; nenhuma fila antiga aparece no código.')
    return [g, t0, t]


def blocos_adr006(C, a, prefixo):
    repo = a['repositorio']
    apps = sorted({o['app'] for o in C['ops'] if C['repo_de'].get(o['app']) == repo})
    ops = [o for o in C['ops'] if C['repo_de'].get(o['app']) == repo]
    filas = [c for c in C['cmds'] if c['repo'] == repo]
    nos, ar, rows = [], [], []
    for o in ops:
        e = C['impl_de'][(o['app'], o['metodo'], o['caminho'])]
        k = o['operationId']
        nos += [{'id': 'c:' + k, 'label': f'{o["metodo"]} {o["caminho"]}', 'col': 0, 'sub': f'{o["app"]} · {k}', 'cor': COR['antes']},
                {'id': 'e:' + k, 'label': f'{e["metodo"]} {e["caminho"]}', 'col': 1, 'sub': f'{e["classe"]}:{e["linha"]}', 'cor': COR['depois']}]
        ar.append({'from': 'c:' + k, 'to': 'e:' + k})
        rows.append((o['operationId'], o['func'], f'{o["metodo"]} {o["caminho"]}', f'{e["metodo"]} {e["caminho"]}', f'{e["arquivo"]}:{e["linha"]}'))
    g = colunas(f'De-para: operação do contrato (fase 20) → endpoint novo no {repo}',
                [(f'Contrato {", ".join(apps)} (fase 20)', COR['antes']), (f'{repo} (novo, {prefixo})', COR['depois'])], nos, ar,
                f'Os endpoints que o {repo} já tem não mudam; os novos ficam sob {prefixo} para não colidir com eles.', nw=360)
    t = rm.T(f'Endpoints criados no {repo} existente', ['operationId', 'Funcionalidades', 'Caminho no contrato (fase 20)', 'Endpoint implementado',
                                                                                     'Código (arquivo:linha)'], rows)
    t2 = rm.T(f'Comandos mainframe do {repo}', ['Comando SQL', 'Operação', 'Tabela DB2', 'Comando no repositório', 'MQ_REQ baixa', 'MQ_RSP baixa',
                                                                       'PROGRAM_DB2', 'Copybook de requisição', 'Copybook de resposta'],
              [(c['cmd'], c['op'], c['tabela'], c['comando_mod'], c['req_para'], c['rsp_para'], c['prog'], c['cpy_req'], c['cpy_rsp']) for c in filas])
    return [g, t, t2]


def blocos_adr007(C, prefixo):
    """De-para do caminho do contrato (fase 20, só com a versão) para o implementado (prefixo da plataforma na frente)."""
    plataforma, versao = prefixo.rsplit('/v', 1)[0], '/v' + prefixo.rsplit('/v', 1)[1]
    ops_de = {}
    for o in C['ops']:
        e = C['impl_de'][(o['app'], o['metodo'], o['caminho'])]
        ops_de.setdefault((e['arquivo'], e['linha']), []).append(o)
    nos, ar, rows = [], [], []
    for e in sorted(C['eps'], key=lambda e: (e['modulo'], e['caminho'], e['metodo'])):
        k = f'{e["modulo"]}:{e["metodo"]}:{e["caminho"]}'
        ant = versao + e['sem_prefixo']
        nos += [{'id': 'a:' + k, 'label': f'{e["metodo"]} {ant}', 'col': 0, 'sub': e['modulo'], 'cor': COR['antes']},
                {'id': 'n:' + k, 'label': f'{e["metodo"]} {e["caminho"]}', 'col': 1, 'sub': f'{e["classe"]}:{e["linha"]}', 'cor': COR['depois']}]
        ar.append({'from': 'a:' + k, 'to': 'n:' + k})
        cs = ops_de.get((e['arquivo'], e['linha']), [])
        rows.append((e['modulo'], e['metodo'], ant, e['caminho'], e['operationId'] or '—', '; '.join(f'{o["app"]} {o["metodo"]} {o["caminho"]}' for o in cs) or '—',
                     f'{e["arquivo"]}:{e["linha"]}'))
    g = colunas(f'De-para dos endpoints: caminho do contrato → prefixo {plataforma}', [('Contrato (fase 20)', COR['antes']), (f'Implementado (prefixo {plataforma})', COR['depois'])], nos, ar,
                f'Todos os endpoints de negócio dos repositórios da POC; endpoints técnicos (/actuator, /v3/api-docs, /swagger-ui) ficam fora do prefixo {plataforma}.', nw=430)
    t = rm.T(f'Endpoints implementados com o prefixo {plataforma}', ['Repositório', 'Método', 'Caminho no contrato', 'Caminho implementado', 'operationId', 'Operações do contrato (fase 20)',
                                                              'Código (arquivo:linha)'], rows,
             note=f'Conferido no repositório: todo @GetMapping/@PostMapping/@PutMapping de classe @RestController está sob @RequestMapping("{prefixo}"): o prefixo {plataforma} na frente da versão {versao} do contrato.')
    cons = [(c['modulo'], c['cliente'], f'${{{c["url"]}}}', c['metodo'], c['caminho'], f'{c["arquivo"]}:{c["linha"]}') for c in C['feign']]
    t2 = rm.T('Consumidores: clientes Feign do BFF', ['Repositório', 'Cliente', 'URL base', 'Método', 'Caminho chamado', 'Código (arquivo:linha)'], cons)
    return [g, t, t2]


def blocos_adr008(C):
    """De-para dos programas executores: nome da fase 19 → nome que será criado, com o comando, as filas de alta e os copybooks de cada um."""
    mud = [c for c in C['cmds'] if c['prog_de'] != c['prog']]
    nos, ar = [], []
    for c in mud:
        k = c['cmd']
        nos += [{'id': 'de:' + k, 'label': c['prog_de'], 'col': 0, 'sub': c['cmd'], 'cor': COR['antes']},
                {'id': 'pa:' + k, 'label': c['prog'], 'col': 1, 'sub': c['req_alta'], 'sub2': f'{c["cpy_req"]} / {c["cpy_rsp"]}', 'cor': COR['depois']}]
        ar.append({'from': 'de:' + k, 'to': 'pa:' + k})
    g = colunas('De-para dos programas executores', [('Antes (regra da fase 19)', COR['antes']), ('Depois (a criar no Mainframe)', COR['depois'])], nos, ar,
                'Na caixa da esquerda, o comando que o programa executa; na da direita, a fila de alta de pedido e os copybooks, que não mudam.', nw=420)
    rows = [(c['cmd'], 'programa corporativo' if c['corp'] else 'comando SQL', c['op'], c['tabela'] or '—', c['prog_de'], c['prog'], c['req_alta'], c['rsp_alta'],
             c['cpy_req'], c['cpy_rsp'], c['repo']) for c in mud]
    t = rm.T('Programas executores renomeados', ['Comando SQL ou programa corporativo', 'Tipo', 'Operação', 'Tabela DB2', 'Programa (fase 19)', 'Programa (novo)',
                                                'MQ_REQ alta', 'MQ_RSP alta', 'Copybook de requisição', 'Copybook de resposta', 'Repositório (DDA)'], rows,
             note=f'{len(mud)} de {len(C["cmds"])} programas mudam de nome; os demais mantêm o da fase 19. Conferido no repositório: nenhum nome anterior aparece no código '
                  '(programas, definições de CICS e MQ, região CICS local, configuração e testes).')
    return [g, t]


def blocos_adr009(C):
    """Pares coordenador e funcional: o coordenador lê a fila de alta e chama o funcional, que executa o SQL ou chama o programa corporativo."""
    pares = [c for c in C['cmds'] if c['func'] != c['prog']]
    nos, ar = [], []
    for c in pares:
        k = c['cmd']
        dest = ('c:' + k, k, 'programa corporativo') if c['corp'] else ('t:' + (c['tabela'] or k), c['tabela'] or '—', 'tabela DB2')
        nos += [{'id': 'a:' + k, 'label': re.sub(r'^\w+\.QL\.REQ\.\w+\.', '', c['req_alta']), 'col': 0, 'sub': 'fila de alta (pedido e resposta)', 'detail': f'{c["req_alta"]} / {c["rsp_alta"]}'},
                {'id': 'co:' + k, 'label': c['prog'], 'col': 1, 'sub': 'PROGRAM_COORD', 'sub2': f'{c["cpy_req"]} / {c["cpy_rsp"]}'},
                {'id': 'fu:' + k, 'label': c['func'], 'col': 2, 'sub': 'PROGRAM_CORP' if c['corp'] else f'PROGRAM_DB2 · {c["op"]}'}]
        if dest[0] not in {n['id'] for n in nos}:
            nos.append({'id': dest[0], 'label': dest[1], 'col': 3, 'sub': dest[2]})
        ar += [{'from': 'a:' + k, 'to': 'co:' + k}, {'from': 'co:' + k, 'to': 'fu:' + k}, {'from': 'fu:' + k, 'to': dest[0]}]
    g = colunas('Pares coordenador e funcional: fila de alta → coordenador → funcional → DB2 ou programa corporativo',
                [('Fila de alta', COR['alta']), ('Coordenador', COR['prog']), ('Funcional', COR['depois']), ('Tabela DB2 ou programa corporativo', COR['dado'])], nos, ar,
                'O coordenador lê a fila de alta de pedido, chama o funcional com EXEC CICS LINK (canal e containers, na mesma tarefa) e responde na fila de alta de resposta.', nw=250)
    t = rm.T('Coordenadores e funcionais de cada comando', ['Comando SQL ou programa corporativo', 'Tipo', 'Operação', 'Tabela DB2', 'Coordenador (PROGRAM_COORD)', 'Funcional',
                                                           'Tipo do funcional', 'MQ_REQ alta', 'MQ_RSP alta', 'Copybook de requisição', 'Copybook de resposta', 'Repositório (DDA)'],
             [(c['cmd'], 'programa corporativo' if c['corp'] else 'comando SQL', c['op'], c['tabela'] or '—', c['prog'], c['func'], 'PROGRAM_CORP' if c['corp'] else 'PROGRAM_DB2',
               c['req_alta'], c['rsp_alta'], c['cpy_req'], c['cpy_rsp'], c['repo']) for c in pares],
             note=f'{len(pares)} pares. Conferido no repositório: todo funcional da fase 19 aparece no código.')
    return [g, t]


def blocos_adr010(C):
    """De-para dos nomes das transações CICS."""
    nos, ar = [], []
    for de, para in sorted(C['trans'].items(), key=lambda x: x[1]):
        nos += [{'id': 'de:' + de, 'label': de, 'col': 0, 'cor': COR['antes']}, {'id': 'pa:' + para, 'label': para, 'col': 1, 'cor': COR['depois']}]
        ar.append({'from': 'de:' + de, 'to': 'pa:' + para})
    g = colunas('De-para das transações CICS', [('Antes (proposta)', COR['antes']), ('Depois', COR['depois'])], nos, ar,
                'Conferido no repositório: toda transação nova aparece no código e nenhuma anterior ficou.', nw=160)
    return [g]


def _raiz(nome, C):
    """Pasta-base de um arquivo citado na ADR: 'projeto' (o repositório) ou uma pasta do pipeline.config.json da análise (fontes, aplicacao, pdc...)."""
    if nome in (None, 'projeto'):
        return Path(C['projeto'])
    cfg = Path(C['ana']).resolve().parent / 'pipeline.config.json'
    if not cfg.exists() or nome not in json.loads(cfg.read_text(encoding='utf-8')):
        raise SystemExit(f'registro de decisões recusado: pasta "{nome}" não está em {cfg}')
    return (cfg.parent / json.loads(cfg.read_text(encoding='utf-8'))[nome]).resolve()


def _exibir(p, C):
    """Caminho do arquivo a partir da pasta que contém o repositório (por exemplo bradesco-seguros/tcap/codigo/COBOL/X.CBL)."""
    try:
        return Path(p).resolve().relative_to(Path(C['projeto']).resolve().parent).as_posix()
    except ValueError:
        return Path(p).as_posix()


def _linhas(caminho):
    b = caminho.read_bytes()
    try:
        return b.decode('utf-8').splitlines()
    except UnicodeDecodeError:
        return b.decode('latin-1').splitlines()


def _sql_do_fonte(ref, C, quem):
    """Comando EXEC SQL do fonte COBOL que contém a âncora: (texto do comando sem EXEC SQL/END-EXEC e sem as colunas de sequência, linha inicial, caminho exibido)."""
    p = _raiz(ref.get('raiz'), C) / ref['arquivo']
    if not p.exists():
        raise SystemExit(f'registro de decisões recusado: {quem}: {ref["arquivo"]} não existe')
    ls = _linhas(p)
    i = next((n for n, l in enumerate(ls) if ref['ancora'] in l), None)
    if i is None:
        raise SystemExit(f'registro de decisões recusado: {quem}: âncora não encontrada em {ref["arquivo"]}: {ref["ancora"]}')
    ini = next(n for n in range(i, -1, -1) if 'EXEC SQL' in ls[n].upper())
    fim = next(n for n in range(i, len(ls)) if 'END-EXEC' in ls[n].upper())
    corpo = [l[6:72] for l in ls[ini:fim + 1] if len(l) < 7 or l[6] not in '*/']
    txt = re.sub(r'^\s*EXEC\s+SQL\s*|\s*END-EXEC\.?\s*$', '', '\n'.join(corpo).strip(), flags=re.I)
    return txt.strip(), ini + 1, _exibir(p, C)


def _trecho_do_fonte(ref, C, quem):
    """Trecho de código entre a linha da âncora de início e a linha seguinte com a âncora de fim (a primeira, ou a n-ésima com ocorrencia_fim), inclusive,
    com o número das linhas."""
    p = _raiz(ref.get('raiz'), C) / ref['arquivo']
    ls = _linhas(p) if p.exists() else []
    i = next((n for n, l in enumerate(ls) if ref['inicio'] in l), None)
    fins = [n for n in range(i, len(ls)) if ref['fim'] in ls[n]] if i is not None else []
    j = fins[ref.get('ocorrencia_fim', 1) - 1] if len(fins) >= ref.get('ocorrencia_fim', 1) else None
    if i is None or j is None:
        raise SystemExit(f'registro de decisões recusado: {quem}: trecho não encontrado em {ref["arquivo"]}: {ref["inicio"]} … {ref["fim"]}')
    return '\n'.join(f'{n + 1:5d}  {ls[n].rstrip()}'.replace('\t', '    ') for n in range(i, j + 1)), i + 1, _exibir(p, C)


def blocos_dono_dados(a, C):
    """Detecção do dono de tabelas DB2 (a mesma da fase 23): quem grava e quem lê nos fontes e quem mantém pelo PDC fora do recorte, com a conclusão calculada."""
    import gerar_enhancement_proposals as EP
    erros = []
    t = EP.deteccao(a['id'], 0, a['dono_dados'], C['ana'], C['projeto'], erros, titulo=f'{a["id"]} · dono dos dados (calculado dos fontes e do PDC)')
    if erros:
        raise SystemExit('registro de decisões recusado:\n  ' + '\n  '.join(erros))
    return [t]


def blocos_consolidacao(a, C):
    """Consultas que a aplicação antiga juntava (uma chamada por consulta) e a consulta única que passa a fazer a junção: etapas, código e comandos
    SQL originais lidos dos fontes, diagramas antes e depois, destino de cada parte e quantidade de chamadas. Tudo vem do registro (a['consolidacao'])
    e dos fontes; o relatório é recusado quando um arquivo, uma âncora ou um trecho não existe."""
    k, cx = a['id'], a['consolidacao']
    out = [rm.T(f'{k} · antes: consultas que a aplicação antiga juntava', ['Etapa', 'Quem chama', 'Processo do PDC', 'Transação FWO', 'Coordenador', 'Funcional',
                                                                          'Tabela DB2', 'Copybooks', 'Execuções'],
                [(e['etapa'], e['chamador'], e['processo_pdc'], e['transacao'], e['coordenador'], e['funcional'], e['tabela'], e['copybooks'], e['execucoes'])
                 for e in cx['legado']], note=cx.get('nota_legado'))]
    for ref in cx.get('codigo_legado', []):
        txt, ln, onde = _trecho_do_fonte(ref, C, k)
        out.append(rm.COD(txt, f'{k} · aplicação antiga: {ref["titulo"]} ({onde}, linha {ln})'))
    for e in cx['legado']:
        for ref in e.get('sql', []):
            txt, ln, onde = _sql_do_fonte(ref, C, k)
            out.append(rm.SQL(txt, f'Antes · {e["funcional"]} — {ref.get("titulo") or e["etapa"]} ({onde}, linha {ln})'))
    nos, ar = [{'id': 'tela', 'label': cx['tela_legado'], 'col': 0, 'sub': 'aplicação antiga'}], []
    for n, e in enumerate(cx['legado']):
        nos += [{'id': f'p{n}', 'label': e['transacao'], 'col': 1, 'sub': e['processo_pdc'], 'sub2': e['execucoes']},
                {'id': f'c{n}', 'label': e['coordenador'], 'col': 2, 'sub': 'coordenador'},
                {'id': f'f{n}', 'label': e['funcional'], 'col': 3, 'sub': 'funcional'}]
        for t in [x.strip() for x in e['tabela'].split(',')]:
            if 't:' + t not in {x['id'] for x in nos}:
                nos.append({'id': 't:' + t, 'label': t, 'col': 4, 'sub': 'tabela DB2'})
            ar.append({'from': f'f{n}', 'to': 't:' + t})
        ar += [{'from': 'tela', 'to': f'p{n}'}, {'from': f'p{n}', 'to': f'c{n}'}, {'from': f'c{n}', 'to': f'f{n}'}]
    out.append(colunas(f'{k} · antes: uma chamada por consulta, juntadas pela aplicação antiga',
                       [('Aplicação antiga', COR['app']), ('Transação do PDC', COR['antes']), ('Coordenador', COR['prog']), ('Funcional', COR['prog']), ('Tabela DB2', COR['dado'])],
                       nos, ar, cx.get('nota_diagrama_legado'), nw=230))
    nos, ar = [], []
    for n, d in enumerate(cx['novo']):
        for i, (rot, sub) in enumerate([(d['tela'], 'tela'), (d['bff'], 'BFF'), (d['servico'], 'serviço'), (d['agregado'], 'agregado'),
                                        (d['fila'], 'fila de baixa (pedido)'), (d['coordenador'], 'coordenador'), (d['funcional'], 'funcional')]):
            nid = f'n{i}:{rot}'
            if nid not in {x['id'] for x in nos}:
                nos.append({'id': nid, 'label': rot, 'col': i, 'sub': sub})
            if i:
                ar.append({'from': f'n{i - 1}:{prev}', 'to': nid})
            prev = rot
        for t in d['tabelas']:
            if 't:' + t not in {x['id'] for x in nos}:
                nos.append({'id': 't:' + t, 'label': t, 'col': 7, 'sub': 'tabela DB2 (na junção)'})
            ar.append({'from': f'n6:{d["funcional"]}', 'to': 't:' + t})
    out.append(colunas(f'{k} · depois: uma consulta com a junção', [('Tela', COR['app']), ('BFF', COR['app']), ('Serviço', COR['depois']), ('Agregado', COR['depois']),
                                                                      ('Fila de baixa', COR['fila']),
                                                                      ('Coordenador', COR['prog']), ('Funcional', COR['prog']), ('Tabela DB2', COR['dado'])],
                       nos, ar, cx.get('nota_diagrama_novo'), nw=180))
    for d in cx['novo']:
        txt, ln, onde = _sql_do_fonte(d['sql'], C, k)
        out.append(rm.SQL(txt, f'Depois · {d["funcional"]} — {d["sql"].get("titulo", "")} ({onde}, linha {ln})'))
    out.append(rm.T(f'{k} · para onde foi cada parte', ['Antes (aplicação antiga)', 'Depois', 'Contexto · agregado', 'Onde está'],
                    [(x['antes'], x['depois'], x['contexto'], x['onde']) for x in cx['destino']]))
    if cx.get('chamadas'):
        out.append(rm.T(f'{k} · chamadas para montar uma página da listagem', ['Situação', 'Antes', 'Depois'], [(x['situacao'], x['antes'], x['depois']) for x in cx['chamadas']],
                        note=cx.get('nota_chamadas')))
    return out


def montar(adr, C, projeto):
    por_id = {a['id']: a for a in adr['adrs']}
    prefixo = adr['prefixo_api']
    blocos = {'comandos_sql': lambda a: blocos_adr001(C), 'programas_corporativos': lambda a: blocos_adr002(C), 'repositorios': lambda a: blocos_adr003(C, adr, projeto),
              'encaixe': lambda a: blocos_adr004(C, adr, a, projeto), 'filas': lambda a: blocos_adr005(C), 'endpoints_repositorio': lambda a: blocos_adr006(C, a, prefixo),
              'prefixo': lambda a: blocos_adr007(C, prefixo), 'programas': lambda a: blocos_adr008(C), 'funcionais': lambda a: blocos_adr009(C), 'transacoes': lambda a: blocos_adr010(C),
              'consolidacao': lambda a: blocos_consolidacao(a, C), 'dono_dados': lambda a: blocos_dono_dados(a, C)}
    extra = {a['id']: blocos[a['evidencias_calculadas']](a) if a.get('evidencias_calculadas') in blocos else [] for a in adr['adrs']}
    rotulos = {'encaixe': 'aplicação → repositório', 'filas': 'filas de baixa', 'endpoints_repositorio': 'endpoints do repositório existente',
               'prefixo': 'caminhos dos endpoints (prefixo /ni)', 'programas': 'programas executores', 'funcionais': 'executor → coordenador + funcional', 'transacoes': 'transações CICS'}
    nomenclatura = {a['id']: rotulos[a['evidencias_calculadas']] for a in adr['adrs'] if a.get('evidencias_calculadas') in rotulos}
    adr_de = lambda *tipos: ', '.join(a['id'] for a in adr['adrs'] if a.get('evidencias_calculadas') in tipos)   # noqa: E731
    indice = [(rm.with_links('', [rm.link(a['id'], FASE, a['id'].lower())]), a['titulo'], a['status'], a.get('data', adr['data']), ', '.join(f.split(' - ')[0] for f in a['fases']),
               nomenclatura.get(a['id'], '—')) for a in adr['adrs']]
    secs = [rm.S('indice', 'Decisões registradas', [
        rm.T('Decisões Arquiteturais', ['ADR', 'Título', 'Status', 'Data', 'Fases de origem', 'Mudança de nomenclatura (diagrama de-para)'], indice,
             ids=[a['id'].lower() for a in adr['adrs']]),
        rm.X('Como ler: cada ADR traz a ficha, o contexto, a decisão, as alternativas descartadas e as consequências, e é completada com as evidências calculadas dos '
             f'relatórios das fases 10 a 21 e do repositório {projeto.name}. As ADRs que mudam nomes têm um diagrama de-para e a tabela completa. Quando uma ADR muda '
             'um nome que aparece nas fases 19, 20 ou 21, vale o nome desta fase.')])]
    for a in adr['adrs']:
        secs.append(rm.S(a['id'].lower(), f'{a["id"]} · {a["titulo"]}', [ficha(a, adr)] + corpo(a, C, projeto) + extra[a['id']] + [evidencias(a, C)]))
    mv = next((a['codigo_movido'] for a in adr['adrs'] if a.get('codigo_movido')), None)
    adr_filas = adr_de('filas') or '—'
    af = C['antigas_nas_fases']
    situacao = lambda f, tema: (f'{af[f]} ocorrência(s) de nome antigo de fila: vale o de-para da {adr_filas}' if af[f] else f'já com os nomes novos das filas{tema}')   # noqa: E731
    pf = C['progs_nas_fases']
    progs_sit = lambda f: (f'; {pf[f]} ocorrência(s) de nome anterior de programa executor: vale o de-para da {adr_de("programas")}' if pf.get(f) else '')   # noqa: E731
    impacto = [('19 - target-architecture', f'Nomes lógicos das aplicações (o repositório de cada uma está na {adr_de("encaixe")}); ' + situacao('19 - target-architecture', '')
                + progs_sit('19 - target-architecture'), adr_de('repositorios', 'encaixe', 'filas', 'programas')),
               ('20 - contracts', f'Caminhos só com a versão da API; o prefixo da plataforma entra na implementação ({adr_de("prefixo")}); '
                + situacao('20 - contracts', ' nos copybooks'), adr_de('filas', 'prefixo')),
               ('21 - traceability-to-be', (f'Módulo das aplicações movidas ({mv["de"]} → {mv["para"]}); ' if mv else '') + situacao('21 - traceability-to-be', '')
                + progs_sit('21 - traceability-to-be'), adr_de('encaixe', 'filas', 'programas'))]
    secs.append(rm.S('impacto', 'Impacto nas fases anteriores', [
        rm.T('Como as fases anteriores refletem as decisões', ['Fase', 'Situação', 'ADR'], impacto,
             note='Conferido nos relatórios a cada geração desta fase. Nas divergências, vale esta fase.')]))
    secs.append(rm.S('criterio', 'Como o registro foi montado', [rm.X(
        'As decisões vêm do registro do dono da arquitetura (interpretacao-adr/adr.json), não de IA. As tabelas e os diagramas são calculados: comandos SQL, programas '
        'corporativos, filas e copybooks da fase 19; tabelas DB2 da fase 10; operações dos contratos da fase 20; filas, endpoints, clientes Feign e âncoras do repositório. '
        'O relatório é recusado quando uma fila nova não está no gerenciador local ou não é usada pelo repositório dono, quando uma fila antiga ou um nome anterior de programa ainda aparece, quando um '
        'endpoint ou cliente Feign está sem o prefixo, quando uma operação do contrato não tem endpoint ou quando uma âncora não existe.')]))
    n_corp = sum(1 for c in C['cmds'] if c['corp'])
    cards = [rm.card('decisões', len(adr['adrs'])), rm.card('repositórios do DDA', len(adr['repositorios_dda'])),
             rm.card('aplicações encaixadas', len(C['repo_de'])), rm.card('filas de baixa renomeadas', 2 * len(C['cmds'])),
             rm.card('programas mainframe (DB2 + CORP)', f'{len(C["cmds"]) - n_corp} + {n_corp}'), rm.card(f'endpoints em {adr["prefixo_api"]}', len(C['eps']))]
    return secs, cards


def main():
    args = sys.argv[1:]
    opc = {}
    for nome in ('--interpretacao', '--projeto'):
        if nome in args:
            i = args.index(nome)
            opc[nome] = Path(args[i + 1]).resolve()
            del args[i:i + 2]
    if not args or '--projeto' not in opc:
        sys.exit(__doc__)
    base = opc.get('--interpretacao', S.BASE)
    ana = Path(args[0])
    saida = Path(args[1]) if len(args) > 1 else ana
    adr = json.loads((Path(base) / INTERP / 'adr.json').read_text(encoding='utf-8'))
    projeto = opc['--projeto']
    MODULOS[:] = modulos_do_projeto(projeto, adr)
    C = calcular(ana, projeto, adr)
    C['modulos'] = set(MODULOS)
    C['ana'], C['projeto'] = ana, projeto
    secs, cards = montar(adr, C, projeto)
    rep = rm.model('Decisões Arquiteturais',
                   f'Decisões de arquitetura sobre a arquitetura alvo, completas com as evidências das fases 10 a 21 e do repositório {projeto.name}', cards, secs)
    S.escrever(saida, FASE, rep)
    print(f'{len(adr["adrs"])} decisões; {len(C["cmds"])} comandos com fila ({2 * len(C["cmds"])} filas de baixa renomeadas); {len(C["eps"])} endpoints em {adr["prefixo_api"]}')


if __name__ == '__main__':
    main()
