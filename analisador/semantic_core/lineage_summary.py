"""Fase 4b — resumo da linhagem de dados (entre a fase 4 e a fase 5).

Lê só o resultado da fase 4 (field_lineage.build) e simplifica, por comando SQL:
  entradas  o que alimenta cada parte do comando que recebe dado: condições do WHERE (SELECT, UPDATE, DELETE, chave de cursor) e campos como parâmetro
            (VALUES do INSERT, SET do UPDATE): a origem mais distante com base na entrada, ligada ao trecho do SQL a que ela se refere;
  saídas    cada coluna lida (SELECT INTO / FETCH) e o fim do caminho dela no programa;
  condições as que escolhem ou habilitam cada origem e cada destino, e as que habilitam o comando.
Campos de transporte (MOVE de um campo para outro sem mudar o valor) não aparecem: o valor é o mesmo. Aparecem a origem real (entrada do entry point, valor fixo,
coluna de tabela lida), a transformação (quando existe), o percurso entre programas e as condições. Tokens e resultados estruturados apenas: nada de leitura do fonte, nada de nome fixo."""
import re

TRANSFORM_OPS = {'COMPUTE', 'ADD', 'SUBTRACT', 'MULTIPLY', 'DIVIDE', 'STRING', 'UNSTRING', 'INSPECT', 'EVALUATE'}
GRAVACAO = {'INSERT', 'UPDATE', 'DELETE', 'MERGE'}
_REFMOD = re.compile(r'\(\s*[\w-]+\s*:\s*[\w-]*\s*\)')
_PALAVRAS = {'AND', 'OR', 'NOT', 'IS', 'NUMERIC', 'TRUE', 'FALSE', 'ZEROS', 'ZERO', 'SPACES', 'SPACE', 'EQUAL', 'GREATER', 'LESS', 'THAN', 'TO', 'ALPHABETIC',
             'HIGH-VALUES', 'LOW-VALUES', 'NULL'}
INFRA_PADRAO = [r'EIB[A-Z0-9-]*', r'SQLSTATE', r'SQLCA[A-Z0-9-]*', r'SQLERR[A-Z0-9-]*', r'SQLWARN[A-Z0-9-]*', r'SQLCODE', r'RETURN-CODE', r'DFHRESP']
_ATUAL = []


def _infra_re(padroes=None):
    if padroes is None and _ATUAL:
        return _ATUAL[0]
    return re.compile('^(' + '|'.join(padroes or INFRA_PADRAO) + ')$')


def _tabela_curta(t):
    return str(t).split('.')[-1]


def _campo_de(name):
    """'PROG · CAMPO (ÁREA)' -> (programa, campo, área); sem ' · ' devolve ('', nome, '')."""
    name = str(name)
    prog, rest = (name.split(' · ', 1) if ' · ' in name else ('', name))
    m = re.match(r'^(.*?)(?: \((.*)\))?$', rest)
    return prog, m.group(1), (m.group(2) or '')


def _tecnica(c, infra):
    """Condição sobre status de execução (SQLCODE, EIBRESP...): não escolhe valor de negócio."""
    if c.get('sql'):
        return True
    ids = [t for t in re.findall(r'[A-Z][A-Z0-9-]*', str(c.get('condition', ''))) if t not in _PALAVRAS and not re.fullmatch(r'\+?\d+', t)]
    return bool(ids) and all(infra.match(t) for t in ids)


def _cond_txt(c, invertida=False):
    sim = (c['result'] == 'Sim') != invertida
    return (f'{c.get("program", "")}:{c["code"]} ' if c.get('code') else '') + (('se ' + c['condition']) if sim else f'senão ({c["condition"]})')


def _chave(c):
    return (c.get('program', ''), c.get('code'), c.get('result'))


def _unicos(seq):
    out = []
    for x in seq:
        if x not in out:
            out.append(x)
    return out


def _condicoes_passos(steps, infra):
    """(decisivas, demais): decisiva é a decisão de negócio mais próxima (a de maior linha antes da atribuição, no programa dela) de cada atribuição do caminho; as outras
    decisões de negócio do caminho são as demais condições. Decisões de status de execução (SQLCODE, EIB...) não entram."""
    nearest, todas = {}, {}
    for s in steps:
        wc = [c for c in (s.get('when_conds') or []) if not _tecnica(c, infra)]
        cand = [c for c in wc if c.get('program') == s.get('program') and (c.get('line') or 0) <= (s.get('line') or 10 ** 9)]
        if cand and s.get('op') in ('MOVE', 'INITIALIZE', 'SELECT', 'FETCH'):
            n = max(cand, key=lambda c: c.get('line') or 0)
            nearest.setdefault(_chave(n), n)
        for c in wc:
            todas.setdefault(_chave(c), c)
    dec = [_cond_txt(c) for k, c in nearest.items()]
    resto = [_cond_txt(c) for k, c in todas.items() if k not in nearest]
    return dec, resto


def _recorte_de_valor(txt, infra):
    """Recorte (referência por posição) que muda o valor; a cópia da área de comunicação limitada pelo tamanho que o ambiente informa (1:EIBCALEN) não muda."""
    for m in _REFMOD.finditer(txt):
        corpo = m.group(0)[1:-1]
        ini, _, fim = (x.strip() for x in corpo.partition(':'))
        if ini == '1' and (not fim or infra.match(fim)):
            continue
        return True
    return False


def _transformacoes(steps, infra=None):
    """Passos que mudam o valor (cálculo, texto, recorte); a cópia simples de campo para campo não conta."""
    infra = infra or _infra_re()
    out = []
    for s in steps:
        txt = ' '.join(str(s.get('text') or '').split())
        op = s.get('op') or ''
        if op in TRANSFORM_OPS or (op == 'MOVE' and (_recorte_de_valor(txt, infra) or 'FUNCTION' in txt.upper())):
            out.append({'op': op, 'programa': s['program'], 'linha': s.get('line'), 'expressao': txt, 'para': s.get('to', '')})
    return out


def _copias(steps):
    return sum(1 for s in steps if (s.get('op') or '') in ('MOVE', 'LINK') and not _transformacoes([s]))


def _percurso(steps):
    seq = []
    for s in steps:
        for p in str(s.get('program', '')).split('→'):
            if p and (not seq or seq[-1] != p):
                seq.append(p)
    return seq


def _id_sql(prog, linha, tabela):
    return f'{prog}@{linha}:{_tabela_curta(tabela)}' if prog and linha not in (None, '') and tabela else ''


def _origem(o, eps, infra):
    """Uma origem da fase 4 em forma resumida."""
    kind, name, steps = o.get('kind'), str(o.get('name', '')), o.get('steps') or []
    tr = _transformacoes(steps, infra)
    dec, resto = _condicoes_passos(steps, infra)
    base = {'copias': _copias(steps), 'transformacoes': tr, 'esperada': bool(o.get('expected')), 'ref_sql': '', 'campo': '', 'tabela': '', 'valor': '', 'programa': '',
            'percurso': _percurso(steps), 'decisivas': dec, 'caminho': resto}
    if kind == 'valor fixo':
        base.update(tipo='valor fixo', valor=name, resumo='valor fixo: ' + ('valor inicial do campo (PIC/VALUE)' if name.startswith('valor inicial') else name))
    elif kind and kind.startswith('valor inicial'):
        prog, campo, area = _campo_de(name)
        base.update(tipo='valor inicial', campo=campo, programa=prog, resumo=f'valor inicial de {campo} (campo nunca atribuído no programa {prog})')
    elif kind == 'tabela':
        partes = name.split('.')
        tab, col = (partes[-2], partes[-1]) if len(partes) >= 2 else (name, '')
        ref = ''
        if steps and steps[0].get('op') in ('SELECT', 'FETCH'):
            ref = _id_sql(steps[0]['program'], steps[0].get('line'), tab)
        base.update(tipo='tabela lida', tabela=tab, campo=col, ref_sql=ref, programa=steps[0]['program'] if steps else '',
                    resumo=f'coluna {col} da tabela {tab}' + (f' (lida em {ref.split(":")[0]})' if ref else ''))
    else:
        prog, campo, area = _campo_de(name)
        if prog in eps and not o.get('expected'):
            base.update(tipo='entrada do entry point', campo=campo, programa=prog, resumo=f'entrada do entry point {prog}: {campo}')
        else:
            base.update(tipo='não rastreada', campo=campo, programa=prog, resumo=f'origem não rastreada: {name}')
    if tr:
        base['resumo'] += ' → transformado: ' + ' ; '.join(f'{t["expressao"]} ({t["programa"]}@{t["linha"]})' for t in tr)
    return base


def _alternativas(origens, eps, infra, prog_cmd=''):
    """Origens do mesmo item: iguais (mesmo resumo) viram uma. Condições: a que escolhe uma origem entre várias (decisão do programa do comando que as separa) e as
    decisivas de cada atribuição vão em `quando`; as demais decisões de negócio do caminho em `caminho`."""
    itens = []
    for o in origens:
        r = _origem(o, eps, infra)
        conds = list(o.get('when_conds') or [])
        for it in itens:
            if it['resumo'] == r['resumo'] and it['ref_sql'] == r['ref_sql']:
                it['_conds'].append(conds)
                it['decisivas'] = _unicos(it['decisivas'] + r['decisivas'])
                it['caminho'] = _unicos(it['caminho'] + r['caminho'])
                break
        else:
            r['_conds'] = [conds]
            itens.append(r)
    rota = [[] for _ in itens]
    if len(itens) > 1:
        sets = []
        for r in itens:
            por = [set(map(_chave, cs)) for cs in r['_conds']]
            sets.append(set.union(*por) if por else set())
        comum = set.intersection(*sets)
        todas = {_chave(c): c for r in itens for cs in r['_conds'] for c in cs}
        proprias = [[k for k in sorted(s - comum, key=lambda k: (k[0], str(k[1]))) if not _tecnica(todas[k], infra) and (not prog_cmd or k[0] == prog_cmd)] for s in sets]
        for i, p in enumerate(proprias):
            if p:
                rota[i] = [_cond_txt(todas[k]) for k in p]
            else:
                outras = [k for j, q in enumerate(proprias) if j != i for k in q]
                rota[i] = [' OU '.join(_cond_txt(todas[k], True) for k in outras)] if outras else []
    for r, ro in zip(itens, rota):
        r['quando'] = _unicos(ro + r['decisivas'])
        r['caminho'] = [x for x in r['caminho'] if x not in r['quando']]
        r.pop('_conds')
        r.pop('decisivas')
    return itens


def _destino(d, eps, infra):
    steps = d.get('steps') or []
    tr = _transformacoes(steps, infra)
    dec, resto = _condicoes_passos(steps, infra)
    ultimo = _campo_de(steps[-1]['to']) if steps else _campo_de(d.get('name', ''))
    if ultimo[1] == 'DFHCOMMAREA' and len(steps) > 1:   # bloco da área de comunicação: o campo que o chamador lê é o último campo nomeado antes dela
        for s_ in reversed(steps[:-1]):
            c_ = _campo_de(s_['to'])
            if c_[1] != 'DFHCOMMAREA':
                ultimo = c_
                break
    kind, name = d.get('kind'), str(d.get('name', ''))
    out = {'tipo': kind, 'programa': d.get('program', ''), 'linha': d.get('line', ''), 'op': d.get('op', ''), 'transformacoes': tr, 'copias': _copias(steps), 'ref_sql': '',
           'campo': ultimo[1], 'percurso': _percurso(steps), 'quando': dec, 'caminho': [x for x in resto if x not in dec]}
    if kind == 'saída do programa':
        prog, campo, area = _campo_de(name)
        if campo == 'DFHCOMMAREA':
            campo = ultimo[1]
        out.update(campo=campo, resumo=f'sai do programa {prog} no campo {campo}')
    elif kind == 'envio':
        out.update(resumo=f'passa ao programa {d.get("program")} pela chamada {d.get("op")} e chega ao campo {ultimo[1]}')
    elif kind == 'gravação':
        partes = name.split('.')
        tab, col = (partes[-2], partes[-1]) if len(partes) >= 2 else (name, '')
        out.update(campo=col, ref_sql=_id_sql(d.get('program'), d.get('line'), tab), resumo=f'gravado em {tab}.{col} por {d.get("op")}')
    elif kind == 'chave de consulta':
        tab = _tabela_curta(name)
        pen = _campo_de(steps[-2]['to'])[1] if len(steps) > 1 else ''
        out.update(campo=pen, ref_sql=_id_sql(d.get('program'), d.get('line'), tab), resumo=f'chave de busca em {tab}' + (f' pelo campo {pen}' if pen else ''))
    else:
        out.update(resumo=f'termina em {ultimo[1]} no programa {d.get("program")} sem sair dele')
    if tr:
        out['resumo'] += ' → transformado: ' + ' ; '.join(f'{t["expressao"]} ({t["programa"]}@{t["linha"]})' for t in tr)
    return out


def _item_curto(item, op='', valor=''):
    """'A.CLIBRD >= :WRK-CLIBRD-INI' -> 'CLIBRD >= WRK-CLIBRD-INI' (sem o apelido da tabela, os dois-pontos e o grupo do campo)."""
    if op:
        v = re.sub(r'^:?(?:[A-Z0-9-]+\.)?', '', str(valor or '')).strip()
        return f'{str(item).split(".")[-1]} {op} {v}'.strip()
    return str(item)


def _entrada_item(grupo, parte, fragmento, item, papel, valor, op, origens, eps, infra, prog_cmd='', curto=''):
    return {'grupo': grupo, 'parte': parte, 'fragmento': fragmento, 'item': item, 'curto': curto or fragmento, 'papel': papel, 'operador': op, 'valor': valor,
            'alternativas': _alternativas(origens or [], eps, infra, prog_cmd)}


def _caminhos(src, infra):
    """Condições do caminho até o comando: lista de caminhos (OU), cada um uma lista de decisões (E)."""
    out = []
    for path in (src or {}).get('conditions') or []:
        p = []
        for c in path:
            sq = c.get('sql') or {}
            p.append({'codigo': c.get('code'), 'programa': c.get('program', ''), 'condicao': c.get('condition', ''), 'resultado': c.get('result', ''), 'linha': c.get('line'),
                      'tecnica': _tecnica(c, infra), 'status_id': sq.get('id') or '', 'status_txt': ('' if sq.get('id') else str(sq.get('text') or ''))})
        out.append(p)
    return out


def _unir_cursores(cmds):
    """Cursor é uma consulta só: o DECLARE traz as condições (entradas) e o FETCH traz as colunas lidas (saídas); viram um comando, com os ids e linhas dos demais."""
    grupos = {}
    for c in cmds:
        if c['cursor']:
            grupos.setdefault((c['programa'], c['cursor'], c['tabela_completa']), []).append(c)
    descartar = set()
    for g in grupos.values():
        if len(g) < 2:
            continue
        main = next((c for c in g if c['entradas']), g[0])
        for o in g:
            if o is main:
                continue
            descartar.add(o['id'])
            main['ids'] = _unicos(main['ids'] + o['ids'])
            main['linhas'] = sorted(set(main['linhas']) | set(o['linhas']))
            main['entry_points'] = sorted(set(main['entry_points']) | set(o['entry_points']))
            if not main['entradas']:
                main['entradas'] = o['entradas']
            if not main['executa_quando']:
                main['executa_quando'] = o['executa_quando']
            vistos = {(x['coluna'], x['campo']): x for x in main['saidas']}
            for x in o['saidas']:
                k = (x['coluna'], x['campo'])
                if k in vistos:
                    ja = {d['resumo'] for d in vistos[k]['destinos']}
                    vistos[k]['destinos'] += [d for d in x['destinos'] if d['resumo'] not in ja]
                else:
                    main['saidas'].append(x)
                    vistos[k] = x
    return [c for c in cmds if c['id'] not in descartar]


def build(lineage, padroes_infra=None, classes=None):
    """Resultado da fase 4b a partir do resultado da fase 4 (`lineage`)."""
    if padroes_infra is None:
        try:
            import projeto_config
            padroes_infra = projeto_config.carregar()['campos_infraestrutura'] + [r'SQLCODE']
        except Exception:
            padroes_infra = None
    infra = _infra_re(padroes_infra)
    _ATUAL[:] = [infra]
    eps = set(lineage.get('entry_points') or [])
    tabelas = lineage.get('tables') or {}
    leit, grav = {}, {}
    for t, tv in tabelas.items():
        for x in tv.get('reads', []):
            leit[x['id']] = x
        for x in tv.get('writes', []):
            grav[x['id']] = x
    cmds = {}
    for t, tv in tabelas.items():
        for q in tv.get('sql', []):
            cmds.setdefault(q['id'], (t, q))
        for q in tv.get('reads', []) + tv.get('writes', []):
            cmds.setdefault(q['id'], (t, q))
    out = []
    for cid, (t, q) in sorted(cmds.items(), key=lambda kv: (kv[1][1]['program'], kv[1][1].get('line') or 0, kv[0])):
        r, w = leit.get(cid), grav.get(cid)
        prog = q['program']
        entradas = []
        onde = q.get('where') or (r or {}).get('where') or (w or {}).get('where') or []
        for p in onde:
            valor = p.get('value_resolved') or p.get('value', '')
            if p.get('origins') or p.get('value_kind') in ('campo',):
                orig = p.get('origins')
            else:
                fixo = p.get('value_kind') in ('valor fixo', 'expressão')
                orig = None
            curto = _item_curto(p.get('column', p['text']), p.get('op', ''), p.get('value', ''))
            it = _entrada_item('where', 'WHERE', p['text'], p.get('column', ''), p.get('role', ''), valor, p.get('op', ''), orig, eps, infra, prog, curto)
            if orig is None:
                fixo = p.get('value_kind') in ('valor fixo', 'expressão')
                it['alternativas'] = [{'tipo': 'valor fixo' if fixo else 'coluna de outra tabela', 'resumo': ('valor fixo: ' if fixo else 'ligação com a coluna ') + str(valor),
                                       'quando': [], 'caminho': [], 'percurso': [], 'copias': 0, 'transformacoes': [], 'esperada': True, 'ref_sql': '', 'campo': '',
                                       'tabela': '', 'valor': str(p.get('value')), 'programa': ''}]
            entradas.append(it)
        if not onde and r:
            for k in r.get('keys') or []:
                entradas.append(_entrada_item('where', 'WHERE (chave do cursor)', k.get('field', ''), k.get('field', ''), k.get('note', ''), k.get('field', ''), '=', k.get('origins'), eps, infra, prog))
        if w:
            for c in w.get('columns') or []:
                op = str(c.get('op') or w.get('statement') or '')
                entradas.append(_entrada_item('campos', 'SET' if op == 'UPDATE' else 'VALUES', f'{c["column"]} ← {c.get("value", "")}', c['column'], op, c.get('value', ''), '←',
                                              c.get('origins'), eps, infra, prog, f'{c["column"]} ← {c.get("value", "")}'))
        saidas = []
        for x in (r or {}).get('returns') or []:
            ds = {}
            for d in x.get('destinations') or []:
                dd = _destino(d, eps, infra)
                k = (dd['tipo'], dd['resumo'], dd['programa'], dd['ref_sql'])
                if k in ds:
                    ds[k]['linhas'].append(dd['linha'])
                    ds[k]['quando'] = _unicos(ds[k]['quando'] + dd['quando'])
                    ds[k]['caminho'] = _unicos(ds[k]['caminho'] + dd['caminho'])
                else:
                    dd['linhas'] = [dd['linha']]
                    ds[k] = dd
            for dd in ds.values():
                ls = sorted({str(l) for l in dd['linhas'] if l not in ('', None)}, key=lambda v: int(v) if v.isdigit() else 0)
                dd['linha'] = ', '.join(ls)
                dd['caminho'] = [z for z in dd['caminho'] if z not in dd['quando']]
                dd.pop('linhas')
            saidas.append({'coluna': x['column'], 'campo': x.get('host', ''), 'uso': x.get('use', ''), 'destinos': list(ds.values())})
        linhas = {q.get('line')} | {a.get('line') for a in q.get('associated', []) or []}
        for z in (r, w):
            if z:
                linhas |= {z.get('line')} | {a.get('line') for a in z.get('associated', []) or []}
        linhas = sorted(l for l in linhas if isinstance(l, int))
        paths = _caminhos(r or w, infra)
        out.append({'id': cid, 'ids': [cid], 'programa': prog, 'linha': q.get('line'), 'linhas': linhas, 'paragrafo': q.get('paragraph') or '', 'comando': q.get('statement', ''),
                    'cursor': q.get('cursor') or '', 'tabela': _tabela_curta(t), 'tabela_completa': t, 'entry_points': list(q.get('entry_points') or []),
                    'sql': q.get('sql') or (r or w or {}).get('sql', ''), 'executa_quando': paths, 'entradas': entradas, 'saidas': saidas})
    out = _unir_cursores(out)
    seq = {}
    for c in sorted(out, key=lambda c: (c['programa'], c['linha'] or 0, c['id'])):   # código curto e estável do comando dentro do programa (ordem das linhas)
        seq[c['programa']] = seq.get(c['programa'], 0) + 1
        c['cod'] = f'{c["programa"]}-Q{seq[c["programa"]]:02d}'
    tipos, dest = {}, {}
    n_alt = n_trans = n_cond = 0
    for c in out:
        for e in c['entradas']:
            for a in e['alternativas']:
                tipos[a['tipo']] = tipos.get(a['tipo'], 0) + 1
                n_alt += 1
                n_trans += bool(a['transformacoes'])
                n_cond += bool(a.get('quando'))
        for s in c['saidas']:
            for d in s['destinos']:
                dest[d['tipo']] = dest.get(d['tipo'], 0) + 1
                n_trans += bool(d['transformacoes'])
    chamadas, vistos = [], set()
    for x in lineage.get('calls') or []:
        k = (x.get('caller'), x.get('callee'), x.get('line'))
        if k not in vistos:
            vistos.add(k)
            chamadas.append({'de': x.get('caller'), 'para': x.get('callee'), 'mecanismo': x.get('mechanism', ''), 'linha': x.get('line'), 'paragrafo': x.get('paragraph') or '', 'area': x.get('area') or ''})
    chamadas.sort(key=lambda c: (str(c['de']), c['linha'] or 0, str(c['para'])))
    return {'commands': out, 'chamadas': chamadas, 'classes': dict(classes or {}), 'entry_points': sorted(eps),
            'summary': {'comandos': len(out), 'tabelas': len({c['tabela_completa'] for c in out}), 'entradas': sum(len(c['entradas']) for c in out), 'alternativas': n_alt,
                        'saidas': sum(len(c['saidas']) for c in out), 'com_transformacao': n_trans, 'escolhidas_por_condicao': n_cond, 'origens_por_tipo': tipos, 'destinos_por_tipo': dest}}


