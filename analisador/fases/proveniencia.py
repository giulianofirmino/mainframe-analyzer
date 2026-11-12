#!/usr/bin/env python3
"""Proveniência da interpretação de IA: tudo que é texto ou julgamento vem de uma execução de prompt, nunca de edição manual.

registrar:  python3 proveniencia.py registrar <pasta-das-interpretacoes> <prompt 1|2|4|5|6|7|8|9|10|11|12|13|14> <pasta-com-o-arquivo-bruto-da-IA> [--executor TEXTO]
            copia o que a IA devolveu para `bruto/<pasta de interpretação>/` e grava `PROVENIENCIA.json` (hash do prompt, hash do bruto, executor).
verificar:  python3 proveniencia.py verificar <pasta-das-interpretacoes>
            1) o prompt atual é o mesmo (SHA-256) que gerou a interpretação; 2) a interpretação em uso é o bruto da IA ou o bruto só com remoções
            (a poda determinística tira regras fora de escopo, grupos vazios e significados sem uso; nunca escreve texto). Qualquer outra diferença é edição manual.
Códigos de saída: 0 sem problemas, 1 com problemas."""
import hashlib
import json
import shutil
import sys
from pathlib import Path

FASES = Path(__file__).resolve().parent   # os prompts (prompts/) ficam junto deste script; a pasta informada é a das interpretações

PROMPTS = {'1': ('prompts/prompt-1-regras-de-negocio.md', 'interpretacao'), '2': ('prompts/prompt-2-funcionalidades.md', 'interpretacao-fluxos'),
           '4': ('prompts/prompt-4-sequencia-de-funcionalidades.md', 'interpretacao-sequencia'), '5': ('prompts/prompt-5-mapeamento-sql.md', 'interpretacao-sql'),
           '6': ('prompts/prompt-6-telas-e-campos.md', 'interpretacao-interface'),
           '7': ('prompts/prompt-7-modelo-de-dominio.md', 'interpretacao-dominio'),
           '8': ('prompts/prompt-8-chamadas-e-n-mais-1.md', 'interpretacao-relacao'),
           '9': ('prompts/prompt-9-contextos.md', 'interpretacao-contextos'),
           '10': ('prompts/prompt-10-arquitetura-alvo.md', 'interpretacao-arquitetura'),
           '11': ('prompts/prompt-11-contratos.md', 'interpretacao-contratos'),
           '12': ('prompts/prompt-12-implementacao-e-testes.md', 'interpretacao-testes'),
           '13': ('prompts/prompt-13-design-de-interfaces.md', 'interpretacao-design'),
           '14': ('prompts/prompt-14-implementacao.md', 'interpretacao-implementacao')}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def so_remocoes(bruto, atual):
    """True se `atual` é `bruto` apenas com itens removidos (chaves de dicionário, elementos de lista, itens de lista de textos)."""
    if isinstance(bruto, dict) and isinstance(atual, dict):
        return set(atual) <= set(bruto) and all(so_remocoes(bruto[k], atual[k]) for k in atual)
    if isinstance(bruto, list) and isinstance(atual, list):
        i = 0
        for a in atual:
            while i < len(bruto) and not so_remocoes(bruto[i], a):
                i += 1
            if i == len(bruto):
                return False
            i += 1
        return True
    return bruto == atual


def registrar(base, n, origem, executor):
    prompt, pasta = PROMPTS[n]
    dest = base / pasta
    dest.mkdir(parents=True, exist_ok=True)
    (base / 'bruto' / pasta).mkdir(parents=True, exist_ok=True)
    arqs = sorted(Path(origem).glob('*.json'))
    for f in arqs:
        shutil.copyfile(f, base / 'bruto' / pasta / f.name)
    reg = {'prompt': prompt, 'sha256_prompt': sha(FASES / prompt), 'executor': executor, 'arquivos': {f.name: sha(f) for f in arqs}}
    (dest / 'PROVENIENCIA.json').write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding='utf-8')
    print('registrado', pasta, [f.name for f in arqs])


def verificar(base):
    problemas = []
    for n, (prompt, pasta) in PROMPTS.items():
        d = base / pasta
        if not d.exists():
            continue
        pj = d / 'PROVENIENCIA.json'
        if not pj.exists():
            problemas.append(f'{pasta}: sem PROVENIENCIA.json (não se sabe qual prompt gerou a interpretação)')
            continue
        reg = json.loads(pj.read_text(encoding='utf-8'))
        if reg['sha256_prompt'] != sha(FASES / prompt):
            problemas.append(f'{pasta}: o {prompt} mudou depois que a interpretação foi gerada; rode o prompt de novo')
        for nome in reg['arquivos']:
            atual, bruto = d / nome, base / 'bruto' / pasta / nome
            if not atual.exists() or not bruto.exists():
                problemas.append(f'{pasta}/{nome}: arquivo atual ou bruto ausente')
            elif sha(bruto) != reg['arquivos'][nome]:
                problemas.append(f'{pasta}/{nome}: o bruto da IA foi alterado')
            elif not so_remocoes(json.loads(bruto.read_text(encoding='utf-8')), json.loads(atual.read_text(encoding='utf-8'))):
                problemas.append(f'{pasta}/{nome}: difere do que a IA devolveu além de remoções (edição manual: refaça pelo prompt)')
        extra = {f.name for f in d.glob('*.json') if f.name != 'PROVENIENCIA.json'} - set(reg['arquivos'])
        for nome in sorted(extra):
            problemas.append(f'{pasta}/{nome}: arquivo de interpretação sem registro de proveniência')
    for p in problemas:
        print('PROVENIÊNCIA', p)
    print(f'proveniência: {len(problemas)} problema(s)')
    return 1 if problemas else 0


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == 'registrar' and len(a) >= 4:
        ex = a[a.index('--executor') + 1] if '--executor' in a else 'IA isolada (só viu o prompt e as entradas)'
        registrar(Path(a[1]), a[2], a[3], ex)
    elif a and a[0] == 'verificar' and len(a) >= 2:
        sys.exit(verificar(Path(a[1])))
    else:
        raise SystemExit(__doc__)
