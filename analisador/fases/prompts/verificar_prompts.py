#!/usr/bin/env python3
"""Confere que cada coluna citada no contrato de entrada dos prompts (linhas `@ler fase=NN bloco="..." colunas="a|b"`) existe no ia/report.json da fase.

  python3 verificar_prompts.py <pasta-da-analise>

`{x}` no nome do bloco vale 'qualquer texto'. O bloco é aceito se o título da tabela (ou, quando ela não tem título, o da seção) começa pelo trecho antes de `{`. Sai com 1 se faltar bloco ou coluna,
para o prompt não ficar desatualizado quando o relatório muda."""
import json
import re
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    ana = Path(sys.argv[1])
    erros, n = [], 0
    for md in sorted(AQUI.glob('prompt-*.md')):
        for linha in re.findall(r'^@ler .*$', md.read_text(encoding='utf-8'), re.M):
            m = re.match(r'@ler fase=(\d\d[a-z]?) bloco="([^"]+)" colunas="([^"]+)"', linha)
            if not m:
                erros.append(f'{md.name}: linha inválida: {linha}')
                continue
            fase, bloco, cols = m.group(1), m.group(2), m.group(3).split('|')
            pastas = sorted(ana.glob(fase + '-*')) or sorted(ana.glob(fase + ' *'))
            if not pastas:
                erros.append(f'{md.name}: fase {fase} sem pasta')
                continue
            rel = json.loads((pastas[0] / 'ia' / 'report.json').read_text(encoding='utf-8'))
            prefixo = bloco.split('{')[0]
            achou = [b for s in rel['sections'] for b in s.get('blocks', []) if b['type'] == 'table' and ((b.get('title') or s['title']).startswith(prefixo))]
            n += 1
            if not achou:
                erros.append(f'{md.name}: fase {fase} sem tabela "{bloco}"')
                continue
            for c in cols:
                if not any(c in b['columns'] for b in achou):
                    erros.append(f'{md.name}: fase {fase} tabela "{bloco}" sem a coluna "{c}"')
    print(f'{n} entradas dos prompts conferidas; {len(erros)} problema(s)')
    for e in erros:
        print('  ' + e)
    sys.exit(1 if erros else 0)


if __name__ == '__main__':
    main()
