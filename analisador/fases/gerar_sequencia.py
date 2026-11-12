#!/usr/bin/env python3
"""Fase 11 (fluxos de negócio), fluxo interno de cada funcionalidade: regras em sequência e, quando houver, as chamadas às funcionalidades corporativas.

  python3 gerar_sequencia.py <pasta-da-analise> [pasta-de-saida] --interpretacao <pasta>   (roda depois de gerar_simulacao.py e gerar_fluxos.py)

Lê <fase>/ia/report.json das fases 00, 01, 05, 11, 12 e 13 da análise (a 13 só é lida, nunca alterada) e a interpretação da IA (prompt 4) em
<pasta>/interpretacao-sequencia/sequencia.json; sem esse arquivo, nada é feito. O script não interpreta: confere e desenha, e grava o resultado dentro de
<saida>/12 - business-flows/{human/report.html, ia/report.json}: em cada seção de funcionalidade `<id>` o fluxo interno da funcionalidade (diagrama, tabelas de nós e ligações,
regras fora do fluxo por escopo, lacunas) e a seção `fluxo-interno` com a qualidade das ligações. Idempotente. Não há relacionamento entre funcionalidades.
Confere: toda funcionalidade da fase 12 descrita; ids, tipos e confiança válidos; todas as regras que a fase 12 relaciona a cada funcionalidade presentes no fluxo; cada corporativa que a
funcionalidade chama (aresta do diagrama de hierarquia) presente no fluxo e ligada por `chama`; todo nó com caminho desde ENTRADA e até SAIDA, sem ciclo; cada literal citado existe no texto dos
relatórios das pontas da ligação (seções da funcionalidade, das regras e da corporativa, mapa de decisão do programa das pontas, fase 13, fase 1 e arestas do diagrama de hierarquia). Sai com erro se algo falhar.
Diagramas em fluxograma (sem colunas). Mesma entrada, mesma saída."""
import json
import re
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
import gerar_simulacao as S  # noqa: E402
import report_model as rm  # noqa: E402

TIPOS_FLUXO = {'dado', 'condicao', 'estado', 'chama', 'ordem'}
CONF = {'alta', 'média', 'baixa'}
VIRTUAIS = {'ENTRADA', 'SAIDA'}
ID_FUNC = re.compile(r'^(F|FC|D)\d+$')


def _norm(t):
    return ' '.join(S.sem_copybook(str(t)).lower().split())


def _texto_bloco(b):
    if b['type'] == 'text':
        return [S.txt(b.get('text'))]
    if b['type'] == 'table':
        return [S.txt(c) + ' ' + ' '.join(_links(c)) for r in b['rows'] for c in r] + [S.txt(c) for c in b['columns']]   # célula de ids vem como {text:'', links:[...]}: o texto visível é o dos links
    if b['type'] == 'graph':
        return [S.txt(n.get('label')) for n in b['nodes']] + [f'{e["from"]}→{e["to"]}' for e in b['edges']] + [S.txt(e.get('label')) for e in b['edges']]
    if b['type'] == 'bands':
        return [S.txt(c) for r in b['rows'] for c in r['cells']]
    return []


def _links(c):
    """Textos dos links de uma célula (a coluna de ids vem como {text:'', links:[...]})."""
    if isinstance(c, dict):
        return [x.get('text', '') for x in c.get('links', [])] + ([c['text']] if c.get('text') else [])
    return [S.txt(c)] if c else []


def ler(entrada):
    """Seções por id das fases 11 e 12 (texto completo), texto da fase 1, regras relacionadas a cada funcionalidade e nomes."""
    f11, f10, f1 = S.fase(entrada, '12 '), S.fase(entrada, '11 '), S.fase(entrada, '01-')   # f11 = business-flows (fase 12), f10 = business-rules (fase 11)
    for s in f11['sections']:   # o fluxo interno de uma rodada anterior não é evidência dele mesmo
        s['blocks'] = [b for b in s['blocks'] if b.get('origem') != 'fluxo-interno']
    ev, nomes, regras_de, tit = {}, {}, {}, {}
    for s in f11['sections']:
        if not ID_FUNC.match(s['id']):
            continue
        ev[s['id']] = _norm(' '.join(S.txt(s.get('title')) + ' ' + ' '.join(t for b in s['blocks'] for t in _texto_bloco(b)) for _ in [0]))
        nomes[s['id']] = s['title'].split(' · ', 1)[-1]
        rel = []
        for b in s['blocks']:
            if b['type'] == 'table' and (b.get('title') or '').endswith('regras de negócio relacionadas'):
                for r in b['rows']:
                    rel += [x for x in _links(r[0]) if re.match(r'^[A-Z]\d+\.\w+', x)]
        regras_de[s['id']] = list(dict.fromkeys(rel))
    categoria = {}   # id de regra -> coluna (categoria) do diagrama macro da fase 12, que dá a cor da regra nos fluxos
    tm = next((b for s in f11['sections'] for b in s['blocks'] if b['type'] == 'table' and (b.get('title') or '').startswith('Tabela do diagrama macro')), None)
    for r in (tm or {}).get('rows', []):
        for k, cel in enumerate(r):
            for x in _links(cel):
                if re.match(r'^[A-Z]\d+\.\w+', x) and k < len(tm['columns']):
                    categoria[x] = tm['columns'][k] if isinstance(tm['columns'][k], str) else tm['columns'][k].get('name', '')
    consultas = {}   # comandos e tabelas dinâmicos não entram nos fluxos: são do mapeamento SQL (fase 10); os fluxos só citam regras de negócio
    for s in f10['sections']:
        if re.match(r'^[A-Z]\d+\.\w+$', s['id']):
            ev[s['id']] = _norm(s['title'] + ' ' + ' '.join(t for b in s['blocks'] for t in _texto_bloco(b)))
            tit[s['id']] = s['title']
    for fid, rs in regras_de.items():   # a evidência de uma funcionalidade inclui as seções das regras de negócio que a fase 12 relaciona a ela
        ev[fid] = ev[fid] + ' ' + ' '.join(ev.get(r, '') for r in rs)
    hier = next((b for s in f11['sections'] if s['id'] == 'hierarquia' for b in s['blocks'] if b['type'] == 'graph'), None)
    arestas = [(e['from'], e['to']) for e in (hier or {}).get('edges', [])]
    chamadas = {}
    for a, b in arestas:
        chamadas.setdefault(a, []).append(b)
    t1 = _norm(' '.join(t for s in f1['sections'] for b in s['blocks'] for t in _texto_bloco(b)))
    arv = {}
    try:
        f5 = S.fase(entrada, '05-')
        for s in f5['sections']:
            if s['id'].startswith('prog-'):
                arv[s['id'][5:]] = _norm(' '.join(t for b in s['blocks'] for t in _texto_bloco(b)))
    except Exception:
        pass
    excl = {}
    try:
        f12 = S.fase(entrada, '13 ')
        for s in f12['sections']:
            if not s['id'].startswith('rastreio-'):
                continue
            tb = next((b for b in s['blocks'] if b['type'] == 'table' and b.get('origem') != 'fluxo-interno' and (b.get('title') or '').startswith('Tabela do diagrama')), None)
            vistos = {}
            for r in (tb or {}).get('rows', []):
                regra, sit, motivo, vinc = S.txt(r[1]), S.txt(r[4]), S.txt(r[5]), S.txt(r[6])
                if regra in ('', '—') or sit != 'descartada':
                    continue
                destino = vinc.rsplit(': ', 1)[-1].strip()
                why = motivo.split('regra: ', 1)[-1].strip() if 'regra: ' in motivo else motivo
                vistos.setdefault((destino, why), set()).add(regra)
            excl[s['id'][9:]] = {k: sorted(v) for k, v in vistos.items()}
    except SystemExit:
        pass
    for fid, ex in excl.items():   # a evidência de uma funcionalidade inclui as regras determinísticas que a fase 13 deixou fora por escopo (por exemplo, o roteamento que chama uma corporativa)
        if fid in ev:
            ev[fid] += ' ' + _norm(' '.join(r for rs in ex.values() for r in rs))
    return {'consultas': consultas, 'excl': excl, 'arv': arv, 'ev': ev, 'nomes': nomes, 'regras': regras_de, 'regra_titulo': tit, 'categoria': categoria, 'fase1': t1, 'arestas': arestas, 'chamadas': chamadas}


def _alcanca(ini, adj):
    vis, fila = {ini}, [ini]
    while fila:
        for y in adj.get(fila.pop(), ()):
            if y not in vis:
                vis.add(y)
                fila.append(y)
    return vis


def _tem_ciclo(ini, adj):
    cor = {}

    def dfs(x):
        cor[x] = 1
        for y in adj.get(x, ()):
            if cor.get(y) == 1 or (y not in cor and dfs(y)):
                return True
        cor[x] = 2
        return False
    return dfs(ini)


def medir(d, interp):
    """Metas de ligação: {id: {'nos', 'ligacoes', 'alta', 'lacunas', 'problemas'}} e o total; 100% = todas alta, sem lacuna e sem problema."""
    out = {}
    for f in interp['funcionalidades']:
        fl = f.get('fluxo') or {}
        lg = fl.get('ligacoes', [])
        out[f['id']] = {'nos': sum(1 for n in fl.get('nos', []) if n['tipo'] in ('regra', 'erro', 'corporativa', 'consulta')), 'ligacoes': len(lg),
                        'alta': sum(1 for l in lg if l.get('confianca') == 'alta'), 'lacunas': len(f.get('lacunas', []))}
    return out


def conferir(d, interp):
    erros = []
    funcs = {f['id']: f for f in interp.get('funcionalidades', [])}
    for fid in d['nomes']:
        if fid not in funcs:
            erros.append(f'{fid}: funcionalidade da fase 12 sem entrada na interpretação')
    ids_ok = set(d['nomes']) | set(d['regra_titulo']) | set(d['consultas']) | VIRTUAIS

    def cita_ok(lit, pontas, chama=False):
        n = _norm(lit)
        if re.match(r'^[\w.]+→[\w.]+$', lit) and (tuple(lit.split('→')) in set(d['arestas'])):
            return True
        base = ' '.join(d['ev'].get(p, '') for p in pontas)
        progs = {r.split('.', 1)[1] for p in pontas for r in ([p] if '.' in p else d['regras'].get(p, [])) if '.' in r}
        base += ' ' + ' '.join(d['arv'].get(x, '') for x in progs)
        if chama:
            base += ' ' + d['fase1']
        return n in base

    for fid, f in funcs.items():
        if fid not in d['nomes']:
            erros.append(f'{fid}: id fora da fase 12')
            continue
        fl = f.get('fluxo') or {}
        nos = {n['id']: n for n in fl.get('nos', [])}
        ligs = fl.get('ligacoes', [])
        for r in d['regras'].get(fid, []):
            if r not in nos:
                erros.append(f'{fid}: regra {r} (fase 12) fora do fluxo')
        for c in d['chamadas'].get(fid, []):
            if ID_FUNC.match(c):
                if c not in nos:
                    erros.append(f'{fid}: funcionalidade corporativa {c} (fase 12) fora do fluxo')
                elif not any(l['para'] == c and l['tipo'] == 'chama' for l in ligs):
                    erros.append(f'{fid}: corporativa {c} sem ligação `chama` que a coloque no fluxo')
        for i, n in nos.items():
            if i not in ids_ok:
                erros.append(f'{fid}.fluxo: nó {i} inexistente')
            elif n['tipo'] in ('regra', 'erro') and i not in d['regras'].get(fid, []):
                erros.append(f'{fid}.fluxo: regra {i} não está nas regras de negócio relacionadas a {fid} na fase 12 (regra de outra funcionalidade; regras de funcionalidade corporativa não entram na de entry point, nem o contrário)')
            elif n['tipo'] == 'consulta':
                erros.append(f'{fid}.fluxo: nó do tipo "consulta" ({i}) não existe; o fluxo cita só regras de negócio (os comandos SQL estão no mapeamento SQL, fase 10)')
            elif n['tipo'] == 'corporativa' and i not in d['chamadas'].get(fid, []):
                erros.append(f'{fid}.fluxo: corporativa {i} no fluxo, mas a fase 12 não diz que {fid} a chama')
        if 'ENTRADA' in nos and 'SAIDA' in nos and any(n['tipo'] in ('regra', 'erro', 'corporativa', 'consulta') for n in nos.values()):   # só virtuais: nada a encadear
            adj, radj = {}, {}
            for l in ligs:
                adj.setdefault(l['de'], set()).add(l['para'])
                radj.setdefault(l['para'], set()).add(l['de'])
            for i in sorted(set(nos) - _alcanca('ENTRADA', adj)):
                erros.append(f'{fid}.fluxo: nó {i} sem caminho desde ENTRADA')
            for i in sorted(set(nos) - _alcanca('SAIDA', radj)):
                erros.append(f'{fid}.fluxo: nó {i} não chega a SAIDA')
            if _tem_ciclo('ENTRADA', adj):
                erros.append(f'{fid}.fluxo: ciclo nas ligações')
        for l in ligs:
            for p in (l['de'], l['para']):
                if p not in nos:
                    erros.append(f'{fid}.fluxo: ligação {l["de"]}->{l["para"]} usa nó fora de `nos`')
            if l['tipo'] not in TIPOS_FLUXO:
                erros.append(f'{fid}.fluxo {l["de"]}->{l["para"]}: tipo {l["tipo"]} inválido')
            if l.get('confianca') not in CONF:
                erros.append(f'{fid}.fluxo {l["de"]}->{l["para"]}: confiança inválida')
            pontas = [fid] + [p for p in (l['de'], l['para']) if p not in VIRTUAIS]
            for lit in l.get('cita', []):
                if not cita_ok(lit, pontas, chama=(l['tipo'] == 'chama')):
                    erros.append(f'{fid}.fluxo {l["de"]}->{l["para"]}: literal "{lit}" não existe na evidência')
    return erros


# ----------------------------------------------------------------------------- relatório
LINK11 = lambda i: rm.link(i, '12 - business-flows', i)
LINK10 = lambda i: rm.link(i, '11 - business-rules', i)


def _rot(d, i):
    return f'{i} · {d["nomes"][i]}'


def _g_fluxo(d, f):
    fl = f['fluxo']
    nos, ar = [], []
    ordem = sorted(fl['nos'], key=lambda n: (n.get('etapa', 0), n['id']))
    for n in ordem:
        t = n['tipo']
        if t in ('entrada', 'saida'):
            nos.append({'id': n['id'], 'label': n.get('rotulo') or n['id'], 'shape': 'start' if t == 'entrada' else 'end', 'detail': n.get('rotulo') or n['id']})
        else:
            titulo = d['regra_titulo'].get(n['id'], d['nomes'].get(n['id'], ''))
            grupo = {'regra': 'regra de negócio', 'corporativa': 'funcionalidade corporativa', 'erro': 'Tratamento de erro', 'consulta': 'consulta estática (internalizada)'}[t]
            if t in ('regra', 'erro') and d['categoria'].get(n['id']):
                grupo = d['categoria'][n['id']]
            sql = ' | '.join(s_ for _, s_ in d['consultas'].get(n['id'], {}).get('sql', [])) if t == 'consulta' else ''
            nos.append({'id': n['id'], 'label': f'{n["id"]}: ' + (titulo.split(" · ", 1)[-1] if titulo else ''), 'group': grupo,
                        'detail': f'etapa {n.get("etapa")}. entra: {n.get("entra", "")} | sai: {n.get("sai", "")}' + (f' | SQL estático: {sql}' if sql else '')})
    for l in fl['ligacoes']:
        ar.append({'from': l['de'], 'to': l['para'], 'label': l['tipo']})
    g = rm.G(f'{f["id"]}: fluxo interno (regras e corporativas pela entrada e saída)', nos, ar, kind='flowchart',
                note='ENTRADA → regras e funcionalidades corporativas chamadas, na ordem dada pela entrada e saída de cada uma → SAIDA; tratamento de erro em ramo. A seta diz por que uma vem depois da outra: '
                     'dado (o que uma produz a outra usa), condicao (só é alcançada se a anterior passou ou falhou), estado (tabela gravada e lida), chama (chamada a funcionalidade corporativa), ordem (só pela ordem do passo). Entrada, saída e evidência de cada nó estão nas tabelas. As cores são as do diagrama macro: cada regra tem a cor da sua categoria (validação, consulta, alteração de estado, derivação, auditoria, retorno de sucesso, tratamento de erro, outras), e funcionalidade corporativa em laranja.')
    g['largura_max'] = 1100
    return g


def blocos(d, interp, i):
    """Blocos do fluxo interno da funcionalidade `i` (diagrama, tabelas de nós e de ligações, regras fora do fluxo por escopo, lacunas); cada bloco leva origem='fluxo-interno'."""
    f = next((x for x in interp['funcionalidades'] if x['id'] == i), None)
    if f is None:
        return []
    bl = []
    fl = f.get('fluxo')
    if fl and any(n['tipo'] in ('regra', 'erro', 'corporativa', 'consulta') for n in fl['nos']):
        bl.append(_g_fluxo(d, f))
        rows = [[n.get('etapa'), rm.with_links('', [LINK10(n['id']) if n['tipo'] in ('regra', 'erro') else LINK11(n['id'])]) if n['tipo'] not in ('entrada', 'saida') else n['id'],
                 n['tipo'], d['regra_titulo'].get(n['id'], d['nomes'].get(n['id'], n.get('rotulo', ''))).split(' · ', 1)[-1], n.get('entra', ''), n.get('sai', '')] for n in sorted(fl['nos'], key=lambda n: (n.get('etapa', 0), n['id']))]
        bl.append(rm.T(f'{i}: nós do fluxo interno (etapa, entrada e saída)', ['Etapa', 'Nó', 'Tipo', 'Nome', 'Entra', 'Sai'], rows))
        lr = [[l['de'], l['para'], l['tipo'], l['confianca'], l['porque'], ', '.join(l.get('cita', []))] for l in fl['ligacoes']]
        bl.append(rm.T(f'{i}: ligações do fluxo interno', ['De', 'Para', 'Tipo', 'Confiança', 'Por que', 'Evidência citada'], lr))
    else:
        bl.append(rm.X('Fluxo interno: sem regras de negócio nem chamadas corporativas para encadear.'))
    ex = d['excl'].get(i, {})
    if ex:
        linhas = [[dest, why, len(rs), ', '.join(rs[:12]) + (' …' if len(rs) > 12 else '')] for (dest, why), rs in sorted(ex.items(), key=lambda kv: (kv[0][0], -len(kv[1])))]
        bl.append(rm.T(f'{i}: regras determinísticas que ficam fora do fluxo interno por escopo', ['Destino', 'Motivo', 'Regras', 'Quais'], linhas))
    if f.get('lacunas'):
        bl.append(rm.T(f'{i}: lacunas do fluxo interno', ['Lacuna'], [[x] for x in f['lacunas']]))
    for b in bl:
        b['origem'] = 'fluxo-interno'
    return bl


def anexar(saida, d, interp):
    """Põe o fluxo interno de cada funcionalidade na sua seção de 12 - business-flows (seção `<id>`), logo depois da descrição, e uma seção de qualidade das ligações. A fase 13 não é alterada.
    Idempotente: os blocos e seções de uma rodada anterior (origem='fluxo-interno') são trocados."""
    import json as _json
    p = Path(saida) / '12 - business-flows' / 'ia' / 'report.json'
    modelo = _json.loads(p.read_text(encoding='utf-8'))
    modelo['sections'] = [s for s in modelo['sections'] if s.get('origem') != 'fluxo-interno']
    modelo['cards'] = [c for c in modelo.get('cards', []) if c.get('origem') != 'fluxo-interno']
    funcs = {f['id']: f for f in interp['funcionalidades']}
    m = medir(d, interp)
    ordem = [i for i in d['nomes'] if i in funcs]
    for s in modelo['sections']:
        if s['id'] in funcs:
            s['blocks'] = [b for b in s['blocks'] if b.get('origem') != 'fluxo-interno']
            k = 0   # a descrição (blocos de texto logo abaixo do título) vem primeiro; o fluxo interno entra depois dela
            while k < len(s['blocks']) and s['blocks'][k]['type'] == 'text':
                k += 1
            s['blocks'] = s['blocks'][:k] + blocos(d, interp, s['id']) + s['blocks'][k:]
    tipos = lambda i, ts: sum(1 for n in (funcs[i].get('fluxo') or {}).get('nos', []) if n['tipo'] in ts)
    t_lig, t_alta = sum(v['ligacoes'] for v in m.values()), sum(v['alta'] for v in m.values())
    t_lac = sum(v['lacunas'] for v in m.values()) + len(interp.get('problemas', []))
    n_regras = sum(tipos(i, ('regra', 'erro')) for i in ordem)
    n_corp = sum(tipos(i, ('corporativa',)) for i in ordem)
    cob = [[rm.with_links('', [rm.link(i, '12 - business-flows', i)]), d['nomes'][i], tipos(i, ('regra', 'erro')), ', '.join(n['id'] for n in (funcs[i].get('fluxo') or {}).get('nos', []) if n['tipo'] == 'corporativa') or '-',
            m[i]['ligacoes'], m[i]['alta'], m[i]['lacunas']] for i in ordem]
    blk = [rm.X(f'{len(ordem)} funcionalidades; {n_regras} regras de negócio posicionadas nos fluxos internos; {n_corp} chamadas a funcionalidades corporativas dentro dos fluxos; {t_lig} ligações internas, {t_alta} de confiança alta ({100 * t_alta // max(1, t_lig)}%); '
                f'{t_lac} lacunas e problemas que o código e os relatórios não decidem. A interpretação (prompt 4) vem da IA; o script confere as citações, a conectividade (todo nó liga ENTRADA a SAIDA, sem ciclo) e desenha.'),
           rm.T('Fluxo interno: qualidade das ligações por funcionalidade', ['Id', 'Funcionalidade', 'Regras no fluxo', 'Corporativas chamadas no fluxo', 'Ligações internas', 'Ligações de confiança alta', 'Lacunas'], cob)]
    if interp.get('problemas'):
        blk.append(rm.T('Afirmações que a IA não conseguiu sustentar', ['Problema'], [[x] for x in interp['problemas']]))
    for b in blk:
        b['origem'] = 'fluxo-interno'
    sec = rm.S('fluxo-interno', 'Fluxo interno das funcionalidades: qualidade das ligações', blk)
    sec['origem'] = 'fluxo-interno'
    k = next((n for n, s in enumerate(modelo['sections']) if s['id'] == 'dinamicas'), next((n for n, s in enumerate(modelo['sections']) if s['id'] == 'filtros'), 0))
    modelo['sections'].insert(k + 1, sec)
    c1, c2 = rm.card('ligações de confiança alta (%)', 100 * t_alta // max(1, t_lig)), rm.card('lacunas e problemas do fluxo', t_lac)
    for c in (c1, c2):
        c['origem'] = 'fluxo-interno'
    modelo['cards'] = modelo.get('cards', []) + [c1, c2]
    S.escrever(saida, '12 - business-flows', modelo)
    return m, t_lig, t_alta, t_lac


def main():
    args = sys.argv[1:]
    base = None
    if '--interpretacao' in args:
        i = args.index('--interpretacao')
        base = Path(args[i + 1]).resolve()
        del args[i:i + 2]
    if len(args) not in (1, 2) or base is None:
        sys.exit(__doc__)
    ana = Path(args[0])
    saida = Path(args[1]) if len(args) == 2 else ana
    arq = base / 'interpretacao-sequencia' / 'sequencia.json'
    if not arq.is_file():
        print('fluxo interno por funcionalidade: sem interpretacao-sequencia/sequencia.json (prompt 4); a fase 12 fica sem os fluxos internos')
        return
    S.definir_copybooks(ana)
    d = ler(ana)
    interp = json.loads(arq.read_text(encoding='utf-8'))
    erros = conferir(d, interp)
    m, t_lig, t_alta, t_lac = anexar(saida, d, interp)
    print(f'{len(d["nomes"])} funcionalidades; afirmações sem evidência: {len(erros)}; ligações alta {t_alta}/{t_lig}; lacunas+problemas {t_lac}; meta de ligação 100%: {"ATINGIDA" if not erros and t_alta == t_lig else "não atingida"} ({t_lac} lacuna(s)/problema(s) que o código e os relatórios não decidem)')
    for e in erros[:40]:
        print('  ' + e)
    sys.exit(1 if erros else 0)


if __name__ == '__main__':
    main()
