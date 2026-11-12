"""Indexação da aplicação web (Java + JSF/JSP + Spring) da intranet, sem nenhum nome de projeto no código: tudo é descoberto dos arquivos.

Descobre, por arquivo:
  - Spring: beans com a propriedade `processName` (adaptador de processo PDC): id, processo, versão, classes de request e response, pacotes; e a propriedade da fábrica que referencia cada adaptador;
  - JSF: managed beans (nome, classe, escopo, propriedades injetadas), regras de navegação, definições de tiles (tela -> JSP), padrões de URL do servlet (web.xml);
  - Java: classes e métodos (chamadas, adaptadores usados) fora dos pacotes gerados dos processos;
  - JSP: árvore de componentes (tag, id, valor ligado, ação, rótulo), expressões EL e eventos ajax.
Tudo é lido em modo texto latin-1 (as fontes antigas não são UTF-8)."""
import json
import os
import re
from collections import defaultdict
from pathlib import Path

ATTR = re.compile(r'([\w:.-]+)\s*=\s*("([^"]*)"|\'([^\']*)\')', re.S)
TAG = re.compile(r'<(/?)([\w-]+):([\w.-]+)((?:\s+[\w:.-]+\s*=\s*(?:"[^"]*"|\'[^\']*\'))*)\s*(/?)>', re.S)
EL = re.compile(r'[#$]\{([^}]*)\}')
CAP = lambda s: s[:1].upper() + s[1:]
DECAP = lambda s: s[:1].lower() + s[1:]
SEM_VISUAL = ('f', 'c', 'fn', 'jsp', 'x', 'fmt')   # prefixos de núcleo (conversores, validadores, itens): não são componentes visuais


def ler(p):
    return Path(p).read_bytes().decode('latin-1')


def arquivos(raiz, exts):
    out = []
    for r, ds, fs in os.walk(raiz):
        ds[:] = [d for d in ds if d not in ('.svn', '.git', 'node_modules')]
        for f in fs:
            if f.lower().endswith(exts):
                out.append(Path(r) / f)
    return sorted(out)


# ------------------------------------------------------------------ Spring / JSF / web.xml
def spring(arqs):
    """Beans com `processName`: {id: {...}} e {id do adaptador: [propriedades de fábrica que o referenciam]}."""
    adaptadores, refs = {}, defaultdict(set)
    for a in arqs:
        t = ler(a)
        if 'processName' not in t and 'ref="' not in t:
            continue
        for m in re.finditer(r'<bean\b[^>]*\bid="([^"]+)"[^>]*>(.*?)</bean>', t, re.S):
            corpo = m.group(2)
            props = dict(re.findall(r'<property\s+name="([^"]+)"\s+value="([^"]*)"', corpo))
            if 'processName' in props:
                adaptadores[m.group(1)] = {'bean': m.group(1), 'processo': props['processName'], 'versao': props.get('processVersion', ''), 'request': props.get('baseClassRequestName', ''),
                                           'response': props.get('baseClassResponseName', ''), 'pacote_request': props.get('packageRequest', ''), 'pacote_response': props.get('packageResponse', ''),
                                           'pacote_adaptador': props.get('adapterPackage', ''), 'arquivo': a.name}
            for n, r in re.findall(r'<property\s+name="([^"]+)"\s+ref="([^"]+)"', corpo):
                refs[r].add(n)
    return adaptadores, {k: sorted(v) for k, v in refs.items()}


def faces(arqs):
    beans, nav, tiles = {}, [], {}
    for a in arqs:
        t = ler(a)
        for m in re.finditer(r'<managed-bean>(.*?)</managed-bean>', t, re.S):
            c = m.group(1)
            g = lambda tag: (re.search(rf'<{tag}>\s*(.*?)\s*</{tag}>', c, re.S) or [None, ''])[1].strip()
            props = [(re.search(r'<property-name>\s*(.*?)\s*</property-name>', p, re.S).group(1),
                      ((re.search(r'<value>\s*(.*?)\s*</value>', p, re.S) or [0, ''])[1])) for p in re.findall(r'<managed-property>(.*?)</managed-property>', c, re.S)]
            if g('managed-bean-name'):
                beans[g('managed-bean-name')] = {'nome': g('managed-bean-name'), 'classe': g('managed-bean-class'), 'escopo': g('managed-bean-scope'), 'propriedades': props, 'arquivo': a.name}
        for m in re.finditer(r'<navigation-rule>(.*?)</navigation-rule>', t, re.S):
            de = (re.search(r'<from-view-id>\s*(.*?)\s*</from-view-id>', m.group(1), re.S) or [0, '*'])[1]
            for c in re.findall(r'<navigation-case>(.*?)</navigation-case>', m.group(1), re.S):
                g = lambda tag: (re.search(rf'<{tag}>\s*(.*?)\s*</{tag}>', c, re.S) or [None, ''])[1].strip()
                nav.append({'de': de, 'acao': g('from-action'), 'resultado': g('from-outcome'), 'para': g('to-view-id'), 'redirect': '<redirect' in c})
        for m in re.finditer(r'<definition\s+name="([^"]+)"(?:\s+extends="([^"]*)")?[^>]*>(.*?)</definition>', t, re.S):
            puts = dict(re.findall(r'<put\s+name="([^"]+)"\s+value="([^"]*)"', m.group(3)))
            tiles[m.group(1)] = {'extends': m.group(2) or '', 'puts': puts}
    return beans, nav, tiles


def web_xml(arqs):
    out = {'servlets': [], 'padroes': [], 'filtros': []}
    for a in arqs:
        if a.name != 'web.xml':
            continue
        t = ler(a)
        sv = dict(re.findall(r'<servlet>.*?<servlet-name>\s*(.*?)\s*</servlet-name>.*?<servlet-class>\s*(.*?)\s*</servlet-class>', t, re.S))
        for n, p in re.findall(r'<servlet-mapping>.*?<servlet-name>\s*(.*?)\s*</servlet-name>.*?<url-pattern>\s*(.*?)\s*</url-pattern>', t, re.S):
            out['padroes'].append({'servlet': n, 'classe': sv.get(n, ''), 'padrao': p})
        for n, p in re.findall(r'<filter-mapping>.*?<filter-name>\s*(.*?)\s*</filter-name>.*?<url-pattern>\s*(.*?)\s*</url-pattern>', t, re.S):
            out['filtros'].append({'filtro': n, 'padrao': p})
    return out


# ------------------------------------------------------------------ Java
DECL = re.compile(r'\b(class|interface|enum)\s+(\w+)(?:\s*<[^>{]*>)?(?:\s+extends\s+([\w.]+)(\s*<[^{]*?>)?)?(?:\s+implements\s+([^{]+?))?\s*\{')
METODO = re.compile(r'(?m)^[ \t]*(?:@\w+(?:\([^)]*\))?\s+)*(?:(?:public|protected|private|static|final|synchronized|abstract)\s+)*([\w<>\[\], .?]+?)\s+(\w+)\s*\(([^)]*)\)\s*(?:throws\s+[\w., ]+)?\s*\{')
CAMPO = re.compile(r'(?m)^[ \t]*(?:private|protected|public)\s+(?!static\b)(?:final\s+)?([\w<>\[\], .?]+?)\s+(\w+)\s*(?:=[^;]*)?;')
CONST = re.compile(r'(?:public\s+)?static\s+final\s+String\s+(\w+)\s*=\s*"([^"]*)"')
VAR = re.compile(r'\b([A-Z][\w.]*(?:<[^;()=]*?>)?(?:\[\])?)\s+([a-z_]\w*)\s*(?=\s*[;=,):])')
RECEPTOR = re.compile(r'(?:\bget(\w+)\(\)|\b(\w+))\s*\.\s*(\w+)\s*\(')
MODIFICADORES = {'final', 'public', 'private', 'protected', 'static'}


def corpo_ate_chave(t, i):
    """Índice do '}' que fecha a '{' em t[i] (ignora chaves em strings e comentários simples)."""
    n, d, j = len(t), 0, i
    while j < n:
        c = t[j]
        if c == '"':
            j += 1
            while j < n and t[j] != '"':
                j += 2 if t[j] == '\\' else 1
        elif c == '/' and t[j:j + 2] == '//':
            j = t.find('\n', j)
            if j < 0:
                break
        elif c == '/' and t[j:j + 2] == '/*':
            j = t.find('*/', j) + 1
            if j <= 0:
                break
        elif c == '{':
            d += 1
        elif c == '}':
            d -= 1
            if d == 0:
                return j
        j += 1
    return n - 1


def divide_args(texto, genericos=False):
    """Divide `a, f(b, c), d` nos argumentos de nível zero (com genericos=True, `<...>` também aninha)."""
    out, d, atual = [], 0, ''
    for ch in texto:
        if ch in '([{' or (genericos and ch == '<'):
            d += 1
        elif ch in ')]}' or (genericos and ch == '>'):
            d -= 1
        if ch == ',' and d == 0:
            out.append(atual.strip())
            atual = ''
        else:
            atual += ch
    if atual.strip():
        out.append(atual.strip())
    return out


def parametros(texto):
    out = []
    for a in divide_args(re.sub(r'@\w+(\([^)]*\))?', '', texto), True):
        partes = [x for x in re.split(r'\s+', a.strip()) if x and x not in MODIFICADORES]
        if len(partes) >= 2:
            out.append((' '.join(partes[:-1]), partes[-1]))
    return out


def variaveis(texto):
    """{nome: tipo} das declarações do texto (campos, parâmetros, locais e for-each)."""
    return {n: t for t, n in VAR.findall(texto) if t not in ('String',) or True}


def classe_java(caminho, guardar_corpo=True):
    t = ler(caminho)
    pk = (re.search(r'^\s*package\s+([\w.]+)\s*;', t, re.M) or [0, ''])[1]
    imps = re.findall(r'^\s*import\s+([\w.*]+)\s*;', t, re.M)
    m = DECL.search(t)
    if not m:
        return None
    ext = [m.group(3).split('.')[-1]] if m.group(3) else []
    ext_args = re.findall(r'\b([A-Z]\w*)\b', m.group(4) or '')
    imp = [x.strip().split('<')[0].split('.')[-1] for x in (m.group(5) or '').split(',') if x.strip()]
    tipos = set(re.findall(r'\b([A-Z]\w+)\b', t))
    metodos = {}
    for mm in METODO.finditer(t, m.end()):
        nome = mm.group(2)
        if nome in ('if', 'for', 'while', 'switch', 'catch', 'synchronized', 'return', 'new', 'else'):
            continue
        ab = t.find('{', mm.end() - 1)
        fim = corpo_ate_chave(t, ab)
        corpo = t[ab:fim + 1]
        recs = sorted({((g1[:1].lower() + g1[1:]) if g1 else g2, g3) for g1, g2, g3 in RECEPTOR.findall(corpo)})
        metodos.setdefault(nome, []).append({'linha': t.count('\n', 0, mm.start()) + 1, 'assinatura': f'{" ".join(mm.group(1).split())} {nome}({" ".join(mm.group(3).split())})',
                                             'retorno': ' '.join(mm.group(1).split()).split()[-1] if mm.group(1).split() else '', 'params': parametros(mm.group(3)),
                                             'chamadas': sorted(set(re.findall(r'\b(\w+)\s*\(', corpo))), 'receptores': [list(x) for x in recs],
                                             'getters': sorted(set(re.findall(r'\.(get\w+Adapter)\s*\(', corpo))), 'resultados': sorted(set(re.findall(r'return\s+("[^"]*"|[\w.]+)\s*;', corpo))),
                                             **({'corpo': corpo} if guardar_corpo else {})})
    return {'fqn': f'{pk}.{m.group(2)}' if pk else m.group(2), 'nome': m.group(2), 'tipo': m.group(1), 'pacote': pk, 'extends': ext, 'ext_args': ext_args, 'implements': imp, 'imports': imps,
            'tipos': sorted(tipos), 'campos': {n: ty.strip() for ty, n in CAMPO.findall(t)}, 'constantes': dict(CONST.findall(t)), 'metodos': metodos, 'arquivo': str(caminho)}


def properties(caminho):
    """Mensagens (rótulos) de um .properties: {chave: texto}; separador `=`, `:` ou espaço; escapes \\uXXXX resolvidos."""
    out = {}
    for ln in ler(caminho).splitlines():
        ln = ln.strip()
        if not ln or ln[0] in '#!':
            continue
        m = re.match(r'([^\s=:]+)\s*[=:\s]\s*(.*)$', ln)
        if m:
            out[m.group(1)] = re.sub(r'\\u([0-9a-fA-F]{4})', lambda mm: chr(int(mm.group(1), 16)), m.group(2).strip())
    return out


# ------------------------------------------------------------------ JSP
def tipo_visual(tag):
    t = tag.lower()
    t = re.sub(r'^br', '', t)
    regras = [
        (r'inputtextarea|textarea', 'área de texto'), (r'calendar|datepicker|inputdate', 'calendário (data)'), (r'inputfile|upload', 'upload de arquivo'),
        (r'inputsecret|password', 'caixa de senha'), (r'inputtext|inputmask|inputnumber|inputhidden|input\b|spinner|suggest|selectinput', 'caixa de texto'),
        (r'selectonemenu|combo|selectonelistbox|dropdown|selectonebutton', 'combobox'), (r'selectmanycheckbox|selectmanylistbox|selectmanymenu|selectmany|shuttle', 'seleção múltipla'),
        (r'selectbooleancheckbox|checkbox', 'checkbox'), (r'selectoneradio|radio', 'radio'),
        (r'commandbutton|button|submit|imagebutton', 'botão'), (r'commandlink|outputlink|link|menuitem', 'link'),
        (r'panelgrid|gridlayout|layoutgrid', 'grade de layout'),
        (r'datatable|datagrid|datalist|table$|listagem|grid$', 'listagem (tabela)'), (r'datascroller|scroller|pagin', 'paginação'),
        (r'column$|^column|headercolumn', 'coluna da listagem'),
        (r'messages|message|errormessage', 'mensagem'), (r'outputtext|outputlabel|outputformat|outputtextbold|label|text$', 'rótulo / texto'),
        (r'graphicimage|image|img', 'imagem'), (r'tabpanel|tabbedpane|tab$|tab\b|simpletogglepanel|accordion', 'abas / painel recolhível'),
        (r'panelgrid|panelgroup|panel|form|div|fieldset|layout|subview|include|region|toolbar', 'contêiner'),
    ]
    for r, nome in regras:
        if re.search(r, t):
            return nome
    return 'outro'


def attrs(s):
    return {m.group(1): (m.group(3) if m.group(3) is not None else m.group(4)) for m in ATTR.finditer(s)}


def jsp(caminho):
    t = ler(caminho)
    taglibs = {}
    for m in re.finditer(r'<%@\s*taglib\s+(.*?)%>', t, re.S):
        a = attrs(m.group(1))
        if a.get('prefix'):
            taglibs[a['prefix']] = a.get('uri', '')
    comps, pilha = [], []
    for m in TAG.finditer(t):
        fecha, pre, nome, resto, auto = m.groups()
        if fecha:
            for k in range(len(pilha) - 1, -1, -1):
                if comps[pilha[k]]['tag'] == f'{pre}:{nome}':
                    del pilha[k:]
                    break
            continue
        a = attrs(resto)
        c = {'ordem': len(comps), 'tag': f'{pre}:{nome}', 'prefixo': pre, 'nome': nome, 'visual': tipo_visual(nome) if pre not in SEM_VISUAL else 'núcleo', 'atributos': a,
             'pai': pilha[-1] if pilha else None, 'nivel': len(pilha), 'linha': t.count('\n', 0, m.start()) + 1}
        c['id'] = a.get('id', '')
        c['valor'] = a.get('value', '')
        comps.append(c)
        if not auto:
            pilha.append(c['ordem'])
    els = [{'expressao': e.strip(), 'linha': t.count('\n', 0, m.start()) + 1} for m in EL.finditer(t) for e in [m.group(1)]]
    return {'arquivo': str(caminho), 'taglibs': taglibs, 'componentes': comps, 'expressoes': els, 'tamanho': len(t)}
