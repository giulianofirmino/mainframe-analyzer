"""Análise estática executada a cada rodada do runtime.

Lê os fontes COBOL da pasta, expande COPY/INCLUDE disponíveis (mantendo mapa de
linhas para o fonte original) e produz, para cada programa: AST, árvore de
decisão, regras, chamadas com destino resolvido, comandos SQL e a
classificação. Também monta o grafo de chamadas e identifica os entry points.
Nada é lido de execuções anteriores.
"""
from __future__ import annotations

import collections
import hashlib
from pathlib import Path

from cobol_token_parser import parse_text
from cobol_data_model import build_data_model
from decision_tree import build as build_tree, business_rules_from_tree
from dependency_map import build as build_dependency_map
from program_classifier import classify_programs
from copybook_resolver import library, expand_file, LineMap
from dclgen_parser import build_catalog as build_dclgen_catalog
from io_deduction import analyze_program, column_categories
from cobol_token_lexer import lex
from token_utils import as_tuple, V, find, strip_outer, string_value, cics_options, sql_tables, join_tokens

SOURCE_EXT = {'.CBL', '.COB'}


def walk(nodes):
    for n in nodes:
        yield n
        for k in ('body', 'then', 'else_body', 'at_end'):
            if isinstance(n.get(k), list):
                yield from walk(n[k])
        for w in n.get('whens', []) or []:
            yield from walk(w.get('body', []))
        for v in (n.get('clauses') or {}).values():
            if isinstance(v, list):
                yield from walk(v)


def discover_sources(root):
    seen, out = {}, []
    for p in sorted(Path(root).rglob('*')):
        if not p.is_file() or p.suffix.upper() not in SOURCE_EXT:
            continue
        data = p.read_bytes()
        if not data.strip():
            continue
        h = hashlib.sha256(data).hexdigest()
        if h in seen:
            continue
        seen[h] = p
        out.append(p)
    return out


def _literais_movidos(ast, nome):
    """Literais que o procedimento move para `nome` (MOVE 'LITERAL' TO nome), sem repetição e na ordem do programa."""
    from dynamic_sql import _atribuicoes, _literal
    out = []
    for a in _atribuicoes(ast).get(nome, []):
        if a['tipo'] == 'MOVE' and _literal(a['fonte']):
            v = a['fonte'][1:-1].strip().upper()
            if v and v not in out:
                out.append(v)
    return out


def _resolve_target(toks, dm, ast=None):
    """Destino de CALL/LINK a partir dos tokens do operando: literal, VALUE da variável no modelo de dados ou, sem VALUE, o único literal que o procedimento move para ela."""
    toks = strip_outer(list(toks or []))
    if not toks:
        return None, 'SEM_DESTINO'
    if len(toks) == 1 and toks[0][0] == 'STRING':
        return string_value(toks[0]).strip().upper(), 'LITERAL'
    if toks[0][0] == 'IDENT':
        it = dm['by_name'].get(V(toks[0]))
        if it is None:
            return None, 'VARIAVEL_NAO_DECLARADA'
        v = it.get('value')
        if isinstance(v, str) and v.strip() and v.strip().upper() not in ('SPACES', 'SPACE'):
            return v.strip().upper(), 'VALUE'
        if ast is not None:
            lits = _literais_movidos(ast, V(toks[0]))
            if len(lits) == 1:
                return lits[0], 'MOVE'
            if len(lits) > 1:
                return None, 'VARIAVEL_COM_VARIOS_MOVE'
        return None, 'VARIAVEL_SEM_VALUE'
    return None, 'SEM_DESTINO'


def _calls(ast, dm):
    out = []
    for n in walk(ast.get('body', [])):
        t = n.get('type')
        if t == 'CALL':
            a = list(n.get('arg_tokens') or [])
            u = find(a, ('USING',))
            head = a if u < 0 else a[:u]
            target, how = _resolve_target(head, dm, ast)
            using = a[u + 1:] if u >= 0 else []
            out.append({'line': n['start_line'], 'mechanism': 'CALL', 'raw': head[0][1] if head else None,
                        'target': target, 'resolution': how, 'statement': 'CALL ' + join_tokens(a),
                        'commarea': V(using[0]) if using and using[0][0] == 'IDENT' else None})
        elif t == 'EXEC_CICS':
            verb, opts = cics_options(list(n.get('tokens') or []))
            if verb in ('LINK', 'XCTL'):
                o = dict(opts)
                prog = o.get('PROGRAM')
                target, how = _resolve_target(prog, dm, ast)
                ca = strip_outer(list(o.get('COMMAREA') or []))
                out.append({'line': n['start_line'], 'mechanism': verb, 'raw': ' '.join(x[1] for x in prog) if prog else None,
                            'target': target, 'resolution': how,
                            'statement': join_tokens(list(n.get('tokens') or [])),
                            'commarea': V(ca[0]) if ca and ca[0][0] == 'IDENT' else None})
    return out


def _sql(ast):
    out = []
    for n in walk(ast.get('body', [])):
        if n.get('type') == 'EXEC_SQL':
            toks = list(n.get('tokens') or [])
            out.append({'line': n['start_line'], 'operation': V(toks[0]) if toks else '?', 'tables': sorted(sql_tables(toks)),
                        'sql': ' '.join(n.get('sql', '').split())[:300]})
    return out


def _linkage_items(text, dm):
    """Itens declarados entre LINKAGE SECTION e PROCEDURE DIVISION (entrada/saída do programa), achados pelos tokens."""
    toks = [as_tuple(t) for t in lex(text) if t.type != 'EOF']
    start = end = None
    for i in range(len(toks) - 1):
        if start is None and V(toks[i]) == 'LINKAGE' and V(toks[i + 1]) == 'SECTION':
            start = toks[i][2]
        if V(toks[i]) == 'PROCEDURE' and V(toks[i + 1]) == 'DIVISION':
            end = toks[i][2]
            break
    if start is None:
        return []
    return [x for x in dm['items'] if start < x['start_line'] < (end or 10 ** 9)]


def build(root, workdir=None):
    root = Path(root)
    lib = library(root)
    dclgen = build_dclgen_catalog(root)
    colcat = column_categories(dclgen)
    programs = {}
    asts = {}
    for f in discover_sources(root):
        lines, origin, rep = expand_file(f, lib)
        text = '\n'.join(lines) + '\n'
        ast = parse_text(text)
        pid = (ast.get('program_id') or f.stem).upper()
        expanded = None
        if workdir:
            expanded = Path(workdir) / 'expanded' / f'{pid}.CBL'
            expanded.parent.mkdir(parents=True, exist_ok=True)
            expanded.write_text(text, encoding='latin-1')
        dm = build_data_model(text)
        tree = build_tree(pid, ast)
        rules = business_rules_from_tree(tree)
        asts[pid] = ast
        lm = LineMap(f, origin)
        linkage = _linkage_items(text, dm)
        missing_cb = sorted({m['member'] for m in rep['missing']})
        programs[pid] = {
            'program': pid, 'file': str(f), 'expanded_file': str(expanded) if expanded else None,
            'sha256': hashlib.sha256(f.read_bytes()).hexdigest(),
            'copybooks': rep, 'linemap': lm, 'text': text, 'ast': ast, 'data_model': dm,
            'decision_tree': tree, 'rules': rules, 'dependencies': build_dependency_map(pid, ast, text),
            'calls': _calls(ast, dm), 'sql': _sql(ast), 'linkage': linkage,
            'io': analyze_program(pid, ast, dm, missing_cb, [i['name'] for i in linkage if i['level'] != 88], colcat, lm),
        }
    classification = {x['program']: x for x in classify_programs(asts, {p: x['text'] for p, x in programs.items()})}
    for p, x in programs.items():
        x['classification'] = classification.get(p)
    edges = [{'caller': p, **c} for p, x in programs.items() for c in x['calls']]
    fan_in = collections.Counter(e['target'] for e in edges if e['target'] and e['target'] != e['caller'])
    entry_points = sorted(p for p in programs if fan_in[p] == 0)
    externals = sorted({e['target'] for e in edges if e['target'] and e['target'] not in programs})
    for p, x in programs.items():
        x['fan_in'] = fan_in[p]
        # A classificação original não resolve chamadas por VALUE; recalcula o destaque de infraestrutura aqui.
        c = x['classification'] or {}
        x['infrastructure'] = c.get('recommendation') == 'MOCK_RECOMMENDED'
    return {'root': str(root), 'programs': programs, 'edges': edges, 'entry_points': entry_points,
            'externals': externals, 'dclgen': dclgen,
            'missing_copybooks': sorted({m['member'] for x in programs.values() for m in x['copybooks']['missing']})}


def _origin_copybook(prog, name):
    """Copybook (membro) em que a área de comunicação foi declarada; None se foi declarada no próprio programa."""
    if not name:
        return None
    it = next((i for i in prog['data_model']['items'] if i['name'].upper() == name.upper()), None)
    if not it:
        return None
    kids = [i for i in prog['data_model']['items'] if (i.get('parent') or '').upper() == it['name'].upper()]
    for cand in [it] + kids[:1]:
        o = prog['linemap'].to_source(cand['start_line'])
        if o.get('file') and not o.get('in_program'):
            return Path(o['file']).stem.upper()
    return None


def _grupos_do_fluxo(fluxo):
    """{campo: grupo 01} dos campos citados no fluxo de dados do programa (inclui os sem declaração)."""
    out = {}
    for f in (fluxo or {}).get('flows', []):
        for e in list(f.get('from', [])) + [f.get('to') or {}]:
            if e.get('type') == 'campo' and e.get('name') and e.get('group'):
                out.setdefault(e['name'].upper(), e['group'].upper())
    return out


def _areas_de_interface(x, fluxo, infra):
    """(áreas de interface, áreas das chamadas à infraestrutura, áreas que as alimentam), grupos 01. Interface = a área de comunicação recebida (DFHCOMMAREA), as áreas das chamadas a programas que não são de
    infraestrutura e as que as alimentam por MOVE (fluxo de dados). Infraestrutura = as áreas das chamadas a programas de infraestrutura (framework, log de erros); as que as alimentam só contam como
    infraestrutura quando são escritas pelo programa (preparo de erro, de sessão), não quando só são lidas (dado de entrada)."""
    raizes, fora = {'DFHCOMMAREA'}, set()
    for c in x['calls']:
        a = (c.get('commarea') or '').upper()
        if a:
            (fora if c.get('target') in infra else raizes).add(a)
    pares = set()
    for f in (fluxo or {}).get('flows', []):
        to = f.get('to') or {}
        for fr in f.get('from', []):
            if fr.get('type') == 'campo' and to.get('type') == 'campo' and fr.get('group') and to.get('group'):
                pares.add((fr['group'].upper(), to['group'].upper()))
    for _ in range(3):
        for a, b in pares:
            if b in raizes and a not in fora:
                raizes.add(a)
    alimenta = {a for a, b in pares if b in fora and a not in raizes and a not in fora}   # áreas preparadas (MOVE) para uma chamada à infraestrutura
    return raizes, fora - raizes, alimenta


def _copybook_fields(x, areas=None, grupo_de=None):
    """Campos dos copybooks do próprio programa que são entrada ou saída dele: [{copybook, name, pic, read, written, via_grupo, declared, evidencia}].
    Copybook do próprio programa = COPY no fonte dele (o que um copybook inclui entra no copybook que o programa inclui). Entrada = campo lido; saída = escrito, pelo
    nome do campo; se só o grupo dele é referenciado (MOVE/INITIALIZE de grupo), vale o uso do grupo (via_grupo). Campo sem nenhuma referência = não usado.
    Quais copybooks são entrada ou saída: (1) evidência estrutural: o campo está numa área de interface (ver _areas_de_interface); (2) sem evidência estrutural, inferência
    pelo uso: o copybook usa pelo menos metade dos campos e pelo menos 75% dos usados são só lidos (entrada) ou só escritos (saída). Copybook de área de infraestrutura fica
    de fora. Copybook ausente: campos deduzidos pelo uso (io), cuja área vem do fluxo de dados."""
    interface, infra_areas, alimenta = areas if areas is not None else (None, set(), set())
    dm, lm, io = x['data_model'], x['linemap'], x['io']
    reads, writes = set(io['reads']), set(io['writes'])
    items = dm['items']
    by = {i['name'].upper(): i for i in items}
    pais = {(i.get('parent') or '').upper() for i in items}

    def cadeia(i):
        out, cur, seen = [i['name'].upper()], i, set()
        while cur.get('parent') and cur['parent'].upper() not in seen:
            seen.add(cur['parent'].upper())
            out.append(cur['parent'].upper())
            cur = by.get(cur['parent'].upper()) or {}
        return out
    prog = Path(x['file']).stem.upper()
    inc = {}   # membro -> arquivo que o inclui (COPY dentro de copybook aninha um no outro)
    for m in x['copybooks']['expanded'] + x['copybooks']['missing']:
        inc.setdefault(m['member'].upper(), Path(m['file']).stem.upper())

    def direto(cb):
        """Copybook incluído pelo próprio programa que contém (direta ou aninhadamente) o copybook dado; None se não achar a cadeia."""
        seen = set()
        while cb and cb not in seen:
            seen.add(cb)
            pai = inc.get(cb)
            if pai == prog:
                return cb
            cb = pai
        return None
    cand = []
    for i in items:
        n = i['name'].upper()
        if i['level'] in (66, 88) or n == 'FILLER' or n in pais:
            continue
        o = lm.to_source(i['start_line'])
        if not o.get('file') or o.get('in_program'):
            continue
        ch = cadeia(i)
        orig = Path(o['file']).stem.upper()
        top = direto(orig)
        if not top:
            continue
        rd, wd = n in reads, n in writes
        if rd or wd:
            r, w, via = rd, wd, False
        else:
            r, w = any(c in reads for c in ch[1:]), any(c in writes for c in ch[1:])
            via = r or w
        cand.append({'copybook': top, 'declarado_em': orig, 'name': n, 'pic': i.get('pic') or '', 'level': i['level'], 'read': r, 'written': w, 'via_grupo': via, 'declared': True, 'area': ch[-1]})
    for f in io['fields']:
        top = direto((f['copybook'] or '').upper())
        if not top:
            continue   # campo sem copybook identificado, ou de copybook que o programa não inclui: não entra nos diagramas
        cand.append({'copybook': top, 'declarado_em': (f['copybook'] or '').upper(), 'name': f['name'], 'pic': f['type'] or '', 'level': None, 'read': f['read'], 'written': f['written'],
                     'via_grupo': False, 'declared': False, 'area': (grupo_de or {}).get(f['name'].upper())})
    por = collections.defaultdict(list)
    for f in cand:
        por[f['copybook']].append(f)
    out = []
    for cb, fs in por.items():
        if interface is None:
            for f in fs:
                out.append({**f, 'evidencia': 'sem classificação'})
            continue
        usados = [f for f in fs if f['read'] or f['written']]
        ent = sum(f['read'] and not f['written'] for f in usados)
        sai = sum(f['written'] and not f['read'] for f in usados)
        if sum(f['area'] in infra_areas for f in fs) * 2 > len(fs):
            continue   # copybook das áreas das chamadas à infraestrutura
        if sum(f['area'] in alimenta for f in fs) * 2 > len(fs) and sai >= ent:
            continue   # copybook preparado (escrito) só para alimentar uma chamada à infraestrutura
        if any(f['area'] in interface for f in fs):
            ev = 'estrutura: área de comunicação ou de chamada a programa de negócio'
        else:
            if not usados or len(usados) * 2 < len(fs) or max(ent, sai) * 4 < len(usados) * 3:
                continue
            ev = f'inferido pelo uso: {ent} de {len(usados)} campos usados só lidos' if ent >= sai else f'inferido pelo uso: {sai} de {len(usados)} campos usados só escritos'
        for f in fs:
            out.append({**{k: v for k, v in f.items() if k != 'area'}, 'evidencia': ev})
    return out


def public(model):
    import data_flow
    fluxos = data_flow.build(model)
    infra = {q for q, y in model['programs'].items() if y['infrastructure']}
    """Visão serializável do modelo estático."""
    progs = {}
    for p, x in model['programs'].items():
        lm = x['linemap']
        decisions = []
        for d in x['decision_tree']['decisions']:
            decisions.append({'decision_id': d['decision_id'], 'type': d['type'], 'line': lm.source_line(d['line']),
                              'expression': d['expression'],
                              'branches': [{'result': b['result'], 'falls_through_to': b.get('falls_through_to'),
                                            'classification': b.get('semantic_classification')} for b in d['branches']]})
        progs[p] = {
            'file': x['file'], 'expanded_file': ('expanded/' + Path(x['expanded_file']).name) if x['expanded_file'] else None, 'sha256': x['sha256'],
            'classification': (x['classification'] or {}).get('classification'),
            'recommendation': (x['classification'] or {}).get('recommendation'),
            'infrastructure': x['infrastructure'], 'fan_in': x['fan_in'],
            'copybooks_expanded': sorted({m['member'] for m in x['copybooks']['expanded']}),
            'copybooks_missing': sorted({m['member'] for m in x['copybooks']['missing']}),
            'calls': [{**c, 'line': lm.source_line(c['line'])} for c in x['calls']],
            'sql': [{**s, 'line': lm.source_line(s['line'])} for s in x['sql']],
            'decisions': decisions,
            'business_rules': len(x['rules']['business_rules']),
            'io': {'undeclared': x['io']['summary']['undeclared'], 'undeclared_read': x['io']['summary']['undeclared_read'],
                   'by_copybook': x['io']['summary']['by_copybook'], 'inputs': x['io']['inputs'], 'outputs': x['io']['outputs']},
            'linkage': [{'level': i['level'], 'name': i['name'], 'pic': i['pic'], 'value': i['value']} for i in x['linkage']],
            'copybook_fields': _copybook_fields(x, _areas_de_interface(x, fluxos.get(p), infra), _grupos_do_fluxo(fluxos.get(p))),
        }
    return {'root': model['root'], 'entry_points': model['entry_points'], 'externals': model['externals'],
            'missing_copybooks': model['missing_copybooks'], 'dclgen': model['dclgen']['summary'],
            'call_graph': [{'caller': e['caller'], 'line': model['programs'][e['caller']]['linemap'].source_line(e['line']),
                            'mechanism': e['mechanism'], 'target': e['target'], 'resolution': e['resolution'],
                            'statement': e.get('statement'), 'commarea': e.get('commarea'),
                            'commarea_copybook': _origin_copybook(model['programs'][e['caller']], e.get('commarea'))} for e in model['edges']],
            'programs': progs}
