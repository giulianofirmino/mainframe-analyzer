#!/usr/bin/env python3
"""Relatório traceability-to-be (fase 21): rastreabilidade do código gerado, da regra de negócio ao teste que a garante.

  python3 gerar_traceability_to_be.py <pasta-da-analise> [pasta-de-saida] --projeto <repositório> --resultados <resultados-testes.json> [--interpretacao PASTA]
  (padrão da saída: a pasta da análise; da interpretação: a pasta deste script)

Para a arquitetura alvo que o código gerado implementa, cada regra de negócio do rastreio da fase 19 é ligada:
  - às decisões e regras determinísticas de origem (fase 13), pelo nó do fluxo de negócio (fase 12) e pelas notas dos diagramas de sequência (fase 19);
  - à funcionalidade, à aplicação e ao caso de uso (fase 19);
  - aos endpoints do contrato (fase 20: `x-business-rules` e "Recusas possíveis" de cada operação, da mesma funcionalidade);
  - ao módulo do repositório e ao código (`arquivo:linha` e trecho de cada âncora da interpretação, procurada no repositório);
  - aos cenários de teste que a citam e ao resultado da execução (`--resultados`, gravado pelo coletor do repositório);
  - e completa a rastreabilidade (fase 13): cada regra de negócio e funcionalidade ganha o caso de uso, a aplicação e as classes que a implementam;
  - aos programas mainframe que cada cenário ponta a ponta executou (campo `mainframe` do cenário: pedido posto na fila pelo serviço, tarefa da região
    CICS que o leu, programas chamados, comandos SQL com o SQLCODE e SYNCPOINT), com a cobertura das transações definidas na região (arquivo de
    definições CICS do repositório, `DEFINE TRANSACTION(...) PROGRAM(...)`).
A interpretação vem do prompt 12 (`interpretacao-testes/implementacao.json`): correlação aplicação → módulo, âncoras de código, conformidade, decisões,
premissas e lacunas (validadas, sem seção própria no relatório). Nada é inventado: âncora que não existe no código, regra fora do rastreio ou aplicação
sem módulo recusam o relatório; regra sem teste, com teste em falha ou divergente aparece destacada no rastreio por regra.
Saída: <saida>/21 - traceability-to-be/human/report.html e <saida>/21 - traceability-to-be/ia/report.json."""
import glob
import html
import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import yaml

import gerar_target_architecture as TA
import report_model as rm  # noqa: E402
import report_render as rr  # noqa: E402
from urllib.parse import quote  # noqa: E402

S = TA.S
FASE = '21 - traceability-to-be'
FASE13 = '13 - traceability'
TAB13 = 'Tabela de rastreabilidade ponta a ponta'
INTERP = 'interpretacao-testes'
CONFORMIDADES = ('CONFORME', 'DIVERGENTE', 'NAO_IMPLEMENTADA')


def texto(c):
    """Texto de uma célula (texto simples ou célula com links)."""
    if isinstance(c, dict):
        if c.get('text'):
            return c['text']
        return ', '.join(l['text'] for l in c.get('links', []) or c.get('parts', []) if isinstance(l, dict))
    return '' if c is None else str(c)


def ids(c):
    return [l['text'] for l in c.get('links', [])] if isinstance(c, dict) else []


def legivel(s):
    """Corpo de resposta ou de requisição em texto corrido (o relatório humano não mostra JSON)."""
    s = '' if s is None else str(s)
    m = re.search(r'[{\[]', s)
    if not m:
        return s
    ini, resto = s[:m.start()], s[m.start():]
    try:
        return ini + _corrido(json.loads(resto))
    except ValueError:
        return ini + re.sub(r'[{}\[\]"]', '', re.sub(r'"([A-Za-z_]\w*)":\s*', r'\1=', resto))


def _corrido(v):
    if isinstance(v, dict):
        return '; '.join(f'{k}={_corrido(x)}' for k, x in v.items())
    if isinstance(v, list):
        return '(' + ', '.join(_corrido(x) for x in v) + ')'
    return 'nulo' if v is None else str(v)


RESUMO = 110


def expansivel(texto_):
    """Resumo da célula com a ação «…» que expande o conteúdo completo (respostas e corpos longos)."""
    t = legivel(texto_)
    return rm.expandir(t[:RESUMO].rstrip(), t) if len(t) > RESUMO else t


def chave(f, r):
    return f'{f}.{r}'


def ancora_regra(k):
    return 'regra-' + k.replace('.', '-')


# ── fases anteriores ─────────────────────────────────────────────────────────
def ler_fase13(ana):
    d = json.loads((Path(ana) / FASE13 / 'ia' / 'report.json').read_text(encoding='utf-8'))
    for sec in d['sections']:
        for b in sec.get('blocks', []):
            if b['type'] == 'table' and b['title'] == TAB13:
                col = {n: i for i, n in enumerate(b['columns'])}
                return col, b['rows']
    raise SystemExit('sem a tabela de rastreabilidade ponta a ponta na fase 13')


def cadeia_fase13(c, m, f18, ev, col, linhas13):
    """(funcionalidade, regra como nas notas da fase 19) -> decisões, regras determinísticas e nó da regra na fase 11, pelo critério da fase 13:
    o nó do fluxo de negócio (fase 12) que a nota mostra e as linhas da fase 13 em que ele é a regra de negócio da regra determinística."""
    TA.sequencias(m, f18, ev, c)
    reg = TA.REG.get(id(m), [])
    no_de = lambda e: TA.FLUXO_IDS.get(e['origem'], {}).get(e['nome'])   # noqa: E731
    por_no = defaultdict(list)
    for r in linhas13:
        if texto(r[col['Situação da regra']]) == 'regra de negócio':
            for n in ids(r[col['Regra de negócio']]):
                por_no[n].append(r)
    out = defaultdict(lambda: {'decisoes': set(), 'deterministicas': set(), 'no': None})
    for e in reg:
        n = no_de(e)
        if not n:
            continue
        v = out[(e['origem'], e['regra'])]
        v['no'] = n
        for r in por_no.get(n, []):
            if e['origem'] in ids(r[col['Funcionalidades']]):
                d = texto(r[col['Decisão']])
                if d and d != '—':
                    v['decisoes'].add(d)
                v['deterministicas'].add(texto(r[col['Regra determinística']]))
    return out


def ler_rastreio19(ana, c):
    d = json.loads((Path(ana) / '19 - target-architecture' / 'ia' / 'report.json').read_text(encoding='utf-8'))
    sec = next(s for s in d['sections'] if s['id'] == 'rastreio')
    b = next(b for b in sec['blocks'] if b['type'] == 'table')
    out = []
    for f, regra, app, caso, seq in b['rows']:
        cod, txt = regra.split(' · ', 1)
        out.append({'f': f, 'r': cod, 'k': chave(f, cod), 'rotulo': regra, 'texto': txt, 'app': app, 'caso': caso, 'seq': seq})
    return out


def ler_contratos(ana, c):
    """Operações dos contratos OpenAPI (fase 20), com as regras e as recusas que cada uma declara."""
    ops = []
    for f in sorted(glob.glob(str(Path(ana) / '20 - contracts' / 'ia' / 'contracts' / '*' / '*.yaml'))):
        doc = yaml.safe_load(Path(f).read_text(encoding='utf-8'))
        app = Path(f).name.replace('.openapi.yaml', '')
        for caminho, metodos in doc.get('paths', {}).items():
            for metodo, op in metodos.items():
                if metodo not in ('get', 'post', 'put', 'delete', 'patch'):
                    continue
                regras = ' | '.join(op.get('x-business-rules', []) + [v.get('description', '') for v in op.get('responses', {}).values()])
                rotulo = f'{metodo.upper()} {caminho}'
                ops.append({'app': app, 'metodo': metodo.upper(), 'caminho': caminho, 'operationId': op.get('operationId', ''), 'rotulo': rotulo,
                            'func': str(op.get('x-legacy', {}).get('feature') or ''), 'regras': regras,
                            'ancora': 'ep-' + re.sub(r'[^a-z0-9]+', '-', f'{app} {rotulo}'.lower()).strip('-')})
    if not ops:
        raise SystemExit('sem contratos OpenAPI na fase 20')
    return ops


# ── projeto ──────────────────────────────────────────────────────────────────
def modulo_de(arquivo):
    p = arquivo.split('/')
    return '/'.join(p[:2]) if p[0] == 'local' else p[0]


def localizar(projeto, a):
    """(linha, trecho) da âncora no arquivo; a busca começa na primeira linha que contém `apos`, quando informado."""
    f = Path(projeto) / a['arquivo']
    if not f.exists():
        return None
    linhas = f.read_text(encoding='utf-8').splitlines()
    ini = 0
    if a.get('apos'):
        ini = next((i for i, l in enumerate(linhas) if a['apos'] in l), None)
        if ini is None:
            return None
    for i in range(ini, len(linhas)):
        if a['ancora'] in linhas[i]:
            return i + 1, linhas[i].strip()
    return None


# ── validação da interpretação (regras do prompt 12) ─────────────────────────
def validar(imp, rastreio, projeto, res):
    erros = []
    if 'cenario' in imp:
        erros.append('o campo cenario não existe (a arquitetura alvo é uma só)')
    apps = {a['aplicacao']: a for a in imp.get('aplicacoes', [])}
    for app in sorted({r['app'] for r in rastreio}):
        if app not in apps:
            erros.append(f'aplicação {app} do rastreio sem correlação com módulo')
        elif not apps[app].get('modulo') and not apps[app].get('observacao'):
            erros.append(f'aplicação {app} sem módulo e sem observação')
    chaves = {r['k'] for r in rastreio}
    vistas = set()
    for r in imp.get('regras', []):
        k = chave(r['funcionalidade'], r['regra'])
        if k not in chaves:
            erros.append(f'regra {k} não está no rastreio da fase 19')
        if k in vistas:
            erros.append(f'regra {k} repetida')
        vistas.add(k)
        if r.get('conformidade') not in CONFORMIDADES:
            erros.append(f'regra {k}: conformidade {r.get("conformidade")!r} inválida')
        if r.get('conformidade') != 'CONFORME' and not r.get('observacao'):
            erros.append(f'regra {k}: {r.get("conformidade")} sem observação')
        if not r.get('implementacao') and r.get('conformidade') != 'NAO_IMPLEMENTADA':
            erros.append(f'regra {k} sem âncora de código')
        for a in r.get('implementacao', []):
            if localizar(projeto, a) is None:
                erros.append(f'regra {k}: âncora não encontrada em {a["arquivo"]}: {a["ancora"][:80]}')
    for k in sorted(chaves - vistas):
        erros.append(f'regra {k} do rastreio sem entrada na interpretação')
    for x in res['cenarios']:
        for k in x['regras']:
            if k not in chaves:
                erros.append(f'cenário {x["id"]} cita a regra {k}, que não está no rastreio')
    for grupo, campos in (('decisoes', ('assunto', 'decisao', 'justificativa')), ('premissas', ('assunto', 'detalhe')), ('lacunas', ('assunto', 'detalhe'))):
        for i, x in enumerate(imp.get(grupo, [])):
            for cmp in campos:
                if not x.get(cmp):
                    erros.append(f'{grupo}[{i}] sem {cmp}')
            if x.get('confianca') and x['confianca'] not in ('CONFIRMED', 'UNCERTAIN', 'UNKNOWN'):
                erros.append(f'{grupo}[{i}]: confiança inválida')
    if erros:
        raise SystemExit('interpretação recusada:\n  ' + '\n  '.join(erros))


# ── relatório ────────────────────────────────────────────────────────────────
def resultado(cens):
    if not cens:
        return 'SEM TESTE'
    ok = sum(x['resultado'] == 'OK' for x in cens)
    return f'OK ({ok}/{len(cens)})' if ok == len(cens) else f'FALHA ({len(cens) - ok} de {len(cens)})'


def transacoes_regiao(projeto):
    """Transações definidas na região CICS do repositório (DEFINE TRANSACTION(x) ... PROGRAM(y)): programa -> transação."""
    out = {}
    for f in Path(projeto).rglob('*.txt'):
        if any(p in ('target', 'node_modules', '.git') for p in f.parts):
            continue
        try:
            txt = f.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        for m in re.finditer(r'DEFINE TRANSACTION\((\w+)\)[^\n]*?PROGRAM\((\w+)\)', txt):
            out[m.group(2)] = (m.group(1), f.relative_to(projeto).as_posix())
    return out


def mainframe(res, projeto, lk_regra):
    """Pedidos ao mainframe dos cenários ponta a ponta, resumo por programa coordenador e cobertura das transações da região."""
    pedidos, ids_, marcas = [], [], []
    por_prog = defaultdict(lambda: {'cens': set(), 'pedidos': 0, 'atendidos': 0, 'indisponivel': 0, 'falhas': 0, 'transacoes': set(), 'chamados': set(),
                                    'sql': defaultdict(set), 'regras': set()})
    for x in sorted(res['cenarios'], key=lambda x: x['id']):
        for i, p in enumerate(x.get('mainframe') or [], 1):
            t = p.get('tarefa') or {}
            v = por_prog[p['programa']]
            v['cens'].add(x['id'])
            v['regras'].update(x['regras'])
            v['pedidos'] += 1
            v['atendidos'] += bool(p['ok'] and t)
            v['indisponivel'] += bool(p['ok'] and p['indisponivel'])
            v['falhas'] += not p['ok']
            if t:
                v['transacoes'].add(t['transacao'])
                v['chamados'].update(q for q in t['programas'] if q != t['coordenador'])
                for q in t['sql']:
                    prog, _l, linha, op, _s, code = q.split(' ')
                    v['sql'][f'{prog} linha {linha} {op}'].add(code)
            pedidos.append((rm.with_links('', [rm.link(x['id'], FASE, x['id'])]), p['programa'], t.get('transacao', '—'), t.get('tarefa', '—'),
                            t.get('fila_pedido') or p['fila'], ' → '.join(t['programas']) if t else '—',
                            expansivel('\n'.join(t['sql'])) if t and t['sql'] else '—', t.get('fila_resposta') or '—',
                            ('sim' if t['syncpoint'] else 'não') if t else '—', p['situacao']))
            ids_.append(f'mf-{x["id"]}-{i}')
            marcas.append(not p['ok'])
    regiao = transacoes_regiao(projeto)
    resumo = [(prog, ', '.join(sorted(v['transacoes'])) or '—', ', '.join(sorted(v['chamados'])) or '—', v['pedidos'], v['atendidos'], v['indisponivel'], v['falhas'],
               expansivel('\n'.join(f'{k}: SQLCODE {", ".join(sorted(c, key=int))}' for k, c in sorted(v['sql'].items()))) if v['sql'] else '—',
               rm.with_links(f'{len(v["cens"])}: ', [rm.link(c, FASE, c) for c in sorted(v['cens'])]),
               rm.with_links('', [lk_regra(k) for k in sorted(v['regras'])])) for prog, v in sorted(por_prog.items())]
    cobertura = [(t, prog, arq, por_prog[prog]['atendidos'] if prog in por_prog else 0,
                  'exercitada' if por_prog.get(prog, {}).get('atendidos') else 'só indisponibilidade' if prog in por_prog else 'sem cenário')
                 for prog, (t, arq) in sorted(regiao.items(), key=lambda kv: kv[1][0])]
    return pedidos, ids_, marcas, resumo, cobertura, [c[-1] != 'exercitada' for c in cobertura]


def montar(c, imp, rastreio, cadeia, ops, projeto, res):
    apps = {a['aplicacao']: a for a in imp['aplicacoes']}
    interp = {chave(r['funcionalidade'], r['regra']): r for r in imp['regras']}
    cen_de = defaultdict(list)
    for x in res['cenarios']:
        for k in x['regras']:
            cen_de[k].append(x)
    eps_de = {r['k']: [o for o in ops if r['texto'] in o['regras'] and (r['f'] in o['func'] or r['f'].startswith('FC'))] for r in rastreio}
    codigo = {}   # chave -> [(âncora, módulo, arquivo, linha, trecho, papel)]
    for k, r in interp.items():
        lst = []
        for i, a in enumerate(r['implementacao'], 1):
            linha, trecho = localizar(projeto, a)
            lst.append((f'cod-{k.replace(".", "-")}-{i}', modulo_de(a['arquivo']), a['arquivo'], linha, trecho, a.get('papel', '')))
        codigo[k] = lst

    def lk_regra(k, rot=None):
        return rm.link(rot or k, FASE, ancora_regra(k))

    def lk_eps(lst):
        return rm.with_links('', [rm.link(f'{o["rotulo"]} ({o["app"]})', FASE, o['ancora']) for o in lst]) or '—'

    def lk_cens(lst, prefixo=''):
        return rm.with_links(prefixo, [rm.link(x, FASE, x) for x in lst]) if lst else '—'

    # rastreio por regra
    linhas, ids_, marcas = [], [], []
    for r in rastreio:
        k, ir = r['k'], interp[r['k']]
        cad = cadeia.get((r['f'], r['rotulo']), {'decisoes': set(), 'deterministicas': set(), 'no': None})
        cens = cen_de[k]
        st = resultado(cens)
        regra_cel = rm.with_links(r['rotulo'], [rm.link(cad['no'], '11 - business-rules', cad['no'])]) if cad['no'] else r['rotulo']
        if cad['decisoes']:
            origem = f'{len(cad["decisoes"])} decisão(ões): ' + ', '.join(sorted(cad['decisoes']))
        elif cad['deterministicas']:
            origem = 'regra determinística ' + ', '.join(sorted(cad['deterministicas']))
        else:
            origem = 'regra do programa corporativo (sem decisão na fase 13)'
        mods = sorted({m for _a, m, *_ in codigo[k]})
        linhas.append((regra_cel, rm.with_links('', [rm.link(r['f'], '12 - business-flows', r['f'])]), origem, r['app'], r['caso'], lk_eps(eps_de[k]),
                       ', '.join(mods), rm.with_links('', [rm.link(f'{Path(arq).name}:{ln}', FASE, an) for an, _m, arq, ln, _t, _p in codigo[k]]),
                       lk_cens([x['id'] for x in cens if x['nivel'] == 'unitário']), lk_cens([x['id'] for x in cens if x['nivel'] != 'unitário']),
                       st, ir['conformidade'].replace('_', ' '), ir.get('observacao') or ''))
        ids_.append(ancora_regra(k))
        marcas.append(not st.startswith('OK') or ir['conformidade'] != 'CONFORME')

    # casos de uso
    por_caso = defaultdict(lambda: {'regras': [], 'eps': {}, 'cens': {}})
    for r in rastreio:
        v = por_caso[(r['app'], r['caso'])]
        v['regras'].append(r['k'])
        for o in eps_de[r['k']]:
            v['eps'][o['ancora']] = o
        for x in cen_de[r['k']]:
            v['cens'][x['id']] = x
    casos = [(app, apps[app].get('modulo') or '—', caso, rm.with_links(f'{len(v["regras"])}: ', [lk_regra(k) for k in v['regras']]), lk_eps(v['eps'].values()),
              lk_cens(sorted(v['cens']), f'{len(v["cens"])}: '), resultado(list(v['cens'].values()))) for (app, caso), v in sorted(por_caso.items())]

    # endpoints
    regras_ep = defaultdict(list)
    for r in rastreio:
        for o in eps_de[r['k']]:
            regras_ep[o['ancora']].append(r['k'])
    endpoints, ids_ep = [], []
    for o in sorted(ops, key=lambda o: (o['app'], o['caminho'], o['metodo'])):
        ks = regras_ep.get(o['ancora'], [])
        cens = {x['id']: x for k in ks for x in cen_de[k]}
        endpoints.append((o['rotulo'], o['app'], (apps.get(o['app']) or {}).get('modulo') or '—', o['func'] or '—', o['operationId'],
                          rm.with_links(f'{len(ks)}: ', [lk_regra(k) for k in ks]) if ks else '—', lk_cens(sorted(cens), f'{len(cens)}: '),
                          resultado(list(cens.values())) if ks else 'sem regra'))
        ids_ep.append(o['ancora'])

    # cenários, evidências e cobertura unitária de cada cenário ponta a ponta
    ordem = sorted(res['cenarios'], key=lambda x: x['id'])
    unit_de = defaultdict(list)   # regra -> testes unitários que a citam
    for x in res['cenarios']:
        if x['nivel'] == 'unitário':
            for k in x['regras']:
                unit_de[k].append(x)
    cobertura, ids_cob, marcas_cob, sem_unit = [], [], [], []
    for x in ordem:
        if x['nivel'] == 'unitário':
            continue
        us = sorted({u['id'] for k in x['regras'] for u in unit_de[k]})
        faltam = [k for k in x['regras'] if not unit_de[k]]
        falham = sorted({u['id'] for k in x['regras'] for u in unit_de[k] if u['resultado'] != 'OK'})
        sit = 'sem teste unitário' if len(faltam) == len(x['regras']) else 'parcial' if faltam else 'unitário em falha' if falham else 'coberto'
        cobertura.append((rm.with_links('', [rm.link(x['id'], FASE, x['id'])]), rm.with_links('', [lk_regra(k) for k in x['regras']]), lk_cens(us, f'{len(us)}: '),
                          rm.with_links('', [lk_regra(k) for k in faltam]) if faltam else '—', ', '.join(falham) or '—', sit))
        ids_cob.append('cob-' + x['id'])
        marcas_cob.append(sit != 'coberto')
        if sit != 'coberto':
            sem_unit.append(x)
    evid_linhas, evid_ids = [], []   # uma linha por cenário com o link para a página de evidências dele (escrever_evidencias)
    for x in ordem:
        evs = x.get('evidencias') or []
        evid_linhas.append((rm.with_links('', [rm.link(x['id'], FASE, x['id'])]), x['nivel'], x['resultado'], len(evs),
                            ', '.join(sorted({e['tipo'] for e in evs})) or '—',
                            rm.with_links('', [rm.link_arquivo('abrir evidências', pagina_evidencia(x['id']), titulo_evidencia(x))]) if evs else 'sem evidência',
                            x.get('arquivo_evidencia') or '—'))
        evid_ids.append(f'ev-{x["id"]}')
    n_evid = sum(len(x.get('evidencias') or []) for x in ordem)
    sem_evid = [x for x in ordem if not x.get('evidencias')]

    def lk_evid(x):
        n = len(x.get('evidencias') or [])
        return rm.with_links(f'{n}: ', [rm.link_arquivo(', '.join(sorted({e['tipo'] for e in x['evidencias']})), pagina_evidencia(x['id']), titulo_evidencia(x))]) if n else 'sem evidência'

    def lk_unit(x):
        if x['nivel'] == 'unitário':
            return '—'
        us = sorted({u['id'] for k in x['regras'] for u in unit_de[k]})
        return lk_cens(us, f'{len(us)}: ') if us else 'nenhum'
    cenarios = [(x['id'], x['nivel'], rm.with_links('', [lk_regra(k) for k in x['regras']]), x['alvo'], x['descricao'], expansivel(x['entrada']), legivel(x['esperado']),
                 expansivel(x['obtido']), x.get('tempo_ms', '—'), x['resultado'], x['teste'], lk_evid(x), lk_unit(x)) for x in ordem]
    mf_pedidos, mf_ids, mf_marcas, mf_resumo, mf_cob, mf_cob_marcas = mainframe(res, projeto, lk_regra)
    n_ped = len(mf_pedidos)
    n_atend = sum(1 for x in res['cenarios'] for p in x.get('mainframe') or [] if p['ok'] and p.get('tarefa'))
    n_indisp = sum(1 for x in res['cenarios'] for p in x.get('mainframe') or [] if p['ok'] and p['indisponivel'])
    cod_linhas, cod_ids = [], []
    for r in rastreio:
        for an, mod, arq, ln, trecho, papel in codigo[r['k']]:
            cod_linhas.append((lk_regra(r['k']), mod, arq, ln, trecho, papel))
            cod_ids.append(an)

    tot = len(rastreio)
    garantidas = sum(1 for r in rastreio if resultado(cen_de[r['k']]).startswith('OK') and codigo[r['k']])
    n_ok = sum(x['resultado'] == 'OK' for x in res['cenarios'])
    conf = defaultdict(int)
    for r in rastreio:
        conf[interp[r['k']]['conformidade']] += 1
    resumo = [('regras de negócio no rastreio da fase 19', tot), ('casos de uso', len(por_caso)), ('endpoints dos contratos (fase 20)', len(ops)),
              ('endpoints com regra de negócio', sum(1 for o in ops if regras_ep.get(o['ancora']))),
              ('regras com decisão de origem na fase 13', sum(1 for r in rastreio if cadeia.get((r['f'], r['rotulo']), {}).get('decisoes'))),
              ('regras com código localizado (arquivo:linha)', sum(1 for r in rastreio if codigo[r['k']])),
              ('regras com teste unitário', sum(1 for r in rastreio if any(x['nivel'] == 'unitário' for x in cen_de[r['k']]))),
              ('regras com cenário ponta a ponta', sum(1 for r in rastreio if any(x['nivel'] != 'unitário' for x in cen_de[r['k']]))),
              ('cenários de teste', len(res['cenarios'])), ('cenários unitários', sum(x['nivel'] == 'unitário' for x in res['cenarios'])),
              ('cenários ponta a ponta', sum(x['nivel'] != 'unitário' for x in res['cenarios'])), ('cenários com resultado OK', n_ok),
              ('cenários em falha', len(res['cenarios']) - n_ok), ('regras garantidas (código localizado e todos os cenários OK)', garantidas),
              ('evidências registradas (requisição, resposta, log, consulta DB2, código e resultado do teste)', n_evid),
              ('cenários sem evidência', len(sem_evid)),
              ('cenários ponta a ponta que chegaram ao mainframe', sum(1 for x in res['cenarios'] if x.get('mainframe'))),
              ('pedidos ao mainframe postos na fila pelos serviços', n_ped),
              ('pedidos atendidos na região CICS pelo coordenador e o funcional, até o SYNCPOINT', n_atend),
              ('pedidos não processados de propósito (função indisponível: transação desabilitada)', n_indisp),
              ('pedidos ao mainframe em falha', n_ped - n_atend - n_indisp),
              ('transações da região exercitadas pelos cenários', f'{sum(1 for c in mf_cob if c[-1] == "exercitada")} de {len(mf_cob)}'),
              ('cenários ponta a ponta com teste unitário para todas as regras', sum(1 for c in cobertura if c[-1] == 'coberto')),
              ('cenários ponta a ponta com regra sem teste unitário', sum(1 for c in cobertura if c[-1] in ('parcial', 'sem teste unitário'))),
              ('regras conformes', conf['CONFORME']), ('regras divergentes (ver observação)', conf['DIVERGENTE']), ('regras não implementadas', conf['NAO_IMPLEMENTADA'])]
    execucoes = [(e['suite'], e['nivel'], e['comando'], e.get('inicio') or '—', e['total'], e['falhas']) for e in res['execucoes']]
    corresp = [(a['aplicacao'], a.get('modulo') or '— (fora do repositório)', a.get('observacao') or '') for a in imp['aplicacoes']]
    corp = [(p['programa'], p['modulo'], p.get('observacao') or '') for p in imp.get('programas_corporativos', [])]

    secs = [
        rm.S('resumo', 'Da regra de negócio ao teste', [
            rm.T('Do rastreio aos testes', ['Etapa', 'Quantidade'], resumo),
            rm.T('Execuções dos testes', ['Suíte', 'Nível', 'Comando', 'Início', 'Cenários', 'Falhas'], execucoes,
                 note=f'{res["projeto"]}: {res.get("ambiente", "")}. Resultados coletados em {res["gerado_em"]}.'),
            rm.T('Aplicações da arquitetura alvo e módulos do código gerado', ['Aplicação (fase 19)', 'Módulo do repositório', 'Observação'], corresp),
            rm.T('Programas corporativos chamados por LEGACY e módulos que os reproduzem', ['Programa', 'Módulo do repositório', 'Observação'], corp),
            rm.X('Como ler: cada linha do rastreio por regra vai da regra de negócio (link para a fase 11) às decisões de origem (fase 13), à aplicação e ao caso de uso '
                 '(fase 19), aos endpoints do contrato (fase 20), ao código (arquivo:linha, com o trecho na tabela de código) e aos cenários de teste, com o resultado da '
                 'execução. A regra é garantida quando o código foi localizado e todos os cenários que a citam passaram. Linhas destacadas pedem atenção: teste em falha '
                 'ou ausente, ou comportamento divergente do texto da regra.')]),
        rm.S('regras', 'Rastreio por regra de negócio', [
            rm.T('Rastreio por regra de negócio: origem, caso de uso, endpoint, código e teste',
                 ['Regra de negócio', 'Funcionalidade', 'Origem (fase 13)', 'Aplicação (fase 19)', 'Caso de uso', 'Endpoints (fase 20)', 'Módulos com o código',
                  'Código (arquivo:linha)', 'Testes unitários', 'Cenários ponta a ponta', 'Resultado', 'Conformidade', 'Observação'], linhas, ids=ids_, marks=marcas)]),
        rm.S('casos', 'Casos de uso', [
            rm.T('Casos de uso: regras, endpoints e cenários de teste', ['Aplicação (fase 19)', 'Módulo', 'Caso de uso', 'Regras de negócio', 'Endpoints (fase 20)',
                                                                                'Cenários de teste', 'Resultado'], casos)]),
        rm.S('endpoints', 'Endpoints', [
            rm.T('Endpoints dos contratos: regras e cenários de teste', ['Endpoint', 'Contrato (aplicação)', 'Módulo', 'Funcionalidade', 'operationId',
                                                                                'Regras de negócio', 'Cenários de teste', 'Resultado'], endpoints, ids=ids_ep,
                 note='Uma regra fica no endpoint cujo contrato a declara (x-business-rules ou recusa possível) na mesma funcionalidade; as regras dos programas '
                      'corporativos ficam nos endpoints que os chamam. Os cenários são os das regras do endpoint.')]),
        rm.S('cenarios', 'Cenários de teste', [
            rm.T('Cenários de teste: entrada, esperado, obtido e resultado', ['Cenário', 'Nível', 'Regras de negócio', 'Alvo', 'Descrição', 'Entrada', 'Esperado',
                                                                                     'Obtido', 'Tempo (ms)', 'Resultado', 'Teste (arquivo::método)', 'Evidências',
                                                                                     'Testes unitários das mesmas regras'], cenarios,
                 ids=[x['id'] for x in ordem], marks=[x['resultado'] != 'OK' for x in ordem],
                 note='Entrada e obtido longos aparecem resumidos: «…» expande o conteúdo completo (corpo da resposta, linha do log ou mensagem da asserção). '
                      'Tempo: duração da chamada HTTP, da consulta ao banco ou da leitura do log (ponta a ponta) e do método de teste (unitário). '
                      'Evidências: link para o que foi registrado no cenário (seção Evidências dos cenários).')]),
        rm.S('evidencias', 'Evidências dos cenários', [
            rm.T('Evidências de cada cenário', ['Cenário', 'Nível', 'Resultado', 'Evidências', 'Tipos', 'Página de evidências', 'Arquivo de origem'], evid_linhas,
                 ids=evid_ids,
                 note='As evidências de cada cenário abrem numa janela sobre este relatório (página do cenário na pasta evidencias, ao lado deste relatório; na visão para IA, '
                      'ia/evidencias/<cenário>.json). '
                      'Ponta a ponta: requisição e resposta HTTP, linhas de log de cada container da cadeia com o traceId da requisição, programas mainframe '
                      'executados na região CICS e consultas ao DB2 (arquivo de origem local/tests/evidencias/cenarios/<cenário>.json). Unitário: código do '
                      'método de teste (arquivo:linha) e resultado do JUnit (relatório do surefire).')]),
        rm.S('mainframe', 'Programas mainframe executados', [
            rm.T('Programas mainframe por coordenador', ['Coordenador', 'Transação', 'Programas chamados', 'Pedidos', 'Atendidos', 'Não processados (indisponível)',
                                                       'Falhas', 'Comandos SQL executados (SQLCODE)', 'Cenários', 'Regras de negócio'], mf_resumo,
                 note='Somado sobre os pedidos ao mainframe dos cenários ponta a ponta. Programas chamados: funcional e corporativos que a tarefa do coordenador '
                      'executou (LINK). Comandos SQL: programa, linha do fonte e comando, com os SQLCODE observados.'),
            rm.T('Transações da região CICS e cenários que as exercitaram', ['Transação', 'Programa coordenador', 'Definição', 'Pedidos atendidos', 'Situação'], mf_cob,
                 marks=mf_cob_marcas,
                 note='Transações definidas no arquivo de recursos CICS do repositório. Exercitada: algum cenário teve o pedido atendido por ela; só '
                      'indisponibilidade: só apareceu desabilitada; sem cenário: nenhum cenário ponta a ponta a exercitou.'),
            rm.T('Pedidos ao mainframe de cada cenário e a tarefa da região que os atendeu',
                 ['Cenário', 'Programa (adaptador MQ)', 'Transação', 'Tarefa', 'Fila do pedido', 'Programas executados', 'Comandos SQL', 'Fila da resposta',
                  'SYNCPOINT', 'Situação'], mf_pedidos, ids=mf_ids, marks=mf_marcas,
                 note='Cada pedido que o serviço pôs na fila (log do adaptador MQ, com o messageId) é casado, pelo id da mensagem, com a unidade de trabalho da região '
                      'CICS que o leu (MQGET), do log da região com o traceId da requisição. O teste falha quando o pedido não foi atendido pelo coordenador do '
                      'adaptador, sem o funcional ou sem SYNCPOINT; com a função indisponível (transação desabilitada), o correto é nenhuma tarefa ler o pedido.')]),
        rm.S('cobertura-unitaria', 'Cobertura unitária dos cenários', [
            rm.T('Cenários ponta a ponta e testes unitários das mesmas regras', ['Cenário ponta a ponta', 'Regras de negócio', 'Testes unitários das mesmas regras',
                                                                                  'Regras sem teste unitário', 'Testes unitários em falha', 'Situação'], cobertura,
                 ids=ids_cob, marks=marcas_cob,
                 note='Cada regra que um cenário ponta a ponta cobre deve ter também teste unitário no código gerado. Coberto: todas as regras do cenário têm '
                      'teste unitário e todos passaram; parcial: alguma regra sem teste unitário; sem teste unitário: nenhuma regra do cenário tem.')]),
        rm.S('codigo', 'Código das regras', [
            rm.T('Código de cada regra: arquivo, linha e trecho', ['Regra de negócio', 'Módulo', 'Arquivo', 'Linha', 'Trecho', 'Papel'], cod_linhas, ids=cod_ids,
                 note=f'Linhas procuradas no repositório {res["projeto"]} na geração deste relatório; uma âncora que não existe recusa o relatório.')])]
    cards = [rm.card('regras de negócio', tot), rm.card('regras garantidas por teste', garantidas), rm.card('cenários de teste', len(res['cenarios'])),
             rm.card('pedidos atendidos no mainframe', n_atend),
             rm.card('aplicações implementadas', sum(1 for a in imp['aplicacoes'] if a.get('modulo'))),
             rm.card('cenários em falha', len(res['cenarios']) - n_ok), rm.card('regras divergentes', conf['DIVERGENTE'])]
    return secs, cards, (tot, garantidas, len(res['cenarios']), len(res['cenarios']) - n_ok), codigo


PREFIXO_AMBIENTE = re.compile(r'(?<![\w-])teste-(?=[a-z0-9])')   # containers do ambiente de teste (teste.env): teste-cics, teste-tcap-srv-canal, teste-tcap1vlo…


def sem_prefixo_ambiente(res):
    """Nomes de programas e aplicações nos logs sem o prefixo do ambiente de teste: no alvo do cenário e no detalhe de cada evidência de log."""
    for x in res['cenarios']:
        x['alvo'] = PREFIXO_AMBIENTE.sub('', x['alvo'])
        for ev in x.get('evidencias') or []:
            if ev.get('tipo') == 'log' and isinstance(ev.get('detalhe'), str):
                ev['detalhe'] = PREFIXO_AMBIENTE.sub('', ev['detalhe'])
    return res


def pagina_evidencia(cid):
    """Caminho da página de evidências do cenário, relativo à página humana do relatório."""
    return f'evidencias/{quote(cid)}.html'


def titulo_evidencia(x):
    """Título da janela em que a página de evidências abre sobre o relatório (report_model.link_arquivo com modal)."""
    return f'Evidências · {x["id"]}'


CSS_EVID = """
.ficha{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px}
.ficha b{color:var(--mut);font-weight:600}.ok{color:#1e7e34;font-weight:700}.falha{color:#c62828;font-weight:700}
.ev{border:1px solid var(--line);border-left:5px solid var(--acc);border-radius:8px;background:var(--card);margin:14px 0;padding:8px 12px}
.ev h3{margin:2px 0 6px;font-size:15px}.ev .det{color:var(--mut);font-size:12px;margin-bottom:6px;word-break:break-all}
.ev pre{max-height:32em}.voltar{display:inline-block;margin-bottom:10px}.emb .voltar{display:none}
"""


def legivel_bloco(txt):
    """Conteúdo de uma evidência para leitura: JSON formatado com recuo; o resto como veio."""
    t = '' if txt is None else str(txt)
    try:
        return json.dumps(json.loads(t), ensure_ascii=False, indent=2)
    except (ValueError, TypeError):
        m = re.search(r'[{\[]', t)
        if m:
            try:
                return t[:m.start()] + json.dumps(json.loads(t[m.start():]), ensure_ascii=False, indent=2)
            except ValueError:
                pass
        return t


def html_evidencia(x, projeto):
    """Página de evidências de um cenário: ficha (regras, alvo, teste, resultado, tempo, trace), entrada/esperado/obtido e cada evidência num bloco."""
    e_ = html.escape
    ok = x['resultado'] == 'OK'
    ficha = [('Cenário', x['id']), ('Regras de negócio', ', '.join(x['regras'])), ('Nível', x['nivel']), ('Alvo', x['alvo']), ('Teste', x['teste']),
             ('Resultado', x['resultado']), ('Tempo', f'{x.get("tempo_ms", "—")} ms'), ('traceId', x.get('trace_id') or '—'),
             ('Executado em', x.get('executado_em') or '—'), ('Arquivo de origem', x.get('arquivo_evidencia') or '—')]
    linhas = ''.join(f'<b>{e_(k)}</b><span class="{("ok" if ok else "falha") if k == "Resultado" else ""}">{e_(str(v))}</span>' for k, v in ficha)
    comp = ''.join(f'<div class="ev"><h3>{e_(k)}</h3><pre>{e_(legivel_bloco(v))}</pre></div>' for k, v in
                   (('Entrada', x.get('entrada')), ('Esperado', x.get('esperado')), ('Obtido', x.get('obtido'))))
    evs = ''.join(f'<div class="ev"><h3>{e_(ev["tipo"])}</h3><div class="det">{e_(str(ev.get("detalhe") or ""))}</div>'
                  f'<pre>{e_(legivel_bloco(ev.get("conteudo")) or "(vazio)")}</pre></div>' for ev in x.get('evidencias') or [])
    tit = f'{x["id"]} · {x["descricao"]}'
    return (f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e_(tit)}</title><style>{rr.CSS}{CSS_EVID}</style><script>if(window.self!==window.top)document.documentElement.className="emb"</script></head><body><main style="max-width:1200px;margin:0 auto;padding:16px">'
            f'<a class="voltar" href="../report.html#ev-{quote(x["id"])}">← Casos de teste e evidências</a><h1>{e_(tit)}</h1>'
            f'<p class="sub">Evidências do cenário de teste em {e_(projeto)}.</p><div class="ficha">{linhas}</div>'
            f'<h2>Entrada, esperado e obtido</h2>{comp}<h2>Evidências ({len(x.get("evidencias") or [])})</h2>{evs or "<p>sem evidência registrada</p>"}'
            f'</main></body></html>')


def escrever_evidencias(saida, res):
    """Uma página por cenário em <fase>/human/evidencias/<cenário>.html e o mesmo conteúdo em <fase>/ia/evidencias/<cenário>.json; refaz as pastas."""
    base = Path(saida) / FASE
    for sub in (base / 'human' / 'evidencias', base / 'ia' / 'evidencias'):
        if sub.exists():
            shutil.rmtree(sub)
        sub.mkdir(parents=True)
    for x in res['cenarios']:
        (base / 'human' / 'evidencias' / f'{x["id"]}.html').write_text(html_evidencia(x, res['projeto']), encoding='utf-8')
        (base / 'ia' / 'evidencias' / f'{x["id"]}.json').write_text(json.dumps(x, ensure_ascii=False, indent=1), encoding='utf-8')
    return len(res['cenarios'])


COLS13 = ['Caso de uso', 'Aplicação', 'Classes que implementam']   # colunas que a rastreabilidade ganha na tabela ponta a ponta
NUMS13 = ('casos de uso', 'aplicações', 'classes que implementam regras')
COMPLEMENTO13 = ' Completada pela fase de casos de teste e evidências: → caso de uso → aplicação → classes que implementam cada regra e funcionalidade.'
COLS_CASOS = ['Caso de uso no BFF', 'Caso de uso no SRV']   # para onde a regra e a funcionalidade foram, por tipo de aplicação
TIPO_BFF, TIPOS_SRV = {'BFMF'}, {'VAS', 'DOMAIN_MICROSERVICE'}   # tipos de recurso da arquitetura alvo (fase 19)
COR_BFF, COR_SRV, COR_CORP = '#6A1B9A', '#00838F', '#5D4037'
COL_CORP = 'Programa corporativo'
TAB_CORP19 = 'Programas corporativos chamados pelos programas mainframe novos'


def servicos_corporativos(ana):
    """Programa corporativo -> (serviço que o chama, coordenador, funcional, programas entre o funcional e ele), da tabela da arquitetura alvo
    (fase 19). Corporativo que só é chamado por outro corporativo (grafo de chamadas da análise estática) herda o serviço de quem o chama, e o caminho
    registra os corporativos do meio."""
    d = json.loads((Path(ana) / '19 - target-architecture' / 'ia' / 'report.json').read_text(encoding='utf-8'))
    out = {}
    for s_ in d['sections']:
        for b in s_['blocks']:
            if b['type'] == 'table' and b['title'] == TAB_CORP19:
                col = {n: i for i, n in enumerate(b['columns'])}
                for row in b['rows']:
                    out[texto(row[col['Programa corporativo']])] = (texto(row[col['Executado por']]), texto(row[col['Coordenador (PROGRAM_COORD)']]),
                                                                    texto(row[col['PROGRAM_CORP']]))
    sm = Path(ana) / 'runtime' / 'static' / 'static-model.json'
    chamadores = defaultdict(set)
    for e in (json.loads(sm.read_text(encoding='utf-8')).get('call_graph') or []) if sm.exists() else []:
        chamadores[e['target']].add(e['caller'])
    def resolver(p, vistos=()):
        if p in out:
            return (*out[p], [])
        for c in sorted(chamadores.get(p, ())):
            if c not in vistos:
                x = resolver(c, vistos + (p,))
                if x:
                    return (*x[:3], x[3] + [c])
        return None
    return resolver


def programa_da_funcionalidade(m13):
    """Funcionalidade corporativa (FCnn) -> programa corporativo, da tabela "Por funcionalidade" da rastreabilidade."""
    out = {}
    for s_ in m13['sections']:
        for b in s_['blocks']:
            if b['type'] == 'table' and b['title'] == 'Por funcionalidade':
                for row in b['rows']:
                    fu = (ids(row[0]) or [texto(row[0])])[0]
                    if fu.startswith('FC'):
                        out[fu] = texto(row[2]).split(',')[0].strip()
    return out


def da_funcionalidade(r, fu, tipos):
    """Entrada do rastreio que vale para a funcionalidade: no BFF, só o caso de uso da própria funcionalidade (o BFF tem um caso de uso por
    funcionalidade, "Caso de uso <id>"); o caso de uso de outra funcionalidade que reaproveita a regra fica de fora. Nos serviços, todas."""
    if tipos.get(r['app']) not in TIPO_BFF:
        return True
    m = re.fullmatch(r'Caso de uso (F\w+)', r['caso'])
    return not m or m.group(1) == fu


def tipos_aplicacao(ana):
    """Aplicação -> tipo de recurso, da tabela de recursos da arquitetura alvo (fase 19)."""
    d = json.loads((Path(ana) / '19 - target-architecture' / 'ia' / 'report.json').read_text(encoding='utf-8'))
    b = next(b for s in d['sections'] if s['id'] == 'recursos' for b in s['blocks'] if b['type'] == 'table')
    return {texto(r[0]): texto(r[1]) for r in b['rows']}


def tirar_colunas(b, nomes):
    """Tira de uma tabela as colunas que este gerador pôs numa execução anterior (as últimas, com esses nomes)."""
    if b['columns'][-len(nomes):] == nomes:
        b['columns'] = b['columns'][:-len(nomes)]
        b['rows'] = [row[:-len(nomes)] for row in b['rows']]


def completar_fase13(saida, rastreio, cadeia, codigo, apps, tipos=None, corporativo=None):
    """Leva a rastreabilidade (fase 13) da funcionalidade até o código: cada regra de negócio ganha o caso de uso e a aplicação (rastreio da fase 19)
    e as classes que a implementam (âncoras de código desta fase, com link para o trecho). Grava na fase 13: as colunas COLS13 na tabela ponta a ponta,
    a seção "implementacao" (uma linha por regra de negócio), uma tabela por funcionalidade e os números do resumo. Idempotente: tira antes o que
    ela mesma pôs. Devolve quantas regras têm classe localizada."""
    f13 = Path(saida) / FASE13 / 'ia' / 'report.json'
    m = json.loads(f13.read_text(encoding='utf-8'))
    por_no = defaultdict(list)   # (funcionalidade, nó da regra de negócio na fase 11) -> regras do rastreio
    for r in rastreio:
        no = cadeia.get((r['f'], r['rotulo']), {}).get('no')
        if no:
            por_no[(r['f'], no)].append(r)
    ancoras = lambda rs: [rm.link(f'{Path(arq).stem}:{ln}', FASE, an) for r in rs for an, _m, arq, ln, _t, _p in codigo.get(r['k'], [])]   # noqa: E731
    classes = lambda rs: rm.with_links('', ancoras(rs)) if ancoras(rs) else '—'   # noqa: E731
    juntar = lambda xs: ', '.join(sorted(set(xs))) or '—'   # noqa: E731
    tipos = tipos or {}
    prog_fc = programa_da_funcionalidade(m)
    corp_de = {fu: (p, *(corporativo(p) or ('—', '—', '—', []))) for fu, p in prog_fc.items()} if corporativo else {}   # FC -> (programa, serviço, coord, funcional, meio)
    srv_corp = lambda fu: f'{corp_de[fu][1]} ({" → ".join([corp_de[fu][2], corp_de[fu][3]] + corp_de[fu][4] + [corp_de[fu][0]])})'   # noqa: E731
    eh = lambda r, grupo: tipos.get(r['app']) in grupo   # noqa: E731
    def casos_de(rs, grupo, fu=None):
        rs = [r for r in rs if eh(r, grupo) and (fu is None or da_funcionalidade(r, fu, tipos))]
        return juntar(f'{r["caso"]} ({r["app"]})' for r in rs) if rs else '—'
    # tabela ponta a ponta: decisão → regra determinística → regra de negócio → funcionalidade → caso de uso → aplicação → classes
    for sec in m['sections']:
        for b in sec['blocks']:
            if b['type'] == 'table' and b['title'] == TAB13:
                if b['columns'][-len(COLS13):] == COLS13:
                    b['columns'] = b['columns'][:-len(COLS13)]
                    b['rows'] = [row[:-len(COLS13)] for row in b['rows']]
                col = {n: i for i, n in enumerate(b['columns'])}
                for row in b['rows']:
                    rs = []
                    if texto(row[col['Situação da regra']]) == 'regra de negócio':
                        rs = [r for n in ids(row[col['Regra de negócio']]) for fu in ids(row[col['Funcionalidades']]) for r in por_no.get((fu, n), [])]
                    row += [juntar(r['caso'] for r in rs) if rs else '—', juntar(r['app'] for r in rs) if rs else '—', classes(rs)]
                b['columns'] += COLS13
    # uma linha por regra de negócio, e uma tabela por funcionalidade
    linhas, por_func = [], defaultdict(list)
    regras_func = defaultdict(lambda: defaultdict(list))   # funcionalidade -> regra (rótulo) -> entradas do rastreio (uma por aplicação)
    for r in rastreio:
        regras_func[r['f']][r['rotulo']].append(r)
    for r in sorted(rastreio, key=lambda r: (r['f'], r['rotulo'])):
        cad = cadeia.get((r['f'], r['rotulo']), {'decisoes': set(), 'no': None})
        regra = rm.with_links(r['rotulo'], [rm.link(cad['no'], '11 - business-rules', cad['no'])]) if cad['no'] else r['rotulo']
        mods = juntar(m_ for _a, m_, *_ in codigo.get(r['k'], []))
        origem = f'{len(cad["decisoes"])}: ' + ', '.join(sorted(cad['decisoes'])) if cad['decisoes'] else '—'
        linhas.append((regra, rm.with_links('', [rm.link(r['f'], '12 - business-flows', r['f'])]), origem, r['app'], (apps.get(r['app']) or {}).get('modulo') or '—',
                       r['caso'], mods, classes([r])))
        if r is regras_func[r['f']][r['rotulo']][0]:   # uma linha por regra na tabela da funcionalidade, com os casos de uso do BFF e do SRV
            rs = regras_func[r['f']][r['rotulo']]
            if r['f'] in corp_de:
                por_func[r['f']].append((regra, casos_de(rs, TIPO_BFF, r['f']), srv_corp(r['f']), corp_de[r['f']][0], classes(rs)))
            else:
                por_func[r['f']].append((regra, casos_de(rs, TIPO_BFF, r['f']), casos_de(rs, TIPOS_SRV), classes(rs)))
    m['sections'] = [s_ for s_ in m['sections'] if s_['id'] != 'implementacao']
    impl = rm.S('implementacao', 'Implementação: regra de negócio → caso de uso → aplicação → classes', [
        rm.X('Cada regra de negócio do rastreio vai até onde foi implementada: o caso de uso e a aplicação da arquitetura alvo e as classes do código '
             'gerado, com a linha (o link leva ao trecho na fase de casos de teste e evidências). Decisões de origem: as decisões do mapa de decisões que '
             'chegam à regra pela tabela ponta a ponta.'),
        rm.T('Regras de negócio implementadas', ['Regra de negócio', 'Funcionalidade', 'Decisões de origem', 'Aplicação', 'Módulo da aplicação', 'Caso de uso',
                                               'Módulos com o código', 'Classes que implementam'], linhas)])
    i = next((n for n, s_ in enumerate(m['sections']) if s_['id'] == 'rastreio'), -1)
    m['sections'].insert(i + 1, impl)
    for s_ in m['sections']:
        if s_['id'].startswith('rastreio-'):
            fu = s_['id'][len('rastreio-'):]
            s_['blocks'] = [b for b in s_['blocks'] if b.get('origem') != 'implementacao']
            rs_f = [r for r in rastreio if r['f'] == fu]
            for b in s_['blocks']:
                if b['type'] == 'graph':
                    diagrama_casos(b, fu, rs_f, cadeia, tipos, corp_de.get(fu))
                elif b['type'] == 'table' and b['title'].startswith('Tabela do diagrama'):
                    tirar_colunas(b, COLS_CASOS + [COL_CORP])
                    tirar_colunas(b, COLS_CASOS)
                    col = {n: i for i, n in enumerate(b['columns'])}
                    for row in b['rows']:
                        nos = set(ids(row[col['Regra de negócio']])) | {texto(row[col['Regra de negócio']])}
                        rs = [r for no in nos for r in por_no.get((fu, no), [])]
                        if fu in corp_de:
                            ativa = texto(row[col['Regra de negócio']]) not in ('', '—')
                            row += [casos_de(rs, TIPO_BFF, fu), srv_corp(fu) if ativa else '—', corp_de[fu][0] if ativa else '—']
                        else:
                            row += [casos_de(rs, TIPO_BFF, fu), casos_de(rs, TIPOS_SRV)]
                    b['columns'] += COLS_CASOS + ([COL_CORP] if fu in corp_de else [])
            if por_func.get(fu):
                cols_f = COLS_CASOS + [COL_CORP] if fu in corp_de else COLS_CASOS
                t = rm.T(f'{fu}: implementação das regras', ['Regra de negócio'] + cols_f + ['Classes que implementam'], por_func[fu])
                t['origem'] = 'implementacao'
                s_['blocks'].append(t)
        elif s_['id'] == 'funcionalidades':
            for b in s_['blocks']:
                if b['type'] == 'table' and b['title'] == 'Por funcionalidade':
                    tirar_colunas(b, ['Casos de uso no BFF', 'Casos de uso no SRV'])
                    for row in b['rows']:
                        fu_r = (ids(row[0]) or [texto(row[0])])[0]
                        rs = [r for r in rastreio if r['f'] == fu_r]
                        row += [casos_de(rs, TIPO_BFF, fu_r), srv_corp(fu_r) if fu_r in corp_de else casos_de(rs, TIPOS_SRV)]
                    b['columns'] += ['Casos de uso no BFF', 'Casos de uso no SRV']
    nomes_classes = {Path(arq).stem for r in rastreio for _an, _m, arq, *_ in codigo.get(r['k'], [])}
    m['summary'] = [c_ for c_ in m.get('summary') or [] if c_['label'] not in NUMS13] + [
        rm.card('casos de uso', len({(r['app'], r['caso']) for r in rastreio})), rm.card('aplicações', len({r['app'] for r in rastreio})),
        rm.card('classes que implementam regras', len(nomes_classes))]
    m['subtitle'] = m.get('subtitle', '').split(COMPLEMENTO13)[0] + COMPLEMENTO13
    S.escrever(saida, FASE13, m)
    return sum(1 for r in rastreio if codigo.get(r['k']))


def diagrama_casos(g, fu, rs, cadeia, tipos, corp=None):
    """No diagrama da funcionalidade (decisão → regra determinística → regra de negócio → funcionalidade), as colunas dos casos de uso no BFF e no
    SRV: a funcionalidade liga ao caso de uso do BFF, que liga aos casos de uso dos serviços, e cada regra de negócio liga ao caso de uso onde foi
    implementada. Tira antes o que pôs numa execução anterior (nós, ligações e colunas marcados com origem implementacao)."""
    g['nodes'] = [n for n in g['nodes'] if n.get('origem') != 'implementacao']
    g['edges'] = [e for e in g['edges'] if e.get('origem') != 'implementacao']
    nomes = [c['name'] for c in g.get('columns', [])]
    if nomes[-1:] == [COL_CORP]:
        g['columns'] = g['columns'][:-1]
        nomes = nomes[:-1]
    if nomes[-2:] == COLS_CASOS:
        g['columns'] = g['columns'][:-2]
    base = len(g['columns'])
    g['columns'] += [{'name': COLS_CASOS[0], 'color': COR_BFF}, {'name': COLS_CASOS[1], 'color': COR_SRV}]
    if corp:
        g['columns'].append({'name': COL_CORP, 'color': COR_CORP})
    existentes = {n['id'] for n in g['nodes']}
    rs = [r for r in rs if da_funcionalidade(r, fu, tipos)]
    nos = {}
    for r in rs:
        tp = tipos.get(r['app'])
        if tp not in TIPO_BFF | TIPOS_SRV:
            continue
        i = f'U:{r["app"]}|{r["caso"]}'
        if i not in nos:
            nos[i] = {'id': i, 'label': r['caso'], 'sub': r['app'], 'col': base + (0 if tp in TIPO_BFF else 1), 'origem': 'implementacao',
                      'detail': f'{r["caso"]} em {r["app"]} ({tp})'}
    if corp:   # funcionalidade corporativa: o serviço que chama o programa corporativo (coordenador → funcional → LINK) e o próprio programa
        prog, app, coord, func, meio = corp
        nos[f'U:{app}|corporativo'] = {'id': f'U:{app}|corporativo', 'label': app, 'sub': f'{coord} → {func}', 'col': base + 1, 'origem': 'implementacao',
                                       'detail': f'{app}: coordenador {coord} → funcional {func} → LINK ao programa corporativo {prog}'}
        nos[f'K:{prog}'] = {'id': f'K:{prog}', 'label': prog, 'sub': 'programa corporativo (mainframe)', 'col': base + 2, 'origem': 'implementacao',
                            'detail': f'{prog}: programa corporativo do mainframe, chamado por LINK: ' + ' → '.join([coord, func] + meio + [prog])}
    g['nodes'] += list(nos.values())
    bff = [i for i, n in nos.items() if n['col'] == base]
    srv = [i for i, n in nos.items() if n['col'] == base + 1]
    arestas = set()
    if f'F:{fu}' in existentes:
        for i in (bff or srv):
            arestas.add((f'F:{fu}', i))
    for a in bff:
        for b in srv:
            arestas.add((a, b))
    if corp:   # o serviço chama o programa corporativo; todas as regras de negócio ativas ficam no programa corporativo
        arestas.add((f'U:{corp[1]}|corporativo', f'K:{corp[0]}'))
        for n in g['nodes']:
            if n['id'].startswith('B:') and not n.get('inactive') and n.get('origem') != 'implementacao':
                arestas.add((n['id'], f'K:{corp[0]}'))
    for r in rs if not corp else []:
        no = cadeia.get((r['f'], r['rotulo']), {}).get('no')
        i = f'U:{r["app"]}|{r["caso"]}'
        if no and f'B:{no}' in existentes and i in nos:
            arestas.add((f'B:{no}', i))
    g['edges'] += [{'from': a, 'to': b, 'guarda': False, 'origem': 'implementacao'} for a, b in sorted(arestas)]


def main():
    args = sys.argv[1:]
    opc = {}
    for nome in ('--interpretacao', '--projeto', '--resultados'):
        if nome in args:
            i = args.index(nome)
            opc[nome] = Path(args[i + 1]).resolve()
            del args[i:i + 2]
    if not args or '--projeto' not in opc or '--resultados' not in opc:
        sys.exit(__doc__)
    base = opc.get('--interpretacao', TA.BASE)
    ana = Path(args[0])
    saida = Path(args[1]) if len(args) > 1 else ana
    imp = json.loads((Path(base) / INTERP / 'implementacao.json').read_text(encoding='utf-8'))
    res = sem_prefixo_ambiente(json.loads(opc['--resultados'].read_text(encoding='utf-8')))
    c = 'C'   # chave interna do modelo da arquitetura alvo (fase 19)
    rastreio = ler_rastreio19(ana, c)
    validar(imp, rastreio, opc['--projeto'], res)
    P = TA.preparar(ana, base)
    col, linhas13 = ler_fase13(ana)
    cadeia = cadeia_fase13(c, P['modelos'][c], P['f18s'][c], P['evs'][c], col, linhas13)
    secs, cards, (tot, gar, ncen, nfal), codigo = montar(c, imp, rastreio, cadeia, ler_contratos(ana, c), opc['--projeto'], res)
    rep = rm.model('Casos de teste e evidências',
                   f'Arquitetura alvo implementada em {res["projeto"]}: regra de negócio → decisões de origem → caso de uso → endpoint → código → cenário de teste → resultado',
                   cards, secs)
    S.escrever(saida, FASE, rep)
    escrever_evidencias(saida, res)
    n13 = completar_fase13(saida, rastreio, cadeia, codigo, apps={a['aplicacao']: a for a in imp['aplicacoes']}, tipos=tipos_aplicacao(ana),
                           corporativo=servicos_corporativos(ana))
    print(f'{tot} regras, {gar} garantidas por teste; {ncen} cenários de teste, {nfal} em falha; rastreabilidade (fase 13) completada com {n13} regras implementadas')


if __name__ == '__main__':
    main()
