# Como estender

1. Garanta que o lexer/parser reconhece a construção (teste em `tests/`).
2. Implemente a semântica em `semantic_core/cobol_ast_runtime.py` (ou no runtime de subsistema).
3. Se afetar regras, ajuste `decision_tree.classify_branch`.
4. Rode todos os testes e o pipeline, e compare a saída com `example-run/`.
5. No simulador (Motor 2), registre `(tecnologia, construção) -> handler` em `runtime_registry.py` **e** faça o despacho em `program_runtime.py`.

Nunca feche um gap só adicionando o nome ao registro.
