#!/usr/bin/env python3
"""Mantém a interpretação (interpretacao/*.json e interpretacao-fluxos/funcionalidades.json) coerente com os relatórios gerados.
Remove dos grupos as regras que a fase 6 deixou fora do escopo de negócio (exceto as da categoria M, permissão de acesso, que o relatório mostra),
apaga grupos que ficaram sem regras e refaz a lista de grupos de cada funcionalidade (só os que alcançam o entry point ou programa dela).
Uso: podar_interpretacao.py <pasta dos relatórios> [--interpretacao PASTA]. Só edita JSON de interpretação; não escreve texto novo."""
import glob
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gerar_simulacao as g  # noqa: E402

BASE = Path(sys.argv[sys.argv.index('--interpretacao') + 1]).resolve() if '--interpretacao' in sys.argv else (
    Path(os.environ['ANALISE_INTERPRETACOES']) if os.environ.get('ANALISE_INTERPRETACOES') else Path(__file__).resolve().parent)


def main():
    g.definir_copybooks(Path(sys.argv[1]))
    d = g.lerRelatorios(Path(sys.argv[1]))
    import gerar_sql as Q   # comandos SQL dinâmicos (mapeamento SQL, fase 10): regras sintéticas `SERVIÇO:Qnn`, também válidas nas regras de negócio
    din = g.regras_dinamicas(Q.carregar_mapeamento(BASE), d['caixas'])
    biz = {r['programa'] + ':' + r['Regra'] for r in d['regras'] + din if r['Escopo'] == 'negócio'}
    mech = {r['programa'] + ':' + r['Regra'] for r in d['regras'] if r['Escopo'] == 'mecanismos implícitos'}
    apagados = []
    for f in sorted(glob.glob(str(BASE / 'interpretacao' / '*.json'))):
        x = json.load(open(f, encoding='utf-8'))
        ch, novos = False, []
        for gr in x.get('grupos', []):
            ok = biz | (mech if gr['cat'] == 'M' else set())
            rs = [r for r in gr['regras'] if r in ok]
            if len(rs) != len(gr['regras']):
                ch = True
                gr['regras'] = rs
                if 'programas' in gr:
                    ps = {r.split(':')[0] for r in rs}
                    gr['programas'] = {k: v for k, v in gr['programas'].items() if k in ps}
            if gr['regras']:
                novos.append(gr)
            else:
                apagados.append(gr['id'])
                ch = True
        ms = []
        for m in x.get('mecanismos', []):   # mecanismo da IA só pode citar regra que a fase 6 deixou no escopo de negócio (o que ficou fora da abrangência já está filtrado)
            rs = [r for r in m['regras'] if r in biz]
            if len(rs) != len(m['regras']):
                ch = True
                m['regras'] = rs
            if m['regras']:
                ms.append(m)
            else:
                apagados.append('mecanismo: ' + m.get('titulo', ''))
                ch = True
        if 'mecanismos' in x:
            x['mecanismos'] = ms
        if ch:
            x['grupos'] = novos
            json.dump(x, open(f, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    _a, _c, grupos, _p = g.carregar_interp()
    ent = {r['programa'] + ':' + r['Regra']: ({e.strip() for e in r['Entry points'].split(',') if e.strip()}, r['programa']) for r in d['regras'] + din}
    reach = {}
    for gr in grupos:
        es, ps = set(), set()
        for r in gr['regras']:
            es |= ent[r][0]
            ps.add(ent[r][1])
        reach[gr['id']] = (es, ps)
    porid = {r['programa'] + ':' + r['Regra']: (r['programa'], r) for r in d['regras'] + din}
    testados = set()
    for gr in grupos:
        testados |= set(g.padroes_decisao([porid[r] for r in gr['regras'] if r in porid], gr.get('campos', ()), gr.get('condicao') == 'exigida'))
    testados_sem = {g.sem_copybook(t).upper() for t in testados}
    for f in sorted(glob.glob(str(BASE / 'interpretacao' / '*.json'))):   # significado de campo que nenhuma regra de negócio testa mais gera erro: sai
        x = json.load(open(f, encoding='utf-8'))
        if 'significados' in x:
            novos_s = [m for m in x['significados'] if g.sem_copybook(m['campo']).upper() in testados_sem]
            if len(novos_s) != len(x['significados']):
                x['significados'] = novos_s
                json.dump(x, open(f, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    ff = BASE / 'interpretacao-fluxos' / 'funcionalidades.json'
    if not ff.exists():   # a interpretação das funcionalidades (prompt 2) ainda não foi feita
        print('grupos apagados:', apagados or 'nenhum')
        return
    y = json.load(open(ff, encoding='utf-8'))
    for fu in y['funcionalidades']:
        e = fu.get('entry') or fu.get('programa')
        keep = [q for q in fu['grupos'] if q in reach and (e in reach[q][0] or e in reach[q][1])]
        fu['grupos'] = keep
    json.dump(y, open(ff, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('grupos apagados:', apagados or 'nenhum')


if __name__ == '__main__':
    main()
