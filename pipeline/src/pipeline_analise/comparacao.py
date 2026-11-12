"""Semelhança entre dois relatórios da mesma fase (ia/report.json): o de referência e o de uma execução apartada.

A nota (0 a 1) junta três medidas, com peso:
  indicadores (30%)  cada indicador do topo (summary) com o mesmo rótulo: 1 - |a - b| / max(a, b) para números (e frações "a/b"), igualdade para texto;
                     indicador que falta em um dos lados vale 0;
  estrutura (30%)    semelhança (Jaccard) dos ids das seções e dos títulos das tabelas;
  conteúdo (40%)     para cada tabela com o mesmo título nos dois relatórios: razão entre as quantidades de linhas e semelhança (Jaccard) dos valores
                     da primeira coluna; média das tabelas.
As diferenças mais relevantes vão em `diferencas`, para o registro da execução (e, com --realimentar, para a IA)."""
import json
import re
from pathlib import Path

PESOS = {'indicadores': 0.3, 'estrutura': 0.3, 'conteudo': 0.4}


def _texto(c):
    if isinstance(c, dict):
        return str(c.get('text') or ', '.join(str(l.get('text', '')) for l in c.get('links', []) if isinstance(l, dict)))
    return '' if c is None else str(c)


def _numero(v):
    if isinstance(v, (int, float)):
        return float(v)
    m = re.fullmatch(r'\s*(-?\d+(?:[.,]\d+)?)\s*(?:/\s*(\d+(?:[.,]\d+)?))?\s*', str(v))
    if not m:
        return None
    a = float(m.group(1).replace(',', '.'))
    return a / float(m.group(2).replace(',', '.')) if m.group(2) and float(m.group(2).replace(',', '.')) else a


def _jaccard(a, b):
    a, b = set(a), set(b)
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def _tabelas(rel):
    out = {}
    for s in rel.get('sections', []):
        for b in s.get('blocks', []):
            if b.get('type') == 'table':
                out.setdefault(b.get('title') or s.get('title') or '', b)
    return out


def similaridade(ref, novo):
    dif = []
    # indicadores
    ri = {c['label']: c['value'] for c in ref.get('summary', [])}
    ni = {c['label']: c['value'] for c in novo.get('summary', [])}
    notas = []
    for rot in sorted(set(ri) | set(ni)):
        if rot not in ri or rot not in ni:
            notas.append(0.0)
            dif.append(f'indicador «{rot}» só {"na referência" if rot in ri else "na execução"}')
            continue
        a, b = _numero(ri[rot]), _numero(ni[rot])
        if a is None or b is None:
            n = 1.0 if str(ri[rot]) == str(ni[rot]) else 0.0
        else:
            n = 1.0 if a == b else 1 - abs(a - b) / max(abs(a), abs(b))
        notas.append(n)
        if n < 1:
            dif.append(f'indicador «{rot}»: referência {ri[rot]}, execução {ni[rot]}')
    indicadores = sum(notas) / len(notas) if notas else 1.0
    # estrutura
    rs, ns = [s['id'] for s in ref.get('sections', [])], [s['id'] for s in novo.get('sections', [])]
    rt, nt = _tabelas(ref), _tabelas(novo)
    estrutura = (_jaccard(rs, ns) + _jaccard(rt, nt)) / 2
    for x in sorted(set(rs) - set(ns))[:10]:
        dif.append(f'seção «{x}» só na referência')
    for x in sorted(set(ns) - set(rs))[:10]:
        dif.append(f'seção «{x}» só na execução')
    for x in sorted(set(rt) - set(nt))[:10]:
        dif.append(f'tabela «{x}» só na referência')
    # conteúdo
    notas = []
    for titulo in sorted(set(rt) & set(nt)):
        a, b = rt[titulo]['rows'], nt[titulo]['rows']
        qtd = 1.0 if len(a) == len(b) else min(len(a), len(b)) / max(len(a), len(b))
        chaves = _jaccard((_texto(r[0]) for r in a if r), (_texto(r[0]) for r in b if r))
        notas.append((qtd + chaves) / 2)
        if qtd < 0.9 or chaves < 0.8:
            dif.append(f'tabela «{titulo}»: {len(a)} linhas na referência, {len(b)} na execução; primeira coluna {chaves:.0%} igual')
    conteudo = sum(notas) / len(notas) if notas else 0.0
    nota = PESOS['indicadores'] * indicadores + PESOS['estrutura'] * estrutura + PESOS['conteudo'] * conteudo
    return {'nota': round(nota, 4), 'indicadores': round(indicadores, 4), 'estrutura': round(estrutura, 4), 'conteudo': round(conteudo, 4), 'diferencas': dif[:40]}


def pasta_fase(analise, n):
    ps = sorted(Path(analise).glob(f'{n}-*')) or sorted(Path(analise).glob(f'{n} *'))
    return ps[0] if ps else None


def comparar_fase(referencia, analise, n):
    pr, pn = pasta_fase(referencia, n), pasta_fase(analise, n)
    if not pr or not (pr / 'ia' / 'report.json').exists():
        return None
    if not pn or not (pn / 'ia' / 'report.json').exists():
        return {'nota': 0.0, 'indicadores': 0.0, 'estrutura': 0.0, 'conteudo': 0.0, 'diferencas': ['fase não gerada na execução']}
    ler = lambda p: json.loads((p / 'ia' / 'report.json').read_text(encoding='utf-8'))   # noqa: E731
    return similaridade(ler(pr), ler(pn))
