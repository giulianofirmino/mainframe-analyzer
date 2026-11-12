# Referência de CLI e Arquivos

## Comandos
```bash
./mainframe-analyzer certify <fontes-ou-zip> [saida]
python3 tools/certify_from_zero.py <fontes-ou-zip> [saida]
python3 cli.py <raiz> --scenario <cenario.json> [--out mainframe-simulation.json]
python3 tools/dclgen_report.py <pasta> [--out dclgen-catalog.json]
python3 tools/run_scenarios.py <fontes> <cenarios> [saida] [--rapido]
python3 tools/run_scenarios.py <fontes> --modelo <PROGRAMA|entry-points> [saida]
```

## Saídas do pipeline
| Arquivo | Conteúdo |
|---|---|
| `phase-0-program-classification.json` | Classe, confiança, recomendação e features por programa |
| `dependency-map.json` | Copybooks, CALL/LINK/XCTL, SQL, tabelas, colunas, CICS, arquivos, `sql_includes` e `dclgen_fields` |
| `dclgen-catalog.json` | DCLGEN: tabelas, colunas, estrutura COBOL, cobertura por linha e ligação com programas |
| `decision-trees.json` | Nós IF/EVALUATE com ramos e efeitos |
| `business-rules-from-decision-tree.json` | Regras BUSINESS + auditoria de todos os ramos |
| `data-usage.json` | Campos declarados vs. usados |
| `decision-map.json` | Mapa de decisão por programa: caixas `Ennn` e decisões `Dnnn` em texto legível |
| `deterministic-rules.json` | Regras determinísticas (validação, tratamento de erro, alteração de estado, roteamento, derivação) com critério, sinais, papel dos campos testados e referências `Dnnn` e `Fnnnn` |
| `data-lineage.json` | Linhagem por campo entre programas: gravações coluna a coluna com origem, chaves, consultas com condições e destinos, áreas entre programas |
| `catalog.json` | Outcomes (1 por ramo) |
| `goldens.json` | Cenários verificados com hash de trace |
| `outcome-status.json` | Status final por outcome |
| `certification-summary.json` | Resumo |
| `00..08/ia/result.json`, `00..08/human/report.html` | Projeções para IA e humanos |

## Módulos de `semantic_core/`
`cobol_token_lexer`, `cobol_token_parser`, `field_lineage`, `report_lineage`, `cobol_data_model`, `cobol_condition_semantics`, `cobol_condition_runtime`, `cobol_functional_runtime`, `cobol_ast_runtime`, `mainframe_file_runtime`, `db2_functional_sql`, `db2_stateful_runtime`, `program_classifier`, `dependency_map`, `decision_tree`, `decision_business_rule_audit`, `data_usage`, `ast_lineage`, `clean_room_catalog`, `business_rule_witness`, `concolic_path_solver`, `operation_scoped_status_solver`, `clean_room_path_solver`, `artifact_renderer`, `dclgen_parser`, `token_utils` (primitivas sobre tokens), `io_deduction` e `io_runtime` (entradas/saídas deduzidas), `copybook_resolver` (COPY/INCLUDE com mapa de linhas), `static_model` (análise estática do runtime), `scenario_runner` (cenários, mocks e validação).

## Reprodução completa
Veja `docs/19-REPRODUCAO-COMPLETA.md` (etapas, prompts 0 a 4, verificações e checklist para outro código).
