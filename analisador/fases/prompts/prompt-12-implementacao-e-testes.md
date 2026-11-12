# Prompt 12: Implementação e testes: cada regra de negócio no código gerado e o teste que a garante

Cole este arquivo inteiro para a IA que trabalha **no repositório do código gerado** (o repositório indicado na execução), junto com os arquivos listados em "Entradas". A IA implementa ou corrige o que faltar, escreve e executa os testes e devolve a interpretação (JSON) com a qual o gerador `gerar_traceability_to_be.py` monta o relatório **traceability-to-be** (`21 - traceability-to-be/human/report.html` e `21 - traceability-to-be/ia/report.json`).

O gerador calcula sozinho, dos relatórios: a lista de regras de cada caso de uso (fase 19), a cadeia decisão → regra determinística → regra de negócio (fase 13), os endpoints de cada regra (fase 20: `x-business-rules` e "Recusas possíveis" de cada operação) e, do código, o `arquivo:linha` e o trecho de cada âncora. A IA entrega o que depende de julgamento: onde a regra está no código, se o comportamento é conforme e por quê, e os testes.

## Objetivo

Para **a arquitetura alvo implementada** (o código gerado segue a arquitetura alvo da fase 19), garantir e provar que **toda regra de negócio do rastreio da fase 19** está implementada e coberta por pelo menos um teste executado com sucesso:

1. **Correlação aplicação → módulo.** Cada aplicação da fase 19 (BFMF, VAS, Domain Microservice) aponta para o módulo do repositório que a implementa (um módulo pode juntar mais de uma aplicação). Aplicação que não está no repositório (por exemplo o micro frontend) entra com `modulo: null` e o motivo. Programas corporativos chamados por LEGACY apontam para o módulo que os reproduz (simulador).
2. **Código da regra.** Nos casos de uso (`application/usecase`), cada regra de negócio fica no seu próprio método, e não num método `executar` grande: o `executar` só orquestra, chamando os métodos das regras na ordem. Regras que formam um só passo (por exemplo a leitura e a recusa que depende dela) podem dividir o método. O método leva um comentário com o código e o título da regra, um por linha, no formato `Regra <funcionalidade>.<regra> · <título da regra na fase 19>` (ex.: `/** Regra F01.V01 · <título da regra> */`). O comentário não leva observação nem referência ao sistema legado, às fases ou aos relatórios da análise (programas antigos, «fase 19», «DIVERGENCIAS.md»); essas informações ficam na interpretação (`observacao` da regra). Para cada regra, uma ou mais âncoras: arquivo relativo à raiz do repositório e um trecho **literal** de uma linha que existe nele. Nos casos de uso, a âncora é a linha do comentário (`Regra F01.V01 ·`); nos demais arquivos (validação do pedido, adapter MQ, tratador de erros, programa simulado), é a validação, a consulta SQL ou o tratamento do retorno. Use `apos` quando o mesmo trecho aparece mais de uma vez no arquivo (a busca começa depois da primeira linha que contém `apos`). Regra que não está no código é implementada antes de responder; se não puder ser implementada, ela vai para `lacunas` e a regra fica `NAO_IMPLEMENTADA`.
3. **Testes.** Toda regra tem **teste unitário** (JUnit 5) no código gerado sempre que possível, e cenário ponta a ponta quando o ambiente a provoca:
   - unitário: no BFF e nos serviços (nunca nos simuladores dos programas mainframe em `local/`, que não têm testes). Endpoint real (MockMvc sobre o resource e o tratador de erros) para as validações de entrada; caso de uso e adapter reais com as portas ou a fila MQ substituídas para as demais. Regra cuja lógica é o SQL ou o programa corporativo (fica no mainframe) é testada do lado do código gerado: o serviço chama o programa certo com os parâmetros certos e traduz a resposta que o programa devolve para aquela regra (sucesso, recusa 08, não encontrado SQLCODE 100, falha 12/16, chave duplicada -803). Regra sem teste unitário só com o motivo em `lacunas`;
   - ponta a ponta (contra o ambiente local: HTTP no BFF ou no serviço, consulta ao banco, linha de log com o traceId), quando a regra pode ser provocada com massa inserida e removida pelo próprio teste ou com injeção de falha (programa mainframe simulado parado, tabela de domínio vazia ou indisponível). A suíte é **Java (JUnit 5)**, nunca script Python, e só roda no ambiente local: módulo `local/testes-integrados`, fora do `pom.xml` raiz (não entra no build nem na esteira das aplicações), executado por `local/testes-integrados/executar.sh` num **ambiente de teste próprio, separado do ambiente de desenvolvimento**: o mesmo docker compose sobe com outro projeto e outro prefixo de containers (arquivo de variáveis de teste), com banco e filas próprios, carga inicial do banco própria e nenhuma porta no host; o script sobe esse ambiente, roda o Maven num container na rede dele (socket do Docker para ler logs pela API do Docker, JDBC para o DB2) e no fim o derruba com os volumes, então cada rodada começa da carga inicial e nunca altera os dados de quem está desenvolvendo. Todo cenário que chega ao mainframe prova que os programas rodaram: cada pedido que o serviço pôs na fila (id da mensagem no log do adaptador) é casado com a unidade de trabalho da região CICS que o leu, e o cenário grava no campo `mainframe` a transação, a tarefa, os programas executados (coordenador, funcional e corporativos), os comandos SQL com o SQLCODE e o SYNCPOINT; o cenário falha se o pedido não foi atendido pelo coordenador esperado com o funcional até o SYNCPOINT, e, com a função indisponível, se alguma tarefa leu o pedido. A massa da suíte fica em faixas de chave que a carga do banco local não usa (faixas que a carga não usa, escolhidas lendo o banco), é criada no início e removida no fim; valores que vêm da carga (como os tipos de canal) são lidos do banco, nunca fixados no teste. O teste de fumaça sobre a carga do banco fica na mesma suíte e desfaz só o que alterou.
   - **evidências de cada cenário**: o cenário ponta a ponta grava em `local/tests/evidencias/cenarios/<ID>.json` a requisição (método, URL, corpo, `X-Trace-Id`), a resposta **completa** (status, corpo, tempo em ms), as linhas de log com o traceId de cada container da cadeia (BFF, serviço e programa simulado) e as consultas ao DB2 com o resultado; o resumo da execução vai para `local/tests/evidencias/e2e-regras.json`. O teste unitário tem como evidência o código do método de teste (`arquivo:linha`) e o resultado do JUnit (relatório do surefire), que o coletor anexa. O relatório mostra o resumo e expande o resto.
   - **cobertura unitária dos cenários**: toda regra coberta por um cenário ponta a ponta tem também teste unitário; o relatório confere cenário por cenário e aponta as regras do cenário sem teste unitário.
   Convenção obrigatória, que o coletor lê: o ID do cenário é `CT-<funcionalidade>-<regra>-NN` (ou `CT-<APLICAÇÃO>-<ASSUNTO>-NN` quando um teste cobre regras de várias funcionalidades); o teste unitário tem `@DisplayName("CT-... [F01.E01, F02.E03] descrição -> resultado esperado")` e o método se chama como o ID (`ct_F01_E01_01`); o cenário ponta a ponta declara o ID, a lista de regras, a entrada, o esperado e o obtido.
4. **Execução e coleta.** Rode os testes unitários e a suíte ponta a ponta e o coletor (`local/tests/coletar-evidencias.py --executar` no repositório de referência: roda o Maven dos módulos e o `local/testes-integrados/executar.sh`), que grava `local/tests/evidencias/resultados-testes.json` com os cenários e as evidências de cada um. Antes de rodar a suíte ponta a ponta, recrie as imagens das aplicações (`docker compose build`) para que o ambiente de teste execute o código atual (as imagens são as mesmas dos dois ambientes). Teste que falha é corrigido (no código, se o defeito é do código; no teste, se o teste estava errado, explicando em `decisoes`) e executado de novo; nada vai para o relatório com falha sem uma lacuna que a explique.
5. **Conformidade.** Para cada regra: `CONFORME` quando o comportamento do código é o da regra; `DIVERGENTE` quando o código faz algo diferente do que a regra diz (por exemplo um campo que a regra chama de obrigatório e o contrato deixou opcional), sempre com `observacao` dizendo o que difere e por quê; `NAO_IMPLEMENTADA` só com a lacuna correspondente. A regra que fica em aplicação diferente da que a fase 19 indicou é `CONFORME` se o comportamento está certo, com a observação de onde ela ficou.

Restrições:

1. Âncora é trecho literal do código, nunca descrição. O gerador recusa a interpretação se uma âncora não for encontrada no arquivo.
2. Nenhuma regra sem âncora e nenhuma regra inventada: as chaves `<funcionalidade>.<regra>` são exatamente as do rastreio da fase 19.
3. Não altere os contratos da fase 20 nem os relatórios anteriores; complemento de contrato feito no código vai para `decisoes`, com a justificativa.
4. Código de erro devolvido pela API (`code` no problem+json) não precisa ser o ID da regra no rastreio; a ligação é pelo texto da regra e pelo teste.

## Regras que o gerador valida

1. `aplicacoes`: toda aplicação que aparece no rastreio da fase 19 tem uma entrada; `modulo` é pasta do repositório ou `null` com `observacao`.
2. `regras`: uma entrada por chave do rastreio (`funcionalidade`, `regra`), com `implementacao` não vazia (salvo `NAO_IMPLEMENTADA`), `conformidade` em `CONFORME`, `DIVERGENTE` ou `NAO_IMPLEMENTADA`, e `observacao` obrigatória quando não é `CONFORME`.
3. Toda âncora existe no arquivo indicado, abaixo de `apos` quando informado.
4. Toda regra tem ao menos um cenário em `--resultados` (o coletor) e todo cenário cita só regras que existem; regra sem cenário, sem teste unitário, com cenário em falha ou com cenário ponta a ponta sem evidência aparece como pendência no relatório, e o cenário ponta a ponta com regra sem teste unitário aparece na cobertura unitária dos cenários.
5. `decisoes` têm `assunto`, `decisao` e `justificativa`; `premissas` e `lacunas` têm `assunto` e `detalhe`; `confianca` é `CONFIRMED`, `UNCERTAIN` ou `UNKNOWN`.

## Entradas

Leia os relatórios abaixo (`ia/report.json` de cada fase) e o repositório do código gerado. O contrato de colunas é conferido por `prompts/verificar_prompts.py`.

@ler fase=19 bloco="Rastreio das regras de negócio" colunas="Funcionalidade de origem da regra|Regra de negócio|Aplicação|Caso de uso|Aparece nos diagramas de sequência de"
@ler fase=19 bloco="Modelo de recursos aprovados" colunas="Id|Tipo|Nome|Contexto de origem (fase 18)|Confiança|Evidência"
@ler fase=19 bloco="Tabela do diagrama de sequência — Sequência de {x}" colunas="Passo|De|Mensagem|Para|Tipo"
@ler fase=20 bloco="Operações dos contratos" colunas="Arquivo|Método|Caminho|operationId|Funcionalidade|Campos de entrada|Campos de saída|Comandos SQL"
@ler fase=20 bloco="Copybooks" colunas="Arquivo|Lado|Fila de baixa|Fila de alta|Programa|Comando SQL|Operação|Campos"

Também: os contratos em `20 - contracts/ia/contracts/C/` (OpenAPI e copybooks), a carga de dados do ambiente local e as regras dos programas corporativos reproduzidos (documentos do repositório que as descrevem, quando existirem).

## Saída

Um objeto JSON (um arquivo, `implementacao.json`), sem texto fora do JSON.

```json
{
  "projeto": "<repositório>",
  "aplicacoes": [
    {"aplicacao": "<sistema>-bff-<contexto de entrega>", "modulo": "<pasta do módulo>", "observacao": ""},
    {"aplicacao": "<sistema>-fed-<contexto de entrega>", "modulo": null, "observacao": "micro frontend em outro projeto"}
  ],
  "programas_corporativos": [
    {"programa": "<PROGRAMA CORPORATIVO>", "modulo": "<pasta que o reproduz>", "observacao": "reprodução em Java sobre tabelas próprias"}
  ],
  "regras": [
    {"funcionalidade": "F01", "regra": "V01", "conformidade": "CONFORME", "observacao": "",
     "implementacao": [
       {"arquivo": "<módulo>/src/main/java/.../<CasoDeUso>.java", "ancora": "/** Regra F01.V01 · <título da regra> */", "papel": "valida a entrada antes de consultar o mainframe"}
     ]}
  ],
  "decisoes": [{"assunto": "...", "decisao": "...", "justificativa": "...", "confianca": "CONFIRMED"}],
  "premissas": [{"assunto": "...", "detalhe": "..."}],
  "lacunas": [{"assunto": "...", "detalhe": "o que falta e quem decide", "confianca": "UNCERTAIN"}]
}
```

## Como o gerador usa a resposta

`gerar_traceability_to_be.py <analise> <saida> --interpretacao <pasta> --projeto <repositório> --resultados <resultados-testes.json>` valida a interpretação (regras 1 a 5) e recusa tudo se algo não bater. O relatório da fase 21 passa a ter, para a arquitetura alvo implementada: o rastreio por regra (decisões e regra determinística de origem, funcionalidade, aplicação e caso de uso, endpoints do contrato, módulo, código com `arquivo:linha`, cenários de teste e resultado); os casos de uso e os endpoints com as regras e os testes que os garantem; o catálogo de cenários (entrada, esperado, obtido, arquivo e método do teste, evidências e testes unitários das mesmas regras); as evidências de cada cenário (requisição, resposta, logs da cadeia, consultas ao DB2, código e resultado do teste unitário); a cobertura unitária de cada cenário ponta a ponta; o código de cada regra; as execuções; e as decisões, premissas, lacunas e pendências. Sem `--interpretacao`/`--resultados` o gerador recusa: a fase 21 só existe com a prova de teste.
