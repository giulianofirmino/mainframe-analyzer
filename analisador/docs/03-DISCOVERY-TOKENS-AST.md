# Discovery, Tokens e AST

## Descoberta
`tools/certify_from_zero.py` coleta `*.CBL`/`*.cbl` recursivamente e remove duplicatas por sha256. Membros DCLGEN são descobertos por conteúdo e analisados por `dclgen_parser` (ver doc 16). Copybooks comuns, JCL e BMS não são lidos pelo pipeline.

## Lexer (`semantic_core/cobol_token_lexer.py`)
- Formato fixo: colunas 1–6 ignoradas, coluna 7 indicador (`*` e `/` = comentário), área 8–72.
- Comentários `*>`.
- Tokens `KEYWORD`, `IDENT`, `NUMBER`, `STRING`, `SYMBOL`, `PERIOD`, `EOF`, cada um com `line`, `column`, `offset`.
- Limitações: continuação de literal (indicador `-`) não é concatenada; `COPY` não é expandido.

## Parser (`semantic_core/cobol_token_parser.py`)
Gera AST somente da **PROCEDURE DIVISION**: `LABEL` (seção/parágrafo), `IF`, `EVALUATE`/`WHEN`, `PERFORM` (inline/UNTIL/VARYING e fora de linha/THRU), `SEARCH`, `FILE_*` (OPEN/CLOSE/READ/WRITE/REWRITE/DELETE/START com AT END/INVALID KEY), `EXEC_SQL`, `EXEC_CICS` e comandos simples com `args` textuais.

## Data Division (`semantic_core/cobol_data_model.py`)
Lê itens de nível, PIC, USAGE, VALUE, OCCURS/DEPENDING, INDEXED BY, REDEFINES, 66/RENAMES e 88, a partir dos tokens.

## Tokens nos nós da AST
O parser guarda em cada nó os tokens que consumiu, como tuplas `(tipo, valor, linha, coluna)`:
`arg_tokens` (comandos simples e I/O de arquivo), `condition_tokens` (IF e WHEN), `subject_tokens` (EVALUATE/SEARCH), `header_tokens` (PERFORM) e `tokens` (EXEC SQL e EXEC CICS). O AST também traz `program_id`. `token_utils.py` reúne as primitivas sobre esses tokens (parênteses, divisão por palavra, nome qualificado, opções de EXEC CICS, tabelas de EXEC SQL, nomes que o léxico parte como `I#FRWKGE`, hospedeiro e indicador do INTO em `sql_host_pairs`, e o cabeçalho do PERFORM em `perform_spec`: destino, THRU, TIMES, UNTIL, VARYING/AFTER e WITH TEST). `sql_aggregate` avalia MAX/MIN/COUNT/SUM/AVG a partir dos tokens do SELECT.

Módulos que já trabalham só sobre tokens: `io_deduction`, `io_runtime`, `static_model` (chamadas, SQL, LINKAGE, PROGRAM-ID), `copybook_resolver` (COPY e EXEC SQL INCLUDE), `dclgen_parser` (código e comentários do DCLGEN) e a leitura de nomes escritos nos cenários (`CAMPO OF GRUPO`).

Ainda leem o texto achatado dos comandos com regex, e são o próximo passo da mesma regra: `cobol_functional_runtime`, `cobol_ast_runtime`, `db2_functional_sql`, `db2_stateful_runtime`, `cobol_condition_runtime`, `cobol_condition_semantics`, `ast_lineage`, `decision_tree`, `dependency_map` (SQL/CICS), `business_rule_witness`, `cobol_data_model` (PIC/VALUE) e `program_classifier`.

## Invariante
Nova semântica COBOL entra pelo token stream/AST, nunca por split de linha.
