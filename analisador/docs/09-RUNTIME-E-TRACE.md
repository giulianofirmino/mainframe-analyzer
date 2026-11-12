# Runtime determinístico e Trace
`runtime_state.py` mantém vars, DB2, arquivos, IMS, filas, trace e snapshots.
## Transações
`begin`, `commit`, `rollback`.
## Determinismo
O trace possui hash SHA-256 sobre representação JSON estável. A suíte integrada repete a execução e exige o mesmo resultado/hash.
## Evidência
Eventos de trace servem como evidência de execução e podem resolver construções cujo comando concreto só é conhecido em runtime.
