#!/usr/bin/env python3
"""Página de entrada da análise (index.html na raiz da pasta da análise): números da análise e resumo das fases, por etapa do processo.

  python3 gerar_indice.py <pasta-da-analise>

As fases ficam agrupadas pelas etapas do mapa das fases (Discovery, Reverse, Modernization, Forward, Consolidation). Cada etapa mostra os números da análise
(programas COBOL, copybooks, DCLGEN, arquivos do PDC, comandos SQL, páginas da intranet, contextos, aplicações implementadas…) e um cartão por fase
com o nome, o tipo (determinística, IA, decisões, propostas) e a descrição. Os números vêm do resumo de cada relatório (NN-*/ia/report.json), pelo
rótulo que o gerador da fase usa; um número cuja fase não foi gerada não aparece, e uma fase da lista de relatórios que a análise não gerou aparece
como não gerada. O título usa o nome do recorte (chave "recorte" do pipeline.config.json ao lado da pasta da análise). Nenhum nome de programa,
tabela ou regra é fixo no código."""
import json
import re
import sys
from html import escape as esc
from pathlib import Path
from urllib.parse import quote

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R / 'semantic_core'))
sys.path.insert(0, str(R / 'tools'))
import report_render as rr  # noqa: E402
from mapa_fases import ETAPAS, ETAPA_DA_FASE  # noqa: E402

# Números da análise por etapa: (o que o número conta, número da fase, rótulo no resumo do relatório da fase; uma tupla de rótulos é somada)
NUMEROS = {
    'Discovery': [('programas COBOL analisados', '00', 'programas'), ('copybooks', '01', 'copybooks'), ('DCLGEN', '03', 'com DCLGEN'),
                  ('tabelas DB2', '03', 'tabelas'), ('decisões nos programas', '05', 'decisões'), ('transações PDC consideradas', '14', 'com programa analisado')],
    'Reverse': [('comandos SQL', '04', 'comandos SQL'), ('queries após unificar', '10', 'queries (após unificar)'),
                ('regras de negócio', '11', 'regras de negócio'), ('funcionalidades', '12', 'funcionalidades'),
                ('cenários da análise dinâmica', '07', 'cenários'),
                ('telas analisadas', '15', 'telas mantidas no funil')],
    'Modernization': [('contextos de domínio', '18', 'Domain Contexts'),
                      ('contextos de entrega', '18', 'Delivery Contexts'), ('agregados', '16', 'agregados'),
                      ('classes de domínio', '16', 'classes de domínio'), ('queries com mais de um dono', '17', 'queries multi-owner')],
    'Forward': [('casos de uso', '19', 'casos de uso'), ('contratos OpenAPI', '20', 'contratos OpenAPI'),
                ('operações nos contratos', '20', 'operações'), ('copybooks de integração', '20', 'copybooks'),
                ('programas mainframe novos (DB2 + corporativos)', '22', 'programas mainframe (DB2 + CORP)'),
                ('cenários de teste', '21', 'cenários de teste')],
    'Consolidation': [('decisões arquiteturais', '22', 'decisões'), ('repositórios do DDA', '22', 'repositórios do DDA'),
                      ('aplicações encaixadas nos repositórios', '22', 'aplicações encaixadas'), ('propostas de evolução', '23', 'propostas'),
                      ('fases afetadas pelas propostas', '23', 'fases afetadas')],
}
# Etapas que a página de entrada não mostra como cartão nem no índice (os relatórios continuam gerados e no índice lateral de cada relatório;
# os números delas em NUMEROS continuam valendo)
FORA_DA_ENTRADA = {'06-deterministic-rules', '07-dynamic-analysis'}
CSS_INDICE = """
.fases{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px;margin:10px 0 18px}
.fase{border:1px solid var(--line);border-top:4px solid var(--c);border-radius:8px;background:var(--card);padding:10px 12px;display:flex;flex-direction:column;gap:6px}
.fase h3{margin:0;font-size:15px}.fase h3 a{color:var(--acc);text-decoration:none}.fase h3 a:hover{text-decoration:underline}
.fase .sub{margin:0;font-size:13px}.fase.off{opacity:.55;border-style:dashed}
"""


def num(pasta):
    return pasta.split('-')[0].strip()


def sem_numero(titulo):
    """Título sem o número da fase ("Fase 4b — Resumo..." → "Resumo..."): a página de entrada mostra as fases pelo nome."""
    return re.sub(r'^Fase\s+\S+\s+—\s+', '', titulo)


def recorte(ana):
    """Nome do recorte registrado na configuração da análise (pipeline.config.json na pasta acima da análise), ou None."""
    cfg = ana.parent / 'pipeline.config.json'
    return json.loads(cfg.read_text(encoding='utf-8')).get('recorte') if cfg.exists() else None


def ler(ana):
    """Fases na ordem do índice dos relatórios: (pasta, título do índice, modelo ou None)."""
    out = []
    for pasta, titulo in rr.RELATORIOS:
        if pasta in rr.SO_IA:   # só visão para IA: fora da página de entrada
            continue
        f = ana / pasta / 'ia' / 'report.json'
        m = json.loads(f.read_text(encoding='utf-8')) if f.exists() and (ana / pasta / 'human' / 'report.html').exists() else None
        out.append((pasta, sem_numero(titulo), m))
    return out


def numeros(etapa, fases):
    """Números da etapa tirados do resumo dos relatórios; o que não está no resumo (fase não gerada ou rótulo ausente) fica de fora."""
    resumo = {num(p): {c['label']: c['value'] for c in m.get('summary') or []} for p, _t, m in fases if m}
    out = []
    for rotulo, fase, chave in NUMEROS.get(etapa, []):
        r = resumo.get(fase, {})
        chaves = chave if isinstance(chave, tuple) else (chave,)
        if all(k in r for k in chaves):
            out.append((rotulo, sum(r[k] for k in chaves) if len(chaves) > 1 else r[chaves[0]]))
    return out


def cartao(pasta, titulo, m, cor):
    tipo = rr.origem(pasta) or 'Determinística'
    if m is None:
        return f'<div class="fase off" style="--c:{cor}"><h3>{esc(titulo)}</h3><span class="tag">{esc(tipo)}</span><p class="sub">não gerada nesta análise</p></div>'
    return (f'<div class="fase" style="--c:{cor}"><h3><a href="{quote(pasta)}/human/report.html">{esc(sem_numero(m["title"]))}</a></h3>'
            f'<span class="tag">{esc(tipo)}</span><p class="sub">{esc(m.get("subtitle", ""))}</p></div>')


def pagina(ana):
    fases = ler(ana)
    corpo = ''
    for nome, pergunta, cor in ETAPAS:
        das = [(p, t, m) for p, t, m in fases if ETAPA_DA_FASE.get(num(p)) == nome and p not in FORA_DA_ENTRADA]
        if not das:
            continue
        nums = ''.join(f'<div class="card"><b>{esc(str(v))}</b><span>{esc(k)}</span></div>' for k, v in numeros(nome, fases))
        corpo += (f'<div class="etapa" style="--c:{cor}"><h2 id="etapa-{nome.lower()}">{esc(nome)}</h2><p>{esc(pergunta)}</p></div>'
                  + (f'<div class="cards etapa-nums" style="--c:{cor}">{nums}</div>' if nums else '')
                  + '<div class="fases">' + ''.join(cartao(p, t, m, cor) for p, t, m in das) + '</div>')
    nav = ('<aside id="idx"><h4>Índice</h4><a class="cur" href="#">Visão geral</a><div class="sec">'
           + ''.join(f'<a href="#etapa-{n.lower()}">{esc(n)}</a>' for n, _p, _c in ETAPAS) + '</div>'
           + ''.join(f'<h4>{esc(n)}</h4>' + ''.join(f'<a href="{quote(p)}/human/report.html">{esc(t)}</a>' if m else f'<span class="off">{esc(t)} <small>(não gerado)</small></span>'
                                                  for p, t, m in fases if p not in FORA_DA_ENTRADA and ETAPA_DA_FASE.get(num(p)) == n)
                     for n, _p, _c in ETAPAS)
           + '</aside><div id="rz" title="Arraste para ajustar a largura"></div><button id="tg" type="button" title="Mostrar ou ocultar o índice">☰ índice</button>')
    titulo = f'Análise do recorte {recorte(ana)}' if recorte(ana) else f'Análise {ana.parent.name if ana.name == "analise" else ana.name}'
    sub = ('Números da análise e resumo de cada fase, agrupados pelas etapas do processo: Discovery (o que existe no legado), Reverse (como o legado se '
           'comporta), Modernization (como reorganizar o domínio), Forward (como construir e provar a solução) e Consolidation (o que foi decidido e o '
           'que melhorar no processo).')
    return (f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(titulo)}</title><style>{rr.CSS}{CSS_INDICE}</style></head><body>{nav}<main><h1>{esc(titulo)}</h1>'
            f'<p class="sub">{esc(sub)}</p>{corpo}</main><script>{rr.SCRIPT}</script></body></html>')


def gerar(ana):
    ana = Path(ana)
    (ana / 'index.html').write_text(pagina(ana), encoding='utf-8')
    return ana / 'index.html'


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    print(f'índice gravado em {gerar(sys.argv[1])}')


if __name__ == '__main__':
    main()
