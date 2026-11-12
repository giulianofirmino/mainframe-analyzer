#!/usr/bin/env python3
"""Relatório sql-mapping: mapeamento dos comandos SQL de todos os programas, estáticos e dinâmicos, lido ÚNICA E EXCLUSIVAMENTE dos relatórios gerados
(<fase>/ia/report.json das fases 0, 1, 4, 4b, 5 e 7).

  python3 gerar_sql.py <pasta-da-analise> [pasta-de-saida] [--interpretacao PASTA]   (padrão da saída: a pasta da análise)

Saída: <saida>/10 - sql-mapping/human/report.html e <saida>/10 - sql-mapping/ia/report.json (o mesmo modelo de visão, como as fases da análise).
Evidência calculada pelo script (a compilação que antes era uma seção do data-lineage): cada comando SQL estático de cada programa, com o código `<PROGRAMA>-Qnn`
da fase 4b, o texto SQL, as linhas, a natureza, quando executa, as condições WHERE, os campos como parâmetro e as colunas lidas com o destino do dado.
A interpretação (interpretacao-sql/mapeamento.json, prompt 5) explica cada comando (propósito, cada coluna, cada condição, tratamento do retorno) e descobre as
consultas dinâmicas (tabela passada por parâmetro), internalizando cada uma em comando estático `Qnn`. O script confere que todo comando foi explicado, que toda
coluna lida e toda condição WHERE foi coberta e que cada literal citado existe na evidência. Mesma entrada, mesma saída."""
import html
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import gerar_simulacao as S
import report_model as rm  # noqa: E402
import report_resumo as rs  # noqa: E402
from cores import COR_CLASSE, cor_sql  # noqa: E402

E = html.escape
AQUI = Path(__file__).resolve().parent
BASE = Path(os.environ['ANALISE_INTERPRETACOES']) if os.environ.get('ANALISE_INTERPRETACOES') else AQUI   # pasta das interpretações (a análise); o pipeline a informa
FASE = '10 - sql-mapping'
ORIGENS_SQL = {'montagem detectada', 'inferido dos parâmetros'}
CONFIANCAS = {'alta', 'média', 'baixa'}
SQL_INICIO = re.compile(r'(?i)^\s*(SELECT|WITH|INSERT|UPDATE|DELETE|MERGE|CALL)\b')


def curto(t):
    return str(t).split('.')[-1]


def codigo_de(c):
    return str(c).split(' ')[0]


# ----------------------------------------------------------------------------- evidência calculada
def coletar(ana):
    """Comandos SQL estáticos (04b) com o texto SQL (04), condições, parâmetros e colunas lidas; e a compilação de todos os comandos da fase 4."""
    f4, f4b = S.fase(ana, '04-'), S.fase(ana, '04b-')
    sqls, lin = {}, []
    for _s, bt, rs_ in S.tabelas(f4):
        if bt.startswith('Comandos SQL sobre '):
            for r in rs_:
                sqls[r['Id']] = r
                lin.append(r)
    cmds, cond, said, par = [], defaultdict(list), defaultdict(list), defaultdict(list)
    for _s, bt, rs_ in S.tabelas(f4b):
        if bt.startswith('Comandos SQL de '):
            cmds += rs_
        elif bt.startswith('Condições do WHERE de '):
            for r in rs_:
                cond[codigo_de(r['Comando SQL'])].append(r)
        elif bt.startswith('Saídas de '):
            for r in rs_:
                said[codigo_de(r['Comando SQL'])].append(r)
        elif bt.startswith('Campos como parâmetro de '):
            for r in rs_:
                par[codigo_de(r['Comando SQL'])].append(r)
    por_id = {}
    for c in cmds:
        cod = c['Código (link fase 4)']
        prog = cod.split('-Q')[0]
        linhas = [int(x) for x in re.findall(r'\d+', c['Linhas'])]
        c['programa'] = prog
        c['linhas'] = linhas
        c['sql'] = ''
        for ln in linhas:
            r = sqls.get(f'{prog}@{ln}:{curto(c["Tabela"])}')
            if r:
                c['sql'] = r['SQL']
                break
        c['cond'], c['said'], c['par'] = cond.get(cod, []), said.get(cod, []), par.get(cod, [])
        c['evidencia'] = '\n'.join([c['sql'], ' '.join(str(v) for v in c.values() if isinstance(v, str))] + [' '.join(str(v) for v in r.values()) for r in c['cond'] + c['said'] + c['par']])
        por_id[cod] = c
    # compilação: cada comando da fase 4 aponta o comando agrupado da fase 4b a que pertence (programa, tabela e linha)
    for r in lin:
        r['codigo'] = ''
        r['tabela'] = 'DB2PRD.' + r['Id'].split(':')[-1]
        for c in cmds:
            if c['programa'] == r['Programa'] and curto(c['Tabela']) == curto(r['Id'].split(':')[-1]) and int(r['Linha']) in c['linhas']:
                r['codigo'] = c['Código (link fase 4)']
                r['tabela'] = c['Tabela']
                break
    lin.sort(key=lambda r: (r['Programa'], int(r['Linha']), r['Id']))
    n_orig = len(cmds)
    cmds, alias = unificar(cmds, por_id, lin)
    return {'cmds': cmds, 'por_id': por_id, 'lin': lin, 'alias': alias, 'n_orig': n_orig}


# ----------------------------------------------------------------------------- queries equivalentes (FROM e WHERE iguais) unificadas
SQL_FIM = re.compile(r'(?i)\b(ORDER\s+BY|FOR\s+(?:FETCH|READ)\s+ONLY|WITH\s+(?:UR|CS|RS|RR)\b|OPTIMIZE\s+FOR|FETCH\s+FIRST)')
FUNCOES_SQL = {'IFNULL', 'VALUE', 'COALESCE', 'CHAR', 'DIGITS', 'DATE', 'TIMESTAMP', 'INTEGER', 'DECIMAL', 'SUBSTR', 'MAX', 'MIN', 'SUM', 'COUNT', 'AVG', 'CURRENT'}
COD_Q = re.compile(r'\b[A-Z0-9]{8}-Q\d{2}\b')


def _divide_virgulas(t):
    out, nivel, atual = [], 0, ''
    for ch in t:
        nivel += (ch == '(') - (ch == ')')
        if ch == ',' and nivel == 0:
            out.append(atual.strip())
            atual = ''
        else:
            atual += ch
    if atual.strip():
        out.append(atual.strip())
    return out


def partes_select(sql):
    """(colunas do SELECT, FROM+WHERE, cauda: ORDER BY etc.) de um SELECT; None se não for SELECT simples."""
    m = re.match(r'(?is)^SELECT\s+(.*?)\s+FROM\s+(.*)$', ' '.join(str(sql).split()))
    if not m:
        return None
    sel = re.split(r'(?i)\s+INTO\s*:', m.group(1), 1)[0]
    resto = m.group(2)
    f = SQL_FIM.search(resto)
    fw, cauda = (resto[:f.start()].strip(), resto[f.start():].strip()) if f else (resto.strip(), '')
    return _divide_virgulas(sel), fw, cauda


def _cods(t):
    return [x.strip() for x in str(t or '').split(',') if x.strip()]


def unificar(cmds, por_id, lin):
    """Comandos SELECT com o mesmo FROM e o mesmo WHERE (mesmo que leiam colunas diferentes, em programas diferentes) são uma query única: a de menor código é a canônica e leva a união das
    colunas; os demais ficam em `membros` e em `alias` (código original -> código da query única). Devolve (queries, alias)."""
    grupos, ordem = defaultdict(list), []
    for c in cmds:
        c['_p'] = partes_select(c['sql']) if str(c['Operação']).upper().startswith('SELECT') else None
        chave = re.sub(r'\s+', '', c['_p'][1]).upper() if c['_p'] else '#' + c['Código (link fase 4)']
        if chave not in grupos:
            ordem.append(chave)
        grupos[chave].append(c)
    alias = {}
    for chave in ordem:
        mem = sorted(grupos[chave], key=lambda x: x['Código (link fase 4)'])
        for m_ in mem[1:]:
            alias[m_['Código (link fase 4)']] = mem[0]['Código (link fase 4)']

    def sub(c, texto):
        own = alias.get(c['Código (link fase 4)'], c['Código (link fase 4)'])
        return ', '.join(x for x in dict.fromkeys(alias.get(y, y) for y in _cods(texto)) if x != own)
    out = []
    for chave in ordem:
        mem = sorted(grupos[chave], key=lambda x: x['Código (link fase 4)'])
        for c in mem:
            c['Recebe dado de'], c['Entrega dado a'] = sub(c, c['Recebe dado de']), sub(c, c['Entrega dado a'])
        copias = [dict(c) for c in mem]
        m = dict(mem[0])
        m['membros'] = copias
        m['equivalentes'] = [c['Código (link fase 4)'] for c in mem[1:]]
        m['programas'] = sorted({c['programa'] for c in mem})
        m['obs'] = []
        if len(mem) > 1:
            itens, vistos = [], set()
            for c in mem:
                for it in c['_p'][0]:
                    k = tuple(t for t in re.findall(r'(?<![\w.])(?:[A-Z]\.)?([A-Z][A-Z0-9_]+)', it.upper()) if t not in FUNCOES_SQL) or re.sub(r'\s+', '', it).upper()
                    if k not in vistos:
                        vistos.add(k)
                        itens.append(it)
            cauda = mem[0]['_p'][2]
            m['sql_original'] = mem[0]['sql']
            m['sql'] = f'SELECT {", ".join(itens)} FROM {mem[0]["_p"][1]}' + (' ' + cauda if cauda else '')
            caudas = {re.sub(r'\s+', '', c['_p'][2]).upper() for c in mem}
            if len(caudas) > 1:
                m['obs'].append('A ordenação difere entre os comandos unificados; a query única usa a do comando de menor código (' + ' | '.join(f'{c["Código (link fase 4)"]}: {c["_p"][2] or "sem ORDER BY"}' for c in mem) + ').')
            m['obs'].append('Cada programa recebe as colunas nos próprios campos (INTO); a query única devolve a união das colunas lidas.')
            seen = set()
            m['said'] = [r for c in mem for r in c['said'] if not (tuple(sorted(r.items())) in seen or seen.add(tuple(sorted(r.items()))))]
            seen = set()
            m['cond'] = [r for c in mem for r in c['cond'] if not (r['Trecho do SQL'] in seen or seen.add(r['Trecho do SQL']))]
            seen = set()
            m['par'] = [r for c in mem for r in c['par'] if not (tuple(sorted(r.items())) in seen or seen.add(tuple(sorted(r.items()))))]
            m['evidencia'] = '\n'.join(c['evidencia'] for c in mem)
            for k in ('Recebe dado de', 'Entrega dado a'):
                m[k] = ', '.join(dict.fromkeys(x for c in mem for x in _cods(c[k])))
            m['linhas'] = sorted({ln for c in mem for ln in c['linhas']})
            m['Executado'] = 'sim' if any(c.get('Executado') == 'sim' for c in mem) else mem[0].get('Executado', '')
            m['Entry points'] = ', '.join(dict.fromkeys(x.strip() for c in mem for x in str(c['Entry points']).split(',') if x.strip()))
        out.append(m)
        for c in mem:
            por_id[c['Código (link fase 4)']] = m
    for r in lin:
        if r['codigo']:
            r['codigo'] = alias.get(r['codigo'], r['codigo'])
    return out, alias


def dobrar_interpretacao(interp, ev):
    """A interpretação (prompt 5) explicou cada comando original. Para a query única, junta a explicação dos comandos unificados na do comando canônico: propósito e retorno de cada um,
    a união das colunas e das condições. Um novo run do prompt 5 já explica a query única direto; as entradas dos comandos unificados, se existirem, são absorvidas aqui."""
    alias = ev['alias']
    if not alias:
        return
    est = {x['codigo']: x for x in interp['comandos_estaticos']}
    conf = ['alta', 'média', 'baixa']
    grupos = defaultdict(list)
    for a, cn in alias.items():
        grupos[cn].append(a)
    for cn, als in grupos.items():
        base = est.get(cn)
        if not base:
            continue
        for a in sorted(als):
            x = est.get(a)
            if not x:
                continue
            for k in ('proposito', 'retorno'):
                tx = str(x.get(k, '')).strip()
                if tx and ' '.join(tx.split()).lower() not in ' '.join(str(base.get(k, '')).split()).lower():
                    base[k] = (str(base.get(k, '')).strip() + f' | {a}: {tx}').strip(' |')
            if x.get('confianca') in conf and base.get('confianca') in conf:
                base['confianca'] = conf[max(conf.index(x['confianca']), conf.index(base['confianca']))]
            for lst in ('colunas', 'condicoes'):
                tem = {w.get('coluna', '').upper() for w in base.get(lst) or []}
                for w in x.get(lst) or []:
                    if w.get('coluna', '').upper() not in tem:
                        base.setdefault(lst, []).append(w)
                        tem.add(w.get('coluna', '').upper())
            if x.get('lacunas'):
                base['lacunas'] = list(dict.fromkeys((base.get('lacunas') or []) + x['lacunas']))
    interp['comandos_estaticos'] = [x for x in interp['comandos_estaticos'] if x.get('codigo') not in alias]


def colunas_gravadas(sql):
    """Colunas que um INSERT (lista entre parênteses) ou UPDATE (lado esquerdo do SET) grava."""
    s = ' '.join(sql.split())
    m = re.match(r'(?i)INSERT INTO \S+\s*\(([^)]*)\)', s)
    if m:
        return [x.strip().split('.')[-1] for x in m.group(1).split(',') if x.strip()]
    m = re.search(r'(?i)\bSET\b(.*?)(\bWHERE\b|$)', s)
    if re.match(r'(?i)UPDATE\b', s) and m:
        return re.findall(r'([A-Za-z_][\w]*)\s*=', m.group(1))
    return []


def colunas_lidas(c):
    return sorted({r['Coluna lida'] for r in c['said'] if r.get('Coluna lida')})


def trechos_where(c):
    return sorted({r['Trecho do SQL'] for r in c['cond'] if r.get('Trecho do SQL')})


# ----------------------------------------------------------------------------- códigos Qnn dos comandos estáticos de consultas dinâmicas
def caixas_efetivas(linhas):
    """{código: 'executado' | 'não executado'} do mapa de decisão (fase 5), em ordem. Uma chamada a outro módulo (CICS LINK, CALL) cujo módulo é simulado (mock) aparece como
    'não executado' porque o rastreio termina nela; se a caixa seguinte do mesmo parágrafo foi executada (o tratamento do retorno da chamada), a chamada aconteceu e conta como executada."""
    linhas = [r for r in linhas if 'Execução' in r]   # a tabela 'Trechos não executados' repete os códigos sem a coluna
    out = {}
    for i, r in enumerate(linhas):
        st = r.get('Execução', '')
        if st == 'não executado' and r.get('Tipo') == 'execução' and re.match(r'^\s*(CICS\s+LINK|CALL|EXEC\s+CICS\s+LINK|CICS\s+XCTL)\b', str(r.get('Condição ou comandos', '')), re.I):
            prox = linhas[i + 1] if i + 1 < len(linhas) else None
            if prox and prox.get('Parágrafo') == r.get('Parágrafo') and prox.get('Execução') == 'executado':
                st = 'executado'
        out[r.get('Código', '')] = st
    return out


def caixa_executada(d, cod):
    """Caixa do mapa de decisão (fase 5) executada por algum cenário? None se o código não existe ou não é caixa de execução."""
    if '_ef' not in d:
        d['_ef'] = caixas_efetivas(r for _p, r in d['mapa'])
    for _p, r in d['mapa']:
        if r.get('Código') == cod and 'Execução' in r:
            return (d['_ef'].get(cod) == 'executado') if r.get('Tipo') == 'execução' else None
    return None


def caixas_do_caso(it):
    """{caso (quando): código da caixa que o executa} de uma internalização: o comando principal e cada variante."""
    out = {'comando principal': str(it.get('executa_em', '')).strip()}
    for v in it.get('variantes', []):
        out[v['quando']] = str(v.get('executa_em', '')).strip()
    return out


def codigos_dinamicos(dins, estaticos=()):
    """Cada comando SQL estático que substitui uma consulta dinâmica (principal e variantes) tem o código `<programa que executa>-Qnn`, o mesmo padrão dos comandos estáticos:
    a numeração continua a dos comandos estáticos do programa (`estaticos`: códigos já usados) e segue a ordem das consultas.
    Devolve ({id da consulta: [(código, quando, sql)]}, {código: [casos que ele atende]}). O mesmo SQL para mais de um caso tem um código só."""
    cmd_de, q_lista, ult = {}, {}, defaultdict(int)
    for c in estaticos:
        m = re.match(r'^(.+)-Q(\d+)$', str(c))
        if m:
            ult[m.group(1)] = max(ult[m.group(1)], int(m.group(2)))
    for x in dins.values():
        it_ = x.get('internalizacao') or {}
        lst, vistos_ = [], {}
        for quando_, sql_ in [('comando principal', it_.get('comando_fixo', ''))] + [(v_['quando'], v_['sql']) for v_ in it_.get('variantes', [])]:
            chave_ = ' '.join(sql_.upper().split())
            if chave_ in vistos_:
                c0_, q0_, s0_ = lst[vistos_[chave_]]
                q_lista[c0_].append(quando_)
                lst[vistos_[chave_]] = (c0_, q0_ + '; ' + quando_, s0_)
                continue
            ult[x['servico']] += 1
            cod_ = f'{x["servico"]}-Q{ult[x["servico"]]:02d}'
            vistos_[chave_] = len(lst)
            lst.append((cod_, quando_, sql_))
            q_lista[cod_] = [quando_]
        cmd_de[x['id']] = lst
    return cmd_de, q_lista


def carregar_mapeamento(base):
    """Interpretação do mapeamento (None se a fase de IA ainda não foi executada) com os códigos Qnn calculados."""
    p = Path(base) / 'interpretacao-sql' / 'mapeamento.json'
    if not p.exists():
        return None
    interp = S.carregar(p)
    interp.setdefault('comandos_estaticos', [])
    interp.setdefault('consultas_dinamicas', [])
    dins = {x['id']: x for x in interp['consultas_dinamicas']}
    interp['_dins'] = dins
    interp['_cmd_de'], interp['_q_lista'] = codigos_dinamicos(dins, [c.get('codigo') for c in interp['comandos_estaticos']])
    return interp


# ----------------------------------------------------------------------------- validação
def validar(d, eps, ev, interp, evid_fn):
    """Devolve (erros, falhas): erros = inconsistência estrutural (aborta); falhas = afirmação sem evidência (contada no relatório)."""
    erros, falhas = [], []
    por_id = ev['por_id']
    est = {}
    for x in interp['comandos_estaticos']:
        c = x.get('codigo')
        if c not in por_id:
            erros.append(f'comando estático inexistente na fase 4b: {c}')
        elif c in est:
            erros.append(f'comando estático repetido: {c}')
        else:
            est[c] = x
    for c in {x['Código (link fase 4)'] for x in ev['cmds']}:
        if c not in est:
            erros.append(f'comando estático sem explicação na interpretação: {c}')
    for c, x in est.items():
        cmd = por_id.get(c)
        if not cmd:
            continue
        if 'unifica' in x and sorted(x.get('unifica') or []) != sorted(cmd['equivalentes']):
            falhas.append(f'{c}: `unifica` deve listar os comandos de mesmo FROM e WHERE ({", ".join(cmd["equivalentes"]) or "nenhum"}); veio {x.get("unifica")}')
        evid = S.sem_copybook(cmd['evidencia'])
        for k in ('proposito', 'retorno'):
            if not str(x.get(k, '')).strip():
                falhas.append(f'{c}: falta `{k}`')
        if x.get('confianca') not in CONFIANCAS:
            falhas.append(f'{c}: `confianca` deve ser um de {sorted(CONFIANCAS)}')
        sql_up = cmd['sql'].upper()
        for col in x.get('colunas') or []:
            if not all(str(col.get(k, '')).strip() for k in ('coluna', 'significado', 'cita')):
                falhas.append(f'{c}: coluna precisa de coluna, significado e cita ({col})')
            elif col['coluna'].upper() not in sql_up:
                falhas.append(f'{c}: coluna {col["coluna"]} explicada, mas ausente do comando SQL')
            elif S.sem_copybook(col['cita']) not in evid:
                falhas.append(f'{c}: literal sem evidência na coluna {col["coluna"]}: {col["cita"]}')
        explicadas = {col.get('coluna', '').upper() for col in x.get('colunas') or []}
        esperadas = set(colunas_lidas(cmd)) | set(colunas_gravadas(cmd['sql']))
        for col in sorted(esperadas):
            if col.upper() not in explicadas:
                falhas.append(f'{c}: coluna {col} do comando (lida ou gravada) sem explicação')
        for w in x.get('condicoes') or []:
            if not all(str(w.get(k, '')).strip() for k in ('coluna', 'significado', 'cita')):
                falhas.append(f'{c}: condição precisa de coluna, significado e cita ({w})')
            elif w['coluna'].upper() not in sql_up or 'WHERE' not in sql_up:
                falhas.append(f'{c}: condição em {w["coluna"]} explicada, mas ausente do WHERE do comando')
            elif S.sem_copybook(w['cita']) not in evid:
                falhas.append(f'{c}: literal sem evidência na condição {w["coluna"]}: {w["cita"]}')
        cobertas = [w.get('coluna', '').upper() for w in x.get('condicoes') or []]
        for t in trechos_where(cmd):
            if not any(co and co in t.upper() for co in cobertas):
                falhas.append(f'{c}: condição WHERE sem explicação: {t}')
    # ---- consultas dinâmicas
    dins = interp['_dins']
    evids = {ep: evid_fn(ep, e, d) for ep, e in eps.items()}
    mapa_txt = defaultdict(str)
    for pr_, r_ in d['mapa']:
        mapa_txt[pr_] += '\n' + r_.get('Condição ou comando', r_.get('Condição ou comandos', ''))
    ids_vistos = set()
    for x in interp['consultas_dinamicas']:
        i = x['id']
        if i in ids_vistos:
            erros.append(f'consulta dinâmica repetida: {i}')
        ids_vistos.add(i)
        it = x.get('internalizacao') or {}
        for c in ('proposito', 'comando_fixo'):
            if not str(it.get(c, '')).strip():
                falhas.append(f'{i}: consulta dinâmica sem internalizacao.{c} (o comando vira estático com a tabela fixa e o programa assume o novo propósito)')
        for caso_, cx_ in caixas_do_caso(it).items():
            if caixa_executada(d, cx_) is None:
                falhas.append(f'{i}: `executa_em` do caso "{caso_[:50]}" ({cx_ or "vazio"}) não é uma caixa de execução do mapa de decisão (fase 5)')
            elif not cx_.startswith(x['servico'] + ':'):
                falhas.append(f'{i}: `executa_em` {cx_} não é uma caixa do serviço {x["servico"]}')
        cmd_ = str(it.get('comando_fixo', '')).strip()
        if cmd_ and not SQL_INICIO.match(cmd_):
            falhas.append(f'{i}: internalizacao.comando_fixo não é um comando SQL ({cmd_[:60]})')
        if cmd_ and not any(curto(t_['nome']).upper() in cmd_.upper() for t_ in x['tabelas']):
            falhas.append(f'{i}: internalizacao.comando_fixo não cita a tabela fixada ({", ".join(curto(t_["nome"]) for t_ in x["tabelas"])})')
        if it.get('origem') not in ORIGENS_SQL:
            falhas.append(f'{i}: internalizacao.origem deve ser um de {sorted(ORIGENS_SQL)}')
        if it.get('origem') == 'montagem detectada' and not str(it.get('montagem', '')).strip():
            falhas.append(f'{i}: internalizacao.origem "montagem detectada" exige internalizacao.montagem (o texto montado, como aparece na fase 1)')
        for v_ in it.get('variantes', []):
            if not (str(v_.get('quando', '')).strip() and SQL_INICIO.match(str(v_.get('sql', '')))):
                falhas.append(f'{i}: variante da internalização precisa de `quando` e `sql` (comando SQL)')
        cols_, whs_ = it.get('colunas_select') or [], it.get('condicoes_where') or []
        if not cols_ and not str(it.get('colunas_nao_inferidas', '')).strip():
            falhas.append(f'{i}: internalizacao.colunas_select vazio: infira as colunas pela saída e pelo uso nos chamadores (ou explique em colunas_nao_inferidas)')
        sqls_ = [cmd_] + [str(v_.get('sql', '')) for v_ in it.get('variantes', [])]
        evus_ = S.sem_copybook(' '.join(evids.get(ep, '') for ep in x['usada_por']))
        for c_ in cols_:
            if not all(str(c_.get(k_, '')).strip() for k_ in ('coluna', 'posicao', 'cita')):
                falhas.append(f'{i}: coluna do SELECT precisa de coluna, posicao e cita ({c_})')
            elif not any(c_['coluna'].upper() in s_.upper() for s_ in sqls_):
                falhas.append(f'{i}: coluna {c_["coluna"]} inferida, mas ausente dos comandos SQL')
            elif S.sem_copybook(c_['cita']) not in evus_:
                falhas.append(f'{i}: literal sem evidência na coluna {c_["coluna"]}: {c_["cita"]}')
        for w_ in whs_:
            if not all(str(w_.get(k_, '')).strip() for k_ in ('coluna', 'operador', 'parametro', 'cita')):
                falhas.append(f'{i}: condição do WHERE precisa de coluna, operador, parametro e cita ({w_})')
            elif not any(w_['coluna'].upper() in s_.upper() and 'WHERE' in s_.upper() for s_ in sqls_):
                falhas.append(f'{i}: condição em {w_["coluna"]} inferida, mas nenhum comando SQL a tem no WHERE')
            elif S.sem_copybook(w_['cita']) not in evus_:
                falhas.append(f'{i}: literal sem evidência na condição {w_["coluna"]}: {w_["cita"]}')
        usos_ = x.get('usos') or []
        if not usos_:
            falhas.append(f'{i}: `usos` vazio: analise o uso do serviço por chamador (tipo de consulta, colunas lidas, retorno tratado)')
        for u_ in usos_:
            if not all(str(u_.get(k_, '')).strip() for k_ in ('chamador', 'tipo_consulta', 'finalidade', 'colunas_lidas', 'retorno_tratado', 'cita')):
                falhas.append(f'{i}: uso do serviço incompleto: {u_}')
                continue
            ev_ch_ = ' '.join(evids.get(k_, '') for k_, e_ in eps.items() if k_ == u_['chamador'] or any(q['programa'] == u_['chamador'] for q in e_['programas']))
            if not ev_ch_:
                erros.append(f'{i}: chamador inexistente nos relatórios: {u_["chamador"]}')
            elif S.sem_copybook(u_['cita']) not in S.sem_copybook(ev_ch_):
                falhas.append(f'{i}: literal sem evidência no uso de {u_["chamador"]}: {u_["cita"]}')
        if x['servico'] not in d['alc_prog']:
            falhas.append(f'{i}: serviço {x["servico"]} não foi alcançado na análise dinâmica')
        for ep in x['usada_por']:
            if ep not in eps:
                erros.append(f'{i}: entry point inexistente {ep}')
            elif x['servico'] not in {q['programa'] for q in eps[ep]['programas']}:
                falhas.append(f'{i}: {ep} não alcança o serviço {x["servico"]}')
        for c in x['cita']:
            if not any(S.sem_copybook(c) in S.sem_copybook(evids.get(ep, '')) for ep in x['usada_por']):
                falhas.append(f'{i}: literal sem evidência: {c}')
        for t in x['tabelas']:
            if S.sem_copybook(x['parametro']) not in S.sem_copybook(t['cita']):
                falhas.append(f'{i}/{t["nome"]}: a citação deve conter o campo de parâmetro {x["parametro"]}')
            if t['nome'] not in t['cita']:
                falhas.append(f'{i}/{t["nome"]}: a citação não contém o nome da tabela')
            if not t['passado_por']:
                falhas.append(f'{i}/{t["nome"]}: nenhum programa passa a tabela')
            for pg in t['passado_por']:
                if t['cita'] not in mapa_txt.get(pg, ''):
                    falhas.append(f'{i}/{t["nome"]}: a citação não aparece nos comandos de {pg} (mapa de decisão)')
                if not any(pg in {q['programa'] for q in eps[ep]['programas']} for ep in x['usada_por'] if ep in eps):
                    falhas.append(f'{i}/{t["nome"]}: {pg} não é alcançado por nenhum entry point que usa a consulta')
    return erros, falhas


# ----------------------------------------------------------------------------- relatório
def _no_prog(p, classes, ativo=True):
    return {'id': 'p', 'col': 1, 'label': p, 'sub': classes.get(p, ''), 'detail': f'programa {p} ({classes.get(p, "")})', 'cor': COR_CLASSE.get(classes.get(p, ''), rs.NEUTRA)}


def _grafo_programa(p, cmds, dinq, chamadas, classes, ex_q=None):
    """Programa que executa o comando SQL e as tabelas envolvidas: quem chama o programa -> programa -> comando SQL -> tabela."""
    nos = [_no_prog(p, classes)]
    arestas, tab = [], {}
    for c in chamadas:
        if c['Programa chamado'] == p and c['Programa chamador'] != p:
            nid = 'a-' + c['Programa chamador']
            if not any(n['id'] == nid for n in nos):
                nos.append({'id': nid, 'col': 0, 'label': c['Programa chamador'], 'sub': classes.get(c['Programa chamador'], ''), 'detail': f'{c["Programa chamador"]} chama {p} por {c["Mecanismo"]} (linha {c["Linha"]})',
                            'cor': COR_CLASSE.get(classes.get(c['Programa chamador'], ''), rs.NEUTRA)})
                arestas.append({'from': nid, 'to': 'p'})
    ex_q = ex_q or {}
    vivas = {curto(c['Tabela']) for c in cmds if c.get('Executado') == 'sim'} | {curto(t) for q, _qu, _sq, tt in dinq if ex_q.get(q, True) for t in tt}   # tabela só de comandos não executados fica tracejada
    for c in cmds:
        nid = 'q-' + c['Código (link fase 4)']
        nos.append({'id': nid, 'col': 2, 'label': f'{c["Código (link fase 4)"]} {c["Operação"]} {curto(c["Tabela"])}', 'sub': f'linhas {c["Linhas"]}' + (f' · cursor {c["Cursor"]}' if c['Cursor'] else ''),
                    'detail': c['Código (link fase 4)'] + ': ' + c['sql'], 'cor': cor_sql(c['Operação']), 'inactive': c.get('Executado') != 'sim'})
        arestas.append({'from': 'p', 'to': nid})
        tid = 't-' + curto(c['Tabela'])
        if tid not in tab:
            tab[tid] = True
            nos.append({'id': tid, 'col': 3, 'label': curto(c['Tabela']), 'sub': 'tabela', 'detail': c['Tabela'], 'cor': rs.NEUTRA, 'inactive': curto(c['Tabela']) not in vivas})
        arestas.append({'from': nid, 'to': tid})
    for q, quando, sql, tabelas in dinq:   # comandos estáticos que substituem consulta dinâmica, executados por este programa (serviço)
        nid = 'q-' + q
        nos.append({'id': nid, 'col': 2, 'label': f'{q} ◇ {sql.split()[0].upper()} {", ".join(curto(t) for t in tabelas)}', 'sub': 'dinâmico internalizado · ' + quando, 'detail': q + ': ' + sql, 'cor': cor_sql(sql), 'inactive': not ex_q.get(q, True)})
        arestas.append({'from': 'p', 'to': nid})
        for t in tabelas:
            tid = 't-' + curto(t)
            if tid not in tab:
                tab[tid] = True
                nos.append({'id': tid, 'col': 3, 'label': curto(t), 'sub': 'tabela descoberta', 'detail': t, 'cor': rs.NEUTRA, 'inactive': curto(t) not in vivas})
            arestas.append({'from': nid, 'to': tid})
    return rs._grafo(f'Programa {p}: quem o chama, comandos SQL que executa e tabelas envolvidas', ['Chamado por', 'Programa', 'Comando SQL que executa', 'Tabela'], nos, arestas,
                     'Borda do programa = classe (azul coordenador, verde funcional, laranja corporativo, vermelho infraestrutura). Comando SQL: azul-petróleo lê, roxo grava; ◇ Qnn = comando estático que substitui consulta dinâmica. Cinza tracejado: nenhum cenário executou.', nw=240)


def _codigos(t):
    return [x.strip() for x in str(t or '').split(',') if x.strip()]


def _grafo_encadeamento(p, cmds, por_id):
    """Relação de dados entre os comandos SQL de um programa (e os comandos de outros programas ligados a eles): quem entrega dado a quem, em níveis."""
    nos, arestas, nivel = {}, [], {}
    for c in cmds:
        for cod in _codigos(c['Recebe dado de']):
            arestas.append((cod, c['Código (link fase 4)']))
        for cod in _codigos(c['Entrega dado a']):
            arestas.append((c['Código (link fase 4)'], cod))
    arestas = sorted(set(arestas))
    if not arestas:
        return None
    ids = sorted({x for a in arestas for x in a})
    for i in ids:
        nivel[i] = 0
    for _ in range(len(ids)):
        for a, b in arestas:
            if nivel[b] < nivel[a] + 1 and nivel[a] + 1 < len(ids):
                nivel[b] = nivel[a] + 1
    out_nos = []
    for i in ids:
        c = por_id.get(i)
        out_nos.append({'id': i, 'col': nivel[i], 'label': f'{i} {c["Operação"]} {curto(c["Tabela"])}' if c else i, 'sub': (f'{c["programa"]}@{c["Linhas"]}' if c else 'comando fora da análise'),
                        'detail': (i + ': ' + c['sql']) if c else i, 'cor': cor_sql(c['Operação']) if c else rs.NEUTRA, 'inactive': bool(c) and c.get('Executado') != 'sim'})
    cols = [f'Nível {n + 1}' + (' (sem dado de outro comando)' if n == 0 else '') for n in range(max(nivel.values()) + 1)]
    return rs._grafo(f'Relação de dados entre os comandos SQL de {p}', cols, out_nos, [{'from': a, 'to': b} for a, b in arestas],
                     'Cada seta é um dado que um comando SQL entrega a outro (a coluna lida de um vira condição ou valor do outro). Nível 1: comandos que não recebem dado de nenhum outro. Cinza tracejado: nenhum cenário executou.', nw=230), arestas


def _grafo_fluxo(titulo, cmds):
    """Origem dos dados dos comandos SQL de um programa (ou de um só comando), como no lineage-summary (fase 4b): origem mais distante -> trecho do SQL (WHERE ou campo como parâmetro)
    -> comando -> coluna lida -> fim do caminho. Origens e destinos iguais são compartilhados entre os comandos."""
    nos, arestas = [], []
    orig, dest, uso = {}, {}, defaultdict(list)
    for n_, c in enumerate(cmds):
        cid = f'c{n_}'
        ok = c.get('Executado') == 'sim'
        nos.append({'id': cid, 'col': 3, 'label': f'{c["Código (link fase 4)"]} {c["Operação"]} {curto(c["Tabela"])}', 'sub': f'{c["programa"]}@{c["Linhas"]}' + (f' · cursor {c["Cursor"]}' if c['Cursor'] else ''),
                    'sub2': '' if ok else 'NÃO EXECUTADO', 'detail': c['Código (link fase 4)'] + ': ' + c['sql'], 'cor': cor_sql(c['Operação']), 'inactive': not ok})
        trechos = {}
        for r in c['cond'] + c['par']:
            grupo = 'where' if r in c['cond'] else 'campos'
            chave = (grupo, r['Trecho do SQL'])
            if chave not in trechos:
                pid = f'{cid}i{len(trechos)}'
                trechos[chave] = pid
                nos.append({'id': pid, 'col': 2, 'label': rs._cut(r['Trecho do SQL'], 38), 'sub': 'WHERE' if grupo == 'where' else 'VALUES / SET', 'detail': f'{r["Parte do comando"]}: {r["Trecho do SQL"]} ({r["Papel"]})',
                            'cor': rs.COR_WHERE if grupo == 'where' else rs.COR_CAMPOS, 'inactive': not ok})
                arestas.append({'from': pid, 'to': cid})
            ko = (r['Origem mais distante'], r['Tipo da origem'], r.get('Condição que escolhe esta origem', ''))
            if ko not in orig:
                orig[ko] = f'o{len(orig)}'
                nos.append({'id': orig[ko], 'col': 1, 'label': rs._cut(r['Origem mais distante'] or '(origem não rastreada)', 44), 'sub': r['Tipo da origem'], 'sub2': ('quando: ' + rs._cut(ko[2], 40)) if ko[2] else '',
                            'detail': r['Origem mais distante'] + (f' | percurso: {r["Percurso entre programas"]}' if r.get('Percurso entre programas') else ''), 'cor': rs.COR.get(r['Tipo da origem'], rs.NEUTRA)})
            uso[orig[ko]].append(ok)
            if {'from': orig[ko], 'to': trechos[chave]} not in arestas:
                arestas.append({'from': orig[ko], 'to': trechos[chave]})
        for k, r in enumerate(c['said']):
            sid = f'{cid}s{k}'
            nos.append({'id': sid, 'col': 4, 'label': r['Coluna lida'], 'sub': 'recebe ' + rs._cut(r['Campo que recebe'], 22), 'detail': f'coluna {r["Coluna lida"]} recebida em {r["Campo que recebe"]} ({r["Uso no código"]})', 'cor': rs.NEUTRA, 'inactive': not ok})
            arestas.append({'from': cid, 'to': sid})
            kd = (r['Destino'], r['Tipo do fim'], r['Até onde o dado vai'])
            if kd not in dest:
                dest[kd] = f'd{len(dest)}'
                nos.append({'id': dest[kd], 'col': 5, 'label': rs._cut(r['Destino'] or r['Tipo do fim'], 34), 'sub': r['Tipo do fim'], 'detail': r['Até onde o dado vai'], 'cor': rs.COR.get(r['Tipo do fim'], rs.NEUTRA)})
            uso[dest[kd]].append(ok)
            if {'from': sid, 'to': dest[kd]} not in arestas:
                arestas.append({'from': sid, 'to': dest[kd]})
    ids = {c['Código (link fase 4)'] for c in cmds}
    for n_, c in enumerate(cmds):   # relação de dados entre comandos SQL: quem entrega dado a este comando e a quem ele entrega
        for k, lado in (('Recebe dado de', 0), ('Entrega dado a', 6)):
            for cod in _codigos(c[k]):
                nid = f'r{lado}-{cod}'
                if not any(n['id'] == nid for n in nos):
                    nos.append({'id': nid, 'col': lado, 'label': cod, 'sub': 'entrega dado a este comando' if lado == 0 else 'recebe dado deste comando', 'detail': f'{cod}: relação de dados com {c["Código (link fase 4)"]} (fase 4b)',
                                'cor': rs.NEUTRA})
                aresta = {'from': nid, 'to': f'c{n_}'} if lado == 0 else {'from': f'c{n_}', 'to': nid}
                if aresta not in arestas:
                    arestas.append(aresta)
    for n in nos:
        if n['id'] in uso:
            n['inactive'] = not any(uso[n['id']])
    return rs._grafo(titulo, ['Comando SQL que fornece o dado', 'Origem do dado (mais distante)', 'Parte do SQL a que se refere', 'Comando SQL', 'Coluna lida', 'Fim do caminho', 'Comando SQL que recebe o dado'], nos, arestas,
                     'Comandos SQL que entregam dado a este comando à esquerda e os que recebem dado dele à direita (relação de dados entre comandos, fase 4b). Entradas (origem mais distante ligada ao trecho do SQL que ela alimenta: marrom = WHERE, cinza-azulado = campo como parâmetro VALUES/SET); saídas à direita. '
                     'Cinza tracejado: nenhum cenário executou. O texto completo está no tooltip de cada nó e nas tabelas.', nw=250, ordem={2: 'fixa', 3: 'fixa', 4: 'fixa', 1: 'prox', 5: 'ant', 0: 'fixa', 6: 'fixa'})


def _grafo_dinamico(x, cod, quando, sql, classes, irmaos, chamadas=(), ok=True, ok_irmaos=None):
    """Mesmas considerações dos comandos estáticos, para o comando Qnn que substitui uma consulta dinâmica: quem informa o nome da tabela e os parâmetros (origem do dado) -> trecho do SQL
    (tabela fixada, WHERE) -> comando executado pelo serviço -> coluna lida -> programa que usa a coluna; e a relação com os outros comandos da mesma consulta."""
    it = x.get('internalizacao') or {}
    cor_prog = lambda p: COR_CLASSE.get(classes.get(p, ''), rs.NEUTRA)
    nos = [{'id': 'c', 'col': 2, 'label': f'{cod} ◇ {sql.split()[0].upper()} {", ".join(curto(t["nome"]) for t in x["tabelas"])}', 'sub': f'executado por {x["servico"]} · {quando}', 'sub2': '' if ok else 'NÃO EXECUTADO', 'detail': cod + ': ' + sql, 'cor': cor_sql(sql)}]
    arestas = []
    for t in x['tabelas']:   # origem do nome da tabela
        for pg in t['passado_por']:
            nid = 'pg-' + pg
            if not any(n['id'] == nid for n in nos):
                nos.append({'id': nid, 'col': 0, 'label': pg, 'sub': f'informa {x["parametro"]} = "{curto(t["nome"])}"', 'detail': t['cita'], 'cor': cor_prog(pg)})
            arestas.append({'from': nid, 'to': 'tab'})
    nos.append({'id': 'tab', 'col': 1, 'label': ', '.join(curto(t['nome']) for t in x['tabelas']), 'sub': 'tabela fixada (FROM)', 'detail': ', '.join(t['nome'] for t in x['tabelas']), 'cor': rs.NEUTRA, 'inactive': not ok})
    arestas.append({'from': 'tab', 'to': 'c'})
    for k, w in enumerate(it.get('condicoes_where') or []):
        if (w.get('para') or 'comando principal') not in irmaos['quandos'] + ['todos']:
            continue
        nid = f'w{k}'
        nos.append({'id': nid, 'col': 1, 'label': rs._cut(f'{w["coluna"]} {w["operador"]} {w["parametro"]}', 40), 'sub': 'WHERE', 'detail': w['cita'], 'cor': rs.COR_WHERE})
        arestas.append({'from': nid, 'to': 'c'})
        for u in x.get('usos') or []:   # o chamador que informa o parâmetro
            if w['coluna'].upper() in (u['cita'] + ' ' + u['tipo_consulta']).upper() or len(x['usos']) == 1:
                oid = 'u-' + u['chamador']
                if not any(n['id'] == oid for n in nos):
                    nos.append({'id': oid, 'col': 0, 'label': u['chamador'], 'sub': 'chamador: ' + rs._cut(u['tipo_consulta'], 36), 'detail': u['cita'], 'cor': cor_prog(u['chamador'])})
                arestas.append({'from': oid, 'to': nid})
    for k, c in enumerate(it.get('colunas_select') or []):
        sid = f's{k}'
        nos.append({'id': sid, 'col': 3, 'label': c['coluna'], 'sub': 'posição ' + rs._cut(c['posicao'], 24), 'detail': c['cita'], 'cor': rs.NEUTRA})
        arestas.append({'from': 'c', 'to': sid})
        for pg in c.get('usada_em') or []:
            did = 'd-' + pg
            if not any(n['id'] == did for n in nos):
                nos.append({'id': did, 'col': 4, 'label': pg, 'sub': 'usa a coluna · ' + classes.get(pg, ''), 'detail': c['cita'], 'cor': cor_prog(pg)})
            arestas.append({'from': sid, 'to': did})
    for o in irmaos['outros']:   # relação com os demais comandos da mesma consulta dinâmica
        nos.append({'id': 'o-' + o[0], 'col': 5, 'label': f'{o[0]} ◇', 'sub': 'mesma consulta: ' + rs._cut(o[1], 30), 'detail': o[0] + ': ' + o[2], 'cor': cor_sql(o[2]), 'inactive': not (ok_irmaos or {}).get(o[0], True)})
        arestas.append({'from': 'c', 'to': 'o-' + o[0]})
    for n in nos:
        if not n['id'].startswith('o-'):
            n['inactive'] = not ok
    return rs._grafo(f'Origem dos dados de {cod} (consulta dinâmica {x["id"]} internalizada)', ['Origem do dado (quem informa)', 'Parte do SQL', 'Comando SQL (programa que executa)', 'Coluna lida', 'Fim do caminho (programa que usa)', 'Outro comando da mesma consulta'], nos, arestas,
                     'Mesmo modelo do resumo de linhagem: de onde vem o dado (quem informa o nome da tabela e os parâmetros) → parte do SQL (tabela fixada, WHERE: marrom) → comando (o programa que o executa está no nó; azul-petróleo lê, roxo grava; ◇ = substitui consulta dinâmica) → coluna lida → programa que a usa. '
                     'Só aparece outro comando da mesma consulta quando existe. Quem chama o programa que executa está na tabela "onde e quando executa". Cinza tracejado: nenhum cenário executou o comando (a caixa do mapa de decisão que o executa não foi alcançada). O texto completo está no tooltip de cada nó e na tabela abaixo.', nw=240)


def _tabela_dinamico(x, cod, quando, sql, irmaos):
    it = x.get('internalizacao') or {}
    rows = [('nome da tabela', t['nome'], pg, f'{x["parametro"]} = "{curto(t["nome"])}"', t['cita']) for t in x['tabelas'] for pg in t['passado_por']]
    rows += [('WHERE', w['coluna'], ', '.join(u['chamador'] for u in x.get('usos') or []), f'{w["operador"]} {w["parametro"]}', w['cita']) for w in it.get('condicoes_where') or [] if (w.get('para') or 'comando principal') in irmaos['quandos'] + ['todos']]
    rows += [('coluna lida', c['coluna'], ', '.join(c.get('usada_em') or []), c['posicao'], c['cita']) for c in it.get('colunas_select') or []]
    rows += [('outro comando da mesma consulta', o[0], x['servico'], o[1], o[2]) for o in irmaos['outros']]
    return rm.T(f'{cod}: origem dos dados (tabela do diagrama)', ['Elemento', 'Nome', 'Programa de origem ou de uso', 'Parâmetro ou posição', 'Evidência'], rows)


def _grafo_geral(porprog, classes, dinq, ex_q):
    """Visão de todos os programas: programa -> comando SQL (estático e dinâmico internalizado, `<programa>-Qnn`) -> tabela. Só entram os comandos que a execução dinâmica alcançou."""
    nos, arestas, tab, n_cmd = [], [], {}, 0
    progs = {}
    for p in sorted(set(porprog) | set(dinq)):
        cmds = [(c['Código (link fase 4)'], f'{c["Operação"]} {curto(c["Tabela"])}', c['Operação'], [curto(c['Tabela'])], c['sql'], False) for c in porprog.get(p, []) if c.get('Executado') == 'sim']
        cmds += [(q, f'◇ {sql.split()[0].upper()} {", ".join(curto(t) for t in tt)}', sql, [curto(t) for t in tt], sql, True) for q, quando, sql, tt in dinq.get(p, []) if ex_q.get(q)]
        if cmds:
            progs[p] = cmds
    for p, cmds in progs.items():
        nos.append({'id': 'p-' + p, 'col': 0, 'label': p, 'sub': classes.get(p, ''), 'detail': f'programa {p} ({classes.get(p, "")}): {len(cmds)} comando(s) SQL executados pela análise dinâmica', 'cor': COR_CLASSE.get(classes.get(p, ''), rs.NEUTRA)})
        for cod, rot, op, tabs, sql, din in cmds:
            n_cmd += 1
            cid = 'c-' + cod
            nos.append({'id': cid, 'col': 1, 'label': cod, 'sub': rot + (' · dinâmico internalizado' if din else ''), 'detail': cod + ': ' + sql, 'cor': cor_sql(op if not din else sql)})
            arestas.append({'from': 'p-' + p, 'to': cid})
            for t in tabs:
                tid = 't-' + t
                if tid not in tab:
                    tab[tid] = True
                    nos.append({'id': tid, 'col': 2, 'label': t, 'sub': 'tabela', 'detail': t, 'cor': rs.NEUTRA})
                arestas.append({'from': cid, 'to': tid})
    return rs._grafo('Programas, comandos SQL e tabelas: quem lê e quem grava cada tabela', ['Programa', 'Comando SQL (azul-petróleo lê, roxo grava; ◇ = dinâmico internalizado)', 'Tabela'], nos, arestas,
                     f'Só os comandos SQL (estáticos e dinâmicos internalizados) e as tabelas que a execução dinâmica alcançou: {n_cmd} comando(s) em {len(progs)} programa(s). Cada programa liga aos seus comandos e cada comando à tabela que lê ou grava; o detalhe está na seção do programa.', nw=230)


def modelo(d, ev, interp, falhas, classes):
    L = rm.link
    cmds = ev['cmds']
    cmd_de, q_lista = interp['_cmd_de'], interp['_q_lista']
    dins = interp['_dins']
    est = {x['codigo']: x for x in interp['comandos_estaticos']}
    porprog = defaultdict(list)   # por programa: os comandos dele, já com o código e o SQL da query única a que pertencem
    for c in cmds:
        for pg in c['programas']:
            mb = [m_ for m_ in c['membros'] if m_['programa'] == pg]
            v = dict(mb[0])
            v['Código (link fase 4)'], v['sql'] = c['Código (link fase 4)'], c['sql']
            v['Linhas'] = ', '.join(str(n_) for n_ in sorted({n_ for m_ in mb for n_ in m_['linhas']}))
            v['Cursor'] = next((m_['Cursor'] for m_ in mb if m_['Cursor']), '')
            v['Executado'] = 'sim' if any(m_.get('Executado') == 'sim' for m_ in mb) else mb[0].get('Executado', '')
            porprog[pg].append(v)
    for pg in porprog:
        porprog[pg].sort(key=lambda x: x['Código (link fase 4)'])
    unif = [c for c in cmds if c['equivalentes']]
    ex_q = {c_: any(caixa_executada(d, caixas_do_caso(x_.get('internalizacao') or {}).get(q_)) for q_ in q_lista[c_]) for x_ in dins.values() for c_, _q, _s in cmd_de[x_['id']]}
    dinq = defaultdict(list)   # programa serviço -> [(Qnn, quando, sql, tabelas)]
    for x in dins.values():
        for q, quando, sql in cmd_de[x['id']]:
            dinq[x['servico']].append((q, quando, sql, [t['nome'] for t in x['tabelas']]))
    programas = sorted(set(porprog) | set(dinq))
    tabelas = sorted({curto(c['Tabela']) for c in cmds} | {curto(t['nome']) for x in dins.values() for t in x['tabelas']})
    secoes = []
    resumo_prog = []
    for p in programas:
        cs = porprog.get(p, [])
        resumo_prog.append((rm.with_links('', [L(p, FASE, 'prog-' + p)]), classes.get(p, 'não classificado'), len(cs), sum(1 for c in cs if cor_sql(c['Operação']) != rs.COR_LEITURA),
                            sum(1 for c in cs if c.get('Executado') == 'sim'), ', '.join(sorted({curto(c['Tabela']) for c in cs})) or '—', ', '.join(q for q, *_ in dinq.get(p, [])) or '—'))
    secoes.append(rm.S('cobertura', 'Cobertura', [
        rm.X(f'{ev["n_orig"]} comandos SQL estáticos (agrupados por programa, tabela e cursor) em {len(porprog)} programas, {len(ev["lin"])} linhas de comando na compilação, {len(tabelas)} tabelas. '
             f'Os comandos de leitura com o mesmo FROM e o mesmo WHERE, mesmo lendo colunas diferentes ou em programas diferentes, são uma query única: {sum(len(c["equivalentes"]) + 1 for c in unif)} comandos viraram {len(unif)} queries, e o total é de {len(cmds)} queries. '
             f'Consultas dinâmicas descobertas: {len(dins)} ({sum(len(x["tabelas"]) for x in dins.values())} tabela(s) passada(s) por parâmetro), internalizadas em {sum(len(v) for v in cmd_de.values())} comando(s) estático(s) Qnn. '
             f'Afirmações sem evidência: {len(falhas)}. Cada comando é explicado: propósito, cada coluna, cada condição do WHERE e o tratamento do retorno.'),
        rm.T('Comandos SQL por programa', ['Programa', 'Classe', 'Comandos estáticos', 'Que gravam', 'Executados pela análise dinâmica', 'Tabelas', 'Dinâmicos internalizados (Qnn)'], resumo_prog)]))
    secoes.append(rm.S('unificacao', 'Queries equivalentes unificadas', [
        rm.X('Comandos de leitura (SELECT) com o mesmo FROM e o mesmo WHERE são a mesma consulta ao banco; o que muda é a lista de colunas lidas (ou o programa que a executa). A query única leva o código do comando de menor código '
             'e devolve a união das colunas; cada programa continua recebendo as colunas nos próprios campos. Comandos que gravam e comandos com FROM ou WHERE diferentes não são unificados.'),
        rm.T('Queries equivalentes unificadas', ['Query única', 'Comandos unificados', 'Programas', 'Tabelas', 'FROM e WHERE equivalentes', 'Colunas lidas (união)'],
             [(rm.with_links('', [L(c['Código (link fase 4)'], FASE, c['Código (link fase 4)'])]), ', '.join([c['Código (link fase 4)']] + c['equivalentes']), ', '.join(c['programas']), curto(c['Tabela']),
               c['_p'][1], ', '.join(colunas_lidas(c))) for c in unif])] if unif else [rm.X('Nenhuma query de leitura tem FROM e WHERE equivalentes a outra.')],
        'Cada linha é uma query única que reúne comandos SELECT equivalentes no FROM e no WHERE; o detalhe de cada comando original está na seção da query única.'))
    g = _grafo_geral(porprog, classes, dinq, ex_q)
    tl = [(p, curto(c['Tabela']), c['Código (link fase 4)'], c['Operação']) for p in sorted(porprog) for c in porprog[p]]
    secoes.append(rm.S('visao-geral', 'Programas, comandos SQL e tabelas', [g, rm.T('Tabela do diagrama: comando SQL de cada programa sobre cada tabela', ['Programa', 'Tabela', 'Comando', 'Operação'], tl)],
                       'Programa que executa o comando SQL e as tabelas envolvidas, para todos os programas com comando SQL.'))
    cols = ['Id (fase 4)', 'Comando', 'Programa', 'Linha', 'Parágrafo', 'Operação', 'Cursor', 'Tabela', 'SQL', 'Entry points', 'Execução dinâmica']
    secoes.append(rm.S('compilacao-sql', 'Compilação dos comandos SQL de todos os programas', [
        rm.T('Comandos SQL por programa', ['Programa', 'Comandos', 'Tabelas'], [(p, len(v), ', '.join(sorted({curto(c['Tabela']) for c in v}))) for p, v in sorted(porprog.items())]),
        rm.T('Todos os comandos SQL (SELECT, INSERT, UPDATE, DELETE e comandos de cursor), por programa e linha', cols,
             [(r['Id'], rm.with_links('', [L(r['codigo'], FASE, r['codigo'])]) if r['codigo'] else '—', r['Programa'], r['Linha'], r['Parágrafo'], r['Comando'], r['Cursor'], r['tabela'], r['SQL'], r['Entry points'], r.get('Execução dinâmica', '')) for r in ev['lin']])],
        f'{len(ev["lin"])} linha(s) de comando SQL em {len(porprog)} programa(s), compiladas das tabelas "Comandos SQL sobre ..." da fase 4 (04-data-lineage); a coluna Comando é o código do comando agrupado (programa, tabela e cursor) explicado abaixo.'))
    for p in programas:
        cs = porprog.get(p, [])
        chamadas = [c for c in d['chamadas']]
        b = [_grafo_programa(p, cs, dinq.get(p, []), chamadas, classes, ex_q)]
        enc = _grafo_encadeamento(p, cs, ev['por_id'])
        if enc:
            b += [enc[0], rm.T(f'Relação de dados entre os comandos SQL de {p}: tabela', ['Comando que entrega o dado', 'Comando que recebe o dado'], enc[1])]
        rel = [('chamado por', c['Programa chamador'], classes.get(c['Programa chamador'], ''), c['Linha'], c['Mecanismo']) for c in chamadas if c['Programa chamado'] == p and c['Programa chamador'] != p]
        rel += [('executa comando SQL', c['Código (link fase 4)'], 'grava' if cor_sql(c['Operação']) != rs.COR_LEITURA else 'lê', c['Linhas'], f'{c["Operação"]} {c["Tabela"]}') for c in cs]
        rel += [('executa comando SQL (dinâmico internalizado)', q, 'lê' if cor_sql(sql) == rs.COR_LEITURA else 'grava', '—', f'{quando}: {", ".join(tt)}') for q, quando, sql, tt in dinq.get(p, [])]
        b.append(rm.T(f'Programa {p}: chamadas e comandos SQL', ['Relação', 'Programa ou comando', 'Classe ou natureza', 'Linha', 'Detalhe'], rel))
        secoes.append(rm.S('prog-' + p, f'Programa {p}', b, f'{classes.get(p, "não classificado")} · {len(cs)} comando(s) SQL estático(s)' + (f' · {len(dinq[p])} comando(s) Qnn' if dinq.get(p) else '')))
    for c in cmds:
        cod = c['Código (link fase 4)']
        x = est.get(cod, {})
        b = [rm.SQL(c['sql'] or '(texto SQL não localizado na fase 4)', title=f'{cod}: comando SQL'),
             rm.X(f'Propósito: {x.get("proposito", "—")}'), rm.X(f'Tratamento do retorno: {x.get("retorno", "—")}'), rm.X(f'Confiança: {x.get("confianca", "—")}'),
             rm.T(f'{cod}: onde e quando executa', ['Comando original', 'Programa', 'Operação', 'Tabela', 'Linhas', 'Parágrafo', 'Cursor', 'Natureza', 'Executa quando (condições de negócio)', 'Só executa conforme o status de', 'Recebe dado de', 'Entrega dado a', 'Entry points', 'Executado'],
                  [(m_['Código (link fase 4)'], rm.with_links('', [L(m_['programa'], FASE, 'prog-' + m_['programa'])]), m_['Operação'], m_['Tabela'], m_['Linhas'], m_['Parágrafo'], m_['Cursor'], m_['Natureza'], m_['Executa quando (condições de negócio)'],
                    m_['Só executa conforme o status de'], m_['Recebe dado de'], m_['Entrega dado a'], m_['Entry points'], m_['Executado']) for m_ in c['membros']])]
        if c['equivalentes']:
            b.insert(1, rm.X('Query única: reúne ' + ', '.join([cod] + c['equivalentes']) + ' (mesmo FROM e mesmo WHERE). ' + ' '.join(c['obs'])))
            b.insert(2, rm.T(f'{cod}: comandos unificados', ['Comando original', 'Programa', 'Linhas', 'Cursor', 'Colunas lidas', 'SQL original'],
                             [(m_['Código (link fase 4)'], m_['programa'], m_['Linhas'], m_['Cursor'], ', '.join(colunas_lidas(m_)), m_['sql']) for m_ in c['membros']]))
        if c['cond'] or c['par'] or c['said']:
            b.append(_grafo_fluxo(f'Origem dos dados de {cod}', [c]))
        esp_cols = {r['coluna'].upper(): r for r in x.get('colunas', [])}
        lidas, gravadas = colunas_lidas(c), colunas_gravadas(c['sql'])
        dest = defaultdict(list)
        for r in c['said']:
            dest[r['Coluna lida']].append(f'{r["Campo que recebe"]} ({r["Uso no código"]}) → {r["Destino"]}: {r["Até onde o dado vai"]}')
        linhas = [('lê', k, '; '.join(dest[k][:3]) + (f' (+{len(dest[k]) - 3})' if len(dest[k]) > 3 else '')) for k in lidas] + [('grava', k, '') for k in gravadas]
        b.append(rm.T(f'{cod}: colunas explicadas', ['Papel', 'Coluna', 'Destino do dado (fase 4b)', 'Significado (IA)', 'Evidência'],
                      [(papel, col, dst, esp_cols.get(col.upper(), {}).get('significado', '—'), esp_cols.get(col.upper(), {}).get('cita', '')) for papel, col, dst in linhas]))
        wh = {w['coluna'].upper(): w for w in x.get('condicoes', [])}
        b.append(rm.T(f'{cod}: condições do WHERE explicadas', ['Trecho do SQL', 'Papel do predicado (fase 4b)', 'Origem mais distante', 'Tipo da origem', 'Percurso entre programas', 'Significado (IA)', 'Evidência'],
                      [(r['Trecho do SQL'], r['Papel'], r['Origem mais distante'], r['Tipo da origem'], r['Percurso entre programas'], next((w['significado'] for k, w in wh.items() if k in r['Trecho do SQL'].upper()), '—'),
                        next((w['cita'] for k, w in wh.items() if k in r['Trecho do SQL'].upper()), '')) for r in c['cond']]))
        if c['par']:
            b.append(rm.T(f'{cod}: campos como parâmetro (VALUES e SET)', ['Trecho do SQL', 'Papel', 'Origem mais distante', 'Tipo da origem', 'Percurso entre programas'], [(r['Trecho do SQL'], r['Papel'], r['Origem mais distante'], r['Tipo da origem'], r['Percurso entre programas']) for r in c['par']]))
        if x.get('lacunas'):
            b.append(rm.X(' | '.join(x['lacunas']), title=f'{cod}: lacunas'))
        secoes.append(rm.S(cod, f'{cod} · {c["Operação"]} {curto(c["Tabela"])}' + (' · query única' if c['equivalentes'] else ''), b))
    bl = []
    if dins:
        lin = []
        for x in dins.values():
            it = x.get('internalizacao') or {}
            for t in x['tabelas']:
                mapeada = any(curto(k) == curto(t['nome']) for k in d['dyn_tab'])
                lin.append([x['id'], t['nome'], 'sim' if mapeada else 'não: fora do mapeamento DB2 analisado', x['parametro'], x['servico'], ', '.join(t['passado_por']), ', '.join(x['usada_por']), t['cita'],
                            it.get('proposito', '') + ' · ' + it.get('comando_fixo', '')])
        bl.append(rm.T('Tabelas passadas por parâmetro', ['Consulta', 'Tabela descoberta', 'No mapeamento DB2 das fases 1 e 3', 'Campo de parâmetro', 'Serviço que executa a consulta', 'Programas que passam o nome', 'Entry points', 'Evidência (comando)', 'Como fica na modernização (consulta fixada)'], lin))
    else:
        bl.append(rm.X('Nenhuma consulta dinâmica foi descoberta.'))
    secoes.append(rm.S('dinamicas', 'Consultas dinâmicas: tabelas passadas por parâmetro', bl,
                       'A análise determinística só vê tabelas citadas em comandos SQL. Aqui estão as tabelas que um serviço genérico lê porque o chamador informa o nome num campo de parâmetro; conferidas nos comandos da fase 5 e nas constantes do chamador da fase 7. '
                       'Na modernização a consulta dinâmica não é preservada: vira comando estático com a tabela fixada no programa (código Qnn) e as regras que só validam ou roteiam o parâmetro são descartadas.'))
    for x in dins.values():
        it = x.get('internalizacao') or {}
        b = [rm.X(x['resumo']), rm.X(f'Confiança: {x["confianca"]}'), rm.X('Como o nome chega à consulta: ' + x['mecanismo']),
             rm.T(f'{x["id"]}: passos da descoberta', ['Passo', 'Texto'], [(i + 1, y) for i, y in enumerate(x['passos'])]),
             rm.T(f'{x["id"]}: evidência dos relatórios', ['Tabela', 'Programa que passa o nome', 'Comando que o repassa'], [(t['nome'], pg, t['cita']) for t in x['tabelas'] for pg in t['passado_por']]),
             rm.T(f'{x["id"]}: uso do serviço por chamador', ['Chamador', 'Tipo de consulta', 'Finalidade no chamador', 'Colunas lidas', 'Retorno tratado', 'Evidência'],
                  [(rm.with_links('', [L(u_['chamador'], '05-decision-map', 'prog-' + u_['chamador'])]), u_['tipo_consulta'], u_['finalidade'], u_['colunas_lidas'], u_['retorno_tratado'], u_['cita']) for u_ in (x.get('usos') or [])]),
             rm.T(f'{x["id"]}: comando SQL estático que substitui a execução dinâmica', ['Código', 'Quando', 'Comando SQL estático', 'Origem', 'Texto montado no código'],
                  [(rm.with_links('', [L(c_, FASE, c_)]), q_, s_, it.get('origem', ''), it.get('montagem', '') or '—') for c_, q_, s_ in cmd_de[x['id']]])]
        if x['lacunas']:
            b.append(rm.X(' | '.join(x['lacunas']), title=f'{x["id"]}: lacunas'))
        secoes.append(rm.S(x['id'], f'{x["id"]} · {x["titulo"]}', b))
    for x in dins.values():
        it = x.get('internalizacao') or {}
        for c_, q_, s_ in cmd_de[x['id']]:
            irm = {'quandos': q_lista[c_], 'outros': [(c2, q2, s2) for c2, q2, s2 in cmd_de[x['id']] if c2 != c_]}
            ex_ = {c2: any(caixa_executada(d, caixas_do_caso(it).get(q2_)) for q2_ in q_lista[c2]) for c2, _q2, _s2 in cmd_de[x['id']]}
            cx_txt = ', '.join(sorted({caixas_do_caso(it).get(q2_, '') for q2_ in q_lista[c_]}))
            qb = [rm.SQL(s_), rm.X(f'Quando: {q_}'), _grafo_dinamico(x, c_, q_, s_, classes, irm, d['chamadas'], ex_[c_], ex_), _tabela_dinamico(x, c_, q_, s_, irm),
                  rm.T(f'{c_}: onde e quando executa', ['Programa que executa', 'Classe', 'Operação', 'Tabela', 'Natureza', 'Executa quando', 'Chamado por', 'Entry points', 'Caixa do mapa de decisão (fase 5)', 'Executado pela análise dinâmica'],
                       [(rm.with_links('', [L(x['servico'], FASE, 'prog-' + x['servico'])]), classes.get(x['servico'], ''), s_.split()[0].upper(), ', '.join(t_['nome'] for t_ in x['tabelas']), 'lê' if cor_sql(s_) == rs.COR_LEITURA else 'grava', q_,
                         ', '.join(sorted({ch['Programa chamador'] for ch in d['chamadas'] if ch['Programa chamado'] == x['servico'] and ch['Programa chamador'] != x['servico']})) or '—', ', '.join(x['usada_por']), cx_txt, 'sim' if ex_[c_] else 'não')]),
                  rm.T(f'{c_}: origem do comando', ['Consulta dinâmica', 'Serviço que executa', 'Tabela fixada', 'Origem', 'Texto montado no código', 'Propósito'],
                       [(rm.with_links('', [L(x['id'], FASE, x['id'])]), rm.with_links('', [L(x['servico'], FASE, 'prog-' + x['servico'])]), ', '.join(curto(t_['nome']) for t_ in x['tabelas']), it.get('origem', ''), it.get('montagem', '') or '—', it.get('proposito', ''))]),
                  rm.T(f'{c_}: colunas e condições inferidas dos chamadores', ['Parte do SQL', 'Coluna', 'Posição na saída ou parâmetro', 'Operador', 'Quando', 'Evidência (comando do chamador)'],
                       [('SELECT', c2['coluna'], c2['posicao'], '—', 'sempre', c2['cita']) for c2 in (it.get('colunas_select') or [])]
                       + [('WHERE', w2['coluna'], w2['parametro'], w2['operador'], w2.get('para') or 'comando principal', w2['cita']) for w2 in (it.get('condicoes_where') or []) if (w2.get('para') or 'comando principal') in q_lista[c_] + ['todos']])]
            secoes.append(rm.S(c_, f'{c_} · {s_.split()[0].upper()} {", ".join(curto(t_["nome"]) for t_ in x["tabelas"])}', qb))
    cards = [rm.card('comandos SQL estáticos', ev['n_orig']), rm.card('queries (após unificar)', len(cmds)), rm.card('programas com SQL', len(porprog)), rm.card('tabelas', len(tabelas)), rm.card('consultas dinâmicas', len(dins)), rm.card('comandos Qnn', sum(len(v) for v in cmd_de.values()))]
    return rm.model('Mapeamento dos comandos SQL', 'Todos os comandos SQL do sistema, estáticos e dinâmicos: o programa que executa cada um, as tabelas envolvidas, o propósito, as colunas e as condições explicadas.', cards, secoes)


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
    interp = carregar_mapeamento(BASE)
    if interp is None:
        print('mapeamento: sem interpretacao-sql/mapeamento.json (prompt 5); a fase 10 não é gerada')
        return
    import gerar_fluxos as F
    d = F.coletar(ana)
    eps = F.por_entry(d)
    ev = coletar(ana)
    dobrar_interpretacao(interp, ev)
    erros, falhas = validar(d, eps, ev, interp, F.evidencia)
    if erros:
        raise SystemExit('interpretação inconsistente com os relatórios:\n  ' + '\n  '.join(erros))
    mod = modelo(d, ev, interp, falhas, d['classe'])
    S.escrever(saida, FASE, mod)
    print(f'{len(ev["cmds"])} comandos estáticos, {len(interp["consultas_dinamicas"])} consultas dinâmicas; afirmações sem evidência: {len(falhas)}')
    for x in falhas:
        print('  ' + x)
    sys.exit(1 if falhas else 0)


if __name__ == '__main__':
    main()
