"""Modelos de visão das fases 4b e 4c (gerados só por script, a partir do resultado da fase 4; nenhuma IA, nenhum nome fixo).

4b (resumo da linhagem), por programa:
  1. relação: quem o chama, quem ele chama, seus comandos SQL e as tabelas (diagrama + tabela);
  2. encadeamento: qual comando alimenta qual (dado lido por um e usado por outro) e qual só executa conforme o status de outro (diagrama + tabela);
  3. fluxo de dados de TODOS os comandos SQL do programa em um só diagrama: origem mais distante -> parte do SQL a que se refere (WHERE ou campo como parâmetro:
     VALUES/SET) -> comando -> coluna lida -> fim do caminho; com as condições; e três tabelas (WHERE, campos como parâmetro, saídas).
  O que a análise dinâmica não executou fica em cinza (comando, tabela, programa, origens e destinos que só ele alimenta) e some no checkbox da seção.
4c (funcionalidades): por funcionalidade, os comandos SQL que executa e as chamadas a outras funcionalidades."""
import re
from collections import defaultdict

from cores import COR_CLASSE, COR_SQL_LE as COR_LEITURA, COR_SQL_GRAVA as COR_GRAVA, GRAVACAO as _GRAV
from report_model import T, G, S, card, model, link, sql_link, with_links

PHASE = '04b-lineage-summary'
COR = {'entrada do entry point': '#3F51B5', 'valor fixo': '#6B7280', 'valor inicial': '#8D6E63', 'tabela lida': COR_LEITURA, 'coluna de outra tabela': COR_LEITURA,
       'não rastreada': '#C2185B', 'saída do programa': '#3F51B5', 'envio': '#1565C0', 'gravação': COR_GRAVA, 'chave de consulta': '#6B7280',
       'fim do caminho (sem saída do programa)': '#C2185B'}
COR_WHERE, COR_CAMPOS = '#B26A00', '#455A64'
NEUTRA = '#555555'
GRAVACAO = set(_GRAV)
LEGENDA = {
    'entrada do entry point': 'o valor vem do pedido recebido pelo entry point e chega ao comando por cópias de campo para campo, sem alteração',
    'valor fixo': 'o valor é uma constante (inclusive quando passa por campos de transporte)',
    'valor inicial': 'o campo nunca é atribuído no programa: vale o valor inicial da declaração',
    'tabela lida': 'o valor é uma coluna lida de uma tabela por outro comando SQL (o link leva à linha desse comando)',
    'coluna de outra tabela': 'ligação (JOIN) com uma coluna de outra tabela dentro do próprio comando',
    'não rastreada': 'o rastreio não explicou a origem (lacuna a investigar)',
    'saída do programa': 'o valor é gravado em campo da área de saída do programa',
    'envio': 'o valor passa a outro programa pela chamada e chega a um campo dele',
    'gravação': 'o valor é gravado em coluna de tabela',
    'chave de consulta': 'o valor vira chave de busca de outra consulta',
    'fim do caminho (sem saída do programa)': 'o valor chega a um campo que não sai do programa'}
LEGENDA_PARTES = [('WHERE', COR_WHERE, 'condição de SELECT, UPDATE, DELETE ou chave do cursor: o dado que escolhe as linhas'),
                  ('VALUES / SET', COR_CAMPOS, 'campo como parâmetro: o dado que o INSERT grava (VALUES) ou o UPDATE altera (SET)'),
                  ('comando que lê', COR_LEITURA, 'SELECT, FETCH (cursor): devolve colunas ao programa'),
                  ('comando que grava', COR_GRAVA, 'INSERT, UPDATE, DELETE, MERGE')]
TG_EXEC = 'Mostrar o que nenhum cenário executou (em cinza)'


def _cut(s, n):
    s = str(s)
    return s if len(s) <= n else s[:n - 1] + '…'


def _quando(a):
    return ' ; '.join(a.get('quando') or [])


def _sem_codigo(txt):
    return re.sub(r'(?:\b[A-Z0-9]+)?:D\d+ ', '', txt)


def _quando_curto(a):
    return ' ; '.join(_sem_codigo(q) for q in a.get('quando') or [])


def _origem_label(a):
    if a['tipo'] == 'valor fixo':
        return a['valor'] if not a['valor'].startswith('valor inicial') else 'valor inicial (PIC/VALUE)'
    if a['tipo'] == 'tabela lida':
        return f'{a["tabela"]}.{a["campo"]}'
    if a['tipo'] in ('entrada do entry point', 'não rastreada', 'valor inicial') and a.get('campo'):
        return a['campo']
    return a['resumo'].split(': ', 1)[-1]


def _trans_txt(trs):
    return ' ; '.join(f'{t["expressao"]} ({t["programa"]}@{t["linha"]})' for t in trs) if trs else 'nenhuma (o valor só é copiado)'


def _ref(x):
    return [link(x['ref_sql'], '04-data-lineage', 'sql-' + x['ref_sql'])] if x.get('ref_sql') else []


def _cor_prog(classes, p):
    return COR_CLASSE.get(classes.get(p, ''), NEUTRA)


def _natureza_cor(comando):
    return COR_GRAVA if comando in GRAVACAO else COR_LEITURA


def _nm(c):
    return f'{c["cod"]} {c["comando"]} {c["tabela"]}'


def _percurso_txt(x):
    p = x.get('percurso') or []
    return ' → '.join(p) if len(p) > 1 else (p[0] if p else '')


# ----------------------------------------------------------------------------- execução dinâmica
class Exec:
    """O que os cenários executaram. Sem execução (dyn None) nada é marcado como não executado."""

    def __init__(self, ctx, cmds):
        import report_maps as mp
        self.mp = mp
        self.dyn = mp.dynamic(ctx or {})
        self.seen = mp.scenario_tables_seen(ctx or {}) if self.dyn else {}
        self.rodou = {c['id']: self.dyn is None or bool(set(c['linhas']) & set(self.dyn['sql_lines'].get(c['programa'], ()))) for c in cmds}
        self.tab_ok = {}
        for c in cmds:
            self.tab_ok.setdefault(c['tabela_completa'], False)
            self.tab_ok[c['tabela_completa']] |= self.rodou[c['id']]

    @property
    def ativo(self):
        return self.dyn is not None

    def cmd(self, c):
        return self.rodou.get(c['id'], True)

    def tabela(self, t):
        return self.dyn is None or self.tab_ok.get(t, False) or bool(self.mp._match(t, self.seen))

    def programa(self, p):
        return self.dyn is None or p in self.dyn['real'] or p in self.dyn['mock']

    def txt(self, ok):
        return ('sim' if ok else 'NÃO') if self.dyn is not None else ''


# ----------------------------------------------------------------------------- diagramas
def _ordenar(nos, arestas, ordem=None):
    """Dentro de cada coluna, ordem pela posição média dos vizinhos (menos cruzamentos). ordem[col] = 'fixa' (mantém a ordem da lista), 'prox' (vizinhos da coluna seguinte)
    ou 'ant' (vizinhos da coluna anterior, padrão); a primeira coluna é fixa por padrão."""
    por = defaultdict(list)
    for n in nos:
        por[n['col']].append(n)
    if not por:
        return nos
    cols = sorted(por)
    modo = {c: (ordem or {}).get(c, 'fixa' if c == cols[0] else 'ant') for c in cols}
    ncol = {n['id']: n['col'] for n in nos}
    viz = defaultdict(set)
    for e in arestas:
        if e['from'] in ncol and e['to'] in ncol:
            viz[e['from']].add(e['to'])
            viz[e['to']].add(e['from'])
    pos = {}

    def marca(c):
        for i, n in enumerate(por[c]):
            pos[n['id']] = i

    def baricentro(c, ref):
        for n in por[c]:
            v = [pos[x] for x in viz[n['id']] if ncol[x] == ref and x in pos]
            n['_m'] = sum(v) / len(v) if v else 0
        por[c].sort(key=lambda n: n['_m'])
        for n in por[c]:
            n.pop('_m')
        marca(c)
    for c in cols:
        if modo[c] == 'fixa':
            marca(c)
    for i in range(len(cols) - 1, -1, -1):
        if modo[cols[i]] == 'prox' and i + 1 < len(cols):
            baricentro(cols[i], cols[i + 1])
    for i, c in enumerate(cols):
        if modo[c] == 'ant' and i > 0:
            baricentro(c, cols[i - 1])
    return [n for c in cols for n in por[c]]


def _legenda_nos(nos):
    """Legenda de cores montada dos nós do diagrama (só o que aparece nele): classe do programa, comando que lê/grava, parte do SQL, tipo de origem e de fim do caminho; cinza = não executado."""
    classe = {v: 'programa ' + k.lower() for k, v in COR_CLASSE.items()}
    fixos = {COR_LEITURA: 'comando que lê', COR_GRAVA: 'comando que grava', COR_WHERE: 'condição WHERE', COR_CAMPOS: 'campo como parâmetro (VALUES / SET)'}
    out, vistos = [], set()
    for n in nos:
        tipo = str(n.get('sub') or '').split(' · ')[0]
        cor = n.get('cor')
        txt = tipo if tipo in COR and COR[tipo] == cor else classe.get(cor) or fixos.get(cor)
        if txt and txt not in vistos:
            vistos.add(txt)
            out.append({'texto': txt, 'cor': cor})
    return out + [{'texto': 'cinza tracejado: nenhum cenário executou', 'inativo': True}]


def _grafo(titulo, colunas, nos, arestas, nota, nw=200, ordem=None):
    """Colunas sem nenhum nó são descartadas (por exemplo, comando sem entrada não tem as duas primeiras colunas)."""
    usadas = sorted({n['col'] for n in nos})
    ordem = {c: v for c, v in (ordem or {}).items() if c in usadas}
    nos = _ordenar(nos, arestas, ordem)
    novo = {c: i for i, c in enumerate(usadas)}
    for n in nos:
        n['col'] = novo[n['col']]
    g = G(titulo, nos, arestas, kind='colunas', note=nota)
    g['columns'] = [{'name': colunas[c], 'color': NEUTRA} for c in usadas]
    g['nw'] = nw
    g['sem_tabela'] = True
    g['toggle_label'] = TG_EXEC
    g['legenda'] = _legenda_nos(nos)
    return g


def _grafo_programa(p, cmds, chamadas, classes, ex):
    """Relação: quem o chama -> programa -> (programas que chama | comandos SQL) -> tabela."""
    nos = [{'id': 'p', 'col': 1, 'label': p, 'sub': classes.get(p, '') + ('' if ex.programa(p) else ' · não executado'), 'detail': f'programa {p} ({classes.get(p, "")})', 'cor': _cor_prog(classes, p)}]
    arestas, tab = [], {}
    for c in chamadas:
        if c['para'] == p:
            nid = 'a-' + str(c['de'])
            if not any(n['id'] == nid for n in nos):
                nos.append({'id': nid, 'col': 0, 'label': str(c['de']), 'sub': classes.get(c['de'], ''), 'detail': f'{c["de"]} chama {p} por {c["mecanismo"]} (linha {c["linha"]})',
                            'cor': _cor_prog(classes, c['de']), 'inactive': not ex.programa(c['de'])})
                arestas.append({'from': nid, 'to': 'p'})
    for c in chamadas:
        if c['de'] == p:
            nid = 'b-' + str(c['para'])
            if not any(n['id'] == nid for n in nos):
                nos.append({'id': nid, 'col': 2, 'label': str(c['para']), 'sub': 'chamado · ' + classes.get(c['para'], ''),
                            'detail': f'{p} chama {c["para"]} por {c["mecanismo"]} (linha {c["linha"]}), área {c["area"]}', 'cor': _cor_prog(classes, c['para']), 'inactive': not ex.programa(c['para'])})
                arestas.append({'from': 'p', 'to': nid})
    for c in cmds:
        nid = 'q-' + c['id']
        nos.append({'id': nid, 'col': 2, 'label': _nm(c), 'sub': f'linha {c["linha"]}' + (f' · cursor {c["cursor"]}' if c['cursor'] else ''), 'detail': c['cod'] + ': ' + c['sql'],
                    'cor': _natureza_cor(c['comando']), 'inactive': not ex.cmd(c)})
        arestas.append({'from': 'p', 'to': nid})
        tid = 't-' + c['tabela']
        if tid not in tab:
            tab[tid] = True
            nos.append({'id': tid, 'col': 3, 'label': c['tabela'], 'sub': 'tabela', 'detail': c['tabela_completa'], 'cor': NEUTRA, 'inactive': not ex.tabela(c['tabela_completa'])})
        arestas.append({'from': nid, 'to': tid})
    return _grafo(f'Relação de {p}: chamadas, comandos SQL e tabelas', ['Chamado por', 'Programa', 'Chama programa ou executa comando SQL', 'Tabela'], nos, arestas,
                  'Cor do programa = classe (azul coordenador, verde funcional, laranja corporativo, vermelho infraestrutura). Comando SQL: verde-água lê, roxo grava. Cinza tracejado: a análise dinâmica não executou.', nw=230)


def _tabela_programa(p, cmds, chamadas, classes, ex):
    rows, desc = [], []
    for c in chamadas:
        if c['para'] == p:
            rows.append(['chamado por', c['de'], classes.get(c['de'], ''), c['linha'], f'{c["mecanismo"]}, área {c["area"]}', ex.txt(ex.programa(c['de']))])
            desc.append(not ex.programa(c['de']))
    for c in chamadas:
        if c['de'] == p:
            rows.append(['chama', c['para'], classes.get(c['para'], ''), c['linha'], f'{c["mecanismo"]}, área {c["area"]}' + (f', parágrafo {c["paragrafo"]}' if c['paragrafo'] else ''),
                         ex.txt(ex.programa(c['para']))])
            desc.append(not ex.programa(c['para']))
    for c in cmds:
        rows.append(['comando SQL', _nm(c), 'grava' if c['comando'] in GRAVACAO else 'lê', c['linha'],
                     (f'cursor {c["cursor"]}; ' if c['cursor'] else '') + f'tabela {c["tabela_completa"]}', ex.txt(ex.cmd(c))])
        desc.append(not ex.cmd(c))
    cols = ['Relação', 'Programa ou comando', 'Classe ou natureza', 'Linha', 'Detalhe'] + (['Executado pela análise dinâmica'] if ex.ativo else [])
    if not ex.ativo:
        rows = [r[:-1] for r in rows]
    return T(f'Relação de {p}: chamadas e comandos SQL', cols, rows, descartadas=desc if ex.ativo else None)


# ----------------------------------------------------------------------------- encadeamento
def _decisao_txt(d, prog=''):
    return (f'{d.get("programa") or prog}:{d["codigo"]} ' if d.get('codigo') else '') + (('se ' + d['condicao']) if d.get('resultado') == 'Sim' else f'senão ({d["condicao"]})')


def _executa(c):
    """(texto das condições de negócio que habilitam o comando, [ids de comandos de que depende o status], [textos de status sem comando])."""
    textos, st, st_txt = [], [], []
    for path in c.get('executa_quando') or []:
        ds = [_decisao_txt(d, c.get('programa', '')) for d in path if not d.get('tecnica')]
        t = ' E '.join(dict.fromkeys(ds))
        if t and t not in textos:
            textos.append(t)
        for d in path:
            if d.get('status_id') and d['status_id'] not in st:
                st.append(d['status_id'])
            if d.get('status_txt') and d['status_txt'] not in st_txt:
                st_txt.append(d['status_txt'])
    if len(textos) > 3:
        textos = textos[:3] + [f'… (+{len(textos) - 3} caminhos)']
    return (' OU '.join(textos) if textos else 'sem condição de negócio'), st, st_txt


def _encadeamento(cmds, todos, ex):
    """Arestas entre comandos: 'dado' (coluna lida por X é origem de uma entrada de Y, ou destino de uma coluna lida por X é Y) e 'execução' (Y só executa conforme o status de X)."""
    por_id = {i: c for c in todos for i in c['ids']}
    arestas = {}

    def add(x, y, tipo, det):
        if x is None or y is None or x['id'] == y['id']:
            return
        arestas.setdefault((x['id'], y['id'], tipo), set()).add(det)
    for y in cmds:
        for e in y['entradas']:
            for a in e['alternativas']:
                if a.get('ref_sql') and por_id.get(a['ref_sql']) is not None:
                    add(por_id[a['ref_sql']], y, 'dado', f'{a["tabela"]}.{a["campo"]} → {e["parte"]}: {e["curto"]}')
        _, st, _ = _executa(y)
        for s in st:
            add(por_id.get(s), y, 'execução', 'só executa conforme o status/resultado do comando de origem')
    for x in cmds:
        for s in x['saidas']:
            for d in s['destinos']:
                if d.get('ref_sql') and por_id.get(d['ref_sql']) is not None:
                    add(x, por_id[d['ref_sql']], 'dado', f'{s["coluna"]} → {d["resumo"]}')
    # as arestas de dados que partem de comandos de outros programas só entram quando chegam a um comando do programa (e vice-versa): `cmds` é o filtro
    return arestas, por_id


def _niveis(ids, ar):
    """Nível de cada comando: maior distância a partir de comandos sem predecessor (ciclos não aumentam o nível além do número de nós)."""
    nivel = {i: 0 for i in ids}
    for _ in range(len(ids)):
        mud = False
        for (x, y) in sorted(ar):
            if nivel[y] < nivel[x] + 1 and nivel[x] + 1 < len(ids):
                nivel[y] = nivel[x] + 1
                mud = True
        if not mud:
            break
    return nivel


def _grafo_encadeamento(p, cmds, arestas, por_id, ex):
    ids_prog = {c['id'] for c in cmds}
    sel = {k: v for k, v in arestas.items() if k[0] in ids_prog or k[1] in ids_prog}
    if not sel:
        return None, []
    # dependência de execução já implícita por outro caminho (A -> B -> C implica A -> C) não é desenhada
    prox = defaultdict(set)
    for (x, y, t) in sel:
        prox[x].add(y)

    def alcanca(a, b, sem):
        vistos, fila = set(), [n for n in prox[a] if (a, n) != sem]
        while fila:
            n = fila.pop()
            if n == b:
                return True
            if n in vistos:
                continue
            vistos.add(n)
            fila += [m for m in prox[n]]
        return False
    sel = {k: v for k, v in sel.items() if not (k[2] == 'execução' and alcanca(k[0], k[1], (k[0], k[1])))}
    nos_ids = sorted({k[0] for k in sel} | {k[1] for k in sel}, key=lambda i: (por_id[i]['programa'], por_id[i]['linha'] or 0))
    nivel = _niveis(nos_ids, {(k[0], k[1]) for k in sel})
    nmax = min(max(nivel.values()), 5)
    recebe = defaultdict(list)
    for (x, y, t), dets in sel.items():
        recebe[y].append(f'{por_id[x]["cod"]} ({t}): ' + ' | '.join(sorted(dets)))
    nos = []
    for i in nos_ids:
        c = por_id[i]
        externo = c['programa'] != p
        nos.append({'id': i, 'col': min(nivel[i], 5), 'label': c['cod'], 'sub': f'{c["comando"]} {c["tabela"]}' + (' · outro programa' if externo else ''),
                    'detail': c['cod'] + ' (' + i + '): ' + c['sql'] + (' || recebe de: ' + ' ; '.join(recebe[i]) if recebe[i] else ''), 'cor': _natureza_cor(c['comando']), 'inactive': not ex.cmd(c)})
    ar = [{'from': x, 'to': y, 'guarda': t == 'execução'} for (x, y, t) in sorted(sel)]
    nomes = ['Primeiros comandos'] + [f'Depois ({k})' for k in range(1, nmax + 1)]
    g = _grafo(f'Encadeamento dos comandos SQL de {p}', nomes, nos, ar,
               'Linha cheia: dado lido por um comando e usado pelo seguinte (como valor de condição, campo gravado ou chave). Linha tracejada: o comando seguinte só executa conforme o status ou resultado do anterior '
               '(dependências já implícitas por outro caminho não são repetidas). A coluna é a maior distância a partir de um comando sem predecessor; o tooltip do nó diz de que comandos ele recebe e o quê. O código do comando está na tabela de comandos do programa.', nw=210)
    return g, []


# ----------------------------------------------------------------------------- fluxo de dados do programa (um diagrama, todos os comandos)
def _grafo_fluxo(p, cmds, ex):
    """Todos os comandos SQL do programa em um só diagrama: origem -> parte do SQL (WHERE ou campo como parâmetro) -> comando -> coluna lida -> fim do caminho."""
    nos, arestas = [], []
    por_origem, por_dest = {}, {}
    uso = defaultdict(list)   # nó compartilhado -> [comando executado?]
    for c in cmds:
        ok = ex.cmd(c)
        cid = 'c' + str(cmds.index(c))
        exec_txt, _, _ = _executa(c)
        sub2 = ('executa se: ' + _sem_codigo(exec_txt)) if exec_txt != 'sem condição de negócio' else ''
        nos.append({'id': cid, 'col': 2, 'label': _nm(c), 'sub': f'{c["programa"]}@{c["linha"]}' + (f' · cursor {c["cursor"]}' if c['cursor'] else ''),
                    'sub2': 'NÃO EXECUTADO' if not ok else sub2, 'detail': c['cod'] + ' (' + c['id'] + '): ' + c['sql'] + (f' | executa quando: {exec_txt}' if exec_txt else ''), 'cor': _natureza_cor(c['comando']),
                    'inactive': not ok})
        for k, e in enumerate(c['entradas']):
            pid = f'{cid}i{k}'
            nalt = len(e['alternativas'])
            nos.append({'id': pid, 'col': 1, 'label': e.get('curto') or e['item'], 'sub': e['parte'] + (f' · {nalt} origens' if nalt > 1 else ''), 'detail': f'{e["parte"]}: {e["fragmento"]} ({e["papel"]})',
                        'cor': COR_WHERE if e['grupo'] == 'where' else COR_CAMPOS, 'inactive': not ok})
            arestas.append({'from': pid, 'to': cid})
            for a in e['alternativas']:
                chave = (a['resumo'], _quando(a), tuple(t['expressao'] for t in a['transformacoes']))
                if chave not in por_origem:
                    por_origem[chave] = f'o{len(por_origem)}'
                    tr = a['transformacoes']
                    nos.append({'id': por_origem[chave], 'col': 0, 'label': _origem_label(a), 'sub': a['tipo'] + (' · transformado' if tr else ''),
                                'sub2': ('quando: ' + _quando_curto(a)) if a.get('quando') else ('transforma: ' + _cut(tr[-1]['expressao'], 40) if tr else ''),
                                'detail': a['resumo'] + (f' | quando: {_quando(a)}' if a.get('quando') else '') + (f' | percurso: {_percurso_txt(a)}' if _percurso_txt(a) else ''), 'cor': COR.get(a['tipo'], NEUTRA)})
                uso[por_origem[chave]].append(ok)
                arestas.append({'from': por_origem[chave], 'to': pid})
        for k, s in enumerate(c['saidas']):
            sid = f'{cid}s{k}'
            nos.append({'id': sid, 'col': 3, 'label': s['coluna'], 'sub': 'recebe ' + _cut(s['campo'], 22), 'detail': f'coluna {s["coluna"]} recebida em {s["campo"]} ({s["uso"]})', 'cor': NEUTRA, 'inactive': not ok})
            arestas.append({'from': cid, 'to': sid})
            for d in s['destinos']:
                chave = (d['resumo'], _quando(d))
                if chave not in por_dest:
                    por_dest[chave] = f'd{len(por_dest)}'
                    rot = _cut(d['transformacoes'][-1]['expressao'], 28) if d['transformacoes'] else (d['campo'] or d['tipo'])
                    nos.append({'id': por_dest[chave], 'col': 4, 'label': rot, 'sub': d['tipo'] + (f' · {d["programa"]}@{d["linha"]}' if d.get('linha') else ''),
                                'sub2': ('quando: ' + _quando_curto(d)) if d.get('quando') else '', 'detail': d['resumo'] + (f' | quando: {_quando(d)}' if d.get('quando') else ''),
                                'cor': COR.get(d['tipo'], NEUTRA)})
                uso[por_dest[chave]].append(ok)
                arestas.append({'from': sid, 'to': por_dest[chave]})
    for n in nos:
        if n['id'] in uso:
            n['inactive'] = not any(uso[n['id']])
    return _grafo(f'Fluxo de dados de {p}: todos os comandos SQL', ['Origem do dado (mais distante)', 'Parte do SQL a que se refere', 'Comando SQL', 'Coluna lida', 'Fim do caminho'], nos, arestas,
                  'Entradas à esquerda (a origem mais distante com base na entrada do entry point, ligada ao trecho do SQL que ela alimenta: marrom = WHERE, cinza-azulado = campo como parâmetro VALUES/SET); '
                  'saídas à direita. Abaixo do nome da origem ou do fim: a condição que o escolhe. Os campos de transporte não aparecem (o valor é o mesmo); a transformação aparece quando existe. '
                  'Cinza tracejado: nenhum cenário executou. O texto completo está no tooltip de cada nó e nas tabelas.', nw=250, ordem={1: 'fixa', 2: 'fixa', 3: 'fixa', 0: 'prox', 4: 'ant'})


def _linhas_origens(c, grupo, ex):
    rows, ids, desc = [], [], []
    ok = ex.cmd(c)
    for e in c['entradas']:
        if e['grupo'] != grupo:
            continue
        n = len(e['alternativas'])
        for k, a in enumerate(e['alternativas'], 1):
            r = [_nm(c), f'{c["programa"]}@{c["linha"]}', e['parte'], e['fragmento'], e['papel'], f'{k} de {n}', a['resumo'], a['tipo'], _percurso_txt(a),
                 _quando(a) or ('' if n == 1 else '(única origem alcançável)'), ' ; '.join(a.get('caminho') or []), _trans_txt(a['transformacoes']), a['copias'],
                 with_links('', _ref(a)) if a.get('ref_sql') else '']
            if ex.ativo:
                r.append(ex.txt(ok))
            rows.append(r)
            ids.append('')
            desc.append(not ok)
    return rows, ids, desc


def _tabelas_entradas(p, cmds, ex):
    cols = ['Comando SQL', 'Linha', 'Parte do comando', 'Trecho do SQL', 'Papel', 'Alternativa', 'Origem mais distante', 'Tipo da origem', 'Percurso entre programas',
            'Condição que escolhe esta origem', 'Outras condições do caminho', 'Transformação', 'Cópias sem alteração', 'Linha de origem (fase 4)'] + (['Executado'] if ex.ativo else [])
    out = []
    for grupo, titulo, nota in (('where', f'Condições do WHERE de {p} (SELECT, UPDATE, DELETE e chave de cursor)',
                                 'O dado que escolhe as linhas. Uma linha por origem possível de cada condição; "Trecho do SQL" é o pedaço do comando a que a origem se refere.'),
                                ('campos', f'Campos como parâmetro de {p} (INSERT VALUES e UPDATE SET)',
                                 'O dado que o comando grava: coluna ← valor. Uma linha por origem possível de cada coluna.')):
        rows, ids, desc = [], [], []
        for c in cmds:
            r_, i_, d_ = _linhas_origens(c, grupo, ex)
            if r_:
                i_[0] = f'{"whr" if grupo == "where" else "par"}-{c["id"]}'
            rows += r_
            ids += i_
            desc += d_
        if rows:
            out.append(T(titulo, cols, rows, note=nota, ids=ids, descartadas=desc if ex.ativo else None))
    return out


def _tabela_saidas(p, cmds, ex):
    rows, ids, desc = [], [], []
    for c in cmds:
        ok = ex.cmd(c)
        primeiro = True
        for s in c['saidas']:
            ds = s['destinos'] or [None]
            n = len(ds)
            for k, d in enumerate(ds, 1):
                r = [_nm(c), f'{c["programa"]}@{c["linha"]}', s['coluna'], s['campo'], s['uso'], f'{k} de {n}' if d else '', d['resumo'] if d else '(sem destino)',
                     d['tipo'] if d else '', _percurso_txt(d) if d else '', _quando(d) if d else '', ' ; '.join(d.get('caminho') or []) if d else '', _trans_txt(d['transformacoes']) if d else '',
                     d['copias'] if d else '', with_links('', _ref(d)) if d and d.get('ref_sql') else '']
                if ex.ativo:
                    r.append(ex.txt(ok))
                rows.append(r)
                ids.append(f'sai-{c["id"]}' if primeiro else '')
                primeiro = False
                desc.append(not ok)
    if not rows:
        return []
    cols = ['Comando SQL', 'Linha', 'Coluna lida', 'Campo que recebe', 'Uso no código', 'Destino', 'Até onde o dado vai', 'Tipo do fim', 'Percurso entre programas', 'Condição que habilita este destino',
            'Outras condições do caminho', 'Transformação até o fim', 'Cópias sem alteração', 'Comando de destino (fase 4)'] + (['Executado'] if ex.ativo else [])
    return [T(f'Saídas de {p}: colunas lidas e o fim do caminho de cada uma', cols, rows, ids=ids, descartadas=desc if ex.ativo else None,
              note='Uma linha por destino de cada coluna lida: o fim do caminho no programa (saída, passagem a outro programa, gravação, chave de outra consulta).')]


def _tabela_comandos(p, cmds, ex, arestas, por_id):
    """Uma linha por comando SQL do programa (âncora cmd-<id>, usada pela fase 4c e pelo índice)."""
    rows, ids, desc = [], [], []
    for c in cmds:
        exec_txt, st, st_txt = _executa(c)
        dep = ' ; '.join([i.split(':')[0] for i in st] + st_txt)
        ntrans = sum(1 for e in c['entradas'] for a in e['alternativas'] if a['transformacoes']) + sum(1 for s in c['saidas'] for d in s['destinos'] if d['transformacoes'])
        recebe = sorted({por_id[x]['cod'] for (x, y, t) in arestas if y == c['id'] and x in por_id and t == 'dado'})
        entrega = sorted({por_id[y]['cod'] for (x, y, t) in arestas if x == c['id'] and y in por_id and t == 'dado'})
        dep = ' ; '.join(sorted({por_id[x]['cod'] for (x, y, t) in arestas if y == c['id'] and x in por_id and t == 'execução'}) + st_txt)
        r = [with_links(c['cod'], [link('fase 4: ' + c['id'], '04-data-lineage', 'sql-' + c['id'])]), c['comando'], c['tabela_completa'], ', '.join(str(x) for x in c['linhas']), c['paragrafo'], c['cursor'],
             'grava' if c['comando'] in GRAVACAO else 'lê', exec_txt, dep, ', '.join(recebe), ', '.join(entrega), ', '.join(c['entry_points']),
             sum(1 for e in c['entradas'] if e['grupo'] == 'where'), sum(1 for e in c['entradas'] if e['grupo'] == 'campos'), len(c['saidas']), ntrans]
        if ex.ativo:
            r.append(ex.txt(ex.cmd(c)))
        rows.append(r)
        ids.append(f'cmd-{c["id"]}')
        desc.append(not ex.cmd(c))
    cols = ['Código (link fase 4)', 'Operação', 'Tabela', 'Linhas', 'Parágrafo', 'Cursor', 'Natureza', 'Executa quando (condições de negócio)', 'Só executa conforme o status de', 'Recebe dado de', 'Entrega dado a', 'Entry points', 'Condições WHERE',
            'Campos como parâmetro', 'Colunas lidas', 'Com transformação'] + (['Executado'] if ex.ativo else [])
    return T(f'Comandos SQL de {p}', cols, rows, ids=ids, descartadas=desc if ex.ativo else None,
             note='"Executa quando" reúne as decisões de negócio do caminho até o comando (caminhos alternativos separados por OU; decisões sobre status de execução ficam em "Só executa conforme o status de"). O código (programa-Qnn, na ordem das linhas) é o id do comando nos diagramas e nas tabelas; as relações entre comandos estão nos diagramas de encadeamento.')


def _legenda(ex):
    rows = [[k, COR[k], v] for k, v in LEGENDA.items()] + [[k, c, v] for k, c, v in LEGENDA_PARTES]
    if ex.ativo:
        rows.append(['cinza tracejado', '#999999', 'comando, tabela, programa, origem ou destino que nenhum cenário da análise dinâmica executou'])
    return T('Cores dos nós nos diagramas', ['Tipo', 'Cor', 'O que significa'], rows)


# ----------------------------------------------------------------------------- fase 4b
def _um_toggle(blocos):
    """O checkbox da seção fica só no primeiro diagrama que tem item não executado; os demais seguem o mesmo estado."""
    ja = False
    for b in blocos:
        if b and b.get('type') == 'graph' and any(n.get('inactive') for n in b['nodes']):
            if ja:
                b['sem_toggle'] = True
            ja = True


def m_resumo(r, ctx):
    cmds = r['commands']
    sm = r['summary']
    classes = r.get('classes') or {}
    chamadas = r.get('chamadas') or []
    ex = Exec(ctx, cmds)
    arestas, por_id = _encadeamento(cmds, cmds, ex)
    por_prog = defaultdict(list)
    for c in cmds:
        por_prog[c['programa']].append(c)
    idx = []
    desc = []
    for p in sorted(por_prog):
        cs = por_prog[p]
        n_ex = sum(1 for c in cs if ex.cmd(c))
        idx.append([with_links(p, [link('abrir', PHASE, 'rp-' + p)]), classes.get(p, ''), len(cs), (f'{n_ex} de {len(cs)}' if ex.ativo else ''), ', '.join(sorted({c['tabela'] for c in cs})),
                    sum(1 for c in cs for e in c['entradas'] if e['grupo'] == 'where'), sum(1 for c in cs for e in c['entradas'] if e['grupo'] == 'campos'), sum(len(c['saidas']) for c in cs)])
        desc.append(ex.ativo and n_ex == 0)
    cols = ['Programa', 'Classe', 'Comandos SQL', 'Executados pela análise dinâmica', 'Tabelas', 'Condições WHERE', 'Campos como parâmetro', 'Colunas lidas']
    if not ex.ativo:
        cols.pop(3)
        idx = [i[:3] + i[4:] for i in idx]
    secs = [S('leitura', 'Como ler', [],
              'Relatório gerado por script (nenhuma IA), a partir da fase 4. Cada programa tem: (1) a relação com os programas que o chamam, os que ele chama, seus comandos SQL e as tabelas; '
              '(2) o encadeamento entre os comandos (qual lê o que outro usa; qual só executa conforme o status de outro); (3) UM diagrama com o fluxo de dados de todos os comandos SQL do programa: '
              'de onde vem cada condição (WHERE) e cada campo como parâmetro (VALUES do INSERT, SET do UPDATE) até a origem mais distante com base na entrada, amarrada ao trecho do SQL, '
              'e para onde vai cada coluna lida; e as tabelas com o mesmo conteúdo, com as condições. '
              + ('O que nenhum cenário da análise dinâmica executou aparece em cinza tracejado e pode ser escondido pelo checkbox da seção. ' if ex.ativo else 'Sem execução dinâmica nesta análise: nada é marcado como não executado. ')
              + 'Resume a fase 4 sem substituí-la (os links levam ao comando na fase 4).'),
            S('indice', 'Programas', [T('Programas com comandos SQL', cols, idx, descartadas=desc if ex.ativo else None)])]
    for p in sorted(por_prog):
        cs = por_prog[p]
        g_rel = _grafo_programa(p, cs, chamadas, classes, ex)
        g_enc, t_enc = _grafo_encadeamento(p, cs, arestas, por_id, ex)
        g_fl = _grafo_fluxo(p, cs, ex)
        _um_toggle([g_rel, g_enc, g_fl])
        blocos = [_tabela_comandos(p, cs, ex, arestas, por_id), g_rel]
        if g_enc:
            blocos.append(g_enc)
        blocos.append(g_fl)
        blocos += _tabelas_entradas(p, cs, ex) + _tabela_saidas(p, cs, ex)
        n_ex = sum(1 for c in cs if ex.cmd(c))
        secs.append(S(f'rp-{p}', f'Programa {p}', blocos, f'{len(cs)} comandos SQL' + (f', {n_ex} executados pela análise dinâmica.' if ex.ativo else '.')))
    cards = [card('programas', len(por_prog)), card('comandos SQL', sm['comandos'])] + ([card('comandos executados', sum(1 for c in cmds if ex.cmd(c)))] if ex.ativo else []) + [
        card('tabelas', sm['tabelas']), card('entradas (WHERE e campos)', sm['entradas']), card('origens (alternativas)', sm['alternativas']), card('colunas lidas', sm['saidas']),
        card('com transformação', sm['com_transformacao']), card('escolhidas por condição', sm['escolhidas_por_condicao'])]
    return model('Fase 4b — Resumo da linhagem de dados', 'Por programa: relação com chamadas, comandos SQL e tabelas; encadeamento; fluxo de dados de todos os comandos (entrada e saída) com as condições.', cards, secs)


# ----------------------------------------------------------------------------- fase 4c
def _grafo_func(f, classes):
    nos = [{'id': 'f', 'col': 0, 'label': f['id'], 'sub': f['tipo'], 'detail': f'funcionalidade {f["id"]} ({f["tipo"]}); programas: {", ".join(f["programas"])}', 'cor': _cor_prog(classes, f['id'])}]
    arestas, tab = [], {}
    for c in f['comandos']:
        nid = 'q-' + c['id']
        nos.append({'id': nid, 'col': 1, 'label': _nm(c), 'sub': f'{c["programa"]}@{c["linha"]} · {c["natureza"]}', 'detail': f'{c["id"]} ({c["natureza"]})',
                    'cor': COR_GRAVA if c['natureza'] == 'gravação' else COR_LEITURA})
        arestas.append({'from': 'f', 'to': nid})
        tid = 't-' + c['tabela']
        if tid not in tab:
            tab[tid] = True
            nos.append({'id': tid, 'col': 2, 'label': c['tabela'], 'sub': 'tabela', 'detail': c['tabela'], 'cor': NEUTRA})
        arestas.append({'from': nid, 'to': tid})
    for c in f['chamadas_funcionalidades']:
        nid = 'x-' + str(c['para'])
        if not any(n['id'] == nid for n in nos):
            nos.append({'id': nid, 'col': 1, 'label': str(c['para']), 'sub': 'chama funcionalidade', 'detail': f'{c["de"]}@{c["linha"]} chama {c["para"]} por {c["mecanismo"]} (área {c["area"]})',
                        'cor': _cor_prog(classes, c['para'])})
            arestas.append({'from': 'f', 'to': nid})
    return _grafo(f'{f["id"]}: comandos SQL e chamadas a outras funcionalidades', ['Funcionalidade', 'Comando SQL ou funcionalidade chamada', 'Tabela'], nos, arestas,
                  'Comando SQL: verde-água lê, roxo grava. Funcionalidade chamada: cor da classe do programa que a atende.', nw=230)


