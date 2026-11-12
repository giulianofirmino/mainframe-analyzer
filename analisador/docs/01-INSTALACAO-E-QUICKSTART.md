# Instalação e Quick Start

## Requisitos
Python 3.10+ (somente biblioteca padrão).

## Estrutura
| Caminho | Papel |
|---|---|
| `mainframe-analyzer` | Launcher do pipeline oficial de análise/certificação |
| `tools/certify_from_zero.py` | Orquestrador do pipeline (fases 0–8) |
| `semantic_core/` | Lexer, parser/AST, modelo de dados, runtime COBOL sobre AST, árvore de decisão, regras, lineage, solvers |
| `cli.py` + `*_runtime.py` na raiz | Simulador multi-tecnologia (JCL, CICS, BMS, DB2, VSAM, IMS, MQ) em nível de fixture |
| `tests/` | Smoke tests de ambos os motores |
| `analises/tcap-codigo/` | Saída do pipeline sobre `C:\workspace_act\bradesco-seguros\tcap\codigo` |
| `example-run/` | Saída de referência do pipeline |
| `_descartados/` | Código e docs retirados (ver `_descartados/LEIAME.md`) |

## Pipeline oficial
```bash
./mainframe-analyzer certify /caminho/tcap/codigo saida/
# ou
python3 tools/certify_from_zero.py <pasta-ou-zip-com-.CBL> <pasta-saida>
```
A pasta de saída é apagada e recriada a cada execução.

## Runtime com cenários de entrada/saída (doc 17)
```bash
./mainframe-analyzer modelo /caminho/tcap/codigo entry-points modelos/     # cenários-modelo por entry point
./mainframe-analyzer run    /caminho/tcap/codigo cenarios/tcap saida/      # análise + cenários x análise estática
```

## Simulador multi-tecnologia
```bash
python3 cli.py tests/fixture --scenario tests/scenario.json --out simulacao.json
```

## Testes
```bash
for t in tests/*_smoke.py tests/smoke.py; do python3 "$t" || echo "FALHOU: $t"; done
```
