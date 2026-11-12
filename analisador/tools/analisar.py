#!/usr/bin/env python3
"""Roda a análise completa e grava tudo numa pasta, para poder repetir à mão e conferir que o resultado é o mesmo.

  python3 tools/analisar.py <pasta-dos-fontes> <pasta-dos-cenarios> <pasta-de-saida> [--cache PASTA] [--comparar PASTA-DE-REFERENCIA] [--simulacao-ia PASTA-DA-INTERPRETACAO | --sem-ia]

Etapas (todas por script, sem intervenção): pipeline de análise (fases 0 a 9), execução dos cenários, cobertura por
entry point, motivo dos ramos sem cobertura e relatórios de todas as fases (human/report.html e ia/report.json).
Saída: as pastas das fases na raiz, o material de execução em runtime/, e MANIFESTO.json com o SHA-256 de cada arquivo.
O hash ignora o caminho absoluto da pasta de fontes (que muda de máquina para máquina), então duas execuções em
computadores diferentes geram o mesmo MANIFESTO quando o resultado é o mesmo. --comparar lista o que difere."""
import argparse
import os
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[1]
TEXT = {'.json', '.html', '.md', '.txt', '.log', '.jsonl', '.cbl', '.CBL'}


def _norm(data, root):
    txt = data.decode('utf-8', errors='replace')
    for v in {str(root), str(root).replace('\\', '/'), str(root).replace('/', '\\'), str(root).replace('\\', '\\\\')}:
        txt = txt.replace(v, '<FONTES>')
    return txt.encode('utf-8')


def manifesto(pasta, fontes):
    pasta, out = Path(pasta), {}
    root = Path(fontes).resolve()
    for f in sorted(pasta.rglob('*')):
        if f.is_file() and f.name != 'MANIFESTO.json':
            b = f.read_bytes()
            if f.suffix in TEXT:
                b = _norm(b, root)
            out[f.relative_to(pasta).as_posix()] = hashlib.sha256(b).hexdigest()
    return out


def _podar(ia, saida):
    """Mantém a interpretação coerente com os relatórios recém-gerados (regras que a fase 6 deixou fora do escopo ou fora da abrangência, grupos vazios, significados sem uso): só edita a pasta da interpretação."""
    subprocess.run([sys.executable, str(R / 'fases' / 'podar_interpretacao.py'), str(saida), '--interpretacao', str(ia)])


def main():
    a = argparse.ArgumentParser()
    a.add_argument('fontes')
    a.add_argument('cenarios')
    a.add_argument('saida')
    a.add_argument('--cache', help='pasta de cache dos cenários (padrão: <saida>.cache, ao lado da pasta de saída; permite retomar uma rodada interrompida)')
    a.add_argument('--comparar')
    a.add_argument('--simulacao-ia', help='pasta das interpretações (interpretacao/*.json, interpretacao-fluxos/...; os geradores e prompts ficam em fases/): gera, em <saida>/10 - sql-mapping, <saida>/11 - business-rules, <saida>/12 - business-flows e <saida>/13 - traceability (human/report.html e ia/report.json), os relatórios de regras de negócio e de fluxos de negócio por entry point, que usam só os relatórios gerados e a interpretação de IA dessa pasta')
    a.add_argument('--config', help='analise.config.json do projeto (padrão: <cenarios>/analise.config.json): prefixo do core business, campos de infraestrutura, SQLCODE de negócio e categorias de mecanismo; ver semantic_core/projeto_config.py')
    a.add_argument('--prefixo-core', help='prefixo dos programas do core business: programa sem ele só pode ser CORPORATIVO ou INFRAESTRUTURA na classificação (fase 0); sem a opção a classificação não usa nomes')
    a.add_argument('--sem-ia', action='store_true', help='não gera os relatórios de IA (fases 10, 11, 12 e 13)')
    a.add_argument('--so-relatorios', action='store_true', help='não refaz a análise nem os cenários: só regenera os relatórios (fases 0 a 9, e 10 a 12 de IA) e o MANIFESTO sobre uma pasta de saída já existente')
    x = a.parse_args()
    cfg_path = Path(x.config) if x.config else Path(x.cenarios) / 'analise.config.json'
    if cfg_path.is_file():
        os.environ['ANALISE_CONFIG'] = str(cfg_path.resolve())   # lido pelo classificador e pelos geradores (os subprocessos herdam)
        if not x.prefixo_core:
            x.prefixo_core = json.loads(cfg_path.read_text(encoding='utf-8')).get('prefixo_core') or None
    if x.prefixo_core:
        os.environ['ANALISE_PREFIXO_CORE'] = x.prefixo_core   # lido pelo classificador (os subprocessos herdam)
    if not x.cache:
        x.cache = str(Path(x.saida).resolve().with_name(Path(x.saida).resolve().name + '.cache'))
    padrao_ia = R.parent / 'analises' / 'simulacao-ia'
    if not x.simulacao_ia and not x.sem_ia and padrao_ia.exists():
        x.simulacao_ia = str(padrao_ia)   # análise completa em um comando: fases 0 a 9 e os relatórios de IA (10 a 12) a partir da interpretação versionada
    saida, tmp = Path(x.saida), Path(x.saida).with_name(Path(x.saida).name + '.tmp')
    if x.so_relatorios:
        if not (saida / 'runtime' / 'runtime-validation.json').exists():
            raise SystemExit('--so-relatorios precisa de uma pasta de saída já gerada por uma análise completa')
        sys.path.insert(0, str(R / 'tools'))
        import gerar_relatorios
        gerar_relatorios.gerar(str(saida), str(saida / 'runtime'))
        rc_ia = 0
        if x.simulacao_ia:
            ia = Path(x.simulacao_ia).resolve()
            _podar(ia, saida)
            for script in ('gerar_sql.py', 'gerar_simulacao.py', 'gerar_fluxos.py', 'gerar_sequencia.py'):
                rc_ia = rc_ia or subprocess.run([sys.executable, str(R / 'fases' / script), str(saida), str(saida), '--interpretacao', str(ia)],
                                            env=dict(os.environ, ANALISE_INTERPRETACOES=str(ia))).returncode
        sys.path.insert(0, str(R / 'semantic_core'))
        import report_render
        print(f'{report_render.ligar(saida)} referências cruzadas ligadas entre os relatórios')
        import gerar_indice
        print(f'índice das fases gravado em {gerar_indice.gerar(saida)}')
        man = manifesto(saida, x.fontes)
        (saida / 'MANIFESTO.json').write_text(json.dumps({'arquivos': man}, indent=1, sort_keys=True), encoding='utf-8')
        print(f'{len(man)} arquivos; relatórios regenerados e MANIFESTO.json gravado em {saida}')
        raise SystemExit(rc_ia)
    for d in (saida, tmp):
        if d.exists():
            shutil.rmtree(d)
    cmd = [sys.executable, str(R / 'tools' / 'run_scenarios.py'), x.fontes, x.cenarios, str(tmp)] + (['--cache', x.cache] if x.cache else [])
    p = subprocess.run(cmd)
    if not (tmp / 'runtime-validation.json').exists():
        raise SystemExit('a execução dos cenários não terminou')
    saida.mkdir(parents=True)
    (saida / 'runtime').mkdir()
    for f in sorted(tmp.iterdir()):
        if f.name == 'analise':
            for g in sorted(f.iterdir()):
                shutil.move(str(g), str(saida / g.name))
        else:
            shutil.move(str(f), str(saida / 'runtime' / f.name))
    shutil.rmtree(tmp, ignore_errors=True)
    rc_ia = 0
    if x.simulacao_ia:
        ia = Path(x.simulacao_ia).resolve()
        _podar(ia, saida)
        for script in ('gerar_sql.py', 'gerar_simulacao.py', 'gerar_fluxos.py', 'gerar_sequencia.py'):
            rc_ia = rc_ia or subprocess.run([sys.executable, str(R / 'fases' / script), str(saida), str(saida), '--interpretacao', str(ia)],
                                        env=dict(os.environ, ANALISE_INTERPRETACOES=str(ia))).returncode
    if x.simulacao_ia:
        rc_ia = rc_ia or subprocess.run([sys.executable, str(R / 'fases' / 'prompts' / 'verificar_prompts.py'), str(saida)]).returncode
    sys.path.insert(0, str(R / 'semantic_core'))
    import report_render
    print(f'{report_render.ligar(saida)} referências cruzadas ligadas entre os relatórios')
    sys.path.insert(0, str(R / 'tools'))
    import gerar_indice
    print(f'índice das fases gravado em {gerar_indice.gerar(saida)}')
    man = manifesto(saida, x.fontes)
    (saida / 'MANIFESTO.json').write_text(json.dumps({'arquivos': man}, indent=1, sort_keys=True), encoding='utf-8')
    print(f'{len(man)} arquivos; MANIFESTO.json gravado em {saida}')
    rc = p.returncode or rc_ia
    if x.comparar:
        ref = json.loads((Path(x.comparar) / 'MANIFESTO.json').read_text(encoding='utf-8'))['arquivos']
        dif = sorted(k for k in set(ref) | set(man) if ref.get(k) != man.get(k))
        print(f'comparação com {x.comparar}: {len(dif)} arquivo(s) diferente(s)' if dif else f'comparação com {x.comparar}: IDÊNTICO ({len(man)} arquivos)')
        for k in dif[:40]:
            print('  ', k)
        rc = rc or (1 if dif else 0)
    raise SystemExit(rc)


if __name__ == '__main__':
    main()
