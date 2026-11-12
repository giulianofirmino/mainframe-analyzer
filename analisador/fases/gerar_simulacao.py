#!/usr/bin/env python3
"""Relatório business-rules: regras de negócio lidas ÚNICA E EXCLUSIVAMENTE dos relatórios gerados (<fase>/ia/report.json).

  python3 gerar_simulacao.py <pasta-da-analise> [pasta-de-saida] [--interpretacao PASTA]   (padrão da saída: a pasta da análise)

Saída: <saida>/11 - business-rules/human/report.html e <saida>/11 - business-rules/ia/report.json (o mesmo modelo de visão, como as fases da análise).
Entradas: 00-*/ia/report.json (classe dos programas), 05-*/ia/report.json (decisões do mapa de decisão), 04-*/ia/report.json (linhagem: comandos SQL,
WHERE, chaves, retornos) e 06-*/ia/report.json (regras determinísticas: tipo, escopo, condições, efeitos, fluxos de detalhe). Nenhum outro arquivo da
análise e nenhum código-fonte é aberto. A interpretação (interpretacao/*.json: categorias e regras de negócio reunidas; o escopo vem só da fase 6) vem
de uma IA; o script junta evidência copiada dos relatórios, o texto da interpretação e a rastreabilidade decisão → regra determinística → regra de
negócio, e confere que cada literal citado existe na regra ou nas linhas de linhagem indicadas. Mesma entrada, mesma saída.
Filtro de modernização: entram só as regras de escopo 'negócio' (coluna do relatório 06) de programas que a fase 0 não marcou como INFRAESTRUTURA."""
import html
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

JUNCAO = re.compile(r'[A-Z]\w*\.\w+$')
AQUI = Path(__file__).resolve().parent
RAIZ = next((q for q in ([Path(os.environ['ANALISE_RAIZ'])] if os.environ.get('ANALISE_RAIZ') else []) + list(AQUI.parents) if (q / 'semantic_core').is_dir()), AQUI.parents[1])   # raiz do analisador (cópias da pasta de IA em outro lugar usam ANALISE_RAIZ)
sys.path.insert(0, str(RAIZ / 'semantic_core'))
import report_model as rm  # noqa: E402
import condition_criteria as cc  # noqa: E402
import report_render as rr  # noqa: E402
import projeto_config  # noqa: E402
CONFIG = projeto_config.carregar()   # analise.config.json do projeto (ANALISE_CONFIG): prefixos, campos de infraestrutura, SQLCODE de negócio, categorias de mecanismo
BASE = Path(os.environ['ANALISE_INTERPRETACOES']) if os.environ.get('ANALISE_INTERPRETACOES') else AQUI   # pasta das interpretações (a análise); o pipeline a informa
E = html.escape
DIN = []   # comandos SQL estáticos que substituem consultas dinâmicas (fase 10), como regras determinísticas sintéticas: entram só na resolução das regras de negócio, nunca na rastreabilidade


def carregar(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


COPYBOOKS = set()   # nomes de copybook da análise (fase 2, "Copybooks: usados ou não"); definidos por definir_copybooks
_RE_CB = None
CHAVES_FIXAS = {'anchor', 'phase', 'id', 'from', 'to', 'origem'}   # chaves do modelo que são âncoras ou ids, nunca texto de atributo


def definir_copybooks(ana):
    """Lê os nomes de copybook da fase 2 (tabela "Copybooks: usados ou não", coluna Copybook), sem lista fixa: servem para tirar o prefixo de copybook dos nomes de atributo."""
    global COPYBOOKS, _RE_CB
    COPYBOOKS = set()
    try:
        for _s, bt, rows in tabelas(fase(ana, '02-')):
            if bt.startswith('Copybooks: usados ou não'):
                for r in rows:
                    n = txt(r.get('Copybook', '')).strip().upper()
                    if re.fullmatch(r'[A-Z0-9#@$][A-Z0-9#@$]*', n):
                        COPYBOOKS.add(n)
    except SystemExit:
        pass
    _RE_CB = re.compile(r'(?<![A-Za-z0-9#@$-])(?:' + '|'.join(sorted(map(re.escape, COPYBOOKS), key=len, reverse=True)) + r')-(?=[A-Za-z0-9])') if COPYBOOKS else None


def sem_copybook(t):
    """Tira o nome do copybook do início de um nome de atributo (`PRGWQBE-E-CTPO-ITEM` → `E-CTPO-ITEM`), em qualquer texto."""
    if not isinstance(t, str):
        return t
    return nomes_de_campo(_RE_CB.sub('', t) if _RE_CB else t)


_RE_NOMES = [(re.compile(r'\bc[óo]digos? de retorno\b', re.I), 'COD-RETORNO'), (re.compile(r'\bc[óo]digos? de erro\b', re.I), 'COD-ERRO'), (re.compile(r'\bc[óo]digos? de mensagem\b', re.I), 'COD-MENSAGEM'),
             (re.compile(r'(?<![\w-])retornos? (?=\d)', re.I), 'COD-RETORNO '),
             (re.compile(r'(COD-ERRO\b[^,;.()]{0,25}(?:,| e| ou|/)) +mensage(?:m|ns)\b', re.I), r'\1 COD-MENSAGEM'),      # "COD-ERRO '0020', mensagem 'ABC0234'"
             (re.compile(r'(COD-RETORNO\b(?:,| e|/) +(?:COD-ERRO,? (?:e |ou )?)?)mensage(?:m|ns)\b', re.I), r'\1COD-MENSAGEM'),
             (re.compile(r'(?<![\w-])mensage(?:m|ns) (?=[\'"“]?[A-Z]{2,6}\d{3,}|[\'"“]?(?:SPACES|ZEROS)\b)'), 'COD-MENSAGEM ')]   # mensagem seguida do código da mensagem   # o campo, não a palavra: "retorno 08" → "COD-RETORNO 08"


def nomes_de_campo(t):
    """Nos relatórios de regras de negócio e de fluxos: COD-RETORNO, COD-ERRO e COD-MENSAGEM."""
    for rx, novo in _RE_NOMES:
        t = rx.sub(novo, t)
    return t


def limpar_copybooks(o, chave=None):
    if isinstance(o, str):
        return o if chave in CHAVES_FIXAS else sem_copybook(o)
    if isinstance(o, list):
        return [limpar_copybooks(x, chave) for x in o]
    if isinstance(o, dict):
        return {k: limpar_copybooks(v, k) for k, v in o.items()}
    return o


def txt(c):
    if isinstance(c, dict):
        return c['text'] if 'text' in c else '; '.join(f'{k}={v}' for k, v in c.items())
    if isinstance(c, list):
        return ', '.join(txt(x) for x in c)
    return '' if c is None else str(c)


def fase(ana, prefixo):
    d = sorted(Path(ana).glob(prefixo + '*'))
    if not d:
        raise SystemExit(f'relatório da fase {prefixo}* não encontrado em {ana}')
    return carregar(d[0] / 'ia' / 'report.json')


def fase_varias(ana, prefixos):
    """Uma visão só (seções concatenadas) de vários relatórios: as tabelas que antes eram da fase de dependências estão agora nas fases 1, 2 e 3."""
    rels = [fase(ana, p) for p in prefixos]
    return {'sections': [s for r in rels for s in r['sections']]}


def tabelas(rel):
    """[(título da seção, título do bloco, [linha como dict coluna→texto])] de todas as tabelas de um relatório."""
    out = []
    for s in rel['sections']:
        for b in s.get('blocks', []):
            if b['type'] == 'table':
                cols = b['columns']
                out.append((s['title'], b.get('title') or '', [{c: txt(v) for c, v in zip(cols, r)} for r in b['rows']]))
    return out


def lerRelatorios(ana):
    """Estruturas usadas pela simulação, todas lidas dos relatórios das fases 0, 4 e 6."""
    f0, f2, f4, f5 = fase(ana, '00-'), fase(ana, '05-'), fase(ana, '04-'), fase(ana, '06-')
    infra = sorted({r['Programa'] for _s, _b, rs in tabelas(f0) for r in rs if r.get('Classe') == 'INFRAESTRUTURA'})
    corp = sorted({r['Programa'] for _s, _b, rs in tabelas(f0) for r in rs if 'Programa' in r and r.get('Classe') == 'CORPORATIVO'})
    regras = []
    for st, bt, rs in tabelas(f5):
        if st.startswith('Regras — ') and bt.startswith('Regras de '):
            p = st.split(' — ', 1)[1]
            for r in rs:
                r['programa'] = p
                regras.append(r)
    caixas = {}
    decisoes = []
    for st, bt, rs in tabelas(f2):
        if bt.startswith('Mapa de decisão — '):
            p = bt.split(' — ', 1)[1]
            import gerar_sql as Q_ef
            caixas.update(Q_ef.caixas_efetivas(rs))
            for r in rs:
                if r['Tipo'] == 'decisão':
                    r['programa'] = p
                    decisoes.append(r)
    sql, wh, chaves, rets, grav = {}, [], [], [], []
    for st, bt, rs in tabelas(f4):
        if bt.startswith('Comandos SQL sobre'):
            for r in rs:
                sql[r['Id']] = r
        elif bt.startswith('Condições SQL (WHERE)'):
            wh += rs
        elif bt.startswith('Chaves de busca'):
            chaves += rs
        elif bt.startswith('Colunas retornadas'):
            rets += rs
        elif bt.startswith('Gravações em'):
            grav += rs
    linha = defaultdict(list)
    for coll in (wh, chaves, rets, grav):
        for r in coll:
            linha[r.get('Comando', '')].append(r)
    alcance = defaultdict(list)
    try:
        for _st, bt, rs in tabelas(fase(ana, '07-')):
            if bt.startswith('Ramos alcançáveis por entry point e programa'):
                for r in rs:
                    alcance[r['Entry point']].append(r['Programa'])
    except SystemExit:
        pass
    return {'caixas': caixas, 'infra': infra, 'corp': corp, 'alcance': dict(alcance), 'decisoes': decisoes, 'regras': regras, 'sql': sql, 'where': wh, 'chaves': chaves, 'retornos': rets, 'gravacoes': grav, 'linha': linha}


class _PorCampo(dict):
    """Dicionário por nome de campo que ignora maiúsculas e o prefixo de copybook: a interpretação pode citar o campo com ou sem o nome do copybook."""
    @staticmethod
    def _k(c):
        return sem_copybook(str(c)).upper()

    def __setitem__(self, k, v):
        super().__setitem__(self._k(k), v)

    def __getitem__(self, k):
        return super().__getitem__(self._k(k))

    def get(self, k, d=None):
        return super().get(self._k(k), d)

    def __contains__(self, k):
        return super().__contains__(self._k(k))


def carregar_significados():
    """Significado dos campos e dos valores comparados nas decisões (interpretacao/*.json, chave 'significados'): [{campo, significado, valores: {valor: texto}, confianca}]."""
    out = _PorCampo()
    for f in sorted((BASE / 'interpretacao').glob('*.json')):
        for x in carregar(f).get('significados', []):
            out[x['campo'].upper()] = x
    return out


# Registradores que o ambiente de execução fornece (bloco de interface do CICS, área de comunicação do DB2): critério sobre eles é infraestrutura,
# não aparece nas tabelas "campos testados e valores comparados" nem precisa de significado.
CAMPO_INFRA = projeto_config.campo_infra()
SQLCODE_NEGOCIO = set(CONFIG['sqlcode_negocio'])   # SQLCODE de negócio: registro não encontrado e chave duplicada; qualquer outro critério sobre SQLCODE (falha genérica) é infraestrutura


def criterio_infra(a):
    c = a['campo'].upper()
    return bool(CAMPO_INFRA.match(c)) or (c == 'SQLCODE' and a['valor'] not in SQLCODE_NEGOCIO)


OPOSTO = {'=': '≠', '≠': '=', '<': '≥', '≥': '<', '>': '≤', '≤': '>', 'não está em': 'está em', 'está em': 'não está em', 'é': 'não é', 'não é': 'é'}


def inverter_criterio(a):
    """Critério `campo op valor` no ramo "não" da decisão: o operador oposto (indicador ligado vira desligado)."""
    if a['valor'] == 'verdadeiro (indicador ligado)':
        return {**a, 'op': '=' if a['op'] == '≠' else '=', 'valor': 'falso (indicador desligado)' if a['op'] == '=' else a['valor']}
    return {**a, 'op': OPOSTO.get(a['op'], a['op'])}


def _itens_nao_tecnicos(r):
    itens = partes(r['Condições (decisão → resultado)'])
    return [x for x in itens if '[técnica]' not in x.split('·')[0]] or itens


def _criterios(item):
    """Critérios (campo, operador, valor) de um item do caminho, já no sentido do ramo que a regra segue (ramo "não": o oposto de cada critério); sem os de infraestrutura."""
    sem_cod = item.split(' ', 1)[1] if ' ' in item else item
    cond, _s, resultado = sem_cod.rpartition(' → ')
    cond = cond or sem_cod
    nega = resultado.strip().startswith('Não')
    out = []
    for a in cc.atomos(cond):
        if nega:
            a = inverter_criterio(a)
        if not criterio_infra(a):
            out.append({**a, 'campo': a['campo'].upper()})
    return out


def campos_do_caminho(rs):
    """Todos os campos testados nas decisões do caminho completo das regras (as condições da evidência de cada regra determinística)."""
    return {a['campo'] for _p, r in rs for item in _itens_nao_tecnicos(r) for a in _criterios(item)}


def padroes_decisao(rs, extra=(), exigida=False):
    """Padrão das decisões de um grupo: {campo: {(operador, valor): {regras}}}, só por tokens das condições (cc.atomos). Entram os critérios envolvidos na regra: os da
    decisão que escolhe o ramo dela (a última não técnica) e os dos campos que a IA citou em `campos` do grupo (o nome da regra os menciona; vêm de outras decisões do caminho).
    `exigida` (IA): o nome diz o que deve valer, não o que dispara a regra; então vale o oposto de cada critério."""
    agg = defaultdict(lambda: defaultdict(set))
    extra = {sem_copybook(x).upper() for x in extra}
    for p, r in rs:
        itens = _itens_nao_tecnicos(r)
        for i, item in enumerate(itens):
            for a in _criterios(item):
                if i == len(itens) - 1 or sem_copybook(a['campo']).upper() in extra:
                    if exigida:
                        a = inverter_criterio(a)
                    agg[a['campo']][(a['op'], a['valor'])].add(p + ':' + r['Regra'])
    return agg


def tabela_padroes(gid, rs, sig, g=None):
    """Tabela "campos testados e valores comparados" (só os campos do critério decisivo de cada regra) com o significado dado pela interpretação; devolve (linhas, campos sem significado)."""
    g = g or {}
    agg = padroes_decisao(rs, g.get('campos', ()), g.get('condicao') == 'exigida')
    linhas, sem = [], []
    for campo in sorted(agg):
        comps = agg[campo]
        s_ = sig.get(campo)
        if not s_:
            sem.append(campo)
        vals = (s_ or {}).get('valores', {})
        vtxt = []
        for (_op, v), _rs in sorted(comps.items()):
            chave = v.strip("'")
            t = vals.get(chave) or vals.get(v)
            if t:
                vtxt.append(f'{v} = {t}')
        linhas.append((campo, '; '.join(f'{op} {v}' for (op, v) in sorted(comps)), len({x for rr_ in comps.values() for x in rr_}),
                       (s_ or {}).get('significado') or 'não identificado', '; '.join(vtxt) or '—', (s_ or {}).get('confianca', '—')))
    return linhas, sem


def filtrar(d):
    """(regras que entram, regras filtradas com motivo, programas de infraestrutura)."""
    entram, fora = [], []
    for r in d['regras']:
        if r['Escopo'] != 'negócio':   # o escopo vem da fase 6 (deterministic-rules); nada é inferido aqui
            fora.append((r['programa'], r, r['Motivo do escopo'] or 'escopo de infraestrutura'))
        else:
            entram.append((r['programa'], r))
    return entram, fora, d['infra']


def partes(t):
    """Quebra a lista de condições/efeitos de uma célula em itens (decisões Dnnn ou fluxos Fnnnn separados por ';' ou ' E ')."""
    t = re.sub(r' · status do comando[^·]*$', '', t)
    return [x.strip() for x in re.split(r'; | (?:E|OU) (?=(?:[A-Z0-9]+:)?D\d{3} )', t) if x.strip()]


def rastreio(d, entram, fora, resolvido, por_plat, resto):
    """Rastreio decisão (fase 5) -> regra determinística (fase 6) -> regra de negócio (grupo da IA), com o motivo de cada descarte.
    Retorna (decisões, regras, resumo). Tudo calculado dos relatórios e da interpretação; nenhum texto novo da IA."""
    destino = {}
    for _g, rs in resolvido:
        for p, r in rs:
            destino.setdefault(p + ':' + r['Regra'], {'grupos': [], 'tipo': 'regra de negócio', 'motivo': ''})['grupos'].append(_g['id'])
    for p, r, m in fora:
        destino[p + ':' + r['Regra']] = {'grupos': [], 'tipo': ('mecanismo implícito' if r['Escopo'] == 'mecanismos implícitos' else 'filtrada: fora da abrangência' if r['Escopo'] == 'fora da abrangência' else 'filtrada: infraestrutura'), 'motivo': m}
    for m, v in por_plat.items():
        for p, r in v:
            destino[p + ':' + r['Regra']] = {'grupos': [], 'tipo': 'plataforma', 'motivo': m}
    for p, r in resto:
        destino[p + ':' + r['Regra']] = {'grupos': [], 'tipo': 'sem classificação', 'motivo': 'regra de negócio (escopo da fase 6) que nenhuma regra reunida cobre'}
    usada_por = defaultdict(list)       # (programa, decisão) -> regras que a citam nas condições (fase 6)
    for r in d['regras']:
        for x in re.findall(r'(?:^|; | E | OU )(?:[A-Z0-9]+:)?(D\d{3}) ', r['Condições (decisão → resultado)']):
            usada_por[(r['programa'], x)].append(r['programa'] + ':' + r['Regra'])
    decs, incons = [], 0
    for x in d['decisoes']:
        p, cod = x['programa'], x['Código'].split(':')[-1]   # o código do relatório é PROGRAMA:Dnnn
        refs = [y.strip() for y in x['Regras que usam'].split(',') if y.strip()]
        refs = [y if ':' in y else p + ':' + y for y in refs]
        if set(refs) != set(usada_por.get((p, cod), [])):
            incons += 1
        ds = [destino.get(y) for y in refs if destino.get(y)]
        gs = sorted({g for t in ds for g in t['grupos']})
        if gs:
            sit, mot = 'regra de negócio', 'decide ' + str(len(refs)) + ' regra(s) determinística(s); ' + str(sum(1 for t in ds if t['grupos'])) + ' entram em regra de negócio'
        elif not refs:
            sit = 'descartada'
            mot = ('laço de repetição (PERFORM ... UNTIL): controla quantas vezes um trecho roda, não escolhe entre efeitos de negócio' if x['Condição ou comandos'].lstrip().startswith('PERFORM')
                   else 'nenhuma regra determinística a usa: nenhum caminho que passa por ela chega a um efeito de negócio decidido por ela (só mapeamento de campos ou efeito vindo de outra decisão)')
        elif any(t['tipo'] == 'sem classificação' for t in ds):
            sit, mot = 'sem classificação', 'regra de negócio sem grupo'
        elif any(t['tipo'] == 'mecanismo implícito' for t in ds):
            sit = 'mecanismo implícito'
            mot = '; '.join(f'{k}: {n} regra(s)' + (f' ({m})' if m else '') for (k, m), n in sorted(Counter((t['tipo'], t['motivo']) for t in ds).items()))
        else:
            sit = 'descartada'
            mot = '; '.join(f'{k}: {n} regra(s)' + (f' ({m})' if m else '') for (k, m), n in sorted(Counter((t['tipo'], t['motivo']) for t in ds).items()))
        decs.append({'programa': p, 'cod': cod, 'linha': x['Linha'], 'par': x['Parágrafo'], 'cond': x['Condição ou comandos'], 'exec': x['Execução'], 'refs': refs,
                     'sit': sit, 'motivo': mot, 'grupos': gs})
    regras = []
    for r in d['regras']:
        k = r['programa'] + ':' + r['Regra']
        t = destino.get(k, {'grupos': [], 'tipo': 'sem destino', 'motivo': ''})
        ds = sorted({x for x in re.findall(r'(?:^|; | E | OU )(?:[A-Z0-9]+:)?(D\d{3}) ', r['Condições (decisão → resultado)'])})
        segs = re.split(r' E (?=[A-Z0-9]+:D\d{3} )', r['Condições (decisão → resultado)'])
        decisiva = ''
        for sg in segs:
            m_ = re.match(r'(?:[A-Z0-9]+:)?(D\d{3}) ', sg)
            if m_ and '[técnica]' not in sg.split('·')[0]:
                decisiva = m_.group(1)
        regras.append({'programa': r['programa'], 'regra': r['Regra'], 'tipo': r['Tipo'], 'sub': r.get('Subtipo', ''), 'escopo': r['Escopo'],
                       'destino': t['tipo'], 'grupos': t['grupos'], 'motivo': t['motivo'], 'decisoes': ds, 'decisiva': decisiva,
                       'entry': [e.strip() for e in r['Entry points'].split(',') if e.strip()]})
    rinfo = {x['programa'] + ':' + x['regra']: x for x in regras}
    dinfo = {(x['programa'], x['cod']): x for x in decs}
    cruz, com_decisao = [], set()
    for x in decs:
        if not x['refs']:
            cruz.append({'p': x['programa'], 'd': x, 'r': None})
        for ref in x['refs']:
            com_decisao.add(ref)
            cruz.append({'p': x['programa'], 'd': x, 'r': rinfo.get(ref)})
    for k, r in rinfo.items():
        if k not in com_decisao:
            cruz.append({'p': r['programa'], 'd': None, 'r': r})
    return decs, regras, {'inconsistentes': incons, 'cruz': cruz}


def verificar(cita, blob):
    blob = sem_copybook(blob)
    return [c for c in cita if sem_copybook(c) not in blob]


def carregar_compartilhados():
    """Programas corporativos/compartilhados declarados na interpretação (00-categorias.json, 'programas_compartilhados')."""
    out = {}
    for f in sorted((BASE / 'interpretacao').glob('*.json')):
        for x in carregar(f).get('programas_compartilhados', []):
            out[x['programa']] = x['motivo']
    return out


CATEGORIAS_MECANISMO_VALIDACAO = set(CONFIG['categorias_mecanismo_validacao'])
CATS_TXT = ', '.join(sorted(CATEGORIAS_MECANISMO_VALIDACAO))   # regra de tipo validação só vira mecanismo por uma destas categorias (IA)


def verificar_nomes_e_retornos(d, grupos):
    """Regras de negócio (instâncias): (1) o nome não cita o programa nem parte do nome dele (o programa já está no id da regra); (2) o nome não traz código de retorno, de erro nem de mensagem e descreve a regra de forma positiva; não é genérico (menos de 4 palavras);
    (3) todas as regras determinísticas de uma regra de negócio devolvem o mesmo retorno (COD-RETORNO, COD-ERRO, COD-MENSAGEM): retornos diferentes são regras de negócio diferentes, com o nome dizendo a diferença."""
    erros = []
    progs = sorted({r['programa'] for r in d['regras']})
    partes = set()
    for p in progs:
        partes.add(p.upper())
        partes.update(x.upper() for x in re.findall(r'[A-Za-z]+|\d+', p) if len(x) >= 3 and not x.isdigit())
        if not p[-3:].isdigit():
            partes.add(p[-3:].upper())
    por = {r['programa'] + ':' + r['Regra']: r for r in d['regras']}
    for g in grupos:
        rs_ = [(por[x]['programa'], por[x]) for x in g['regras'] if x in por]
        if g.get('condicao', 'gatilho') not in ('gatilho', 'exigida'):
            erros.append(f'{g["id"]}: "condicao" deve ser "gatilho" ou "exigida"')
        fora_ = sorted({sem_copybook(c).upper() for c in g.get('campos', [])} - {sem_copybook(c).upper() for c in campos_do_caminho(rs_)})
        if fora_:
            erros.append(f'{g["id"]}: "campos" cita campo que nenhuma condição do caminho das regras testa: {", ".join(fora_)}')
        achados = sorted({t for t in re.findall(r'[A-Za-z0-9]+', g['titulo']) if t.upper() in partes})
        if achados:
            erros.append(f'{g["id"]}: o nome cita o programa ou parte do nome dele ({", ".join(achados)}); tire a referência: o programa já está no id da regra')
        if len(g['titulo'].split()) < 4:
            erros.append(f'{g["id"]}: nome genérico ("{g["titulo"]}"); use as condições para dizer qual regra é')
        rets = {}
        for ref in g['regras']:
            t = retornos(por[ref]) if ref in por else None
            if t:
                rets.setdefault(t, []).append(ref)
        lits = {x.strip("'") for t in rets for x in t if x.strip("'") not in ('', 'ZEROS', 'SPACES', '0')}
        cod = sorted(x for x in lits if re.search(r'(?<![\w-])' + re.escape(x) + r'(?![\w-])', g['titulo']))
        if cod:
            erros.append(f'{g["id"]}: o nome traz código de retorno, de erro ou de mensagem ({", ".join(cod)}); descreva a regra de forma positiva, sem os códigos (por exemplo, "parcela inicial deve ser numérica")')
        if len(rets) > 1:
            erros.append(f'{g["id"]}: as regras devolvem {len(rets)} retornos diferentes ({"; ".join(", ".join(t) + " em " + ",".join(r.split(":")[1] for r in rs) for t, rs in rets.items())}); separe em uma regra de negócio por retorno')
    return erros


def carregar_mecanismos():
    """Mecanismos reconhecidos pela IA (interpretacao/*.json, chave 'mecanismos'): [{regras: ['PROG:Rnnn'], titulo, motivo, confianca}]. A IA julga, regra a regra, o que é só encanamento
    (repasse de retorno, preparo de chamada, validação de continuação de paginação...) e não decisão de negócio; nada disso é fixo no script."""
    out = {}
    for f in sorted((BASE / 'interpretacao').glob('*.json')):
        for x in carregar(f).get('mecanismos', []):
            for ref in x['regras']:
                out[ref] = x
    return out


def aplicar_mecanismos(d, grupos):
    """Passa para o escopo 'mecanismos implícitos' as regras que a IA julgou mecanismo (com o motivo dela). Erros: regra inexistente, regra de infraestrutura, regra de tipo validação, regra também citada
    em regra de negócio, ou motivo vazio."""
    mec, erros = carregar_mecanismos(), []
    por_ref = {r['programa'] + ':' + r['Regra']: r for r in d['regras']}
    citadas = {ref for g in grupos for ref in g['regras']}
    for ref, x in mec.items():
        r = por_ref.get(ref)
        if r is None:
            erros.append(f'mecanismo da IA cita regra inexistente: {ref}')
        elif r['Escopo'] != 'negócio':
            erros.append(f'mecanismo da IA cita regra que a fase 6 já filtrou ({r["Escopo"]}): {ref}')
        elif r['Tipo'] == 'validação' and x.get('categoria') not in CATEGORIAS_MECANISMO_VALIDACAO:
            erros.append(f'mecanismo da IA cita regra de tipo validação (validação nunca é descartada, nem pela IA, exceto as categorias {CATS_TXT}, que levam "categoria": "<essa>"): {ref}')
        elif ref in citadas:
            erros.append(f'regra julgada mecanismo pela IA e também citada em regra de negócio: {ref}')
        elif not (x.get('motivo') or '').strip():
            erros.append(f'mecanismo da IA sem motivo: {ref}')
        else:
            r['Escopo'] = 'mecanismos implícitos'
            r['Motivo do escopo'] = 'julgamento da IA: ' + x['motivo'].strip()
    return erros


def carregar_interp():
    """Junta os arquivos interpretacao/*.json (categorias e grupos de regras)."""
    cats, grupos, plat, aviso = [], [], [], ''
    for f in sorted((BASE / 'interpretacao').glob('*.json')):
        x = carregar(f)
        aviso = x.get('_aviso', aviso)
        cats += x.get('categorias', [])
        grupos += x.get('grupos', [])
    return aviso, cats, grupos, plat


def regras_dinamicas(mp, caixas=None):
    """Cada comando SQL estático `<SERVIÇO>-Qnn` que substitui uma consulta dinâmica (mapeamento SQL, fase 10) vira uma regra determinística sintética do programa que executa o serviço
    (`SERVICO:SERVICO-Qnn`, tipo consulta de dados, escopo negócio): as regras de negócio (prompt 1) são escritas também a partir dos comandos dinâmicos e citam `SERVICO:SERVICO-Qnn` em `regras`.
    A linha traz as mesmas colunas das regras da fase 6; o texto do comando, o propósito, as colunas e as condições do mapeamento são a evidência dos literais citados."""
    out = []
    if not mp:
        return out
    for x in mp['consultas_dinamicas']:
        it = x.get('internalizacao') or {}
        for cod, quando, sql in mp['_cmd_de'][x['id']]:
            escopo, motivo = 'negócio', 'comando SQL estático que substitui a consulta dinâmica (mapeamento SQL, fase 10)'
            if caixas is not None:   # como nas regras determinísticas: só entra regra que a execução dinâmica alcançou (a caixa do mapa de decisão que executa o caso)
                import gerar_sql as Q_
                cx_ = Q_.caixas_do_caso(x.get('internalizacao') or {})
                if not any(caixas.get(cx_.get(c_, '')) == 'executado' for c_ in mp['_q_lista'][cod]):
                    escopo, motivo = 'fora da abrangência', 'fora da abrangência: nenhum cenário de execução dinâmica alcança a caixa ' + ', '.join(sorted({cx_.get(c_, '') for c_ in mp['_q_lista'][cod]})) + ' que executa ' + cod
            cols = '; '.join(f'{c["coluna"]} ({c["posicao"]})' for c in it.get('colunas_select') or [])
            whs = '; '.join(f'{w["coluna"]} {w["operador"]} {w["parametro"]} (para: {w.get("para") or "comando principal"})' for w in it.get('condicoes_where') or [])
            ef = f'{sql} · quando: {quando} · consulta dinâmica {x["id"]} ({x["titulo"]}) · propósito: {it.get("proposito", "")}' + (f' · colunas: {cols}' if cols else '') + (f' · condições: {whs}' if whs else '')
            tabs = ', '.join(t['nome'] for t in x['tabelas'])
            out.append({'programa': x['servico'], 'Regra': cod, 'Decisões': '', 'Tipo': 'consulta de dados', 'Subtipo': 'consulta dinâmica internalizada', 'Escopo': escopo,
                        'Motivo do escopo': motivo, 'Critério': '', 'Sinais': '', 'Encerra': '',
                        'Condições (decisão → resultado)': f'consulta dinâmica {x["id"]}: executada pelo serviço quando chamado, com a tabela {tabs} informada em {x["parametro"]}',
                        'Campos testados: papel e origem': '', 'Efeitos de negócio (fluxo, natureza)': ef, 'Tabelas gravadas': '', 'Programas chamados': '', 'Consultas que alimentam a condição': '',
                        'Comandos SQL na linhagem': '', 'Componentes dos nomes': '', 'Entry points': ', '.join(x['usada_por']), '_dinamica': True, 'consulta': x['id'], 'quando': quando})
    return out


def expandir_por_programa(grupos, entradas_da_regra, compartilhados=(), corporativos=()):
    """Uma regra de negócio pertence a um único programa (e, por ele, ao entry point dele) e seu id é sempre '<código>.<programa>', para mostrar a origem. Uma regra reunida cujas regras determinísticas estão em mais de um
    programa vira uma regra de negócio por programa, com o texto, os literais e as lacunas de 'programas' (interpretação).
    Programas da classe CORPORATIVO (fase 0, 'corporativos') nunca se juntam a outro programa: cada um é uma funcionalidade corporativa com as suas regras.
    Exceção: regras de programas corporativos/compartilhados (declarados em 'compartilhados' na interpretação) ficam juntas numa só regra de negócio
    (id '<id>.<programas>' quando o grupo também tem regras de outros programas) e podem servir a vários entry points.
    Cada instância traz 'entry' (os entry points que as regras alcançam, separados por vírgula). 'entradas_da_regra': 'PROG:Rnnn' -> entry points.
    Retorna (instâncias, erros)."""
    out, erros = [], []
    for g in grupos:
        por = defaultdict(list)
        for ref in g['regras']:
            p = ref.split(':')[0]
            por[p if (p not in compartilhados or p in corporativos) else 'compartilhado'].append(ref)   # programa corporativo é uma funcionalidade própria: nunca se junta a outro programa
        unidades = {}
        for k, refs in por.items():
            chave = k if k != 'compartilhado' else '+'.join(sorted({r.split(':')[0] for r in refs}))
            unidades[chave] = refs
        ov = g.get('programas', {})

        def entry_de(refs):
            return ', '.join(sorted({e for r in refs for e in entradas_da_regra.get(r, [])}))
        if len(unidades) == 1:
            u = next(iter(unidades))
            out.append({**{k: v for k, v in g.items() if k != 'programas'}, 'id': f'{g["id"]}.{u}', 'base': g['id'], 'entry': entry_de(g['regras'])})
            continue
        for u in sorted(unidades):
            if u not in ov:
                erros.append(f'{g["id"]}: as regras estão em {len(unidades)} programas; falta o texto de "{u}" em "programas" na interpretação')
                continue
            refs = unidades[u]
            progs = {r.split(':')[0] for r in refs}
            lin = ov[u].get('lineage', [i for i in g.get('lineage', []) if i.split('@')[0] in progs])
            out.append({**{k: v for k, v in g.items() if k != 'programas'}, **ov[u], 'id': f'{g["id"]}.{u}', 'base': g['id'], 'entry': entry_de(refs), 'regras': refs, 'lineage': lin})
        for u in ov:
            if u not in unidades:
                erros.append(f'{g["id"]}: "programas" cita {u}, que nenhuma das regras reúne')
    return out, erros


def funcionalidades_por_grupo(instancias=()):
    """Regra de negócio (V01, C04.PROGA...) -> funcionalidades do relatório de fluxos (entry point) que a citam; vazio se o relatório não existe.
    O id base citado por uma funcionalidade vale para as regras de negócio daquele id que alcançam o entry point dela."""
    f = BASE / 'interpretacao-fluxos' / 'funcionalidades.json'
    out = defaultdict(list)
    if f.exists():
        d = carregar(f)
        for x in d['funcionalidades']:
            for g in x['grupos']:
                ids = ids_do_entry(g, x['entry'], instancias) if 'entry' in x else ids_do_programa(g, x['programa'], instancias)
                for i in ids:
                    out[i].append((x['id'], x['nome']))
    return out


def grupos_filtrados():
    """Ids base das regras de negócio que a IA filtrou das funcionalidades (chaves filtro_* de interpretacao-fluxos/funcionalidades.json): têm destino registrado na seção 'filtros' do relatório de fluxos."""
    f = BASE / 'interpretacao-fluxos' / 'funcionalidades.json'
    out = set()
    if f.exists():
        d = carregar(f)
        for k, v in d.items():
            if k.startswith('filtro') and isinstance(v, dict):
                out |= set(v.get('grupos', []))
    return out


def ids_do_entry(base, ep, instancias):
    """Ids das regras de negócio de um id base que alcançam o entry point (se não há instâncias, o próprio id)."""
    achou = [i['id'] for i in instancias if i['base'] == base and ep in [e.strip() for e in i['entry'].split(',')]]
    return achou or [base]


def ids_do_programa(base, prog, instancias):
    """Ids das regras de negócio de um id base cujas regras determinísticas estão no programa (funcionalidade de programa corporativo)."""
    achou = [i['id'] for i in instancias if i['base'] == base and any(r.split(':')[0] == prog for r in i['regras'])]
    return achou or [base]


def links_func(lst):
    return ' '.join(f'<a href="business-flows.html#{E(i)}" title="{E(n)}">{E(i)}</a>' for i, n in lst) or '—'


def texto_regra(r):
    return json.dumps(r, ensure_ascii=False)


def retornos(r):
    """(retorno, erro, mensagem) atribuídos pelos efeitos de uma regra, quando existem (lidos do texto do relatório)."""
    v = {}
    for k in ('RETORNO', 'ERRO', 'MENSAGEM'):
        f = re.findall(r'COD-' + k + r'[^=;]*= ([^;(]+?)(?: \(linha|;|$)', r['Efeitos de negócio (fluxo, natureza)'])
        if f:
            v[k] = f[-1].strip()
    return (v.get('RETORNO', ''), v.get('ERRO', ''), v.get('MENSAGEM', '')) if v else None


def classificar_plataforma(entram, atribuidas, plat):
    """Regras de negócio (escopo da fase 6) sem grupo: ficam sem classificação; não há mais seletor de plataforma, o escopo não é inferido aqui."""
    sobra = [(p, r) for p, r in entram if p + ':' + r['Regra'] not in atribuidas]
    por, resto = defaultdict(list), []
    for p, r in sobra:
        efs = r['Efeitos de negócio (fluxo, natureza)']
        cds = r['Condições (decisão → resultado)']
        for s in plat:
            if any(x in efs for x in s.get('efeito_contem', [])) or any(x in cds for x in s.get('condicao_contem', [])):
                por[s['motivo']].append((p, r))
                break
        else:
            resto.append((p, r))
    return por, resto


def escrever(saida, nome, modelo):
    """Grava <saida>/<nome>/human/report.html e <saida>/<nome>/ia/report.json a partir do mesmo modelo (como as fases da análise)."""
    modelo['phase'] = nome
    if nome.startswith(('10 ', '11 ', '12 ')):   # a rastreabilidade (13) fica como está; nas interpretações os atributos aparecem sem o nome do copybook
        modelo = limpar_copybooks(modelo)
    pasta = Path(saida) / nome
    (pasta / 'ia').mkdir(parents=True, exist_ok=True)
    (pasta / 'ia' / 'report.json').write_text(json.dumps(modelo, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
    rr.gravar_html(pasta, modelo)   # etapa só com a visão para IA (rr.SO_IA) não tem página humana
    (pasta / 'ia' / 'schema.json').write_text(json.dumps({'step': nome, 'report_model': 'report.json', 'human_projection': '../human/report.html',
                                                          'equivalence': 'report.json e report.html vêm do mesmo modelo de visão: mesmas seções, tabelas e valores'}, indent=1, ensure_ascii=False), encoding='utf-8')
    rr.reindexar(saida)


def modelo(d, cats, grupos, plat, entram, fora, infra_progs):
    sig = carregar_significados()
    fg = funcionalidades_por_grupo(grupos)

    def func_links(gid):
        return rm.with_links('', [rm.link(i, '12 - business-flows', i) for i, _n in fg.get(gid, [])])
    ids = {p + ':' + r['Regra']: (p, r) for p, r in entram}
    ids.update({r['programa'] + ':' + r['Regra']: (r['programa'], r) for r in DIN})
    filtradas = {p + ':' + r['Regra'] for p, r, _m in fora}
    erros, resolvido = [], []
    for g in grupos:
        rs = []
        for ref in g['regras']:
            if ref in ids:
                rs.append(ids[ref])
            else:
                erros.append(f'{g["id"]}: {ref} ' + ('foi filtrada como infraestrutura' if ref in filtradas else 'não existe nos relatórios'))
        resolvido.append((g, rs))
    if erros:
        raise SystemExit('referências inválidas na interpretação:\n  ' + '\n  '.join(erros))
    atribuidas = {p + ':' + r['Regra'] for _g, rs in resolvido for p, r in rs}
    por_plat, resto = classificar_plataforma(entram, atribuidas, plat)
    n_plat = sum(len(v) for v in por_plat.values())
    decs, regs_t, rinfo = rastreio(d, entram, fora, resolvido, por_plat, resto)
    tot = len(entram) + len(fora)
    secoes = []
    linhas = []
    for c in cats:
        gs = [(g, rs) for g, rs in resolvido if g['cat'] == c['id']]
        linhas.append((c['nome'], len({p + r['Regra'] for _g, rs in gs for p, r in rs}), f'{len(gs)} regras de negócio reunidas'))
    if resto:
        linhas.append(('Sem classificação', len(resto), ', '.join(p + ':' + r['Regra'] for p, r in resto)))
    def motivo_curto(m):   # o motivo do escopo resumido: os detalhes (decisão não alcançada, justificativa da IA) ficam na fase 6
        if m.startswith('fora da abrangência'):
            return 'decisão que nenhum cenário da análise dinâmica alcança'
        if m.startswith('julgamento da IA'):
            return 'mecanismo técnico, não regra de negócio (julgamento da IA)'
        if 'INFRAESTRUTURA' in m:
            return f'programa de infraestrutura na fase 0 ({", ".join(infra_progs)})' if infra_progs else 'programa de infraestrutura na fase 0'
        return m
    por_motivo = defaultdict(Counter)
    for _p, r, m in fora:
        por_motivo[motivo_curto(m)][r['Tipo']] += 1
    t_fora = [(mo, sum(c.values()), ', '.join(f'{t} {n}' for t, n in c.most_common())) for mo, c in sorted(por_motivo.items(), key=lambda kv: -sum(kv[1].values()))]
    secoes.append(rm.S('cobertura', 'Cobertura', [
        rm.X(f'{tot} regras determinísticas no total. {len(fora)} foram filtradas por serem infraestrutura. Das {len(entram)} de escopo negócio: {len(atribuidas)} sustentam as regras de negócio abaixo, '
             f'{len(resto)} ficaram sem classificação.'),
        rm.T('Destino das regras determinísticas de negócio', ['Destino', 'Regras determinísticas', 'Observação'], linhas,
             note='Categoria das regras de negócio, quantas regras determinísticas de escopo negócio ela reúne e em quantas regras de negócio.'),
        rm.T('Regras determinísticas filtradas, por motivo', ['Motivo', 'Regras', 'Tipos de regra'], t_fora,
             note=f'As {len(fora)} regras de escopo infraestrutura, que não viram regra de negócio. O motivo de cada uma, com a decisão ou a justificativa, está nas regras determinísticas (fase 6).')]))
    cartoes, falhas, idx, ids_idx = {}, 0, [], []
    for g, rs in resolvido:
        blob = ''.join(texto_regra(r) for _p, r in rs) + ''.join(json.dumps(x, ensure_ascii=False) for i in g.get('lineage', []) for x in ([d['sql'][i]] + d['linha'].get(i, [])) if i in d['sql'])
        faltam = verificar(g['cita'], blob)
        falhas += len(faltam)
        if faltam:
            print(f'  literal sem evidência em {g["id"]}: ' + ', '.join(faltam))
        cartoes[g['id']] = (g, rs, faltam)
        idx.append((f'{g["id"]} {g["titulo"]}', g.get('entry') or '—', g['cat'], ', '.join(sorted({p for p, _r in rs})), len(rs), g['confianca'], func_links(g['id'])))
        ids_idx.append('resumo-' + g['id'])   # âncora própria da linha do resumo: o id da regra de negócio aponta para a seção da regra (links de outros relatórios)
    todos, sem_sig, uso_campo = set(), set(), defaultdict(set)
    for g, rs in resolvido:
        _l, sem = tabela_padroes(g['id'], rs, sig, g)
        sem_sig |= set(sem)
        for campo_ in padroes_decisao(rs, g.get('campos', ()), g.get('condicao') == 'exigida'):
            todos.add(campo_)
            uso_campo[campo_].add(g['id'])
    for c_ in sorted(set(sig) - {sem_copybook(t).upper() for t in todos}):
        print(f'  significado para campo que nenhuma regra de negócio testa: {c_}')
        falhas += 1
    if sem_sig:
        print(f'  campos testados sem significado: {len(sem_sig)}: ' + ', '.join(sorted(sem_sig)))
    linhas_s = []
    for campo_ in sorted(todos):
        s_ = sig.get(campo_, {})
        linhas_s.append((campo_, s_.get('significado') or 'não identificado', '; '.join(f'{k} = {v}' for k, v in (s_.get('valores') or {}).items()) or '—', s_.get('confianca', '—'),
                         rm.with_links('', [rm.link(x, '11 - business-rules', x) for x in sorted(uso_campo[campo_])])))
    secoes.append(rm.S('significados', 'Significado dos campos e valores das decisões', [
        rm.X(f'{len(todos)} campos são testados pelas regras de negócio; {len(todos) - len(sem_sig)} têm significado na interpretação e {len(sem_sig)} ficaram como "não identificado". O significado é dedução da IA pelo nome do campo, pelos valores comparados e pelo uso nas regras e nos efeitos; a coluna de confiança diz quanto a evidência sustenta.'),
        rm.T('Campos testados nas decisões', ['Campo', 'Significado', 'Valores', 'Confiança', 'Regras de negócio que o testam'], linhas_s)]))
    secoes.append(rm.S('regras', 'Regras de negócio', [rm.T('Regras de negócio reunidas', ['Regra de negócio', 'Entry points', 'Categoria', 'Programas', 'Regras determinísticas', 'Confiança', 'Funcionalidades'], idx, ids=ids_idx)],
                       'Cada regra de negócio pertence a um único programa: quando o mesmo comportamento aparece em vários programas, há uma regra de negócio por programa (id com o sufixo do programa); a exceção são os programas corporativos/compartilhados, cujas regras ficam juntas e podem servir a vários entry points. Reúne as regras determinísticas que dizem a mesma coisa nesse entry point; a seção de cada uma traz o texto, a evidência (condições e efeitos) e a linhagem consultada.'))
    for c in cats:
        for g in [g for g, _rs in resolvido if g['cat'] == c['id']]:
            _g, rs, faltam = cartoes[g['id']]
            progs = sorted({p for p, _r in rs})
            blocos = [rm.X(g['texto']),
                      rm.X(f'entry points: {g.get("entry") or "—"} · programas: {", ".join(progs)} · {len(rs)} regras determinísticas · confiança: {g["confianca"]} · literais citados conferidos: ' + ('ok' if not faltam else 'faltam: ' + ', '.join(faltam)))]
            rets = [(p, r, retornos(r)) for p, r in rs if retornos(r)]
            if rets:
                blocos.append(rm.T(f'{g["id"]}: COD-RETORNO, COD-ERRO e COD-MENSAGEM', ['Regra', 'COD-RETORNO', 'COD-ERRO', 'COD-MENSAGEM'], [(f'{p}:{r["Regra"]}', t[0], t[1], t[2]) for p, r, t in rets]))
            linhas_p, _sem = tabela_padroes(g['id'], rs, sig, g)
            if linhas_p:
                blocos.append(rm.T(f'{g["id"]}: campos testados e valores comparados', ['Campo', 'Comparações (operador e valor)', 'Regras', 'Significado do campo', 'Significado dos valores', 'Confiança'], linhas_p,
                                   'Campos e valores vêm das condições das regras (tokens); o significado vem da interpretação (IA) pelo nome do campo, pelos valores comparados e pelo uso nas regras e nos efeitos; "não identificado" quando as evidências não bastam.'))
            ev = []
            for p, r in rs:
                cs = ' | '.join(partes(r['Condições (decisão → resultado)'])) or '(sem condição de negócio)'
                efs = ' | '.join(partes(r['Efeitos de negócio (fluxo, natureza)']) + [f'{k}: {r[k]}' for k in ('Tabelas gravadas', 'Programas chamados', 'Comandos SQL na linhagem') if r[k]])
                ev.append((f'{p}:{r["Regra"]}', r['Tipo'], cs, efs))
            blocos.append(rm.T(f'{g["id"]}: evidência, condições e efeitos de cada regra determinística', ['Regra', 'Tipo', 'Condições (relatório da fase 6)', 'Efeitos e comandos'], ev))
            if g.get('lineage'):
                lin = []
                for i in g['lineage']:
                    if i in d['sql']:
                        sq = d['sql'][i]
                        lin.append((i, sq['Comando'], sq['Cursor'], sq['Linha'], sum(1 for x in d['where'] if x['Comando'] == i), sum(1 for x in d['retornos'] if x['Comando'] == i), sq['SQL']))
                    else:
                        lin.append((i, 'id não encontrado nos relatórios de linhagem', '', '', '', '', ''))
                blocos.append(rm.T(f'{g["id"]}: linhagem consultada', ['Id', 'Comando', 'Cursor', 'Linha', 'Predicados no WHERE', 'Colunas retornadas', 'SQL'], lin))
            if g['lacunas']:
                blocos.append(rm.X(' | '.join(g['lacunas']), title=f'{g["id"]}: lacunas'))
            secoes.append(rm.S(g['id'], f'{g["id"]} · {g["titulo"]}', blocos, f'{c["nome"]}: {c["desc"]}'))
    uso = defaultdict(lambda: [set(), set(), set()])
    for g, rs in resolvido:
        for _p, r in rs:
            for i in re.findall(r'[A-Z0-9]+@\d+:[A-Z0-9_]+', r['Comandos SQL na linhagem'] + ' ' + r['Efeitos de negócio (fluxo, natureza)']):
                sq = d['sql'].get(i)
                if sq:
                    k = 1 if sq['Comando'].split()[0] in ('INSERT', 'UPDATE', 'DELETE', 'MERGE') else 0
                    uso[i.split(':')[1]][k].add(i)
                    uso[i.split(':')[1]][2].add(g['id'])
    secoes.append(rm.S('dados', 'Dados tocados pelas regras', [rm.T('Comandos por tabela nos grupos de regras', ['Tabela', 'Comandos de consulta', 'Comandos de gravação', 'Regras de negócio'],
                                                                   [(t, len(l), len(w), ', '.join(sorted(gs))) for t, (l, w, gs) in sorted(uso.items())])],
                       'Contagem de comandos por tabela nas regras de negócio, extraída dos relatórios.'))
    cards = [rm.card('regras determinísticas', tot), rm.card('filtradas (infraestrutura)', sum(1 for f in fora if f[1]['Escopo'] not in ('mecanismos implícitos', 'fora da abrangência'))), rm.card('fora da abrangência', sum(1 for f in fora if f[1]['Escopo'] == 'fora da abrangência')), rm.card('mecanismos implícitos', sum(1 for f in fora if f[1]['Escopo'] == 'mecanismos implícitos')), rm.card('em regra de negócio', len(atribuidas)),
             rm.card('regras de negócio', len(grupos)), rm.card('decisões', len(decs))]
    rastro = modelo_rastreio(decs, regs_t, rinfo, grupos, atribuidas, fg, d)
    return rm.model('Regras de negócio', 'Regras de negócio reunidas a partir das regras determinísticas. A rastreabilidade decisão → regra determinística → regra de negócio → funcionalidade está no relatório da fase 13 (Rastreabilidade).', cards, secoes), falhas, len(atribuidas), n_plat, resto, rastro


COR_TRACO = [('Decisão', '#0072B2'), ('Regra determinística', '#1E8E3E'), ('Regra de negócio', '#F28C00'), ('Funcionalidade', '#D32F2F')]


def ordenar_colunas(cols, arestas, passes=24):
    """Ordem dos nós em cada coluna que reduz os cruzamentos entre colunas vizinhas: varreduras de baricentro (média da posição dos vizinhos), da esquerda para a direita e de volta.
    cols = [[ids na ordem inicial]...]; arestas = [(de, para)] entre colunas vizinhas. Determinístico (empates pela ordem inicial)."""
    viz = defaultdict(list)
    for a, b in arestas:
        viz[a].append(b)
        viz[b].append(a)
    col_de = {n: k for k, c in enumerate(cols) for n in c}
    pos = {n: i for c in cols for i, n in enumerate(c)}
    for t in range(passes):
        ordem = range(1, len(cols)) if t % 2 == 0 else range(len(cols) - 2, -1, -1)
        for k in ordem:
            ref = k - 1 if t % 2 == 0 else k + 1
            def bary(n, k=k, ref=ref):
                v = [pos[m] / max(1, len(cols[col_de[m]])) for m in viz[n] if col_de[m] == ref]
                return sum(v) / len(v) if v else pos[n] / max(1, len(cols[k]))
            cols[k] = sorted(cols[k], key=lambda n: (bary(n), pos[n]))
            for i, n in enumerate(cols[k]):
                pos[n] = i
    return cols


def cruzamentos(cols, arestas):
    """Número de cruzamentos de arestas entre colunas vizinhas na ordem dada (para conferir a ordenação)."""
    pos = {n: i for c in cols for i, n in enumerate(c)}
    col_de = {n: k for k, c in enumerate(cols) for n in c}
    n = 0
    for k in range(len(cols) - 1):
        es = [(pos[a], pos[b]) for a, b in arestas if col_de[a] == k and col_de[b] == k + 1]
        n += sum(1 for i in range(len(es)) for j in range(i + 1, len(es)) if (es[i][0] - es[j][0]) * (es[i][1] - es[j][1]) < 0)
    return n


def carregar_funcionalidades():
    """Funcionalidades da interpretação de fluxos (id, nome, entry ou programa), na ordem do arquivo; vazio se o relatório de fluxos não existe."""
    f = BASE / 'interpretacao-fluxos' / 'funcionalidades.json'
    return [x for x in carregar(f)['funcionalidades']] if f.exists() else []


def curto_motivo(x):
    """Motivo curto (para o nó cinza do diagrama) de uma decisão ou regra que não chega a regra de negócio; o motivo completo vai no detalhe e na tabela."""
    m = x['motivo']
    if 'destino' in x:
        return x['destino']
    if m.startswith('laço'):
        return 'laço de repetição'
    if m.startswith('nenhuma regra'):
        return 'nenhuma regra a usa'
    if x['sit'] == 'mecanismo implícito':
        return 'só mecanismo implícito'
    if 'infraestrutura' in m:
        return 'só infraestrutura'
    return x['sit']


def alcance_funcionalidade(f, regs_t, d):
    """Programas e regras que a funcionalidade alcança: a de programa corporativo, o próprio programa; a de entry point, os programas do fluxo dele (fase 7 e regras que o citam) sem os corporativos."""
    corp = set(d['corp'])
    if f.get('programa'):
        progs = {f['programa']}
        regras = [r for r in regs_t if r['programa'] == f['programa']]
    else:
        regras = [r for r in regs_t if f['entry'] in r['entry'] and r['programa'] not in corp]
        progs = ({r['programa'] for r in regras} | set(d.get('alcance', {}).get(f['entry'], []))) - corp
        regras = [r for r in regs_t if r['programa'] in progs and (f['entry'] in r['entry'] or not r['entry'])]
    return progs, regras


def grafo_funcionalidade(f, progs, regras, decs, grupos, fg, titulo_grupo):
    """Diagrama de 4 colunas da funcionalidade com TODAS as decisões dos programas dela e TODAS as regras determinísticas que ela alcança: decisão → regra determinística → regra de negócio → funcionalidade.
    O que não chega a regra de negócio aparece em cinza, com o motivo; a decisão que escolhe o ramo da regra liga em linha cheia e as de guarda do caminho em linha tracejada."""
    fid = f['id']
    nos = {0: {}, 1: {}, 2: {}, 3: {fid: {'id': 'F:' + fid, 'label': fid, 'sub': f['nome'], 'col': 3, 'detail': f'{fid}: {f["nome"]}'}}}
    ar, guarda = set(), set()
    ds = {(x['programa'], x['cod']): x for x in decs if x['programa'] in progs}
    for k, x in ds.items():
        did = k[0] + ':' + k[1]
        cinza = x['sit'] != 'regra de negócio'
        nos[0][did] = {'id': 'D:' + did, 'label': did, 'sub': ('descartada: ' + curto_motivo(x)) if cinza else x['cond'], 'col': 0, 'inactive': cinza,
                       'detail': f'{did} linha {x["linha"]}: {x["cond"]}' + (f' — {x["sit"]}: {x["motivo"]}' if cinza else '')}
    for r in regras:
        rid = r['programa'] + ':' + r['regra']
        cinza = r['destino'] != 'regra de negócio'
        nos[1][rid] = {'id': 'R:' + rid, 'label': rid, 'sub': ('descartada: ' + curto_motivo(r)) if cinza else r['tipo'], 'col': 1, 'inactive': cinza,
                       'detail': f'{rid} ({r["tipo"]}, {r["escopo"]})' + (f' — {r["destino"]}: {r["motivo"]}' if cinza else '')}
        for dc in r['decisoes']:
            if (r['programa'], dc) in ds:
                e = ('D:' + r['programa'] + ':' + dc, 'R:' + rid)
                ar.add(e)
                if dc != r['decisiva']:
                    guarda.add(e)
        for g in r['grupos']:
            if not fg or any(i == fid for i, _n in fg.get(g, [])):
                nos[2][g] = {'id': 'B:' + g, 'label': g, 'sub': titulo_grupo.get(g, ''), 'col': 2, 'detail': f'{g}: {titulo_grupo.get(g, "")}'}
                ar.add(('R:' + rid, 'B:' + g))
                ar.add(('B:' + g, 'F:' + fid))
    cols = [sorted(nos[k].values(), key=lambda x: x['id']) for k in range(4)]
    base = sorted(e for e in ar if e not in guarda)
    ordem = ordenar_colunas([[n['id'] for n in c] for c in cols], base)
    por_id = {n['id']: n for c in cols for n in c}
    return [por_id[i] for c in ordem for i in c], sorted(ar), guarda, cruzamentos(ordem, base)


def tabela_funcionalidade(f, progs, regras, decs, ar, fg):
    """Tabela do diagrama: uma linha por vínculo decisão × regra determinística (e por decisão ou regra sem par), com a regra de negócio, a situação, o motivo e o vínculo não feito."""
    fid = f['id']
    ds = {(x['programa'], x['cod']): x for x in decs if x['programa'] in progs}
    rows, vistas = [], set()
    com_regra = set()
    def bn(r):
        gs = [g for g in r['grupos'] if not fg or any(i == fid for i, _n in fg.get(g, []))]
        return (rm.with_links('', [rm.link(g, '11 - business-rules', g) for g in gs]), rm.with_links('', [rm.link(fid, '12 - business-flows', fid)])) if gs else ('—', '—')
    def nao_feito(d, r):
        out = []
        if d is None:
            out.append('decisão → regra determinística: a regra não tem decisão nas condições')
        elif r is None:
            out.append('decisão → regra determinística: nenhuma regra determinística usa esta decisão')
        if r is not None and r['destino'] != 'regra de negócio':
            out.append('regra determinística → regra de negócio: ' + r['destino'])
        return '; '.join(out) or 'nenhum'
    for r in regras:
        pares = [dc for dc in r['decisoes'] if (r['programa'], dc) in ds]
        for dc in pares or [None]:
            d = ds[(r['programa'], dc)] if dc else None
            if d:
                com_regra.add((r['programa'], dc))
            b, ff = bn(r)
            sit = 'vínculo completo' if r['destino'] == 'regra de negócio' and d is not None and d['sit'] == 'regra de negócio' else 'descartada'
            mot = '; '.join(x for x in (('decisão: ' + d['motivo']) if d and d['sit'] != 'regra de negócio' else '', ('regra: ' + r['destino'] + (' — ' + r['motivo'] if r['motivo'] else '')) if r['destino'] != 'regra de negócio' else '') if x)
            rows.append(((d['programa'] + ':' + d['cod']) if d else '—', r['programa'] + ':' + r['regra'], b, ff, sit, mot or '—', nao_feito(d, r)))
    for (p, cod), d in sorted(ds.items()):
        if (p, cod) not in com_regra:
            rows.append((p + ':' + cod, '—', '—', '—', 'descartada', 'decisão: ' + d['motivo'], nao_feito(d, None)))
    return rm.T(f'Tabela do diagrama — {fid}', ['Decisão', 'Regra determinística', 'Regra de negócio', 'Funcionalidade', 'Situação', 'Motivo', 'Vínculo não feito'], rows,
                'Todas as decisões dos programas da funcionalidade e todas as regras determinísticas que ela alcança aparecem; o que não chega a regra de negócio está em cinza no diagrama e aqui traz o motivo e o vínculo que não foi feito.',
                marks=[r[4] == 'descartada' for r in rows], descartadas=[r[4] == 'descartada' for r in rows])


def modelo_rastreio(decs, regs_t, rinfo, grupos, atribuidas, fg, d):
    """Relatório da fase 13: rastreabilidade ponta a ponta (decisão → regra determinística → regra de negócio → funcionalidade): funil, tabela completa e, por funcionalidade, um diagrama de 4 colunas e a sua tabela
    com tudo que há nos programas dela, inclusive o descartado (cinza, com motivo e vínculo não feito)."""
    sec = rastreio_secao(decs, regs_t, rinfo, grupos, atribuidas, fg)
    tit = {g['id']: g['titulo'] for g in grupos}
    funcs = carregar_funcionalidades()
    secs, resumo, cobertas_d, cobertas_r, cruz_tot = [], [], set(), set(), 0
    for f in funcs:
        progs, regras = alcance_funcionalidade(f, regs_t, d)
        nodes, ar, guarda, nc = grafo_funcionalidade(f, progs, regras, decs, grupos, fg, tit)
        cruz_tot += nc
        g = rm.G(f'Rastreabilidade de {f["id"]}', nodes, [{'from': a, 'to': b, 'guarda': (a, b) in guarda} for a, b in ar], kind='colunas',
                 note='Colunas, da esquerda para a direita: decisão, regra determinística, regra de negócio e funcionalidade; a cor da borda é fixa por coluna. Cinza tracejado: decisão ou regra que não chega a regra de negócio (o motivo está no nó e na tabela). '
                      'Linha cheia: a decisão que escolhe o ramo da regra; linha pontilhada: decisão de guarda do caminho. A ordem dentro de cada coluna reduz os cruzamentos (' + str(nc) + ' nas linhas cheias).')
        g['columns'] = [{'name': n, 'color': c} for n, c in COR_TRACO]
        g['sem_tabela'] = True
        tb = tabela_funcionalidade(f, progs, regras, decs, ar, fg)
        ds = [x for x in decs if x['programa'] in progs]
        cobertas_d |= {(x['programa'], x['cod']) for x in ds}
        cobertas_r |= {(r['programa'], r['regra']) for r in regras}
        resumo.append((rm.with_links('', [rm.link(f['id'], '13 - traceability', 'rastreio-' + f['id'])]), f['nome'], ', '.join(sorted(progs)), len(ds), sum(1 for x in ds if x['sit'] != 'regra de negócio'),
                       len(regras), sum(1 for r in regras if r['destino'] != 'regra de negócio'), len({b for a, b in ar if b[0] == 'B'})))
        secs.append(rm.S('rastreio-' + f['id'], f'{f["id"]} · {f["nome"]}', [g, tb]))
    if funcs:
        sobra_d = [x for x in decs if (x['programa'], x['cod']) not in cobertas_d]
        sobra_r = [r for r in regs_t if (r['programa'], r['regra']) not in cobertas_r]
        cab = [rm.T('Por funcionalidade', ['Funcionalidade', 'Nome', 'Programas', 'Decisões', 'Decisões descartadas', 'Regras determinísticas', 'Regras descartadas', 'Regras de negócio'], resumo,
                    'Cada funcionalidade tem a sua seção, com o diagrama de 4 colunas e a tabela de todos os vínculos (feitos e não feitos).')]
        if sobra_d or sobra_r:
            cab.append(rm.T('Fora de qualquer funcionalidade', ['Item', 'Código', 'Situação', 'Motivo'],
                            [('decisão', x['programa'] + ':' + x['cod'], x['sit'], x['motivo']) for x in sobra_d] + [('regra determinística', r['programa'] + ':' + r['regra'], r['destino'], r['motivo']) for r in sobra_r],
                            'Decisões e regras de programas que nenhuma funcionalidade alcança nos relatórios; nada é omitido.'))
        secs = [rm.S('funcionalidades', 'Rastreabilidade por funcionalidade', cab)] + secs
    cards = [rm.card('decisões', len(decs)), rm.card('regras determinísticas', len(regs_t)), rm.card('regras de negócio', len(grupos)), rm.card('funcionalidades', len(funcs))]
    return rm.model('Rastreabilidade', 'Da decisão do mapa de decisões até a funcionalidade: decisão → regra determinística → regra de negócio → funcionalidade, em tabela e em diagrama por funcionalidade, com o que foi descartado em cinza e o motivo.', cards, [sec] + secs)


def rastreio_secao(decs, regs_t, rinfo, grupos, atribuidas, fg):
    """Seção "Rastreio": funil, tabela por programa, motivos de descarte e a tabela ponta a ponta (decisão × regra determinística × regra de negócio)."""
    nd = Counter(x['sit'] for x in decs)
    nr = Counter(x['destino'] for x in regs_t)
    DESC_D = {'regra de negócio': 'decide ao menos uma regra determinística que entra em regra de negócio', 'descartada': 'não chega a regra de negócio; o motivo está nas tabelas abaixo', 'sem classificação': 'chega a regra de negócio sem grupo', 'mecanismo implícito': 'só decide regras de mecanismos implícitos (paginação, montagem de chamada à infraestrutura, roteamento, erro repassado), fora do escopo de negócio'}
    DESC_R = {'regra de negócio': 'sustenta uma regra de negócio reunida', 'filtrada: fora da abrangência': 'a fase 6 (deterministic-rules) a marcou fora da abrangência: nenhum cenário de execução dinâmica alcança uma decisão dela ("não executado" na fase 5)', 'filtrada: infraestrutura': 'a fase 6 (deterministic-rules) a classificou com escopo de infraestrutura',
              'mecanismo implícito': 'escopo mecanismos implícitos: decidido pela fase 6 (deterministic-rules) ou julgado pela IA (o motivo está na coluna de motivo)',
              'sem classificação': 'regra de negócio sem grupo'}
    funil = [('Decisões no mapa de decisão', len(decs), 'fase 5, só as de tipo decisão (IF, EVALUATE, PERFORM UNTIL)')]
    funil += [('→ ' + k, nd.get(k, 0), DESC_D[k]) for k in ('regra de negócio', 'mecanismo implícito', 'descartada', 'sem classificação')]
    funil += [('Regras determinísticas', len(regs_t), 'fase 6')]
    funil += [('→ ' + k, n, DESC_R.get(k, '')) for k, n in sorted(nr.items(), key=lambda x: (-x[1], x[0]))]
    funil += [('Regras de negócio reunidas', len(grupos), f'{len(atribuidas)} regras determinísticas as sustentam'),
              ('Conferência', rinfo['inconsistentes'], 'decisões cuja lista "Regras que usam" (fase 5) difere das regras que a citam nas condições (fase 6)')]
    progs = sorted({x['programa'] for x in decs} | {x['programa'] for x in regs_t})
    porp = []
    for p in progs:
        dd = [x for x in decs if x['programa'] == p]
        rr_ = [x for x in regs_t if x['programa'] == p]
        c = Counter(x['destino'] for x in rr_)
        porp.append((p, len(dd), sum(1 for x in dd if x['sit'] == 'regra de negócio'), sum(1 for x in dd if x['sit'] == 'descartada'), sum(1 for x in dd if x['sit'] == 'mecanismo implícito'), len(rr_), c.get('regra de negócio', 0), c.get('filtrada: infraestrutura', 0), c.get('mecanismo implícito', 0), c.get('sem classificação', 0)))
    mot_d = Counter((x['sit'], x['motivo'] if not x['motivo'].startswith(('filtrada', 'plataforma')) else re.sub(r'\d+ regra\(s\)', 'N regra(s)', x['motivo'])) for x in decs if x['sit'] != 'regra de negócio')
    mot_r = Counter((x['destino'], x['tipo'], x['motivo']) for x in regs_t if x['destino'] != 'regra de negócio')
    blocos = [rm.X('Cada decisão do mapa de decisão (fase 5) é seguida até as regras determinísticas que dependem dela (fase 6) e daí até a regra de negócio. Tudo que ficou pelo caminho tem o motivo escrito.'),
              rm.T('Do mapa de decisão às regras de negócio', ['Etapa', 'Quantidade', 'O que acontece'], funil),
              rm.T('Por programa', ['Programa', 'Decisões', 'Decisões em regra de negócio', 'Decisões descartadas', 'Decisões de mecanismos implícitos', 'Regras determinísticas', 'Em regra de negócio', 'Filtradas (infraestrutura)', 'Mecanismos implícitos', 'Sem classificação'], porp),
              rm.T('Decisões descartadas: motivos', ['Situação', 'Motivo', 'Decisões'], [(s_, m, n) for (s_, m), n in sorted(mot_d.items(), key=lambda x: -x[1])]),
              rm.T('Regras determinísticas descartadas: motivos', ['Destino', 'Tipo da regra', 'Motivo', 'Regras'], [(dst, tp, m, n) for (dst, tp, m), n in sorted(mot_r.items(), key=lambda x: (x[0][0], -x[1]))])]
    linhas_t = cruzada(rinfo, fg)
    blocos.append(rm.T('Tabela de rastreabilidade ponta a ponta', ['Programa', 'Decisão', 'Linha', 'Condição da decisão', 'Execução', 'Situação da decisão', 'Regra determinística', 'Tipo', 'Subtipo', 'Escopo', 'Situação da regra', 'Regra de negócio', 'Funcionalidades', 'Motivo do descarte'],
                       linhas_t,
                       'Linhas com fundo azul: regras (e as decisões que só decidem regras) de mecanismos implícitos, escopo da fase 6 que não é regra de negócio. Uma linha por par decisão × regra determinística, da decisão do mapa de decisão (fase 5) até a regra de negócio. Nenhuma linha é agrupada: cada decisão e cada regra determinística aparece individualmente, com o seu próprio motivo. Decisão sem regra aparece com a regra "—"; regra sem decisão nas condições, com a decisão "—".',
                       marks=[str(r[5]).startswith('mecanismo implícito') or str(r[10]).startswith('mecanismo implícito') for r in linhas_t]))
    return rm.S('rastreio', 'Rastreio: decisão → regra determinística → regra de negócio → funcionalidade', blocos)


def cruzada(rinfo, fg):
    """Linhas da tabela ponta a ponta: UMA linha por par decisão × regra determinística (decisão sem regra e regra sem decisão também têm a sua), sem nenhum agrupamento;
    ordenadas por programa, linha e código da decisão."""
    saida = []
    for c in rinfo['cruz']:
        dd, rr_ = c['d'], c['r']
        mot = []
        if dd and dd['sit'] != 'regra de negócio':
            mot.append('decisão: ' + dd['motivo'])
        if rr_ and rr_['destino'] != 'regra de negócio':
            mot.append('regra: ' + rr_['destino'] + (' — ' + rr_['motivo'] if rr_['motivo'] else ''))
        if rr_ and not dd:
            mot.append('regra sem decisão nas condições: o caminho só exige o ramo de sucesso ou não tem condição de negócio')
        gl = rm.with_links('', [rm.link(g, '11 - business-rules', g) for g in rr_['grupos']]) if rr_ and rr_['grupos'] else '—'
        fs = list(dict.fromkeys(i for g in (rr_['grupos'] if rr_ else []) for i, _n in fg.get(g, [])))
        fl = rm.with_links('', [rm.link(i, '12 - business-flows', i) for i in fs]) if fs else '—'
        chave = (c['p'], int(dd['linha']) if dd and str(dd['linha']).isdigit() else 10 ** 9, dd['cod'] if dd else '~', rr_['regra'] if rr_ else '')
        saida.append((chave, [c['p'], (c['p'] + ':' + dd['cod']) if dd else '—', str(dd['linha']) if dd else '', dd['cond'] if dd else '', dd['exec'] if dd else '', dd['sit'] if dd else '—',
                              (c['p'] + ':' + rr_['regra']) if rr_ else '—', rr_['tipo'] if rr_ else '', rr_['sub'] if rr_ else '', rr_['escopo'] if rr_ else '', rr_['destino'] if rr_ else '—', gl, fl, '; '.join(mot)]))
    return [x[1] for x in sorted(saida, key=lambda x: x[0])]


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    global BASE
    args = sys.argv[1:]
    if '--interpretacao' in args:
        i = args.index('--interpretacao')
        BASE = Path(args[i + 1]).resolve()
        del args[i:i + 2]
    ana = Path(args[0])
    saida = Path(args[1]) if len(args) > 1 else ana
    definir_copybooks(ana)
    d = lerRelatorios(ana)
    _aviso, cats, grupos, plat = carregar_interp()
    compartilhados = carregar_compartilhados()
    import gerar_sql as Q   # mapeamento SQL (fase 10): os comandos dinâmicos também geram regras de negócio
    global DIN
    DIN = regras_dinamicas(Q.carregar_mapeamento(BASE), d['caixas'])
    grupos, erros_e = expandir_por_programa(grupos, {r['programa'] + ':' + r['Regra']: [x.strip() for x in r['Entry points'].split(',') if x.strip()] for r in d['regras'] + DIN}, compartilhados, d['corp'])
    if erros_e:
        raise SystemExit('regras de negócio que cruzam programas:\n  ' + '\n  '.join(erros_e))
    erros_n = verificar_nomes_e_retornos(d, grupos)
    if erros_n:
        raise SystemExit('regras de negócio com nome ou retorno inválido:\n  ' + '\n  '.join(erros_n))
    erros_m = aplicar_mecanismos(d, grupos)
    if erros_m:
        raise SystemExit('mecanismos da IA inconsistentes:\n  ' + '\n  '.join(erros_m))
    entram, fora, infra = filtrar(d)
    mod, falhas, n_atr, n_plat, resto, rastro = modelo(d, cats, grupos, plat, entram, fora, infra)
    sem_din = [r for r in DIN if r['Escopo'] == 'negócio' and not any(f'{r["programa"]}:{r["Regra"]}' in g['regras'] for g in grupos)]
    if DIN:
        mod['sections'].insert(1, rm.S('comandos-dinamicos', 'Comandos SQL dinâmicos e as regras de negócio', [
            rm.T('Comandos SQL estáticos que substituem consultas dinâmicas (fase 10) e a regra de negócio que cada um sustenta', ['Comando', 'Consulta dinâmica', 'Serviço', 'Quando', 'Regra de negócio', 'Entry points'],
                 [(rm.with_links('', [rm.link(r['Regra'], '10 - sql-mapping', r['Regra'])]), r['consulta'], r['programa'], r['quando'],
                   rm.with_links('', [rm.link(g['id'], '11 - business-rules', g['id']) for g in grupos if f'{r["programa"]}:{r["Regra"]}' in g['regras']]) or ('fora da abrangência (nenhum cenário o executa)' if r['Escopo'] != 'negócio' else 'sem regra de negócio'), r['Entry points']) for r in DIN])],
            f'{len(DIN)} comando(s) SQL estático(s) que substituem consultas dinâmicas; cada um deve estar em alguma regra de negócio (categoria C, consulta de dados, ou outra que o comando sustente). Sem regra: {len(sem_din)}.'))
    escrever(saida, '11 - business-rules', mod)
    escrever(saida, '13 - traceability', rastro)
    print(f'{len(entram)} regras de negócio, {len(fora)} filtradas; {len(grupos)} regras reunidas sobre {n_atr} regras; sem classificação: {len(resto)}; literais citados sem evidência: {falhas}')
    for p, r in resto:
        print(f'  sem classificação: {p}:{r["Regra"]} [{r["Tipo"]}]')
    fg = funcionalidades_por_grupo(grupos)
    filtrados = grupos_filtrados()
    sem = [g['id'] for g in grupos if fg and not fg.get(g['id']) and g['id'].split('.')[0] not in filtrados]
    for g in sem:
        print(f'  regra de negócio {g} sem funcionalidade no relatório de fluxos')
    for r in sem_din:
        print(f'  comando SQL dinâmico {r["programa"]}:{r["Regra"]} sem regra de negócio (cite-o em `regras` de algum grupo)')
    sys.exit(1 if (falhas or resto or sem or sem_din) else 0)


if __name__ == '__main__':
    main()
