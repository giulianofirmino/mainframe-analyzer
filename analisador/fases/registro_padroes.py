#!/usr/bin/env python3
"""Registros de padrões das fases de design das interfaces e de implementação: diretrizes e convenções com exemplos ancorados no código e uma
verificação automática de conformidade sobre o repositório.

O bloco "fora" do registro (motivo, módulos, arquivos…) tira do relatório e das verificações o que não faz parte do recorte. Cada item do registro tem id, categoria, título, regra (texto), origem (ADRs e fases de onde vem), exemplos (raiz + arquivo + âncora + papel, a
âncora é procurada no arquivo e recusa o registro se não existir) e, opcionalmente, verificacao. Tipos de verificação (globs relativos à raiz):
  conteudo   {"arquivos", "deve_conter" | "nao_deve_conter", "apos"?}  cada arquivo contém (ou não) a expressão, no texto todo ou depois do marcador "apos"
  linhas     {"arquivos", "seleciona", "formato"}                      toda linha que casa com "seleciona" segue "formato"
  par        {"arquivos", "de", "para"}                                 para cada arquivo existe o par com "de" trocado por "para" no nome
  estrutura  {"modulos", "pastas"}                                      cada módulo (pasta) tem todas as pastas (globs) da lista
O resultado é (conformes, total, não conformes); total zero é falha (a verificação não achou o que verificar)."""
import re
from pathlib import Path

import gerar_enhancement_proposals as EP
import report_model as rm

TIPOS = ('conteudo', 'linhas', 'par', 'estrutura')


def _ler(p):
    try:
        return p.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        return p.read_text(encoding='latin-1')


def _arquivos(base, padrao, excluir=()):
    fora = {q for g in excluir for q in Path(base).glob(g)}
    return sorted(p for p in Path(base).glob(padrao) if p.is_file() and p not in fora and not any(x in ('node_modules', 'target', '.git', 'dist') for x in p.parts))


def verificar(v, ana, projeto, excluir=()):
    """Aplica a verificação, sem os arquivos que casam com os globs de excluir (o que o registro deixa fora); devolve (conformes, total, [não conformes])."""
    base = EP.raiz(v.get('raiz'), ana, projeto)
    _arquivos_ = lambda b, g: _arquivos(b, g, excluir)   # noqa: E731
    rel = lambda p: p.relative_to(base).as_posix()   # noqa: E731
    tipo = v['tipo']
    if tipo == 'conteudo':
        arqs = _arquivos_(base, v['arquivos'])
        ruins = []
        for p in arqs:
            t = _ler(p)
            if v.get('apos'):
                i = t.find(v['apos'])
                t = t[i:] if i >= 0 else ''
            achou = re.search(v.get('deve_conter') or v.get('nao_deve_conter'), t, re.M) is not None
            if achou != bool(v.get('deve_conter')):
                ruins.append(rel(p))
        return len(arqs) - len(ruins), len(arqs), ruins
    if tipo == 'linhas':
        sel, fmt, tot, ruins = re.compile(v['seleciona']), re.compile(v['formato']), 0, []
        for p in _arquivos_(base, v['arquivos']):
            for n, l in enumerate(_ler(p).splitlines(), 1):
                if sel.search(l):
                    tot += 1
                    if not fmt.search(l):
                        ruins.append(f'{rel(p)}:{n}')
        return tot - len(ruins), tot, ruins
    if tipo == 'par':
        arqs = _arquivos_(base, v['arquivos'])
        ruins = [rel(p) for p in arqs if not (p.parent / p.name.replace(v['de'], v['para'], 1)).exists()]
        return len(arqs) - len(ruins), len(arqs), ruins
    if tipo == 'estrutura':
        fora = {q for g in excluir for q in Path(base).glob(g)}
        mods = sorted(p for p in Path(base).glob(v['modulos']) if p.is_dir() and p not in fora)
        ruins = [f'{rel(m)}: falta {g}' for m in mods for g in v['pastas'] if not any(x.is_dir() for x in m.glob(g))]
        maus = {r.split(':')[0] for r in ruins}
        return len(mods) - len(maus), len(mods), ruins
    raise ValueError(f'tipo de verificação desconhecido: {tipo}')


def validar(itens, ana, projeto, erros, prefixo, excluir=()):
    """Confere ids únicos, campos obrigatórios, tipo de verificação e âncoras dos exemplos; devolve, por item, (exemplos localizados, resultado)."""
    vistos, out = set(), {}
    for it in itens:
        k = it.get('id', '?')
        if k in vistos:
            erros.append(f'{prefixo} {k}: id repetido')
        vistos.add(k)
        for c in ('id', 'categoria', 'titulo', 'regra', 'exemplos'):
            if not it.get(c):
                erros.append(f'{prefixo} {k}: sem {c}')
        exs = []
        for r in it.get('exemplos', []):
            loc = EP.localizar(r, ana, projeto, f'{prefixo} {k}', erros)
            if loc:
                ls = EP.linhas(EP.raiz(r.get('raiz'), ana, projeto) / r['arquivo'])
                ini = max(0, loc[1] - 3)
                contexto = '\n'.join(f'{ini + i + 1:>5}  {l}' for i, l in enumerate(ls[ini:loc[1] + 4]))   # a linha da âncora com o entorno
                exs.append((*loc, r.get('papel', ''), contexto))
        res = None
        v = it.get('verificacao')
        if v:
            if v.get('tipo') not in TIPOS:
                erros.append(f'{prefixo} {k}: verificação de tipo {v.get("tipo")!r} fora de {TIPOS}')
            else:
                res = verificar(v, ana, projeto, excluir)
                if res[1] == 0:
                    erros.append(f'{prefixo} {k}: a verificação não achou nada para verificar ({v.get("arquivos") or v.get("modulos")})')
        out[k] = (exs, res)
    return out


def descrever(v):
    if not v:
        return 'sem verificação automática (diretriz de revisão)'
    alvo = v.get('arquivos') or v.get('modulos')
    if v['tipo'] == 'conteudo':
        return f'{alvo}: ' + (f'contém /{v["deve_conter"]}/' if v.get('deve_conter') else f'não contém /{v["nao_deve_conter"]}/') + \
            (f' depois de "{v["apos"]}"' if v.get('apos') else '')
    if v['tipo'] == 'linhas':
        return f'{alvo}: toda linha com /{v["seleciona"]}/ segue /{v["formato"]}/'
    if v['tipo'] == 'par':
        return f'{alvo}: cada arquivo tem o par {v["de"]} → {v["para"]}'
    return f'{alvo}: tem ' + ', '.join(v['pastas'])


def _conformidade(res):
    if not res:
        return '—'
    ok, tot, _ruins = res
    return f'{ok} de {tot}' + (' (conforme)' if ok == tot else ' (fora da regra)')


def secoes(itens, achados, rotulo, sec_id, fase, fase_adr='22 - architecture-decision-records'):
    """O registro item a item: uma seção de índice (uma linha por item, com link para ele) e uma seção por item, com a regra, a ficha (categoria,
    origem, verificação e conformidade, com a regra na primeira linha), os exemplos no código (trecho com o entorno) e o que está fora da regra."""
    indice, marcas = [], []
    for it in itens:
        _exs, res = achados.get(it['id'], ([], None))
        indice.append((rm.with_links('', [rm.link(it['id'], fase, it['id'].lower())]), it['titulo'], it['categoria'], _conformidade(res)))
        marcas.append(bool(res and res[0] != res[1]))
    out = [rm.S(sec_id, rotulo, [rm.T(rotulo, ['Id', 'Título', 'Categoria', 'Conformidade no repositório'], indice, marks=marcas,
                                      note='Cada item tem a sua seção logo abaixo (e no índice lateral). Conformidade calculada no repositório a cada geração; '
                                           'linha destacada = algo fora da regra. Item sem verificação automática é conferido na revisão.')])]
    for it in itens:
        exs, res = achados.get(it['id'], ([], None))
        origem = it.get('origem') or {}
        orig = rm.with_links(', '.join(origem.get('fases', [])) or '', [rm.link(a, fase_adr, a.lower()) for a in origem.get('adrs', [])]) if origem else '—'
        blocos = [rm.T(f'{it["id"]} · ficha', ['Campo', 'Conteúdo'], [('Regra', it['regra']), ('Categoria', it['categoria']), ('Origem', orig),
                                                                      ('Verificação automática', descrever(it.get('verificacao'))),
                                                                      ('Conformidade no repositório', _conformidade(res))])]
        for arq, ln, _trecho, papel, contexto in exs:
            blocos.append(rm.COD(contexto, f'Exemplo: {arq}:{ln}' + (f' · {papel}' if papel else '')))
        if res and res[2]:
            blocos.append(rm.T(f'{it["id"]} · fora da regra', ['Arquivo (ou arquivo:linha)'], [(x,) for x in res[2]]))
        out.append(rm.S(it['id'].lower(), f'{it["id"]} · {it["titulo"]}', blocos))
    return out


def resumo_conformidade(achados):
    verif = [r for _e, r in achados.values() if r]
    return len(achados), len(verif), sum(1 for r in verif if r[0] == r[1])
