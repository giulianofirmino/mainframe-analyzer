# Reprodução completa: do código-fonte aos relatórios de IA e humanos

Este roteiro refaz, do zero e para qualquer código COBOL/CICS/DB2 de qualquer negócio, tudo o que foi feito na base de referência (`tcap`): análise estática, casos de teste da análise dinâmica, relatórios das fases 0 a 12, interpretações de IA e verificações. Seguindo-o com o mesmo código-fonte você chega aos mesmos relatórios determinísticos (hash idêntico) e a interpretações de IA equivalentes (a IA varia pouco de uma execução para outra; ver "Variação da IA"). Com outro código, o procedimento é o mesmo e nada precisa ser alterado em scripts ou prompts.

## 1. Princípios (o que garante a reprodução)

1. **Tudo o que é determinístico vem só de scripts.** Números, tabelas, diagramas, cores, ids (`Q01`, `F01`...), validações e o HTML saem de `semantic_core/`, `tools/` e `analises/simulacao-ia/gerar_*.py`, sem edição manual. O HTML (humano) é a projeção exata do `report.json` (IA); `tests/relatorios_equivalencia.py` confere.
2. **Tudo o que é julgamento ou texto vem só de prompts.** Há cinco prompts em `analises/simulacao-ia/prompts/`: 0 (cenários de teste), 1 (regras de negócio), 2 (funcionalidades), 3 (rastreabilidade: só script, sem texto de IA) e 4 (fluxo interno de cada funcionalidade). A IA devolve JSON; os scripts o validam (citação, id, cenário, coerência) e recusam o que não tem evidência.
3. **Scripts e prompts não conhecem o código analisado.** Nomes de programas, tabelas, campos e copybooks vêm dos relatórios em tempo de execução. `tests/agnostico_smoke.py` falha se qualquer nome do código analisado aparecer em script ou prompt. O que depende do projeto fica em `<cenarios>/analise.config.json`.
4. **A IA executa isolada.** Cada prompt roda numa IA que só vê o prompt e os relatórios de entrada que ele lista (o "contrato" `@ler`, conferido por `verificar_prompts.py`), nunca o código analisado (exceto o prompt 0) nem interpretações anteriores.
5. **Nenhuma edição manual da saída da IA.** `analises/simulacao-ia/proveniencia.py` guarda o que a IA devolveu (`bruto/`) e o hash do prompt que a gerou; a verificação acusa interpretação editada à mão ou gerada por versão antiga do prompt. A única alteração permitida é a poda determinística (`podar_interpretacao.py`: só remove).
6. **Erro do validador volta para a mesma IA.** Se o gerador recusa algo, a mensagem é devolvida à IA para ela corrigir pelo prompt; ajustar o JSON à mão invalida a proveniência.

## 2. Mapa das etapas

| Etapa | Quem faz | Entrada | Saída | Comando |
|---|---|---|---|---|
| A. Análise estática e certificação (fases 0 a 6, 8, 9) | scripts | fontes | `00` a `06`, `08`, `09` | `tools/analisar.py` |
| B. Casos de teste da análise dinâmica | IA (prompt 0) + script gerador | fases 0, 1, 5, 7, código | `cenarios/<sistema>/*.json` | `tools/run_scenarios.py` |
| C. Execução dos cenários (fase 7) e relatórios 0 a 9 e 4b | scripts | fontes + cenários | `07-dynamic-analysis`, `runtime/` | `tools/analisar.py --sem-ia` |
| D0. Mapeamento de comandos SQL | IA (prompt 5) + script | fases 0, 1, 4, 4b, 5, 7 | `interpretacao-sql/mapeamento.json` → `10 - sql-mapping` | `tools/analisar.py --so-relatorios` |
| D1. Regras de negócio | IA (prompt 1) + script | fases 0, 2, 4, 5, 6, 10 | `interpretacao/regras.json` → `11 - business-rules` | idem |
| D2. Funcionalidades | IA (prompt 2) + script | fases 0, 1, 5, 10, 11 | `interpretacao-fluxos/funcionalidades.json` → `12 - business-flows` | idem |
| D3. Rastreabilidade | script (prompt 3 descreve) | fases 5, 6, 11, 12 | `13 - traceability` | idem |
| D4. Fluxo interno por funcionalidade | IA (prompt 4) + script | fases 0, 1, 5, 11, 12, 13 | `interpretacao-sequencia/sequencia.json` → seção de cada funcionalidade em `12` | idem |
| E. Verificações | scripts | pasta de resultados | OK/erro | seção 8 |

## 3. Preparação

- Python 3.10+, somente biblioteca padrão. Raiz do analisador = este repositório.
- **Fontes**: pasta com os `.CBL`/`.CPY`/DCLGEN do sistema (copybooks ausentes são tolerados: os campos viram "deduzidos").
- **Configuração do projeto** `cenarios/<sistema>/analise.config.json`:
  - `prefixo_core`: prefixo que todo programa do core do negócio tem (por exemplo `ABCD`); programa sem o prefixo só pode ser CORPORATIVO ou INFRAESTRUTURA. É a única heurística por nome e só vale se informada;
  - `campos_infraestrutura`: expressões dos registradores do CICS/DB2 que não são negócio;
  - `sqlcode_negocio`: SQLCODE tratados como regra de negócio (por exemplo registro não encontrado e chave duplicada); os demais viram infraestrutura;
  - `categorias_mecanismo_validacao`: categorias com que a IA pode descartar uma validação como mecanismo (por exemplo permissão de acesso).
- **Tempo limite**: se o ambiente corta cada comando (por exemplo 3 minutos), repita o mesmo comando até terminar; o cache (`<saida>.cache`) retoma e o resultado é idêntico ao de uma execução contínua. Use `ANALISE_RAIZ=<raiz do analisador>` quando rodar scripts de uma cópia fora do repositório.

## 4. Etapa A: análise estática

```
python3 tools/analisar.py <fontes> cenarios/<sistema> <saida> --sem-ia
```

Sem cenários ainda, rode só a certificação: `./mainframe-analyzer certify <fontes> <saida>` (fases 0 a 6, 8 e 9). Ela classifica os programas (fase 0), descobre dependências (1), esquemas de programa e dados (2 e 3), linhagem de dados (4), mapa de decisão (5) e regras determinísticas (6), tudo por tokens e AST, sem IA.

## 5. Etapa B: como os casos de teste foram criados (prompt 0)

Os 289 cenários da base `tcap` foram escritos por IA lendo o código e os relatórios, com este procedimento (agora no prompt `prompt-0-cenarios-de-teste.md`, que é a fonte de verdade para repetir):

1. **Gerar os cenários-modelo.** `python3 tools/run_scenarios.py <fontes> --modelo entry-points <saida>` grava um modelo por entry point, com as entradas candidatas (campos que o programa lê e não declara, com tipo e valor inicial deduzidos pelo uso) e os mocks previstos (programas de infraestrutura e programas ausentes dos fontes).
2. **Catálogo de casos por entry point** (o prompt 0 detalha): caminho feliz de cada função; consistência da entrada (zero, não numérico, combinação inválida, faixa invertida, indicador de continuação inválido); cada código de retorno do programa chamado que o chamador trata diferente (mock com `returns`); erro de infraestrutura (`cics_status` em cada LINK, retorno de erro da infraestrutura); execução real do programa chamado (`execute`) sobre tabelas informadas (cursor, join, INSERT, UPDATE, sobreposição, `MAX()+1`, colunas NULL, página cheia, seguinte e além do fim); erro de banco (`db2_status`) em cada OPEN, FETCH, CLOSE, SELECT, INSERT e UPDATE; serviços corporativos executados de verdade pelo entry point que os usa.
3. **Esperado vem do código, antes de rodar.** O `expected` (status, saídas, tabelas, chamadas, caminho) é previsto pela leitura; divergência depois da execução é investigada (esperado errado, cenário que não leva ao ramo, ou código que se comporta diferente do que parece, registrado em `description`).
4. **Laço de cobertura.** Rode os cenários e leia na fase 7 "Ramos sem cobertura" (cada ramo tem um motivo e a evidência). Para cada `FALTA_CENARIO`, escreva o cenário que decide aquele lado. Pare quando: todos os cenários passam, não há divergência com a análise estática e todo ramo restante tem motivo conferido (código inalcançável a partir dos entry points, ramo morto, depende de copybook ausente). Não se escreve cenário só para subir o percentual.
5. **Gerador de cenários.** Quando há muitos casos parecidos, a IA escreve um script gerador com a tabela de casos (como `tools/gen_cenarios_qal_real.py`); o conjunto fica reproduzível e revisável. Esses geradores são específicos do sistema e ficam fora do pipeline (e do teste de agnosticismo).
6. **Fatia alcançável.** O denominador de cobertura de um programa chamado é a fatia alcançável a partir do chamador (`semantic_core/slice_reach.py`), não o programa inteiro; `outside_slice_taken` deve ser 0.

Resultado de referência (`tcap`): 289 cenários, 289 passam, 0 divergências estáticas, 9 de 9 entry points com cenário, 619 de 794 ramos fora de infraestrutura exercitados, 128 de 229 regras de negócio exercitadas. Os ramos que faltam têm motivo conferido na fase 7. O formato do cenário e a semântica de mocks, entradas deduzidas e validações estão em `docs/17-RUNTIME-CENARIOS.md`.

Observação de honestidade: os 289 cenários do repositório foram escritos de forma interativa antes de o prompt 0 existir; o prompt 0 registra o procedimento seguido. Para outro código ele deve ser executado como os demais (IA isolada, leitura do código, laço até a meta) e a proveniência dos cenários registrada no gerador ou no commit.

## 6. Etapa C: executar tudo sem IA

```
python3 tools/analisar.py <fontes> cenarios/<sistema> <saida> --sem-ia
```

Executa o pipeline, os cenários (`run_scenarios.py`), a cobertura por entry point, o motivo dos ramos sem cobertura e os relatórios das fases 0 a 9 e 4b. Duas execuções do zero com o mesmo código geram os mesmos hashes (o `MANIFESTO.json` difere só no campo `ausentes`, que lista as fases de IA ainda não geradas).

## 7. Etapa D: interpretações de IA, uma por prompt

Crie a pasta de trabalho da interpretação (copie `analises/simulacao-ia/` sem as pastas `interpretacao*`, `bruto` e `__pycache__`; scripts e prompts vêm do repositório) e, para cada prompt, repita: **preparar a entrada → rodar a IA isolada → gravar o bruto → gerar o relatório → corrigir pelo validador**.

### 7.1 Preparar a entrada isolada

Crie uma pasta `entrada/` com **somente** os `ia/report.json` das fases que o contrato `@ler` do prompt cita (`python3 analises/simulacao-ia/prompts/verificar_prompts.py <saida>` confere que cada tabela e coluna existe), o prompt em `entrada/_prompt/` e, para os prompts 2 e 4, a saída do passo anterior (para o prompt 2, o `regras.json` do prompt 1 após a poda; para o 4, os relatórios 10, 11 e 12 **gerados sem fluxo interno**). Fases por prompt: prompt 1 usa 00, 02, 04, 05 e 06; prompt 2 usa 00, 01, 05, 06 e 07 mais o resultado do prompt 1; prompt 4 usa 00, 01, 05, 10, 11 e 12.

### 7.2 Instrução padrão da IA isolada

Entregue à IA o texto abaixo, trocando `N`, o nome do prompt, a lista de fases e o arquivo de saída:

> Execute o Prompt N de um pipeline de análise de código legado. O prompt está em `entrada/_prompt/prompt-N-....md`: leia-o inteiro e siga-o à risca. As entradas que ele lista estão em `entrada/<fase>/ia/report.json`. Leia somente o prompt e esses relatórios: não leia código-fonte, interpretações anteriores, relatórios que o prompt não cita nem execuções anteriores. Use scripts para consultar os JSON; todo o julgamento é seu. Grave o JSON no formato do prompt em `<pasta de saída>/<arquivo>`. Responda com o caminho, as contagens, as lacunas registradas e os pontos do prompt imprecisos que o obrigaram a adivinhar.

A resposta traz também as imprecisões do prompt: elas são a fonte de melhoria dos prompts (se mudar o prompt, a interpretação tem de ser regerada).

### 7.3 Gravar o bruto e gerar

```
python3 analises/simulacao-ia/proveniencia.py registrar <simulacao-ia> <1|2|4> <pasta-com-o-JSON-da-IA>
python3 tools/analisar.py <fontes> cenarios/<sistema> <saida> --so-relatorios --simulacao-ia <simulacao-ia>
```

Ordem: prompt 5 (mapeamento SQL) → rodar (gera `10`) → prompt 1 (regras; considera também os comandos dinâmicos `Qnn`) → rodar (gera `11`, `13`) → prompt 2 com o `regras.json` podado (usa o mapeamento da fase 10 e decide o desdobramento de cada consulta dinâmica) → rodar (gera `12`) → prompt 4 com `11`, `12`, `13` → rodar (acrescenta o fluxo interno à seção de cada funcionalidade em `12`). O prompt 3 não tem etapa de IA: o `13 - traceability` é calculado. Cada prompt roda em execução isolada (só as pastas `entrada/<fase>/ia/report.json` do contrato `@ler`), e o resultado é registrado com `proveniencia.py registrar <pasta> <1|2|4|5> <bruto>`.

### 7.4 O que o gerador recusa (e a IA tem de corrigir)

Prompt 1: regra de negócio sem grupo; literal citado que não está nos relatórios; título que cita programa ou código de retorno; grupo com mais de um retorno (COD-RETORNO, COD-ERRO, COD-MENSAGEM); campo em `campos` que nenhuma condição do caminho testa; mecanismo que descarta validação fora das categorias permitidas. Prompt 2: id de grupo inexistente; funcionalidade de entry point com regra de programa corporativo e vice-versa; consulta dinâmica sem comando estático, origem, colunas e condições inferidas dos chamadores e decisão de desdobramento; cenário citado que não existe. Prompt 4: nó sem caminho desde ENTRADA ou sem chegada a SAIDA, ciclo, regra fora da lista da fase 11, comando SQL estático fora do fluxo, literal de `cita` sem evidência nos relatórios do escopo. A mensagem do gerador é devolvida à IA.

## 8. Etapa E: verificações (todas devem passar)

| Verificação | Comando | O que prova |
|---|---|---|
| Equivalência IA/humano e diagrama com tabela | `python3 tests/relatorios_equivalencia.py <saida>` | o HTML é a projeção exata do `report.json`, sem JSON; todo diagrama em faixas tem tabela |
| Contrato dos prompts | `python3 analises/simulacao-ia/prompts/verificar_prompts.py <saida>` | toda tabela e coluna que um prompt usa existe nos relatórios |
| Agnosticismo | `python3 tests/agnostico_smoke.py <saida>` | nenhum nome do código analisado em scripts ou prompts |
| Proveniência | `python3 analises/simulacao-ia/proveniencia.py verificar <simulacao-ia>` | interpretação = bruto da IA (ou só com remoções da poda) e prompt atual = prompt usado |
| Determinismo | `python3 tests/determinismo_hashseed.py <cópia da saída>` | relatórios idênticos sob 3 sementes de hash |
| Reprodução do zero | duas execuções de `tools/analisar.py ... --sem-ia` em pastas diferentes e comparação dos `MANIFESTO.json` | mesma análise, mesmos bytes |
| Suíte do motor | `python3 tests/rodar_todos.py <saida>` | smoke tests do analisador e do runtime |

## 9. Resultado de referência (base `tcap`, pasta `analises/consolidado/`)

| Medida | Valor |
|---|---|
| Cenários e cobertura | 289 de 289 passam; 0 divergências estáticas; 619 de 794 ramos; 128 de 229 regras exercitadas |
| Regras de negócio | 159 regras do analisador em grupos (de 227 de escopo de negócio; as demais são mecanismos julgados pela IA), 130 regras de negócio por programa, 0 sem classificação |
| Funcionalidades | 13 (F01 a F09 por entry point, FC01 a FC04 corporativas, a consulta dinâmica internalizada e desdobrada em duas) mais a descoberta D01 |
| Fluxo interno | 225 de 225 ligações em confiança alta (100%); 0 afirmações sem evidência; 41 lacunas e problemas registrados pela IA (ramos que nenhum cenário exercita, comandos só mockados e textos das fases 10 e 11 que contradizem o mapa de decisão) |
| IA igual ao humano | 15 de 15 fases |
| Contrato dos prompts | todas as entradas conferidas, 0 problemas |
| Agnosticismo | 89 arquivos, 0 nomes do código analisado |
| Determinismo | 3 sementes de hash e 2 execuções do zero com relatórios idênticos |

A saída completa está em `analises/consolidado/analise/`; as interpretações, o bruto da IA e a proveniência em `analises/consolidado/simulacao-ia/`; as entradas isoladas dadas à IA em `analises/consolidado/entrada/`; a rodada anterior de cada interpretação em `analises/consolidado/anteriores/`.

## 10. Variação da IA

As execuções independentes do mesmo prompt dão resultados muito próximos, não idênticos: o prompt 1 produziu entre 126 e 130 grupos (V 30; E 32 a 39; C 37 a 43; A 3; S 7 a 11; D 7) e o prompt 4 entre 2 e 41 lacunas, conforme a IA registra ou não os ramos que o mapa de decisão marca como não executados. O que é garantido é a **validade** (tudo citado existe, nada fora do escopo, ligações com evidência) e a **estrutura** (mesmas categorias, funcionalidades por entry point e por programa corporativo, consulta dinâmica internalizada). Compare duas interpretações com `analises/validacao-prompts/comp2.py <A> <B>`. Mudar um prompt exige regerar a interpretação dele e das etapas seguintes (a proveniência acusa).

## 11. Replicar para outro código ou outro negócio (checklist)

1. Criar `cenarios/<novo>/analise.config.json` (prefixo do core, campos de infraestrutura, SQLCODE de negócio, categorias de mecanismo).
2. Rodar a etapa A e ler as fases 0 e 1: confira a classificação dos programas e os entry points.
3. Criar os cenários com o prompt 0 (modelo → catálogo → laço de cobertura) e rodar a etapa C.
4. Executar os prompts 1, 2 e 4 isolados, na ordem, gerando os relatórios entre eles.
5. Rodar as verificações da seção 8 e registrar as medidas da seção 9 para o novo código.
6. Se aparecer vocabulário do negócio anterior em prompt ou script, é defeito: o `agnostico_smoke.py` pega nomes do código analisado, mas não palavras comuns do domínio (canal, plano, parcela...); revise os exemplos dos prompts ao adotar um domínio muito diferente.

Armadilhas já vistas: nome de campo com e sem prefixo de copybook (os scripts comparam sem o prefixo; o gerador tira o prefixo dos textos); copybook ausente (campos deduzidos, ver doc 17); consulta dinâmica cujo mock não define o texto montado (comando "inferido dos parâmetros", com a lacuna dita); programa corporativo com um só chamador (também vira funcionalidade corporativa, para não misturar regras de entry point com as dele); limite de uso da IA no meio de uma execução (repita só o prompt interrompido, a entrada é a mesma).

## Nota: comandos SQL dinâmicos e business-flows

Os comandos SQL dinâmicos internalizados usam o código `<programa>-Qnn` (mesmo padrão dos estáticos); a regra sintética de business-rules é `SERVIÇO:SERVIÇO-Qnn`. O diagrama de sql-mapping (programa → comando → tabela) mostra só o que a execução dinâmica alcançou (`executa_em` no prompt 5 aponta a caixa do mapa de decisão). business-rules só traz regras alcançadas. business-flows não repete a descoberta dinâmica nem cita comandos ou tabelas dinâmicos: o desdobramento usa `desdobramentos` {programa, decisao, criterio} e funcionalidades com `usada_por` e `grupos`. Ordem de reprodução dos prompts: 5 → 1 → 2 → 4.

## Fase 14 — pdc-mapping

Determinística, sem IA: `gerar_pdc.py <analise> <saida> --pdc <pasta-dos-xml-do-pdc>`. Relaciona processo, ação e transação (programa mainframe) dos XML do PDC com os programas das fases 0, 1, 2 e 7 e diferencia os executados pela análise dinâmica.

Fase 15 (user-interface-mapping): ver LEIAME da análise validacao-sql; novo bloco `wire` (wireframe da tela) em report_render.

## Fase 16 — domain-model

IA com evidência determinística: `gerar_dominio.py <analise> <saida> --interpretacao <pasta-simulacao-ia>`. Lê as fases 3, 4 e 10 (e a fase 0 pela classe dos programas), deduz chaves e vínculos, separa Business core de Corporativo e valida a interpretação do prompt 7 (`interpretacao-dominio/dominio.json`, proveniência registrada com `proveniencia.py registrar . 7`). Ver docs/18.

Evidência determinística e análise por IA: `gerar_responsibility_segregation.py <analise> <saida> --interpretacao <pasta>`. Lê as fases 3, 4, 10, 12 e 16 e monta a estratégia de acesso aos dados: leituras de uma tabela e gravações nos agregados; leituras de várias tabelas em Legacy Query, agrupadas em Group Query quando têm as mesmas tabelas ou são usadas por mais de uma funcionalidade; os agregados corporativos chamam os programas corporativos originais por meio de LEGACY. A IA (prompt 8, `prompts/prompt-8-chamadas-e-n-mais-1.md`, registrada com `proveniencia.py registrar . 8 <pasta>`) julga chamadas, latência e N+1 por funcionalidade; sem a interpretação o relatório sai só com a evidência.

Fase 18 (context-discovery): `gerar_context_discovery.py <analise> <saida> --interpretacao <pasta>`. Lê as fases 12, 15, 16 e 17 e monta os Domain Contexts, os Delivery Contexts e o mapa semântico de contextos (cada contexto com os seus componentes). A interpretação (prompt 9, `interpretacao-contextos/`) traz capacidades, opções de modernização, classe DDMS, agrupamento dos Delivery Contexts e protocolos; o gerador a valida contra a evidência.

Fase 19 (target-architecture): `gerar_target_architecture.py <analise> <saida> --interpretacao <pasta>`. Lê as fases 3, 10, 15, 16 e 18, monta o modelo de recursos (`ia/architecture-resource-model.yaml`; nomes já atribuídos em `nomes-atribuidos.json`) e gera os diagramas a partir dele. A interpretação (prompt 10) só traz decisões, premissas e lacunas; todo recurso `UNCERTAIN` ou `UNKNOWN` precisa de uma lacuna com `tipos`.

Fase 20 (contracts): `gerar_contracts.py <analise> <saida> --interpretacao <pasta>`. Lê as fases 3, 10, 17, 18 e 19 e gera os OpenAPI 3.1 (BFMF, VAS, Domain Microservice) e os copybooks das filas em `20 - contracts/ia/contracts/`. A interpretação (prompt 11) traz nomes de campo, operações de entrada, listas paginadas, decisões, premissas e lacunas; `--planilha` lista as chaves de campo exigidas.

Fase 21 (traceability-to-be, IA + execução de testes): rastreabilidade do código gerado, da regra de negócio ao teste que a garante. 1) No repositório do código gerado, rode o `prompts/prompt-12-implementacao-e-testes.md` (a IA implementa ou corrige o que faltar, escreve os testes com a convenção `CT-<funcionalidade>-<regra>-NN` e `[F06.E31]`, executa e devolve `implementacao.json`) e registre: `proveniencia.py registrar . 12 <pasta>`. 2) Colete os resultados no repositório: `python3 local/tests/coletar-evidencias.py --executar` (testes unitários JUnit 5 dos módulos + suíte ponta a ponta Java em `local/testes-integrados`, que só roda no ambiente local, com massa própria e evidência por cenário em `local/tests/evidencias/cenarios/` -> `local/tests/evidencias/resultados-testes.json`). 3) `gerar_traceability_to_be.py <analise> <saida> --projeto <repositório> --resultados <resultados-testes.json>` e depois `report_render.ligar`. Para a arquitetura alvo implementada (em tcap-modernizacao): rastreio por regra (decisões de origem da fase 13, funcionalidade, aplicação e caso de uso da fase 19, endpoints da fase 20, módulo, código com arquivo:linha, cenários e resultado), casos de uso, endpoints, catálogo de cenários (entrada, esperado, obtido, arquivo::método), código de cada regra, execuções, pendências, decisões, premissas e lacunas. Recusa âncora que não existe no código, regra fora do rastreio e aplicação sem módulo. Saída: `21 - traceability-to-be/{human,ia}`. Roda depois das fases 19 e 20. Toda regra tem teste unitário no código gerado quando possível (os simuladores em `local/` não têm testes); o rastreio separa testes unitários e cenários ponta a ponta, e a tabela de cenários mostra o tempo de cada um e a resposta completa por trás do «…» (célula `report_model.expandir`). Nos casos de uso do código gerado, cada regra fica no seu método, com o código e o título no comentário (âncora da regra). O relatório traz também as evidências de cada cenário (requisição, resposta, logs da cadeia com o traceId, consultas ao DB2; código e resultado do teste unitário) e a cobertura unitária de cada cenário ponta a ponta.

Fase 22 (architecture-decision-records, decisões): Registro das decisões de arquitetura (ADRs) tomadas pelo dono da arquitetura sobre a arquitetura alvo: `gerar_architecture_decisions.py <analise> <saida> --projeto <repositório>`, com as decisões em `interpretacao-adr/adr.json` (não é saída de IA). Cada ADR traz ficha, contexto, decisão, alternativas e consequências, completas com tabelas calculadas das fases 10, 19 e 20 e do repositório; as mudanças de nomenclatura têm diagrama de-para e tabela completa. Recusa fila, endpoint ou âncora que não confere com o repositório. Roda depois da fase 21.

Fase 23 (enhancement-proposals, propostas): propostas de melhoria do processo de análise e de modernização (`gerar_enhancement_proposals.py <analise> <saida> --projeto <repositório>`, registro em `interpretacao-ep/ep.json`); roda depois da fase 22, e o pipeline a executa na etapa 23.

Estratégia única (desde 21/10/2026): as fases 17 a 21 trazem só a estratégia de acesso aos dados adotada (o antigo cenário C; os cenários A, Composition, e B, híbrido sem LEGACY, foram retirados dos relatórios e dos prompts 8 a 12, e as interpretações foram refeitas e registradas). Queries de uma tabela e gravações executadas pelos agregados; queries de várias tabelas em Query Legacy dentro de Group Query; os agregados corporativos chamam os programas corporativos originais por meio de LEGACY, em vez de executar SQL. Fase 18: as caixas dos Domain Contexts corporativos trazem só o agregado e os nomes dos programas corporativos (LEGACY no lugar de FILTERED_SELECT, DIRECT_SELECT etc.). Fase 19: cada programa corporativo vira uma fila de pedido, uma de resposta e um programa mainframe novo do tipo PROGRAM_CORP, que chama o programa corporativo original; os comandos SQL do programa apontam para as mesmas filas. Os nomes já atribuídos aos programas mainframe novos, aos copybooks e à abreviação do contexto nas filas ficam em `simulacao-ia/nomes-atribuidos.json` (registro dos nomes usados pelo código gerado, não é saída de IA) e são mantidos; só comando novo recebe nome pela regra. Fase 20: o contrato REST do domínio corporativo expõe os campos dos comandos SQL que o programa corporativo executa; os copybooks são um par por programa corporativo (união dos campos dos comandos); as listas paginadas (chave `paginacao` do prompt 11, requisito do dono do produto) recebem `pagina` e `tamanhoPagina` e devolvem `itens`, `pagina`, `tamanhoPagina`, `totalItens` e `totalPaginas`, e os copybooks das queries de lista ganham `REQ-NUM-PAGINA` e `REQ-QTD-POR-PAGINA` no pedido e `RSP-QTD-TOTAL` no cabeçalho da resposta. Os títulos dos blocos não levam mais o prefixo do cenário (por exemplo «Relação por funcionalidade», «Domain Contexts», «Rastreio das regras de negócio», «Operações dos contratos»), e os contratos ficam em `20 - contracts/ia/contracts/{delivery,domain,mainframe}/`.
