# Prompt 11: Contratos (Contracts): OpenAPI 3.1 e copybooks COBOL

Cole este arquivo inteiro para a IA, junto com os arquivos listados em "Entradas". A IA devolve a interpretação (JSON) com a qual o gerador `gerar_contracts.py` completa o relatório **contracts** (`20 - contracts/human/report.html`, `20 - contracts/ia/report.json` e os arquivos em `20 - contracts/ia/contracts/`). O gerador monta, só dos relatórios, a estrutura dos contratos (operações, parâmetros, respostas, erros, tipos, copybooks); a IA entrega o que depende de julgamento: nomes e descrições de campo, método e caminho de cada operação de entrada, as listas paginadas, decisões, premissas e lacunas.

## Objetivo

Definir os contratos de cada fronteira da arquitetura alvo aprovada na fase 19:

- **OpenAPI 3.1**, um arquivo por `BFMF`, por `VAS` e por `DOMAIN_MICROSERVICE`.
- **Copybook COBOL**, um arquivo por fila IBM MQ: `Aplicação → MQ_REQ (baixa) → MQ_REQ_ALTA [copybook de requisição] → programa mainframe → MQ_RSP_ALTA [copybook de resposta] → MQ_RSP (baixa) → Aplicação`.

Restrições:

1. Nenhum código de implementação.
2. Nenhum modelo de persistência exposto nos contratos.
3. Os campos vêm da **linhagem de campos** (fase 10, quando existe), não do nome da coluna DB2. Onde não há linhagem, o campo sai marcado como «sem linhagem» e confiança `UNCERTAIN`.
4. Nenhum contrato para recurso que a fase 19 não aprovou.
5. Em OpenAPI, nomes em camelCase; os nomes do sistema original aparecem **somente** em `x-legacy`.
6. Programa, fila, copybook e campos de entrada e saída do mainframe em CAIXA ALTA.
7. As palavras de ligação (de, e, para, do, da, dos, das, o, a, os, as, em, no, na, com, por, of, and, for, the) não entram em identificadores; podem ficar em títulos e textos.
8. Tipos do copybook vêm do tipo SQL da coluna (fase 3): `DECIMAL(p,s)` → `S9(p-s)V9(s)`, `CHAR(n)` → `X(n)`, data → `X(10)`, timestamp → `X(26)`. Tamanho que não vem da fase 3 sai com tamanho padrão e confiança `UNCERTAIN`.

9. **Endpoint é recurso, não ação.** O caminho usa substantivos no plural e identificadores (`/planos-captacao/{numeroPlano}`); nenhum segmento começa por verbo (consultar, listar, pesquisar, incluir, alterar…). A ação é o método HTTP: `GET` consulta e lista, `POST` inclui, `PUT` altera. O verbo só aparece no `operationId`.
10. **Chamada direta ao serviço de destino.** Siga os caminhos das sequências da fase 19: quem precisa do dado chama o serviço dono dele; nenhum serviço faz papel de proxy de outro. Se algum caminho passar por mais de um serviço, aponte na lacuna em vez de criar o encadeamento no contrato.

11. **Listas paginadas.** As listas que o requisito abaixo manda paginar recebem página e tamanho da página na entrada e devolvem, além dos itens, a página, o tamanho, o total de itens do filtro e o total de páginas. A paginação é feita no programa mainframe (a consulta conta o total do filtro e devolve só as linhas da página), então o BFMF e o serviço que executa a lista são paginados juntos.

## Requisitos definidos pelo dono do produto

- A **pesquisa de liberações de venda por canal** (a lista consolidada de liberações: funcionalidade de entrada que pesquisa as liberações e o serviço que executa a consulta consolidada) é **paginada**: 5 itens por página por padrão, no máximo 100 (o limite de ocorrências do copybook de resposta). As demais listas não são paginadas.

Você **não** presume infraestrutura (servidores, autenticação, versionamento). Onde faltar evidência, a confiança é `UNCERTAIN` ou `UNKNOWN` e o assunto vai para as lacunas.

## Regras que o gerador valida

1. `campos`: todo campo que aparece em algum contrato (chave = coluna, ou `COLUNA#inicio` / `COLUNA#fim` para faixas, ou a chave derivada do campo de entrada) tem `nome` em camelCase, sem palavras de ligação, que **não** repete o nome bruto da coluna, e uma `descricao` de negócio.
2. `operacoes` (BFMF): toda funcionalidade de entrada (F01, F02, …) tem `operationId` único em camelCase (verbo + assunto), `metodo` (`GET`, `POST`, `PUT` ou `DELETE`) e `caminho` começando por `/`, sem verbo e sem palavras de ligação; a combinação método + caminho é única. `dispensar` (opcional) lista campos de entrada que o BFMF obtém da resposta de uma chamada anterior e que, por isso, o cliente não envia.
2a. `servicos` (VAS e Domain Microservice): toda funcionalidade que um serviço atende (`recurso` = id do serviço como na fase 19, `funcionalidade`) tem `metodo`, `caminho` (recurso, sem verbo) e `operationId`. Funcionalidades do mesmo serviço com o mesmo método e caminho viram **um** endpoint (união dos campos): é assim que dois usos do mesmo recurso (por exemplo detalhe e produto operacional do plano) saem de `GET /planos-captacao/{numeroPlano}`. Todo `{parâmetro}` do caminho precisa ser campo de entrada da operação.
2b. `paginacao`: uma entrada por operação paginada (`recurso` = id do BFMF ou do serviço, como na fase 19, e `funcionalidade`), com `tamanho_padrao` e `tamanho_maximo` (inteiros, `1 ≤ tamanho_padrao ≤ tamanho_maximo ≤ 100`) e `justificativa`. A operação precisa ser de lista; o serviço paginado precisa executar a lista por cursor; o BFMF paginado precisa chamar ao menos um serviço paginado, e todo serviço paginado precisa ser chamado por um BFMF paginado. Os campos de paginação têm nome fixo, dado pelo gerador (não entram em `campos`): na entrada `pagina` (1 = primeira) e `tamanhoPagina`; na resposta `itens`, `pagina`, `tamanhoPagina`, `totalItens` e `totalPaginas`; nos copybooks `REQ-NUM-PAGINA` e `REQ-QTD-POR-PAGINA` no pedido e `RSP-QTD-TOTAL` no cabeçalho da resposta.
3. Toda decisão tem `justificativa`; todo item tem `assunto` e `detalhe` (lacunas, premissas) ou `decisao` (decisões). `confianca` é `CONFIRMED`, `UNCERTAIN` ou `UNKNOWN`.
4. **Nenhuma referência ao sistema original fora de `x-legacy`.** Nas descrições e nos nomes não cite tabela, coluna, programa, comando SQL nem a palavra «legado». O gerador recusa tudo se sobrar algum.

## Entradas

Leia os relatórios abaixo (`ia/report.json` de cada fase). O contrato de colunas é conferido por `prompts/verificar_prompts.py`.

@ler fase=19 bloco="Modelo de recursos aprovados" colunas="Id|Tipo|Nome|Contexto de origem (fase 18)|Confiança|Evidência"
@ler fase=19 bloco="Comandos SQL: fila de pedido, programa e fila de resposta" colunas="Comando (ou programa corporativo chamado)|Executado por|MQ_REQ|PROGRAM_DB2 ou PROGRAM_CORP|MQ_RSP|Operação|Classes de domínio acessadas"
@ler fase=19 bloco="Tabela do diagrama de sequência — Sequência de {x}" colunas="Passo|De|Mensagem|Para|Tipo"
@ler fase=19 bloco="Integrações e protocolos" colunas="De|Tipo de origem|Para|Tipo de destino|Protocolo|Base"
@ler fase=18 bloco="Delivery Contexts" colunas="Contexto|Nome|Tipo|Componentes|Telas mantidas (fase 15)|Consumido por|Estratégia de leitura|Domain Contexts que usa|Jornada ou finalidade (IA)|Valor entregue ao usuário (IA)|Origem"
@ler fase=18 bloco="Domain Contexts" colunas="Contexto|Nome|Agregado raiz|Categoria|Componentes (classes e comandos)|Funcionalidades que o usam|Operações|Valor de negócio (IA)"
@ler fase=17 bloco="Relação por funcionalidade" colunas="Funcionalidade|Nome|Query|Programa|Operação|Natureza|Padrão SQL|Tabelas|Group Query|Agregado|Como é executada"
@ler fase=17 bloco="Group Queries" colunas="Group Query|Tabelas|Legacy Queries ligadas|Funcionalidades|Por que"
@ler fase=10 bloco="{q}: colunas explicadas" colunas="Papel|Coluna|Destino do dado (fase 4b)|Significado (IA)|Evidência"
@ler fase=10 bloco="{q}: condições do WHERE explicadas" colunas="Trecho do SQL|Papel do predicado (fase 4b)|Origem mais distante|Tipo da origem|Percurso entre programas|Significado (IA)|Evidência"
@ler fase=10 bloco="{q}: campos como parâmetro (VALUES e SET)" colunas="Trecho do SQL|Papel|Origem mais distante|Tipo da origem|Percurso entre programas"
@ler fase=10 bloco="{q}: colunas e condições inferidas dos chamadores" colunas="Parte do SQL|Coluna|Posição na saída ou parâmetro|Operador|Quando|Evidência (comando do chamador)"
@ler fase=03 bloco="Colunas por tabela: tipo, campo COBOL e uso" colunas="Tabela|Coluna|Tipo|Aceita nulo|Campo COBOL|PIC|Uso no SQL"

## Saída

Um objeto JSON (um arquivo), sem texto fora do JSON.

```json
{
  "campos": [
    {"coluna": "<chave como o gerador lista em --planilha>", "nome": "numeroPlano", "descricao": "Número do plano de captação."}
  ],
  "operacoes": [
    {"funcionalidade": "F01", "operationId": "listarPlanosCaptacao", "metodo": "GET", "caminho": "/planos-captacao", "dispensar": []}
  ],
  "servicos": [
    {"recurso": "<id do serviço, como na fase 19>", "funcionalidade": "F01", "metodo": "GET", "caminho": "/planos-captacao", "operationId": "listarPlanosCaptacao"}
  ],
  "paginacao": [
    {"recurso": "<id do BFMF ou do serviço, como na fase 19>", "funcionalidade": "F03", "tamanho_padrao": 5, "tamanho_maximo": 100, "justificativa": "requisito do dono do produto: ..."}
  ],
  "decisoes": [
    {"assunto": "...", "decisao": "o que foi decidido", "justificativa": "por quê, com a evidência", "confianca": "CONFIRMED"}
  ],
  "premissas": [{"assunto": "...", "detalhe": "..."}],
  "lacunas": [
    {"assunto": "...", "detalhe": "o que falta decidir e quem decide", "confianca": "UNCERTAIN"}
  ]
}
```

`campos`, `operacoes` e `servicos` são obrigatórios e cobrem tudo (regras 1, 2 e 2a); `paginacao` cobre as listas do requisito (regra 2b). Nenhum item leva o campo `cenario` (o gerador o recusa). A lista exata de chaves de `campos` sai de `python3 gerar_contracts.py <analise> <saida> --planilha`.

## Como o gerador usa a resposta

Valida nomes, métodos, caminhos, cobertura e a ausência de referências ao sistema original, e recusa a interpretação inteira se algo não bater. Gera os OpenAPI e os copybooks, valida cada arquivo (sintaxe, `$ref`, `operationId` único, colunas 8 a 72, PIC) e mostra no relatório os contratos em estilo Swagger, os copybooks pré-formatados, a rastreabilidade para o sistema original e as pendências (tamanhos deduzidos, linhagem ausente). Acrescenta os campos de paginação às operações e aos copybooks das listas paginadas. Recusa caminho com verbo, serviço sem caminho e contrato com parâmetro de caminho que não é entrada.
