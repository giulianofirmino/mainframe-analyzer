# Cenários e Golden Cases (pipeline oficial)

## Catálogo de outcomes
`clean_room_catalog` cria um alvo por ramo de cada IF/EVALUATE com efeito observável:
- `DIRECT_CONSTRAINT`: condição simples sobre variáveis;
- `NEEDS_88_LINEAGE`: condição usa nível 88;
- `EVALUATE_BRANCH`: ramo de EVALUATE.

## Geração dinâmica (somente DIRECT_CONSTRAINT)
1. `business_rule_witness.synthesize` gera valores que satisfazem o ramo.
2. `cobol_ast_runtime` executa o programa com o cenário `{inputs, tables, files}`.
3. Se outro ramo foi atingido por causa de SQL/CICS, `operation_scoped_status_solver.route_status` injeta `db2_status`/`cics_status` na operação.
4. Os que falham vão para `clean_room_path_solver.solve` (first-divergence, profundidade 1, largura 5, até 180 alvos).

## Golden Case
Promovido quando 3 execuções atingem o ramo com o mesmo hash SHA-256 de trace. Os demais ficam `UNKNOWN_DEPENDENCY`.

## Formato de cenário
```json
{"inputs":{"VAR":1},"tables":{},"files":{},
 "db2_status":{"PROG:linha":{"SQLCODE":100}},
 "cics_status":{"PROG:linha":{"EIBRESP":13}},
 "cics_link_outputs":{"PROG:linha":{"CAMPO":"X"}},
 "cics_containers":{"NOME":{"CAMPO":"X"}}}
```
