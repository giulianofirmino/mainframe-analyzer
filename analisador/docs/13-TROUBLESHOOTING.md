# Troubleshooting

## `UNSUPPORTED_AST_<VERBO>` / `UNSUPPORTED_AST_EXEC_CICS_<OP>`
Construção sem semântica em `cobol_ast_runtime`. Implemente no runtime e adicione teste em `tests/`.

## `PERFORM_TARGET_NOT_FOUND`
Parágrafo não reconhecido pelo parser (verifique ponto final e formato fixo).

## `PROGRAM_NOT_FOUND`
CALL para programa fora do corpus: forneça o fonte ou um mock.

## `MAX_STEPS`
Laço sem saída no cenário; revise entradas ou aumente `max_steps`.

## `UNSUPPORTED_SQL`
SQL fora do subset de `db2_functional_sql`.

## Resultado não determinístico
Compare traces; relógio e IDs devem vir do cenário.
