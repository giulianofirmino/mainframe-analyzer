"""Mapa de transformação de dados de cada programa, lido dos TOKENS da AST (nada de regex sobre o fonte, nenhum nome fixo).

Cada instrução que move ou calcula dado vira um fluxo  origem(ns) -> destino:
  MOVE, SET, COMPUTE, ADD/SUBTRACT/MULTIPLY/DIVIDE, STRING/UNSTRING, INITIALIZE, INSPECT,
  EXEC SQL (coluna da tabela -> variável hospedeira no SELECT/FETCH; variável -> coluna no INSERT/UPDATE; variável -> filtro no WHERE),
  CALL/EXEC CICS LINK|XCTL (área enviada e recebida), EXEC CICS RETURN/SEND/RECEIVE/READQ/WRITEQ, leitura/gravação de arquivo.
Cada ponta é {'type': campo|literal|tabela|arquivo|programa|figurativa, 'name', 'group'}; group é o item 01/77 que contém o campo.
Entradas do programa = grupos da LINKAGE SECTION; saídas = grupos da LINKAGE, áreas devolvidas por RETURN COMMAREA e
gravações em tabela/arquivo. Terminal = fluxo cujo destino é uma saída: é o ponto final de alteração do dado."""
from collections import defaultdict

from dependency_map import declared_cursors
from sql_where import predicates, aliases, resolve, resolve_value, role
from io_deduction import RESERVED, FIG_NUM, FIG_STR, is_runtime_name
from token_utils import V, is_sym, find, match_paren, split_top, strip_outer, cics_options, sql_tables, dotted_name, tokens_of, join_tokens

FIG = FIG_NUM | FIG_STR
STOP_WORDS = {'TO', 'FROM', 'INTO', 'BY', 'GIVING', 'REMAINDER', 'ROUNDED', 'ON', 'SIZE', 'ERROR', 'END-ADD', 'END-COMPUTE',
              'DELIMITED', 'DELIMITER', 'COUNT', 'TALLYING', 'REPLACING', 'CONVERTING', 'POINTER', 'WITH', 'CORRESPONDING', 'CORR', 'ALL', 'LEADING',
              'FIRST', 'FOR', 'UP', 'DOWN', 'TRUE', 'FALSE', 'NOT', 'BEFORE', 'AFTER', 'INITIAL', 'CHARACTERS'}


class Scope:
    """Nomes declarados de um programa: grupo (01/77) de cada campo, condições 88 e áreas de LINKAGE."""

    def __init__(self, prog):
        dm = prog['data_model']
        self.by = defaultdict(list)
        for it in dm['items']:
            self.by[it['name'].upper()].append(it)
        self.c88 = {k.upper(): v for k, v in dm['conditions_88'].items()}
        self.parent = {}
        for it in dm['items']:
            self.parent.setdefault(it['name'].upper(), (it.get('parent') or '').upper() or None)
        # raiz (01/77) de cada item pela ordem de declaração; FILLER repetido não confunde a subida
        self._root, self._root_item, stack = {}, {}, []
        for it in dm['items']:
            if it['level'] in (66, 88):
                continue
            while stack and stack[-1]['level'] >= it['level']:
                stack.pop()
            if it['level'] in (1, 77):
                stack.clear()
            root = stack[0]['name'].upper() if stack else it['name'].upper()
            self._root.setdefault(it['name'].upper(), root)
            self._root_item[id(it)] = root
            stack.append(it)
        self.linkage = {i['name'].upper() for i in prog['linkage'] if i['level'] != 88}

    def top(self, name, quals=()):
        cands = self.by.get(name, [])
        if len(cands) > 1 and quals:
            for it in cands:
                anc, p, seen = set(), (it.get('parent') or '').upper(), set()
                while p and p not in seen:
                    anc.add(p)
                    seen.add(p)
                    p = self.parent.get(p)
                if set(quals) & anc:
                    return self._root_item.get(id(it), self._root.get(name, name))
        return self._root.get(name, name)

    def declared(self, name):
        return name in self.by or name in self.c88


def refs(toks, sc, stop=STOP_WORDS):
    """Referências a dado (campo, literal, figurativa) na sequência de tokens, na ordem em que aparecem."""
    out, i = [], 0
    while i < len(toks):
        t = toks[i]
        v = V(t)
        if t[0] in ('STRING', 'NUMBER'):
            out.append({'type': 'literal', 'name': t[1], 'group': None})
            i += 1
        elif t[0] == 'IDENT' and v in FIG:
            out.append({'type': 'figurativa', 'name': v, 'group': None})
            i += 1
        elif t[0] == 'IDENT' and v not in RESERVED and v not in stop and (not is_runtime_name(v) or sc.declared(v)):
            name, j = dotted_name(toks, i)
            quals = []
            while j + 1 < len(toks) and V(toks[j]) in ('OF', 'IN') and toks[j + 1][0] == 'IDENT':
                quals.append(V(toks[j + 1]))
                j += 2
            base = name.split('.')[-1]
            grp = name.split('.')[0] if '.' in name else sc.top(base, quals)
            out.append({'type': 'campo', 'name': base, 'group': grp, 'declared': sc.declared(base) or '.' in name})
            i = match_paren(toks, j) + 1 if j < len(toks) and is_sym(toks[j], '(') else j
        elif is_sym(t, '('):
            i = match_paren(toks, i) + 1
        else:
            i += 1
    return out


def fields(rs):
    return [r for r in rs if r['type'] == 'campo']


def lit(text):
    return {'type': 'literal', 'name': text, 'group': None}


# comandos CICS cujas opções com campo são saídas (valor: opções que são entrada do comando)
CICS_OUTPUT_VERBS = {'ASKTIME': set(), 'FORMATTIME': {'ABSTIME'}, 'ASSIGN': set(), 'ADDRESS': set()}


class Flow:
    def __init__(self, prog):
        self.prog, self.lm = prog, prog['linemap']
        self.sc = Scope(prog)
        self.cursors = declared_cursors(prog['text'])
        self.out, self.calls, self.par, self._cursor = [], [], None, None
        self.indicators = {}
        self.commands = []
        self.guards = []

    def command(self, n, op, table, where_toks, cursor=None, sql_toks=None):
        """Comando SQL: tabela, texto, e condições do WHERE (predicados lidos dos tokens, cada um com a tabela resolvida pelo FROM)."""
        sql_toks = list(sql_toks if sql_toks is not None else n.get('tokens') or [])
        al = aliases(sql_toks)
        wh = predicates(where_toks)
        for w in wh:
            w['table'] = resolve(w, al) or (table if len(set(al.values())) <= 1 else '')
            w['value_table'], w['value_field'] = '', ''
            if w.get('value_kind') == 'coluna':
                parts = w['value'].split('.')
                w['value_field'] = parts[-1]
                w['value_table'] = al.get(parts[-2].upper(), '') if len(parts) > 1 else (table if len(set(al.values())) <= 1 else '')
            w['value_resolved'], vt = resolve_value(w['value'], al, table) if w.get('value') else ('', [])
            if w.get('value_kind') == 'coluna' and not w['value_table'] and '.' not in w['value'] and len(set(al.values())) <= 1:
                w['value_resolved'] = (table.split('.')[-1] + '.' + w['value']) if table else w['value']
            w['role'] = role(w, w['table'], vt or ([w['value_table']] if w['value_table'] else []))
        self.commands.append({'line': self.lm.source_line(n['start_line']), 'paragraph': self.par, 'op': op, 'table': table, 'cursor': cursor,
                              'tables': sorted(set(al.values())) or ([table] if table else []), 'sql': join_tokens(sql_toks), 'where': wh})

    @staticmethod
    def _text(n):
        """Comando como está no código, numa linha: 'MOVE A TO B', 'COMPUTE X = Y + 1', 'EXEC SQL ...'."""
        if n.get('args') is not None:
            return ' '.join(f'{n["type"]} {n["args"]}'.split())
        toks = n.get('tokens')
        if toks:
            return ('EXEC SQL ' if n['type'] == 'EXEC_SQL' else 'EXEC CICS ') + join_tokens(list(toks))
        return n['type']

    def add(self, n, op, src, dst, note=None):
        line = self.lm.source_line(n['start_line'])
        text = self._text(n)
        for d in dst:
            self.out.append({'line': line, 'paragraph': self.par, 'op': op, 'from': src, 'to': d, 'note': note, 'cursor': self._cursor, 'guards': list(self.guards), 'text': text})

    def args(self, n):
        return list(n.get('arg_tokens') or [])

    # ------------------------------------------------------------ instruções de dados
    def move(self, n):
        a = self.args(n)
        i = find(a, ('TO',))
        if i >= 0:
            src = refs(a[:i], self.sc)
            self.add(n, 'MOVE', src if any(V(t) in ('CORRESPONDING', 'CORR') for t in a[:i]) else src[:1], fields(refs(a[i + 1:], self.sc)))

    def set_(self, n):
        a = self.args(n)
        i = find(a, ('TO', 'UP', 'DOWN'))
        if i < 0:
            return
        val = V(a[i + 1]) if i + 1 < len(a) else ''
        for t in fields(refs(a[:i], self.sc)):
            c = self.sc.c88.get(t['name'])
            if c:
                p = (c['parent'] or '').upper()
                self.add(n, 'SET', [lit(f'{t["name"]} = {val}')], [{'type': 'campo', 'name': p, 'group': self.sc.top(p), 'declared': True}])
            else:
                self.add(n, 'SET', refs(a[i + 1:], self.sc) or [lit(val)], [t])

    def arith(self, n):
        a, t = self.args(n), n['type']
        g = find(a, ('GIVING',))
        if t == 'COMPUTE':
            i = find(a, ('=',))
            if i >= 0:
                self.add(n, t, fields(refs(a[i + 1:], self.sc)), fields(refs(a[:i], self.sc)))
            return
        sep = {'ADD': 'TO', 'SUBTRACT': 'FROM', 'MULTIPLY': 'BY', 'DIVIDE': 'INTO'}[t]
        i = find(a, (sep,))
        if i < 0 and t == 'DIVIDE':
            i = find(a, ('BY',))
        if i < 0 and g < 0:
            return
        before = refs(a[:i if i >= 0 else g], self.sc)
        after = refs(a[i + 1:g if g >= 0 else len(a)], self.sc) if i >= 0 else []
        if g >= 0:
            rem = find(a, ('REMAINDER',))
            self.add(n, t, [x for x in before + after], fields(refs(a[g + 1:rem if rem > g else len(a)], self.sc)))
            if rem > g:
                self.add(n, t, fields(before + after), fields(refs(a[rem + 1:], self.sc)))
        else:
            self.add(n, t, before + after, fields(after))

    def string(self, n):
        a = self.args(n)
        i = find(a, ('INTO',))
        if i < 0:
            return
        srcs, j = [], 0
        while j < i:
            if V(a[j]) == 'DELIMITED':
                j += 3 if j + 1 < i and V(a[j + 1]) == 'BY' else 1
                continue
            srcs.append(a[j])
            j += 1
        self.add(n, 'STRING', refs(srcs, self.sc), fields(refs(a[i + 1:], self.sc))[:1])

    def unstring(self, n):
        a = self.args(n)
        i = find(a, ('INTO',))
        if i >= 0:
            self.add(n, 'UNSTRING', refs(a[:i][:1], self.sc), fields(refs(a[i + 1:], self.sc)))

    def initialize(self, n):
        a = self.args(n)
        i = find(a, ('REPLACING', 'WITH'))
        self.add(n, 'INITIALIZE', [lit('valor inicial (PIC/VALUE)')], fields(refs(a[:i] if i >= 0 else a, self.sc)))

    def inspect(self, n):
        a = self.args(n)
        if find(a, ('REPLACING', 'CONVERTING')) >= 0:
            self.add(n, 'INSPECT', [lit('substituição')], fields(refs(a[:1], self.sc)))

    # ------------------------------------------------------------ SQL
    def host(self, toks, i):
        name, j = dotted_name(toks, i + 1)
        if name is None:
            return None, i + 1
        base = name.split('.')[-1]
        r = {'type': 'campo', 'name': base, 'group': name.split('.')[0] if '.' in name else self.sc.top(base), 'declared': self.sc.declared(base) or '.' in name}
        if j < len(toks) and is_sym(toks[j], ':'):
            ind, j = dotted_name(toks, j + 1)
            if ind:
                r['indicator'] = ind.split('.')[-1]
        return r, j

    def hosts(self, toks):
        out, i = [], 0
        while i < len(toks):
            if is_sym(toks[i], ':'):
                r, i = self.host(toks, i)
                if r:
                    out.append(r)
            else:
                i += 1
        return out

    def _ind(self, n, h, column, op):
        """Guarda a variável indicadora de nulo (`:HOST :IND`) com a coluna a que ela se refere."""
        if h.get('indicator'):
            self.indicators.setdefault(h['indicator'], {'column': column, 'host': h['name'], 'op': op, 'line': self.lm.source_line(n['start_line'])})

    def select_columns(self, toks):
        e = find(toks, ('INTO', 'FROM'), 1)
        cols = []
        for it in split_top(toks[1:e if e > 0 else len(toks)], lambda t: t[1] == ','):
            names = [V(t) for t in it if t[0] == 'IDENT' and V(t) != 'AS']
            cols.append(names[-1] if names else '?')
        return cols

    def sql(self, n):
        toks = list(n.get('tokens') or [])
        if not toks:
            return
        verb = V(toks[0])
        self._cursor = None
        tab = lambda name: {'type': 'tabela', 'name': name, 'group': name}
        col = lambda t, c: {'type': 'tabela', 'name': f'{t}.{c}', 'group': t}
        if verb in ('SELECT', 'FETCH'):
            if verb == 'FETCH':
                cn = next((V(t) for t in toks if V(t) in self.cursors), None)
                if not cn:
                    return
                self._cursor = cn
                tables, cols = self.cursors[cn]['tables'], self.select_columns(tokens_of(self.cursors[cn]['sql']))
            else:
                tables, cols = sql_tables(toks), self.select_columns(toks)
            i = find(toks, ('INTO',))
            e = find(toks, ('FROM', 'WHERE', 'FETCH', 'FOR', 'WITH'), i + 1) if i >= 0 else -1
            hs = self.hosts(toks[i + 1:e if e > 0 else len(toks)]) if i >= 0 else []
            t0 = tables[0] if tables else '?'
            for k, h in enumerate(hs):
                self._ind(n, h, col(t0, cols[k] if k < len(cols) else '?')['name'], verb)
                self.add(n, verb, [col(t0, cols[k] if k < len(cols) else '?')], [h])
            if verb == 'FETCH':
                ctoks = tokens_of(self.cursors[cn]['sql'])
                cw = find(ctoks, ('WHERE',))
                self.command(n, verb, t0, ctoks[cw + 1:] if cw >= 0 else [], cn, ctoks)
            else:
                cw = find(toks, ('WHERE',))
                self.command(n, verb, t0, toks[cw + 1:] if cw >= 0 else [])
            w = find(toks, ('WHERE',))
            for h in (self.hosts(toks[w:]) if w >= 0 else []):
                self.add(n, 'FILTRO', [h], [tab(t0)], 'chave de busca')
        elif verb == 'OPEN':
            cn = next((V(t) for t in toks[1:] if V(t) in self.cursors), None)
            if cn:
                self._cursor = cn
                ctoks = tokens_of(self.cursors[cn]['sql'])
                w = find(ctoks, ('WHERE',))
                t0 = (self.cursors[cn]['tables'] or ['?'])[0]
                self.command(n, 'OPEN', t0, ctoks[w + 1:] if w >= 0 else [], cn, ctoks)
                for h in (self.hosts(ctoks[w:]) if w >= 0 else []):
                    self.add(n, 'FILTRO', [h], [tab(t0)], 'chave de busca do cursor ' + cn)
        elif verb == 'CLOSE':
            cn = next((V(t) for t in toks[1:] if V(t) in self.cursors), None)
            if cn:
                ctoks = tokens_of(self.cursors[cn]['sql'])
                self.command(n, 'CLOSE', (self.cursors[cn]['tables'] or ['?'])[0], [], cn, ctoks)
        elif verb == 'INSERT':
            t0 = (sql_tables(toks) or ['?'])[0]
            p = next((i for i, t in enumerate(toks) if is_sym(t, '(')), -1)
            cols = [V(t) for t in toks[p + 1:match_paren(toks, p)] if t[0] == 'IDENT'] if p >= 0 else []
            self.command(n, 'INSERT', t0, [])
            v = find(toks, ('VALUES',))
            for k, h in enumerate(self.hosts(toks[v:] if v >= 0 else toks)):
                self._ind(n, h, col(t0, cols[k] if k < len(cols) else '?')['name'], 'INSERT')
                self.add(n, 'INSERT', [h], [col(t0, cols[k] if k < len(cols) else '?')])
        elif verb in ('UPDATE', 'DELETE'):
            t0 = (sql_tables(toks) or ['?'])[0]
            s, w = find(toks, ('SET',)), find(toks, ('WHERE',))
            self.command(n, verb, t0, toks[w + 1:] if w >= 0 else [])
            if s >= 0:
                for part in split_top(toks[s + 1:w if w > s else len(toks)], lambda t: t[1] == ','):
                    c = next((V(t) for t in part if t[0] == 'IDENT'), '?')
                    eq = next((k for k, t in enumerate(part) if t[1] == '='), -1)
                    src = self.hosts(part) or [lit(join_tokens(part[eq + 1:]) if eq >= 0 else '')]
                    for h_ in src:
                        if h_['type'] == 'campo':
                            self._ind(n, h_, f'{t0}.{c}', 'UPDATE')
                    self.add(n, 'UPDATE', src, [col(t0, c)])
            if w >= 0:
                for h in self.hosts(toks[w:]):
                    self.add(n, 'FILTRO', [h], [tab(t0)], 'chave de ' + ('atualização' if verb == 'UPDATE' else 'exclusão'))
            if verb == 'DELETE':
                self.add(n, 'DELETE', [lit('exclusão de linha')], [tab(t0)])

    # ------------------------------------------------------------ chamadas, CICS e arquivos
    def call_area(self, n, mech, prog_toks, area_toks):
        pr = refs(prog_toks, self.sc)
        target = prog_toks[0][1].strip('\'"').upper() if prog_toks and prog_toks[0][0] == 'STRING' else (pr[0]['name'] if pr else None)
        areas = fields(refs(area_toks, self.sc))
        self.calls.append({'line': self.lm.source_line(n['start_line']), 'paragraph': self.par, 'mechanism': mech, 'program_ref': target, 'areas': [a['name'] for a in areas],
                           'areas_ref': [{'name': a['name'], 'group': a['group']} for a in areas]})
        p = {'type': 'programa', 'name': target or '?', 'group': target or '?'}
        for a in areas:
            self.add(n, mech, [a], [p], 'área enviada')
            self.add(n, mech, [p], [a], 'área devolvida')

    def cics(self, n):
        verb, opts = cics_options(list(n.get('tokens') or []))
        o = {}
        for k, v in opts:
            o.setdefault(k, v)
        if verb in ('LINK', 'XCTL'):
            self.call_area(n, verb, o.get('PROGRAM', []), strip_outer(o.get('COMMAREA', [])))
        elif verb == 'RETURN' and 'COMMAREA' in o:
            ch = {'type': 'programa', 'name': 'CHAMADOR (RETURN)', 'group': 'CHAMADOR (RETURN)'}
            self.add(n, 'RETURN', fields(refs(o['COMMAREA'], self.sc)), [ch], 'área devolvida ao chamador')
        else:
            src = [f for f in fields(refs(o.get('FROM', []), self.sc))]
            dst = [f for k in ('INTO', 'SET') for f in fields(refs(o.get(k, []), self.sc))]
            if verb in CICS_OUTPUT_VERBS:
                # comandos CICS que devolvem valores em várias opções (data, hora, usuário...): toda opção que cita campo recebe o valor, menos as de entrada do verbo
                ins = CICS_OUTPUT_VERBS[verb]
                dst += [f for k, v in o.items() if k not in ins and k not in ('INTO', 'SET') for f in fields(refs(strip_outer(v), self.sc))]
                src += [f for k in ins for f in fields(refs(strip_outer(o.get(k, [])), self.sc))]
            res = {'type': 'programa', 'name': 'CICS ' + verb, 'group': 'CICS ' + verb}
            if src:
                self.add(n, 'CICS ' + verb, src, [res])
            if dst:
                self.add(n, 'CICS ' + verb, [res], dst)

    def call(self, n):
        a = self.args(n)
        u = find(a, ('USING',))
        self.call_area(n, 'CALL', a if u < 0 else a[:u], a[u + 1:] if u >= 0 else [])

    def file_(self, n):
        a = self.args(n)
        name = a[0][1].upper() if a else '?'
        fl = {'type': 'arquivo', 'name': name, 'group': name}
        i, j = find(a, ('INTO',)), find(a, ('FROM',))
        if n['type'] == 'FILE_READ' and i >= 0:
            self.add(n, 'READ', [fl], fields(refs(a[i + 1:], self.sc)))
        if n['type'] in ('FILE_WRITE', 'FILE_REWRITE'):
            self.add(n, n['type'].split('_')[1], fields(refs(a[j + 1:], self.sc)) if j >= 0 else fields(refs(a[:1], self.sc)), [fl])

    HANDLERS = {'MOVE': 'move', 'SET': 'set_', 'COMPUTE': 'arith', 'ADD': 'arith', 'SUBTRACT': 'arith', 'MULTIPLY': 'arith', 'DIVIDE': 'arith',
                'STRING': 'string', 'UNSTRING': 'unstring', 'INITIALIZE': 'initialize', 'INSPECT': 'inspect', 'EXEC_SQL': 'sql', 'EXEC_CICS': 'cics', 'CALL': 'call'}

    def walk(self, body):
        for n in body:
            t = n['type']
            if t == 'LABEL':
                self.par = n['name'].upper()
            elif t in self.HANDLERS:
                getattr(self, self.HANDLERS[t])(n)
            elif t.startswith('FILE_'):
                self.file_(n)
            ctext = ' '.join(str(n.get('condition') or n.get('subject') or '').split())
            for k in ('then', 'else_body', 'body'):
                if isinstance(n.get(k), list):
                    pushed = t == 'IF' and k in ('then', 'else_body')
                    if pushed:
                        self.guards.append({'text': ctext, 'branch': 'then' if k == 'then' else 'else'})
                    self.walk(n[k])
                    if pushed:
                        self.guards.pop()
            for w in n.get('whens', []) or []:
                self.guards.append({'text': 'WHEN ' + ' '.join(str(w.get('condition') or '').split()), 'branch': 'when', 'subject': ctext})
                self.walk(w['body'])
                self.guards.pop()


def program_flow(prog):
    f = Flow(prog)
    f.walk(prog['ast']['body'])
    sc = f.sc
    inputs = sorted({sc.top(x) for x in sc.linkage if x != 'FILLER'})
    returned = {r['group'] for x in f.out if x['op'] == 'RETURN' for r in x['from'] if r['type'] == 'campo'}
    outputs = set(inputs) | returned
    # grupos cujo conteúdo chega a uma saída por MOVE/cálculo entre grupos (a área de trabalho movida para a LINKAGE, por exemplo)
    rev = defaultdict(set)
    for x in f.out:
        if x['to']['type'] == 'campo':
            for s_ in x['from']:
                if s_['type'] == 'campo' and s_['group'] != x['to']['group']:
                    rev[x['to']['group']].add(s_['group'])
    reach, stack = set(), list(outputs)
    while stack:
        g = stack.pop()
        if g not in reach:
            reach.add(g)
            stack.extend(rev.get(g, ()))
    for x in f.out:
        d = x['to']
        x['terminal'] = (d['type'] in ('tabela', 'arquivo') and x['op'] != 'FILTRO') or (d['type'] == 'programa' and x['note'] == 'área enviada') \
            or (d['type'] == 'campo' and d['group'] in reach)
    for k, x in enumerate(f.out):
        x['id'] = f'F{k + 1:04d}'
    return {'program': prog['program'], 'inputs': inputs, 'outputs': sorted(outputs), 'flows': f.out, 'calls': f.calls, 'indicators': f.indicators, 'commands': f.commands,
            'cursors': [{'name': cn, 'line': (f.lm.source_line(c['line']) if c.get('line') else None), 'tables': c['tables'], 'sql': join_tokens(tokens_of(c['sql']))} for cn, c in sorted(f.cursors.items())],
            'undeclared': sorted({r['name'] for x in f.out for r in x['from'] + [x['to']] if r['type'] == 'campo' and not r.get('declared', True)})}


def build(model):
    return {p: program_flow(x) for p, x in model['programs'].items()}
