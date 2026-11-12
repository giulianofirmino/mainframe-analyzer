# Regras de Negócio (pipeline oficial)

## Árvore de decisão (`semantic_core/decision_tree.py`)
Cada IF/EVALUATE vira um nó com `path_context` (decisões ancestrais) e ramos. Os efeitos de cada ramo incluem os parágrafos chamados por PERFORM (expandidos recursivamente); decisões aninhadas são nós separados.

## Classificação do ramo (estrutural, sem usar nomes)
| Classe | Critério |
|---|---|
| BUSINESS | grava dados (INSERT/UPDATE/DELETE, WRITE/REWRITE/DELETE), invoca programa/saída (CALL, LINK, XCTL, SEND MAP, START, PUT CONTAINER) ou lê SQL e altera estado |
| TECHNICAL | só efeitos de runtime (SYNCPOINT, TSQ, GETMAIN, ASKTIME...) |
| FLOW_CONTROL | sem efeito, só roteia para decisões filhas |
| UNKNOWN | só mutações em memória, sem prova de fronteira |

`business_rules_from_tree` publica as BUSINESS como regras e todas as classes em `branch_audit`.

## Limites atuais
- Não distingue validação, mudança de estado, cálculo ou erro.
- Não atravessa programas: efeitos param no LINK/CALL.
- `decision_business_rule_audit` (usado pelo catálogo) classifica BUSINESS_ERROR por palavras (`ERRO`, `COD-RETORNO`...), critério diferente do da árvore.
