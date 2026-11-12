"""Análise da aplicação web indexada (intranet_indice): cadeia do processo PDC até o managed bean, resolução de expressões EL (bean -> propriedade -> tipo),
mapeamento dos campos nos métodos de serviço (VO <-> request/response) e nas ações do processo PDC (campo do processo <-> campo do layout da transação).
Nenhum nome de projeto no código: tudo é descoberto dos arquivos."""
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import intranet_indice as IX

norm = lambda s: re.sub(r'[^a-z0-9]', '', str(s).lower())
DEC = IX.DECAP


# ------------------------------------------------------------------ tipos
def base(t):
    """`java.util.List<X>` -> `List`; `X[]` -> `X`."""
    t = str(t or '').strip()
    t = re.sub(r'<.*', '', t).replace('[]', '')
    return t.split('.')[-1]


def elem(t):
    """Tipo do elemento de uma lista/array: `List<X>` -> `X`; `Map<K, V>` -> `V`; `X[]` -> `X`; senão ''."""
    t = str(t or '').strip()
    if t.endswith('[]'):
        return base(t[:-2])
    m = re.search(r'<(.*)>', t)
    if m:
        args = IX.divide_args(m.group(1), True)
        return base(args[-1]) if args else ''
    return ''


def preparar(idx):
    if '_simples' in idx:
        return idx
    simples = defaultdict(list)
    for fqn, c in idx['classes'].items():
        simples[c['nome']].append(fqn)
    idx['_simples'] = simples
    idx['_classe_bean'] = defaultdict(list)
    for b in idx['beans'].values():
        idx['_classe_bean'][b['classe']].append(b['nome'])
    rev = defaultdict(list)
    for f, c in idx['classes'].items():
        for n, ms in c['metodos'].items():
            for mi, m in enumerate(ms):
                for r_, mn in m['receptores']:
                    rev[mn].append((f, n, mi))
    idx['_rev'] = rev
    return idx


def fq(idx, tipo, perto=None):
    """Nome simples -> fqn da classe indexada (prefere o mesmo pacote de `perto`)."""
    s = base(tipo)
    cand = idx['_simples'].get(s, [])
    if not cand:
        return None
    if perto:
        pk = perto.rsplit('.', 1)[0]
        for c in cand:
            if c.rsplit('.', 1)[0] == pk:
                return c
    return cand[0]


def hierarquia(idx, fqn):
    out, atual = [], fqn
    while atual and atual not in out and len(out) < 8:
        out.append(atual)
        ext = idx['classes'].get(atual, {}).get('extends') or []
        atual = fq(idx, ext[0], atual) if ext else None
    return out


def interfaces(idx, fqn):
    nomes = set()
    for h in hierarquia(idx, fqn):
        c = idx['classes'][h]
        nomes.add(c['nome'])
        nomes.update(c['implements'])
        nomes.update(c['extends'])
        for i in c['implements']:
            f = fq(idx, i, h)
            if f:
                nomes.update(idx['classes'][f]['extends'])
    return nomes


def tipo_prop(idx, fqn, prop):
    """Tipo da propriedade `prop` (getter sem parâmetros ou campo) da classe, subindo pelas superclasses; `T` genérico vira o argumento do extends."""
    h = hierarquia(idx, fqn)
    for k, f in enumerate(h):
        c = idx['classes'][f]
        for pref in ('get', 'is'):
            for m in c['metodos'].get(pref + IX.CAP(prop), []):
                if not m['params']:
                    t = m['retorno']
                    if re.fullmatch(r'[A-Z]\w?', t or '') and k > 0:
                        args = idx['classes'][h[k - 1]].get('ext_args') or []
                        return args[0] if args else t
                    return t
        if prop in c['campos']:
            t = c['campos'][prop]
            if re.fullmatch(r'[A-Z]\w?', t) and k > 0:
                args = idx['classes'][h[k - 1]].get('ext_args') or []
                return args[0] if args else t
            return t
    return ''


def vars_metodo(idx, fqn, m):
    """{variável: tipo}: parâmetros, locais/for-each do corpo e campos da classe (e superclasses)."""
    out = {}
    for h in reversed(hierarquia(idx, fqn)):
        out.update(idx['classes'][h]['campos'])
    out.update(IX.variaveis(m.get('corpo', '')))
    for t, n in m['params']:
        out[n] = t
    return out


# ------------------------------------------------------------------ cadeia backend
def metodos_do_adaptador(idx, bean_id):
    getters = {'get' + IX.CAP(n) for n in idx['refs'].get(bean_id, [])}
    out = []
    for fqn, c in idx['classes'].items():
        for nome, ms in c['metodos'].items():
            for m in ms:
                if getters & set(m['getters']):
                    out.append((fqn, nome, m))
    return out


def chamadores(idx, fqn, nome):
    """Métodos que chamam `nome` da classe `fqn`: por receptor tipado (variável/campo/getter cujo tipo é a classe, uma interface ou superclasse dela) ou chamada interna da mesma classe."""
    alvo = interfaces(idx, fqn)
    out = set()
    sub = {fqn} | {f for f, c in idx['classes'].items() if fqn in hierarquia(idx, f)[1:]}
    for f2, n2, mi in idx['_rev'].get(nome, []):
        m2 = idx['classes'][f2]['metodos'][n2][mi]
        locais = None
        for rec, mn in m2['receptores']:
            if mn != nome:
                continue
            if rec in ('this', 'super'):
                if f2 in sub:
                    out.add((f2, n2))
                continue
            if locais is None:
                locais = vars_metodo(idx, f2, m2)
            if base(locais.get(rec, '')) in alvo:
                out.add((f2, n2))
    for f2 in sub:
        for n2, ms in idx['classes'][f2]['metodos'].items():
            if any(nome in m['chamadas'] for m in ms) and not any(r[1] == nome for m in ms for r in m['receptores'] if r[0] not in ('this', 'super')):
                out.add((f2, n2))
    return sorted(out)


def cadeia(idx, bean_id, profundidade=6, teto=400):
    """Do adaptador aos managed beans. Devolve {'servico': [(fqn, método)], 'pai': {nó: nó seguinte (em direção ao serviço)}, 'dist': {nó: saltos}, 'beans': {bean: [métodos]}}."""
    preparar(idx)
    base_ = [(f, n) for f, n, _m in metodos_do_adaptador(idx, bean_id)]
    pai, dist = {}, {n: 0 for n in base_}
    nivel = list(base_)
    for d in range(1, profundidade + 1):
        prox = []
        for f, n in nivel:
            for c in chamadores(idx, f, n):
                if c not in dist and len(dist) < teto:
                    dist[c] = d
                    pai[c] = (f, n)
                    prox.append(c)
        if not prox:
            break
        nivel = prox
    beans = defaultdict(set)
    for (f, n) in dist:
        for h_f in [f]:
            for cls, nomes in idx['_classe_bean'].items():
                if cls == h_f or h_f in hierarquia(idx, fq(idx, cls) or cls)[1:]:
                    for b in nomes:
                        beans[b].add(n)
    return {'servico': base_, 'pai': pai, 'dist': dist, 'beans': {k: sorted(v) for k, v in beans.items()}}


def caminho_ate_servico(cad, no):
    out = [no]
    while out[-1] in cad['pai'] and len(out) < 12:
        out.append(cad['pai'][out[-1]])
    return out


# ------------------------------------------------------------------ expressões EL
EL_CAMINHO = re.compile(r"([A-Za-z_]\w*)((?:\s*\.\s*\w+|\[\s*'[^']*'\s*\]|\[\s*\"[^\"]*\"\s*\])*)")


def resolver_el(idx, expr, ambiente):
    """`bean.viewHelper.filtro.plano` -> {'bean','caminho','dono','prop','tipo','var'} resolvendo o tipo de cada propriedade."""
    e = str(expr or '').strip().lstrip('!').strip()
    m = EL_CAMINHO.match(e)
    if not m:
        return None
    cab, resto = m.group(1), m.group(2)
    props = re.findall(r'\.\s*(\w+)', resto)
    base_lista = ''
    if cab in ambiente:
        tipo, bean, var = ambiente[cab], '', cab
        if isinstance(tipo, tuple):
            tipo, bean, base_lista = tipo
    elif cab in idx['beans']:
        tipo, bean, var = idx['beans'][cab]['classe'], cab, ''
    else:
        return None
    dono, prop = '', ''
    for p in props:
        dono, prop = tipo, p
        f = fq(idx, tipo)
        tipo = tipo_prop(idx, f, p) if f else ''
    return {'bean': bean, 'var': var, 'caminho': (base_lista + '[].' if base_lista else '') + '.'.join(props), 'dono': base(dono), 'prop': prop, 'tipo': tipo}


def ambientes(idx, j):
    """Para cada componente da JSP, as variáveis de laço (`var`) visíveis -> tipo do elemento da lista ligada (value)."""
    comps = j['componentes']
    env = {}
    for c in comps:
        e = dict(env.get(c['pai'], {})) if c['pai'] is not None else {}
        v = c['atributos'].get('var')
        if v:
            val = c['atributos'].get('value', '')
            for ex in IX.EL.findall(val):
                r = resolver_el(idx, ex, e)
                if r:
                    e[v] = (elem(r['tipo']) or r['tipo'], r['bean'], r['caminho'])
                    break
        env[c['ordem']] = e
    return env


def texto_rotulo(idx, valor):
    """Texto de um rótulo: literal ou a mensagem do arquivo de recursos (`#{msgs.chave}`)."""
    v = str(valor or '').strip()
    exprs = IX.EL.findall(v)
    if not exprs:
        return v
    out = []
    for ex in exprs:
        m = re.search(r"\.(\w+)\s*$|\['([^']+)'\]", ex.strip())
        chave = (m.group(1) or m.group(2)) if m else ex
        msg = idx.get('rotulos', {}).get(chave)
        out.append(msg[0] if msg else f'«{chave}»')
    return ' '.join(out)


# ------------------------------------------------------------------ serviço
def chamada_ate(texto, i):
    """Texto dos parênteses que abrem em texto[i] == '(' (até o fecha-parênteses correspondente)."""
    d, j = 0, i
    while j < len(texto):
        if texto[j] == '(':
            d += 1
        elif texto[j] == ')':
            d -= 1
            if d == 0:
                return texto[i + 1:j]
        j += 1
    return texto[i + 1:]


def classes_do_pacote(idx, pacote, principais=()):
    """Classes do pacote (arquivos irmãos) e classes aninhadas nas classes principais (request/response)."""
    out = {f.rsplit('.', 1)[1] for f in idx['fqn_arq'] if pacote and f.rsplit('.', 1)[0] == pacote}
    for p in principais:
        arq = idx['fqn_arq'].get(f'{pacote}.{p}')
        if arq:
            out |= set(re.findall(r'\bclass\s+(\w+)', IX.ler(arq)))
    return out


def sem_cabecalho_for(corpo):
    """Remove os cabeçalhos `for (...)` do texto (o corpo do laço continua)."""
    out, i = '', 0
    for m in re.finditer(r'\bfor\s*\(', corpo):
        if m.start() < i:
            continue
        txt = chamada_ate(corpo, m.end() - 1)
        out += corpo[i:m.start()]
        i = m.end() + len(txt) + 1
    return out + corpo[i:]


def mapa_servico(idx, fqn, metodo, adap, getters):
    """Para o método do serviço que chama o adaptador: {'ent': [(grupo, campo do request, [(tipo, propriedade)] | constante)], 'sai': [(grupo, campo do response, alvo)],
    'params', 'retorno', 'assinatura'}. Grupo = classe do item (vazio = o próprio request/response)."""
    c = idx['classes'][fqn]
    res = {'ent': [], 'sai': [], 'params': [], 'retorno': '', 'assinatura': ''}
    req_cls = classes_do_pacote(idx, adap['pacote_request'], (adap['request'],))
    resp_cls = classes_do_pacote(idx, adap['pacote_response'], (adap['response'],))
    for m in c['metodos'].get(metodo, []):
        if not (set(getters) & set(m['getters'])):
            continue
        corpo = m.get('corpo', '')
        locais = vars_metodo(idx, fqn, m)
        res['params'], res['retorno'], res['assinatura'] = m['params'], m['retorno'], m['assinatura']
        grupo = lambda t: '' if base(t) in (adap['request'], adap['response']) else base(t)
        # entrada: X.setY(...) em variável do tipo de request (ou item de request)
        for mm in re.finditer(r'\b(\w+)\s*\.\s*set(\w+)\s*\(', corpo):
            v, campo = mm.group(1), DEC(mm.group(2))
            tv = base(locais.get(v, ''))
            args = chamada_ate(corpo, mm.end() - 1)
            if tv in req_cls and tv != adap['response']:
                origem = []
                for gv, gp in re.findall(r'\b(\w+)\s*\.\s*get(\w+)\s*\(\s*\)', args):
                    tg = base(locais.get(gv, ''))
                    if tg in req_cls or tg in resp_cls:
                        continue
                    origem.append((tg or gv, DEC(gp)))
                if not origem and re.fullmatch(r'\s*(\w+)\s*', args) and args.strip() in {p[1] for p in m['params']}:
                    origem = [('@param', args.strip())]   # valor vem de um parâmetro do método de serviço (argumento da chamada no bean)
                res['ent'].append((grupo(tv), campo, origem or 'constante'))
        # saída: getters em variável de tipo do response (ou item do response)
        grupos_resp = {norm(x) for x in resp_cls}
        for st in re.split(r';', sem_cabecalho_for(corpo)):
            sel = re.search(r'new\s+SelectItem\s*\(', st)
            alvo_st = st[sel.start():] if sel else st   # com SelectItem, só os getters dos argumentos dele (os da condição do if não são valor/rótulo)
            gets = [(gv, DEC(gp)) for gv, gp in re.findall(r'\b(\w+)\s*\.\s*get(\w+)\s*\(\s*\)', alvo_st) if base(locais.get(gv, '')) in resp_cls and norm(gp) not in grupos_resp]
            gets = [(grupo(locais[gv]), gp) for gv, gp in gets]
            # item de lista acessado em cadeia: response.getLista().get(i).getCampo()
            por_norm = {norm(x): x for x in resp_cls}
            for gv, gl, gp in re.findall(r'\b(\w+)\s*\.\s*get(\w+)\s*\(\s*\)\s*\.\s*get\s*\([^()]*\)\s*\.\s*get(\w+)\s*\(\s*\)', alvo_st):
                if base(locais.get(gv, '')) in resp_cls and norm(gl) in por_norm:
                    gets.append((por_norm[norm(gl)], DEC(gp)))
            if not gets:
                continue
            alvo = re.search(r'\b(\w+)\s*\.\s*set(\w+)\s*\(', st)
            sel = re.search(r'new\s+SelectItem\s*\((.*)\)', st, re.S)
            for ordem, (g, gp) in enumerate(gets):
                if sel:
                    parts = IX.divide_args(sel.group(1))
                    g_ = 'get' + IX.CAP(gp)
                    em_v, em_r = g_ in parts[0], len(parts) > 1 and g_ in parts[1]
                    papel = 'valor e rótulo' if em_v and em_r else 'valor' if em_v else 'rótulo' if em_r else 'item da lista'
                    res['sai'].append((g, gp, ('SelectItem', papel)))
                elif alvo and base(locais.get(alvo.group(1), '')) not in resp_cls:
                    res['sai'].append((g, gp, (base(locais.get(alvo.group(1), '')) or alvo.group(1), DEC(alvo.group(2)))))
                else:
                    res['sai'].append((g, gp, ('', '')))
        break
    res['sai'] = sorted(set(res['sai']))
    return res


# ------------------------------------------------------------------ PDC: ação do processo (campo do processo <-> campo do layout)
def _dec_fonte(G, node, nome):
    return G.dec(node.findtext(nome))


def pdc_processo(G, pasta, nome_processo):
    """Versões do processo: [{'versao','arquivo','transacoes': {tx: {'ent': {elemento: caminho do layout}, 'sai': {...}, 'campos': {campo: (pic, bytes, tipo)}}}}]."""
    out = []
    for f in sorted(Path(pasta).glob('*.xml')):
        txt = f.read_bytes().decode('latin-1')
        if nome_processo not in txt:
            continue
        raiz = ET.fromstring(f.read_bytes())
        for p in raiz.iter('processo'):
            if (p.findtext('nome') or '').strip() != nome_processo:
                continue
            txs = {}
            campos = {}
            for t in p.iterfind('transacoes/transacao'):
                tn = (t.findtext('nome') or '').strip()
                cp = {}
                for m in re.finditer(r'<field\s+name="([^"]+)"([^>]*)/?>', G.dec(t.findtext('fonte'))):
                    a = dict(re.findall(r'(\w+)="([^"]*)"', m.group(2)))
                    cp[m.group(1)] = (a.get('pic', ''), a.get('bytes', ''), a.get('type', ''))
                campos[tn] = cp
            for a in p.iterfind('acoes/acao'):
                fonte = G.dec(a.findtext('fonte'))
                tx = next((tn for tn in campos if tn.lower() in (a.findtext('nome') or '').lower() or tn.lower() in fonte[:2000].lower()), '')
                ent, sai = acao_campos(fonte)
                if ent or sai:
                    d = txs.setdefault(tx, {'ent': {}, 'sai': {}, 'campos': campos.get(tx, {})})
                    d['ent'].update(ent)
                    d['sai'].update(sai)
            out.append({'versao': (p.findtext('versao') or '').strip(), 'arquivo': f.name, 'transacoes': txs})
    return out


DECL_EL = re.compile(r'\b(IProcessMessageElement|ITransactionMessageElement)\s+(\w+)\s*=\s*([^;]+);')
SET_EL = re.compile(r'\b(\w+)\s*\.\s*setElementValue\s*\(\s*"([^"]+)"\s*,\s*([^;]*?)\)\s*;', re.S)


def acao_campos(fonte):
    """Na ação (pre/post): {elemento do processo: caminho do campo do layout} de entrada (pre) e de saída (post). Elementos de repetição ganham o prefixo do grupo (`Grupo.campo`)."""
    tipo, prefixo = {}, {}
    for t, v, expr in DECL_EL.findall(fonte):
        tipo[v] = t
        m = re.match(r'\s*(\w+)\s*\.\s*getElement\s*\(\s*"([^"]+)"', expr)
        prefixo[v] = (prefixo.get(m.group(1), '') + ('.' if prefixo.get(m.group(1)) else '') + m.group(2)) if m else ''
    ent, sai = {}, {}
    for v, nome, expr in SET_EL.findall(fonte):
        g = re.search(r'\b(\w+)\s*\.\s*getElementValue\s*\(\s*"([^"]+)"', expr)
        if not g or v not in tipo:
            continue
        gv, gn = g.group(1), g.group(2)
        if tipo[v] == 'ITransactionMessageElement' and tipo.get(gv) == 'IProcessMessageElement':
            ent[(prefixo[gv] + '.' if prefixo.get(gv) else '') + gn] = (prefixo[v] + '.' if prefixo.get(v) else '') + nome
        elif tipo[v] == 'IProcessMessageElement' and tipo.get(gv) == 'ITransactionMessageElement':
            sai[(prefixo[v] + '.' if prefixo.get(v) else '') + nome] = (prefixo[gv] + '.' if prefixo.get(gv) else '') + gn
    return ent, sai


def escolher_versao(versoes, versao):
    exatas = [v for v in versoes if v['versao'] == versao and v['transacoes']]
    pool = exatas or [v for v in versoes if v['transacoes']]
    return max(pool, key=lambda v: (v['versao'], v['arquivo'])) if pool else None


def campo_layout(versao, grupo, campo, direcao):
    """(transação, caminho do layout, nome do campo, pic, bytes, tipo) do elemento `grupo.campo` do processo; vazio se a ação não o traz."""
    if not versao:
        return None
    chave = norm((grupo + '.' if grupo else '') + campo)
    for tx, d in versao['transacoes'].items():
        mapa = d[direcao]
        for el, caminho in mapa.items():
            if norm(el) == chave or (not grupo and norm(el.split('.')[-1]) == norm(campo) and '.' not in el):
                leaf = caminho.split('.')[-1]
                pic = d['campos'].get(leaf, ('', '', ''))
                return (tx, caminho, leaf, pic[0], pic[1], pic[2])
    # grupo aninhado: casa pelo último trecho do grupo + campo
    for tx, d in versao['transacoes'].items():
        for el, caminho in d[direcao].items():
            partes = el.split('.')
            if len(partes) >= 2 and norm(partes[-2] + partes[-1]) == chave:
                leaf = caminho.split('.')[-1]
                pic = d['campos'].get(leaf, ('', '', ''))
                return (tx, caminho, leaf, pic[0], pic[1], pic[2])
    return None


# ------------------------------------------------------------------ lado do managed bean: chamada ao serviço (alvo e argumentos)
def _cadeia_propriedades(expr):
    """`getViewHelper().getFiltro()` / `this.filtro` -> ['viewHelper', 'filtro']; None se não for só uma cadeia de propriedades."""
    e = expr.strip()
    e = re.sub(r'^\(\w[\w.<>]*\)\s*', '', e)
    e = re.sub(r'^this\s*\.\s*', '', e)
    if not re.fullmatch(r'(?:get\w+\(\s*\)|\w+)(?:\s*\.\s*(?:get\w+\(\s*\)|\w+))*', e):
        return None
    return [DEC(re.sub(r'^get(\w+)\(\s*\)$', r'\1', p.strip())) if re.match(r'get\w+\(', p.strip()) else p.strip() for p in re.split(r'\s*\.\s*', e)]


def _tipo_do_caminho(idx, bean_fqn, partes):
    tipo = bean_fqn
    for p in partes:
        f = fq(idx, tipo, bean_fqn)
        if not f:
            return ''
        tipo = tipo_prop(idx, f, p)
    return tipo


def chamadas_no_bean(idx, bean_fqn, metodo, callee_f, callee_n):
    """No corpo de `metodo` (na classe do bean ou em suas superclasses), cada chamada a `callee_n` do tipo `callee_f`:
    [{'alvo': 'viewHelper.comboCanal' (onde o retorno é guardado) ou '', 'args': [{'expr','caminho','tipo'}]}]."""
    alvo_tipos = interfaces(idx, callee_f)
    out = []
    for h in hierarquia(idx, bean_fqn):
        for m in idx['classes'][h]['metodos'].get(metodo, []):
            corpo = m.get('corpo', '')
            locais = vars_metodo(idx, h, m)
            for mm in re.finditer(r'(?:\bget(\w+)\(\s*\)|\b(\w+))\s*\.\s*' + re.escape(callee_n) + r'\s*\(', corpo):
                rec = (DEC(mm.group(1)) if mm.group(1) else mm.group(2))
                if rec not in ('this', 'super') and base(locais.get(rec, '')) not in alvo_tipos:
                    continue
                ini = max(corpo.rfind(';', 0, mm.start()), corpo.rfind('{', 0, mm.start()), corpo.rfind('}', 0, mm.start())) + 1
                prefixo = corpo[ini:mm.start()].strip()
                alvo = ''
                ms = re.search(r'((?:this\s*\.\s*)?[\w().\s]*?)\.?\s*set(\w+)\s*\(\s*(?:\(\w[\w<>]*\)\s*)?$', prefixo)
                ma = re.search(r'(?:^|\s)(?:this\s*\.\s*)?(\w+)\s*=\s*(?:\(\w[\w<>]*\)\s*)?$', prefixo)
                if ms:
                    pre = _cadeia_propriedades(ms.group(1)) if ms.group(1).strip() else []
                    alvo = '.'.join((pre or []) + [DEC(ms.group(2))])
                elif ma:
                    var = ma.group(1)
                    if var in idx['classes'][h]['campos']:
                        alvo = var
                    else:   # variável local: procura onde ela é entregue a um setter
                        ms2 = re.search(r'((?:this\s*\.\s*)?[\w().\s]*?)\.?\s*set(\w+)\s*\(\s*' + re.escape(var) + r'\s*[,)]', corpo)
                        if ms2:
                            pre = _cadeia_propriedades(ms2.group(1)) if ms2.group(1).strip() else []
                            alvo = '.'.join((pre or []) + [DEC(ms2.group(2))])
                args = []
                for a in IX.divide_args(chamada_ate(corpo, mm.end() - 1)):
                    partes = _cadeia_propriedades(a)
                    caminho, tipo = '', ''
                    if partes:
                        if len(partes) == 1 and partes[0] in locais and partes[0] not in idx['classes'][h]['campos']:
                            tipo = locais[partes[0]]
                            att = re.search(r'\b' + re.escape(partes[0]) + r'\s*=\s*([^;]+);', corpo)
                            p2 = _cadeia_propriedades(att.group(1)) if att else None
                            if p2:
                                caminho = '.'.join(p2)
                                tipo = _tipo_do_caminho(idx, h, p2) or tipo
                        else:
                            caminho = '.'.join(partes)
                            tipo = _tipo_do_caminho(idx, h, partes)
                    args.append({'expr': ' '.join(a.split())[:80], 'caminho': caminho, 'tipo': tipo})
                out.append({'alvo': alvo, 'args': args})
    return out


# ------------------------------------------------------------------ telas
ENTRADA_VIS = {'caixa de texto', 'área de texto', 'calendário (data)', 'caixa de senha', 'combobox', 'seleção múltipla', 'checkbox', 'radio', 'upload de arquivo'}
ACOES_ATR = ('action', 'actionListener', 'listener', 'onclick', 'actionExpression')


def liga_jsp(idx, caminho):
    """Para cada componente da JSP: expressões resolvidas (valor, ação). Calculado uma vez por JSP."""
    cache = idx.setdefault('_liga', {})
    if caminho in cache:
        return cache[caminho]
    j = idx['jsps'][caminho]
    env = ambientes(idx, j)
    out = {}
    for c in j['componentes']:
        info = {'valor': None, 'acao': None, 'opcoes': None}
        a = c['atributos']
        for ex in IX.EL.findall(a.get('value', '')):
            r = resolver_el(idx, ex, env[c['ordem']])
            if r:
                info['valor'] = dict(r, expressao=ex.strip())
                break
        if c['nome'].lower().endswith('selectitems'):
            info['opcoes'] = info['valor']
        for atr in ACOES_ATR:
            for ex in IX.EL.findall(a.get(atr, '')):
                m = re.match(r'\s*(\w+)\s*\.\s*(\w+)', ex)
                if m and m.group(1) in idx['beans']:
                    info['acao'] = {'bean': m.group(1), 'metodo': m.group(2), 'atributo': atr}
                    break
            if info['acao']:
                break
        out[c['ordem']] = info
    cache[caminho] = out
    return out


def opcoes_fixas(idx, caminho, ordem):
    """Opções fixas de um combo (filhos <f:selectItem> com itemValue e itemLabel): ['valor = texto', ...]; o texto vem do arquivo de recursos quando é #{msgs.chave}."""
    j = idx['jsps'][caminho]
    out = []
    for c in j['componentes']:
        if c['pai'] == ordem and c['tag'].split(':')[-1].lower() == 'selectitem':
            a = c['atributos']
            if 'itemValue' in a or 'itemLabel' in a:
                out.append(f"{a.get('itemValue', '')} = {texto_rotulo(idx, a.get('itemLabel', ''))}")
    return out


def indice_acoes(idx):
    """{(bean, método): [(jsp, ordem)]} dos componentes com ação ligada a um managed bean."""
    if '_acoes' in idx:
        return idx['_acoes']
    out = defaultdict(list)
    for caminho in idx['jsps']:
        for ordem, info in liga_jsp(idx, caminho).items():
            if info['acao']:
                out[(info['acao']['bean'], info['acao']['metodo'])].append((caminho, ordem))
    idx['_acoes'] = out
    return out


def rotulo_do_componente(idx, caminho, ordem):
    """Rótulo de um campo: atributo label, cabeçalho da coluna (facet) ou o texto de rótulo mais próximo antes dele na mesma grade."""
    j = idx['jsps'][caminho]
    comps = j['componentes']
    c = comps[ordem]
    if c['atributos'].get('label'):
        return texto_rotulo(idx, c['atributos']['label'])
    # coluna de listagem: cabeçalho (a própria coluna ou a coluna que contém o componente)
    k = c['ordem'] if c['visual'] == 'coluna da listagem' else c['pai']
    while k is not None:
        pk = comps[k]
        if pk['visual'] == 'coluna da listagem':
            for x in comps:
                if x['pai'] is not None and comps[x['pai']]['nome'].lower() == 'facet' and comps[x['pai']]['pai'] == k and x['atributos'].get('value'):
                    return texto_rotulo(idx, x['atributos']['value'])
            break
        k = pk['pai']
    # rótulo mais próximo antes (sem cruzar outro campo de entrada)
    for x in reversed(comps[max(0, ordem - 14):ordem]):
        if x['visual'] in ENTRADA_VIS or x['visual'] == 'botão':
            break
        if x['visual'] == 'rótulo / texto' and x['atributos'].get('value') and not any(e.strip().split('.')[0] in idx['beans'] for e in IX.EL.findall(x['atributos']['value'])):
            return texto_rotulo(idx, x['atributos']['value'])
    return ''


def posicao_na_grade(j, ordem):
    """(linha, coluna, nº de colunas) do componente na grade de layout que o contém (a célula é o filho direto da grade); None se não há grade."""
    comps = j['componentes']
    c = comps[ordem]
    atual = c
    while atual['pai'] is not None:
        pai = comps[atual['pai']]
        if pai['visual'] == 'grade de layout':
            filhos = [x for x in comps if x['pai'] == pai['ordem'] and x['visual'] != 'núcleo']
            try:
                n = int(re.sub(r'\D', '', pai['atributos'].get('columns', '1')) or 1)
                k = [f['ordem'] for f in filhos].index(atual['ordem'])
            except (ValueError, TypeError):
                return None
            return (k // n + 1, k % n + 1, n)
        atual = pai
    return None


def arvore_tela(idx, caminho, ligados):
    """Wireframe da tela: árvore de componentes visuais {tipo, id, rotulo, liga, direcao, colunas, relacionado, filhos}. `ligados` = {ordem: [descrições da relação com a transação]}."""
    j = idx['jsps'][caminho]
    comps = j['componentes']
    liga = liga_jsp(idx, caminho)
    nos = {}
    visiveis = [c for c in comps if c['visual'] not in ('núcleo',) and c['tag'].split(':')[1].lower() not in ('verbatim', 'facet', 'selectitem')]

    def folha(c):
        v = liga[c['ordem']]
        el = (v['valor'] or {}).get('expressao', '') if v['valor'] else ''
        acao = v['acao']
        return {'ordem': c['ordem'], 'tipo': c['visual'], 'tag': c['tag'], 'id': c['id'], 'rotulo': ((texto_rotulo(idx, c['atributos'].get('value', '')) if c['visual'] == 'rótulo / texto' and not el else '') or (rotulo_do_componente(idx, caminho, c['ordem']) if c['visual'] in ENTRADA_VIS or c['visual'] in ('rótulo / texto', 'coluna da listagem') else '')) or
                (texto_rotulo(idx, c['atributos'].get('value', '')) if c['visual'] in ('botão', 'link', 'rótulo / texto') else ''),
                'liga': el, 'acao': (f'{acao["bean"]}.{acao["metodo"]}' if acao else ''), 'direcao': ('entrada' if c['visual'] in ENTRADA_VIS else 'saída' if el and c['visual'] in ('rótulo / texto', 'coluna da listagem', 'listagem (tabela)') else ''),
                'colunas': (int(re.sub(r'\D', '', c['atributos'].get('columns', '')) or 1) if c['visual'] == 'grade de layout' else 0), 'relacionado': ligados.get(c['ordem'], []), 'filhos': []}
    for c in visiveis:
        nos[c['ordem']] = folha(c)
    raiz = []
    for c in visiveis:
        pai = c['pai']
        while pai is not None and pai not in nos:
            pai = comps[pai]['pai']
        (nos[pai]['filhos'] if pai is not None else raiz).append(nos[c['ordem']])

    def poda(n):
        n['filhos'] = [f for f in (poda(f) for f in n['filhos']) if f]
        util = n['tipo'] not in ('contêiner', 'outro', 'grade de layout', 'coluna da listagem') or n['filhos'] or n['liga'] or n['acao'] or n['rotulo']
        return n if util else None
    arvore = [f for f in (poda(n) for n in raiz) if f]
    return tira_rotulos_repetidos(arvore)


def tira_rotulos_repetidos(arvore):
    """Tira do wireframe os textos de rótulo que repetem o rótulo do campo que vem logo depois (o campo já mostra o rótulo) e os textos iguais em sequência."""
    ordem = []

    def achata(ns):
        for n in ns:
            ordem.append(n)
            achata(n['filhos'])
    achata(arvore)
    so_texto = lambda n: n['tipo'] == 'rótulo / texto' and not n['liga'] and not n['relacionado'] and not n['acao'] and n['rotulo']
    neutro = lambda n: n['tipo'] in ('contêiner', 'outro', 'grade de layout')
    norm_ = lambda t: re.sub(r'[\s:*]+', ' ', str(t or '')).strip().lower()
    cair = set()
    for i, n in enumerate(ordem):
        if not so_texto(n):
            continue
        for m in ordem[i + 1:]:
            if neutro(m):
                continue
            if (m['tipo'] in ENTRADA_VIS and norm_(m['rotulo']) == norm_(n['rotulo'])) or (m['tipo'] == 'rótulo / texto' and norm_(m['rotulo']) == norm_(n['rotulo'])):
                cair.add(id(n))
            break

    def limpa(ns):
        out = []
        for n in ns:
            if id(n) in cair:
                continue
            n['filhos'] = limpa(n['filhos'])
            if n['tipo'] in ('contêiner', 'outro', 'grade de layout') and not n['filhos'] and not n['liga'] and not n['rotulo']:
                continue
            out.append(n)
        return out
    return limpa(arvore)


def resultados_do_metodo(idx, bean_fqn, metodo):
    """Resultados de navegação retornados pelo método (literais e constantes resolvidas)."""
    consts = idx.get('_consts')
    if consts is None:
        consts = defaultdict(list)
        for c in idx['classes'].values():
            for k, v in c['constantes'].items():
                consts[k].append(v)
        idx['_consts'] = consts
    out = set()
    for h in hierarquia(idx, bean_fqn):
        for m in idx['classes'][h]['metodos'].get(metodo, []):
            for r in m['resultados']:
                if r.startswith('"'):
                    out.add(r.strip('"'))
                else:
                    for v in consts.get(r.split('.')[-1], [])[:1]:
                        out.add(v)
    return sorted(out)


# ------------------------------------------------------------------ eventos das telas e ciclo de vida dos beans (quando um dado é carregado)
EVENTO_ATR = ('action', 'actionListener', 'listener', 'valueChangeListener', 'actionExpression', 'onclick')


def indice_eventos(idx):
    """{(bean, método): [evento]} com todo componente cuja ação/escutador/evento chama um managed bean (botão, link, ajax por campo, valor alterado, temporizador, evento de ciclo da página)."""
    if '_eventos' in idx:
        return idx['_eventos']
    out = defaultdict(list)
    for caminho, j in idx['jsps'].items():
        for c in j['componentes']:
            a = c['atributos']
            tag = c['tag'].lower()
            vistos = set()
            for atr in EVENTO_ATR:
                for ex in IX.EL.findall(a.get(atr, '')):
                    m = re.match(r'\s*(\w+)\s*\.\s*(\w+)', ex)
                    if not (m and m.group(1) in idx['beans']) or (m.group(1), m.group(2)) in vistos:
                        continue
                    vistos.add((m.group(1), m.group(2)))
                    ajax = any(k in tag for k in ('support', 'ajax', 'poll'))
                    if atr == 'valueChangeListener':
                        ev = 'alteração do valor'
                    elif 'poll' in tag:
                        ev = 'temporizador (poll)'
                    elif 'scroller' in tag:
                        ev = 'troca de página (paginação)'
                    elif a.get('type') in ('preRenderView', 'postAddToView', 'preValidate'):
                        ev = a['type']
                    elif a.get('event'):
                        ev = a['event']
                    elif c['visual'] in ('botão', 'link'):
                        ev = 'clique'
                    else:
                        ev = 'não informado'
                    out[(m.group(1), m.group(2))].append({'jsp': caminho, 'ordem': c['ordem'], 'tag': c['tag'], 'atributo': atr, 'evento': ev, 'ajax': ajax,
                                                          'alvo': c['pai'] if ajax and c['pai'] is not None else c['ordem'], 'rerender': a.get('reRender') or a.get('render') or a.get('update') or ''})
    idx['_eventos'] = out
    return out


def ciclo_vida(idx, fqn):
    """Métodos do bean executados na criação: chamados pelo construtor ou anotados com @PostConstruct (lidos do fonte, uma vez por classe)."""
    cache = idx.setdefault('_ciclo', {})
    if fqn in cache:
        return cache[fqn]
    r = {'construtor': set(), 'posconstruct': set()}
    c = idx['classes'].get(fqn)
    try:
        t = IX.ler(c['arquivo']) if c else ''
    except Exception:
        t = ''
    if t:
        for m in re.finditer(r'@PostConstruct\s*(?:@\w+(?:\([^)]*\))?\s*)*(?:public|protected|private)?\s*(?:final\s+)?\w+\s+(\w+)\s*\(', t):
            r['posconstruct'].add(m.group(1))
        for m in re.finditer(r'(?:public|protected|private)\s+' + re.escape(c['nome']) + r'\s*\([^)]*\)\s*(?:throws[^{]*)?\{', t):
            corpo = t[m.end() - 1:IX.corpo_ate_chave(t, m.end() - 1) + 1]
            r['construtor'] |= set(re.findall(r'\b(\w+)\s*\(', corpo))
    cache[fqn] = r
    return r
