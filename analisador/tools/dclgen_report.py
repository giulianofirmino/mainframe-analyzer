#!/usr/bin/env python3
"""Relatório de cobertura do analisador sintático de DCLGEN.

Uso: python3 tools/dclgen_report.py <pasta-de-fontes> [--out dclgen-catalog.json]
Sai com código 0 quando 100% das linhas de todos os DCLGEN foram reconhecidas e
todas as colunas SQL são coerentes com os campos COBOL; 2 caso contrário.
"""
import argparse, json, sys
from pathlib import Path
R = Path(__file__).parents[1]
sys.path.insert(0, str(R / 'semantic_core'))
from dclgen_parser import build_catalog


def main():
    a = argparse.ArgumentParser()
    a.add_argument('root')
    a.add_argument('--out')
    x = a.parse_args()
    cat = build_catalog(x.root)
    print(f"{'membro':10} {'status':6} {'tabela':32} {'col':>4} {'linhas':>6} {'cobert.':>8} {'bytes':>6}")
    for k, r in sorted(cat['members'].items()):
        c = r['coverage']
        print(f"{k:10} {r['status']:6} {str(r['table']):32} {len(r['columns']):4} {c['lines']:6} {c['percent']:7.2f}% {str(r['record_length']):>6}")
        for u in r['unrecognized']:
            print(f"   linha {u['line']}: {u['reason']} :: {u['text'][:80]}")
        for i in r['issues']:
            print(f"   inconsistência: {i}")
    print(json.dumps(cat['summary'], ensure_ascii=False))
    if x.out:
        Path(x.out).write_text(json.dumps(cat, indent=2, ensure_ascii=False), encoding='utf-8')
    raise SystemExit(0 if cat['summary']['status'] == 'PASS' else 2)


if __name__ == '__main__':
    main()
