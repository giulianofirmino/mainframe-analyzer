#!/usr/bin/env python3
"""Mapa das fases: como as fases e os dados de cada uma se relacionam, para medir a utilidade de cada coisa mapeada.

  python3 tools/mapa_fases.py <pasta-da-analise> [arquivo.html] [--config pipeline.config.json]
  (padrão: <pasta-da-analise>/../mapa-das-fases.html; grava também o .json ao lado). Com --config, cada gerador roda de verdade, com a saída numa pasta
  temporária, e o mapa usa os arquivos que ele abriu (medido); sem --config, usa os literais do código (estimado).

Tudo é calculado do método e dos relatórios, sem nada fixo do sistema analisado:
  - fases e dados: as pastas da análise (NN-*/ia/report.json): tabelas (com linhas e colunas), diagramas e indicadores;
  - quem lê o quê:
      prompt de IA      as linhas `@ler fase= bloco= colunas=` de fases/prompts/prompt-*.md (fase, tabela e colunas) e as fases que o pipeline
                        entrega a mais a cada prompt (pipeline_analise.execucao.PROMPTS);
      gerador           as fases e os arquivos que o gerador abre ao rodar (com --config) e, nelas, as tabelas cujo título (ou o início longo dele)
                        aparece como literal no código do gerador e dos geradores que ele importa;
      relatório do motor as funções m_* que montam os relatórios das fases 0 a 9 (semantic_core), pelos nomes de fase que usam;
      cálculo do motor  a cadeia de tools/certify_from_zero.py (que resultado alimenta qual), pelos nomes das variáveis publicadas em cada fase;
  - utilidade: quantas fases consomem cada fase e cada tabela, por qual meio, se a fase chega (direta ou indiretamente) às fases de implementação
    e quais tabelas só servem à leitura humana (ninguém as lê);
  - impacto na implementação: as camadas (frontend, BFF, serviços, programas executores) pelo tipo das aplicações da arquitetura alvo, os módulos e as
    regras de cada camada pelo rastreio da implementação, e, por fase, se os dados citam artefatos da camada (direto) ou alimentam uma fase que cita (indireto)."""
import ast
import os
import shutil
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R / 'semantic_core'))
sys.path.insert(0, str(R.parent / 'pipeline' / 'src'))
import report_render as rr  # noqa: E402

ETAPAS, ETAPA_DA_FASE = rr.ETAPAS, rr.ETAPA_DA_FASE   # etapas do processo e a etapa de cada fase (definidas em report_render, usadas no índice lateral)
IMPLEMENTACAO = ('21', '22')   # fases que olham o código gerado: chegar a elas é chegar à solução
# entradas externas de cada fase (o que vem de fora da análise)
EXTERNAS = {'Fontes COBOL, copybooks e DCLGEN': ['00', '01', '02', '03', '04', '05', '06'], 'Cenários da análise dinâmica': ['07', '08', '09'],
            'XML do PDC': ['14', '15'], 'Aplicação web atual': ['15'], 'Código gerado e testes': ['21', '22'], 'Registro de decisões de arquitetura': ['22'], 'Registro de propostas de melhoria': ['23']}
CORES = {'prompt': '#8e44ad', 'gerador': '#1f5fa8', 'relatório do motor': '#5b6b7f', 'cálculo do motor': '#a06a00', 'externa': '#888888'}


def num(pasta):
    return pasta.split(' ')[0].split('-')[0]


# ── fases e dados ────────────────────────────────────────────────────────────
def inventario(ana):
    fases = {}
    for p in sorted(Path(ana).iterdir()):
        f = p / 'ia' / 'report.json'
        if not f.exists():
            continue
        d = json.loads(f.read_text(encoding='utf-8'))
        tabelas = {}
        graficos = 0
        for s in d['sections']:
            for b in s['blocks']:
                if b['type'] == 'table':
                    t = b.get('title') or s['title']
                    tabelas.setdefault(t, {'linhas': len(b['rows']), 'colunas': b['columns'], 'secao': s['title']})
                elif b['type'] == 'graph':
                    graficos += 1
        fases[p.name] = {'n': num(p.name), 'titulo': d['title'], 'tipo': rr.origem(p.name) or 'Determinística', 'etapa': ETAPA_DA_FASE.get(num(p.name), 'Reverse'),
                         'tabelas': tabelas, 'graficos': graficos, 'indicadores': {c['label']: c['value'] for c in d.get('summary', [])}}
    return fases


# ── quem lê o quê ────────────────────────────────────────────────────────────
def literais(codigo):
    out = []
    for no in ast.walk(ast.parse(codigo)):
        if isinstance(no, ast.Constant) and isinstance(no.value, str):
            out.append(no.value)
    return out


def leituras_prompts(fases):
    """(prompt, fase lida, tabela, colunas) do contrato @ler e das fases que o pipeline entrega a mais."""
    try:
        from pipeline_analise.execucao import PROMPTS
    except ImportError:
        PROMPTS = {}
    pasta_de = {f['n']: p for p, f in fases.items()}
    out = []
    for md in sorted((R / 'fases' / 'prompts').glob('prompt-*.md')):
        n = re.match(r'prompt-(\d+)', md.name).group(1)
        destino = PROMPTS.get(n, (None, None, []))[2]
        for fase, bloco, cols in re.findall(r'^@ler fase=(\d\d[a-z]?) bloco="([^"]+)" colunas="([^"]+)"', md.read_text(encoding='utf-8'), re.M):
            if fase in pasta_de:
                padrao = re.compile('^' + '.+'.join(re.escape(x) for x in re.split(r'\{[^}]*\}', bloco)) + ('' if bloco.endswith('}') else '.*') + '$')
                tabs = [t for t in fases[pasta_de[fase]]['tabelas'] if padrao.match(t)] or [bloco]   # {x} no bloco: qualquer texto naquela posição
                for t in tabs:
                    out.append({'meio': 'prompt', 'quem': f'prompt {n}', 'destinos': destino, 'fase': pasta_de[fase], 'tabela': t, 'colunas': cols.split('|')})
        for fase in PROMPTS.get(n, (None, None, [], [], []))[4]:
            if fase in pasta_de:
                out.append({'meio': 'prompt', 'quem': f'prompt {n}', 'destinos': destino, 'fase': pasta_de[fase], 'tabela': '*', 'colunas': []})
    return out


BOOT = r"""
import builtins, io, json, os, runpy, sys, atexit
lidos, alvo, _o = set(), os.path.realpath(os.environ['MAPA_ANALISE']), builtins.open
def _op(f, *a, **k):
    try:
        modo = a[0] if a else k.get('mode', 'r')
        p = os.path.realpath(os.fspath(f))
        if 'r' in modo and '+' not in modo and p.startswith(alvo + os.sep):
            lidos.add(os.path.relpath(p, alvo))
    except Exception:
        pass
    return _o(f, *a, **k)
builtins.open = io.open = _op
atexit.register(lambda: _o(os.environ['MAPA_SAIDA'], 'w', encoding='utf-8').write(json.dumps(sorted(lidos))))
script = sys.argv[1]
sys.argv = sys.argv[1:]
sys.path.insert(0, os.path.dirname(script))
runpy.run_path(script, run_name='__main__')
"""


def rastrear(ana, cfg):
    """Roda cada gerador com a saída numa pasta temporária e registra os arquivos da análise que ele abre para leitura (o que ele lê de fato)."""
    import os
    import subprocess
    import tempfile
    from pipeline_analise.execucao import PROMPTS
    base = Path(cfg).resolve().parent
    c = json.loads(Path(cfg).read_text(encoding='utf-8'))
    p = lambda k: (base / c[k]).resolve()   # noqa: E731
    interp, projeto = p('interpretacoes'), p('projeto')
    extras = {'gerar_interface.py': ['--aplicacao', p('aplicacao'), '--pdc', p('pdc'), '--cache', p('trabalho') / 'cache-interface', '--limite', '100000'],
              'gerar_traceability_to_be.py': ['--projeto', projeto, '--resultados', projeto / 'local' / 'tests' / 'evidencias' / 'resultados-testes.json'],
              'gerar_pdc.py': ['--pdc', p('pdc')], 'gerar_architecture_decisions.py': ['--projeto', projeto],
              'gerar_enhancement_proposals.py': ['--projeto', projeto], 'gerar_ui_design.py': ['--projeto', projeto],
              'gerar_implementation.py': ['--projeto', projeto]}
    gens = sorted({g for _i, g, _f, _a, _e in PROMPTS.values()} | {f.name for f in (R / 'fases').glob('gerar_*.py')})
    env = dict(os.environ, ANALISE_RAIZ=str(R), ANALISE_INTERPRETACOES=str(interp), MAPA_ANALISE=str(ana), PYTHONHASHSEED='0')
    cfg_proj = p('cenarios') / 'analise.config.json'
    if cfg_proj.exists():
        env['ANALISE_CONFIG'] = str(cfg_proj)
    out = {}
    for g in gens:
        with tempfile.TemporaryDirectory() as tmp:
            saida_lidos = Path(tmp) / 'lidos.json'
            for n in next((fs for _i, gg, fs, _a, _e in PROMPTS.values() if gg == g), []):   # gerador que completa uma fase (ex.: fluxo interno) precisa dela na saída
                for q in list(Path(ana).glob(f'{n}-*')) + list(Path(ana).glob(f'{n} *')):
                    shutil.copytree(q, Path(tmp) / 'saida' / q.name)
            args = [sys.executable, '-c', BOOT, str(R / 'fases' / g), str(ana), str(Path(tmp) / 'saida'), '--interpretacao', str(interp)] + [str(x) for x in extras.get(g, [])]
            r = subprocess.run(args, env=dict(env, MAPA_SAIDA=str(saida_lidos)), capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=1800)
            out[g] = {'ok': r.returncode == 0, 'lidos': json.loads(saida_lidos.read_text(encoding='utf-8')) if saida_lidos.exists() else [],
                      'erro': (r.stdout + r.stderr)[-400:] if r.returncode else ''}
            print(f'  {g}: {"ok" if out[g]["ok"] else "FALHOU"}; {len(out[g]["lidos"])} arquivo(s) da análise lido(s)', flush=True)
    return out


RASTREIO = {}


def leituras_geradores(fases):
    """Literais de fase, de título de tabela e de arquivo de resultado no código de cada gerador (com os geradores que ele importa)."""
    try:
        from pipeline_analise.execucao import PROMPTS
        gera = {g: fs for _p, (_i, g, fs, _a, _e) in PROMPTS.items()}
    except ImportError:
        gera = {}
    for f in (R / 'fases').glob('gerar_*.py'):   # geradores fora do pipeline de prompts: a fase que escrevem vem da constante FASE do próprio código
        m = re.search(r"^FASE = '([^']+)'", f.read_text(encoding='utf-8'), re.M)
        if m and f.name not in gera:
            gera[f.name] = [num(m.group(1))]
    fontes = {f.stem: f.read_text(encoding='utf-8') for f in (R / 'fases').glob('*.py')}
    importa = {k: set(re.findall(r'^import (gerar_\w+|intranet_\w+)', v, re.M)) & set(fontes) for k, v in fontes.items()}

    def fechamento(k, vistos=None):
        vistos = vistos or set()
        for i in importa.get(k, ()):
            if i not in vistos:
                vistos.add(i)
                fechamento(i, vistos)
        return vistos
    arquivos_resultado = {p.name for p in Path(ANALISE).glob('*.json')}
    pasta_de = {f['n']: p for p, f in fases.items()}
    out = []
    for gen, destinos in sorted(gera.items()):
        k = gen[:-3]
        if k not in fontes:
            continue
        lits = set()
        for m in {k} | fechamento(k):
            lits |= set(literais(fontes[m]))
        medido = RASTREIO.get(gen)
        abertas = {x.split(os.sep)[0] for x in medido['lidos']} if medido else None   # fases que o gerador abriu de fato (rastreio)
        so_link = set(re.findall(r"link\([^)]*?'([^']+)'", fontes[k]))
        ordem_destino = min(list(fases).index(pasta_de[d]) for d in destinos if d in pasta_de) if any(d in pasta_de for d in destinos) else 99
        for pasta, f in fases.items():
            if f['n'] in destinos or list(fases).index(pasta) >= ordem_destino:
                continue
            if abertas is not None and pasta not in abertas:
                continue
            tabs = [t for t in f['tabelas'] if t in lits or any(len(x) >= 25 and not x.startswith('Tabela do diagrama') and t.startswith(x) for x in lits)]
            for t in tabs:
                out.append({'meio': 'gerador', 'quem': gen, 'destinos': destinos, 'fase': pasta, 'tabela': t, 'colunas': []})
            if not tabs and (abertas is not None or (pasta in lits and pasta not in so_link)):
                out.append({'meio': 'gerador', 'quem': gen, 'destinos': destinos, 'fase': pasta, 'tabela': '*', 'colunas': []})
        arqs = {x for x in medido['lidos'] if os.sep not in x} if medido else arquivos_resultado & lits
        for arq in sorted(arqs):
            out.append({'meio': 'gerador', 'quem': gen, 'destinos': destinos, 'fase': None, 'arquivo': arq, 'tabela': '*', 'colunas': []})
    return out


def leituras_motor(fases):
    """Relatórios das fases 0 a 9: nomes de fase usados pelas funções que montam cada um (e pelas funções do mesmo módulo que elas chamam)."""
    import report_model
    out = []
    pastas = set(fases)
    for destino, fn in report_model._steps().items():
        mod = Path(sys.modules[fn.__module__].__file__).read_text(encoding='utf-8')
        funcs = {m.group(1): m.group(0) for m in re.finditer(r'(?ms)^def (\w+)\(.*?(?=^def |\Z)', mod)}
        corpo, fila, vistos = '', [fn.__name__], set()
        while fila:
            f = fila.pop()
            if f in vistos or f not in funcs:
                continue
            vistos.add(f)
            corpo += funcs[f]
            fila += [c for c in re.findall(r'\b(\w+)\(', funcs[f]) if c in funcs]
        for p in sorted(pastas):
            if p != destino and f"'{p}'" in corpo:
                out.append({'meio': 'relatório do motor', 'quem': fn.__name__, 'destinos': [num(destino)], 'fase': p, 'tabela': '*', 'colunas': []})
    return out


def leituras_calculo(fases):
    """Cadeia do cálculo determinístico (tools/certify_from_zero.py): cada fase publica variáveis; uma fase lê outra quando a variável publicada
    pela segunda é usada no cálculo das variáveis da primeira."""
    cod = (R / 'tools' / 'certify_from_zero.py').read_text(encoding='utf-8')
    pub = {m.group(1): set(re.findall(r"[:,{]\s*([a-z_]+)\b", m.group(2))) for m in re.finditer(r"publish\(outdir,'([^']+)',(\{.*?\}),'", cod)}
    atrib = defaultdict(set)   # variável -> variáveis usadas no seu cálculo
    for m in re.finditer(r'(?m)^\s*([a-z_]+(?:\s*,\s*[a-z_]+)*)\s*=\s*(.+)$', cod):
        usados = set(re.findall(r'\b([a-z_]+)\b', m.group(2)))
        for v in re.split(r'\s*,\s*', m.group(1)):
            atrib[v] |= usados

    def origem(v, vistos=None):
        vistos = vistos or set()
        for u in atrib.get(v, ()):
            if u not in vistos:
                vistos.add(u)
                origem(u, vistos)
        return vistos
    out = []
    for destino, vs in pub.items():
        usa = set().union(*(origem(v) for v in vs)) if vs else set()
        for outra, ws in pub.items():
            if outra != destino and destino in fases and outra in fases and ws & usa and list(fases).index(outra) < list(fases).index(destino):
                if any(w in usa and w not in vs for w in ws):
                    out.append({'meio': 'cálculo do motor', 'quem': 'certify_from_zero', 'destinos': [num(destino)], 'fase': outra, 'tabela': '*', 'colunas': []})
    return out


# ── utilidade ────────────────────────────────────────────────────────────────
def calcular(ana):
    fases = inventario(ana)
    pasta_de = {f['n']: p for p, f in fases.items()}
    leituras = leituras_prompts(fases) + leituras_geradores(fases) + leituras_motor(fases) + leituras_calculo(fases)
    arestas = defaultdict(lambda: defaultdict(set))   # lida -> consumidora -> {meio}
    tab_uso = defaultdict(lambda: defaultdict(lambda: {'quem': set(), 'colunas': set()}))
    for x in leituras:
        if not x['fase']:
            continue
        for d in x['destinos']:
            if d in pasta_de and pasta_de[d] != x['fase']:
                arestas[x['fase']][pasta_de[d]].add(x['meio'])
        if x['tabela'] != '*':
            u = tab_uso[x['fase']][x['tabela']]
            u['quem'].add(f"{x['quem']} → fase {'/'.join(x['destinos'])}")
            u['colunas'] |= set(x['colunas'])
    # alcance: a fase chega, direta ou indiretamente, às fases de implementação?
    def descendentes(p, vistos=None):
        vistos = vistos or set()
        for q in arestas.get(p, {}):
            if q not in vistos:
                vistos.add(q)
                descendentes(q, vistos)
        return vistos
    resumo = []
    for p, f in fases.items():
        cons = sorted(arestas.get(p, {}), key=list(fases).index)
        desc = descendentes(p)
        lidas = [t for t in f['tabelas'] if t in tab_uso.get(p, {})]
        integral = any(x['fase'] == p and x['tabela'] == '*' for x in leituras)
        resumo.append({'fase': p, 'n': f['n'], 'titulo': f['titulo'], 'tipo': f['tipo'], 'etapa': f['etapa'], 'consumidoras': cons,
                       'meios': sorted({m for q in cons for m in arestas[p][q]}), 'alcance': len(desc), 'chega_implementacao': any(fases[q]['n'] in IMPLEMENTACAO for q in desc) or f['n'] in IMPLEMENTACAO,
                       'tabelas': len(f['tabelas']), 'tabelas_lidas': len(lidas), 'lida_inteira': integral, 'linhas': sum(t['linhas'] for t in f['tabelas'].values()),
                       'graficos': f['graficos']})
    tabelas = []
    for p, f in fases.items():
        for t, info in f['tabelas'].items():
            u = tab_uso.get(p, {}).get(t)
            tabelas.append({'fase': p, 'tabela': t, 'linhas': info['linhas'], 'colunas': len(info['colunas']),
                            'colunas_lidas': sorted(u['colunas'] & set(info['colunas'])) if u else [], 'consumidores': sorted(u['quem']) if u else []})
    arquivos = sorted({(x['arquivo'], x['quem']) for x in leituras if x.get('arquivo')})
    return fases, resumo, tabelas, {p: {q: sorted(ms) for q, ms in d.items()} for p, d in arestas.items()}, arquivos


# ── impacto na implementação (frontend e backend) ────────────────────────────
CAMADAS = [('Frontend (micro frontend)', ('MFE', 'HOST')), ('BFF', ('BFMF',)), ('Serviços (domínio e VAS)', ('DOMAIN_MICROSERVICE', 'VAS')),
           ('Programas executores (mainframe)', ('PROGRAM_DB2', 'PROGRAM_CORP'))]


def _linhas(ana, pasta, titulo_ini):
    f = Path(ana) / pasta / 'ia' / 'report.json'
    if not f.exists():
        return []
    def txt(x):
        if isinstance(x, dict):
            return x.get('text') or ', '.join(str(l.get('text', '')) for l in x.get('links', []) + x.get('parts', []) if isinstance(l, dict))
        return str(x)
    out = []   # todas as tabelas cujo título começa assim (ex.: as várias tabelas da especificação de UX)
    for s in json.loads(f.read_text(encoding='utf-8'))['sections']:
        for b in s['blocks']:
            if b['type'] == 'table' and (b.get('title') or '').startswith(titulo_ini):
                out += [{c: txt(x) for c, x in zip(b['columns'], r)} for r in b['rows']]
    return out


def impacto(ana, fases, arestas):
    """Artefatos de cada camada (aplicações pelo tipo da fase 19, módulos da fase 21, telas da UX, programas executores e copybooks), as regras de negócio
    cujo código está em cada camada (rastreio da fase 21) e, por fase, se os dados dela citam artefatos da camada (impacto direto) ou se ela alimenta
    uma fase que os cita (impacto indireto)."""
    pasta = {f['n']: p for p, f in fases.items()}
    if '19' not in pasta:
        return None
    rec = _linhas(ana, pasta['19'], 'Modelo de recursos aprovados')
    tipo_app = {r['Id']: r['Tipo'] for r in rec}
    cmds = _linhas(ana, pasta['19'], 'Comandos SQL: fila de pedido, programa e fila de resposta')
    ux = _linhas(ana, pasta['19'], 'Especificação UX')
    modulo = {}
    if '21' in pasta:
        for r in _linhas(ana, pasta['21'], 'Aplicações da arquitetura alvo e módulos'):
            m = r.get('Módulo do repositório', '')
            if m and not m.startswith('—'):
                modulo[r['Aplicação (fase 19)']] = m
    ids = {c: set() for c, _t in CAMADAS}
    camada_de_modulo = {}
    for c, tipos in CAMADAS:
        for app, t in tipo_app.items():
            if t in tipos:
                ids[c].add(app)
                if app in modulo:
                    ids[c].add(modulo[app])
                    camada_de_modulo[modulo[app]] = c
    ids['Frontend (micro frontend)'] |= {r.get('Tela', '') for r in ux if r.get('Tela')}
    exec_ = 'Programas executores (mainframe)'
    for r in cmds:
        for col in ('PROGRAM_DB2 ou PROGRAM_CORP', 'Copybook de requisição', 'Copybook de resposta'):
            v = r.get(col, '')
            if v and v != '—' and ' ' not in v:
                ids[exec_].add(v)
    if '21' in pasta:
        for r in _linhas(ana, pasta['21'], 'Programas corporativos chamados por LEGACY'):
            camada_de_modulo[r.get('Módulo do repositório', '')] = exec_
    regras = {c: set() for c, _t in CAMADAS}
    if '21' in pasta:
        for r in _linhas(ana, pasta['21'], 'Rastreio por regra de negócio'):
            for m in [x.strip() for x in r.get('Módulos com o código', '').split(',') if x.strip()]:
                c = camada_de_modulo.get(m) or (exec_ if m.startswith('local/') else None)
                if c:
                    regras[c].add(r['Regra de negócio'].split(' · ')[0] + ' ' + r.get('Funcionalidade', ''))
    ids = {c: {i for i in v if i and len(i) >= 5} for c, v in ids.items()}
    diretas = {}
    for p in fases:
        rel = json.loads((Path(ana) / p / 'ia' / 'report.json').read_text(encoding='utf-8'))
        textos = [' '.join((x.get('text', '') if isinstance(x, dict) else str(x)) for x in r) for s in rel['sections'] for b in s['blocks'] if b['type'] == 'table' for r in b['rows']]
        diretas[p] = {c: sum(1 for t in textos if any(i in t for i in v)) for c, v in ids.items()}

    def desc(p, vistos=None):
        vistos = vistos or set()
        for q in arestas.get(p, {}):
            if q not in vistos:
                vistos.add(q)
                desc(q, vistos)
        return vistos
    matriz = {}
    for p in fases:
        ds = desc(p)
        matriz[p] = {c: ('direto', diretas[p][c]) if diretas[p][c] else (('indireto', sorted(fases[q]['n'] for q in ds if diretas[q][c])) if any(diretas[q][c] for q in ds) else ('—', 0))
                     for c, _t in CAMADAS}
    contrib = contribuicoes(ana, pasta, tipo_app, camada_de_modulo, cmds, ux, exec_)
    return {'ids': {c: sorted(v) for c, v in ids.items()}, 'regras': {c: sorted(v) for c, v in regras.items()}, 'matriz': matriz, 'contribuicao': contrib}


def contribuicoes(ana, pasta, tipo_app, camada_de_modulo, cmds, ux, exec_):
    """O que cada fase entrega de concreto a cada camada, contado nas tabelas de cruzamento das fases 19, 20 e 21:
    regras de negócio (fase 11) com código na camada e, delas, as que vêm de decisões (fases 05 e 13) ou de regras determinísticas (fase 06);
    funcionalidades (fase 12); comandos SQL (fase 10) que viram programas executores; telas e ações (fase 15, pela UX da fase 19); contextos (fase 18)
    e aplicações (fase 19); operações de contrato e copybooks (fase 20)."""
    camada_tipo = {t: c for c, ts in CAMADAS for t in ts}
    out = defaultdict(lambda: defaultdict(list))

    def por(fase, camada, texto):
        if fase in pasta and camada:
            out[pasta[fase]][camada].append(texto)
    regras = defaultdict(set)
    decisao = defaultdict(set)
    determ = defaultdict(set)
    funcs = defaultdict(set)
    if '21' in pasta:
        for r in _linhas(ana, pasta['21'], 'Rastreio por regra de negócio'):
            cods = {camada_de_modulo.get(m) or (exec_ if m.startswith('local/') else None) for m in (x.strip() for x in r.get('Módulos com o código', '').split(',')) if m}
            k = r.get('Funcionalidade', '') + '.' + r['Regra de negócio'].split(' · ')[0]
            for c in cods - {None}:
                regras[c].add(k)
                funcs[c].add(r.get('Funcionalidade', ''))
                o = r.get('Origem (fase 13)', '')
                if 'decis' in o:
                    decisao[c].add(k)
                elif 'determin' in o:
                    determ[c].add(k)
    for c in regras:
        por('11', c, f'{len(regras[c])} regras de negócio')
        por('12', c, f'{len(funcs[c])} funcionalidades')
        por('13', c, f'{len(decisao[c]) + len(determ[c])} regras com a origem rastreada')
        if decisao[c]:
            por('05', c, f'{len(decisao[c])} regras vindas de decisões do código')
        if determ[c]:
            por('06', c, f'{len(determ[c])} regras vindas de regras determinísticas')
    sql = [r for r in cmds if r.get('MQ_REQ', '—') not in ('—', '') and 'corporativo' not in r.get('Operação', '')]
    corp = [r for r in cmds if 'corporativo' in r.get('Operação', '')]
    por('10', exec_, f'{len(sql)} comandos SQL viram programas executores')
    if corp:
        por('00', exec_, f'{len(corp)} programas corporativos chamados por programa executor')
    telas = {r.get('Tela') for r in ux if r.get('Tela')}
    acoes = [r for r in ux if r.get('Ação')]
    if telas:
        por('15', 'Frontend (micro frontend)', f'{len(telas)} telas e {len(acoes)} ações')
    apps = defaultdict(set)
    ctx = defaultdict(set)
    for r in _linhas(ana, pasta.get('19', ''), 'Modelo de recursos aprovados') if '19' in pasta else []:
        c = camada_tipo.get(r['Tipo'])
        apps[c].add(r['Id'])
        if r.get('Contexto de origem (fase 18)', '—') not in ('—', ''):
            ctx[c].add(r['Contexto de origem (fase 18)'])
    for c in apps:
        por('19', c, f'{len(apps[c])} aplicações')
        if ctx[c]:
            por('18', c, f'{len(ctx[c])} contextos')
    if '19' in pasta:
        por('19', exec_, f'{len(sql) + len(corp)} programas e {2 * (len(sql) + len(corp))} filas de baixa')
    if '20' in pasta:
        ops = defaultdict(int)
        for r in _linhas(ana, pasta['20'], 'Operações dos contratos'):
            app = r.get('Arquivo', '').split('/')[-1].replace('.openapi.yaml', '')
            ops[camada_tipo.get(tipo_app.get(app))] += 1
        for c, n in ops.items():
            por('20', c, f'{n} operações de contrato')
        cpy = _linhas(ana, pasta['20'], 'Copybooks')
        if cpy:
            por('20', exec_, f'{len(cpy)} copybooks')
    if '16' in pasta:
        dom = [r for r in _linhas(ana, pasta['19'], 'Modelo de recursos aprovados') if r['Tipo'] == 'DOMAIN_MICROSERVICE'] if '19' in pasta else []
        if dom:
            por('16', 'Serviços (domínio e VAS)', f'{len(dom)} agregados raiz viram microsserviços de domínio')
    return {p: dict(v) for p, v in out.items()}


# ── HTML ─────────────────────────────────────────────────────────────────────
def esc(x):
    return str(x).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def nivel(r):
    if not r['consumidoras']:
        return 'final' if r['n'] in IMPLEMENTACAO else 'só leitura humana'
    if len(r['consumidoras']) >= 3:
        return 'estrutural'
    return 'consumida'


def svg_mapa(fases, resumo, arestas):
    por = {r['fase']: r for r in resumo}
    col = {e: i + 1 for i, (e, _q, _c) in enumerate(ETAPAS)}
    larg, alt_no, gap = 210, 46, 14
    colunas = defaultdict(list)
    for p in fases:
        colunas[col[fases[p]['etapa']]].append(p)
    ext = list(EXTERNAS)
    altura = 70 + max([len(v) for v in colunas.values()] + [len(ext)]) * (alt_no + gap)
    W = 30 + 5 * (larg + 70)
    pos = {}
    for i, e in enumerate(ext):
        pos['ext:' + e] = (20, 70 + i * (alt_no + gap))
    for c, ps in colunas.items():
        off = (altura - 70 - len(ps) * (alt_no + gap)) / 2
        for i, p in enumerate(ps):
            pos[p] = (20 + c * (larg + 70), 70 + off + i * (alt_no + gap))
    o = [f'<svg viewBox="0 0 {W} {altura}" width="{W}" height="{altura}" class="mapa" role="img" aria-label="Mapa das fases"><defs>'
         + ''.join(f'<marker id="s{i}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0L10,5L0,10z" fill="{c}"/></marker>'
                   for i, c in enumerate(CORES.values())) + '</defs>']
    for i, (e, q, c) in enumerate(ETAPAS):
        x = 20 + (i + 1) * (larg + 70)
        o.append(f'<text x="{x + larg / 2}" y="24" text-anchor="middle" class="et" fill="{c}">{esc(e)}</text><text x="{x + larg / 2}" y="42" text-anchor="middle" class="eq">{esc(q)}</text>')
    o.append(f'<text x="{20 + larg / 2}" y="24" text-anchor="middle" class="et" fill="#888">Entradas externas</text>')
    idx = list(CORES)

    def curva(a, b, cor, i, classe):
        x1, y1 = pos[a][0] + larg, pos[a][1] + alt_no / 2
        x2, y2 = pos[b][0], pos[b][1] + alt_no / 2
        if x2 <= x1:   # mesma coluna ou para trás: arco por fora
            x2b = pos[b][0] + larg
            return (f'<path class="ar {classe}" d="M{x1},{y1} C{x1 + 60},{y1} {x2b + 60},{y2} {x2b},{y2}" stroke="{cor}" marker-end="url(#s{i})"/>')
        dx = (x2 - x1) / 2
        return f'<path class="ar {classe}" d="M{x1},{y1} C{x1 + dx},{y1} {x2 - dx},{y2} {x2},{y2}" stroke="{cor}" marker-end="url(#s{i})"/>'
    for e, fs in EXTERNAS.items():
        for n in fs:
            p = next((q for q in fases if fases[q]['n'] == n), None)
            if p:
                o.append(curva('ext:' + e, p, CORES['externa'], idx.index('externa'), f'de-ext{ext.index(e)} para-{re.sub(r"[^a-z0-9]", "", p)}'))
    for a, d in arestas.items():
        for b, meios in d.items():
            m = meios[0] if len(meios) == 1 else ('prompt' if 'prompt' in meios else meios[0])
            o.append(curva(a, b, CORES[m], idx.index(m), f'de-{re.sub(r"[^a-z0-9]", "", a)} para-{re.sub(r"[^a-z0-9]", "", b)}'))
    for e in ext:
        x, y = pos['ext:' + e]
        o.append(f'<g class="no ext"><rect x="{x}" y="{y}" width="{larg}" height="{alt_no}" rx="6"/><text x="{x + 10}" y="{y + 28}">{esc(e)}</text></g>')
    for p in fases:
        r = por[p]
        x, y = pos[p]
        cor = dict((e, c) for e, _q, c in ETAPAS)[fases[p]['etapa']]
        nv = nivel(r)
        k = re.sub(r'[^a-z0-9]', '', p)
        o.append(f'<g class="no fase n-{nv.replace(" ", "")}" data-k="{k}"><rect x="{x}" y="{y}" width="{larg}" height="{alt_no}" rx="6" stroke="{cor}"/>'
                 f'<text x="{x + 10}" y="{y + 19}" class="t">{esc(p[:30])}</text>'
                 f'<text x="{x + 10}" y="{y + 36}" class="s">{len(r["consumidoras"])} consumidora(s) · {r["tabelas_lidas"]}/{r["tabelas"]} tabelas lidas</text>'
                 f'<title>{esc(fases[p]["titulo"])} — {nv}</title></g>')
    o.append('</svg>')
    return ''.join(o)


def html_impacto(fases, imp):
    if not imp:
        return '<p class="nota">A análise não tem a fase de arquitetura alvo: não há camadas da implementação para relacionar.</p>'
    cam = [c for c, _t in CAMADAS]
    cards = ''.join(f'<div class="card"><b>{len(imp["regras"][c])}</b><span>regras de negócio com código em {esc(c)}</span></div>' for c in cam)
    cab = ''.join(f'<th>{esc(c)}</th>' for c in cam)
    corpo = ''
    contrib = imp.get('contribuicao', {})
    for p in fases:
        cel = ''
        for c in cam:
            t, v = imp['matriz'][p][c]
            entrega = contrib.get(p, {}).get(c, [])
            if entrega:
                cel += f'<td class="dir">{esc("; ".join(entrega))}</td>'
            elif t == 'direto':
                cel += f'<td class="cit">cita a camada ({v} linha{"s" if v != 1 else ""})</td>'
            elif t == 'indireto':
                cel += f'<td class="ind">indireto, via fase {esc(", ".join(v[:6]))}{" …" if len(v) > 6 else ""}</td>'
            else:
                cel += '<td>—</td>'
        corpo += f'<tr><td>{esc(p)}</td>{cel}</tr>'
    arts = ''.join(f'<tr><td>{esc(c)}</td><td>{len(imp["ids"][c])}</td><td>{esc(", ".join(imp["ids"][c][:40]))}{" …" if len(imp["ids"][c]) > 40 else ""}</td>'
                   f'<td>{esc(", ".join(imp["regras"][c][:60]))}{" …" if len(imp["regras"][c]) > 60 else ""}</td></tr>' for c in cam)
    return (f'<div class="cards">{cards}</div>'
            '<p class="nota">Verde: o que a fase entrega de concreto à camada (contado nas tabelas de cruzamento das fases 19, 20 e 21); mudar a fase muda isso na '
            'implementação. Cita a camada: os dados da fase nomeiam artefatos da camada sem que haja uma contagem própria. Azul, indireto: a fase só alimenta, pela cadeia '
            'de ligações, fases que entregam à camada. —: a fase não chega à camada.</p>'
            f'<div class="wrap"><table class="imp"><thead><tr><th>Fase</th>{cab}</tr></thead><tbody>{corpo}</tbody></table></div>'
            '<h3>Artefatos e regras de cada camada</h3><p class="nota">Artefatos: o que identifica a camada nos relatórios (fase 19 e fase 21). Regras: as regras de negócio '
            'cujo código está em módulos da camada (rastreio da fase 21); uma regra pode estar em mais de uma camada.</p>'
            f'<div class="wrap"><table><thead><tr><th>Camada</th><th>Artefatos</th><th>Quais</th><th>Regras de negócio com código na camada</th></tr></thead><tbody>{arts}</tbody></table></div>')


def html(ana, fases, resumo, tabelas, arestas, arquivos, imp=None):
    ordem = list(fases)
    # matriz: linha = fase lida, coluna = fase que consome
    cab = ''.join(f'<th class="v"><span>{esc(fases[p]["n"])}</span></th>' for p in ordem)
    linhas_m = ''
    for a in ordem:
        cel = ''
        for b in ordem:
            ms = arestas.get(a, {}).get(b)
            cel += (f'<td class="m" style="background:{CORES[ms[0]]}" title="{esc(a)} → {esc(b)}: {esc(", ".join(ms))}">{"●" if len(ms) > 1 else ""}</td>' if ms else '<td></td>')
        linhas_m += f'<tr><th class="h">{esc(a)}</th>{cel}</tr>'
    nivel_cont = defaultdict(int)
    for r in resumo:
        nivel_cont[nivel(r)] += 1
    tl = [t for t in tabelas if t['consumidores']]
    ts = [t for t in tabelas if not t['consumidores'] and not t['tabela'].startswith('Tabela do diagrama')]
    cards = [('fases', len(fases)), ('ligações entre fases', sum(len(d) for d in arestas.values())), ('tabelas nos relatórios', len(tabelas)),
             ('tabelas lidas por outra fase', len(tl)), ('tabelas só para leitura humana (sem contar as dos diagramas)', len(ts)),
             ('fases estruturais (3 ou mais consumidoras)', nivel_cont['estrutural']), ('fases sem consumidora (fora da implementação)', nivel_cont['só leitura humana'])]
    rows_r = ''
    for r in resumo:
        nv = nivel(r)
        rows_r += (f'<tr class="n-{nv.replace(" ", "")}"><td>{esc(r["fase"])}</td><td>{esc(r["etapa"])}</td><td>{esc(r["tipo"])}</td><td>{nv}</td>'
                   f'<td>{len(r["consumidoras"])}: {esc(", ".join(fases[q]["n"] for q in r["consumidoras"]) or "—")}</td><td>{esc(", ".join(r["meios"]) or "—")}</td>'
                   f'<td>{r["alcance"]}</td><td>{"sim" if r["chega_implementacao"] else "não"}</td><td>{r["tabelas_lidas"]}/{r["tabelas"]}{" + leitura integral" if r["lida_inteira"] else ""}</td>'
                   f'<td>{r["linhas"]}</td><td>{r["graficos"]}</td></tr>')
    rows_t = ''.join(f'<tr><td>{esc(t["fase"])}</td><td>{esc(t["tabela"])}</td><td>{t["linhas"]}</td><td>{len(t["colunas_lidas"])}/{t["colunas"]}</td>'
                     f'<td>{esc(", ".join(t["colunas_lidas"]) or "—")}</td><td>{esc("; ".join(t["consumidores"]))}</td></tr>' for t in sorted(tl, key=lambda t: (ordem.index(t['fase']), t['tabela'])))
    por_fase_s = defaultdict(list)
    for t in ts:
        por_fase_s[t['fase']].append(t)
    rows_s = ''.join(f'<tr><td>{esc(p)}</td><td>{len(v)}</td><td>{esc("; ".join(f"{t["tabela"]} ({t["linhas"]})" for t in v[:40]))}{" …" if len(v) > 40 else ""}</td></tr>'
                     for p, v in sorted(por_fase_s.items(), key=lambda kv: ordem.index(kv[0])))
    rows_a = ''.join(f'<tr><td>{esc(a)}</td><td>{esc(q)}</td></tr>' for a, q in arquivos)
    leg = ''.join(f'<span><i style="background:{c}"></i>{esc(m)}</span>' for m, c in CORES.items())
    return f'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mapa das fases</title><style>
:root{{--bg:#f7f7f5;--fg:#1d1d1f;--mut:#5c5c66;--card:#fff;--line:#d9d9df;--th:#eef0f4}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16171a;--fg:#e8e8ea;--mut:#a3a3ad;--card:#202227;--line:#34363d;--th:#2a2d33}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
main{{max-width:1500px;margin:auto;padding:24px 16px 60px}}h1{{font-size:24px;margin:0 0 4px}}h2{{font-size:19px;margin-top:34px;border-bottom:2px solid #1f5fa8;padding-bottom:4px}}
p.sub{{color:var(--mut);margin:0 0 14px}}.cards{{display:flex;flex-wrap:wrap;gap:10px}}.card{{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:10px 14px;flex:1;min-width:150px}}
.card b{{display:block;font-size:22px;color:#1f5fa8}}.card span{{color:var(--mut);font-size:12.5px}}
.wrap{{overflow:auto;background:var(--card);border:1px solid var(--line);border-radius:6px;padding:8px}}
svg.mapa text{{fill:var(--fg);font-size:11.5px}}svg.mapa .t{{font-weight:600}}svg.mapa .s{{fill:var(--mut);font-size:10.5px}}svg.mapa .et{{font-size:15px;font-weight:700}}svg.mapa .eq{{fill:var(--mut);font-size:11px}}
svg.mapa .no rect{{fill:var(--card);stroke-width:2.2}}svg.mapa .ext rect{{stroke:#888;stroke-dasharray:4 3}}svg.mapa .n-sóleiturahumana rect{{stroke-dasharray:6 4;opacity:.75}}
svg.mapa .ar{{fill:none;stroke-width:1.4;opacity:.45}}svg.mapa.foco .ar{{opacity:.05}}svg.mapa.foco .ar.on{{opacity:.95;stroke-width:2.4}}svg.mapa.foco .no{{opacity:.35}}svg.mapa.foco .no.on{{opacity:1}}
.legend{{display:flex;gap:16px;flex-wrap:wrap;margin:8px 0;font-size:13px}}.legend i{{display:inline-block;width:22px;height:4px;margin-right:6px;vertical-align:middle;border-radius:2px}}
table{{border-collapse:collapse;width:100%;background:var(--card);font-size:12.5px}}th,td{{border:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}}th{{background:var(--th)}}
table.mx td{{width:20px;height:20px;padding:0;text-align:center;color:#fff;font-size:10px}}table.mx th.h{{white-space:nowrap;font-weight:500}}table.mx th.v{{height:42px;vertical-align:bottom;padding:2px}}table.mx th.v span{{writing-mode:vertical-rl;transform:rotate(180deg)}}
tr.n-sóleiturahumana td:nth-child(4){{color:#b00020;font-weight:600}}tr.n-estrutural td:nth-child(4){{color:#1e7e34;font-weight:600}}
.nota{{color:var(--mut);font-size:12.5px}}h3{{font-size:16px;margin-top:22px}}
table.imp td.dir{{background:rgba(30,126,52,.18);font-weight:600}}table.imp td.cit{{background:rgba(30,126,52,.08)}}table.imp td.ind{{background:rgba(31,95,168,.10);color:var(--mut)}}
table.mx{{width:auto}}
</style></head><body><main>
<h1>Mapa das fases e dos dados</h1><p class="sub">Como cada fase da análise ({esc(Path(ana).resolve())}) usa os dados das outras, calculado dos prompts, dos geradores, do motor e dos relatórios. Serve para medir a utilidade de cada coisa mapeada: o que alimenta as fases seguintes, o que chega à implementação e o que só existe para leitura humana.</p>
<div class="cards">{"".join(f'<div class="card"><b>{v}</b><span>{esc(k)}</span></div>' for k, v in cards)}</div>
<h2>Mapa visual</h2>
<p class="nota">Colunas: as quatro etapas, com as entradas externas à esquerda. Cada seta vai da fase lida para a fase que a consome; a cor diz o meio. Caixa tracejada: fase que nenhuma outra lê. Passe o mouse (ou toque) numa fase para destacar as ligações dela.</p>
<div class="legend">{leg}</div><div class="wrap">{svg_mapa(fases, resumo, arestas)}</div>
<h2>Utilidade de cada fase</h2>
<p class="nota">Estrutural: 3 ou mais fases a consomem. Consumida: 1 ou 2. Só leitura humana: nenhuma fase a lê (o relatório existe para pessoas). Final: fase de implementação, o fim da cadeia. Alcance: quantas fases dependem dela direta ou indiretamente. Chega à implementação: se, seguindo as ligações, ela alimenta as fases {", ".join(IMPLEMENTACAO)}.</p>
<div class="wrap"><table><thead><tr><th>Fase</th><th>Etapa</th><th>Tipo</th><th>Utilidade</th><th>Consumidoras</th><th>Meio</th><th>Alcance</th><th>Chega à implementação</th><th>Tabelas lidas</th><th>Linhas</th><th>Diagramas</th></tr></thead><tbody>{rows_r}</tbody></table></div>
<h2>Matriz: quem lê quem</h2>
<p class="nota">Linha: a fase lida. Coluna: a fase que a consome (pelo número). A cor é o meio; ● quando há mais de um meio.</p>
<div class="wrap"><table class="mx"><thead><tr><th></th>{cab}</tr></thead><tbody>{linhas_m}</tbody></table></div>
<h2>O que afeta a implementação do frontend e do backend</h2>
{html_impacto(fases, imp)}
<h2>Tabelas lidas por outras fases</h2>
<p class="nota">Cada tabela que um prompt (contrato @ler, com as colunas) ou um gerador (pelo título) lê. Colunas lidas: as que o prompt declara; gerador lê a tabela inteira.</p>
<div class="wrap"><table><thead><tr><th>Fase</th><th>Tabela</th><th>Linhas</th><th>Colunas lidas</th><th>Quais</th><th>Lida por</th></tr></thead><tbody>{rows_t}</tbody></table></div>
<h2>Tabelas só para leitura humana</h2>
<p class="nota">Tabelas que nenhuma fase lê (sem contar as tabelas que repetem um diagrama). Não são inúteis por isso: são a explicação para pessoas. Mas são as candidatas a enxugar quando o objetivo é só alimentar as fases seguintes.</p>
<div class="wrap"><table><thead><tr><th>Fase</th><th>Quantas</th><th>Tabelas (linhas)</th></tr></thead><tbody>{rows_s}</tbody></table></div>
<h2>Arquivos de resultado lidos direto pelos geradores</h2>
<div class="wrap"><table><thead><tr><th>Arquivo</th><th>Gerador</th></tr></thead><tbody>{rows_a or '<tr><td colspan="2">—</td></tr>'}</tbody></table></div>
<h2>Como o mapa foi calculado</h2><p class="nota">{esc(__doc__.split("Tudo é calculado")[1])}</p>
</main><script>
(function(){{var s=document.querySelector('svg.mapa');if(!s)return;
function liga(k,on){{s.classList.toggle('foco',on);s.querySelectorAll('.on').forEach(function(e){{e.classList.remove('on')}});if(!on)return;
s.querySelectorAll('.de-'+k+',.para-'+k).forEach(function(e){{e.classList.add('on');var c=e.getAttribute('class').match(/(de|para)-([a-z0-9]+)/g)||[];c.forEach(function(x){{var n=s.querySelector('[data-k="'+x.split('-')[1]+'"]');if(n)n.classList.add('on')}})}});
var n=s.querySelector('[data-k="'+k+'"]');if(n)n.classList.add('on')}}
s.querySelectorAll('.fase').forEach(function(g){{var k=g.getAttribute('data-k');g.addEventListener('mouseenter',function(){{liga(k,true)}});g.addEventListener('mouseleave',function(){{liga(k,false)}});
g.addEventListener('click',function(){{liga(k,!g.classList.contains('on'))}})}})}})();
</script></body></html>'''


ANALISE = None


def main():
    global ANALISE
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    args = sys.argv[1:]
    cfg = None
    if '--config' in args:
        i = args.index('--config')
        cfg = args[i + 1]
        del args[i:i + 2]
    ANALISE = Path(args[0]).resolve()
    saida = Path(args[1]) if len(args) > 1 else ANALISE.parent / 'mapa-das-fases.html'
    if cfg:
        print('rastreando as leituras de cada gerador (cada um roda com a saída numa pasta temporária):')
        RASTREIO.update(rastrear(ANALISE, cfg))
    fases, resumo, tabelas, arestas, arquivos = calcular(ANALISE)
    imp = impacto(ANALISE, fases, arestas)
    saida.write_text(html(ANALISE, fases, resumo, tabelas, arestas, arquivos, imp), encoding='utf-8')
    saida.with_suffix('.json').write_text(json.dumps({'fases': resumo, 'tabelas': tabelas, 'ligacoes': arestas, 'arquivos': arquivos, 'implementacao': imp},
                                                     ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'{len(fases)} fases, {sum(len(d) for d in arestas.values())} ligações, {sum(1 for t in tabelas if t["consumidores"])}/{len(tabelas)} tabelas lidas -> {saida}')


if __name__ == '__main__':
    main()
