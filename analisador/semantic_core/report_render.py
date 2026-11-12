"""Desenha o modelo de relatório (report_model) em HTML com SVG, sem dependências.

O modelo é a única fonte: o HTML (humano) e o JSON (ia/report.json) mostram exatamente o mesmo conteúdo.
Blocos: text, table, bars (barras empilhadas), bands (faixas: uma unidade por linha, células por coluna), graph (kind: layered | er | flowchart; nó com inactive=true fica cinza tracejado; nó com mocked=true fica com fundo laranja claro).
"""
import html
import re
import json
import shutil
from pathlib import Path
from urllib.parse import quote

from cores import (COR_CLASSE, COR_SQL_LE, COR_SQL_GRAVA, COR_REGRA, COR_VALIDACAO, COR_DERIVACAO, COR_SUCESSO, COR_ERRO, COR_ROTEAMENTO)

PALETA = ['#0072B2', '#E69F00', '#009E73', '#CC79A7', '#56B4E9', '#D55E00', '#5E7C16', '#7f7f7f']
# Cores fixas por classe de programa em todos os relatórios (borda colorida, fundo branco); o restante usa a paleta sem essas cores.
_ALIAS = {'COORDENADORES': 'COORDENADOR', 'FUNCIONAIS': 'FUNCIONAL', 'CORPORATIVOS': 'CORPORATIVO', 'FRAMEWORK': 'INFRAESTRUTURA', 'FRAMEWORKS': 'INFRAESTRUTURA', 'NEGOCIO': 'FUNCIONAL'}
# Tipos de regra (fase 6): cores básicas bem distintas entre si.
COR_TIPO = {'consulta estática (internalizada)': COR_SQL_LE, 'funcionalidade corporativa': COR_CLASSE['CORPORATIVO'], 'validação': COR_VALIDACAO, 'tratamento de erro': COR_ERRO, 'retorno de sucesso': COR_SUCESSO,
            'consulta de dados': COR_SQL_LE, 'alteração de estado': COR_SQL_GRAVA, 'roteamento': COR_ROTEAMENTO, 'derivação': COR_DERIVACAO, **COR_REGRA}
PALETA_OUTROS = ['#7f7f7f', '#CC79A7', '#8c564b', '#bcbd22', '#e377c2', '#5E7C16', '#455A64', '#B26A00']


def _colors(names):
    """nome -> cor: classes de programa têm cor fixa; os demais grupos recebem cores da paleta restante, em ordem."""
    out, k = {}, 0
    for n in dict.fromkeys(names):
        c = COR_CLASSE.get(_ALIAS.get(str(n).upper(), str(n).upper())) or COR_TIPO.get(str(n))
        if c is None:
            c = PALETA_OUTROS[k % len(PALETA_OUTROS)]
            k += 1
        out[n] = c
    return out
CSS = """
.wire{border:1px solid var(--line);border-radius:8px;padding:10px;background:var(--card);margin:6px 0 4px}.wgrid{display:grid;gap:6px;margin:4px 0}.wn{display:flex;flex-direction:column;gap:2px;padding:5px 7px;border:1px dashed var(--line);border-radius:6px;background:var(--bg);min-width:0}.wn.wi{border:2px solid #0072B2}.wn.wo{border:2px solid #1E8E3E}.wn.wr{border-style:solid}.wl{font-weight:600;font-size:12px}.wbox{border:1px solid var(--line);border-radius:4px;padding:2px 6px;font-size:12px;color:var(--mut);background:var(--card)}.wbtn{display:inline-block;border:1px solid var(--acc);color:var(--acc);border-radius:14px;padding:2px 12px;font-weight:600;font-size:12px}.wtxt{font-size:12px}.wmeta{font:10.5px ui-monospace,Consolas,monospace;color:var(--mut);word-break:break-all}.wact{color:#EF6C00}.wsel{display:inline-block;font-size:10.5px;background:#E8EAF6;color:#1a237e;border-radius:4px;padding:1px 5px;margin-top:2px}.wbox2{border:1px solid var(--line);border-radius:6px;padding:6px;margin:4px 0}.wtt{font-weight:700;font-size:12px;margin-bottom:3px}.wlist{border:2px solid #1E8E3E;border-radius:6px;padding:6px;margin:4px 0;background:var(--bg)}.wcols{display:flex;gap:6px;flex-wrap:wrap}.wcol{display:flex;flex-direction:column;border:1px solid var(--line);border-radius:4px;padding:3px 6px;min-width:90px;max-width:230px}
pre.cod{font:12.5px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:var(--card);border:1px solid var(--line);border-left:5px solid #56B4E9;border-radius:6px;padding:10px 14px;margin:8px 0 14px;overflow-x:auto;white-space:pre;tab-size:4}
.oa{border:1px solid var(--line);border-radius:8px;padding:10px 14px;margin:8px 0 16px}.oa-h p{margin:.2em 0 .6em;color:var(--muted)}.oa-v{font-size:11px;border:1px solid var(--line);border-radius:10px;padding:0 7px;margin-left:4px;color:var(--muted)}
.oa-op{border:1px solid var(--line);border-left-width:5px;border-radius:6px;margin:6px 0;background:var(--card)}.oa-op>summary{cursor:pointer;padding:6px 10px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.oa-m{font-weight:700;font-size:12px;color:#fff;border-radius:4px;padding:2px 9px;min-width:52px;text-align:center}.oa-s{flex:1;color:var(--muted)}.oa-id{font-size:11px;color:var(--muted)}
.m-get{border-left-color:#0072B2}.m-get .oa-m{background:#0072B2}.m-post{border-left-color:#009E73}.m-post .oa-m{background:#009E73}.m-put{border-left-color:#E69F00}.m-put .oa-m{background:#E69F00}.m-delete{border-left-color:#D55E00}.m-delete .oa-m{background:#D55E00}
.oa-b{padding:4px 14px 12px}.oa-b h4,.oa>h4{margin:.9em 0 .3em;font-size:13px}.oa-t{border-collapse:collapse;width:100%;font-size:12.5px;margin:2px 0 6px}.oa-t th,.oa-t td{border:1px solid var(--line);padding:3px 7px;text-align:left;vertical-align:top}
.oa-req{color:#D55E00;margin-left:2px}.oa-r{margin:5px 0}.oa-c{font-weight:700;font-size:12px;border-radius:4px;padding:1px 7px;color:#fff;background:#666}.oa-c.c2{background:#009E73}.oa-c.c4{background:#E69F00}.oa-c.c5{background:#D55E00}
.oa-ext{font-size:11px;color:var(--muted);word-break:break-all}.oa-sc{margin:4px 0}.oa-sc>summary{cursor:pointer}
div.sql{font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:var(--card);border:1px solid var(--line);border-left:5px solid #009E73;border-radius:6px;padding:10px 14px;margin:8px 0 14px;overflow-x:auto;white-space:pre;tab-size:4}
div.sql.w{border-left-color:#CC79A7}.sk{color:var(--acc);font-weight:700}.sh{color:#D55E00}.sl{color:#117733}
tr.mk td{background:#EAF3FB}details.exp{margin:0}details.exp>summary{cursor:pointer;color:inherit;list-style:none}details.exp>summary::-webkit-details-marker{display:none}details.exp .mais{color:var(--acc);font-weight:700;margin-left:4px;padding:0 4px;border:1px solid var(--line);border-radius:4px}details.exp[open] .res{display:none}details.exp[open] .mais{font-size:0;margin:0 0 4px}details.exp[open] .mais::after{content:'recolher';font-size:11px}.expd{white-space:pre-wrap;word-break:break-word;font-size:12px;max-height:28em;overflow:auto}
:root{--bg:#fff;--fg:#1c1c1c;--mut:#666;--line:#d0d0d0;--card:#f6f7f9;--acc:#0072B2}
@media (prefers-color-scheme:dark){:root{--bg:#16181c;--fg:#e6e6e6;--mut:#9aa0a6;--line:#3a3d42;--card:#20232a;--acc:#56B4E9}}
body{font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;margin:0;background:var(--bg);color:var(--fg)}
main{max-width:1280px;margin:0 auto;padding:24px 20px 60px;box-sizing:border-box}h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 8px;border-top:1px solid var(--line);padding-top:16px}
h3{font-size:15px;margin:20px 0 6px}.sub{color:var(--mut);margin:0 0 16px}.cards{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 14px;min-width:120px}.card b{display:block;font-size:20px}.card span{color:var(--mut);font-size:12px}
.etapa{margin:22px 0 8px;padding:8px 12px;border-left:6px solid var(--c);background:var(--card);border-radius:6px}.etapa h2{margin:0;font-size:18px}.etapa p{margin:2px 0 0;color:var(--mut)}
.etapa-nums .card{border-top:3px solid var(--c)}.etapa-fase{margin:0 0 10px}
table{border-collapse:collapse;width:100%;margin:8px 0;font-size:13px}th,td{border:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}th{background:var(--card);position:sticky;top:0}
.tw{max-height:520px;overflow:auto;border:1px solid var(--line);border-radius:6px}.tw table{margin:0}
.svgw{overflow:auto;border:1px solid var(--line);border-radius:8px;background:var(--card);padding:6px;margin:8px 0}
svg text{fill:var(--fg);font:11px system-ui,sans-serif}svg .mut{fill:var(--mut)}svg .box{fill:var(--bg);stroke:var(--line)}svg .edge{fill:none;stroke:var(--mut);stroke-opacity:.55}
.legend{display:flex;flex-wrap:wrap;gap:12px;margin:4px 0;font-size:12px}.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;box-sizing:border-box}
body{display:flex;align-items:flex-start}#idx{position:sticky;top:0;height:100vh;flex:0 0 auto;width:var(--w,270px);min-width:170px;max-width:60vw;overflow:auto;background:var(--card);border-right:1px solid var(--line);padding:12px 12px 24px;font-size:13px;box-sizing:border-box}#idx h4{margin:14px 0 6px;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--mut)}#idx h4:first-child{margin-top:0}#idx a{display:block;padding:3px 6px;color:var(--acc);text-decoration:none;border-radius:4px;overflow-wrap:anywhere}#idx a:hover{background:var(--bg)}#idx a.cur{font-weight:600;background:var(--bg)}span.tag{display:inline-block;font-size:11px;border:1px solid var(--line);border-radius:10px;padding:1px 8px;color:var(--mut);margin:0 0 6px}#idx .off{display:block;padding:3px 6px;color:var(--mut)}#idx>a,#idx>.off{padding-left:12px}#idx>a.ent{padding-left:6px}#idx .sec{margin:2px 0 8px 14px;padding-left:6px;border-left:1px solid var(--line)}#idx .sec a{padding:2px 6px;font-size:12px}#idx .sec .grp{display:block;margin:8px 0 2px;padding:0 6px;font-size:12px;font-weight:600;color:var(--mut)}#idx .sec a.emgrp{margin-left:10px;padding-left:8px;border-left:1px solid var(--line);border-radius:0 4px 4px 0}#rz{flex:0 0 5px;align-self:stretch;cursor:col-resize;background:var(--line);opacity:.6}#rz:hover,#rz.on{background:var(--acc);opacity:1}#tg{position:fixed;left:6px;bottom:6px;z-index:9;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:6px;padding:3px 8px;cursor:pointer;font-size:12px}body.nonav #idx,body.nonav #rz{display:none}main{flex:1 1 0;min-width:0}@media(max-width:800px){#idx,#rz{display:none}body.shownav #idx{display:block;position:fixed;z-index:8;width:80vw}}details{margin:12px 0}summary{cursor:pointer;color:var(--acc)}pre{white-space:pre-wrap;background:var(--card);padding:10px;border-radius:6px;overflow:auto;font-size:12px}
label.tgd{display:block;margin:6px 0;font-size:13px;cursor:pointer}.hide-dn .dn{display:none}.svcomp{display:none}.hide-dn .svcomp{display:block}.hide-dn .svfull{display:none}svg .ina rect,svg .ina polygon,svg .ina circle{stroke:#999!important;stroke-dasharray:5 3;fill:var(--bg);opacity:.55}svg .ina text{fill:#8a8a8a}svg path.edge.ina{stroke:#999;stroke-dasharray:5 3;opacity:.55}.legend i.ina{background:none;border:1px dashed #999;box-sizing:border-box}
svg .cdash text{fill:#7a7a7a}svg .dashbox{fill:none;stroke:#8a8a8a;stroke-width:1;stroke-dasharray:4 3}.legend i.cdash{background:none;border:1px dashed #8a8a8a}svg .cna text{fill:#b3261e;text-decoration:line-through}svg .cna text.mut{fill:#b3261e}svg .mck rect,svg .mck polygon,svg .mck circle{fill:#fff3b0!important}svg .mck text{fill:#1c1c1c}.legend i.cna{background:none;border:1px solid #b3261e;box-sizing:border-box}.legend i.mck{background:#fff3b0;border:1px solid #999;box-sizing:border-box}code{background:var(--card);padding:0 4px;border-radius:3px}.note{color:var(--mut);font-size:12px}tr.rs td{color:#b3261e;text-decoration:line-through}
svg [data-n]{cursor:pointer}svg [data-n],svg [data-a]{transition:opacity .12s}svg.foco [data-n]:not(.on),svg.foco [data-a]:not(.on){opacity:.12}svg.foco .edge.on{stroke:var(--acc)!important;stroke-opacity:1!important;stroke-width:2.6px!important}svg.foco text.on{font-weight:700}
"""


def esc(x):
    return html.escape(str(x))


def _cut(s, n):
    s = str(s)
    return s if len(s) <= n else s[:n - 1] + '…'


def table(b):
    cols = b['columns']
    head = ''.join(f'<th>{esc(c)}</th>' for c in cols)
    ids = b.get('row_ids') or []
    marks = b.get('row_marks') or []
    dn = b.get('row_descartada') or []
    rs = b.get('row_riscada') or []
    def _cls(i):
        c = (['mk'] if i < len(marks) and marks[i] else []) + (['dn'] if i < len(dn) and dn[i] else []) + (['rs'] if i < len(rs) and rs[i] else [])
        return f' class="{" ".join(c)}">' if c else '>'
    body = ''.join((f'<tr id="{esc(ids[i])}"' if i < len(ids) and ids[i] else '<tr')
                   + _cls(i) + ''.join(f'<td>{cell(v)}</td>' for v in r) + '</tr>' for i, r in enumerate(b['rows']))
    return f'<div class="tw"><table><tr>{head}</tr>{body}</table></div>' + (f'<p class="note">{esc(b["note"])}</p>' if b.get('note') else '')


def readable(v):
    """Texto humano para qualquer valor: dict -> 'chave=valor; ...', lista -> 'a, b, c' (nunca JSON)."""
    if v is None:
        return ''
    if isinstance(v, dict) and 'detalhe' in v:
        return readable(v['detalhe'])
    if isinstance(v, dict) and 'text' in v and 'links' in v:
        return readable(v['text']) + (' — ver: ' if v['text'] else '') + ', '.join(readable(x['text']) for x in v['links'])
    if isinstance(v, dict):
        return '; '.join(f'{k}={readable(x)}' for k, x in v.items())
    if isinstance(v, (list, tuple, set)):
        return ', '.join(readable(x) for x in v)
    if isinstance(v, bool):
        return 'sim' if v else 'não'
    return str(v)


_PHASE = ['']


def href(l):
    """Endereço de um link do modelo: mesma fase = âncora na própria página; outra fase = a página dela, ao lado nas pastas de saída;
    fase só com a visão para IA (SO_IA) = None (o texto aparece sem link); link para arquivo (report_model.link_arquivo) = o caminho dele."""
    if l.get('url'):
        return l['url']
    if l['phase'] != _PHASE[0] and l['phase'] in SO_IA:
        return None
    return ('#' if l['phase'] == _PHASE[0] else f'../../{quote(l["phase"])}/human/report.html#') + str(l['anchor'])


def ancora(l):
    h = href(l)
    modal = f' data-modal="{esc(l["modal"])}"' if l.get('modal') else ''   # abre numa janela sobre o relatório (MODAL)
    return f'<a href="{esc(h)}"{modal}>{esc(l["text"])}</a>' if h else esc(l['text'])


def cell(v):
    if isinstance(v, dict) and 'detalhe' in v:   # resumo com ação «…» que expande o conteúdo completo (report_model.expandir)
        return f'<details class="exp"><summary><span class="res">{esc(v["text"])}</span><span class="mais" title="ver tudo">…</span></summary><div class="expd">{esc(v["detalhe"])}</div></details>'
    if isinstance(v, dict) and 'parts' in v:   # texto com referências cruzadas no meio (ligar): pedaços de texto e links
        return ''.join(ancora(p) if isinstance(p, dict) else esc(p) for p in v['parts'])
    if isinstance(v, dict) and 'text' in v and 'links' in v:
        return esc(readable(v['text'])) + (' — ver: ' if v['links'] and v['text'] else '') + ', '.join(ancora(l) for l in v['links'])
    return esc(readable(v))


def bars(b):
    series = b['series']  # [{label, parts:[{name,value}]}]
    names = list(dict.fromkeys(list(b.get('names') or []) + [p['name'] for s in series for p in s['parts']]))   # 'names' fixa a ordem (e a cor) quando vários gráficos mostram as mesmas categorias
    mx = max([sum(p['value'] for p in s['parts']) for s in series] + [1])
    W, lab, rowh = 620, 220, 22
    h = len(series) * rowh + 8
    out = [f'<svg width="{lab + W + 90}" height="{h}" role="img" aria-label="{esc(b.get("title", ""))}">']
    for i, s in enumerate(series):
        y = 4 + i * rowh
        out.append(f'<text x="{lab - 8}" y="{y + 13}" text-anchor="end">{esc(_cut(s["label"], 34))}</text>')
        x = lab
        for p in s['parts']:
            w = W * p['value'] / mx
            if w > 0:
                c = _colors(names)[p['name']]
                out.append(f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="16" fill="{c}"><title>{esc(s["label"])} — {esc(p["name"])}: {p["value"]}</title></rect>')
                x += w
        tot = sum(p['value'] for p in s['parts'])
        out.append(f'<text x="{x + 6:.1f}" y="{y + 13}" class="mut">{tot if not s.get("suffix") else esc(s["suffix"])}</text>')
    out.append('</svg>')
    leg = ''.join(f'<span><i style="background:{_colors(names)[n]}"></i>{esc(n)}</span>' for n in names)
    return f'<div class="svgw">{"".join(out)}</div><div class="legend">{leg}</div>'


def _layers(nodes, edges):
    ids = [n['id'] for n in nodes]
    out, inn = {i: [] for i in ids}, {i: 0 for i in ids}
    for e in edges:
        if e['from'] in out and e['to'] in out and e['from'] != e['to']:
            out[e['from']].append(e['to'])
            inn[e['to']] += 1
    depth = {}
    roots = [i for i in ids if inn[i] == 0] or ids[:1]
    stack = [(r, 0, ()) for r in roots]
    while stack:
        n, d, path = stack.pop()
        if n in path:
            continue
        if depth.get(n, -1) >= d:
            continue
        depth[n] = d
        for m in out[n]:
            stack.append((m, d + 1, path + (n,)))
    for i in ids:
        depth.setdefault(i, 0)
    return depth


def layered(b):
    nodes, edges = b['nodes'], b['edges']
    depth = _layers(nodes, edges)
    groups = list(dict.fromkeys(n.get('group', '') for n in nodes))
    byl = {}
    for n in nodes:
        byl.setdefault(depth[n['id']], []).append(n)
    nw, nh, gx, gy = 236, 24, 84, 8
    pos = {}
    for d, ns in byl.items():
        for k, n in enumerate(ns):
            pos[n['id']] = (10 + d * (nw + gx), 10 + k * (nh + gy))
    W = 20 + (max(byl) + 1) * (nw + gx)
    H = 20 + max(len(v) for v in byl.values()) * (nh + gy)
    out = [f'<svg width="{W}" height="{H}" role="img" aria-label="{esc(b.get("title", ""))}"><defs><marker id="ar" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 z" fill="#888"/></marker></defs>']
    for e in edges:
        if e['from'] in pos and e['to'] in pos:
            x1, y1 = pos[e['from']][0] + nw, pos[e['from']][1] + nh / 2
            x2, y2 = pos[e['to']][0], pos[e['to']][1] + nh / 2
            dx = max(30, abs(x2 - x1) / 2)
            out.append(f'<path{_da(e)} class="edge{" ina" if e.get("inactive") else ""}" d="M{x1},{y1} C{x1 + dx},{y1} {x2 - dx},{y2} {x2},{y2}" marker-end="url(#ar)"><title>{esc(e.get("label", ""))}</title></path>')
            if b.get('edge_labels') and e.get('label'):
                out.append(f'<text{_da(e)} class="mut" x="{x1 + (x2 - x1) * 0.12 + 4:.1f}" y="{y1 + (y2 - y1) * 0.12 - 3:.1f}">{esc(_cut(e["label"], 30))}</text>')
    for n in nodes:
        x, y = pos[n['id']]
        c = _colors(groups)[n.get('group', '')]
        h_ = href(n['link']) if n.get('link') else None   # nó com link do modelo ({'text', 'phase', 'anchor'}): a caixa abre o destino
        out.append((f'<a href="{esc(h_)}">' if h_ else '') + f'<g{_cls(n)}{_dn(n["id"])}><rect class="box" x="{x}" y="{y}" width="{nw}" height="{nh}" rx="5" style="stroke:{c};stroke-width:1.6"/>'
                   f'<text x="{x + 7}" y="{y + 16}"{" style=\"text-decoration:underline\"" if h_ else ""}>{esc(_cut(n["label"], 28))}</text><title>{esc(n.get("detail") or n["label"])}</title></g>' + ('</a>' if h_ else ''))
    out.append('</svg>')
    return f'<div class="svgw">{"".join(out)}</div>' + _legend(groups, b)


def _cls(n):
    return ' class="ina"' if n.get('inactive') else ' class="mck"' if n.get('mocked') else ''


def _dn(i):
    """Marca de nó para o destaque das ligações: ao passar o mouse (ou tocar) num nó, o script DESTAQUE acende as arestas com a mesma ponta e os nós da outra ponta."""
    return f' data-n="{esc(i)}"'


def _da(e, para=None):
    """Marca de aresta (e do seu rótulo) para o destaque das ligações: as duas pontas, pelo id do nó."""
    return f' data-a="{esc(e["from"])}" data-b="{esc(e["to"] if para is None else para)}"'


def _legend(groups, b):
    leg = ''.join(f'<span><i style="background:{_colors(groups)[g]}"></i>{esc(g)}</span>' for g in groups if g)
    if b.get('inactive_label') and (any(n.get('inactive') for n in b['nodes']) or any(e.get('inactive') for e in b.get('edges', []))):
        leg += f'<span><i class="ina"></i>{esc(b["inactive_label"])}</span>'
    if b.get('dashed_label') and any(c.get('dashed') for n in b['nodes'] for c in n.get('columns') or []):
        leg += f'<span><i class="cdash"></i>{esc(b["dashed_label"])}</span>'
    if b.get('column_label') and any(c.get('inactive') for n in b['nodes'] for c in n.get('columns') or []):
        leg += f'<span><i class="cna"></i>{esc(b["column_label"])}</span>'
    if b.get('mocked_label') and any(n.get('mocked') for n in b['nodes']):
        leg += f'<span><i class="mck"></i>{esc(b["mocked_label"])}</span>'
    return f'<div class="legend">{leg}</div>' if leg else ''


def _wrap(text, width=30, maxlines=6):
    parts = str(text).split('\n')
    if len(parts) > 1:
        lines = [x for part in parts for x in _wrap(part, width, 99)]
        return lines if len(lines) <= maxlines else lines[:maxlines - 1] + [lines[maxlines - 1][:width - 1] + '…']
    words, lines, cur = str(text).split(), [], ''
    for w in words:
        while len(w) > width:
            if cur:
                lines.append(cur)
                cur = ''
            lines.append(w[:width])
            w = w[width:]
        if len(cur) + len(w) + (1 if cur else 0) > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + ' ' + w).strip()
    if cur:
        lines.append(cur)
    if len(lines) > maxlines:
        lines = lines[:maxlines - 1] + [lines[maxlines - 1][:width - 1] + '…']
    return lines or ['']


def flowchart(b):
    """Fluxograma de cima para baixo: losango = decisão, retângulo = consequência, pílula = início/fim, círculo = junção."""
    nodes, edges = b['nodes'], b['edges']
    depth = _layers(nodes, edges)
    groups = list(dict.fromkeys(n.get('group', '') for n in nodes if n.get('group')))
    size = {}
    for n in nodes:
        sh = n.get('shape', 'action')
        lines = _wrap(n['label'], {'action': 44, 'decision': 34}.get(sh, 40), {'action': 400, 'decision': 400}.get(sh, 2))
        n['_lines'] = lines
        pill = max(120, 7 * max(len(x) for x in lines) + 24)
        size[n['id']] = {'start': (pill, 26), 'end': (pill, 26), 'join': (12, 12), 'decision': (max(330, 7 * max(len(x) for x in lines) + 90), 34 + 13 * len(lines))}.get(sh, (max(250, 7 * max(len(x) for x in lines) + 20), 12 + 13 * len(lines)))
    camadas = {}
    for n in nodes:
        camadas.setdefault(depth[n['id']], []).append(n)
    parents = {}
    for e in edges:
        parents.setdefault(e['to'], []).append(e['from'])
    xc, gap = {}, 24
    widths, layers = {}, {}
    limite = b.get('largura_max')   # opcional: camada mais larga que isso quebra em linhas (nada fica fora da tela)
    for d in sorted(camadas):
        ns = camadas[d]
        if d > 0:
            ns.sort(key=lambda n: sum(xc.get(p, 0) for p in parents.get(n['id'], [])) / max(1, len(parents.get(n['id'], []))))
        linhas, atual, larg = [], [], 0
        for n in ns:
            w = size[n['id']][0]
            if limite and atual and larg + gap + w > limite:
                linhas.append(atual)
                atual, larg = [], 0
            larg += (gap if atual else 0) + w
            atual.append(n)
        linhas.append(atual)
        for k, linha in enumerate(linhas):
            layers[(d, k)] = linha
            widths[(d, k)] = sum(size[n['id']][0] for n in linha) + gap * (len(linha) - 1)
            x = 0
            for n in linha:
                xc[n['id']] = x + size[n['id']][0] / 2
                x += size[n['id']][0] + gap
    W = max(widths.values()) + 40
    y, yy = 12, {}
    for d in sorted(layers):
        for n in layers[d]:
            xc[n['id']] += 20 + (max(widths.values()) - widths[d]) / 2
        h = max(size[n['id']][1] for n in layers[d])
        for n in layers[d]:
            yy[n['id']] = y + (h - size[n['id']][1]) / 2
        y += h + 46
    H = y
    out = [f'<svg width="{W:.0f}" height="{H:.0f}" role="img" aria-label="{esc(b.get("title", ""))}"><defs><marker id="ar" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 z" fill="#888"/></marker></defs>']
    for e in edges:
        if e['from'] in xc and e['to'] in xc and e['from'] != e['to']:
            x1, y1 = xc[e['from']], yy[e['from']] + size[e['from']][1]
            x2, y2 = xc[e['to']], yy[e['to']]
            dy = max(18, abs(y2 - y1) / 2)
            out.append(f'<path{_da(e)} class="edge" d="M{x1:.1f},{y1:.1f} C{x1:.1f},{y1 + dy:.1f} {x2:.1f},{y2 - dy:.1f} {x2:.1f},{y2:.1f}" marker-end="url(#ar)"/>')
            if e.get('label'):
                out.append(f'<text{_da(e)} class="mut" x="{(x1 * 0.7 + x2 * 0.3) + 4:.1f}" y="{y1 + 13:.1f}">{esc(_cut(e["label"], 22))}</text>')
    for n in nodes:
        w, h = size[n['id']]
        x, y0 = xc[n['id']] - w / 2, yy[n['id']]
        c = _colors(groups)[n['group']] if n.get('group') in groups else '#888'
        sh = n.get('shape', 'action')
        fundo = f';fill:{c};fill-opacity:.22' if n.get('group') in groups else ''
        if sh == 'decision':
            k = 18
            shp = f'<polygon points="{x + k:.1f},{y0:.1f} {x + w - k:.1f},{y0:.1f} {x + w:.1f},{y0 + h / 2:.1f} {x + w - k:.1f},{y0 + h:.1f} {x + k:.1f},{y0 + h:.1f} {x:.1f},{y0 + h / 2:.1f}" class="box" style="stroke:{c};stroke-width:1.6{fundo}"/>'
        elif sh == 'join':
            shp = f'<circle cx="{x + 6:.1f}" cy="{y0 + 6:.1f}" r="5" fill="{c}" opacity=".5"/>'
        else:
            shp = f'<rect class="box" x="{x:.1f}" y="{y0:.1f}" width="{w}" height="{h}" rx="{13 if sh in ("start", "end") else 5}" style="stroke:{c};stroke-width:1.6{fundo}"/>'
        tx = ''
        if sh != 'join':
            top = y0 + (h - 13 * len(n['_lines'])) / 2 + 10
            anchor = 'start' if sh == 'action' else 'middle'
            px = x + 7 if sh == 'action' else x + w / 2
            tx = ''.join(f'<text text-anchor="{anchor}" x="{px:.1f}" y="{top + 13 * i:.1f}">{esc(l)}</text>' for i, l in enumerate(n['_lines']))
        out.append(f'<g{_cls(n)}{_dn(n["id"])}>{shp}{tx}<title>{esc(n.get("detail") or n["label"])}</title></g>')
    out.append('</svg>')
    return f'<div class="svgw">{"".join(out)}</div>' + _legend(groups, b)


def er_io(b):
    """Diagrama de entrada e saída: copybooks de entrada (side='left') à esquerda do programa, o programa no meio e os de saída (side='right') à direita; seta da entrada para o
    programa e do programa para a saída. Campo 'dashed' = tracejado."""
    ents = [n for n in b['nodes'] if n.get('columns') is not None]
    prog = [n for n in b['nodes'] if n.get('columns') is None]
    left = [n for n in ents if n.get('side') != 'right']
    right = [n for n in ents if n.get('side') == 'right']
    bw, rowh, gap, pw = 270, 14, 22, 170
    groups = list(dict.fromkeys(n.get('group', '') for n in b['nodes'] if n.get('group')))
    color = lambda n: _colors(groups)[n['group']] if n.get('group') in groups else PALETA[0]
    hh = lambda n: 24 + rowh * len(n['columns']) + 6

    def coluna(lst, x):
        y, out = 10, {}
        for n in lst:
            out[n['id']] = (x, y, bw, hh(n))
            y += hh(n) + gap
        return out, y
    xl, xp = 10, 10 + bw + 90
    xr = xp + pw + 90
    pl, yl = coluna(left, xl)
    pr, yr = coluna(right, xr)
    H = max(yl, yr, 60)
    pos = {**pl, **pr}
    for k, n in enumerate(prog):
        pos[n['id']] = (xp, max(10, H / 2 - 20 + k * 50), pw, 40)
    W = xr + bw + 10
    out = [f'<svg width="{W}" height="{H + 10}" role="img" aria-label="{esc(b.get("title", ""))}"><defs><marker id="ar" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 z" fill="#888"/></marker></defs>']
    for e in b['edges']:
        if e['from'] in pos and e['to'] in pos:
            a, c = pos[e['from']], pos[e['to']]
            if a[0] < c[0]:
                x1, x2 = a[0] + a[2], c[0]
            else:
                x1, x2 = a[0], c[0] + c[2]
            y1, y2 = a[1] + a[3] / 2, c[1] + c[3] / 2
            dx = (x2 - x1) / 2
            out.append(f'<path{_da(e)} class="edge" d="M{x1},{y1} C{x1 + dx},{y1} {x2 - dx},{y2} {x2},{y2}" marker-end="url(#ar)"><title>{esc(e.get("label", ""))}</title></path>')
    for n in prog:
        x, y, w, h = pos[n['id']]
        out.append(f'<g{_cls(n)}{_dn(n["id"])}><rect class="box" x="{x}" y="{y}" width="{w}" height="{h}" rx="6" style="stroke:{color(n)};stroke-width:2"/><text x="{x + w / 2}" y="{y + 24}" text-anchor="middle" style="font-weight:600">{esc(_cut(n["label"], 22))}</text><title>{esc(n.get("detail") or n["label"])}</title></g>')
    for n in ents:
        x, y, w, h = pos[n['id']]
        out.append(f'<g{_cls(n)}{_dn(n["id"])}><rect class="box" x="{x}" y="{y}" width="{w}" height="{h}" rx="6" style="stroke:{color(n)};stroke-width:1.6"/>'
                   f'<rect x="{x}" y="{y}" width="{w}" height="20" rx="6" fill="{color(n)}" opacity=".18"/><text x="{x + 8}" y="{y + 14}" style="font-weight:600">{esc(_cut(n["label"], 40))}</text><title>{esc(n.get("detail") or n["label"])}</title>')
        for i, c in enumerate(n['columns']):
            yy = y + 34 + i * rowh
            if c.get('dashed'):
                out.append(f'<rect class="dashbox" x="{x + 3}" y="{yy - 12}" width="{w - 6}" height="{rowh}" rx="3"/>')
            gcl = ' class="cdash"' if c.get('dashed') else ''
            out.append(f'<g{gcl}><text x="{x + 8}" y="{yy}">{esc(_cut(c["name"], 30))}</text><text class="mut" x="{x + w - 8}" y="{yy}" text-anchor="end">{esc(_cut(c.get("type", ""), 16))}</text></g>')
        out.append('</g>')
    out.append('</svg>')
    return f'<div class="svgw">{"".join(out)}</div>' + _legend(groups, b)


def er(b):
    if any(n.get('side') for n in b['nodes']):
        return er_io(b)
    ents = [n for n in b['nodes'] if n.get('columns') is not None]
    plain = [n for n in b['nodes'] if n.get('columns') is None]
    bw, per_row, rowh, cap = 250, b.get('per_row', 3), 14, b.get('cap', 16)
    px = 10
    ex0 = 190 if plain else 10
    groups = list(dict.fromkeys(n.get('group', '') for n in b['nodes'] if n.get('group')))
    color = lambda n: _colors(groups)[n['group']] if n.get('group') in groups else PALETA[0]
    pos = {}
    for k, n in enumerate(plain):
        pos[n['id']] = (px, 10 + k * 30, 160, 24)
    ey = 10
    rowmax = 0
    out = []
    agrup = bool(b.get('agregados'))   # cada grupo (agregado) vai dentro de uma borda tracejada com o seu nome
    if agrup:
        cats = list(dict.fromkeys(n.get('categoria', '') for n in ents))
        ents.sort(key=lambda n: (cats.index(n.get('categoria', '')), groups.index(n['group']) if n.get('group') in groups else len(groups)))
        tam = {g: sum(1 for n in ents if n.get('group') == g) for g in groups}
        ey += 24
    col, ant, cant = 0, None, None
    for k, n in enumerate(ents):
        if agrup:
            if len(cats) > 1 and n.get('categoria', '') != cant:   # nova caixa de categoria: nova linha e espaço para o título
                if k:
                    col = 0
                    ey += rowmax + 90
                    rowmax = 0
                else:
                    ey += 30
                cant, ant = n.get('categoria', ''), None
            if n.get('group') != ant and col and tam.get(n.get('group'), 1) > per_row - col:
                col = 0
                ey += rowmax + 54
                rowmax = 0
            ant = n.get('group')
        elif col == per_row:
            col = 0
        if col == per_row or (not agrup and col == 0 and k):
            col = 0
            ey += rowmax + (54 if agrup else 30)
            rowmax = 0
        cols = n['columns']
        hh = 24 + rowh * (min(len(cols), cap) + (1 if len(cols) > cap else 0)) + 6
        pos[n['id']] = (ex0 + col * (bw + 60), ey, bw, hh)
        rowmax = max(rowmax, hh)
        col += 1
    W = ex0 + per_row * (bw + 60) + 10
    H = max(ey + rowmax + 30, 20 + len(plain) * 30)
    out.append(f'<svg width="{W}" height="{H}" role="img" aria-label="{esc(b.get("title", ""))}"><defs><marker id="ar" markerWidth="11" markerHeight="11" refX="10" refY="5.5" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L11,5.5 L0,11 z" fill="#555"/></marker></defs>')
    rotulos = []
    if agrup and len(cats) > 1:
        for ci, cname in enumerate(cats):
            ps = [pos[n['id']] for n in ents if n.get('categoria', '') == cname]
            if not ps:
                continue
            gx1, gy1 = min(q[0] for q in ps) - 22, min(q[1] for q in ps) - 52
            gx2, gy2 = max(q[0] + q[2] for q in ps) + 22, max(q[1] + q[3] for q in ps) + 22
            fundo = ('#eef4fb', '#2f6db5') if ci == 0 else ('#fbf3ea', '#c9792a')
            out.append(f'<g><rect x="{gx1}" y="{gy1}" width="{gx2 - gx1}" height="{gy2 - gy1}" rx="14" fill="{fundo[0]}" fill-opacity=".55" stroke="{fundo[1]}" stroke-width="2.4"/>'
                       f'<text x="{gx1 + 14}" y="{gy1 + 20}" style="font-weight:700;font-size:14px;fill:{fundo[1]}">{esc(cname)}</text></g>')
    if agrup:
        for g in groups:
            ps = [pos[n['id']] for n in ents if n.get('group') == g]
            if not ps:
                continue
            gx1, gy1 = min(q[0] for q in ps) - 10, min(q[1] for q in ps) - 22
            gx2, gy2 = max(q[0] + q[2] for q in ps) + 10, max(q[1] + q[3] for q in ps) + 10
            out.append(f'<g><rect x="{gx1}" y="{gy1}" width="{gx2 - gx1}" height="{gy2 - gy1}" rx="10" fill="none" stroke="{_colors(groups)[g]}" stroke-width="1.6" stroke-dasharray="7 4"/>'
                       f'<text x="{gx1 + 10}" y="{gy1 + 15}" style="font-weight:600;font-size:12px">Agregado: {esc(_cut(g, 40))}</text></g>')
    for e in b['edges']:
        if e['from'] in pos and e['to'] in pos:
            a, c = pos[e['from']], pos[e['to']]
            x1, y1 = a[0] + a[2] / 2, a[1] + a[3] / 2
            x2, y2 = c[0] + c[2] / 2, c[1] + c[3] / 2
            if b.get('setas'):   # seta da borda de uma caixa à borda da outra, com o rótulo da associação no meio
                def borda(bx, cx, cy, tx, ty):
                    dx, dy = tx - cx, ty - cy
                    t = min((bx[2] / 2) / abs(dx) if dx else 1e9, (bx[3] / 2) / abs(dy) if dy else 1e9)
                    return cx + dx * t, cy + dy * t
                bx1, by1 = borda(a, x1, y1, x2, y2)
                bx2, by2 = borda(c, x2, y2, x1, y1)
                out.append(f'<line{_da(e)} class="edge" x1="{bx1:.1f}" y1="{by1:.1f}" x2="{bx2:.1f}" y2="{by2:.1f}" marker-end="url(#ar)"><title>{esc(e.get("label", ""))}</title></line>')
                if e.get('label'):
                    rotulos.append(f'<text{_da(e)} class="mut" x="{bx1 + (bx2 - bx1) * 0.22 + 4:.1f}" y="{by1 + (by2 - by1) * 0.22 - 4:.1f}" style="paint-order:stroke;stroke:var(--bg,#fff);stroke-width:3px">{esc(_cut(e["label"], 44))}</text>')
            else:
                out.append(f'<line{_da(e)} class="edge" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"><title>{esc(e.get("label", ""))}</title></line>')
    for n in plain:
        x, y, w, h = pos[n['id']]
        h_ = href(n['link']) if n.get('link') else None   # nó com link do modelo ({'text', 'phase', 'anchor'}): a caixa abre o destino
        out.append((f'<a href="{esc(h_)}">' if h_ else '') + f'<g{_cls(n)}{_dn(n["id"])}><rect class="box" x="{x}" y="{y}" width="{w}" height="{h}" rx="5" style="stroke:{color(n)};stroke-width:1.6"/><text x="{x + 7}" y="{y + 16}"{" style=\"text-decoration:underline\"" if h_ else ""}>{esc(_cut(n["label"], 24))}</text><title>{esc(n.get("detail") or n["label"])}</title></g>' + ('</a>' if h_ else ''))
    for n in ents:
        x, y, w, h = pos[n['id']]
        h_ = href(n['link']) if n.get('link') else None
        out.append((f'<a href="{esc(h_)}">' if h_ else '') + f'<g{_cls(n)}{_dn(n["id"])}><rect class="box" x="{x}" y="{y}" width="{w}" height="{h}" rx="6" style="stroke:{color(n)};stroke-width:1.6"/>'
                   f'<rect x="{x}" y="{y}" width="{w}" height="20" rx="6" fill="{color(n)}" opacity=".18"/><text x="{x + 8}" y="{y + 14}" style="font-weight:600{";text-decoration:underline" if h_ else ""}">{esc(_cut(("«" + n["estereotipo"] + "» " if n.get("estereotipo") else "") + n["label"], 44))}</text>')
        for i, c in enumerate(n['columns'][:cap]):
            key = c.get('key')
            ci = ' class="cna"' if c.get('inactive') else (' class="cdash"' if c.get('dashed') else '')
            if c.get('dashed'):
                out.append(f'<rect class="dashbox" x="{x + 3}" y="{y + 34 + i * rowh - 12}" width="{w - 6}" height="{rowh}" rx="3"/>')
            out.append(f'<g{ci}><text x="{x + 8}" y="{y + 34 + i * rowh}">{"🔑 " if key else ""}{"✕ " if c.get("inactive") else ""}{esc(_cut(c["name"], 26))}</text>'
                       f'<text class="mut" x="{x + w - 8}" y="{y + 34 + i * rowh}" text-anchor="end">{esc(_cut(c.get("type", ""), 16))}</text></g>')
        if len(n['columns']) > cap:
            out.append(f'<text class="mut" x="{x + 8}" y="{y + 34 + cap * rowh}">… +{len(n["columns"]) - cap} colunas</text>')
        out.append('</g>' + ('</a>' if h_ else ''))
    out.extend(rotulos)
    out.append('</svg>')
    return f'<div class="svgw">{"".join(out)}</div>' + _legend(groups, b)


def _quebra(t, larg):
    import textwrap
    return textwrap.wrap(str(t), max(8, int(larg / 6.8))) if t else []


def bands(b):
    """Diagrama em faixas: cada linha do bloco é uma unidade (rótulo + células por coluna, em ordem de execução da esquerda para a direita).
    b = {'columns':[{'name','width','color'}], 'rows':[{'cells':[[linhas de texto]...]}], 'arrows': n colunas ligadas por seta}."""
    cols = b['columns']
    x0, gap, y = 8, 8, 8
    xs, x = [], x0
    for c in cols:
        xs.append(x)
        x += c['width'] + gap
    o = [f'<svg viewBox="0 0 {x:.0f} {{H}}" role="img" aria-label="{esc(b.get("title", ""))}" style="width:100%;height:auto;font:11px system-ui,sans-serif">',
         '<defs><marker id="seta" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#888"/></marker></defs>']
    for c, xx in zip(cols, xs):
        o.append(f'<text x="{xx + c["width"] / 2:.0f}" y="{y + 10}" text-anchor="middle" font-weight="600">{esc(c["name"])}</text>')
    y += 20
    for r in b['rows']:
        linhas = [[l for parte in cel for l in _quebra(parte, c['width'] - 12)] for cel, c in zip(r['cells'], cols)]
        h = max(34, 14 * max(len(ls) for ls in linhas) + 12)
        for k, c in enumerate(cols):
            ls = linhas[k]
            if k == 0:
                o.append(f'<rect x="{xs[k]}" y="{y}" width="{c["width"]}" height="{h}" rx="5" fill="var(--card)" stroke="var(--fg)"/>')
            elif ls:
                o.append(f'<rect x="{xs[k]}" y="{y}" width="{c["width"]}" height="{h}" rx="5" fill="{c["color"]}" fill-opacity="0.22" stroke="{c["color"]}"/>')
            else:
                o.append(f'<rect x="{xs[k]}" y="{y}" width="{c["width"]}" height="{h}" rx="5" fill="none" stroke="var(--line)" stroke-dasharray="3 3"/>')
            for j, t in enumerate(ls):
                fw = ' font-weight="600"' if k == 0 and j == 0 else ''
                o.append(f'<text x="{xs[k] + 6}" y="{y + 15 + 14 * j}"{fw}>{esc(t)}</text>')
            if not ls and k:
                o.append(f'<text x="{xs[k] + c["width"] / 2:.0f}" y="{y + h / 2 + 4:.0f}" text-anchor="middle" class="mut">—</text>')
        for k in range(0, min(b.get('arrows', 0), len(cols) - 1)):
            o.append(f'<line x1="{xs[k] + cols[k]["width"]}" y1="{y + h / 2:.0f}" x2="{xs[k + 1]}" y2="{y + h / 2:.0f}" stroke="#888" stroke-width="1.4" marker-end="url(#seta)"/>')
        y += h + 8
    o.append('</svg>')
    return f'<div class="svgw">{"".join(o).replace("{H}", f"{y:.0f}")}</div>' + (f'<p class="note">{esc(b["note"])}</p>' if b.get('note') else '')


def _colunas_svg(b, nodes, edges, mid='ar'):
    """Diagrama em colunas (graph kind 'colunas'): cada nó tem 'col' (0..n-1); b['columns'] = [{'name','color'}] dá o título e a cor fixa da borda de cada coluna;
    as arestas ligam colunas vizinhas. A ordem dos nós em cada coluna é a ordem da lista (o script já a deixa na ordem que menos cruza as ligações)."""
    cols = b['columns']
    nw, nh, gx, gy, top = b.get('nw', 210), (46 if any(n.get('sub2') for n in nodes) else 34), 90, 8, 26
    cl, cs = int(nw / 6.6), int(nw / 6.1)
    por = [[n for n in nodes if n.get('col') == k] for k in range(len(cols))]
    H = top + 10 + max([len(v) for v in por] + [1]) * (nh + gy)
    W = 20 + len(cols) * nw + (len(cols) - 1) * gx
    pos = {}
    for k, ns in enumerate(por):
        for i, n in enumerate(ns):
            pos[n['id']] = (10 + k * (nw + gx), top + (i + 0.5) * (H - top - 10) / len(ns) - nh / 2)
    o = [f'<svg width="{W}" height="{H}" role="img" aria-label="{esc(b.get("title", ""))}"><defs><marker id="{mid}" markerWidth="11" markerHeight="11" refX="9" refY="4.5" markerUnits="userSpaceOnUse" orient="auto"><path d="M0,0 L10,4.5 L0,9 z" fill="#555"/></marker></defs>']
    for k, c in enumerate(cols):
        o.append(f'<text x="{10 + k * (nw + gx) + nw / 2:.0f}" y="16" text-anchor="middle" font-weight="600" style="fill:{c["color"]}">{esc(c["name"])}</text>')
    for e in b['edges']:
        if e['from'] in pos and e['to'] in pos:
            x1, y1 = pos[e['from']][0] + nw, pos[e['from']][1] + nh / 2
            x2, y2 = pos[e['to']][0], pos[e['to']][1] + nh / 2
            dx = (x2 - x1) / 2
            nd = ' dn' if any(n.get('inactive') for n in nodes if n['id'] in (e['from'], e['to'])) else ''
            tr = ';stroke-dasharray:6 4' if e.get('tracejado') or any(n.get('tracejado') for n in nodes if n['id'] in (e['from'], e['to'])) else ''   # ligação com algo que não existe
            o.append(f'<path{_da(e)} class="edge{" ina" if e.get("guarda") else ""}{nd}" d="M{x1:.1f},{y1:.1f} C{x1 + dx:.1f},{y1:.1f} {x2 - dx:.1f},{y2:.1f} {x2:.1f},{y2:.1f}" style="stroke-width:1.5;stroke-opacity:.8{tr}" marker-end="url(#{mid})"/>')
    for n in nodes:
        x, y = pos[n['id']]
        c = n.get('cor') or cols[n['col']]['color']
        sub = f'<text class="mut" x="{x + 7:.0f}" y="{y + 28:.0f}">{esc(_cut(n["sub"], cs))}</text>' if n.get('sub') else ''
        sub += f'<text class="mut" x="{x + 7:.0f}" y="{y + 41:.0f}" font-style="italic">{esc(_cut(n["sub2"], cs))}</text>' if n.get('sub2') else ''
        gcls = ' class="ina dn"' if n.get('inactive') else ''
        tr = ';stroke-dasharray:6 4' if n.get('tracejado') else ''   # nó tracejado: o que não existe (por exemplo, sem fonte)
        h_ = href(n['link']) if n.get('link') else None   # nó com link do modelo ({'text', 'phase', 'anchor'}): a caixa abre o destino
        o.append((f'<a href="{esc(h_)}">' if h_ else '') + f'<g{gcls}{_dn(n["id"])}><rect class="box" x="{x:.0f}" y="{y:.0f}" width="{nw}" height="{nh}" rx="5" style="stroke:{c};stroke-width:2{tr}"/>'
                 f'<text x="{x + 7:.0f}" y="{y + (14 if sub else 21):.0f}" font-weight="600"{" style=\"text-decoration:underline\"" if h_ else ""}>{esc(_cut(n["label"], cl))}</text>{sub}<title>{esc(n.get("detail") or n["label"])}</title></g>' + ('</a>' if h_ else ''))
    o.append('</svg>')
    return f'<div class="svgw">{"".join(o)}</div>'


def _legenda_colunas(b):
    """Legenda de cores do diagrama em colunas (b['legenda'] = [{'texto','cor'} | {'texto','inativo':True}]); a entrada de inativo só aparece se há nó em cinza. Quadrado com a cor da borda do nó."""
    itens = []
    for x in b.get('legenda') or []:
        if x.get('inativo'):
            if any(n.get('inactive') for n in b['nodes']):
                itens.append(f'<span><i class="ina"></i>{esc(x["texto"])}</span>')
        else:
            itens.append(f'<span><i style="background:none;border:2px {"dashed" if x.get("tracejado") else "solid"} {x["cor"]}"></i>{esc(x["texto"])}</span>')
    return f'<div class="legend">{"".join(itens)}</div>' if itens else ''


def colunas(b):
    """Diagrama em colunas com checkbox "Mostrar descartados": são desenhados dois diagramas, o completo e o refeito só com os nós ativos (ordem e posições recalculadas), e o checkbox alterna entre eles."""
    nodes, edges = b['nodes'], b['edges']
    if not any(n.get('inactive') for n in nodes):
        return _legenda_colunas(b) + _colunas_svg(b, nodes, edges)
    ativos = [n for n in nodes if not n.get('inactive')]
    ids = {n['id'] for n in ativos}
    rot = b.get('toggle_label') or 'Mostrar descartados (decisões, regras e linhas da tabela em cinza)'
    tg = '' if b.get('sem_toggle') else ('<label class="tgd"><input type="checkbox" checked onchange="this.closest(\'.secb\').classList.toggle(\'hide-dn\',!this.checked)"> ' + esc(rot) + '</label>')
    return (_legenda_colunas(b) + tg + '<div class="svfull">' + _colunas_svg(b, nodes, edges) + '</div><div class="svcomp">'
            + _colunas_svg(b, ativos, [e for e in edges if e['from'] in ids and e['to'] in ids], 'ar2') + '</div>')


def contextos(b):
    """Diagrama de contextos (graph kind 'contextos'): cada nó é uma caixa de contexto (title, sub, cor) com os seus componentes por dentro (n['componentes'] = [{'label','sub','cor'}]).
    Colunas como no diagrama em colunas (n['col'], b['columns']); as arestas ligam as caixas dos contextos e levam o rótulo (por exemplo, o protocolo)."""
    cols, nodes = b['columns'], b['nodes']
    nw, gx, gy, top, hh, ch = b.get('nw', 250), b.get('gx', 120), 16, 28, 40, 24   # gx: espaço entre as colunas (diagrama sem setas pode ser mais junto)
    if b.get('fronteiras'):
        top = 52   # faixa para o rótulo da fronteira tracejada
    rl = 23   # altura (com o espaço) de cada caixa de regra de negócio dentro do componente (m['regras'])
    chm = lambda m: ch + rl * len(m.get('regras') or []) + (2 if m.get('regras') else 0)
    alt = lambda n: hh + (sum(chm(m) + 4 for m in n.get('componentes') or []) or ch + 4) + 8
    por = [[n for n in nodes if n.get('col') == k] for k in range(len(cols))]
    H = top + 10 + max([sum(alt(n) + gy for n in ns) for ns in por] + [1])
    W = 20 + len(cols) * nw + (len(cols) - 1) * gx
    pos = {}
    for k, ns in enumerate(por):
        y = top
        for n in ns:
            pos[n['id']] = (10 + k * (nw + gx), y, alt(n))
            y += alt(n) + gy
    cl = int((nw - 16) / 6.2)
    o = [f'<svg width="{W}" height="{H}" role="img" aria-label="{esc(b.get("title", ""))}"><defs><marker id="arx" markerWidth="11" markerHeight="11" refX="9" refY="4.5" markerUnits="userSpaceOnUse" orient="auto"><path d="M0,0 L10,4.5 L0,9 z" fill="#555"/></marker></defs>']
    for k, c in enumerate(cols):
        o.append(f'<text x="{10 + k * (nw + gx) + nw / 2:.0f}" y="16" text-anchor="middle" font-weight="600" style="fill:{c["color"]}">{esc(c["name"])}</text>')
    for f in b.get('fronteiras') or []:
        ps = [pos[i] for i in f['nodes'] if i in pos]
        if not ps:
            continue
        x0, x1 = min(p[0] for p in ps) - 12, max(p[0] for p in ps) + nw + 12
        y0, y1 = min(p[1] for p in ps) - 26, max(p[1] + p[2] for p in ps) + 12
        o.append(f'<rect x="{x0:.0f}" y="{y0:.0f}" width="{x1 - x0:.0f}" height="{y1 - y0:.0f}" rx="12" fill="none" stroke="#555" stroke-width="1.8" stroke-dasharray="9 6"/>'
                 f'<text x="{x0 + 12:.0f}" y="{y0 + 17:.0f}" font-weight="700" style="fill:#555">{esc(f.get("label", ""))}</text>')
    cn = {n['id']: n.get('col', 0) for n in nodes}
    for e in b['edges']:
        if e['from'] in pos and e['to'] in pos:
            a, c = pos[e['from']], pos[e['to']]
            ca, cb = cn[e['from']], cn[e['to']]
            if cb > ca:
                x1, x2 = a[0] + nw, c[0]
            elif cb < ca:
                x1, x2 = a[0], c[0] + nw
            else:
                x1, x2 = a[0] + nw, c[0] + nw
            y1, y2 = a[1] + a[2] / 2, c[1] + c[2] / 2
            dx = (x2 - x1) / 2 if cb != ca else 60
            o.append(f'<path{_da(e)} class="edge" d="M{x1:.1f},{y1:.1f} C{x1 + dx:.1f},{y1:.1f} {x2 - dx:.1f},{y2:.1f} {x2:.1f},{y2:.1f}" style="stroke-width:1.5;stroke-opacity:.8" marker-end="url(#arx)"><title>{esc(e.get("label", ""))}</title></path>')
            if e.get('label'):
                o.append(f'<text{_da(e)} class="mut" x="{(x1 + x2) / 2:.0f}" y="{(y1 + y2) / 2 - 4:.0f}" text-anchor="middle" style="paint-order:stroke;stroke:var(--bg,#fff);stroke-width:3px">{esc(_cut(e["label"], 14))}</text>')
    for n in nodes:
        x, y, h = pos[n['id']]
        c = n.get('cor') or cols[n['col']]['color']
        hn = href(n['link']) if n.get('link') else None   # contexto com link do modelo ({'text', 'phase', 'anchor'}): o título da caixa abre o destino
        o.append(f'<g{_dn(n["id"])}><rect x="{x:.0f}" y="{y:.0f}" width="{nw}" height="{h}" rx="9" style="fill:var(--bg,#fff)"/><rect x="{x:.0f}" y="{y:.0f}" width="{nw}" height="{h}" rx="9" fill="{c}" fill-opacity=".08" stroke="{c}" stroke-width="2.2"/>'
                 + (f'<a href="{esc(hn)}">' if hn else '') + f'<text x="{x + 9:.0f}" y="{y + 17:.0f}" font-weight="700" style="fill:{c}{";text-decoration:underline" if hn else ""}">{esc(_cut(n["label"], cl))}</text>' + ('</a>' if hn else '')
                 + (f'<text class="mut" x="{x + 9:.0f}" y="{y + 32:.0f}">{esc(_cut(n["sub"], cl))}</text>' if n.get('sub') else '') + f'<title>{esc(n.get("detail") or n["label"])}</title></g>')
        my = y + hh
        for i, m in enumerate(n.get('componentes') or []):
            mh = chm(m)
            mc = m.get('cor') or c
            dsh = (';stroke-dasharray:5 3;fill-opacity:.4', ';opacity:.65') if m.get('dashed') else (';stroke:#b3261e;stroke-dasharray:5 3;fill-opacity:.3', ';fill:#b3261e;text-decoration:line-through') if m.get('riscada') else ('', '')
            cap = int((nw - 32) / 5.6)   # caracteres que cabem na linha do componente (fonte de 11px)
            lab = _cut(m['label'], max(10, int(cap * 0.6)) if m.get('sub') else cap)
            hc = href(m['link']) if m.get('link') else None   # componente com link do modelo ({'text', 'phase', 'anchor'}): a caixa abre o destino
            o.append((f'<a href="{esc(hc)}">' if hc else '') + f'<g{_dn(n["id"])}><rect class="box" x="{x + 8:.0f}" y="{my:.0f}" width="{nw - 16}" height="{mh}" rx="4" style="stroke:{mc};stroke-width:1.2{dsh[0]}"/>'
                     f'<text x="{x + 14:.0f}" y="{my + 16:.0f}" style="font-size:11px{dsh[1]}"><tspan font-weight="600"{" text-decoration=\"underline\"" if hc else ""}>{esc(lab)}</tspan>'
                     + (f'<tspan class="mut" dx="5">{esc(_cut(m["sub"], max(8, cap - len(lab) - 1)))}</tspan>' if m.get('sub') else '') + f'</text><title>{esc(m.get("detail") or (m["label"] + (" · " + m["sub"] if m.get("sub") else "")))}</title></g>' + ('</a>' if hc else ''))
            for j, rg in enumerate(m.get('regras') or []):
                ry = my + ch + j * rl
                h_ = href(rg) if isinstance(rg, dict) and rg.get('anchor') else None   # regra como link do modelo ({'text', 'phase', 'anchor'}): a caixa abre a regra
                rg = rg['text'] if isinstance(rg, dict) else rg
                o.append((f'<a href="{esc(h_)}">' if h_ else '') + f'<g{_dn(n["id"])}><rect x="{x + 16:.0f}" y="{ry:.0f}" width="{nw - 32}" height="{rl - 3}" rx="3" style="fill:#FFF4B8;stroke:#B8A000;stroke-width:1"/>'
                         f'<text x="{x + 22:.0f}" y="{ry + 13:.0f}" style="font-size:10px;fill:#4a4200{";text-decoration:underline" if h_ else ""}">{esc(_cut(rg, int((nw - 48) / 5.0)))}</text><title>{esc(rg)}</title></g>' + ('</a>' if h_ else ''))
            my += mh + 4
        if not n.get('componentes'):
            o.append(f'<text class="mut" x="{x + 14:.0f}" y="{y + hh + 16:.0f}" style="font-size:11px">sem componentes</text>')
    o.append('</svg>')
    leg = ''
    if b.get('dashed_label') and any(m.get('dashed') for n in nodes for m in n.get('componentes') or []):
        leg = f'<div class="legend"><span><i class="cdash"></i>{esc(b["dashed_label"])}</span></div>'
    if b.get('riscada_label') and any(m.get('riscada') for n in nodes for m in n.get('componentes') or []):
        leg += f'<div class="legend"><span><i class="cna"></i>{esc(b["riscada_label"])}</span></div>'
    return _legenda_colunas(b) + f'<div class="svgw">{"".join(o)}</div>' + leg


def sequencia(b):
    """Diagrama de sequência (graph kind 'sequencia'): nodes = participantes (id, label, sub, cor) da esquerda para a direita; edges = mensagens NA ORDEM da lista
    ({'from','to','label','retorno': True para a resposta, tracejada}). Cada participante tem uma linha de vida; as mensagens descem em ordem."""
    nodes, edges = b['nodes'], b['edges']
    pw, gx, top, passo = b.get('nw', 170), 40, 62, 34
    gtop = 22 if any(n.get('grupo') for n in nodes) else 0   # faixa para o nome da aplicação que rodeia os casos de uso
    top += gtop
    W = 20 + len(nodes) * pw + (len(nodes) - 1) * gx
    H = top + 20 + max(1, len(edges)) * passo
    cx = {n['id']: 10 + i * (pw + gx) + pw / 2 for i, n in enumerate(nodes)}
    cl = int((pw - 12) / 6.2)
    o = [f'<svg width="{W}" height="{H}" role="img" aria-label="{esc(b.get("title", ""))}"><defs><marker id="arq" markerWidth="11" markerHeight="11" refX="9" refY="4.5" markerUnits="userSpaceOnUse" orient="auto"><path d="M0,0 L10,4.5 L0,9 z" fill="#555"/></marker></defs>']
    i = 0
    while i < len(nodes):   # aplicação com casos de uso: caixa tracejada em volta das linhas de vida dos seus casos de uso
        gname = nodes[i].get('grupo')
        j = i
        while gname and j + 1 < len(nodes) and nodes[j + 1].get('grupo') == gname:
            j += 1
        if gname:
            x0, x1 = cx[nodes[i]['id']] - pw / 2 - 8, cx[nodes[j]['id']] + pw / 2 + 8
            gc = nodes[i].get('cor') or '#555555'
            o.append(f'<rect x="{x0:.0f}" y="3" width="{x1 - x0:.0f}" height="{H - 6}" rx="10" fill="none" stroke="{gc}" stroke-width="1.6" stroke-dasharray="8 5"/>'
                     f'<text x="{x0 + 8:.0f}" y="17" font-weight="700" style="font-size:12px;fill:{gc}">{esc(_cut(gname + " · " + (nodes[i].get("grupo_sub") or ""), int((x1 - x0) / 6.6)))}</text>')
        i = j + 1
    for n in nodes:
        x = cx[n['id']] - pw / 2
        c = n.get('cor') or '#555555'
        o.append(f'<line{_dn(n["id"])} x1="{cx[n["id"]]:.0f}" y1="{top - 4}" x2="{cx[n["id"]]:.0f}" y2="{H - 6}" stroke="#999" stroke-dasharray="4 4" stroke-width="1"/>')
        o.append(f'<g{_dn(n["id"])}><rect class="box" x="{x:.0f}" y="{6 + gtop}" width="{pw}" height="{top - 14 - gtop}" rx="6" style="stroke:{c};stroke-width:2"/>'
                 f'<text x="{x + 8:.0f}" y="{25 + gtop}" font-weight="700" style="fill:{c}">{esc(_cut(n["label"], cl))}</text>'
                 + (f'<text class="mut" x="{x + 8:.0f}" y="{41 + gtop}" style="font-size:11px">{esc(_cut(n["sub"], cl))}</text>' if n.get('sub') else '') + f'<title>{esc(n.get("detail") or n["label"])}</title></g>')
    import textwrap
    num = 0
    for i, e in enumerate(edges):
        if e['from'] not in cx or e['to'] not in cx:
            continue
        y = top + 14 + i * passo
        if e.get('nota'):   # regra de negócio: nota ancorada na linha de vida de quem a aplica
            w = pw * 1.9
            x0 = max(4, min(W - w - 4, cx[e['from']] - w / 2))
            linhas = textwrap.wrap(('Comando: ' if e.get('nota_tipo') == 'comando SQL' else 'Regra: ') + e.get('label', ''), int((w - 14) / 5.3)) or ['']
            if len(linhas) > 2:
                linhas = [linhas[0], _cut(' '.join(linhas[1:]), int((w - 14) / 5.3))]
            o.append(f'<g{_da(e, e["from"])}><rect x="{x0:.0f}" y="{y - 14}" width="{w:.0f}" height="28" rx="5" style="fill:#f9a825;fill-opacity:.16;stroke:#f9a825;stroke-width:1.2"/>'
                     + ''.join(f'<text x="{x0 + 7:.0f}" y="{y - 2 + 11 * k - (0 if len(linhas) > 1 else -5):.0f}" style="font-size:10px">{esc(t)}</text>' for k, t in enumerate(linhas))
                     + f'<title>{esc("Regra de negócio: " + e.get("label", ""))}</title></g>')
            continue
        num += 1
        x1, x2 = cx[e['from']], cx[e['to']]
        tracejada = ' stroke-dasharray="6 4"' if e.get('retorno') else ''
        o.append(f'<line{_da(e)} class="edge" x1="{x1:.0f}" y1="{y}" x2="{x2:.0f}" y2="{y}" style="stroke-width:1.5"{tracejada} marker-end="url(#arq)"><title>{esc(e.get("label", ""))}</title></line>')
        o.append(f'<text{_da(e)} x="{(x1 + x2) / 2:.0f}" y="{y - 5}" text-anchor="middle" style="font-size:11px;paint-order:stroke;stroke:var(--bg,#fff);stroke-width:3px">{esc(_cut(str(num) + ". " + e.get("label", ""), int(abs(x2 - x1) / 5.6) + 6))}</text>')
    o.append('</svg>')
    return f'<div class="svgw">{"".join(o)}</div>'


_SQL_KW = ('SELECT','DISTINCT','FROM','WHERE','AND','OR','NOT','IN','IS','NULL','LIKE','BETWEEN','ORDER','BY','GROUP','HAVING','INSERT','INTO','VALUES','UPDATE','SET','DELETE','JOIN','INNER','LEFT','RIGHT','OUTER','ON','AS','WITH','UR','CS','FETCH','FIRST','ROWS','ONLY','ASC','DESC','COUNT','MAX','MIN','SUM','AVG','EXISTS','UNION','ALL','CASE','WHEN','THEN','ELSE','END','CURRENT','DATE','TIMESTAMP')
_SQL_RE = re.compile(r"('(?:[^']|'')*')|(:[A-Za-z][\w\-]*)|(\b\d+(?:\.\d+)?\b)|(\b[A-Za-z_][\w]*\b)")


def _sql_html(t):
    def sub(m):
        if m.group(1):
            return f'<span class="sl">{esc(m.group(1))}</span>'
        if m.group(2):
            return f'<span class="sh">{esc(m.group(2))}</span>'
        if m.group(3):
            return f'<span class="sl">{m.group(3)}</span>'
        w = m.group(4)
        return f'<span class="sk">{w}</span>' if w.upper() in _SQL_KW else esc(w)
    out, pos = [], 0
    for m in _SQL_RE.finditer(t):
        out += [esc(t[pos:m.start()]), sub(m)]
        pos = m.end()
    return ''.join(out) + esc(t[pos:])


def wire(b):
    """Wireframe de uma tela (disposição dos componentes visuais): árvore {tipo, id, rotulo, liga, acao, direcao, colunas, relacionado, filhos}; grades de layout viram colunas;
    cada campo mostra o rótulo, a ligação com o bean e, quando existe, a relação com o campo da transação mainframe."""
    def fold(n):
        t, rot = n['tipo'], n.get('rotulo') or ''
        liga = n.get('liga') or ''
        rel = n.get('relacionado') or []
        selo = ''.join(f'<span class="wsel">{esc(r)}</span>' for r in rel[:3])
        lg = (f'campo → {liga}' if n.get('direcao') == 'entrada' else f'{liga} → exibe' if n.get('direcao') == 'saída' else liga) if liga else ''
        meta = (f'<span class="wmeta">{esc(lg)}</span>' if liga else '') + (f'<span class="wmeta wact">clique → {esc(n["acao"])}</span>' if n.get('acao') else '') + selo
        cls = 'wn ' + ('wi' if n.get('direcao') == 'entrada' else 'wo' if n.get('direcao') == 'saída' else 'wx') + (' wr' if rel else '')
        filhos = ''.join(fold(f) for f in n.get('filhos') or [])
        if t == 'grade de layout':
            return f'<div class="wgrid" style="grid-template-columns:repeat({max(int(n.get("colunas") or 1), 1)},minmax(0,1fr))">{filhos}</div>'
        if t == 'listagem (tabela)':
            cols = ''.join(f'<div class="wcol"><b>{esc(f.get("rotulo") or f.get("id") or "coluna")}</b>' + ''.join(f'<span class="wmeta">{esc((g.get("liga") + " → coluna") if g.get("liga") else "")}</span>' + ''.join(f'<span class="wsel">{esc(r)}</span>' for r in (g.get("relacionado") or [])[:2]) for g in f.get('filhos') or []) + '</div>'
                           for f in n.get('filhos') or [] if f['tipo'] == 'coluna da listagem' and (f.get('rotulo') or f.get('id') or f.get('filhos')))
            resto = ''.join(fold(f) for f in n.get('filhos') or [] if f['tipo'] != 'coluna da listagem')
            return f'<div class="wlist"><div class="wtt">listagem {esc(liga)}</div><div class="wcols">{cols}</div>{resto}</div>'
        if t in ('caixa de texto', 'área de texto', 'calendário (data)', 'caixa de senha'):
            return f'<div class="{cls}"><span class="wl">{esc(rot)}</span><span class="wbox">▭ {esc(t)}</span>{meta}</div>'
        if t in ('combobox', 'seleção múltipla'):
            return f'<div class="{cls}"><span class="wl">{esc(rot)}</span><span class="wbox">▾ {esc(t)}</span>{meta}{filhos}</div>'
        if t in ('checkbox', 'radio'):
            return f'<div class="{cls}"><span class="wl">{esc(rot)}</span><span class="wbox">{"☑" if t == "checkbox" else "◉"} {esc(t)}</span>{meta}</div>'
        if t in ('botão', 'link'):
            return f'<div class="{cls}"><span class="wbtn">{esc(rot or n.get("id") or t)}</span>{meta}</div>'
        if t == 'rótulo / texto':
            return f'<div class="{cls}"><span class="wtxt">{esc(rot or liga)}</span>{meta if liga else ""}</div>'
        if t == 'mensagem':
            return f'<div class="{cls}"><span class="wtxt">✉ mensagens</span></div>'
        if t == 'abas / painel recolhível':
            return f'<div class="wbox2"><div class="wtt">{esc(rot or n.get("id") or "abas")}</div>{filhos}</div>'
        if filhos or liga or rot:
            return f'<div class="wbox2">{(f"<div class=wtt>{esc(rot)}</div>" if rot else "")}{meta if liga else ""}{filhos}</div>'
        return ''
    corpo = ''.join(fold(n) for n in b.get('arvore') or [])
    leg = '<p class="note">Borda azul = campo de entrada; verde = saída (exibição); selo cinza = relação com campo de transação (campo do processo, PIC, bytes e programa); tracejado = componente sem relação com as transações analisadas.</p>'
    return f'<div class="wire">{corpo}</div>{leg}'


def _oa_ref(doc, sc):
    """Schema resolvido: devolve (nome, schema) quando é uma referência para components/schemas."""
    r = sc.get('$ref') if isinstance(sc, dict) else None
    if r:
        nome = r.rsplit('/', 1)[-1]
        return nome, doc.get('components', {}).get('schemas', {}).get(nome, {})
    return None, sc


def _oa_tipo(doc, sc):
    nome, x = _oa_ref(doc, sc)
    if nome:
        return nome
    t = x.get('type')
    t = ' | '.join(t) if isinstance(t, list) else (t or 'object')
    if t == 'array':
        return 'array de ' + (_oa_tipo(doc, x.get('items', {})))
    extra = [x[k] if k == 'format' else f'{k} {x[k]}' for k in ('format', 'maxLength', 'minimum', 'maximum', 'multipleOf') if k in x]
    return t + (f' ({", ".join(str(e) for e in extra)})' if extra else '')


def _oa_props(doc, sc, destaque=True):
    _n, x = _oa_ref(doc, sc)
    props = x.get('properties') or {}
    if not props:
        return '<p class="note">Sem campos.</p>'
    req = set(x.get('required') or [])
    linhas = ''.join(f'<tr><td><code>{esc(k)}</code>{"<span class=oa-req>*</span>" if k in req else ""}</td><td>{esc(_oa_tipo(doc, v))}</td><td>{esc(v.get("description", ""))}'
                     + ('<div class="oa-ext">x-legacy: ' + esc(json.dumps(v['x-legacy'], ensure_ascii=False)) + '</div>' if v.get('x-legacy') else '') + '</td></tr>' for k, v in props.items())
    return f'<table class="oa-t"><thead><tr><th>Campo</th><th>Tipo</th><th>Descrição</th></tr></thead><tbody>{linhas}</tbody></table>'


def openapi(b):
    """Contrato OpenAPI 3.1 no estilo de uma página de documentação: operações por caminho com método colorido, parâmetros, corpo, respostas e schemas; o YAML fica recolhido no fim."""
    doc = b['doc']
    info = doc.get('info', {})
    out = [f'<div class="oa"><div class="oa-h"><b>{esc(info.get("title", ""))}</b> <span class="oa-v">{esc(info.get("version", ""))}</span> <span class="oa-v">OpenAPI {esc(doc.get("openapi", ""))}</span>'
           f'<p>{esc(info.get("description", ""))}</p></div>']
    for cam, mets in doc.get('paths', {}).items():
        for met, op in mets.items():
            corpo = []
            if op.get('description'):
                corpo.append(f'<p>{esc(op["description"])}</p>')
            if op.get('parameters'):
                linhas = ''.join(f'<tr><td><code>{esc(p["name"])}</code>{"<span class=oa-req>*</span>" if p.get("required") else ""}</td><td>{esc(p["in"])}</td><td>{esc(_oa_tipo(doc, p.get("schema", {})))}</td><td>{esc(p.get("description", ""))}</td></tr>' for p in op['parameters'])
                corpo.append(f'<h4>Parâmetros</h4><table class="oa-t"><thead><tr><th>Nome</th><th>Em</th><th>Tipo</th><th>Descrição</th></tr></thead><tbody>{linhas}</tbody></table>')
            if op.get('requestBody'):
                sc = op['requestBody']['content']['application/json']['schema']
                corpo.append(f'<h4>Corpo da requisição <span class="oa-v">application/json</span> <span class="oa-v">{esc(_oa_ref(doc, sc)[0] or "")}</span></h4>' + _oa_props(doc, sc))
            rs = []
            for cod, r in op.get('responses', {}).items():
                c = r.get('content', {})
                sc = (c.get('application/json') or c.get('application/problem+json') or {}).get('schema')
                rs.append(f'<div class="oa-r"><span class="oa-c c{esc(cod[0])}">{esc(cod)}</span> {esc(r.get("description", ""))}' + (f' <span class="oa-v">{esc(_oa_ref(doc, sc)[0] or "")}</span>' if sc else '')
                          + (_oa_props(doc, sc) if sc and cod[0] == '2' else '') + '</div>')
            corpo.append('<h4>Respostas</h4>' + ''.join(rs))
            ext = ''
            if op.get('x-business-rules'):
                ext += '<h4>Regras de negócio <span class="oa-v">x-business-rules</span></h4><ul>' + ''.join(f'<li>{esc(x)}</li>' for x in op['x-business-rules']) + '</ul>'
            if op.get('x-calls'):
                ext += '<h4>Serviços chamados <span class="oa-v">x-calls</span></h4><ul>' + ''.join(f'<li>{esc(x["service"])} · <code>{esc(x.get("method", ""))} {esc(x.get("path", ""))}</code> · {esc(x.get("operation", x.get("feature", "")))}</li>' for x in op['x-calls']) + '</ul>'
            if op.get('x-integration'):
                ext += '<h4>Filas e programas <span class="oa-v">x-integration</span></h4><ul>' + ''.join(f'<li>{esc(x["command"])}: {esc(x["request-queue"])} → {esc(x["program"])} → {esc(x["response-queue"])}</li>' for x in op['x-integration']) + '</ul>'
            if op.get('x-legacy'):
                ext += '<p class="oa-ext">x-legacy: ' + esc(json.dumps(op['x-legacy'], ensure_ascii=False)) + '</p>'
            out.append(f'<details class="oa-op m-{esc(met)}"><summary><span class="oa-m">{esc(met.upper())}</span><code>{esc(cam)}</code><span class="oa-s">{esc(op.get("summary", ""))}</span>'
                       f'<span class="oa-id">{esc(op.get("operationId", ""))}</span></summary><div class="oa-b">{"".join(corpo)}{ext}</div></details>')
    esq = ''.join(f'<details class="oa-sc"><summary><code>{esc(n)}</code></summary>{_oa_props(doc, sc)}</details>' for n, sc in doc.get('components', {}).get('schemas', {}).items())
    out.append(f'<h4>Schemas</h4>{esq}')
    if b.get('yaml'):
        out.append(f'<details class="oa-sc"><summary>Arquivo do contrato (YAML)</summary><pre class="cod">{esc(b["yaml"])}</pre></details>')
    return ''.join(out) + '</div>'


def block(b):
    t = b['type']
    ttl = f'<h3>{esc(b["title"])}</h3>' if b.get('title') else ''
    if t == 'text':
        if b.get('sql'):
            return ttl + f'<div class="sql {b["sql"]}">{_sql_html(b["text"])}</div>'
        if b.get('pre'):
            return ttl + f'<pre class="cod">{esc(b["text"])}</pre>'
        return ttl + f'<p>{esc(b["text"])}</p>'
    if t == 'table':
        return ttl + table(b)
    if t == 'openapi':
        return ttl + openapi(b)
    if t == 'bars':
        return ttl + bars(b)
    if t == 'bands':
        return ttl + bands(b)
    if t == 'wire':
        return ttl + wire(b) + (f'<p class="note">{esc(b["note"])}</p>' if b.get('note') else '')
    if t == 'graph':
        if not b.get('nodes'):
            return ttl + '<p class="note">Nada a desenhar: o diagrama não tem nenhum nó neste código.</p>'
        return ttl + (er(b) if b.get('kind') == 'er' else colunas(b) if b.get('kind') == 'colunas' else contextos(b) if b.get('kind') == 'contextos' else sequencia(b) if b.get('kind') == 'sequencia' else flowchart(b) if b.get('kind') == 'flowchart' else layered(b)) + (f'<p class="note">{esc(b["note"])}</p>' if b.get('note') else '')
    raise ValueError(t)


# Todas as etapas, na ordem do índice lateral (pasta, título): a lista é fixa para a página depender só do seu modelo.
# SEM_RELATORIO: etapas sem página; aparecem no índice sem link. Etapas que esta análise não gerou (por exemplo, relatórios de IA sem interpretação,
# ou cenários que não existem) entram em model['ausentes'] pela função reindexar() e também ficam sem link.
SEM_RELATORIO = set()
# SO_IA: etapas que só têm a visão para IA (ia/report.json): não têm página humana, não aparecem no índice e os links para elas viram texto.
SO_IA = {'04-data-lineage', '08-golden-cases', '09-certification'}   # 04: a página é a 04b (Linhagem de dados)
RELATORIOS = [('00-program-classification', 'Classificação dos programas'), ('01-discovery-dependencies', 'Dependências'), 
              ('02-program-schema', 'Esquema de programas'), ('03-data-schema', 'Esquema de dados'), ('04-data-lineage', 'Linhagem de dados'), ('10 - sql-mapping', 'Mapeamento de comandos SQL'), ('04b-lineage-summary', 'Linhagem de dados'), ('05-decision-map', 'Mapa de decisões'), ('06-deterministic-rules', 'Regras determinísticas'),
              ('07-dynamic-analysis', 'Análise dinâmica'), ('08-golden-cases', 'Casos dourados'), ('09-certification', 'Certificação'), ('11 - business-rules', 'Regras de negócio'), ('12 - business-flows', 'Funcionalidades'), ('14 - pdc-mapping', 'Processos PDC'), ('15 - user-interface-mapping', 'Interfaces com o Usuário'), ('16 - domain-model', 'Modelo de domínio DDD'), ('17 - responsibility-segregation', 'Segregação de Responsabilidades'), ('18 - context-discovery', 'Contextualização'), ('19 - target-architecture', 'Arquitetura Alvo'), ('20 - contracts', 'Contratos de Integração'), ('20a - ui-design', 'Design das Aplicações de Frontend'), ('20b - implementation', 'Design das Aplicações dos Serviços'), ('21 - traceability-to-be', 'Casos de teste e evidências'), ('13 - traceability', 'Rastreabilidade'), ('22 - architecture-decision-records', 'Decisões Arquiteturais'), ('23 - enhancement-proposals', 'Propostas de Evolução')]

# Comportamento do índice lateral: arrastar a barra muda a largura; o botão recolhe/expande; a escolha fica no navegador (sem ela, o padrão vale).
SCRIPT = ('''(function(){var b=document.body,i=document.getElementById('idx'),r=document.getElementById('rz'),t=document.getElementById('tg'),k='idxw',c='idxc';\
function g(n){try{return localStorage.getItem(n)}catch(e){return null}}function s(n,v){try{localStorage.setItem(n,v)}catch(e){}}\
var w=g(k);if(w)b.style.setProperty('--w',w+'px');if(g(c)==='1')b.classList.add('nonav');\
t.onclick=function(){if(window.innerWidth<=800){b.classList.toggle('shownav')}else{b.classList.toggle('nonav');s(c,b.classList.contains('nonav')?'1':'0')}};\
r.onmousedown=function(e){e.preventDefault();r.classList.add('on');function m(ev){var v=Math.max(170,Math.min(ev.clientX,window.innerWidth*0.6));b.style.setProperty('--w',v+'px');s(k,Math.round(v))}\
function u(){r.classList.remove('on');document.removeEventListener('mousemove',m);document.removeEventListener('mouseup',u)}document.addEventListener('mousemove',m);document.addEventListener('mouseup',u)};\
})();''')


# Destaque das ligações em todo diagrama com nós (data-n) e arestas (data-a/data-b): passar o mouse num nó acende as arestas dele e os nós da outra ponta
# e apaga o resto; clicar (ou tocar) fixa o destaque, clicar de novo ou no fundo solta. Nó que é link (dentro de <a>, ou clique num <a> dentro do nó) não fixa: o clique abre o destino.
DESTAQUE = ('''document.querySelectorAll('.svgw svg').forEach(function(s){var ns=s.querySelectorAll('[data-n]');if(!ns.length||!s.querySelector('[data-a]'))return;var fx=null;\
function liga(k){s.querySelectorAll('.on').forEach(function(e){e.classList.remove('on')});s.classList.toggle('foco',k!==null);if(k===null)return;var v={};v[k]=1;\
s.querySelectorAll('[data-a]').forEach(function(e){var a=e.getAttribute('data-a'),b=e.getAttribute('data-b');if(a===k||b===k){e.classList.add('on');v[a]=1;v[b]=1}});\
ns.forEach(function(e){if(v[e.getAttribute('data-n')])e.classList.add('on')})}\
ns.forEach(function(g){var k=g.getAttribute('data-n');g.addEventListener('mouseenter',function(){if(fx===null)liga(k)});g.addEventListener('mouseleave',function(){if(fx===null)liga(null)});\
if(!g.closest('a'))g.addEventListener('click',function(ev){if(ev.target.closest&&ev.target.closest('a'))return;ev.stopPropagation();fx=fx===k?null:k;liga(fx)})});s.addEventListener('click',function(){fx=null;liga(null)})});''')


IA = ('04b-lineage-summary', '10 - sql-mapping', '11 - business-rules', '12 - business-flows', '13 - traceability', '15 - user-interface-mapping', '16 - domain-model', '17 - responsibility-segregation', '18 - context-discovery', '19 - target-architecture', '20 - contracts', '20a - ui-design', '20b - implementation', '21 - traceability-to-be')  # etapas escritas com apoio de IA; as demais são determinísticas


DECISOES = ('22 - architecture-decision-records',)  # etapas que registram decisões do dono da arquitetura (nem IA nem cálculo)
PROPOSTAS = ('23 - enhancement-proposals',)  # etapas que registram propostas de melhoria do processo de análise e modernização


def origem(fase):
    """Rótulo do tipo de etapa mostrado ao lado do título da página."""
    return '' if not fase else ('IA' if fase in IA else 'Humano' if fase in DECISOES or fase in PROPOSTAS else 'Determinística')   # decisões e propostas: registro humano


# Etapas do processo, na ordem do índice lateral, e a etapa de cada fase (pelo número da pasta): o índice lateral, o mapa das fases e a página de entrada
# agrupam as fases por elas.
ETAPAS = [('Discovery', 'O que existe no legado?', '#5b6b7f'), ('Reverse', 'Como o legado se comporta?', '#a06a00'),
          ('Modernization', 'Como o domínio deve ser reorganizado?', '#1f5fa8'), ('Forward', 'Como a solução é construída e provada?', '#1e7e34'),
          ('Consolidation', 'O que foi decidido e o que melhorar no processo?', '#6f42c1')]
ETAPA_DA_FASE = {**{n: 'Discovery' for n in ('00', '01', '02', '03', '05', '14')}, **{n: 'Reverse' for n in ('04', '04b', '06', '07', '08', '09', '10', '11', '12', '15')},
                 **{n: 'Modernization' for n in ('16', '17', '18')}, **{n: 'Forward' for n in ('19', '20', '20a', '20b', '21', '13')},   # a rastreabilidade (13) é completada pela fase 21 até o código
                 **{n: 'Consolidation' for n in ('22', '23')}}


def etapa(pasta):
    return ETAPA_DA_FASE.get(pasta.split('-')[0].strip(), 'Reverse')


def visiveis(model):
    """Seções da página humana: a seção marcada so_ia fica só na visão para IA (insumo de outras fases), com o texto de so_ia dizendo onde ela é exibida."""
    return [s for s in model['sections'] if not s.get('so_ia')]


def blocos_visiveis(s):
    """Blocos da seção na página humana: o bloco marcado so_ia (insumo de outras fases ou prompts) fica só na visão para IA."""
    return [b for b in s['blocks'] if not b.get('so_ia')]


def indice(model):
    """Barra lateral: todos os relatórios (o atual destacado) e, abaixo dele, as seções do relatório atual."""
    atual = model.get('phase') or ''
    secoes, grupo = '', None
    for x in visiveis(model):   # seções do mesmo grupo (report_curadoria) ficam sob o título do grupo
        if x.get('grupo') != grupo:
            grupo = x.get('grupo')
            if grupo:
                secoes += f'<span class="grp">{esc(grupo)}</span>'
        secoes += f'<a{" class=\"emgrp\"" if grupo else ""} href="#{esc(x["id"])}">{esc(x["title"])}</a>'
    rel = ''
    for nome, _pergunta, _cor in ETAPAS:   # as fases agrupadas pela etapa do processo
        itens = ''
        for pasta, titulo in RELATORIOS:
            if pasta in SO_IA or etapa(pasta) != nome:
                continue
            if pasta in SEM_RELATORIO or pasta in model.get('ausentes', ()):
                itens += f'<span class="off">{esc(titulo)} <small>(não gerado)</small></span>'
            elif pasta == atual:
                itens += f'<a class="cur" href="#">{esc(titulo)}</a><div class="sec">{secoes}</div>'
            else:
                itens += f'<a href="../../{quote(pasta)}/human/report.html">{esc(titulo)}</a>'
        if itens:
            rel += f'<h4>{esc(nome)}</h4>{itens}'
    if atual not in dict(RELATORIOS):
        rel += f'<h4>Seções</h4><div class="sec">{secoes}</div>'
    entrada = '<a class="ent" style="font-weight:600;margin-bottom:6px" href="../../index.html">← Índice</a>'   # página de entrada da análise (index.html na raiz da pasta da análise)
    return f'<aside id="idx">{entrada}{rel}</aside><div id="rz" title="Arraste para ajustar a largura"></div><button id="tg" type="button" title="Mostrar ou ocultar o índice">☰ índice</button>'


def etiqueta(model):
    o = origem(model.get('phase') or '')
    return f'<span class="tag">{o}</span>' if o else ''


def sem_numero(titulo):
    """Título sem o número da fase ("Fase 4b — Resumo..." → "Resumo..."): as páginas mostram as fases pelo nome."""
    return re.sub(r'^Fase\s+\S+\s+—\s+', '', titulo)


# Estilo elegante (o padrão, como a página de entrada): seções com a barra da etapa, números em cartões, índices em grade de cartões com etiquetas de
# situação, fichas em lista de definição, tabelas com a borda da etapa e avisos em caixa de destaque. page(model, elegante=False) volta ao estilo simples.
# Links com data-modal (report_model.link_arquivo com modal): o arquivo abre num <dialog> com iframe sobre o relatório (funciona aberto do disco, sem servidor);
# Ctrl/Shift/clique do meio seguem o link normal. A página aberta no iframe pode se ajustar (por exemplo, esconder o "voltar") testando window.self !== window.top.
MODAL = ('''(function(){var st=document.createElement('style');st.textContent='dialog.mdl{width:min(1200px,94vw);height:90vh;padding:0;border:1px solid var(--line);'+\
'border-radius:8px;background:var(--bg);color:inherit;box-shadow:0 10px 40px rgba(0,0,0,.35)}dialog.mdl[open]{display:flex;flex-direction:column;overflow:hidden}dialog.mdl::backdrop{background:rgba(0,0,0,.45)}'+\
'dialog.mdl .mh{display:flex;align-items:center;gap:14px;padding:8px 14px;border-bottom:1px solid var(--line);background:var(--card)}dialog.mdl .mh b{flex:1}'+\
'dialog.mdl .mh button{border:0;background:none;font-size:20px;cursor:pointer;color:inherit}dialog.mdl iframe{flex:1;min-height:0;width:100%;border:0;background:var(--bg)}';\
document.head.appendChild(st);var d=null;\
document.addEventListener('click',function(e){var a=e.target.closest&&e.target.closest('a[data-modal]');if(!a||e.ctrlKey||e.metaKey||e.shiftKey||e.button)return;\
e.preventDefault();if(!d){d=document.createElement('dialog');d.className='mdl';var h=document.createElement('div');h.className='mh';var t=document.createElement('b'),n=document.createElement('a'),x=document.createElement('button');\
n.target='_blank';n.textContent='abrir em nova aba';x.type='button';x.title='Fechar (Esc)';x.textContent='\u2715';x.onclick=function(){d.close()};h.append(t,n,x);d.append(h,document.createElement('iframe'));\
d.addEventListener('click',function(ev){if(ev.target===d)d.close()});d.addEventListener('close',function(){d.querySelector('iframe').src='about:blank';document.documentElement.style.overflow=''});document.body.appendChild(d)}\
d.querySelector('b').textContent=a.getAttribute('data-modal');d.querySelector('.mh a').href=a.href;d.querySelector('iframe').src=a.href;document.documentElement.style.overflow='hidden';d.showModal()})})();''')

CSS_ELEGANTE = """
h2.secband{border-left:5px solid var(--c);padding:4px 10px;background:var(--card);border-radius:4px;margin-top:28px}
p.objetivo{font-size:15px;margin:6px 0 12px}p.objetivo b{color:var(--c)}
.grupo{margin:36px 0 4px;padding:8px 0 4px;border-bottom:2px solid var(--c)}.grupo .gt{font-size:20px;font-weight:700;margin:0}.grupo p{margin:4px 0 0;color:var(--mut);font-size:13px}

.callout{border:1px solid var(--line);border-left:5px solid var(--c);background:var(--card);border-radius:6px;padding:8px 12px;margin:10px 0}
.callout b{display:block;margin-bottom:2px}
p.fora{margin:8px 0}
.grade{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;margin:10px 0 18px}
.cartao{border:1px solid var(--line);border-top:4px solid var(--c);border-radius:8px;background:var(--card);padding:10px 12px;display:flex;flex-direction:column;gap:6px}
.cartao .pill{align-self:flex-start}.cartao h3{margin:0;font-size:15px}.cartao h3 a{text-decoration:none}
.chips{display:flex;flex-wrap:wrap;gap:6px}.chip{font-size:12px;border:1px solid var(--line);border-radius:10px;padding:1px 8px}
.pill{display:inline-block;font-size:12px;border-radius:10px;padding:1px 9px;font-weight:600;border:1px solid}
.pill.ok{color:#1e7e34;border-color:#1e7e34;background:#1e7e3414}.pill.mau{color:#c62828;border-color:#c62828;background:#c6282814}.pill.neutro{color:var(--mut);border-color:var(--line)}
dl.ficha{display:grid;grid-template-columns:max-content 1fr;gap:6px 16px;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px;margin:10px 0}
dl.ficha dt{color:var(--mut);font-weight:600}dl.ficha dd{margin:0}
.tw{border:none;border-top:4px solid var(--c);border-bottom:1px solid var(--line);border-radius:0;max-height:520px;overflow:auto;box-shadow:none;background:var(--bg);margin:6px 0 4px}
.tw table{font-size:13px}.tw th,.tw td{border:none;border-bottom:1px solid var(--line);padding:7px 10px}
.tw th{background:color-mix(in srgb,var(--c) 12%,var(--card));border-bottom:1px solid var(--c);font-weight:600;font-size:12px;letter-spacing:.02em;white-space:nowrap}
.tw tr:nth-child(even) td{background:var(--bg)}.tw tr:nth-child(odd) td{background:var(--card)}
.tw tr:hover td{background:color-mix(in srgb,var(--c) 9%,transparent)}
.tw tr.mk td{background:color-mix(in srgb,#c62828 7%,transparent)}.tw tr.mk td:first-child{box-shadow:inset 3px 0 0 #c62828}
.tw td.num,.tw th.num{text-align:right;font-variant-numeric:tabular-nums}
.tw tr:last-child td{border-bottom:none}
"""
NUMEROS = (['Item', 'Quantidade'], ['Indicador', 'Valor'], ['Etapa', 'Quantidade'])


def _txt(v):
    return v if isinstance(v, str) else (v.get('text') if isinstance(v, dict) else str(v))


def pill(v):
    """Situação como etiqueta colorida: conforme, OK, Aceita… em verde; fora da regra, FALHA… em vermelho."""
    t = _txt(v) or ''
    mau = any(k in t for k in ('fora da regra', 'FALHA', 'Recusada', 'falha'))
    ok = not mau and any(k in t for k in ('(conforme)', 'OK', 'Aceita', 'Implementada', 'conforme'))
    return f'<span class="pill {"mau" if mau else "ok" if ok else "neutro"}">{cell(v)}</span>'


def _numero(v):
    t = (_txt(v) or '').strip()
    return bool(re.fullmatch(r'-?[\d.,]+( \+ [\d.,]+)?', t))


def table_elegante(b):
    """Tabela no estilo elegante: situação em etiqueta colorida e colunas só com números alinhadas à direita (o resto como table())."""
    cols, rows = b['columns'], b['rows']
    situ = {i for i, c in enumerate(cols) if c.startswith(('Situação', 'Resultado', 'Conformidade', 'Status', 'Execução'))}
    num = {i for i in range(len(cols)) if rows and all(_numero(r[i]) or _txt(r[i]) in ('', '—') for r in rows) and any(_numero(r[i]) for r in rows)}
    ids, marks = b.get('row_ids') or [], b.get('row_marks') or []
    dn, rs = b.get('row_descartada') or [], b.get('row_riscada') or []
    def _cls(i):
        c = (['mk'] if i < len(marks) and marks[i] else []) + (['dn'] if i < len(dn) and dn[i] else []) + (['rs'] if i < len(rs) and rs[i] else [])
        return f' class="{" ".join(c)}">' if c else '>'
    head = ''.join(f'<th{" class=\"num\"" if i in num else ""}>{esc(c)}</th>' for i, c in enumerate(cols))
    body = ''.join((f'<tr id="{esc(ids[k])}"' if k < len(ids) and ids[k] else '<tr') + _cls(k)
                   + ''.join(f'<td class="num">{cell(v)}</td>' if i in num else f'<td>{pill(v) if i in situ and _txt(v) not in ("", "—") else cell(v)}</td>' for i, v in enumerate(r)) + '</tr>'
                   for k, r in enumerate(rows))
    return f'<div class="tw"><table><tr>{head}</tr>{body}</table></div>' + (f'<p class="note">{esc(b["note"])}</p>' if b.get('note') else '')


def _linhas(rows):
    """Marca a tabela do modelo desenhada em outra forma (cartões, ficha, texto) com a quantidade de linhas, para a conferência JSON × HTML."""
    return f' data-linhas="{len(rows)}"'


def block_elegante(b, cor):
    t, ttl = b['type'], b.get('title') or ''
    if t == 'text' and not b.get('pre') and not b.get('sql') and ttl in ('Como ler', 'Regra'):
        return f'<div class="callout" style="--c:{cor}"><b>{esc(ttl)}</b>{esc(b["text"])}</div>'
    if t != 'table':
        return block(b)
    cols, rows = b['columns'], b['rows']
    if cols in NUMEROS and len(rows) <= 12:   # lista longa de números fica em tabela
        return (f'<h3>{esc(ttl)}</h3>' if ttl else '') + f'<div class="cards etapa-nums" style="--c:{cor}"{_linhas(rows)}>' + ''.join(
            f'<div class="card"><b>{cell(r[1])}</b><span>{cell(r[0])}</span></div>' for r in rows) + '</div>'
    if ttl.startswith('Fora deste relatório'):
        return f'<div{_linhas(rows)}>' + ''.join('<p class="fora"><b>Fora deste relatório:</b> ' + ' · '.join(   # texto corrido, sem caixa
            f'{esc(c)}: {cell(v)}' if i else cell(v) for i, (c, v) in enumerate(zip(cols, r)) if _txt(v) not in ('', '—')) + '</p>' for r in rows) + '</div>'
    if cols == ['Campo', 'Conteúdo']:
        return (f'<h3>{esc(ttl)}</h3>' if ttl else '') + f'<dl class="ficha"{_linhas(rows)}>' + ''.join(
            f'<dt>{cell(r[0])}</dt><dd>{pill(r[1]) if _txt(r[0]).startswith(("Conformidade", "Status", "Situação")) else cell(r[1])}</dd>' for r in rows) + '</dl>'
    if 'Título' in cols and 0 < len(rows) <= 60:
        it = cols.index('Título')
        situ = next((i for i, c in enumerate(cols) if c.startswith(('Conformidade', 'Status', 'Situação', 'Resultado'))), None)
        cartoes = []
        for r in rows:
            cab = (cell(r[0]) + ' · ' if it != 0 else '') + cell(r[it])
            chips = ''.join(f'<span class="chip">{esc(c)}: {cell(v)}</span>' for i, (c, v) in enumerate(zip(cols, r)) if i not in (0, it, situ) and _txt(v) not in ('', '—'))
            cartoes.append(f'<div class="cartao" style="--c:{cor}"><h3>{cab}</h3>' + (pill(r[situ]) if situ is not None else '') + (f'<div class="chips">{chips}</div>' if chips else '') + '</div>')
        return (f'<h3>{esc(ttl)}</h3>' if ttl else '') + f'<div class="grade"{_linhas(rows)}>{"".join(cartoes)}</div>' + (f'<p class="note">{esc(b["note"])}</p>' if b.get('note') else '')
    return (f'<h3>{esc(ttl)}</h3>' if ttl else '') + table_elegante(b)


def page(model, elegante=True):
    _PHASE[0] = model.get('phase') or ''
    cards = ''.join(f'<div class="card"><b>{esc(c["value"])}</b><span>{esc(c["label"])}</span></div>' for c in model.get('destaques') or model.get('summary', []))
    fase = model.get('phase') or ''
    nome_e, pergunta_e, cor_e = next(((n, q, c) for n, q, c in ETAPAS if n == etapa(fase)), (None, None, None)) if fase else (None, None, None)
    faixa = f'<div class="etapa etapa-fase" style="--c:{cor_e}"><p><b>{esc(nome_e)}</b> · {esc(pergunta_e)}</p></div>' if nome_e else ''   # a etapa do processo, como na página de entrada
    vis = visiveis(model)
    if elegante:
        secs = ''.join(_grupo(model, vis, k) + f'<h2 id="{esc(s["id"])}" class="secband" style="--c:{cor_e or "var(--line)"}">{esc(s["title"])}</h2>' + (f'<p class="sub">{esc(s["text"])}</p>' if s.get('text') else '')
                       + '<div class="secb">' + ''.join(block_elegante(b, cor_e or 'var(--line)') for b in blocos_visiveis(s)) + '</div>' for k, s in enumerate(vis))
    else:
        secs = ''.join(_grupo(model, vis, k) + f'<h2 id="{esc(s["id"])}">{esc(s["title"])}</h2>' + (f'<p class="sub">{esc(s["text"])}</p>' if s.get('text') else '') + '<div class="secb">' + ''.join(block(b) for b in blocos_visiveis(s)) + '</div>' for k, s in enumerate(vis))
    topo = (f'<p class="objetivo"><b>Objetivo:</b> {esc(model["objetivo"])}</p>' if model.get('objetivo') else f'<p class="sub">{esc(model.get("subtitle", ""))}</p>')
    return (f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(sem_numero(model["title"]))}</title><style>{CSS}{CSS_ELEGANTE if elegante else ""}</style></head><body>{indice(model)}<main{f' style="--c:{cor_e}"' if elegante and cor_e else ''}>{faixa}<h1>{esc(sem_numero(model["title"]))}</h1>{etiqueta(model)}'
            f'{topo}<div class="cards etapa-nums" style="--c:{cor_e or 'var(--line)'}">{cards}</div>{secs}</main><script>{SCRIPT}{DESTAQUE}{MODAL if ' data-modal="' in secs else ''}</script></body></html>')


def _grupo(model, secoes, k):
    """Título do grupo (report_curadoria) antes da primeira seção dele; não é h2, para a conferência contar só as seções."""
    g = secoes[k].get('grupo')
    if not g or (k and secoes[k - 1].get('grupo') == g):
        return ''
    desc = (model.get('grupos') or {}).get(g)
    return f'<div class="grupo"><p class="gt">{esc(g)}</p>' + (f'<p>{esc(desc)}</p>' if desc else '') + '</div>'


def counts(model):
    """Contagens do que o HTML desenha; o teste compara com o que o JSON traz."""
    c = {'sections': len(visiveis(model)), 'tables': 0, 'table_rows': 0, 'graphs': 0, 'nodes': 0, 'edges': 0, 'bars': 0, 'bar_rows': 0, 'texts': 0}
    for s in visiveis(model):
        for b in blocos_visiveis(s):
            t = b['type']
            if t == 'table':
                c['tables'] += 1
                c['table_rows'] += len(b['rows'])
            elif t == 'graph':
                c['graphs'] += 1
                c['nodes'] += len(b['nodes'])
                c['edges'] += len(b['edges'])
            elif t == 'bands':
                c['bands'] = c.get('bands', 0) + 1
            elif t == 'bars':
                c['bars'] += 1
                c['bar_rows'] += len(b['series'])
            else:
                c['texts'] += 1
    return c


def reindexar(saida):
    """Depois de gerar as etapas, marca em cada relatório (JSON e HTML, do mesmo modelo) quais etapas do índice esta análise não gerou, para o índice
    lateral não apontar para páginas que não existem, e aplica a curadoria de cada fase (report_curadoria), idempotente."""
    import report_curadoria as rc   # objetivo, números principais, descrições dos diagramas, tabelas repetidas e grupos de cada fase
    saida = Path(saida)
    arquivos = sorted(saida.glob('*/ia/report.json'))
    destinos = {f.parent.parent.name: rc.ancoras(rc.curar(json.loads(f.read_text(encoding='utf-8')))) for f in arquivos}   # um relatório por vez: há relatórios de dezenas de MB
    for f in arquivos:
        m = rc.curar(json.loads(f.read_text(encoding='utf-8')))
        rc.corrigir_links(m, destinos)
        ausentes = [p for p, _t in RELATORIOS if p not in SEM_RELATORIO and p not in SO_IA and not (saida / p / 'human' / 'report.html').exists()]
        if ausentes:
            m['ausentes'] = ausentes
        else:
            m.pop('ausentes', None)
        f.write_text(json.dumps(m, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
        gravar_html(f.parent.parent, m)


def gravar_html(pasta_fase, m):
    """Grava human/report.html da etapa; etapa só com a visão para IA (SO_IA) não tem página: a pasta human é removida."""
    human = Path(pasta_fase) / 'human'
    if Path(pasta_fase).name in SO_IA:
        if human.exists():
            shutil.rmtree(human)
        return
    human.mkdir(parents=True, exist_ok=True)
    (human / 'report.html').write_text(page(m), encoding='utf-8')


# ----------------------------------------------------------------------------- referências cruzadas entre relatórios
# Cada tipo de referência tem um relatório "dono" (a tabela ou seção em que ela é definida). Depois de gerar todos os relatórios, ligar() âncora as linhas
# donas (row_ids) e transforma, em todas as tabelas de todos os relatórios, cada ocorrência do identificador num link para o dono. Tudo calculado dos
# próprios relatórios: nenhum nome de programa, tabela ou regra é fixo no código.
def _tabelas(m):
    for s in m['sections']:
        for b in s['blocks']:
            if b['type'] == 'table':
                yield b


def _ancorar(b, chaves, prefixo, ancoras=None):
    """Garante row_ids na tabela dona e devolve {chave da linha: âncora}."""
    ids = b.get('row_ids') or []
    out = {}
    novos = []
    for i, k in enumerate(chaves):
        a = ids[i] if i < len(ids) and ids[i] else ((ancoras[i] if ancoras else prefixo + str(k)) if k not in (None, '') else '')
        novos.append(a)
        if k not in (None, '') and k not in out:
            out[k] = a
    b['row_ids'] = novos
    return out


def _coluna(b, nome):
    return b['columns'].index(nome) if nome in b['columns'] else None


def _texto(c):
    return c['text'] if isinstance(c, dict) and 'text' in c else (c if isinstance(c, str) else str(c))


def _registrar(modelos):
    """{tipo: {chave: (fase, âncora)}} lendo os relatórios donos; marca com row_ids as linhas donas."""
    reg = {'programa': {}, 'tabela': {}, 'copybook': {}, 'cenario': {}, 'decisao': {}, 'regra': {}, 'query': {}}
    m = modelos.get('00-program-classification')
    for b in _tabelas(m[1]) if m else ():
        if b['title'] == 'Programas' and _coluna(b, 'Programa') is not None:
            c = _coluna(b, 'Programa')
            for k, a in _ancorar(b, [_texto(r[c]) for r in b['rows']], 'programa-').items():
                reg['programa'][k] = ('00-program-classification', a)
    m = modelos.get('10 - sql-mapping')
    for sec in (m[1]['sections'] if m else ()):
        if re.fullmatch(r'[A-Z][A-Z0-9]{3,7}-Q\d+', sec['id']):
            reg['query'][sec['id']] = ('10 - sql-mapping', sec['id'])   # cada query tem a sua seção completa no sql-mapping
    m = modelos.get('05-decision-map')
    for sec in (m[1]['sections'] if m else ()):
        if sec['id'].startswith('prog-'):
            reg['programa'][sec['id'][5:]] = ('05-decision-map', sec['id'])   # todo link de programa aponta para o mapa de decisões do programa (quando ele tem)
    m = modelos.get('03-data-schema')
    for b in _tabelas(m[1]) if m else ():
        if b['title'].startswith('Colunas por tabela') and _coluna(b, 'Tabela') is not None:
            c = _coluna(b, 'Tabela')
            ids, vistos = [], set()
            for r in b['rows']:
                t = _texto(r[c])
                ids.append('' if t in vistos else 'tabela-' + t)
                if t not in vistos:
                    reg['tabela'][t] = ('03-data-schema', 'tabela-' + t)
                vistos.add(t)
            b['row_ids'] = ids
    for b in _tabelas(m[1]) if m else ():
        if b['title'].startswith('Colunas deduzidas') and _coluna(b, 'Tabela') is not None:
            c = _coluna(b, 'Tabela')
            ids, vistos = [], set()
            for r in b['rows']:
                t = _texto(r[c])
                novo = t not in vistos and t not in reg['tabela']
                ids.append('tabela-' + t if novo else '')
                if novo:
                    reg['tabela'][t] = ('03-data-schema', 'tabela-' + t)
                vistos.add(t)
            b['row_ids'] = ids
    m = modelos.get('04-data-lineage')
    for sec in (m[1]['sections'] if m else ()):
        if sec['id'].startswith('tab-'):
            reg['tabela'].setdefault(sec['id'][4:], ('04-data-lineage', sec['id']))
    m = modelos.get('02-program-schema')
    for b in _tabelas(m[1]) if m else ():
        if b['title'] == 'Copybooks: usados ou não' and _coluna(b, 'Copybook') is not None:
            c = _coluna(b, 'Copybook')
            for k, a in _ancorar(b, [_texto(r[c]) for r in b['rows']], 'copybook-').items():
                reg['copybook'][k] = ('02-program-schema', a)
    m = modelos.get('07-dynamic-analysis')
    for b in _tabelas(m[1]) if m else ():
        if b['title'] == 'Cenários' and _coluna(b, 'Cenário') is not None:
            c = _coluna(b, 'Cenário')
            for k, a in _ancorar(b, [_texto(r[c]) for r in b['rows']], 'cenario-' ).items():
                reg['cenario'][k] = ('07-dynamic-analysis', a)
            ids = b['row_ids']
            b['row_ids'] = [f'cenario-{i + 1}' if x else '' for i, x in enumerate(ids)]
            for i, r in enumerate(b['rows']):
                reg['cenario'][_texto(r[c])] = ('07-dynamic-analysis', f'cenario-{i + 1}')
    m = modelos.get('05-decision-map')
    for b in _tabelas(m[1]) if m else ():
        if b['title'].startswith('Mapa de decisão — ') and _coluna(b, 'Código') is not None:
            prog = b['title'].split('— ', 1)[1].strip()
            c = _coluna(b, 'Código')
            for k, a in _ancorar(b, [_texto(r[c]).split(':')[-1] for r in b['rows']], f'decisao-{prog}-').items():
                reg['decisao'][(prog, k)] = ('05-decision-map', a)
    m = modelos.get('06-deterministic-rules')
    for b in _tabelas(m[1]) if m else ():
        if b['title'].startswith('Regras de ') and _coluna(b, 'Regra') is not None:
            prog = b['title'][len('Regras de '):].strip()
            c = _coluna(b, 'Regra')
            for k, a in _ancorar(b, [_texto(r[c]) for r in b['rows']], f'regra-{prog}-').items():
                reg['regra'][(prog, k)] = ('06-deterministic-rules', a)
    return reg


def _contexto(b, row, reg):
    """Programa a que os códigos Dnnn e Rnnn da linha se referem: o do título da tabela ou o da coluna Programa."""
    for pedaco in re.split(r'[\s—:,]+', b.get('title') or ''):
        if pedaco in reg['programa']:
            return pedaco
    for n in ('Programa', 'Programas', 'Chamador', 'Programa chamador'):
        c = _coluna(b, n)
        if c is not None and _texto(row[c]).strip() in reg['programa']:
            return _texto(row[c]).strip()
    return None


def _ligar_texto(t, fase, propria, ctx, reg, padrao):
    """Pedaços [texto | link] de t, ou None se nada foi ligado. 'propria' é a âncora da linha dona (não liga a si mesma)."""
    partes, pos, achou = [], 0, False
    for m in padrao.finditer(t):
        tok = m.group(0)
        alvo = None
        if m.group('rp'):
            alvo = (reg['regra'] if m.group('rr')[0] == 'R' else reg['decisao']).get((m.group('rp'), m.group('rr')))
        elif m.group('d'):
            alvo = reg['decisao'].get((ctx, tok)) if ctx else None
        elif m.group('r'):
            alvo = reg['regra'].get((ctx, tok)) if ctx else None
        elif m.group('q'):
            alvo = reg['query'].get(tok.split('.')[0])   # a query desdobrada (query.k) leva à seção da query original
        else:
            alvo = reg['programa'].get(tok) or reg['tabela'].get(tok) or reg['copybook'].get(tok)
        if not alvo or (alvo[0] == fase and alvo[1] == propria):
            continue
        partes += [t[pos:m.start()], {'text': tok, 'phase': alvo[0], 'anchor': alvo[1]}]
        pos, achou = m.end(), True
    if not achou:
        return None
    partes.append(t[pos:])
    return [p for p in partes if p != '']


def ligar(saida):
    """Liga todos os relatórios pelas referências cruzadas: programa, tabela DB2, copybook, decisão (Dnnn), regra determinística (Rnnn ou PROG:Rnnn) e cenário
    viram link para o relatório que os define, em qualquer tabela de qualquer relatório. Reescreve JSON e HTML do mesmo modelo; rodar de novo não duplica nada."""
    saida = Path(saida)
    modelos = {}
    for f in sorted(saida.glob('*/ia/report.json')):
        modelos[f.parts[-3]] = (f, json.loads(f.read_text(encoding='utf-8')))
    reg = _registrar(modelos)
    nomes = sorted({*reg['programa'], *reg['tabela'], *reg['copybook']}, key=lambda n: -len(n))
    progs = '|'.join(re.escape(p) for p in sorted(reg['programa'], key=lambda n: -len(n))) or '(?!x)x'
    alt = '|'.join(re.escape(n) for n in nomes) or '(?!x)x'
    qs = '|'.join(re.escape(q) for q in sorted(reg['query'], key=lambda n: -len(n))) or '(?!x)x'
    padrao = re.compile(rf'(?<![\w-])(?:(?P<rp>{progs}):(?P<rr>[RDE]\d{{3}})\b|(?P<d>D\d{{3}})\b|(?P<r>R\d{{3}})\b|(?P<q>(?:{qs})(?:\.\d+)?)(?![\w-])|(?:{alt})(?![\w-]))')
    total = 0
    for fase, (f, m) in modelos.items():
        for b in _tabelas(m):
            ids = b.get('row_ids') or []
            for i, row in enumerate(b['rows']):
                ctx = _contexto(b, row, reg)
                propria = ids[i] if i < len(ids) else ''
                for j, c in enumerate(row):
                    if not isinstance(c, str) or len(c) < 4:
                        continue
                    ex = reg['cenario'].get(c)
                    if ex and not (ex[0] == fase and ex[1] == propria):
                        row[j] = {'text': c, 'parts': [{'text': c, 'phase': ex[0], 'anchor': ex[1]}]}
                        total += 1
                        continue
                    ps = _ligar_texto(c, fase, propria, ctx, reg, padrao)
                    if ps:
                        row[j] = {'text': c, 'parts': ps}
                        total += 1
    for fase, (f, m) in modelos.items():
        f.write_text(json.dumps(m, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
        gravar_html(f.parent.parent, m)
    return total
