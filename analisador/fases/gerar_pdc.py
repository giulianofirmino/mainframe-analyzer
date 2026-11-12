#!/usr/bin/env python3
"""Relatório pdc-mapping (fase 14, determinística): processos PDC (arquivos XML) -> ação -> transação -> programa mainframe analisado, e o que foi executado.

  python3 gerar_pdc.py <pasta-da-analise> [pasta-de-saida] --pdc <pasta-dos-xml>   (padrão da saída: a pasta da análise)

Saída: <saida>/14 - pdc-mapping/human/report.html e <saida>/14 - pdc-mapping/ia/report.json (o mesmo modelo de visão das outras fases).

Entradas: os XML do PDC (cada <processo> traz o nome do processo, o corpo com o controle FWO e, em laço, o controle Loop, as ações <acao> e as transações <transacao>) e os relatórios
das fases 0, 1, 2 e 7 da análise (classe e situação de execução dos programas, copybooks incluídos por programa, entry points e cenários). Nenhuma IA: mesma entrada, mesma saída.

Correlação transação -> programa analisado, em dois critérios, nesta ordem:
  1. nome: a transação tem o mesmo nome de um programa analisado;
  2. layout: a transação trafega um layout (código de 8 posições dos registros da transação, por exemplo AAAAWWWS) que o programa analisado inclui por COPY (fase 2).
A situação do programa vem da fase 1 (executado / só mock / não executado)."""
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
import xml.etree.ElementTree as ET

import gerar_simulacao as S
import report_model as rm  # noqa: E402
import report_resumo as rs  # noqa: E402
from cores import COR_CLASSE  # noqa: E402

FASE = '14 - pdc-mapping'
EXEC, MOCK, NAO = 'executado', 'só mock', 'não executado'
NUM = re.compile(r'-?\d+(\s*,\s*-?\d+)*')


def dec(t):
    """O PDC grava corpo, entrada, saída e fontes como lista de bytes em decimal (com sinal, como o Java); o resto é texto."""
    t = (t or '').strip()
    if t and NUM.fullmatch(t):
        return bytes(int(x) & 255 for x in t.split(',')).decode('utf-8', 'replace')
    return t


def ler_pdc(pasta):
    """Uma entrada por <processo> com nome: {nome, versao, arquivo, acoes [nome], acao_tx, acao_laco, transacao, tipo, layouts}."""
    procs = []
    arquivos = sorted(Path(pasta).glob('*.xml'))
    if not arquivos:
        raise SystemExit(f'nenhum arquivo .xml em {pasta}')
    for f in arquivos:
        raiz = ET.parse(f).getroot()
        for p in raiz.iter('processo'):
            nome = (p.findtext('nome') or '').strip()
            if not nome:
                continue
            corpo = dec(p.findtext('corpo'))
            controles = re.findall(r'<control\b[^>]*type="([^"]*)"[^>]*>\s*<action>([^<]*)</action>', corpo)
            acoes = [(a.findtext('nome') or '').strip() for a in p.iterfind('acoes/acao')]
            trans = [((t.findtext('nome') or '').strip(), (t.findtext('tipo') or '').strip(), dec(t.findtext('fonte'))) for t in p.iterfind('transacoes/transacao')]
            fwo = re.findall(r'<FWO-transaction>([^<]*)<', corpo)
            tx = [a for tp, a in controles if tp != 'Loop'] or [a for a in acoes if '.Tx' in a]
            laco = [a for tp, a in controles if tp == 'Loop'] or [a for a in acoes if '.Lp' in a]
            for tn, tipo, fonte in trans or [(fwo[0] if fwo else '', '', '')]:
                lay = set(re.findall(r'register name="([A-Z0-9#@$]{8})-', fonte)) | set(re.findall(r'COD-LAYOUT"[^>]*value="([A-Z0-9#@$]{8})"', fonte))
                procs.append({'nome': nome, 'versao': (p.findtext('versao') or '').strip(), 'arquivo': f.name, 'acao_tx': ', '.join(sorted(set(tx))), 'acao_laco': ', '.join(sorted(set(laco))),
                              'acoes': acoes, 'transacao': tn, 'tipo': tipo, 'layouts': sorted(lay)})
    return procs, len(arquivos)


def ler_analise(ana):
    f0, f1, f2, f7 = S.fase(ana, '00-'), S.fase(ana, '01-'), S.fase(ana, '02-'), S.fase(ana, '07-')
    classe, sit, motivo, copy, ep = {}, {}, {}, defaultdict(set), {}
    ler_analise.chamadas = defaultdict(set)
    for _s, bt, rows in S.tabelas(f0):
        if bt == 'Programas':
            classe.update({r['Programa']: r['Classe'] for r in rows})
    for _s, bt, rows in S.tabelas(f1):
        if bt == 'Todas as chamadas':
            for r in rows:
                ler_analise.chamadas[r['Programa chamador']].add(r['Programa chamado'])
        if bt.startswith('Programas: chamados'):
            for r in rows:
                classe.setdefault(r['Programa'], r['Classe'])
                st = r['Situação']
                sit[r['Programa']] = EXEC if st == 'executado' else MOCK if st.startswith('chamado só como mock') else NAO
                motivo[r['Programa']] = r['Motivo']
    for _s, bt, rows in S.tabelas(f2):
        if bt.startswith('Copybooks: usados ou não'):
            for r in rows:
                for p in [x.strip() for x in r['Programas que o incluem'].split(',') if x.strip()]:
                    copy[r['Copybook'].strip()].add(p)
    for _s, bt, rows in S.tabelas(f7):
        if bt == 'Entry points':
            ep = {r['Entry point']: r for r in rows}
    return classe, sit, motivo, copy, ep


def correlacionar(procs, classe, copy):
    """{transação: [(programa, critério, layouts em comum)]}."""
    por_prog = defaultdict(set)
    for cb, ps in copy.items():
        for p in ps:
            por_prog[p].add(cb)
    out = {}
    for t in sorted({p['transacao'] for p in procs if p['transacao']}):
        lay = {l for p in procs if p['transacao'] == t for l in p['layouts']}
        achou = []
        if t in classe:
            achou.append((t, 'nome', []))
        for prog in sorted(por_prog):
            comum = sorted(lay & por_prog[prog])
            if comum and prog != t:
                achou.append((prog, 'layout', comum))
        out[t] = achou
    return out


def modelo(procs, n_arq, classe, sit, motivo, copy, ep, corr, pdc_pasta):
    distintos = sorted({p['nome'] for p in procs})
    transacoes = sorted({p['transacao'] for p in procs if p['transacao']})
    acoes = {a for p in procs for a in p['acoes']}
    prog_de = {t: sorted({x[0] for x in corr[t]}) for t in transacoes}
    sit_t = {}
    for t in transacoes:
        ss = [sit.get(x, NAO) for x in prog_de[t]]
        sit_t[t] = '—' if not ss else EXEC if EXEC in ss else MOCK if MOCK in ss else NAO
    correl = [t for t in transacoes if prog_de[t]]
    # processo distinto -> linhas (processo, transação)
    pares = defaultdict(lambda: {'arqs': set(), 'tx': set(), 'laco': set(), 'versoes': set()})
    for p in procs:
        k = (p['nome'], p['transacao'])
        pares[k]['arqs'].add(p['arquivo'])
        pares[k]['versoes'].add(p['versao'])
        if p['acao_tx']:
            pares[k]['tx'].add(p['acao_tx'])
        if p['acao_laco']:
            pares[k]['laco'].add(p['acao_laco'])

    def lista(xs, n=3):
        xs = sorted(xs)
        return ', '.join(xs[:n]) + (f' (+{len(xs) - n})' if len(xs) > n else '')

    def progtxt(t):
        return ', '.join(prog_de[t]) or '—'

    cards = [rm.card('arquivos XML', n_arq), rm.card('processos (entradas)', len(procs)), rm.card('processos distintos', len(distintos)), rm.card('ações', len(acoes)),
             rm.card('transações (programas PDC)', len(transacoes)), rm.card('com programa analisado', len(correl)),
             rm.card('executadas na análise dinâmica', sum(1 for t in correl if sit_t[t] == EXEC))]
    secs = []
    n_dir = sum(1 for t in transacoes if any(c == 'nome' for _p, c, _l in corr[t]))
    n_lay = sum(1 for t in transacoes if any(c == 'layout' for _p, c, _l in corr[t]))
    secs.append(rm.S('cobertura', 'Cobertura', [
        rm.X(f'{n_arq} arquivos XML lidos em {Path(pdc_pasta).name}; {len(procs)} processos (o mesmo processo aparece em várias versões e arquivos), {len(distintos)} processos distintos, '
             f'{len(acoes)} ações e {len(transacoes)} transações. Cada processo tem uma transação FWO (o programa mainframe que o PDC executa) e uma ação Tx; os processos com laço (Loop) têm também uma ação de laço. '
             f'Correlação com os programas analisados: {n_dir} transação(ões) com o mesmo nome de um programa; {n_lay} por layout (copybook que a transação trafega e o programa inclui); '
             f'{len(transacoes) - len(correl)} fora da análise (o programa da transação não está entre os fontes analisados; ver "Processos fora da análise").'),
        rm.T('Resumo', ['Indicador', 'Valor'], [('arquivos XML', n_arq), ('processos (entradas)', len(procs)), ('processos distintos', len(distintos)), ('ações distintas', len(acoes)),
                                               ('transações distintas', len(transacoes)), ('transações com o mesmo nome de programa analisado', n_dir), ('transações correlacionadas por layout', n_lay),
                                               ('transações com programa analisado', len(correl)), ('com programa executado na análise dinâmica', sum(1 for t in correl if sit_t[t] == EXEC)),
                                               ('com programa só mock', sum(1 for t in correl if sit_t[t] == MOCK)), ('com programa não executado', sum(1 for t in correl if sit_t[t] == NAO)),
                                               ('transações fora da análise', len(transacoes) - len(correl)),
                                               ('processos fora da análise', len({p['nome'] for p in procs if p['transacao'] and not prog_de[p['transacao']]}))])],
        'Leitura determinística dos XML do PDC e dos relatórios das fases 0, 1, 2 e 7.'))
    secs.append(rm.S('processos', 'Processos, ações e transações', [
        rm.T('Processos distintos: ação, transação (programa) e programa analisado', ['Processo', 'Ação (Tx)', 'Ação de laço (Loop)', 'Transação (programa PDC)', 'Versões', 'Arquivos', 'Programa analisado', 'Execução'],
             [(k[0], lista(v['tx'], 2), lista(v['laco'], 2), k[1], len(v['versoes']), lista(v['arqs']), progtxt(k[1]), sit_t.get(k[1], '—')) for k, v in sorted(pares.items())])],
        'Uma linha por processo e transação. Versões: quantas versões do processo existem nos XML; Arquivos: onde ele aparece.'))
    lin = []
    for t in transacoes:
        ps = sorted({p['nome'] for p in procs if p['transacao'] == t})
        ac = sorted({a for p in procs if p['transacao'] == t for a in p['acoes']})
        lay = sorted({l for p in procs if p['transacao'] == t for l in p['layouts']})
        crit = '; '.join(f'{pg}: {c}' + (f' ({", ".join(l)})' if l else '') for pg, c, l in corr[t]) or '—'
        lin.append((t, len(ps), lista(ps, 2), lista(ac, 2), ', '.join(lay) or '—', progtxt(t), crit, sit_t[t]))
    secs.append(rm.S('transacoes', 'Transações e programas analisados', [
        rm.T('Transação PDC, processos, ações, layouts e programa analisado', ['Transação', 'Processos', 'Exemplos de processo', 'Ações', 'Layouts', 'Programa analisado', 'Critério da correlação', 'Execução'], lin)],
        'Execução = situação do programa analisado na fase 1: executado, só mock (chamado só como destino de chamada simulada) ou não executado; "—" quando nenhum programa analisado corresponde à transação.'))
    # por programa analisado
    inv = defaultdict(list)
    for t in transacoes:
        for pg, c, l in corr[t]:
            inv[pg].append(t)
    alcance = defaultdict(set)   # programa -> programas com transação PDC que o alcançam pelas chamadas (fase 1)
    for raiz in inv:
        vis, pilha = {raiz}, [raiz]
        while pilha:
            x = pilha.pop()
            for y in ler_analise.chamadas.get(x, ()):
                if y not in vis:
                    vis.add(y)
                    pilha.append(y)
        for y in vis - {raiz}:
            alcance[y].add(raiz)
    prog_rows = []
    for pg in sorted(classe):
        ts = sorted(inv.get(pg, []))
        ps = sorted({p['nome'] for p in procs if p['transacao'] in ts})
        ac = sorted({a for p in procs if p['transacao'] in ts for a in p['acoes']})
        e = ep.get(pg)
        prog_rows.append((pg, classe.get(pg, ''), sit.get(pg, NAO), (e['Cenários'] if e else '—'), ', '.join(ts) or '—', len(ps), lista(ps, 3) or '—', lista(ac, 3) or '—', ', '.join(sorted(alcance.get(pg, []))) or '—'))
    secs.append(rm.S('programas', 'Programas analisados e o PDC', [
        rm.T('Programas analisados: situação na execução e transações, processos e ações do PDC', ['Programa', 'Classe', 'Situação na execução', 'Cenários (entry point)', 'Transações PDC', 'Processos', 'Exemplos de processo', 'Ações', 'Alcançado (chamadas) a partir de'], prog_rows),
        rm.T('Resumo por situação', ['Grupo', 'Programas'],
             [('Executados, com transação PDC (entrada direta)', ', '.join(r[0] for r in prog_rows if r[2] == EXEC and r[4] != '—') or '—'),
              ('Executados, sem transação PDC, alcançados por programa que tem', ', '.join(r[0] for r in prog_rows if r[2] == EXEC and r[4] == '—' and r[8] != '—') or '—'),
              ('Executados e sem relação com o PDC', ', '.join(r[0] for r in prog_rows if r[2] == EXEC and r[4] == '—' and r[8] == '—') or '—'),
              ('Só mock', ', '.join(r[0] + (' (PDC)' if r[4] != '—' else '') for r in prog_rows if r[2] == MOCK) or '—'),
              ('Não executados', ', '.join(r[0] + (' (PDC)' if r[4] != '—' else '') for r in prog_rows if r[2] == NAO) or '—')])],
        'Todos os programas das fases 0 e 1, com o que o PDC chama deles.'))
    # diagrama
    nos, ares, vistos = [], [], set()
    sel = [(k, v) for k, v in sorted(pares.items()) if prog_de.get(k[1])]
    for (proc, t), v in sel:
        for pid, col, lab, sub, det, cor, ina in (('p-' + proc, 0, proc, 'processo', proc, rs.NEUTRA, False),
                                                  ('a-' + (lista(v['tx'], 1) or '—'), 1, (lista(v['tx'], 1) or '—').split('.')[-1], 'ação', lista(v['tx'], 1), rs.NEUTRA, False),
                                                  ('t-' + t, 2, t, 'transação', t, rs.NEUTRA, False)):
            if pid not in vistos:
                vistos.add(pid)
                nos.append({'id': pid, 'col': col, 'label': lab, 'sub': sub, 'detail': det, 'cor': cor, 'inactive': ina})
        a_id = 'a-' + (lista(v['tx'], 1) or '—')
        ares += [{'from': 'p-' + proc, 'to': a_id}, {'from': a_id, 'to': 't-' + t}]
        for pg in prog_de[t]:
            gid = 'g-' + pg
            if gid not in vistos:
                vistos.add(gid)
                nos.append({'id': gid, 'col': 3, 'label': pg, 'sub': f'{classe.get(pg, "")} · {sit.get(pg, NAO)}', 'detail': f'programa {pg} ({classe.get(pg, "")}): {sit.get(pg, NAO)}',
                            'cor': COR_CLASSE.get(classe.get(pg, ''), rs.NEUTRA), 'inactive': sit.get(pg, NAO) != EXEC})
            ares.append({'from': 't-' + t, 'to': gid})
    ares = [{'from': f, 'to': t} for f, t in sorted({(a['from'], a['to']) for a in ares})]
    g = rs._grafo('Processo PDC → ação → transação → programa analisado', ['Processo', 'Ação', 'Transação', 'Programa analisado'], nos, ares,
                  'Só as transações com programa analisado. Borda do programa = classe (azul coordenador, verde funcional, laranja corporativo, vermelho infraestrutura). '
                  'Cinza tracejado: o programa não foi executado de verdade pela análise dinâmica (não chamado ou só mock).', nw=230)
    tb = [(a['from'][2:], a['to'][2:]) for a in ares]
    secs.append(rm.S('diagrama', 'Diagrama: do processo ao programa', [g, rm.T('Tabela do diagrama: ligações', ['De', 'Para'], tb)],
                     'Processos PDC cujas transações correspondem a programas analisados, até o programa e se ele foi executado.'))
    lay_de = {t: ', '.join(sorted({l for p in procs if p['transacao'] == t for l in p['layouts']})) or '—' for t in transacoes}
    fora = [(k[0], lista(v['tx'], 2) or '—', lista(v['laco'], 2) or '—', k[1], lay_de[k[1]], len(v['versoes']), lista(v['arqs']))
            for k, v in sorted(pares.items(), key=lambda kv: (kv[0][1] or '', kv[0][0])) if k[1] and not prog_de[k[1]]]
    secs.append(rm.S('fora-da-analise', 'Processos fora da análise', [
        rm.T('Processo, ação e transação fora da análise', ['Processo', 'Ação (Tx)', 'Ação de laço (Loop)', 'Transação (programa PDC)', 'Layouts', 'Versões', 'Arquivos'], fora,
             note=f'{len(fora)} linhas: {len({x[0] for x in fora})} processos distintos em {len(transacoes) - len(correl)} transações (um processo com mais de uma '
                  'transação aparece uma vez por transação), ordenadas pela transação. O programa que atende a transação não está entre '
                  'os fontes analisados: nenhum programa analisado tem o nome da transação nem inclui os layouts que ela trafega.')],
        'Mapeamento processo → ação → transação do que o PDC executa e ficou fora da análise.'))
    secs.append(rm.S('criterio', 'Critério da correlação', [
        rm.X('A transação FWO do PDC é o identificador da transação mainframe; o programa que a atende é achado por (1) mesmo nome ou (2) layout em comum: os registros da transação (TCAPWxxx) são os copybooks que o programa inclui por COPY. '
             'Quando o nome da transação não coincide com nenhum programa e o layout não é incluído por nenhum programa analisado, a transação fica sem correlação. '
             'Um layout incluído por mais de um programa correlaciona a transação a todos eles (coordenador e funcional); a coluna Critério mostra o layout.')],
        'Como o PDC foi ligado às fases anteriores.'))
    return rm.model('Processos PDC', 'Do XML do PDC (processo, ação, transação) aos programas mapeados nas fases anteriores, com o que a análise dinâmica executou.', cards, secs)


def main():
    args = sys.argv[1:]
    if '--pdc' not in args or len(args) < 3:
        sys.exit(__doc__)
    i = args.index('--pdc')
    pdc = Path(args[i + 1])
    del args[i:i + 2]
    ana = Path(args[0])
    saida = Path(args[1]) if len(args) > 1 else ana
    S.definir_copybooks(ana)
    procs, n_arq = ler_pdc(pdc)
    classe, sit, motivo, copy, ep = ler_analise(ana)
    corr = correlacionar(procs, classe, copy)
    mod = modelo(procs, n_arq, classe, sit, motivo, copy, ep, corr, pdc)
    S.escrever(saida, FASE, mod)
    print(f'{n_arq} arquivos, {len(procs)} processos, {len(corr)} transações, {sum(1 for v in corr.values() if v)} com programa analisado')


if __name__ == '__main__':
    main()
