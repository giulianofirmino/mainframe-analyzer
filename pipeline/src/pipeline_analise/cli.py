"""Comando `pipeline-analise`: roda a análise inteira (fases 0 a 22) em sequência, sem intervenção humana.

  pipeline-analise --ia-cli claude|kiro [--config ARQUIVO] [--ia quando-necessario|sempre|nunca] [--deterministico relatorios|refazer|pular]
                   [--desde ETAPA] [--ate ETAPA] [--sem-testes] [--sem-ambiente]

--ia-cli escolhe a IA que executa os prompts (Claude Code CLI ou Kiro CLI); as duas mostram no console tudo o que fazem.
--apartada PASTA roda numa cópia, refaz todos os prompts e repete cada um até as fases ficarem parecidas com a referência (--limiar, --ciclos).
A configuração (caminhos da análise, das fontes, do código gerado e as opções de cada CLI) vem de --config, da variável PIPELINE_ANALISE_CONFIG
ou de ./pipeline.config.json, nessa ordem."""
import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .execucao import ETAPAS, ORDEM, Pipeline
from .ia import AGENTES


def _config(arg):
    for c in (arg, os.environ.get('PIPELINE_ANALISE_CONFIG'), 'pipeline.config.json'):
        if c and Path(c).is_file():
            return Path(c).resolve()
    raise SystemExit('pipeline.config.json não encontrado: use --config, a variável PIPELINE_ANALISE_CONFIG ou rode na pasta que o contém')


def main(argv=None):
    etapas = '\n'.join(f'  {e:6} {r}' for e, r, _p in ETAPAS)
    a = argparse.ArgumentParser(prog='pipeline-analise', description=__doc__ + '\n\nEtapas:\n' + etapas, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument('--ia-cli', choices=sorted(AGENTES), help='CLI de IA que executa os prompts (obrigatória, salvo com --ia nunca)')
    a.add_argument('--config', help='pipeline.config.json')
    a.add_argument('--ia', choices=('quando-necessario', 'sempre', 'nunca'), default='quando-necessario',
                   help='quando-necessario: refaz só o prompt cuja interpretação não vale mais (padrão); sempre: refaz todos; nunca: só reaproveita')
    a.add_argument('--deterministico', choices=('relatorios', 'refazer', 'pular'), default='relatorios',
                   help='fases 0 a 9: relatorios reaproveita a execução dos cenários (padrão); refazer executa tudo; pular não mexe')
    a.add_argument('--desde', choices=ORDEM, help='começa nesta etapa')
    a.add_argument('--ate', choices=ORDEM, help='termina nesta etapa')
    a.add_argument('--sem-testes', action='store_true', help='fase 21 sem executar os testes (usa os resultados já coletados)')
    a.add_argument('--sem-ambiente', action='store_true', help='fase 21 sem subir o ambiente local (ele já está no ar)')
    g = a.add_argument_group('execução apartada (repete cada prompt até o resultado ficar parecido com a referência)')
    g.add_argument('--apartada', metavar='PASTA', help='roda numa cópia da análise e das interpretações nesta pasta; a referência não muda')
    g.add_argument('--referencia', metavar='PASTA', help='análise de referência para a comparação (padrão: a análise da configuração)')
    g.add_argument('--limiar', type=float, default=0.85, help='semelhança mínima (0 a 1) de cada fase com a referência (padrão 0,85)')
    g.add_argument('--ciclos', type=int, default=5, help='máximo de ciclos por prompt; 0 = sem limite (padrão 5)')
    g.add_argument('--realimentar', action='store_true', help='a cada ciclo, conta à IA onde o resultado anterior divergiu da referência')
    a.add_argument('--version', action='version', version=f'pipeline-analise {__version__}')
    opc = a.parse_args(argv)
    if opc.apartada:
        opc.sem_testes, opc.sem_ambiente = True, True   # a execução apartada não mexe no código gerado nem no ambiente local
        if opc.ia == 'nunca':
            a.error('a execução apartada refaz os prompts: não combine com --ia nunca')
    if opc.ia != 'nunca' and not opc.ia_cli:
        a.error('informe --ia-cli claude ou --ia-cli kiro (ou --ia nunca para só reaproveitar as interpretações)')
    sys.exit(Pipeline(_config(opc.config), opc).executar())


if __name__ == '__main__':
    main()
