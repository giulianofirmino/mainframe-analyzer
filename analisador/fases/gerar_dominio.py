#!/usr/bin/env python3
"""Relatório domain-model (fase 16): o modelo de domínio lógico (DDD) a partir do modelo físico (tabelas, colunas, vínculos), lido ÚNICA E EXCLUSIVAMENTE dos relatórios
gerados (<fase>/ia/report.json das fases 3 e 4: esquema de dados e linhagem de dados).

  python3 gerar_dominio.py <pasta-da-analise> [pasta-de-saida] [--interpretacao PASTA]   (padrão da saída: a pasta da análise)

Saída: <saida>/16 - domain-model/human/report.html e <saida>/16 - domain-model/ia/report.json (o mesmo modelo de visão das outras fases).
Evidência calculada pelo script (sem IA, mesma entrada → mesma saída):
  - tabelas e colunas (tipo, aceita nulo, de onde vem a coluna, quem lê, grava e filtra);
  - chaves candidatas: o DB2 do relatório não declara PK/FK, então a identidade é deduzida do que os programas fazem (colunas comparadas com `=` a um campo do programa
    nas cláusulas WHERE, em conjunto) e da primeira coluna do DCLGEN (indício fraco);
  - vínculos fortes entre tabelas: o valor gravado ou procurado numa coluna vem de uma coluna de outra tabela (origem `tabela: DB2PRD.X.COL` da linhagem);
  - vínculos fracos: colunas de mesmo nome em tabelas diferentes (colunas de auditoria, presentes em quase todas as tabelas, ficam separadas como transversais);
  - candidatas a tabela de junção (N:N), a parte de agregado (a chave da tabela contém o vínculo) e a raiz de agregado;
  - dicionário de prefixos e de abreviações dos nomes físicos, para a tradução em nomes de domínio.
A interpretação (interpretacao-dominio/*.json, prompt 7) dá o nome de domínio de cada classe e atributo, a identidade, os relacionamentos semânticos (1:1, 1:N, N:N), os
agregados com raiz e invariantes. O script confere que toda tabela e toda coluna foi traduzida, que os nomes seguem a convenção, que toda citação existe na evidência,
que todo vínculo forte virou relacionamento e que todo vínculo fraco foi aceito ou descartado com motivo. Não agrupa em Bounded Contexts (próxima fase)."""
import json
import os
import re
import unicodedata
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import gerar_simulacao as S
import report_model as rm  # noqa: E402
import report_resumo as rs  # noqa: E402

AQUI = Path(__file__).resolve().parent
BASE = Path(os.environ['ANALISE_INTERPRETACOES']) if os.environ.get('ANALISE_INTERPRETACOES') else AQUI   # pasta das interpretações (a análise); o pipeline a informa
FASE = '16 - domain-model'
TIPOS_LOGICOS = {'Codigo', 'Numero', 'Texto', 'Descricao', 'Data', 'Hora', 'DataHora', 'Valor', 'Quantidade', 'Percentual', 'Indicador', 'Identificador', 'Enumerado'}
BASES_INV = {'não nulo', 'identidade', 'valor fixo', 'vínculo', 'dedução'}
BASES_REL = {'vínculo forte', 'vínculo fraco', 'dedução'}
CARD = {'1:1', '1:N', 'N:N'}
CAT_NUCLEO, CAT_CORP = 'Business core', 'Corporativo'
NATUREZAS = {'núcleo', 'referência', 'apoio'}
# classificação da fase 3 (protagonista, coadjuvante, figurante) → natureza provável no domínio
NATUREZA_DE = {'protagonista': ('núcleo', 'o sistema altera a tabela (INSERT/UPDATE/DELETE): o dado é governado aqui; candidata a entidade do núcleo e a raiz ou membro de agregado'),
               'coadjuvante': ('referência', 'só consulta, mas vários programas ou entry points a leem: dado mantido fora, entidade de referência (somente leitura) que os agregados do núcleo apontam'),
               'figurante': ('apoio', 'só consulta e aparece pouco: dado de apoio pontual; candidata a objeto de valor, enumerado ou tabela de códigos')}
CONF = {'alta', 'média', 'media', 'baixa'}
CHAVES_RAIZ = {'entidades', 'relacionamentos', 'agregados', 'descartes', 'lacunas'}
RE_CLASSE = re.compile(r'^[A-Z][A-Za-z0-9]+$')
RE_ATRIB = re.compile(r'^[a-z][A-Za-z0-9]*$')
RE_PREFIXO_SQL = re.compile(r'^(n|d|v|vl|dt|i|c|h|r|q|t)[A-Z]')
RE_CODIGO = re.compile(r'(@[A-Z][A-Za-z]+\b|\b(public|private|protected)\s+(class|\w+\s+\w+\s*[;(])|\bclass\s+[A-Z]\w*|\bimport\s+[\w.]+;?|\b(extends|implements)\s+[A-Z]\w+|\bnew\s+[A-Z]\w*\()')


def curto(t):
    return str(t).split('.')[-1].strip()


def norm(t):
    return ' '.join(str(t).split())


def so_repete_nome(desc, nome):
    """True se a descrição só reaproveita as palavras do nome do atributo (descrição de modelo pronto: "Código de centro lucro sap")."""
    sem = lambda t: unicodedata.normalize('NFD', str(t)).encode('ascii', 'ignore').decode().lower()
    pal = lambda t: set(re.findall(r'[a-z0-9]+', sem(re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', str(t)))))
    stop = {'de', 'da', 'do', 'das', 'dos', 'a', 'o', 'e', 'em', 'um', 'uma', 'codigo', 'numero', 'valor', 'data', 'hora', 'indicador', 'quantidade', 'descricao', 'texto', 'identificador', 'tipo'}
    return not (pal(desc) - stop - pal(nome))


def tipo_familia(t):
    t = str(t).upper()
    for f in ('DECIMAL', 'INTEGER', 'SMALLINT', 'BIGINT', 'CHAR', 'VARCHAR', 'TIMESTAMP', 'DATE', 'TIME', 'FLOAT', 'DOUBLE'):
        if t.startswith(f):
            return 'CHAR' if f == 'VARCHAR' else 'INTEIRO' if f in ('INTEGER', 'SMALLINT', 'BIGINT') else f
    return 'INDETERMINADO'


# ----------------------------------------------------------------------------- evidência calculada
def coletar(ana):
    f3, f4 = S.fase(ana, '03-'), S.fase(ana, '04-')
    cols, ordem = defaultdict(list), {}
    for _s, bt, rows in S.tabelas(f3):
        if rows and 'Uso no SQL' in rows[0] and 'Origem da coluna' in rows[0]:
            for r in rows:
                t = curto(r['Tabela'])
                uso = r['Uso no SQL']
                m = re.match(r'(lê|filtra|grava)\s*:\s*(.*)', uso)
                cols[t].append({'nome': r['Coluna'], 'tipo': r['Tipo'], 'nulo': r['Aceita nulo'], 'origem': r['Origem da coluna'], 'cobol': r['Campo COBOL'], 'uso': uso,
                                'programas_uso': r['Programas que usam o campo'], 'situacao': r['Situação'], 'posicao': len(cols[t]) + 1})
    # as tabelas e colunas do diagrama ER (todas as tabelas do sistema) completam a tabela de colunas (que só traz as tabelas com colunas conhecidas)
    for sec in f3['sections']:
        for b in sec.get('blocks', []):
            if b.get('type') == 'graph' and b.get('kind') == 'er':
                for n in b['nodes']:
                    t = curto(n['label'])
                    have = {c['nome'] for c in cols.get(t, [])}
                    cols.setdefault(t, [])
                    for c in n.get('columns') or []:
                        if c['name'] not in have:
                            cols[t].append({'nome': c['name'], 'tipo': c.get('type', ''), 'nulo': '', 'origem': 'diagrama ER', 'cobol': '', 'uso': '', 'programas_uso': '', 'situacao': '', 'posicao': len(cols[t]) + 1})
    if not cols:
        raise SystemExit('fase 3: tabelas não encontradas')
    # só as tabelas atingidas pela execução dinâmica (fase 4: "Alcançada pela execução dinâmica")
    atingidas, todas = set(), set()
    for _s, bt, rows in S.tabelas(f4):
        if rows and 'Alcançada pela execução dinâmica' in rows[0] and 'Comandos que gravam' in rows[0]:
            for r in rows:
                todas.add(curto(r['Tabela']))
                if not r['Alcançada pela execução dinâmica'].upper().startswith('NÃO'):
                    atingidas.add(curto(r['Tabela']))
    ignoradas = sorted(todas - atingidas)
    cols = {t: c for t, c in cols.items() if t in atingidas}
    # tabelas dinâmicas descobertas no sql-mapping (fase 10): o nome da tabela passa por parâmetro a um serviço; as colunas vêm do que os chamadores leem e filtram
    classe = {}
    for _s, bt, rows in S.tabelas(S.fase(ana, '00-')):
        if bt == 'Programas':
            classe.update({r['Programa']: r['Classe'] for r in rows})
    dinamicas, dwhere = {}, []
    try:
        f10 = S.fase(ana, '10 ')
    except SystemExit:
        f10 = None
    if f10:
        for _s, bt, rows in S.tabelas(f10):
            if bt == 'Tabelas passadas por parâmetro':
                for r in rows:
                    t = curto(r['Tabela descoberta'])
                    dinamicas[t] = {'consulta': r['Consulta'], 'servico': r['Serviço que executa a consulta'], 'param': r['Campo de parâmetro'], 'no_db2': r['No mapeamento DB2 das fases 1 e 3'],
                                    'passam': [x.strip() for x in r['Programas que passam o nome'].split(',') if x.strip()], 'comandos': []}
        for st, bt, rows in S.tabelas(f10) if f10 else []:
            if bt.endswith(': colunas e condições inferidas dos chamadores'):
                t, cmd = curto(st.split()[-1]), bt.split(':')[0]
                if t not in dinamicas:
                    continue
                dinamicas[t]['comandos'].append(cmd)
                lista = cols.setdefault(t, [])
                for r in rows:
                    nome = r['Coluna']
                    c = next((x for x in lista if x['nome'] == nome), None)
                    if c is None:
                        c = {'nome': nome, 'tipo': 'indeterminado (inferido)', 'nulo': '', 'origem': 'deduzida do sql-mapping (consulta dinâmica)', 'cobol': r['Posição na saída ou parâmetro'], 'uso': '', 'programas_uso': '',
                             'situacao': 'usada', 'posicao': len(lista) + 1}
                        lista.append(c)
                    uso = f'{r["Parte do SQL"].lower()}: {cmd}' + (f' {r["Operador"]}' if r['Operador'] not in ('', '—') else '')
                    c['uso'] = (c['uso'] + '; ' if c['uso'] else '') + uso
                    if r['Parte do SQL'].upper().startswith('WHERE') and r['Operador'].strip() == '=':
                        dwhere.append({'tabela': t, 'coluna': nome, 'cmd': cmd, 'op': 'SELECT', 'operador': '=', 'valor': r['Posição na saída ou parâmetro'], 'papel': 'filtro por campo do programa', 'origem': '', 'criterio': f'{cmd}:{t}.{nome} = {r["Posição na saída ou parâmetro"]}'})
        for t, d in dinamicas.items():
            for st, bt, rows in S.tabelas(f10):
                if bt.endswith(': onde e quando executa') and st.split()[-1] == t and rows and rows[0].get('Classe'):
                    d['classe_servico'] = rows[0]['Classe']
            d['classe_servico'] = d.get('classe_servico') or classe.get(d['servico'], '')
    dinamicas = {t: d for t, d in dinamicas.items() if t in cols}
    dtxt = defaultdict(list)   # texto do sql-mapping sobre a tabela dinâmica (para conferir as citações da IA)
    for t, d in dinamicas.items():
        for st, bt, rows in S.tabelas(f10):
            if st.split()[-1] == t or st.startswith(d['consulta'] + ' ') or bt.startswith(d['consulta'] + ':'):
                dtxt[t] += [' '.join(str(v) for v in r.values()) for r in rows]
    chave1 = {t: (c[0]['nome'] if c else '') for t, c in cols.items()}
    papel, acesso = {}, {}
    for _s, bt, rows in S.tabelas(f3):
        if rows and 'Papel' in rows[0] and 'Tabela' in rows[0] and 'Por quê' in rows[0]:
            for r in rows:
                acesso[curto(r['Tabela'])] = [(m.group(1), m.group(2), m.group(3)) for m in re.finditer(r'([A-Z0-9#@$]+) \(([A-ZÇÃ]+), nível \d+: ([^)]*)\)', r.get('Programas (classe, nível, operações)', ''))]
                papel[curto(r['Tabela'])] = {'papel': r['Papel'], 'porque': r['Por quê'], 'gravacao': r['Comandos de gravação'], 'consulta': r['Comandos de consulta'], 'programas': r['Programas']}
    where, buscas, gravs = [], [], []
    for _s, bt, rows in S.tabelas(f4):
        if bt.startswith('Condições SQL (WHERE)'):
            for r in rows:
                cmd = r['Comando']
                tab = cmd.split(':')[-1]
                c = r['Coluna']
                if '.' in c:
                    tab = c.split('.')[0]
                where.append({'tabela': curto(tab), 'coluna': curto(c), 'cmd': cmd, 'op': r['Operação'], 'operador': r['Operador'], 'valor': r['Valor'], 'papel': r['Papel do predicado'],
                              'origem': r['Origem do valor'], 'criterio': r['Critério']})
        elif bt.startswith('Chaves de busca em '):
            tab = curto(bt[len('Chaves de busca em '):].split(':')[0])
            for r in rows:
                buscas.append({'tabela': tab, 'coluna': r['Campo da chave'].replace('-', '_'), 'campo': r['Campo da chave'], 'cmd': r['Comando'], 'op': r['Operação'], 'origem': r['Origem']})
        elif bt.startswith('Gravações em '):
            tab = curto(bt[len('Gravações em '):].split(':')[0])
            for r in rows:
                gravs.append({'tabela': tab, 'coluna': curto(r['Coluna']), 'cmd': r['Comando'], 'op': r['Operação'], 'valor': r['Valor gravado'], 'origem': r['Origem']})
    sqls = []
    for _s, bt, rows in S.tabelas(f4):
        if bt.startswith('Comandos SQL sobre '):
            sqls += [r['SQL'] for r in rows if r.get('SQL')]
    # evidência textual por tabela (para conferir as citações da IA)
    evid = defaultdict(list)
    for t, cs in cols.items():
        evid[t].append(t)
        evid[t] += [f'{c["nome"]} {c["tipo"]} {c["origem"]} {c["uso"]} {c["cobol"]}' for c in cs]
    for t, xs in dtxt.items():
        evid[t] += xs
    for q in sqls:
        for t in cols:
            if re.search(r'(?<![A-Z0-9_])' + t + r'(?![A-Z0-9_])', q):
                evid[t].append(q)
    for w in where:
        evid[w['tabela']].append(' '.join(str(v) for v in w.values()))
    for b in buscas + gravs:
        evid[b['tabela']].append(' '.join(str(v) for v in b.values()))
    where = where + dwhere
    where, buscas, gravs = [[x for x in l if x['tabela'] in cols] for l in (where, buscas, gravs)]
    papel = {t: v for t, v in papel.items() if t in cols}
    acesso = {t: v for t, v in acesso.items() if t in cols}
    for t, d in dinamicas.items():
        acesso[t] = [(d['servico'], d['classe_servico'], 'SELECT')]
    return {'dinamicas': dinamicas, 'acesso': acesso, 'ignoradas': ignoradas, 'cols': dict(cols), 'chave1': chave1, 'papel': papel, 'where': where, 'buscas': buscas, 'gravs': gravs, 'evid': {t: norm('\n'.join(v)) for t, v in evid.items()}}


ORIG = re.compile(r'tabela:\s*(?:[A-Z0-9_]+\.)?([A-Z0-9_#@$]+)\.([A-Z0-9_#@$]+)')


def deduzir(ev):
    cols = ev['cols']
    tabs = sorted(cols)
    nomes = {t: {c['nome'] for c in cs} for t, cs in cols.items()}
    # chaves candidatas: conjunto de colunas comparadas com `=` a campo do programa, por comando
    por_cmd = defaultdict(set)
    fixos = defaultdict(Counter)
    for w in ev['where']:
        if w['tabela'] not in cols or w['coluna'] not in nomes[w['tabela']]:
            continue
        if w['operador'].strip() == '=' and not w['papel'].startswith('filtro por valor fixo'):
            por_cmd[(w['tabela'], w['cmd'])].add(w['coluna'])
        elif w['operador'].strip() == '=':
            fixos[w['tabela']][(w['coluna'], w['valor'])] += 1
    conj = defaultdict(Counter)
    for (t, _c), cs in por_cmd.items():
        conj[t][tuple(sorted(cs))] += 1
    chave, cmd_chave = {}, {}
    for t in tabs:
        if conj[t]:
            k = max(conj[t].items(), key=lambda kv: (kv[1], len(kv[0])))
            chave[t] = list(k[0])
            cmd_chave[t] = k[1]
        else:
            chave[t] = []
    # vínculos fortes: o valor de uma coluna vem de outra tabela (origem `tabela: X.COL` na linhagem).
    # Busca (WHERE ou chave de busca): a tabela procurada é a referenciada (pai) e a tabela de onde veio o valor guarda a referência (filho).
    # Gravação: a tabela gravada guarda a referência (filho) para a tabela de onde veio o valor (pai); se a maior parte das colunas vem da mesma tabela, é cópia (histórico/controle).
    brutos = defaultdict(lambda: {'pares': set(), 'fontes': set(), 'cmds': set()})

    def add(t, col, orig, cmd, fonte):
        m = ORIG.search(orig or '')
        if not m or m.group(1) not in cols or m.group(1) == t or col not in nomes.get(t, ()) or m.group(2) not in nomes[m.group(1)]:
            return
        x, colx = m.group(1), m.group(2)
        modo = 'gravação' if fonte == 'gravação' else 'busca'
        pai, filho, cp, cf = (x, t, colx, col) if modo == 'gravação' else (t, x, col, colx)
        g = brutos[(pai, filho, modo)]
        g['pares'].add((cp, cf))
        g['fontes'].add(fonte)
        g['cmds'].add(cmd)
    for w in ev['where']:
        add(w['tabela'], w['coluna'], w['origem'], w['cmd'], 'WHERE')
    for b in ev['buscas']:
        add(b['tabela'], b['coluna'], b['origem'], b['cmd'], 'chave de busca')
    for g in ev['gravs']:
        add(g['tabela'], g['coluna'], g['origem'], g['cmd'], 'gravação')
    fortes = {}
    for k, v in sorted(brutos.items()):
        pai_, filho_, modo = k
        pares = sorted(v['pares'])
        fortes[k] = {'pares': pares, 'cols_pai': [p for p, _f in pares], 'cols_filho': [f for _p, f in pares], 'fontes': sorted(v['fontes']), 'cmds': sorted(v['cmds']),
                     'copia': modo == 'gravação' and len(pares) * 2 >= len(cols[filho_])}
    for (pai_, filho_, modo), v in fortes.items():
        if not chave[filho_] and v['copia']:
            chave[filho_] = [f for p, f in v['pares'] if p in chave[pai_]]
            v['chave_herdada'] = True
    for (pai_, filho_, modo), v in fortes.items():
        kf, cf = set(chave[filho_]), set(v['cols_filho'])
        v['cardinalidade'] = '1:1' if kf and cf == kf and not v['copia'] else '1:N'
        v['parte'] = bool(kf and cf <= kf and not v['copia'])
    # colunas por nome
    onde = defaultdict(list)
    for t in tabs:
        for c in cols[t]:
            onde[c['nome']].append(t)
    em_forte = {(k[0], c) for k, v in fortes.items() for c in v['cols_pai']} | {(k[1], c) for k, v in fortes.items() for c in v['cols_filho']}
    busca = {(t, c) for t, cs in chave.items() for c in cs}
    transv = {n for n, ts in onde.items() if len(ts) >= 3 and not any((t, n) in em_forte or (t, n) in busca for t in ts)}
    pares_fortes = {(frozenset((k[0], k[1])), c) for k, v in fortes.items() for c in v['cols_pai'] + v['cols_filho']}
    fracos = []
    for n, ts in sorted(onde.items()):
        if n in transv or len(ts) < 2:
            continue
        tipos = {t: next(c['tipo'] for c in cols[t] if c['nome'] == n) for t in ts}
        fam = {tipo_familia(v) for v in tipos.values()} - {'INDETERMINADO'}
        fracos.append({'coluna': n, 'tabelas': ts, 'tipos': tipos, 'compativel': len(fam) <= 1, 'chaves': [t for t in ts if n in chave[t] or ev['chave1'][t] == n],
                       'forte': any((t, n) in em_forte for t in ts)})
    # junção: tabela cuja chave é feita de vínculos com 2 ou mais tabelas pai
    juncao = []
    for t in tabs:
        pais = {k[0] for k, v in fortes.items() if k[1] == t and set(v['cols_filho']) <= set(chave[t]) and not v['copia']}
        if len(pais) >= 2 and len(cols[t]) <= len(pais) * 3 + 4:
            juncao.append({'tabela': t, 'liga': sorted(pais)})
    # agregados candidatos: raiz = tabela que não é parte de ninguém; membros = partes ligadas
    pai = {}
    for (p_, f_, _m), v in fortes.items():
        if v['parte']:
            pai.setdefault(f_, p_)
    def raiz(t, vis=()):
        return t if t not in pai or t in vis else raiz(pai[t], vis + (t,))
    grupos = defaultdict(list)
    for t in tabs:
        grupos[raiz(t)].append(t)
    # vocabulário
    prefixos = defaultdict(lambda: {'tipos': Counter(), 'ex': []})
    toks = defaultdict(lambda: {'n': 0, 'ex': []})
    for t in tabs:
        for c in cols[t]:
            p = prefixos[c['nome'][0]]
            p['tipos'][tipo_familia(c['tipo'])] += 1
            if len(p['ex']) < 4 and c['nome'] not in p['ex']:
                p['ex'].append(c['nome'])
        for nome in [t] + [c['nome'] for c in cols[t]]:
            ps = nome.split('_')
            for i, tk in enumerate(ps):
                tk = tk[1:] if i == 0 and len(tk) > 3 else tk
                d = toks[tk]
                d['n'] += 1
                if len(d['ex']) < 3 and nome not in d['ex']:
                    d['ex'].append(nome)
    # business core x corporativo: classe dos programas que acessam a tabela (fase 0, vinda da fase 3): coordenador/funcional = business core, corporativo = corporativo
    categoria, acesso_cls = {}, {}
    for t in tabs:
        prog = ev['acesso'].get(t, [])
        nucleo = sorted({p for p, c, _o in prog if c in ('COORDENADOR', 'FUNCIONAL')})
        corp = sorted({p for p, c, _o in prog if c == 'CORPORATIVO'})
        infra = sorted({p for p, c, _o in prog if c == 'INFRAESTRUTURA'})
        grava = any(re.search(r'INSERT|UPDATE|DELETE|MERGE', o) for p, c, o in prog if c in ('COORDENADOR', 'FUNCIONAL'))
        categoria[t] = CAT_NUCLEO if nucleo and (grava or len(nucleo) >= len(corp)) else CAT_CORP
        acesso_cls[t] = {'nucleo': nucleo, 'corp': corp, 'infra': infra, 'grava': grava}
    return {'em_forte': em_forte, 'categoria': categoria, 'acesso_cls': acesso_cls, 'chave': chave, 'cmd_chave': cmd_chave, 'fixos': fixos, 'fortes': fortes, 'fracos': fracos, 'transv': {n: onde[n] for n in sorted(transv)}, 'juncao': juncao,
            'pai': pai, 'grupos': dict(grupos), 'prefixos': prefixos, 'toks': toks, 'onde': onde}


# ----------------------------------------------------------------------------- interpretação
def ler_interp(base):
    d = Path(base) / 'interpretacao-dominio'
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


def achado(cita, texto):
    return norm(cita).lower() in texto.lower() if str(cita).strip() else False


def validar(ev, de, interp):
    erros, falhas = [], []
    cols = ev['cols']
    extra = set(interp) - CHAVES_RAIZ
    for k in sorted(extra):
        erros.append(f'chave desconhecida na interpretação: {k} (o agrupamento em contextos delimitados é a próxima fase e não entra aqui)')
    for t in interp['entidades'], interp['agregados'], interp['relacionamentos']:
        for x in t:
            if RE_CODIGO.search(json.dumps(x, ensure_ascii=False)):
                falhas.append(f'texto parece código (anotação, class, import): {json.dumps(x, ensure_ascii=False)[:100]}')
    ents = {}
    classes = Counter()
    for e in interp['entidades']:
        t = e.get('tabela')
        if t not in cols:
            erros.append(f'entidade de tabela inexistente: {t}')
            continue
        if t in ents:
            erros.append(f'tabela com duas entidades: {t}')
            continue
        ents[t] = e
        n = str(e.get('nome', ''))
        classes[n] += 1
        if not RE_CLASSE.match(n) or n.upper() == t.replace('_', '').upper():
            falhas.append(f'{t}: nome de classe "{n}" fora da convenção (UpperCamelCase, singular, sem o nome físico nem prefixo de tabela)')
        if not str(e.get('descricao', '')).strip():
            falhas.append(f'{t}: entidade sem descricao')
        pp = ev['papel'].get(t, {}).get('papel')
        if e.get('natureza') not in NATUREZAS:
            falhas.append(f'{t}: natureza deve ser um de {sorted(NATUREZAS)}')
        elif pp == 'protagonista' and e['natureza'] != 'núcleo':
            falhas.append(f'{t}: a fase 3 a classifica como protagonista (o sistema a altera), mas a natureza é {e["natureza"]}; use núcleo ou explique a exceção em lacunas')
        elif pp in ('coadjuvante', 'figurante') and e['natureza'] == 'núcleo':
            falhas.append(f'{t}: a fase 3 a classifica como {pp} (só consulta), mas a natureza é núcleo; use referência ou apoio ou explique a exceção em lacunas')
        idt = e.get('identidade') or {}
        ic = idt.get('colunas') or []
        nomes = {c['nome'] for c in cols[t]}
        if not ic or any(c not in nomes for c in ic):
            falhas.append(f'{t}: identidade precisa de colunas existentes ({ic})')
        if idt.get('confianca') not in CONF:
            falhas.append(f'{t}: identidade.confianca deve ser um de {sorted(CONF)}')
        if not achado(idt.get('cita', ''), ev['evid'][t]):
            falhas.append(f'{t}: identidade sem evidência (a citação não existe nos relatórios): {idt.get("cita", "")}')
        vistos, nomes_at = set(), Counter()
        for a in e.get('atributos') or []:
            c = a.get('coluna')
            if c not in nomes:
                erros.append(f'{t}: atributo de coluna inexistente: {c}')
                continue
            if c in vistos:
                erros.append(f'{t}.{c}: coluna traduzida duas vezes')
            vistos.add(c)
            nm = str(a.get('nome', ''))
            nomes_at[nm] += 1
            if not RE_ATRIB.match(nm) or RE_PREFIXO_SQL.match(nm) or nm.upper() == c.replace('_', ''):
                falhas.append(f'{t}.{c}: atributo "{nm}" fora da convenção (lowerCamelCase, sem prefixo SQL como n, d, v, dt, vl, i, c, h; abreviações expandidas)')
            if a.get('tipo_logico') not in TIPOS_LOGICOS:
                falhas.append(f'{t}.{c}: tipo_logico deve ser um de {sorted(TIPOS_LOGICOS)}')
            nulo = next(x['nulo'] for x in cols[t] if x['nome'] == c)
            if not isinstance(a.get('obrigatorio'), bool):
                falhas.append(f'{t}.{c}: obrigatorio deve ser true ou false')
            elif nulo == 'não' and not a['obrigatorio']:
                falhas.append(f'{t}.{c}: a coluna não aceita nulo, o atributo deve ser obrigatorio')
            elif nulo == 'sim' and a['obrigatorio']:
                falhas.append(f'{t}.{c}: a coluna aceita nulo, o atributo não é obrigatorio')
            if not str(a.get('descricao', '')).strip():
                falhas.append(f'{t}.{c}: atributo sem descricao')
            elif so_repete_nome(a['descricao'], nm):
                falhas.append(f'{t}.{c}: a descrição só repete as palavras do nome ("{a["descricao"][:50]}"): explique o significado de negócio (use o uso no SQL, o campo COBOL, os valores e os programas) ou diga em lacunas que a evidência não permite')
        for c in sorted(nomes - vistos):
            falhas.append(f'{t}.{c}: coluna sem atributo (toda coluna deve ser traduzida)')
        for nm, k in nomes_at.items():
            if k > 1:
                falhas.append(f'{t}: atributo "{nm}" repetido na classe')
        for i in e.get('invariantes') or []:
            ic2 = i.get('colunas') or []
            if not str(i.get('regra', '')).strip() or i.get('base') not in BASES_INV or any(c not in nomes for c in ic2) or not ic2:
                falhas.append(f'{t}: invariante precisa de regra, colunas existentes e base em {sorted(BASES_INV)} ({str(i)[:80]})')
            elif i['base'] == 'não nulo' and any(next(x['nulo'] for x in cols[t] if x['nome'] == c) == 'sim' for c in ic2):
                falhas.append(f'{t}: invariante "não nulo" sobre coluna que aceita nulo ({ic2}); só vale para NOT NULL ou, em tabela sem DCLGEN, para coluna que os programas sempre usam como chave')
            elif i['base'] in ('valor fixo', 'identidade') and not achado(i.get('cita', ''), ev['evid'][t]):
                falhas.append(f'{t}: invariante sem evidência: {i.get("cita", "")}')
    for n, k in classes.items():
        if k > 1:
            erros.append(f'nome de classe repetido: {n}')
    for t in sorted(set(cols) - set(ents)):
        falhas.append(f'{t}: tabela sem entidade (toda tabela vira uma classe de domínio)')
    # relacionamentos
    rels, cobertos, tc = [], set(), defaultdict(set)
    for r in interp['relacionamentos']:
        a, b = r.get('de'), r.get('para')
        if a not in cols or b not in cols or a == b:
            erros.append(f'relacionamento entre tabelas inexistentes ou iguais: {a} → {b}')
            continue
        rels.append(r)
        nm = str(r.get('nome', ''))
        if r.get('cardinalidade') not in CARD:
            falhas.append(f'{a}→{b}: cardinalidade deve ser um de {sorted(CARD)}')
        if not RE_ATRIB.match(nm):
            falhas.append(f'{a}→{b}: nome da associação "{nm}" deve ser lowerCamelCase (por exemplo contatoCliente)')
        ca, cb = r.get('colunas_de') or [], r.get('colunas_para') or []
        if r.get('cardinalidade') != 'N:N' and (not ca or not cb or len(ca) != len(cb) or any(c not in {x['nome'] for x in cols[a]} for c in ca) or any(c not in {x['nome'] for x in cols[b]} for c in cb)):
            falhas.append(f'{a}→{b}: colunas_de e colunas_para devem existir, em igual número')
        if r.get('base') not in BASES_REL:
            falhas.append(f'{a}→{b}: base deve ser um de {sorted(BASES_REL)}')
        if r.get('cardinalidade') == 'N:N':
            j = r.get('tabela_juncao')
            if j not in cols or j in (a, b):
                falhas.append(f'{a}→{b}: N:N exige tabela_juncao (uma tabela da evidência, diferente das duas pontas)')
        if not isinstance(r.get('cascata'), bool):
            falhas.append(f'{a}→{b}: cascata deve ser true ou false (exclusão em cascata: a parte não vive sem o todo)')
        if not str(r.get('descricao', '')).strip():
            falhas.append(f'{a}→{b}: relacionamento sem descricao')
        txt = ev['evid'].get(a, '') + '\n' + ev['evid'].get(b, '') + '\n' + ' '.join(f'{k[2]} ({"cópia de colunas" if v["copia"] else "colunas"}) {" ".join(v["fontes"])}' for k, v in de['fortes'].items() if {k[0], k[1]} == {a, b})
        if r.get('base') == 'vínculo forte':
            ok = any({k[0], k[1]} == {a, b} for k in de['fortes'])
            if not ok:
                falhas.append(f'{a}→{b}: base "vínculo forte", mas a linhagem não liga essas duas tabelas')
        if r.get('base') == 'vínculo fraco' and not any(c in {x['nome'] for x in cols[a]} and c in {x['nome'] for x in cols[b]} for c in ca + cb):
            falhas.append(f'{a}→{b}: base "vínculo fraco" exige colunas de mesmo nome nas duas tabelas')
        if r.get('base') != 'dedução' and not achado(r.get('cita', ''), txt):
            falhas.append(f'{a}→{b}: citação sem evidência: {r.get("cita", "")}')
        for k in de['fortes']:
            if {k[0], k[1]} == {a, b}:
                cobertos.add(k)
        for c in set(ca) | set(cb):
            tc[c].update([a] if c in ca or c in {x['nome'] for x in cols[a]} else [])
            tc[c].update([b] if c in cb or c in {x['nome'] for x in cols[b]} else [])
    for d in interp['descartes']:
        if not str(d.get('motivo', '')).strip() or d.get('coluna') not in de['onde']:
            falhas.append(f'descarte precisa de coluna existente e motivo: {d}')
            continue
        tc[d['coluna']].update(d.get('tabelas') or de['onde'][d['coluna']])
    for k, v in de['fortes'].items():
        if k not in cobertos:
            falhas.append(f'vínculo forte sem relacionamento: {k[1]} referencia {k[0]} ({", ".join(f"{p}←{f}" for p, f in v["pares"][:3])}); a linhagem mostra o valor vindo da outra tabela')
    for f in de['fracos']:
        falta = sorted(set(f['tabelas']) - tc[f['coluna']] - {t for t in f['tabelas'] if (t, f['coluna']) in de['em_forte']})
        if f['compativel'] and falta and len(f['tabelas']) - len([t for t in f['tabelas'] if (t, f['coluna']) in de['em_forte']]) >= 1:
            falhas.append(f'vínculo fraco sem decisão: coluna {f["coluna"]} em {", ".join(f["tabelas"])} (sem relacionamento ou descarte para {", ".join(falta)}); aceite como relacionamento ou descarte com motivo em `descartes`')
    # agregados
    em_agr = Counter()
    for g in interp['agregados']:
        rz, mem = g.get('raiz'), g.get('membros') or []
        if rz not in cols or any(m not in cols for m in mem):
            erros.append(f'agregado {g.get("nome")}: raiz ou membro inexistente')
            continue
        if not RE_CLASSE.match(str(g.get('nome', ''))):
            falhas.append(f'agregado "{g.get("nome")}" fora da convenção UpperCamelCase')
        em_agr.update([rz] + [m for m in mem if m != rz])
        if not str(g.get('justificativa', '')).strip():
            falhas.append(f'agregado {g.get("nome")}: sem justificativa')
        cats = {de['categoria'][m] for m in [rz] + list(mem)}
        if len(cats) > 1:
            falhas.append(f'agregado {g.get("nome")}: mistura {CAT_NUCLEO} e {CAT_CORP} ({", ".join(m + "=" + de["categoria"][m] for m in [rz] + list(mem))}); separe em agregados distintos (os programas que o usam são de classes diferentes) e ligue por relacionamento')
        ligado, pend = {rz}, set(mem) - {rz}
        mudou = True
        while pend and mudou:
            mudou = False
            for r in rels:
                for x, y in ((r['de'], r['para']), (r['para'], r['de'])):
                    if x in ligado and y in pend:
                        ligado.add(y)
                        pend.discard(y)
                        mudou = True
                if r.get('cardinalidade') == 'N:N' and r.get('tabela_juncao') in pend and (r['de'] in ligado or r['para'] in ligado):
                    ligado.add(r['tabela_juncao'])
                    pend.discard(r['tabela_juncao'])
                    mudou = True
        for m in sorted(pend):
            falhas.append(f'agregado {g.get("nome")}: {m} não tem relacionamento com a raiz ou com outro membro')
        for i in g.get('invariantes') or []:
            if not str(i.get('regra', '')).strip():
                falhas.append(f'agregado {g.get("nome")}: invariante sem regra')
    for t in cols:
        if em_agr[t] == 0 and ents.get(t) is not None:
            falhas.append(f'{t}: entidade fora de qualquer agregado (uma entidade sozinha é a raiz do próprio agregado)')
        if em_agr[t] > 1:
            falhas.append(f'{t}: entidade em {em_agr[t]} agregados (cada entidade pertence a um só)')
    for l in interp['lacunas']:
        if not (str(l.get('assunto', '')).strip() and str(l.get('detalhe', '')).strip()):
            falhas.append(f'lacuna incompleta: {l}')
    return erros, falhas


# ----------------------------------------------------------------------------- relatório
def lk(t):
    return rm.link(t, '03-data-schema', 'tabela-' + t)


def modelo(ev, de, interp, falhas):
    cols, chave = ev['cols'], de['chave']
    tabs = sorted(cols)
    n_cols = sum(len(c) for c in cols.values())
    ents = {e['tabela']: e for e in (interp or {}).get('entidades', [])}
    cls = {t: ents[t]['nome'] for t in ents}
    cards = [rm.card('tabelas (atingidas na execução dinâmica)', len(tabs)), rm.card('tabelas do business core', sum(1 for t in tabs if de['categoria'][t] == CAT_NUCLEO)), rm.card('tabelas corporativas', sum(1 for t in tabs if de['categoria'][t] == CAT_CORP)), rm.card('protagonistas (núcleo)', sum(1 for t in tabs if ev['papel'].get(t, {}).get('papel') == 'protagonista')), rm.card('tabelas dinâmicas (sql-mapping)', len(ev['dinamicas'])), rm.card('tabelas ignoradas (não atingidas)', len(ev['ignoradas'])), rm.card('colunas', n_cols), rm.card('chaves candidatas', sum(1 for t in tabs if chave[t])), rm.card('vínculos fortes', len(de['fortes'])),
             rm.card('vínculos fracos', len(de['fracos'])), rm.card('colunas transversais', len(de['transv'])), rm.card('candidatas a junção', len(de['juncao'])), rm.card('grupos de agregado (candidatos)', len(de['grupos']))]
    if interp:
        cards += [rm.card('classes de domínio', len(ents)), rm.card('relacionamentos', len(interp['relacionamentos'])), rm.card('agregados', len(interp['agregados'])),
                  rm.card('afirmações sem evidência', len(falhas))]
    secs = []
    if interp:
        agr_de = {}
        for g in interp['agregados']:
            for m in [g['raiz']] + list(g.get('membros') or []):
                agr_de[m] = g['nome']
        nos = []
        for t in tabs:
            e = ents.get(t)
            if not e:
                continue
            idc = set((e.get('identidade') or {}).get('colunas') or [])
            nos.append({'id': t, 'label': e['nome'], 'group': agr_de.get(t, ''), 'categoria': de['categoria'][t], 'estereotipo': 'Agregado' if any(a['raiz'] == t for a in interp['agregados']) else 'Entidade', 'columns': [{'name': a['nome'], 'type': a.get('tipo_logico', ''), 'key': a['coluna'] in idc} for a in e.get('atributos') or []]})
        nome_cl = {t: ents[t]['nome'] for t in ents}
        arestas = []
        for r in interp['relacionamentos']:
            if r.get('cardinalidade') == 'N:N':
                arestas.append({'from': r['de'], 'to': r['para'], 'label': f'N:N {r.get("nome", "")} (via {nome_cl.get(r.get("tabela_juncao"), r.get("tabela_juncao"))})'})
            else:
                arestas.append({'from': r['de'], 'to': r['para'], 'label': f'{r["cardinalidade"]} {r.get("nome", "")}'})
        g = rm.G('Classes de domínio e associações (agrupadas por agregado)', nos, arestas, kind='er',
                 note='Cada caixa é uma classe de domínio com os atributos lógicos (chave = identidade), marcada «Agregado» (raiz) ou «Entidade» (membro); a borda tracejada envolve o agregado. A seta vai do todo para a parte: 1:1, 1:N (a parte não vive sem o todo) ou N:N (por tabela de junção). Sem Bounded Contexts: o agrupamento em contextos é a próxima fase.')
        g['sem_tabela'] = True
        g['edge_labels'] = True
        g['setas'] = True
        g['agregados'] = True
        linhas = [(lk(t), cls[t], de['categoria'][t], agr_de.get(t, '—'), 'raiz do agregado' if any(a['raiz'] == t for a in interp['agregados']) else 'entidade', ev['papel'].get(t, {}).get('papel', '—'), ents[t].get('natureza', ''),
                   ', '.join(f'{c} → {next((a["nome"] for a in ents[t]["atributos"] if a["coluna"] == c), c)}' for c in (ents[t].get('identidade') or {}).get('colunas') or []), ents[t].get('descricao', ''))
                  for t in tabs if t in ents]
        rel_t = [(f'{cls.get(r["de"], r["de"])}', r.get('nome', ''), r['cardinalidade'], f'{cls.get(r["para"], r["para"])}', ', '.join(r.get('colunas_de') or []) + ' → ' + ', '.join(r.get('colunas_para') or []) if r['cardinalidade'] != 'N:N' else cls.get(r.get('tabela_juncao'), r.get('tabela_juncao')),
                  'sim' if r.get('cascata') else 'não', r.get('base', ''), r.get('descricao', '')) for r in interp['relacionamentos']]
        secs.append(rm.S('relacao', 'Relação: classes de domínio e associações', [
            g,
            rm.T('Classes de domínio: tabela física → classe', ['Tabela', 'Classe', 'Categoria', 'Agregado', 'Papel no agregado', 'Papel na execução (fase 3)', 'Natureza no domínio', 'Identidade (coluna → atributo)', 'Descrição'], linhas, ids=[f'classe-{t}' for t in tabs if t in ents]),
            rm.T('Associações entre as classes', ['De (todo)', 'Associação', 'Cardinalidade', 'Para (parte)', 'Colunas (física) ou junção', 'Cascata', 'Base', 'Descrição'], rel_t)],
            'A tradução do modelo físico em classes de domínio: uma tabela vira uma classe; chaves estrangeiras viram associações semânticas.'))
        agr_rows = []
        for a in interp['agregados']:
            mem = [m for m in a.get('membros') or [] if m != a['raiz']]
            inv = '; '.join(i.get('regra', '') for i in a.get('invariantes') or []) or '—'
            agr_rows.append((a['nome'], de['categoria'][a['raiz']], f'{cls.get(a["raiz"], a["raiz"])} ({a["raiz"]})', ', '.join(f'{cls.get(m, m)} ({m})' for m in mem) or '— (agregado de uma entidade)', inv, a.get('justificativa', '')))
        secs.append(rm.S('agregados', 'Agregados: raiz, membros e invariantes', [
            rm.T('Agregados', ['Agregado', 'Categoria', 'Raiz', 'Membros', 'Invariantes do agregado', 'Por que esta fronteira'], agr_rows)],
            'A raiz é o único ponto de entrada do agregado: encapsula as entidades membros e garante as invariantes. Candidatas calculadas pelo script estão na seção de evidências.'))
        at_rows, at_ids, inv_rows = [], [], []
        for t in tabs:
            e = ents.get(t)
            if not e:
                continue
            idc = set((e.get('identidade') or {}).get('colunas') or [])
            cm = {c['nome']: c for c in cols[t]}
            for a in e.get('atributos') or []:
                c = cm.get(a['coluna'], {})
                at_rows.append((e['nome'], a['nome'], a.get('tipo_logico', ''), 'sim' if a.get('obrigatorio') else 'não', 'identidade' if a['coluna'] in idc else '', a.get('descricao', ''), t, a['coluna'], c.get('tipo', ''), c.get('uso', '') or '—', c.get('origem', '')))
                at_ids.append(f'attr-{t}.{a["coluna"]}')
            for i in e.get('invariantes') or []:
                inv_rows.append((e['nome'], i.get('regra', ''), ', '.join(i.get('colunas') or []), i.get('base', ''), i.get('cita', '')))
        secs.append(rm.S('entidades', 'Entidades: atributos lógicos', [
            rm.T('Atributos de cada classe (coluna física → atributo lógico)', ['Classe', 'Atributo', 'Tipo lógico', 'Obrigatório', 'Identidade', 'Descrição', 'Tabela', 'Coluna', 'Tipo SQL', 'Uso no SQL (fase 4)', 'Origem da coluna'], at_rows, ids=at_ids),
            rm.T('Invariantes das entidades', ['Classe', 'Regra', 'Colunas', 'Base', 'Evidência'], inv_rows)],
            'Nomes: plural → singular, MAIÚSCULAS_COM_SUBLINHADO → CamelCase, prefixos SQL tirados e abreviações expandidas. Obrigatório vem da coluna NOT NULL.'))
        desc = [(d.get('coluna'), ', '.join(d.get('tabelas') or de['onde'].get(d.get('coluna'), [])), d.get('motivo')) for d in interp['descartes']]
        secs.append(rm.S('descartes', 'Vínculos fracos descartados', [rm.T('Colunas de mesmo nome sem relacionamento de domínio', ['Coluna', 'Tabelas', 'Motivo'], desc)],
                         'Coluna de mesmo nome em duas tabelas é só um indício; aqui estão os indícios que a interpretação rejeitou.'))
        lac = [(l.get('assunto', ''), l.get('detalhe', '')) for l in interp['lacunas']]
        secs.append(rm.S('lacunas', 'Lacunas e dúvidas', [rm.T('O que a evidência não permite decidir', ['Assunto', 'Detalhe'], lac)], 'Tudo que o modelo físico e a linhagem não dizem: confirmar com o dono do domínio.'))
    else:
        secs.append(rm.S('relacao', 'Relação: tabelas e vínculos (evidência)', [rm.X('AVISO: sem interpretação (interpretacao-dominio/*.json, prompt 7). A fase mostra só a evidência calculada.')]))
    # evidência
    ch_rows = [(lk(t), len(cols[t]), ', '.join(chave[t]) or '—', de['cmd_chave'].get(t, 0), ev['chave1'][t],
                '; '.join(f'{c}={v} ({n})' for (c, v), n in de['fixos'][t].most_common(3)) or '—', ev['papel'].get(t, {}).get('papel', '—'), NATUREZA_DE.get(ev['papel'].get(t, {}).get('papel'), ('', ''))[0] or '—') for t in tabs]
    ev_secs = [rm.T('Chaves candidatas', ['Tabela', 'Colunas', 'Chave candidata', 'Comandos que a usam', 'Primeira coluna do DCLGEN (indício fraco)',
                                                                       'Filtros de estado (coluna=valor fixo)', 'Papel (fase 3)', 'Natureza provável no domínio'], ch_rows,
                        note='Chave candidata = colunas que os programas comparam com `=` a um campo do programa nos WHERE, em conjunto (deduzida do uso: o banco não declara PK). Filtros de estado = coluna comparada a um valor fixo.',
                        ids=[f'chave-{t}' for t in tabs])]
    fr_rows = []
    for (pai, filho, modo), v in de['fortes'].items():
        fr_rows.append((lk(pai), lk(filho), ', '.join(f'{p} ← {f}' for p, f in v['pares']), modo + (' (cópia de colunas)' if v['copia'] else ''), v['cardinalidade'] + (' (parte: a chave do filho contém o vínculo)' if v['parte'] else ''),
                        ', '.join(v['fontes']), ', '.join(v['cmds'][:3]) + (f' (+{len(v["cmds"]) - 3})' if len(v['cmds']) > 3 else '')))
    ev_secs.append(rm.T('Papel na execução e natureza no domínio', ['Papel (fase 3)', 'Natureza provável', 'Leitura', 'Tabelas'],
                        [(pp, nat, txt, ', '.join(t for t in tabs if ev['papel'].get(t, {}).get('papel') == pp) or '—') for pp, (nat, txt) in NATUREZA_DE.items()]))
    if ev['dinamicas']:
        ev_secs.append(rm.T('Tabelas dinâmicas descobertas no sql-mapping (fase 10)', ['Tabela', 'Consulta', 'Serviço que executa', 'Classe do serviço', 'Campo de parâmetro', 'Programas que passam o nome', 'No mapeamento DB2 das fases 1 e 3', 'Colunas inferidas'],
                            [(t, d['consulta'], d['servico'], d['classe_servico'], d['param'], ', '.join(d['passam']), d['no_db2'], ', '.join(c['nome'] for c in ev['cols'][t])) for t, d in sorted(ev['dinamicas'].items())],
                            note='Tabelas que nenhum DCLGEN nem comando estático mostra: o nome passa por parâmetro a um serviço genérico. Colunas, tipos e filtros vêm do que os programas chamadores leem e comparam (sql-mapping); o tipo é indeterminado.'))
    ev_secs.append(rm.T('Acesso por classe de programa (business core x corporativo)', ['Tabela', 'Categoria', 'Programas do business core (coordenador/funcional)', 'Programas corporativos', 'Business core grava'],
                        [(lk(t), de['categoria'][t], ', '.join(de['acesso_cls'][t]['nucleo']) or '—', ', '.join(de['acesso_cls'][t]['corp']) or '—', 'sim' if de['acesso_cls'][t]['grava'] else 'não') for t in tabs],
                        note='Regra: a tabela é do business core quando algum programa coordenador ou funcional a grava, ou quando eles são a maioria dos programas que a acessam (empate vai para o business core); caso contrário é corporativa. A classe dos programas vem da fase 0.'))
    ev_secs.append(rm.T('Vínculos fortes (o valor de uma coluna vem de outra tabela, na linhagem)', ['Tabela referenciada (pai)', 'Tabela que referencia (filho)', 'Colunas (pai ← filho)', 'Tipo de evidência', 'Cardinalidade candidata (pai → filho)', 'Onde aparece', 'Comandos'], fr_rows,
                        ids=[f'forte-{k[0]}-{k[1]}-{k[2]}' for k in de['fortes']]))
    fw = [(f['coluna'], ', '.join(f'{t} ({f["tipos"][t]})' for t in f['tabelas']), ', '.join(f['chaves']) or '—', 'sim' if f['compativel'] else 'não', 'sim' if f['forte'] else '') for f in de['fracos']]
    ev_secs.append(rm.T('Vínculos fracos (mesmo nome de coluna em tabelas diferentes)', ['Coluna', 'Tabelas (tipo)', 'Tabelas em que é chave', 'Tipos compatíveis', 'Também em vínculo forte'], fw))
    ev_secs.append(rm.T('Colunas transversais (em 3 tabelas ou mais, sem vínculo nem chave: auditoria e controle, não relacionamento)', ['Coluna', 'Tabelas'], [(n, ', '.join(ts)) for n, ts in de['transv'].items()]))
    ev_secs.append(rm.T('Candidatas a tabela de junção (N:N)', ['Tabela', 'Liga'], [(lk(j['tabela']), ', '.join(j['liga'])) for j in de['juncao']]))
    ev_secs.append(rm.T('Candidatas a agregado (tabelas cuja chave contém o vínculo ficam sob a raiz)', ['Raiz candidata', 'Papel da raiz (fase 3)', 'Partes ligadas'], [(lk(r), ev['papel'].get(r, {}).get('papel', '—'), ', '.join(m for m in ms if m != r) or '—') for r, ms in sorted(de['grupos'].items())]))
    ev_secs.append(rm.T('Prefixos dos nomes físicos (1ª letra → tipos observados)', ['Prefixo', 'Colunas por tipo', 'Exemplos'], [(p, ', '.join(f'{k} {n}' for k, n in v['tipos'].most_common()), ', '.join(v['ex'])) for p, v in sorted(de['prefixos'].items())]))
    ev_secs.append(rm.T('Abreviações nos nomes físicos (para expandir nos nomes de domínio)', ['Abreviação', 'Ocorrências', 'Exemplos'], [(k, v['n'], ', '.join(v['ex'])) for k, v in sorted(de['toks'].items())]))
    secs.append(rm.S('evidencia', 'Evidências calculadas', ev_secs, 'Tudo calculado dos relatórios das fases 3 e 4 sem IA. O DB2 do relatório não declara PK/FK/unique: chaves e vínculos são deduzidos do uso nos programas e marcados como candidatos.'))
    secs.append(rm.S('criterio', 'Como o modelo foi montado', [rm.X(
        'Escopo: só as tabelas que a análise dinâmica atingiu (fase 4), mais as tabelas dinâmicas descobertas no sql-mapping (' + (', '.join(sorted(ev['dinamicas'])) or 'nenhuma') + '); ignoradas: ' + (', '.join(ev['ignoradas']) or 'nenhuma') + '. '
        'Entrada: tabelas, colunas, tipos e aceita-nulo (fase 3) e, da linhagem (fase 4), as cláusulas WHERE, as chaves de busca e as gravações com a origem de cada valor. '
        'Tabela → classe de domínio; coluna → atributo lógico (nome sem prefixo SQL, abreviações expandidas, CamelCase, singular); vínculo entre tabelas → associação semântica 1:1, 1:N ou N:N; '
        'NOT NULL, identidade e filtros de estado → invariantes. Uma entidade tem identidade própria e ciclo de vida; o agregado tem uma raiz que é o único ponto de entrada e que garante as invariantes. '
        'Não há código nem anotações de framework, e o agrupamento em Bounded Contexts não é feito aqui (próxima fase: Context Discovery).')], 'Convenções e limites desta fase.'))
    return rm.model('Modelo de domínio (DDD)', 'Do modelo físico (tabelas, colunas, vínculos) ao modelo lógico: classes, atributos, associações, agregados e invariantes.', cards, secs)


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
    erros, falhas = ([], [])
    if interp is None:
        print('AVISO: sem interpretacao-dominio/*.json (prompt 7): a fase mostra só a evidência calculada')
    else:
        erros, falhas = validar(ev, de, interp)
        if erros:
            raise SystemExit('interpretação inconsistente com os relatórios:\n  ' + '\n  '.join(erros))
    mod = modelo(ev, de, interp, falhas)
    S.escrever(saida, FASE, mod)
    print(f'{len(ev["cols"])} tabelas, {sum(len(c) for c in ev["cols"].values())} colunas, {len(de["fortes"])} vínculos fortes, {len(de["fracos"])} fracos; afirmações sem evidência: {len(falhas)}')
    for x in falhas:
        print('  ' + x)
    sys.exit(1 if falhas else 0)


if __name__ == '__main__':
    main()
