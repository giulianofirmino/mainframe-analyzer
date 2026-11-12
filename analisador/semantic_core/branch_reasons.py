"""Motivo de cada ramo sem cobertura, calculado pela AST e pelos tokens (sem regex sobre o fonte).

Classes:
  PARAGRAFO_INALCANCAVEL       o parágrafo do ramo nunca é executado a partir do início do programa;
  FLAG_NUNCA_SETADA            a condição 88 do ramo não recebe SET nem MOVE do valor em lugar nenhum do programa;
  TERMINA_ANTES_DE_CHEGAR      todo SET da flag é seguido de encerramento do programa (RETURN ou PERFORM que termina);
  BARRADO_PELO_CHAMADOR        um chamador já testa o mesmo campo (de onde vem o dado) e encerra antes de chamar;
  DEPENDE_DE_STATUS_EXTERNO    o ramo depende de SQLCODE/EIBRESP/status de arquivo: falta db2_status/cics_status/file_status;
  PROGRAMA_NAO_EXECUTADO       nenhum cenário executa o programa (só mock);
  FALTA_CENARIO                alcançável e sem impedimento estático: falta um cenário com as entradas/tabelas certas.
"""
from token_utils import tokens_of, V
import slice_reach as sr

DESCRICAO = {
    'PARAGRAFO_INALCANCAVEL': 'O parágrafo deste ramo não é executado a partir do início do programa (nenhum PERFORM o alcança).',
    'FLAG_NUNCA_SETADA': 'A condição 88 deste ramo nunca recebe SET nem MOVE do valor no programa: o ramo só existiria com dado externo.',
    'TERMINA_ANTES_DE_CHEGAR': 'Todo SET desta flag é seguido de encerramento do programa (RETURN); nenhum caminho volta a testar a flag.',
    'BARRADO_PELO_CHAMADOR': 'Um chamador testa o mesmo dado e encerra antes de chamar este programa: o ramo é inalcançável por esse caminho.',
    'DEPENDE_DE_STATUS_EXTERNO': 'O ramo depende de um status externo (SQLCODE, EIBRESP, status de arquivo): use db2_status/cics_status/file_status no comando anterior.',
    'PROGRAMA_NAO_EXECUTADO': 'Nenhum cenário executa este programa de verdade (só mock ou nunca chamado).',
    'MOCKADO_NO_ENTRY_POINT': 'Os cenários deste entry point mockam o programa; a cobertura dele vem dos entry points que o executam de verdade.',
    'FALTA_CENARIO': 'Alcançável e sem impedimento estático: falta um cenário com entradas/tabelas que decidam este lado.',
}
STATUS = {'SQLCODE', 'SQLWARN0', 'SQLSTATE', 'EIBRESP', 'EIBRESP2', 'DFHRESP'}
COMPARE = {'NUMERIC', 'ZEROS', 'ZERO', 'ZEROES', 'SPACES', 'SPACE', 'LOW-VALUES', 'LOW-VALUE'}


def _blocks(body):
    yield body
    for n in body:
        for k in ('then', 'else_body', 'body'):
            if isinstance(n.get(k), list):
                yield from _blocks(n[k])
        for w in n.get('whens', []) or []:
            yield from _blocks(w['body'])


def _idents(text):
    return [V(t) for t in tokens_of(text or '') if t[0] in ('IDENT', 'KEYWORD') and V(t)]


def _terminates(nodes, terminating):
    """Linha do comando que encerra o programa incondicionalmente na lista: EXEC CICS RETURN, PERFORM de parágrafo que
    termina, ou IF cujos dois lados terminam."""
    for n in nodes:
        if n['type'] == 'EXEC_CICS' and (n.get('command') or '').split()[:1] == ['RETURN']:
            return n['start_line']
        if n['type'] == 'PERFORM' and not n.get('inline'):
            sp = sr.perform_spec(n.get('header_tokens') or [], False)
            if sp['target'] and sp['target'].upper() in terminating:
                return n['start_line']
        if n['type'] == 'IF':
            t, e = _terminates(n['then'], terminating), _terminates(n['else_body'], terminating)
            if t and e:
                return t
    return None


class Program:
    def __init__(self, name, prog):
        self.name, self.prog = name, prog
        self.body = prog['ast']['body']
        self.c88 = {k.upper(): v for k, v in prog['data_model']['conditions_88'].items()}
        r = sr.reach(prog)
        self.reached, self.terminating = set(r['labels']), set(r['terminating'])
        self.labels = [(n['start_line'], n['name'].upper()) for n in self.body if n['type'] == 'LABEL']
        self.sets = {}  # flag -> [(linha, linha_que_encerra|None)]
        self.moves = {}  # campo -> [linhas de MOVE literal]
        self.if_nodes = {}
        self.execs = sorted((n['start_line'], n) for n in sr._walk_nodes(self.body) if n['type'] in ('EXEC_SQL', 'EXEC_CICS'))
        for blk in _blocks(self.body):
            for i, n in enumerate(blk):
                if n['type'] == 'IF':
                    self.if_nodes[n['start_line']] = n
                if n['type'] == 'SET':
                    words = [V(t) for t in n.get('arg_tokens') or []]
                    if 'TO' in words and words[words.index('TO') + 1:][:1] == ['TRUE']:
                        for w in words[:words.index('TO')]:
                            if w not in ('OF', 'IN'):
                                self.sets.setdefault(w, []).append((n['start_line'], _terminates(blk[i + 1:], self.terminating)))
                if n['type'] == 'MOVE':
                    words = [V(t) for t in n.get('arg_tokens') or []]
                    if 'TO' in words:
                        for w in words[words.index('TO') + 1:]:
                            self.moves.setdefault(w, []).append(n['start_line'])

    def paragraph(self, line):
        cur = None
        for ln, nm in self.labels:
            if ln <= line:
                cur = nm
        return cur

    def previous_exec(self, line):
        prev = [n for ln, n in self.execs if ln < line]
        return prev[-1] if prev else None

    def source_line(self, line):
        return self.prog['linemap'].source_line(line)

    def snippet(self, line, n=6):
        lines = self.prog['text'].splitlines()
        return [f"{self.source_line(i + 1)}: {lines[i][6:72].rstrip()}" for i in range(max(0, line - 1), min(len(lines), line - 1 + n))]


def classify(model, prog_name, u, executed, programs):
    P = programs[prog_name]
    d = next((x for x in P.prog['decision_tree']['decisions'] if x['decision_id'] == u['decision_id']), None)
    line, branch = u['line'], u['branch']
    ev = []
    par = P.paragraph(line)
    if par and par not in P.reached:
        return 'PARAGRAFO_INALCANCAVEL', [f'parágrafo {par} (linha {P.source_line(line)}) não é alcançado por PERFORM a partir do início'], None
    when = ' '.join(b.get('when') or '' for b in (d or {}).get('branches', []) if b['result'] == branch)
    expr_ids = _idents(u['expression'])
    ids = expr_ids + _idents(when)
    if u['type'] == 'EVALUATE':
        # EVALUATE TRUE WHEN nome-de-condição: a condição é um nome sozinho; EVALUATE campo WHEN valor não tem flag
        wt = [t for t in tokens_of(when) if t[0] != 'EOF']
        flags = [V(wt[0])] if u['expression'].strip().upper() == 'TRUE' and len(wt) == 1 and wt[0][0] in ('IDENT', 'KEYWORD') else []
    else:
        et = tokens_of(u['expression'])
        flags = [w for w in dict.fromkeys(expr_ids) if w in P.c88] or ([expr_ids[0]] if len(et) == 1 and expr_ids else [])
    flags = [f for f in flags if f not in ('TRUE', 'OTHER') and f not in COMPARE]
    positive = branch != 'FALSE' and not u['expression'].upper().lstrip('( ').startswith('NOT ')
    if flags and positive:
        for f in flags:
            parent = ((P.c88.get(f) or {}).get('parent') or '').upper()
            if not P.sets.get(f) and not (parent and P.moves.get(parent)):
                nota = '' if f in P.c88 else ' (nível 88 não declarado neste programa: copybook ausente?)'
                return 'FLAG_NUNCA_SETADA', [f'{f}: nenhum SET {f} TO TRUE' + (f' e nenhum MOVE para {parent}' if parent else '') + ' neste programa' + nota], None
        allsets = [(f, s) for f in flags for s in P.sets.get(f, [])]
        if allsets and all(s[1] for _, s in allsets):
            return 'TERMINA_ANTES_DE_CHEGAR', [f'SET {f} na linha {P.source_line(a)} seguido de encerramento na linha {P.source_line(b)}' for f, (a, b) in allsets], None
    # o chamador já testa o mesmo dado e encerra antes de chamar
    fields = [w for w in ids if w not in P.c88 and w not in COMPARE and w not in STATUS and '-' in w]
    kws = COMPARE & set(ids)
    if fields and kws:
        for cname, C in programs.items():
            if not any(c.get('target') == prog_name for c in C.prog['calls']):
                continue
            for mv in sr._walk_nodes(C.body):
                if mv['type'] != 'MOVE':
                    continue
                words = [V(t) for t in mv.get('arg_tokens') or []]
                if 'TO' not in words or words[words.index('TO') + 1:][:1] not in [[f] for f in fields]:
                    continue
                srcs = [w for w in words[:words.index('TO')] if '-' in w]
                for dd in C.prog['decision_tree']['decisions']:
                    cw = set(_idents(dd['expression']))
                    node = C.if_nodes.get(dd['line'])
                    if srcs and srcs[0] in cw and kws & cw and node and _terminates(node['then'], C.terminating):
                        return 'BARRADO_PELO_CHAMADOR', [f"{cname} testa {srcs[0]} na linha {C.source_line(dd['line'])} ({dd['expression']}) e encerra antes de chamar {prog_name}; o dado chega por {fields[0]}"], None
    if STATUS & set(ids) or any(i.startswith('DFHRESP') for i in ids):
        ex = P.previous_exec(line)
        if ex:
            kind = 'db2_status' if ex['type'] == 'EXEC_SQL' else 'cics_status'
            key = f"{prog_name}:{P.source_line(ex['start_line'])}"
            sug = {kind: {key: {'SQLCODE': '<valor>'} if kind == 'db2_status' else {'EIBRESP': '<valor>'}}}
            return 'DEPENDE_DE_STATUS_EXTERNO', [f"status do comando da linha {P.source_line(ex['start_line'])}"], sug
        return 'DEPENDE_DE_STATUS_EXTERNO', ['status externo sem comando anterior identificado'], None
    if prog_name not in executed:
        return 'PROGRAMA_NAO_EXECUTADO', [], None
    return 'FALTA_CENARIO', [f'campos da condição: {", ".join(fields[:6]) or "(nenhum campo nomeado)"}'], {'inputs_ou_tabelas': fields[:6]}


def analyze(model, uncovered_global, slice_coverage, executed):
    """{'por_programa': {prog: [ramo classificado]}, 'por_entry_point': {ep: {prog: [...]}}, 'resumo': {...}}"""
    programs = {p: Program(p, x) for p, x in model['programs'].items() if not x['infrastructure']}
    cache = {}

    def one(p, u):
        k = (p, u['decision_id'], u['branch'])
        if k not in cache:
            P = programs[p]
            code, evidence, sug = classify(model, p, u, executed, programs)
            cache[k] = {**u, 'source_line': P.source_line(u['line']), 'reason': code, 'explanation': DESCRICAO[code], 'evidence': evidence,
                        'suggestion': sug, 'snippet': P.snippet(u['line'])}
        return cache[k]
    por_prog = {p: [one(p, u) for u in us] for p, us in uncovered_global.items() if p in programs}
    def in_ep(e, p, x, u):
        r = one(p, u)
        if x['exercised'] == 0 and p != e and r['reason'] in ('FALTA_CENARIO', 'DEPENDE_DE_STATUS_EXTERNO', 'PROGRAMA_NAO_EXECUTADO'):
            r = {**r, 'reason': 'MOCKADO_NO_ENTRY_POINT', 'explanation': DESCRICAO['MOCKADO_NO_ENTRY_POINT']}
        return r
    por_ep = {e: {p: [in_ep(e, p, x, u) for u in x['uncovered']] for p, x in ps.items() if p in programs and x['uncovered']} for e, ps in slice_coverage.items()}
    resumo = {}
    for lst in por_prog.values():
        for r in lst:
            resumo[r['reason']] = resumo.get(r['reason'], 0) + 1
    return {'por_programa': por_prog, 'por_entry_point': por_ep, 'resumo': dict(sorted(resumo.items(), key=lambda kv: -kv[1])), 'descricao': DESCRICAO}
