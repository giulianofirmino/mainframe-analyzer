"""Papel de cada tabela DB2 no sistema, decidido só pelo que o código faz nela (operações SQL e alcance pelo grafo de chamadas).

  protagonista  a tabela muda de estado: algum programa faz INSERT, UPDATE, DELETE ou MERGE nela. Entre as protagonistas, quem tem mais
                comandos de gravação vem primeiro;
  coadjuvante   só é consultada, mas aparece bastante: tem mais de um programa acessando, ou mais de um entry point a alcança, ou mais
                comandos de consulta que a mediana das tabelas só consultadas;
  figurante     só é consultada e aparece pouco: um programa, um entry point e comandos até a mediana;
  não referenciada  existe no catálogo de DCLGEN, mas nenhum programa a acessa.
Comandos que contam: cada SELECT e cada cursor (OPEN, FETCH e CLOSE do mesmo cursor valem uma consulta só) são consulta; cada INSERT, UPDATE, DELETE e MERGE é gravação.
Nível = menor distância, na árvore de chamadas, entre um entry point (ninguém o chama) e um programa que acessa a tabela.
Também informa se há DCLGEN (colunas conhecidas) e quais programas leem ou gravam."""
from collections import defaultdict, deque

READ = {'SELECT', 'FETCH', 'OPEN'}
WRITE = {'INSERT', 'UPDATE', 'DELETE', 'MERGE'}
ROLES = ('protagonista', 'coadjuvante', 'figurante', 'não referenciada')
CRITERIOS_PAPEL = [
    ('protagonista', 'A tabela muda de estado: algum programa faz INSERT, UPDATE, DELETE ou MERGE nela.', 'Comandos de gravação encontrados no SQL. Entre as protagonistas, quem tem mais comandos de gravação vem primeiro.'),
    ('coadjuvante', 'Só é consultada, mas aparece bastante: mais de um programa a acessa, ou mais de um entry point a alcança, ou tem mais comandos de consulta que a mediana das tabelas só consultadas.', 'Contagem de programas, de entry points (pelo grafo de chamadas) e de comandos de consulta.'),
    ('figurante', 'Só é consultada e aparece pouco: um programa, um entry point e comandos de consulta até a mediana.', 'Mesmas contagens, nenhuma acima do limite.'),
    ('não referenciada', 'Existe no catálogo de DCLGEN, mas nenhum programa a acessa.', 'Nenhum acesso no SQL dos programas.'),
    ('Contagem de comandos', 'Cada SELECT e cada cursor (OPEN, FETCH e CLOSE do mesmo cursor valem uma consulta só) é consulta; cada INSERT, UPDATE, DELETE e MERGE é gravação.', 'Operações do SQL de cada programa.'),
    ('Nível', 'Menor distância, na árvore de chamadas, entre um entry point (ninguém o chama) e um programa que acessa a tabela.', 'Grafo de chamadas resolvido.'),
]


def reach_by_root(edges, programs):
    """{entry point: programas que ele alcança (ele incluído)} pelo grafo de chamadas resolvido."""
    callees = defaultdict(set)
    called = set()
    for e in edges:
        if e.get('target') and e['target'] != e['caller']:
            callees[e['caller']].add(e['target'])
            called.add(e['target'])
    out = {}
    for r in sorted(p for p in programs if p not in called):
        seen, q = {r}, deque([r])
        while q:
            for c in callees[q.popleft()]:
                if c not in seen:
                    seen.add(c)
                    q.append(c)
        out[r] = seen
    return out


def depths(edges, programs):
    callees = defaultdict(set)
    called = set()
    for e in edges:
        if e.get('target') and e['target'] != e['caller']:
            callees[e['caller']].add(e['target'])
            called.add(e['target'])
    roots = sorted(p for p in programs if p not in called)
    dist = {r: 0 for r in roots}
    q = deque(roots)
    while q:
        p = q.popleft()
        for c in sorted(callees[p]):
            if c not in dist:
                dist[c] = dist[p] + 1
                q.append(c)
    return dist


def _median(xs):
    xs = sorted(xs)
    if not xs:
        return 0
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def build(edges, programs, classes, dependencies, dclgen_tables):
    """classes: {programa: classe}; dependencies: {programa: {'table_access': [...]}}; dclgen_tables: {tabela: [membros]}."""
    dist = depths(edges, programs)
    roots = reach_by_root(edges, programs)
    acc = defaultdict(lambda: defaultdict(lambda: {'ops': set(), 'cursors': set(), 'reads': 0, 'writes': 0}))
    for p, d in dependencies.items():
        for a in d.get('table_access', []):
            x = acc[a['table']][p]
            x['ops'].add(a['operation'])
            x['reads'] += a['operation'] in READ and not a['via_cursor']
            x['writes'] += a['operation'] in WRITE
            if a['via_cursor']:
                x['cursors'].add(a['via_cursor'])
    base = []
    for t in sorted(set(acc) | set(dclgen_tables)):
        progs = acc.get(t, {})
        rows = [{'program': p, 'class': classes.get(p), 'depth': dist.get(p), 'operations': sorted(x['ops']), 'cursors': sorted(x['cursors']),
                 'read_commands': x['reads'] + len(x['cursors']), 'write_commands': x['writes']} for p, x in sorted(progs.items())]
        depth = min([r['depth'] for r in rows if r['depth'] is not None] or [None]) if rows else None
        eps = sorted(r for r, seen in roots.items() if any(x['program'] in seen for x in rows))
        base.append({'table': t, 'level': depth, 'entry_points': eps, 'has_dclgen': t in dclgen_tables, 'programs': rows,
                     'read_commands': sum(r['read_commands'] for r in rows), 'write_commands': sum(r['write_commands'] for r in rows),
                     'write_programs': sorted(r['program'] for r in rows if r['write_commands']), 'read_programs': sorted(r['program'] for r in rows if r['read_commands'])})
    med = _median([b['read_commands'] for b in base if b['programs'] and not b['write_commands']])
    out = []
    for b in base:
        if not b['programs']:
            role, why = 'não referenciada', 'nenhum programa acessa a tabela'
        elif b['write_commands']:
            kinds = sorted({o for r in b['programs'] for o in r['operations'] if o in WRITE})
            role, why = 'protagonista', f'tem {b["write_commands"]} comando(s) de gravação ({", ".join(kinds)}) em {len(b["write_programs"])} programa(s)'
        else:
            reasons = []
            if len(b['programs']) > 1:
                reasons.append(f'{len(b["programs"])} programas a acessam')
            if len(b['entry_points']) > 1:
                reasons.append(f'{len(b["entry_points"])} entry points a alcançam')
            if b['read_commands'] > med:
                reasons.append(f'{b["read_commands"]} comandos de consulta, acima da mediana {med:g}')
            role, why = ('coadjuvante', 'só consulta; ' + '; '.join(reasons)) if reasons else ('figurante', f'só consulta; 1 programa, {len(b["entry_points"])} entry point(s), {b["read_commands"]} comando(s) de consulta, até a mediana {med:g}')
        out.append({**b, 'role': role, 'why': why, 'reads': bool(b['read_commands']), 'writes': bool(b['write_commands'])})
    out.sort(key=lambda r: (ROLES.index(r['role']), -r['write_commands'], -r['read_commands'], r['level'] if r['level'] is not None else 99, r['table']))
    return out
