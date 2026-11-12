# Arquitetura

O projeto tem **dois motores independentes** que ainda não compartilham código.

## Motor 1 — Pipeline de análise e certificação (oficial)
Entrada: arquivos `*.CBL` (JCL, BMS e copybooks não são lidos).

```text
.CBL -> cobol_token_lexer -> cobol_token_parser (AST da PROCEDURE DIVISION)
     -> Fase 0  program_classifier            -> phase-0-program-classification.json
     -> Estático dependency_map               -> dependency-map.json
                 dclgen_parser (DCLGEN da entrada)  -> dclgen-catalog.json
                 decision_tree (+ business_rules_from_tree)
                                              -> decision-trees.json / business-rules-from-decision-tree.json
                 data_usage (cobol_data_model)-> data-usage.json
                 ast_lineage                  -> data-lineage.json
     -> clean_room_catalog (decision_business_rule_audit + cobol_condition_semantics)
                                              -> catalog.json (1 alvo por ramo)
     -> Dinâmico  business_rule_witness -> cobol_ast_runtime (x3, hash de trace)
                  operation_scoped_status_solver (injeta SQLCODE/EIBRESP)
                  clean_room_path_solver (first-divergence, profundidade 1)
                                              -> goldens.json / outcome-status.json
     -> artifact_renderer                     -> 00..08/{ia,human}
```

`cobol_ast_runtime` estende `cobol_functional_runtime`, usa `cobol_condition_runtime`, `cobol_data_model` (níveis 88, REDEFINES, OCCURS, VALUE), `mainframe_file_runtime` e o DB2 em memória (`db2_functional_sql`, `db2_stateful_runtime`).

## Runtime com cenários (doc 17)
```text
fontes -> copybook_resolver (COPY/INCLUDE + mapa de linhas) -> static_model (AST, árvore, regras, grafo, entry points)
cenário (entrada, tabelas, mocks, saída esperada) -> scenario_runner -> cobol_ast_runtime x3
      -> saída x esperado, caminho x árvore estática, SQL/chamadas x grafo, cobertura
```

## Motor 2 — Simulador multi-tecnologia (linha anterior)
```text
cli.py -> simulation_completeness (construct_ledger + runtime_registry)
       -> simulator.deterministic (3 execuções) -> jcl_runtime -> program_runtime
          -> sql_runtime/db2_*, cics_runtime, bms_runtime, vsam_runtime, ims_runtime, mq_runtime
       -> runtime_state (vars, tabelas, arquivos, filas, trace, commit/rollback)
```
Interpreta COBOL **linha a linha por regex** (MOVE, IF/ELSE, EXEC SQL/CICS, CALL, READ/WRITE/DELETE). Serve para fixtures pequenas; não usa o lexer/AST.

## Direção recomendada
Convergir o Motor 2 para o runtime sobre AST do Motor 1, mantendo os runtimes de JCL/BMS/IMS/MQ como adaptadores.
