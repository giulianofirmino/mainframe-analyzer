# Certificação

`certification-summary.json` fica `PASS` somente quando nenhum outcome termina em `UNKNOWN_DEPENDENCY`/`UNSUPPORTED`.

Na execução de referência (`example-run/`, 19 programas): 1.142 outcomes; 111 Golden verificados (9,7%); 1.031 `UNKNOWN_DEPENDENCY`; status `FAIL`. Base atual `tcap/codigo` (20 programas .CBL): 1.157 outcomes, 116 Golden (10%), `FAIL` (após as correções de runtime de 29/09 o total se manteve: 2 goldens que dependiam de 'ZEROS' tratado como texto deixaram de existir e 2 novos surgiram) — ver `analises/tcap-codigo/`.

Observação: 234 dos 302 alvos `NEEDS_88_LINEAGE` são, na verdade, condições relacionais abreviadas (`SQLCODE NOT EQUAL ZEROS AND + 100`, `X EQUAL 5 OR 6`) que `cobol_condition_semantics` interpreta como nome de condição.

Principais causas de pendência: 298 alvos dependem de níveis 88 definidos em copybooks ausentes; EVALUATE não passa pelo gerador de testemunhas; caminhos que exigem compor várias decisões ou dados de tabela.

## Simulador (Motor 2)
`simulation_completeness` compara construções encontradas por regex com `runtime_registry`. Atenção: estar no registro não garante execução — `program_runtime` não despacha GETMAIN/FREEMAIN/READQ/WRITEQ/DELETEQ/ASSIGN/ASKTIME/FORMATTIME, apesar de registrados.
