# COBOL e Memória (runtime sobre AST)

`semantic_core/cobol_ast_runtime.py` executa a AST com estado em dicionário de variáveis.

## Suportado
MOVE (múltiplos receptores, subscrito, reference modification), INITIALIZE, COMPUTE (esquerda→direita, sem parênteses), ADD/SUBTRACT/MULTIPLY (forma TO/FROM/BY), DIVIDE ... GIVING, SET (88 TO TRUE, UP/DOWN BY), STRING DELIMITED BY SIZE/SPACE, CALL, GOBACK/STOP, CONTINUE/DISPLAY/EXIT, IF, EVALUATE (TRUE ou sujeito), SEARCH, PERFORM parágrafo/THRU e inline UNTIL/VARYING, I/O de arquivo, EXEC SQL e EXEC CICS (LINK, XCTL, RETURN, ASKTIME, FORMATTIME, ASSIGN, GETMAIN, FREEMAIN, READQ, WRITEQ, DELETEQ, GET CONTAINER).

Níveis 88, REDEFINES (alias), OCCURS/ODO e VALUE vêm de `cobol_data_model`.

## Não suportado (gera `UNSUPPORTED_AST_*` ou `RuntimeError`)
GO TO, NEXT SENTENCE, UNSTRING, INSPECT, EVALUATE ALSO, SEARCH ALL, COMPUTE com parênteses, ADD/SUBTRACT ... GIVING.

## Correções de fidelidade (29/09/2026)
- WHENs empilhados (`WHEN A WHEN B <instruções>`) executam o corpo compartilhado; a árvore marca `falls_through_to`.
- O modelo de dados (88, REDEFINES, OCCURS) é do programa em execução e é restaurado ao voltar de CALL/LINK.
- Constantes figurativas (ZEROS, SPACES, LOW/HIGH-VALUES) em VALUE e em MOVE viram o valor que representam.
- Comparação COBOL: numérica quando os dois lados são numéricos; alfanumérica ignorando brancos à direita.
- MOVE para `CAMPO OF GRUPO`; o qualificador só é mantido quando o nome é ambíguo no programa.
- Leitura subscrita de OCCURS com VALUE devolve o valor inicial.
- DB2: FETCH de rowset com menos linhas que as pedidas devolve +100; variável indicadora negativa grava NULL; `:GRUPO.CAMPO` encontra o campo não qualificado.

## Memória
Não há modelo físico de bytes: PIC/COMP-3/COMP não truncam nem codificam valores. Todos os programas de uma execução compartilham o mesmo espaço de nomes de variáveis (não há mapeamento LINKAGE/COMMAREA por posição).

## Chamadas e mocks
`CALL 'X'` e `EXEC CICS LINK/XCTL PROGRAM(var)` resolvem o nome pelo valor da variável. Programa ausente: CALL falha com `PROGRAM_NOT_FOUND`; LINK registra `CICS_EXTERNAL_PROGRAM` e aplica `cics_link_outputs` do cenário. Mocks de programa: `Runtime(programs, mocks={...})` com cenários `when`/`returns`.
