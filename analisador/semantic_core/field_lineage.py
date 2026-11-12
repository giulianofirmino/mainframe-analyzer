"""Linhagem de dados por campo, entre programas. Só AST, tokens e o fluxo de dados; nenhum nome do código analisado fixado aqui.

O dado é seguido por faixa de bytes, não só por nome: cada campo ocupa uma faixa (raiz 01/77, deslocamento, tamanho) calculada da DATA DIVISION
(PIC, USAGE, OCCURS, REDEFINES). Cada fluxo do data_flow liga faixas de origem à faixa de destino; MOVE que envolve grupo ou buffer copia bytes
(o byte n da origem vai ao byte n do destino); os demais comandos ligam o campo inteiro. CALL e CICS LINK|XCTL ligam a área do chamador à LINKAGE do
chamado (e o caminho de volta) da mesma forma. Assim um buffer genérico (área de comunicação recebida e depois movida para uma estrutura) não
mistura campos: o caminho para trás só segue os bytes que interessam.

Para cada comando SQL que grava (INSERT/UPDATE/DELETE) a linhagem traz, por coluna: o valor gravado, as origens (caminho para trás,
atravessando chamadas de programa até a entrada do entry point, valor fixo, tabela lida ou recurso externo), as chaves de UPDATE/DELETE e o
caminho de decisões (Dnnn) que leva ao comando e as condições do WHERE (uma por predicado: coluna, operador, valor, conector e a origem do campo). Para cada SELECT/FETCH: chaves de busca com suas origens, caminho de decisões e, por coluna
retornada, o destino do dado (caminho para frente: gravação, chave de outra consulta, saída do programa)."""
from collections import defaultdict, deque

from rule_paths import collect_paths, path_conditions, status_commands
from table_roles import reach_by_root

MAX_STATES = 6000
MAX_DEPTH = 80
MAX_ORIGINS = 6
MAX_DEST = 8
MAX_PATHS = 3
BLOCK = 64
WRITE_OPS = ('INSERT', 'UPDATE', 'DELETE')
READ_OPS = ('SELECT', 'FETCH')
CALL_OPS = ('CALL', 'LINK', 'XCTL')
SPECIAL = ('lit', 'tab', 'res')
EXPECTED_ORIGINS = ('valor fixo', 'tabela', 'comando CICS', 'recurso externo', 'entrada do entry point', 'entrada (chamador não analisado)', 'valor inicial (campo nunca atribuído no programa)', 'campo sem declaração (copybook ausente)')


# --------------------------------------------------------------------------- layout em bytes
def _pic_size(pic):
    """(posições em display, dígitos numéricos) de uma PIC, lida caractere a caractere (S, V e P não ocupam posição)."""
    size = digits = 0
    last, i = None, 0
    while i < len(pic):
        c = pic[i]
        if c == '(':
            j = pic.find(')', i)
            k = int(pic[i + 1:j]) if j > i and pic[i + 1:j].isdigit() else 1
            if last:
                size += k - 1
                if last == '9':
                    digits += k - 1
            i = j + 1 if j > i else len(pic)
            continue
        last = None
        if c not in 'SVP':
            size += 1
            last = c
            if c == '9':
                digits += 1
        i += 1
    return size, digits


def _storage(it):
    size, digits = _pic_size((it.get('pic') or '').upper())
    u = (it.get('usage') or '').upper()
    if u in ('COMP-3', 'PACKED-DECIMAL'):
        return digits // 2 + 1
    if u in ('COMP', 'BINARY', 'COMP-4', 'COMP-5'):
        return 2 if digits <= 4 else 4 if digits <= 9 else 8
    if u == 'COMP-1':
        return 4
    if u == 'COMP-2':
        return 8
    return size


def layout(dm):
    """{'spans': {nome: [(raiz, deslocamento, tamanho, é_grupo)]}, 'items': {raiz: [(nome, lo, hi)]}, 'root_len': {raiz: tamanho}}."""
    spans, items, root_len = defaultdict(list), defaultdict(list), {}
    stack, starts, rootof = [], {}, {}

    def close(e):
        length = (e['max_end'] - e['start']) * (e['occurs'] or 1)
        spans[e['name']].append((e['root'], e['start'], length, True))
        if e['name'] != 'FILLER':
            items[e['root']].append((e['name'], e['start'], e['start'] + max(length, 1)))
        if stack:
            par = stack[-1]
            if not e['redef']:
                par['cursor'] = e['start'] + length
            par['max_end'] = max(par['max_end'], e['start'] + length)
        else:
            root_len[e['root']] = max(root_len.get(e['root'], 0), length)
    for it in dm['items']:
        if it['level'] in (66, 88):
            continue
        while stack and stack[-1]['level'] >= it['level']:
            close(stack.pop())
        if it['level'] in (1, 77):
            stack.clear()
        par = stack[-1] if stack else None
        root = par['root'] if par else (rootof.get(it['redefines'], it['redefines']) if it.get('redefines') else it['name'])
        rootof[it['name']] = root
        redef = bool(it.get('redefines'))
        base = par['cursor'] if par else 0
        start = starts.get((root, it['redefines']), base) if redef else base
        starts[(root, it['name'])] = start
        if it.get('pic'):
            length = _storage(it) * (it.get('occurs') or 1)
            spans[it['name']].append((root, start, length, False))
            if it['name'] != 'FILLER':
                items[root].append((it['name'], start, start + max(length, 1)))
            if par:
                if not redef:
                    par['cursor'] = start + length
                par['max_end'] = max(par['max_end'], start + length)
            else:
                root_len[root] = max(root_len.get(root, 0), length)
        else:
            stack.append({'level': it['level'], 'name': it['name'], 'root': root, 'start': start, 'cursor': start, 'max_end': start,
                          'occurs': it.get('occurs'), 'redef': redef})
    while stack:
        close(stack.pop())
    return {'spans': dict(spans), 'items': dict(items), 'root_len': root_len}


class RangeIndex:
    """Arestas indexadas por blocos de bytes de (programa, raiz): consulta por faixa sem varrer tudo."""

    def __init__(self):
        self.b = defaultdict(list)

    def add(self, p, root, lo, hi, e):
        for k in range(lo // BLOCK, max(hi - 1, lo) // BLOCK + 1):
            self.b[(p, root, k)].append(e)

    def query(self, p, root, lo, hi):
        seen, out = set(), []
        for k in range(lo // BLOCK, max(hi - 1, lo) // BLOCK + 1):
            for e in self.b.get((p, root, k), ()):
                if id(e) not in seen:
                    seen.add(id(e))
                    out.append(e)
        return out


# --------------------------------------------------------------------------- grafo
class Graph:
    def __init__(self, model, flows):
        self.model, self.flows = model, flows
        self.progs = model['programs']
        self.lay = {p: layout(x['data_model']) for p, x in self.progs.items()}
        called = {e['target'] for e in model['edges'] if e.get('target') and e['target'] != e['caller']}
        self.entry = {p for p in self.progs if p not in called}
        self.by_dst, self.by_src, self.sinks = RangeIndex(), RangeIndex(), RangeIndex()
        self.special_in = defaultdict(list)
        self.assigned = set()
        self.calls = []
        self.when = {}
        self.whenp = {}
        self.resolved = {}
        for e in model['edges']:
            if e.get('target') in self.progs:
                self.resolved[(e['caller'], self.progs[e['caller']]['linemap'].source_line(e['line']), e['mechanism'])] = e['target']
        self._flows_edges()
        self._bridges()

    # ---- faixas
    def rng(self, p, ref):
        """(programa, raiz, lo, hi, é_grupo) do campo; campo sem declaração vira uma faixa própria de 1 byte."""
        sp = self.lay[p]['spans'].get(ref['name'])
        if sp:
            s = next((x for x in sp if x[0] == ref['group']), sp[0])
            return (p, s[0], s[1], s[1] + max(s[2], 1), s[3])
        return (p, '?' + str(ref['name']), 0, 1, False)

    def name_at(self, p, root, lo, hi):
        """Nome do item declarado que melhor descreve a faixa: o menor que a contém; senão o de maior interseção."""
        its = self.lay[p]['items'].get(root)
        if not its:
            return root[1:] if root.startswith('?') else root
        cont = [x for x in its if x[1] <= lo and hi <= x[2]]
        if cont:
            return min(cont, key=lambda x: (x[2] - x[1], x[1]))[0]
        best = max(its, key=lambda x: (min(hi, x[2]) - max(lo, x[1]), -(x[2] - x[1])))
        return best[0]

    def label(self, st):
        if st[0] in SPECIAL:
            return st[2] if st[0] == 'lit' else st[1]
        p, root, lo, hi = st
        n = self.name_at(p, root, lo, hi)
        return f'{p} · {n}' + ('' if n == root or root.startswith('?') else f' ({root})')

    def _edge(self, dst, src, shift, p, f, kind, op=None, line=None, paragraph=None, text=None):
        e = {'dst': dst, 'src': src, 'shift': shift, 'program': p, 'paragraph': paragraph if paragraph is not None else (f or {}).get('paragraph'),
             'line': line if line is not None else (f or {}).get('line'), 'op': op or (f or {}).get('op'), 'kind': kind,
             'text': text if text is not None else (f or {}).get('text') or '', 'flow': f'{p}.{f["id"]}' if f and f.get('id') else None, 'terminal': bool(f and f.get('terminal')), 'guards': (f or {}).get('guards') or []}
        d = dst
        self.assigned.add((d[0], d[1]))
        self.by_dst.add(d[0], d[1], d[2], d[3], e)
        if src[0] not in SPECIAL:
            self.by_src.add(src[0], src[1], src[2], src[3], e)
        else:
            self.special_in[(d[0], d[1])].append(e)

    def _flows_edges(self):
        for p, fl in self.flows.items():
            for f in fl['flows']:
                d = f['to']
                if d['type'] != 'campo':
                    for s in f['from']:
                        if s['type'] == 'campo':
                            r = self.rng(p, s)
                            self.sinks.add(p, r[1], r[2], r[3], (p, f, r[2], r[3]))
                    continue
                if f['op'] in CALL_OPS + ('RETURN',) and f['note'] == 'área devolvida' and (p, f['line'], f['op']) in self.resolved:
                    continue
                dr = self.rng(p, d)
                for s in f['from']:
                    if s['type'] == 'campo':
                        sr = self.rng(p, s)
                        copy = f['op'] == 'MOVE' and not sr[1].startswith('?') and (sr[4] or dr[4] or sr[3] - sr[2] != dr[3] - dr[2])
                        if copy:
                            n = min(sr[3] - sr[2], dr[3] - dr[2])
                            self._edge((p, dr[1], dr[2], dr[2] + n), (p, sr[1], sr[2], sr[2] + n), sr[2] - dr[2], p, f, 'fluxo')
                        else:
                            self._edge(dr[:4], sr[:4], None, p, f, 'fluxo')
                        continue
                    if s['type'] in ('literal', 'figurativa'):
                        sn = ('lit', p, str(s['name']))
                    elif s['type'] == 'tabela':
                        sn = ('tab', s['name'])
                    elif s['type'] == 'programa':
                        sn = ('res', s['name'])
                    else:
                        continue
                    self._edge(dr[:4], sn, None, p, f, 'fluxo')

    def _bridges(self):
        for p, fl in sorted(self.flows.items()):
            for c in fl['calls']:
                t = self.resolved.get((p, c['line'], c['mechanism']))
                if not t:
                    continue
                cal = self.progs[t]
                params = list(cal['ast'].get('procedure_using') or [])
                if c['mechanism'] != 'CALL':
                    ll = self.lay[t]['spans']
                    params = ['DFHCOMMAREA'] if 'DFHCOMMAREA' in ll else [i['name'] for i in cal['linkage'] if i['level'] == 1][:1]
                for i, a in enumerate(c.get('areas_ref') or []):
                    if i >= len(params):
                        break
                    prm = params[i]
                    ra = self.rng(p, a)
                    sp_b = next((s for s in self.lay[t]['spans'].get(prm, []) if s[0] == prm), None)
                    if not sp_b:
                        continue
                    n = min(ra[3] - ra[2], max(sp_b[2], 1))
                    self.calls.append({'caller': p, 'callee': t, 'mechanism': c['mechanism'], 'line': c['line'], 'paragraph': c['paragraph'], 'area': a['name'],
                                       'area_bytes': ra[3] - ra[2], 'param': prm, 'param_bytes': sp_b[2]})
                    self._edge((t, prm, 0, n), (p, ra[1], ra[2], ra[2] + n), ra[2], f'{p}→{t}', None, 'chamada', c['mechanism'], c['line'], c['paragraph'], f"{c['mechanism']} {t}: área {a['name']} de {p} vira {prm} de {t}")
                    self._edge((p, ra[1], ra[2], ra[2] + n), (t, prm, 0, n), -ra[2], f'{t}→{p}', None, 'retorno', c['mechanism'], c['line'], c['paragraph'], f"retorno de {t}: {prm} volta para a área {a['name']} de {p}")

    # ---- passos
    def _step(self, e, a, b):
        return {'program': e['program'], 'paragraph': e['paragraph'], 'line': e['line'], 'op': e['op'], 'kind': e['kind'],
                'from': self.label(a), 'to': self.label(b), 'text': e.get('text') or '', 'flow': e['flow'], 'guards': e.get('guards') or [], 'when': self.when.get((e['program'], e['line']), ''), 'when_conds': self.whenp.get((e['program'], e['line']), [])}

    def _chain(self, st, pred, forward=False):
        steps = []
        while st in pred:
            nxt, e = pred[st]
            steps.append(self._step(e, st, nxt) if not forward else self._step(e, nxt, st))
            st = nxt
        return steps if not forward else steps[::-1]

    def origin_kind(self, st):
        if st[0] == 'lit':
            return 'valor fixo'
        if st[0] == 'tab':
            return 'tabela'
        if st[0] == 'res':
            return 'comando CICS' if str(st[1]).startswith('CICS ') else 'recurso externo'
        p, root = st[0], st[1]
        if root.startswith('?'):
            return 'campo sem declaração (copybook ausente)'
        if root in self.flows[p]['inputs']:
            return 'entrada do entry point' if p in self.entry else 'entrada (chamador não analisado)'
        if (p, root) not in self.assigned:
            return 'valor inicial (campo nunca atribuído no programa)'
        return 'origem não rastreada'

    def _incoming(self, st):
        p, root, lo, hi = st
        out = []
        for e in self.by_dst.query(p, root, lo, hi):
            d = e['dst']
            a, b = max(lo, d[2]), min(hi, d[3])
            if d[0] == p and d[1] == root and a < b:
                if e['shift'] is None:
                    out.append((e, e['src']))
                else:
                    s = e['src']
                    out.append((e, (s[0], s[1], a + e['shift'], b + e['shift'])))
        for e in self.special_in.get((p, root), ()):
            d = e['dst']
            if max(lo, d[2]) < min(hi, d[3]):
                out.append((e, e['src']))
        return out

    def _outgoing(self, st):
        p, root, lo, hi = st
        out = []
        for e in self.by_src.query(p, root, lo, hi):
            s = e['src']
            a, b = max(lo, s[2]), min(hi, s[3])
            if s[0] == p and s[1] == root and a < b:
                d = e['dst']
                out.append((e, d if e['shift'] is None else (d[0], d[1], a - e['shift'], b - e['shift'])))
        return out

    def _reaching(self, inc, st, use):
        """Ordem de execução: no mesmo parágrafo do uso, uma atribuição incondicional (sem IF/WHEN em volta) que cobre toda a faixa e vem antes do uso
        encerra as atribuições anteriores do mesmo parágrafo: elas não chegam ao uso. Fora desse caso (outro parágrafo, atribuição condicional,
        laço) nada é descartado."""
        if not use or use[0] != st[0] or use[1] is None:
            return inc
        _p, uline, upar = use
        lo, hi = st[2], st[3]

        def same(e):
            return e['program'] == st[0] and e['paragraph'] == upar and e['line'] is not None and e['kind'] == 'fluxo'
        kills = [e['line'] for e, _s in inc if same(e) and e['line'] < uline and not e['guards'] and e['dst'][2] <= lo and hi <= e['dst'][3]]
        if not kills:
            return inc
        w = max(kills)
        return [(e, s) for e, s in inc if not (same(e) and e['line'] < w)]

    def trace_back(self, starts, at=None):
        """Origens das faixas `starts` (caminho para trás, atravessando chamadas): [{'kind','name','steps','when','expected'}], as mais próximas primeiro.
        `at` = (programa, linha, parágrafo) do comando que usa o dado, para respeitar a ordem de execução (ver _reaching)."""
        pred, seen, q, origins, keys = {}, set(starts), deque((s, 0) for s in starts), [], set()
        use = {s: at for s in starts}
        while q and len(seen) < MAX_STATES and len(origins) < MAX_ORIGINS:
            st, d = q.popleft()
            stop = st[0] in SPECIAL or (st[1] in self.flows[st[0]]['inputs'] and st[0] in self.entry)
            inc = [] if stop or d >= MAX_DEPTH else self._reaching(self._incoming(st), st, use.get(st))
            if not inc:
                k = (self.origin_kind(st), self.label(st))
                if k not in keys:
                    keys.add(k)
                    steps = self._chain(st, pred)
                    origins.append({'kind': k[0], 'name': k[1], 'steps': steps, 'when': steps[0]['when'] if steps else '', 'when_conds': steps[0]['when_conds'] if steps else [],
                                    'expected': k[0] in EXPECTED_ORIGINS})
                continue
            for e, src in inc:
                if src not in seen:
                    seen.add(src)
                    pred[src] = (st, e)
                    use[src] = (e['program'], e['line'], e['paragraph']) if e['kind'] == 'fluxo' and e['program'] == src[0] else None
                    q.append((src, d + 1))
        return origins

    def trace_forward(self, start):
        """Destinos do dado da faixa `start` (caminho para frente): gravação em tabela, chave de consulta, saída do programa."""
        pred, seen, q, dests, keys = {}, {start}, deque([(start, 0)]), [], set()

        def add(kind, name, prog, line, op, flow, st, text=''):
            k = (kind, name, prog, line)
            if k not in keys and len(dests) < MAX_DEST:
                keys.add(k)
                dests.append({'kind': kind, 'name': name, 'program': prog, 'line': line, 'op': op, 'flow': flow, 'text': text, 'steps': self._chain(st, pred, forward=True)})
        leaves = []
        while q and len(seen) < MAX_STATES and len(dests) < MAX_DEST:
            st, d = q.popleft()
            p, root, lo, hi = st
            outs = self._outgoing(st)
            if not outs and not self.sinks.query(p, root, lo, hi):
                leaves.append(st)
            for p2, f, slo, shi in self.sinks.query(p, root, lo, hi):
                dst = f['to']
                if p2 == p and max(lo, slo) < min(hi, shi):
                    kind = 'chave de consulta' if f['op'] == 'FILTRO' else 'gravação' if dst['type'] in ('tabela', 'arquivo') else 'envio'
                    add(kind, dst['name'], p, f['line'], f['op'], f'{p}.{f["id"]}', st, f.get('text') or '')
            if d >= MAX_DEPTH:
                continue
            for e, nxt in self._outgoing(st):
                if e['terminal'] and e['kind'] == 'fluxo':
                    add('saída do programa', self.label(nxt), nxt[0], e['line'], e['op'], e['flow'], st, e.get('text') or '')
                if nxt not in seen:
                    seen.add(nxt)
                    pred[nxt] = (st, e)
                    q.append((nxt, d + 1))
        if not dests:
            # sem saída do programa, gravação ou chave: mostra onde o rastro termina (campo final), para a lacuna ficar explícita
            for st in leaves[:3]:
                if st != start:
                    add('fim do caminho (sem saída do programa)', self.label(st), st[0], '', '', '', st)
        return dests


def final_role(kinds):
    """Papel final do campo testado, pela origem do dado seguida por faixa de bytes até onde ele nasce."""
    ks = set(kinds)
    if not ks:
        return 'origem não rastreada'
    if ks == {'origem não rastreada'}:
        return 'origem não rastreada'
    if 'origem não rastreada' in ks:
        return 'origem parcialmente não rastreada: ' + ', '.join(sorted(ks - {'origem não rastreada'}))
    if len(ks) == 1:
        return {'entrada do entry point': 'derivado da entrada do entry point', 'entrada (chamador não analisado)': 'derivado de entrada (chamador não analisado)',
                'tabela': 'derivado de tabela lida', 'valor fixo': 'constante do programa', 'valor inicial (campo nunca atribuído no programa)': 'valor inicial do campo',
                'comando CICS': 'derivado de comando CICS', 'recurso externo': 'derivado de recurso externo', 'campo sem declaração (copybook ausente)': 'derivado de área sem declaração (copybook ausente)'}.get(next(iter(ks)), next(iter(ks)))
    return 'misto: ' + ', '.join(sorted(ks))


def refine_condition_roles(g, rules, dmaps):
    """Papel fino dos campos testados nas condições das regras (o papel grosso, 'atribuído no programa', 'derivado da entrada' ou 'sem atribuição', continua):
    segue o campo por faixa de bytes até a origem (g.trace_back) e acrescenta `origin_kinds`, `origin_names` e `final_role` a cada campo."""
    for p, d in rules.items():
        line_of = {r['code']: r['source_line'] for r in (dmaps.get(p) or {}).get('rows', []) if r.get('code')}
        for r in d['rules']:
            for c in r['condition_fields']:
                if c['role'] not in ('atribuído no programa', 'derivado da entrada', 'sem atribuição', 'entrada') or p not in g.progs:
                    continue
                os_ = g.trace_back([g.rng(p, {'name': c['field'], 'group': c.get('group')})[:4]], (p, line_of.get(c.get('decision')), None))
                c['origin_kinds'] = sorted({o['kind'] for o in os_})
                c['origin_names'] = [f'{o["kind"]}: {o["name"]}' for o in os_]
                c['final_role'] = final_role(c['origin_kinds'])


# --------------------------------------------------------------------------- registros por comando SQL
def _use_of(dests):
    """Uso da coluna retornada no código: 'usada' (chega a gravação, chave de outra consulta, envio ou saída do programa), 'só chega a campo que não sai
    do programa' (o rastro termina em campo) ou 'sem uso no código' (o campo que recebe não é lido em lugar nenhum)."""
    if not dests:
        return 'sem uso no código'
    return 'usada' if any(not d['kind'].startswith('fim do caminho') for d in dests) else 'só chega a campo que não sai do programa'


def _col(name):
    return name.rsplit('.', 1)[-1] if '.' in name else name


def _sql_list(p, fl, tables, eps):
    """Todos os comandos SQL do programa por tabela: SELECT, INSERT, UPDATE e DELETE, com o texto e o WHERE. Cursor: o SELECT do DECLARE é montado
    e associado aos OPEN/FETCH/CLOSE do fluxo (o FETCH tem o mesmo id da linhagem)."""
    cmds = fl.get('commands', [])
    cursors = {c['name']: c for c in fl.get('cursors', [])}

    def ident(line, t):
        return f'{p}@{line}:{_col(t)}'
    for c in cmds:
        if c['cursor'] or c['op'] not in ('SELECT', 'INSERT', 'UPDATE', 'DELETE'):
            continue
        for t in c['tables'] or [c['table']]:
            tables[t]['sql'].append({'id': ident(c['line'], t), 'program': p, 'line': c['line'], 'paragraph': c['paragraph'], 'statement': c['op'], 'cursor': None,
                                     'table': t, 'sql': c['sql'], 'where': [w for w in c['where']], 'associated': [], 'entry_points': eps})
    for cn, cur in sorted(cursors.items()):
        use = [c for c in cmds if c['cursor'] == cn]
        if not use and not cur['line']:
            continue
        for t in cur['tables']:
            assoc = [{'statement': c['op'], 'line': c['line'], 'paragraph': c['paragraph'], 'id': ident(c['line'], c['table'])} for c in sorted(use, key=lambda c: (c['line'], c['op']))]
            wh = next((c['where'] for c in use if c['op'] == 'FETCH'), None) or next((c['where'] for c in use), [])
            tables[t]['sql'].append({'id': ident(cur['line'] or 0, t), 'program': p, 'line': cur['line'], 'paragraph': None, 'statement': 'SELECT', 'cursor': cn, 'table': t,
                                     'sql': cur['sql'], 'where': list(wh), 'associated': assoc, 'entry_points': eps})


def _when_text(dmap, paths):
    """Condição em que a linha executa, a partir do(s) caminho(s) de decisão mais curto(s): 'se COND e senão (COND)'. Vazio = sempre."""
    outs = []
    for path in sorted(paths, key=lambda x: (len(x), x))[:2]:
        cs = path_conditions(dmap, path)
        txt = ' e '.join(('se ' if c['result'] == 'Sim' else 'senão ') + (c['condition'] if c['result'] == 'Sim' else f'({c["condition"]})') for c in cs)
        if not txt:
            return ''
        if txt not in outs:
            outs.append(txt)
    return ' OU '.join(outs)


def _with_sql(stat, conds):
    """Cópia das condições; a de teste de status (SQLCODE, EIBRESP...) leva o comando SQL/CICS de que ela testa o status (`sql`)."""
    return [{**c, **({'sql': stat[c['code']]} if c.get('code') in stat else {})} for c in conds]


def build(model, flows, dmaps=None, rules=None):
    dmaps = dmaps or {}
    g = Graph(model, flows)
    stats = {p: status_commands(model['programs'][p], dmaps.get(p)) for p in flows}
    for p, fl in sorted(flows.items()):
        lines = {f['line'] for f in fl['flows'] if f.get('line')}
        if not lines:
            continue
        hits_all, _e = collect_paths(model['programs'][p], {ln: [ln] for ln in lines})
        for ln, paths in hits_all.items():
            g.when[(p, ln)] = _when_text(dmaps.get(p), paths)
            if paths:
                g.whenp[(p, ln)] = _with_sql(stats[p], [{'code': c['code'], 'condition': c['condition'], 'result': c['result'], 'line': c.get('line'), 'program': p} for c in path_conditions(dmaps.get(p), min(paths, key=lambda x: (len(x), x)))])
    roots = reach_by_root(model['edges'], set(model['programs']))
    eps = lambda p: sorted(r for r, seen in roots.items() if p in seen)
    tables = defaultdict(lambda: {'writes': [], 'reads': [], 'sql': []})
    for p, fl in sorted(flows.items()):
        prog = model['programs'][p]
        _sql_list(p, fl, tables, eps(p))
        sql = [f for f in fl['flows'] if f['op'] in WRITE_OPS + READ_OPS + ('FILTRO',) and (f['to']['type'] == 'tabela' or f['from'] and f['from'][0]['type'] == 'tabela')]
        if not sql:
            continue
        by_line = defaultdict(list)
        for f in sql:
            by_line[f['line']].append(f['line'])
        hits, _ends = collect_paths(prog, by_line)
        open_keys = defaultdict(list)
        for f in fl['flows']:
            if f['op'] == 'FILTRO' and f.get('cursor'):
                open_keys[f['cursor']].append(f)
        stm = defaultdict(list)
        for f in sql:
            t = f['to']['group'] if f['to']['type'] == 'tabela' else f['from'][0]['group']
            stm[(f['line'], t, f['op'] if f['op'] in WRITE_OPS else ('SELECT' if f['op'] in READ_OPS else 'FILTRO'), f.get('cursor'))].append(f)
        start = lambda ref: g.rng(p, ref)[:4]
        for (line, t, kind, cur), fs in sorted(stm.items(), key=lambda x: (x[0][0], x[0][1], x[0][2], x[0][3] or '')):
            if kind == 'FILTRO':
                continue
            paths = sorted(hits.get(line, ()), key=lambda x: (len(x), x))[:MAX_PATHS]
            conds = [_with_sql(stats[p], path_conditions(dmaps.get(p), path)) for path in paths]
            keys_f = [x for x in fl['flows'] if x['op'] == 'FILTRO' and x['line'] == line and x['to']['group'] == t] if not cur else open_keys.get(cur, [])
            keys = [{'field': k['from'][0]['name'], 'group': k['from'][0]['group'], 'flow': f'{p}.{k["id"]}', 'line': k['line'], 'note': k['note'],
                     'origins': g.trace_back([start(k['from'][0])], (p, line, fs[0]['paragraph']))} for k in keys_f if k['from'] and k['from'][0]['type'] == 'campo']
            uniq, seen_k = [], set()
            for k in keys:
                if (k['field'], k['note']) not in seen_k:
                    seen_k.add((k['field'], k['note']))
                    uniq.append(k)
            keys = uniq
            cmd = next((c for c in fl.get('commands', []) if c['line'] == line and c['table'] == t and c['cursor'] == cur), None)
            by_host = {}
            for k in keys:
                by_host.setdefault(k['field'], k['origins'])
            where = [{**w, 'origins': [o for h in w['hosts'] for o in by_host.get(h, [])]} for w in (cmd['where'] if cmd else [])]
            rec = {'id': f'{p}@{line}:{_col(t)}', 'program': p, 'line': line, 'paragraph': fs[0]['paragraph'], 'statement': kind, 'cursor': cur, 'table': t,
                   'entry_points': eps(p), 'conditions': conds, 'where': where, 'keys': keys}
            if kind in WRITE_OPS:
                rec['columns'] = []
                for f in fs:
                    if f['op'] == 'DELETE':
                        continue
                    srcs = [start(s) for s in f['from'] if s['type'] == 'campo']
                    lits = [s for s in f['from'] if s['type'] in ('literal', 'figurativa')]
                    origins = [{'kind': 'valor fixo', 'name': s['name'], 'steps': []} for s in lits] + (g.trace_back(srcs, (p, line, fs[0]['paragraph'])) if srcs else [])
                    rec['columns'].append({'column': _col(f['to']['name']), 'op': f['op'], 'flow': f'{p}.{f["id"]}',
                                           'value': ', '.join(s['name'] for s in f['from']), 'origins': origins})
                slot = 'writes'
            else:
                rec['returns'] = []
                for f in fs:
                    if f['to']['type'] != 'campo':
                        continue
                    dests = g.trace_forward(start(f['to']))
                    rec['returns'].append({'column': _col(f['from'][0]['name']), 'host': f['to']['name'], 'flow': f'{p}.{f["id"]}', 'destinations': dests,
                                           'use': _use_of(dests)})
                slot = 'reads'
            tables[t][slot].append(rec)
    for t, v in tables.items():
        recs = {r['id']: r for r in v['writes'] + v['reads']}
        for e in v['sql']:
            ids = [e['id']] + [a['id'] for a in e['associated'] if a['statement'] == 'FETCH']
            rec = next((recs[i] for i in ids if i in recs), None)
            if rec:
                e['where'] = rec['where']
            else:
                e['where'] = [{**w, 'origins': []} for w in e['where']]
        v['sql'].sort(key=lambda e: (e['program'], e['line'] or 0, e['statement']))
    if rules:
        refine_condition_roles(g, rules, dmaps)
    return {'tables': {t: tables[t] for t in sorted(tables)}, 'calls': sorted(g.calls, key=lambda c: (c['caller'], c['line'], c['callee'])),
            'entry_points': sorted(g.entry),
            'summary': {'tables': len(tables), 'sql': sum(len(v['sql']) for v in tables.values()), 'writes': sum(len(v['writes']) for v in tables.values()), 'reads': sum(len(v['reads']) for v in tables.values()),
                        'call_bridges': len(g.calls)}}
