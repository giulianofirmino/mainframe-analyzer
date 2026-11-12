# Runtime com cenários x análise estática

Permite informar **entrada e saída esperada** para um entry point, executar o fluxo real sobre a AST (com mocks para o que não se quer executar) e validar o caminho percorrido contra a análise estática.

## Execução
```bash
./mainframe-analyzer run    <fontes> <cenarios> [saida] [--rapido]
./mainframe-analyzer modelo <fontes> [PROGRAMA|entry-points] [saida]
# equivalentes:
python3 tools/run_scenarios.py <fontes> <cenarios> [saida] [--rapido] [--execucoes 3]
python3 tools/run_scenarios.py <fontes> --modelo entry-points [saida]
```
Toda execução refaz a análise a partir dos fontes (nada é reaproveitado):
1. `saida/analise/`: pipeline completo (`certify_from_zero`), igual ao `certify` (pule com `--rapido`);
2. `saida/static/`: análise estática usada na comparação, com COPY/INCLUDE expandidos (`expanded/*.CBL`) e `static-model.json` (entry points, grafo de chamadas com destino resolvido por VALUE, decisões, SQL, LINKAGE);
3. `saida/cenarios/<nome>/`: `result.json`, `trace.log` (legível) e `trace.jsonl` de cada cenário;
4. `saida/runtime-validation.json` e `saida/runtime-validation/{ia,human}`: consolidado e cobertura.

Código de saída 0 somente se todos os cenários passam.

## Formato do cenário (`*.json`; um cenário por arquivo ou `{"scenarios": [...]}`)
```json
{
  "name": "TCAP1PWL consulta inicial com 2 planos",
  "entry_point": "TCAP1PWL",
  "inputs": {"EIBCALEN": 100, "FRWKWAAA-SOLIC-MAIS-DADOS": "I"},
  "tables": {"DB2PRD.TPLANO_CAPTZ": [{"NPLANO_CAPTZ": 10, "CPLANO_CAPTZ": 501}]},
  "mock_policy": "infra_and_external",
  "mocks": {
    "FRWK1200": {"returns": {"FRWKEL04-COD-RETORNO": 0}},
    "GCOR1910": {"scenarios": [{"when": {"GCORW910-E-TIPO-PESQUISA": "D"}, "returns": {"GCORW910-COD-RETORNO": 0}}],
                 "default": {"returns": {"GCORW910-COD-RETORNO": 8}}}
  },
  "execute": [],
  "db2_status": {"TCAP3PWL:313": {"SQLCODE": -911}},
  "cics_status": {"TCAP1PWL:390": {"EIBRESP": 13}},
  "expected": {
    "status": "SUCCESS",
    "outputs": {"TCAPW000-COD-RETORNO": 0, "NPLANO-CAPTZ OF TCAPB080": 10},
    "tables": {"DB2PRD.TCTRL_LIBRC_CANAL": [{"NPLANO_CAPTZ": 10, "CTPO_OPER_CAPTZ": 2}]},
    "calls": ["TCAP3PWL"], "not_calls": ["FRWK1999"],
    "path": [{"program": "TCAP3PWL", "line": 276, "result": "TRUE"}],
    "rules": ["BR-..."]
  }
}
```
- Nomes de campo: `CAMPO`, `CAMPO OF GRUPO` ou `GRUPO.CAMPO` (qualificador só é necessário quando o nome é ambíguo no programa, como no COBOL).
- Linhas (`path`, `db2_status`, `cics_status`, `cics_link_outputs`) são do **fonte original**; o runner traduz para o texto expandido.
- `tables`: linhas por tabela; colunas são conferidas contra o catálogo DCLGEN quando existir (aviso `COLUNA_INEXISTENTE_NA_DCLGEN`).

### CICS com canal e IBM MQ (programas disparados por fila)
- `cics_containers`: `{"PEDIDO": {"CAMPO": valor}}` são os containers do canal que o programa recebe (o ponto de entrada lê com `GET CONTAINER`). O nome do container e do canal podem vir de variável. `PUT CONTAINER` grava no canal corrente e o programa chamado por `LINK ... CHANNEL` enxerga os mesmos containers (pilha de canais). Container inexistente devolve RESP `CONTAINERERR` (110); canal inexistente, `CHANNELERR` (122).
- `cics_retrieve`: campos devolvidos pelo `EXEC CICS RETRIEVE` (por exemplo a mensagem de disparo do CKTI, `{"MQTM-QNAME": "QL.FILA"}`); sem a chave, o RETRIEVE devolve `ENDDATA` (29).
- `mq`: filas do IBM MQ simulado, `{"FILA": [mensagem, ...]}`; mensagem é o dicionário de campos ou `{"dados": {...}, "backout": n}`. MQOPEN/MQGET/MQPUT/MQPUT1/MQCLOSE operam nessas filas (ids de mensagem `MSG000001`..., `MQGET` em fila vazia devolve reason 2033); com syncpoint, o que foi lido e gravado só se confirma no `EXEC CICS SYNCPOINT` e volta para a fila (com backout + 1) no `SYNCPOINT ROLLBACK` ou no fim sem syncpoint. A execução devolve as filas finais.
- `expected.mq`: `{"FILA": [mensagem esperada, ...]}` confere a quantidade de mensagens que ficaram em cada fila e os campos de cada uma (`correl_id` confere o CorrelId). As operações do MQ aparecem nas chamadas com o modo `MQ`.
- Programa de outro sistema executado de verdade (por exemplo um corporativo): o fonte entra nos fontes, o nome vai em `execute` e os programas que ele chama ficam nos `mocks`. Os campos que o programa preenche por sobreposição de bytes numa tabela de grupos (`MOVE AREA(1:n) TO TABELA`) são informados direto no mock (por exemplo `"WRK-S-CTPO-CANAL": [2, 5, 14]`).
- `cics_status` num `LINK` com EIBRESP diferente de zero: o programa chamado não roda (evento `CICS_LINK_FALHOU`, chamada com modo `FALHOU`) e o chamador segue com o RESP.
- `expected.outputs` aceita elemento de tabela: `"CAMPO(2)": valor`.

## Entradas e saídas deduzidas (copybook ausente)
Nome usado pelo código e sem declaração (o copybook/DCLGEN que o define não está na pasta) é um campo **deduzido**. A dedução lê os tokens de cada programa executado (IF/EVALUATE, MOVE, aritmética, SET, PERFORM, CALL, EXEC CICS, EXEC SQL com variáveis indicadoras) e infere:
- **tipo pelo uso**: comparado/movido com literal alfanumérico ou SPACES → ALPHANUMERIC; com número/ZEROS, subscrito, aritmética, PERFORM VARYING ou NUMERIC → NUMERIC; usado sozinho como condição ou em `SET ... TO TRUE` → CONDITION_88; em SQL, pela coluna de mesmo nome em outra DCLGEN (`comparado com a coluna X`);
- **copybook ausente**: pelo qualificador (`ESTRUTURA.CAMPO`), pelo prefixo do nome, por ser o único copybook ausente do programa (`UNICO_AUSENTE`) ou como lista de candidatos.

Na execução, o campo lido pelo código e não informado no cenário recebe o valor inicial do tipo deduzido (NUMERIC 0, ALPHANUMERIC SPACES, CONDITION_88 falso), em vez do 0 genérico do runtime (que não é igual a SPACES). Valor informado no cenário sempre prevalece, e campo declarado em outro programa do fluxo não é tocado. `"deduce_inputs": false` desliga.

Avisos e resultado:
| Onde | Conteúdo |
|---|---|
| aviso `COPYBOOK_AUSENTE_CAMPOS_DEDUZIDOS` (um por copybook) | copybook ausente e como foi atribuído, programas, entradas e saídas deduzidas; o console imprime `AVISO dedução: ...` |
| aviso `SAIDA_ESPERADA_EM_CAMPO_DEDUZIDO` | o valor esperado é de um campo sem layout: tipo/tamanho não foram validados |
| aviso `MOCK_SEM_RETORNO_DEFINIDO` | agora lista os campos que o fluxo lê e que o fonte do mock escreve |
| `io.inputs` / `io.outputs` no `result.json` | campo, tipo, valor inicial, origem (`DEDUZIDO`, `CENARIO`, `NAO_DEDUZIDO`), copybook, evidência com a linha do fonte; saídas com o valor final |
| `static/io-deduction.json` | todos os campos sem declaração de cada programa |
| cenário-modelo | `_entradas_deduzidas` e `_saidas_deduzidas` |

Limite: é dedução pelo uso, não o layout. Tamanho, PIC e níveis 88 reais só vêm do copybook.

## Mocks
| `mock_policy` | O que é mockado automaticamente |
|---|---|
| `infra_and_external` (padrão) | programas classificados como infraestrutura (recomendação `MOCK_RECOMMENDED`, hoje FRWK1200 e FRWK1999) + programas chamados que não estão nos fontes |
| `external_only` | só os que não estão nos fontes |
| `none` | nada (programa ausente gera erro no CALL) |

`mocks` define/ sobrepõe o comportamento (`returns` fixo, `scenarios` com `when`, `default`). `execute` força a execução real de um programa que seria mockado. Mock sem `returns` executa como "não faz nada" e gera aviso `MOCK_SEM_RETORNO_DEFINIDO`.

## Validações
**Saída x esperado** (`checks`): status, variáveis, linhas de tabela, chamadas, caminho e regras; cada item `MATCH`, `DIFF` ou `MISSING`. Determinismo: o cenário roda 3 vezes e exige o mesmo hash de trace.

**Caminho x análise estática** (`divergences` bloqueiam `static_consistency`; `warnings` são informativos):
| Tipo | Significado |
|---|---|
| `DECISAO_SEM_CORRESPONDENTE_ESTATICO` | runtime avaliou uma decisão que a árvore estática não tem |
| `RAMO_INEXISTENTE_NA_ARVORE` | resultado da decisão não existe entre os ramos estáticos |
| `CONTEXTO_AUSENTE` / `CONTEXTO_DIVERGENTE` | decisão aninhada executada sem o ancestral / com ancestral em outro ramo |
| `SQL_NAO_PREVISTO` | SQL executado em linha que a análise não conhece |
| `CHAMADA_NAO_PREVISTA` / `DESTINO_DIVERGENTE` | chamada fora do grafo estático / destino diferente do resolvido por VALUE |
| aviso `EFEITO_PREVISTO_NAO_OBSERVADO` | ramo percorrido tinha SQL/chamada prevista que não aconteceu |
| aviso `DESTINO_RESOLVIDO_SO_EM_EXECUCAO`, `CHAMADA_SEM_DESTINO` | destino vindo de variável sem VALUE |
| aviso `RAMO_IMPLICITO_NO_MATCH` | EVALUATE sem WHEN OTHER não casou nada |

**Cobertura**: por programa, ramos exercitados/total e regras de negócio exercitadas; por entry point, cenários existentes (`entry_points_without_scenario`).

## Cenários da base tcap
`cenarios/tcap/` tem 289 cenários que cobrem os 9 entry points (nomes `PROGRAMA-caso.json`). Cada entry point tem casos de:
- **entrada**: consistência dos campos (zero, não numérico, combinação inválida, faixa invertida), indicador de paginação inválido, página incoerente;
- **retorno do funcional/serviço** (mock com `returns`): 0, 01 (mais páginas), 08 (não encontrado), 16 (erro de módulo) e `GCOR0030` tratado como sucesso;
- **erro de infraestrutura**: `cics_status` (EIBRESP) em cada LINK e retorno diferente de zero da FRWK1200;
- **execução real do funcional** (`execute`) sobre tabelas informadas: leitura por cursor, SELECT com join, INSERT, UPDATE, sobreposição de faixa, `MAX(...)+1`, colunas NULL (indicador -1), páginas 1, 2 e além do fim com 101 linhas, e erro DB2 (`db2_status`) em OPEN/FETCH/CLOSE/SELECT/INSERT/UPDATE;
- **CDPS1SAA executado de verdade a partir do TCAP1QAL** e o CDPS1SAJ também (`TCAP1QAL-real-*`, gerados por `tools/gen_cenarios_qal_real.py`; o CDPS1SAJ só é mockado nos cenários que testam o retorno dele): lista de canais por cursor e via GCOR1910, sem canais, produto inexistente/zerado, situação nula/6/inválida, colunas nulas, datas `01.01.0001`, erro DB2 em cada SQL, erro CICS no LINK do CDPS1SAJ, CDPS1SAJ sem agrupador/modelo, erro DB2 e CICS dentro dele, erro CICS no LINK da GCOR1910 e retornos 08/16 (inclusive erro `0021`) do CDPS1SAJ e da GCOR1910. Achado: o TCAP1QAL só testa `EIBRESP` após o LINK do CDPS1SAA e ignora `W000-COD-RETORNO`, então qualquer erro do serviço vira lista vazia (08/0010/TCAP0019);
- **GCOR1910 executada de verdade** (detalhe e lista) com mocks de GCOR1210/1220/453F/1300: retornos 00/01/08/12, erro CICS em cada LINK e falha do log de erros.

Copybook ausente e nível 88: `TCAPWSHI`/`TCAPWSHW` não estão na pasta, então `TCAPWSHI-P-INICIAL`, `TCAPWSHW-P-ULTIMA` etc. são campos deduzidos (CONDITION_88, falso por padrão) e os cenários do TCAP1SHL os informam em `inputs` (`true`). Sem isso o EVALUATE cai em `WHEN OTHER`.

Achado de negócio: em TCAP1SWL o índice `IND-1` avança duas vezes por volta (`ADD 1 TO IND-1` em 2200 mais o `PERFORM VARYING`), então com 2 origens `TCAPWSWS-S-TOT-REG` termina em 3 e as ocorrências ficam nas posições 1 e 3. O cenário `lista-origens` fixa esse comportamento.

Resultado em `analises/tcap-codigo/runtime/`: 289 de 289 cenários passam, 0 divergências estáticas, 619 de 794 ramos fora de infraestrutura exercitados e 128 de 229 regras de negócio. `runtime-validation.json` lista em `uncovered_branches` cada ramo não exercitado (programa, linha do arquivo expandido, tipo, expressão e lado).

### Cobertura por entry point e fatia alcançável
`tools/entry_point_coverage.py` (chamado por `run_scenarios.py`) grava `entry-point-coverage.{json,md,html}` com o fluxo de cada entry point e o percentual. O denominador de um programa chamado é a **fatia alcançável** a partir do chamador (`semantic_core/slice_reach.py`), não o programa inteiro: um serviço como o CDPS1SAA é dirigido por flags `CDPSWAAA-E-PESQ-*` e o TCAP1QAL liga só `CDPSWAAA-E-PESQ-CANAL-CONTR`. A fatia sai da AST e dos tokens: o grafo de PERFORM, as condições de IF avaliadas em três valores (verdadeiro, falso, desconhecido) e as constantes que o chamador fixa antes do LINK/CALL (`MOVE 'S' TO campo` no mesmo parágrafo). Campos do mesmo grupo que o chamador não altera com dados (INITIALIZE só devolve o valor inicial) e que o chamado não grava valem o valor inicial da PIC; `MOVE DFHCOMMAREA TO área` não conta como atribuição do chamado; na fatia do chamado entram também os valores iniciais (VALUE) dos campos da COMMAREA que o chamador nunca altera. Um IF decidido por constantes só mantém o lado possível; ramos e parágrafos dentro do lado impossível saem do denominador. O numerador conta só os cenários do próprio entry point, e `outside_slice_taken` funciona como prova de consistência (ramo executado fora da fatia = fatia errada; hoje 0). Exemplo TCAP1QAL: o CDPS1SAA tem 217 ramos, 82 alcançáveis, 81 exercitados; o CDPS1SAJ tem 15 alcançáveis, 13 exercitados; o entry point cobre 118 de 121 ramos alcançáveis nos programas realmente executados (97,5%) e 118 de 190 no fluxo todo (a GCOR1910 continua mockada nos cenários do QAL). Os 3 ramos que faltam são inalcançáveis a partir do QAL: `WHEN ERRO-LIVRE` do 9999 do CDPS1SAA (todo `SET ERRO-LIVRE` é seguido de `PERFORM 6000-FINALIZAR`, que dá RETURN), `WHEN ERRO-CICS` do 9998 do CDPS1SAJ (ninguém faz `SET ERRO-CICS`) e a consistência de produto zerado do CDPS1SAJ (o CDPS1SAA rejeita produto zero antes de chamá-lo).

Ramos que sobram e por quê: CDPS1SAJ (16) só é executado de verdade se um cenário o tirar do mock; nos demais, o que resta é código morto pelo caminho dos entry points (segundas verificações `NOT NUMERIC` de faixa em QBI/QCA, que o teste anterior `NOT NUMERIC OR ZEROS` já barrou; `WHEN ERRO-CICS/ERRO-MODULO` do 9998 em programas sem esse caminho, etc.).

Achado adicional: em TCAP3QCA e TCAP3QBI os parágrafos de cursor (`OPEN`/`FETCH`/`CLOSE` de CSR01/CSR02) fazem `SET DB2-OPEN/FETCH/CLOSE` mas não `SET ERRO-DB2`, então o 9998 não grava o bloco de erro DB2 nesses casos (só o log é chamado).

Desempenho: 257 cenários rodam em cerca de 70 s (3 execuções cada, com verificação de determinismo) e a certificação completa leva de 13 a 38 s. Os ganhos vieram de cache de leitura/parse dos fontes, `lru_cache` nas normalizações de nomes e condições e de tokenização de literais longos sem estouro da coluna 72. O comando imprime tempos por etapa em stderr.

## Limites conhecidos
- Valores iniciais: campo declarado e ainda não gravado vale 0 (PIC numérica) ou brancos (alfanumérica); `INITIALIZE` aplica o mesmo padrão a cada elementar do grupo (itens de nível 77 são independentes). `VALUE(col, x)` do DB2 é tratado como `COALESCE`.
- Memória por nome, sem layout em bytes: MOVE de grupo não propaga subcampos (exceção: grupo cujo único conteúdo é uma tabela OCCURS de elementares copia posição a posição, como `MOVE WRK-CANAL TO CDPSWAAA-S-CDTPOS-CANAL`; `MOVE SPACES/ZEROS` no grupo preenche a tabela; layouts com OCCURS de grupos por sobreposição de bytes, como `MOVE GCORW910-S-DADOS(1:n) TO WRK-DADOS`, continuam sem suporte e o cenário informa os elementos no mock); commarea é compartilhada por nome entre chamador e chamado (campos de nome ambíguo, guardados qualificados, são copiados na ida e na volta do LINK pelo nome elementar, e o EIBRESP após o LINK volta a ser o do próprio LINK). Exceções tratadas: REDEFINES de campo `+9(n)` ou `X(n)` por elementares (gravar o base preenche os filhos e vice-versa, cobrindo o idioma `WRK-S9-03`/`WRK-9-03`) e leitura de um grupo em comparação (concatena os elementares no tamanho da PIC; FILLER final vale espaços).
- PERFORM: `TIMES`, `UNTIL`, `VARYING`/`AFTER` e `WITH TEST` (dentro e fora de linha) são lidos dos tokens do cabeçalho (`perform_spec`). Um cenário com `db2_status` fixo em 0 num FETCH dentro de `PERFORM UNTIL` que só termina em +100 não termina (como no programa real); a certificação por witness perdeu 2 goldens de 116 (TCAP1SWL:377 e TCAP3QCA:819, lado FALSE de `SQLCODE EQUAL +100`) por causa disso, embora os cenários de runtime cubram os dois ramos.
- Copybooks ausentes (61 na base) deixam campos e níveis 88 desconhecidos para o runtime.
- SEARCH e PERFORM UNTIL não fazem parte da árvore de decisão; só IF/EVALUATE são comparados.
- SQL: variável indicadora do INTO (`:HOST :IND`) vale -1 quando a coluna é NULL; agregações suportadas são `MAX/MIN/COUNT/SUM/AVG(coluna) [+|-|*|/ número]` sem GROUP BY (NULL sem indicador dá SQLCODE -305). GROUP BY, HAVING, UNION e OUTER JOIN continuam sem suporte (o cenário falha com `UNSUPPORTED_SQL`).

- CICS e MQ: a execução não passa por tradutor CICS, pré-compilador DB2 nem BIND; o tempo não conta (espera do MQGET, timeout) e a memória é por campo (sem EBCDIC).
- `LENGTH OF item` vale o tamanho em bytes calculado do modelo de dados (PIC e USAGE: COMP-3 = dígitos/2+1, COMP/BINARY = 2, 4 ou 8; grupo = soma dos filhos sem REDEFINES; OCCURS vezes, `OCCURS n TO m` pelo máximo). No `EXEC CICS LINK` com COMMAREA, o `EIBCALEN` do programa chamado é o `LENGTH` do comando (ou o tamanho da COMMAREA) e volta ao do chamador no retorno.

## Programas novos (fora do legado)
Os programas COBOL escritos na modernização (por exemplo os pares coordenador e funcional) rodam no host CICS abaixo, e a prova de que rodaram vem dos testes ponta a ponta do código gerado: cada pedido que um serviço põe na fila é casado com a unidade de trabalho da região que o atendeu (programas chamados, comandos SQL com o SQLCODE, SYNCPOINT), e a fase 21 (traceability-to-be) mostra isso na seção "Programas mainframe executados", com a cobertura das transações da região. Os fontes de várias pastas são juntados numa só e os books da plataforma IBM que faltarem (SQLCA, CMQV, CMQODV, CMQMDV, CMQGMOV, CMQPMOV, CMQTML) vêm de `fases/stubs-ibm`.

## Host CICS (programas ligados a filas e banco)
`tools/cics_host.py <config.json>` roda programas COBOL como transações disparadas por fila, interpretados por este runtime (sem compilar), para desenvolver e testar localmente. Duas formas, com a mesma configuração:
- `internal`: IBM MQ e DB2 em memória (`semantic_core/host_backends.py`): filas com syncpoint, backout e gatilho FIRST; tabelas de uma massa JSON, com trava por unidade de trabalho; API HTTP para gravar e ler mensagens e consultar tabelas;
- `external`: IBM MQ e DB2 de verdade (pymqi e ibm_db): monitor de gatilho (como o CKTI) na fila de iniciação, transação pelo APPLICID, SQL com variáveis host como marcadores (CAST pelo PIC) e esquema trocado (`esquemas`).
O host liga no runtime: `memoria_bytes` (texto ↔ campos pelo layout do grupo em `cobol_layout_codec.py` nas fronteiras: fila, container, MOVE entre grupo e área, `LENGTH OF` com ODO pelo valor corrente), `ws_por_programa` (no `LINK`, o chamado tem área de trabalho própria e só a COMMAREA passa, como no CICS), `nativos` (programas sem fonte em Python), `mocks` (mesmo formato dos cenários) e `registros` (linha de log com campos da área ao fim de um programa). O `SYNCPOINT` confirma o DB2 e depois o MQ; o que fica sem confirmação no fim da tarefa é desfeito. Uma região pode ter várias transações (programas instalados uma vez, um monitor de gatilho, `instancias` tarefas ao mesmo tempo). Painel em `/`, estado em `/status` e CEMT em `/cemt` (`GET` = INQUIRE TRANSACTION; `POST ?transacao=X&estado=DISABLED|ENABLED` = SET TRANSACTION: desabilitada, o disparo não inicia tarefa e a mensagem fica na fila; ao habilitar, a transação é iniciada para escoar a fila).

## Relatórios das fases

Veja `docs/18-RELATORIOS-E-REPRODUCAO.md`. O relatório `07-dynamic-analysis` reúne os cenários, a cobertura, os casos dourados, a certificação e o motivo dos ramos sem cobertura. `run_scenarios.py --cache <pasta>` retoma uma rodada interrompida.
