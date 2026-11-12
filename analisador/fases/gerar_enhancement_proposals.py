#!/usr/bin/env python3
"""Relatório enhancement-proposals (fase 23): propostas de melhoria do processo de análise e de modernização, levantadas ao longo do recorte.

  python3 gerar_enhancement_proposals.py <pasta-da-analise> [pasta-de-saida] --projeto <repositório> [--interpretacao PASTA]
  (padrão da saída: a pasta da análise; da interpretação: a pasta deste script)

As propostas vêm de `interpretacao-ep/ep.json` (registro do dono da arquitetura, não é saída de IA), no formato das enhancement proposals:
motivação, proposta, exemplos (antes e depois), impacto nas fases, riscos e o que fica de fora. Cada exemplo pode citar linhas dos fontes
(`fontes`: raiz + arquivo + âncora; a raiz é 'projeto' ou uma pasta do pipeline.config.json da análise, como fontes ou aplicacao) e, quando a
proposta se apoia numa decisão, a ADR da fase 22. Um exemplo pode ter ainda um diagrama, uma tabela ou a detecção do dono de tabelas DB2: quem grava e quem
lê cada tabela nos EXEC SQL dos fontes e quem a mantém pelo PDC (fase 14) sem programa no recorte, com a recomendação calculada (migrar só quando apenas o
recorte grava). Uma âncora que não existe, uma ADR que não está no registro ou uma recomendação calculada diferente da registrada recusam o relatório.
Saída: <saida>/23 - enhancement-proposals/human/report.html e <saida>/23 - enhancement-proposals/ia/report.json."""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import gerar_simulacao as S
import report_model as rm  # noqa: E402

FASE = '23 - enhancement-proposals'
FASE_ADR = '22 - architecture-decision-records'
INTERP, INTERP_ADR = 'interpretacao-ep', 'interpretacao-adr'
ESTADOS = ('Proposta', 'Aceita', 'Implementada', 'Recusada')
COR = {'tela': '#0072B2', 'servico': '#1E8E3E', 'dado': '#555555', 'evento': '#7B3FA0', 'alta': '#D55E00', 'leitor': '#8a6d00'}
GRAVA = re.compile(r'^(INSERT\s+INTO|UPDATE|DELETE\s+FROM|MERGE\s+INTO)\s+(?:\w+\.)?(\w+)', re.I)


def raiz(nome, ana, projeto):
    """Pasta-base de um arquivo citado: 'projeto' (o repositório) ou uma pasta do pipeline.config.json da análise."""
    if nome in (None, 'projeto'):
        return Path(projeto)
    cfg = Path(ana).resolve().parent / 'pipeline.config.json'
    pastas = json.loads(cfg.read_text(encoding='utf-8')) if cfg.exists() else {}
    if nome not in pastas:
        raise SystemExit(f'registro de propostas recusado: pasta "{nome}" não está em {cfg}')
    return (cfg.parent / pastas[nome]).resolve()


def linhas(p):
    b = p.read_bytes()
    try:
        return b.decode('utf-8').splitlines()
    except UnicodeDecodeError:
        return b.decode('latin-1').splitlines()


def localizar(ref, ana, projeto, quem, erros):
    """(arquivo exibido a partir da pasta que contém o repositório, linha, trecho) da primeira linha com a âncora."""
    p = raiz(ref.get('raiz'), ana, projeto) / ref['arquivo']
    ls = linhas(p) if p.exists() else []
    n = next((i for i, l in enumerate(ls) if ref['ancora'] in l), None)
    if n is None:
        erros.append(f'{quem}: âncora não encontrada em {ref["arquivo"]}: {ref["ancora"]}')
        return None
    try:
        exib = p.resolve().relative_to(Path(projeto).resolve().parent).as_posix()
    except ValueError:
        exib = p.as_posix()
    return exib, n + 1, ls[n].strip()[:160]


def lado(titulo, x):
    """Um lado do exemplo (antes ou depois): texto, SQL ou código."""
    if not x:
        return []
    out = []
    if x.get('texto'):
        out.append(rm.X(x['texto'], titulo))
        titulo = None
    if x.get('sql'):
        out.append(rm.SQL(x['sql'], titulo))
    elif x.get('codigo'):
        out.append(rm.COD(x['codigo'], titulo))
    return out


def acessos_sql(pastas):
    """Por tabela: {programa: operações de gravação} e {programa} que só leem, varrendo os EXEC SQL dos fontes COBOL (colunas 7 a 72, sem comentários)."""
    grava, le = defaultdict(lambda: defaultdict(set)), defaultdict(set)
    for pasta in pastas:
        for f in sorted(Path(pasta).glob('*.[Cc][Bb][Ll]')):
            txt = ' '.join(l[6:72] for l in linhas(f) if len(l) > 6 and l[6] not in '*/')
            for m in re.finditer(r'EXEC\s+SQL(.*?)END-EXEC', txt, re.S | re.I):
                cmd = ' '.join(m.group(1).split())
                g = GRAVA.match(cmd)
                if g:
                    grava[g.group(2).upper()][f.stem.upper()].add(g.group(1).split()[0].upper())
                elif re.match(r'(SELECT|DECLARE)\b', cmd, re.I):
                    for t in re.findall(r'(?:FROM|JOIN|,)\s+(?:\w+\.)?([A-Z]\w+)', cmd, re.I):
                        le[t.upper()].add(f.stem.upper())
    return grava, le


def processos_pdc(ana):
    """Linhas da tabela de processos da fase 14: (processo, transação, programa analisado)."""
    p = Path(ana) / '14 - pdc-mapping' / 'ia' / 'report.json'
    if not p.exists():
        return []
    out = []

    def txt(x):
        return x.get('text') if isinstance(x, dict) else x

    def anda(o):
        if isinstance(o, dict):
            if str(o.get('title') or '').startswith('Processos distintos'):
                out.extend((txt(r[0]), txt(r[3]), txt(r[6])) for r in o['rows'])
            for v in o.values():
                anda(v)
        elif isinstance(o, list):
            for v in o:
                anda(v)
    anda(json.loads(p.read_text(encoding='utf-8')))
    return out


def deteccao(k, n, dx, ana, projeto, erros, titulo=None):
    """Detecção do dono de cada tabela: quem grava e quem lê nos fontes analisados e quem mantém a tabela pelo PDC sem programa no recorte;
    a recomendação sai do cálculo: só o recorte grava → migrar; outro contexto grava → não migrar; ninguém conhecido grava → não migrar até achar o dono."""
    pastas = []
    for x in dx['raizes']:
        p = raiz(x.get('raiz'), ana, projeto) / x['pasta']
        if not p.is_dir():
            erros.append(f'{k} exemplo {n}: pasta de fontes não existe: {x["pasta"]}')
        pastas.append(p)
    grava, le = acessos_sql(pastas)
    pdc = processos_pdc(ana)
    linhas_t = []
    for t in dx['tabelas']:
        nome = t['tabela'].upper()
        gr = grava.get(nome, {})
        fora = [(pr, tr) for pr, tr, prog in pdc if t.get('processos_pdc') and re.search(t['processos_pdc'], pr or '') and prog in (None, '', '—')]
        if t.get('dono_externo'):   # dono registrado fora do recorte (por exemplo, sistema corporativo), sem processo no PDC deste sistema
            fora.append((f'dono registrado: {t["dono_externo"]}', 'outro sistema'))
        if gr and not fora:
            rec = 'Migrar: só programas do recorte gravam'
        elif gr and fora:
            rec = 'Não migrar: gravada dentro e fora do recorte'
        elif fora:
            rec = 'Não migrar: o dono é outro contexto'
        else:
            rec = 'Não migrar: nenhum gravador conhecido (dono a descobrir)'
        if t.get('recomendacao_esperada') and not rec.startswith(t['recomendacao_esperada']):
            erros.append(f'{k} exemplo {n}: {nome} calculada como "{rec}", registrada como "{t["recomendacao_esperada"]}"')
        linhas_t.append((nome, t['contexto'], ', '.join(f'{p} ({"/".join(sorted(o))})' for p, o in sorted(gr.items())) or '—',
                         ', '.join(sorted(le.get(nome, set()) - set(gr))) or '—',
                         '; '.join(f'{pr} ({tr})' for pr, tr in fora[:6]) + (f' e mais {len(fora) - 6}' if len(fora) > 6 else '') if fora else '—',
                         rec, t.get('observacao', '')))
    return rm.T(titulo or f'{k} · exemplo {n}: detecção do dono de cada tabela', ['Tabela', 'Contexto dono', 'Programas do recorte que gravam', 'Programas que só leem',
                                                                       'Manutenção fora do recorte (PDC, sem programa analisado)', 'Recomendação', 'Observação'], linhas_t,
                note=dx.get('nota'))


def diagrama(k, n, dg):
    g = rm.G(f'{k} · exemplo {n}: {dg["titulo"]}', dg['nos'], dg['arestas'], kind='colunas', note=dg.get('nota'))
    g['columns'] = [{'name': c, 'color': COR.get(cor, cor)} for c, cor in dg['colunas']]
    g['nw'] = dg.get('largura', 200)
    return g


def secao(ep, ana, projeto, adrs, erros):
    k = ep['id']
    if ep['status'] not in ESTADOS:
        erros.append(f'{k}: status "{ep["status"]}" fora de {ESTADOS}')
    falta = [a for a in ep.get('adrs', []) if a not in adrs]
    if falta:
        erros.append(f'{k}: ADR inexistente no registro: {", ".join(falta)}')
    ficha = rm.T(f'{k} · ficha', ['Campo', 'Conteúdo'], [
        ('Título', ep['titulo']), ('Status', ep['status']), ('Data', ep['data']), ('Área', ep['area']), ('Origem', ep['origem']),
        ('Decisões relacionadas', rm.with_links(', '.join(ep['adrs']), [rm.link(a, FASE_ADR, a.lower()) for a in ep['adrs']]) if ep.get('adrs') else '—'),
        ('Fases afetadas', ', '.join(i['fase'] for i in ep['impacto']))])
    blocos = [ficha, rm.X(ep['resumo'], 'Resumo'), rm.X(ep['motivacao'], 'Motivação'),
              rm.T(f'{k} · objetivos', ['Objetivo'], [(o,) for o in ep['objetivos']]),
              rm.T(f'{k} · fora do escopo', ['O que esta proposta não faz'], [(o,) for o in ep['nao_objetivos']]) if ep.get('nao_objetivos') else None,
              rm.X(ep['proposta'], 'Proposta')]
    blocos = [b for b in blocos if b]
    for n, ex in enumerate(ep.get('exemplos', []), 1):
        refs = []
        for r in ex.get('fontes', []):
            loc = localizar(r, ana, projeto, f'{k} exemplo {n}', erros)
            if loc:
                refs.append((loc[0], loc[1], loc[2], r['papel']))
        blocos.append(rm.X(ex['descricao'], f'{k} · exemplo {n}: {ex["titulo"]}'))
        if ex.get('deteccao'):
            blocos.append(deteccao(k, n, ex['deteccao'], ana, projeto, erros))
        if ex.get('diagrama'):
            blocos.append(diagrama(k, n, ex['diagrama']))
        if ex.get('tabela'):
            tb = ex['tabela']
            blocos.append(rm.T(f'{k} · exemplo {n}: {tb["titulo"]}', tb['colunas'], [tuple(l) for l in tb['linhas']], note=tb.get('nota')))
        blocos += lado('Antes', ex.get('antes')) + lado('Depois (proposto)', ex.get('depois'))
        if refs:
            blocos.append(rm.T(f'{k} · exemplo {n}: onde aparece', ['Arquivo', 'Linha', 'Trecho', 'O que mostra'], refs))
    blocos.append(rm.T(f'{k} · impacto nas fases', ['Fase', 'O que muda'], [(i['fase'], i['mudanca']) for i in ep['impacto']]))
    blocos.append(rm.T(f'{k} · riscos e cuidados', ['Risco', 'Como tratar'], [(r['risco'], r['tratamento']) for r in ep['riscos']]))
    return rm.S(k.lower(), f'{k} · {ep["titulo"]}', blocos)


def main():
    args = sys.argv[1:]
    opc = {}
    for nome in ('--interpretacao', '--projeto'):
        if nome in args:
            i = args.index(nome)
            opc[nome] = Path(args[i + 1]).resolve()
            del args[i:i + 2]
    if not args or '--projeto' not in opc:
        sys.exit(__doc__)
    base = opc.get('--interpretacao', S.BASE)
    ana = Path(args[0])
    saida = Path(args[1]) if len(args) > 1 else ana
    reg = json.loads((Path(base) / INTERP / 'ep.json').read_text(encoding='utf-8'))
    adr = Path(base) / INTERP_ADR / 'adr.json'
    adrs = {a['id'] for a in json.loads(adr.read_text(encoding='utf-8'))['adrs']} if adr.exists() else set()
    projeto, eps, erros = opc['--projeto'], reg['propostas'], []
    secoes = [secao(ep, ana, projeto, adrs, erros) for ep in eps]
    if erros:
        raise SystemExit('registro de propostas recusado:\n  ' + '\n  '.join(erros))
    indice = rm.S('indice', 'Propostas registradas', [
        rm.T('Propostas de Evolução', ['Proposta', 'Título', 'Área', 'Status', 'Data', 'Fases afetadas'],
             [(rm.with_links('', [rm.link(ep['id'], FASE, ep['id'].lower())]), ep['titulo'], ep['area'], ep['status'], ep['data'],
               ', '.join(i['fase'].split(' - ')[0] for i in ep['impacto'])) for ep in eps], ids=['indice-' + ep['id'].lower() for ep in eps]),
        rm.X(reg['descricao'], 'Como ler')])
    fases = sorted({i['fase'] for ep in eps for i in ep['impacto']})
    mapa = rm.S('mapa', 'Fases afetadas por proposta', [rm.T('Fase × proposta', ['Fase'] + [ep['id'] for ep in eps],
             [(f,) + tuple('●' if any(i['fase'] == f for i in ep['impacto']) else '' for ep in eps) for f in fases],
             note='● = a proposta muda a fase.')])
    cards = [rm.card('propostas', len(eps))] + [rm.card(s.lower(), sum(1 for ep in eps if ep['status'] == s)) for s in ESTADOS if any(ep['status'] == s for ep in eps)] + \
            [rm.card('exemplos', sum(len(ep.get('exemplos', [])) for ep in eps)), rm.card('fases afetadas', len(fases))]
    rep = rm.model('Propostas de Evolução', f'Propostas de melhoria do processo de análise e de modernização, levantadas no recorte de {projeto.name}', cards,
                   [indice] + secoes + [mapa, rm.S('criterio', 'Como o registro foi montado', [rm.X(
                       'As propostas vêm do registro do dono da arquitetura (interpretacao-ep/ep.json), não de IA. Uma proposta descreve uma mudança no processo '
                       '(como os recortes são feitos, o que as fases analisam, o que o analisador verifica); quando ela é aceita e muda a arquitetura alvo, a decisão '
                       'vai para a fase 22 como ADR. Os exemplos citam linhas dos fontes, conferidas a cada geração; uma âncora que não existe, uma ADR que não está '
                       'no registro ou um status fora de ' + ', '.join(ESTADOS) + ' recusam o relatório.')])])
    S.escrever(saida, FASE, rep)
    print(f'{len(eps)} propostas; {sum(len(ep.get("exemplos", [])) for ep in eps)} exemplos; {len(fases)} fases afetadas')


if __name__ == '__main__':
    main()
