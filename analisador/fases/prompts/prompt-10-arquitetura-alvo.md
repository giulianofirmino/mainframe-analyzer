# Prompt 10: Arquitetura alvo (Target Architecture Definition)

Cole este arquivo inteiro para a IA, junto com os arquivos listados em "Entradas". A IA devolve a interpretação (JSON) com a qual o gerador `gerar_target_architecture.py` completa o relatório **target-architecture** (`19 - target-architecture/human/report.html`, `19 - target-architecture/ia/report.json` e `19 - target-architecture/ia/architecture-resource-model.yaml`). O gerador já monta, só dos relatórios, o modelo de recursos, as integrações e os diagramas (C4 níveis 1, 2 e 3, diagrama de domínio, um diagrama de sequência por funcionalidade de negócio e as especificações de UX); a IA entrega o que depende de julgamento: decisões, premissas e lacunas.

## Objetivo

Transformar os Delivery Contexts e os Domain Contexts da fase 18 em recursos de arquitetura alvo, na estratégia de acesso aos dados da fase 17 (queries de uma tabela e gravações nos agregados; queries de várias tabelas em Legacy Query com Group Query; agregados corporativos chamando os programas corporativos originais por meio de LEGACY). O gerador aplica a transformação abaixo, sem inventar recursos:

- Delivery Context `Presentation` → `MFE` + `BFMF`.
- Delivery Context `Query` → `VAS`.
- Domain Context → `DOMAIN_MICROSERVICE`.
- Para cada comando SQL: quatro filas IBM MQ, duas de baixa (a aplicação fala com elas) e duas de alta (o programa mainframe fala com elas): pedido `MQ_REQ` (baixa) → `MQ_REQ_ALTA` e resposta `MQ_RSP_ALTA` → `MQ_RSP` (baixa).
- Programa mainframe (cobol) que executa o SQL no DB2: `PROGRAM_DB2` (lê a `MQ_REQ_ALTA` e responde na `MQ_RSP_ALTA`).
- **Coordenador e funcional** (quando o projeto define `programas_mainframe.funcional` no `analise.config.json`): quem lê a `MQ_REQ_ALTA` e responde na `MQ_RSP_ALTA` é o programa coordenador `PROGRAM_COORD` (`<SISTEMA>1` + 3 letras), que chama com `EXEC CICS LINK` o programa funcional `<SISTEMA>` + o dígito configurado + as mesmas 3 letras: `PROGRAM_DB2` (executa o SQL) ou `PROGRAM_CORP` (chama o programa corporativo). O gerador cria os dois a partir do mesmo nome.
- Fluxo: a aplicação envia o pedido à fila de baixa de pedido, que o passa à fila de alta de pedido; o programa cobol processa a mensagem e responde na fila de alta de resposta, que a encaminha à fila de baixa de resposta, de onde a aplicação a lê.
- **Domínio corporativo:** nos Domain Contexts corporativos, em vez de um conjunto por comando SQL, um conjunto por **programa corporativo** (as caixas da fase 18 trazem os nomes dos programas): as quatro filas e um programa mainframe novo do tipo `PROGRAM_CORP`, que lê o pedido, **chama o programa corporativo original** (que executa o SQL) e responde na fila de alta de resposta. Os comandos SQL do programa corporativo apontam para essas mesmas filas.

Tipos de recurso: `HOST`, `MFE`, `BFMF`, `VAS`, `DOMAIN_MICROSERVICE`, `MQ_REQ`, `MQ_REQ_ALTA`, `MQ_RSP_ALTA`, `MQ_RSP`, `PROGRAM_DB2`, `PROGRAM_CORP` (só no domínio corporativo), `PROGRAM_COORD` (só com coordenador e funcional).

Protocolos permitidos: MFE→BFMF REST; BFMF→VAS REST; BFMF→Domain Microservice REST; Domain→Domain REST (só síncrono justificado); aplicação (BFMF, VAS ou Domain Microservice)→MQ_REQ SEND_BAIXA; MQ_REQ→MQ_REQ_ALTA ENCAMINHA; MQ_REQ_ALTA→PROGRAM_DB2 RECEIVE_ALTA; PROGRAM_DB2→MQ_RSP_ALTA SEND_ALTA; MQ_REQ_ALTA→PROGRAM_CORP RECEIVE_ALTA; PROGRAM_CORP→MQ_RSP_ALTA SEND_ALTA; MQ_REQ_ALTA→PROGRAM_COORD RECEIVE_ALTA; PROGRAM_COORD→MQ_RSP_ALTA SEND_ALTA; PROGRAM_COORD→PROGRAM_DB2 ou PROGRAM_CORP LINK; MQ_RSP_ALTA→MQ_RSP ENCAMINHA; MQ_RSP→aplicação RECEIVE_BAIXA. O **MQ_ADAPTER fica dentro das aplicações**, não fora: as filas se ligam direto à aplicação dona do comando, e não existe elemento de banco lógico nos diagramas.

Nomes das filas, em caixa alta e sem separadores dentro de cada parte, com no máximo 48 posições. Filas de baixa: pedido `FR.<SISTEMA>.<CONTEXTO>.NI<PROPÓSITO DO COMANDO SQL>.REQ` e resposta `FL.<SISTEMA>.<CONTEXTO>.NI<PROPÓSITO DO COMANDO SQL>.RSP` (por exemplo `FR.<SISTEMA>.DADOSBANCARIOS.NICONSDADOSBANCARIOS.REQ`, para o contexto Dados Bancários e o propósito Consulta Dados Bancários). Filas de alta: pedido `<SISTEMA>.QL.REQ.<SISTEMA>.NI<PROPÓSITO DO COMANDO SQL>.01` e resposta `<SISTEMA>.QR.RSP.<SISTEMA>.NI<PROPÓSITO DO COMANDO SQL>.01` (sem o contexto; se outro contexto usa o mesmo propósito, o sufixo sobe para 02, 03...). O gerador monta o nome a partir do nome do contexto e do propósito que você dá a cada comando (o verbo inicial vira abreviação: Consulta→CONS, Lista→LIST, Pesquisa→PESQ, Inclui→INCL, Altera→ALT, Verifica→VERIF) e abrevia palavras longas se passar de 48 caracteres. O programa mainframe segue o padrão `<SISTEMA>1` + 3 letras, com 8 posições (por exemplo, `<SISTEMA>1UBO`), e os copybooks de requisição e de resposta seguem `<SISTEMA>W` + 3 letras, também com 8 posições; o gerador propõe os dois a partir do propósito e mantém os nomes já atribuídos (registro `nomes-atribuidos.json`, usado pelo código gerado). Os copybooks existem, mas não entram nos diagramas.

Você **não** gera código-fonte e **não** presume infraestrutura (identidade, observabilidade, segurança de plataforma). Todo diagrama sai do modelo de recursos; nenhum diagrama pode ter recurso que o modelo não tem. Onde faltar evidência, a confiança é `UNCERTAIN` ou `UNKNOWN` e o assunto vai para as lacunas.

## Caminho percorrido

Antes das decisões, percorra cada funcionalidade de entrada e confirme que o caminho é MFE → BFMF → serviço → filas, com o BFMF (ou o VAS) chamando cada Domain Microservice direto. Ligação REST Domain→Domain só existe se algum caminho passar de um serviço para outro e a justificativa estiver na fase 18; referência por identidade entre agregados não conta (o gerador não cria essa ligação e registra a pendência). Se um serviço só devolveria dado de outro, a fronteira de agregados (fase 16) está errada: registre em `lacunas` em vez de ligar os dois serviços.

## Regras que o gerador valida

1. Nomes em kebab-case, sem as palavras de ligação (de, e, para, do, da, dos, das, o, a, os, as, em, no, na, com, por, of, and, for, the): `tcap-fed-<contexto-de-entrega>`, `tcap-bff-<contexto-de-entrega>`, `tcap-vas-<contexto-de-entrega>`, `tcap-srv-<contexto-de-dominio>`.
2. Todo comando SQL tem as quatro filas (`MQ_REQ`, `MQ_REQ_ALTA`, `MQ_RSP_ALTA`, `MQ_RSP`) e `PROGRAM_DB2`.
3. Todo recurso cuja confiança não é `CONFIRMED` (hoje: `HOST`, `MQ_REQ`, `MQ_REQ_ALTA`, `MQ_RSP_ALTA`, `MQ_RSP`, `PROGRAM_DB2`, `PROGRAM_CORP`, `PROGRAM_COORD` quando houver coordenador e, quando houver, `BFMF`) precisa estar coberto por uma **lacuna** com `tipos` listando o tipo de recurso.
4. Toda decisão tem `justificativa`. Todo item tem `assunto` e `detalhe` (lacunas, premissas) ou `decisao` (decisões).
5. `confianca` é `CONFIRMED`, `UNCERTAIN` ou `UNKNOWN`.
6. **Propósito de cada comando SQL.** Todo comando que aparece na tabela "Comandos SQL mapeados dentro dos contextos" da fase 18 (inclusive o programa corporativo chamado por um Domain Context corporativo) e todo comando SQL que esse programa corporativo executa (tabelas "{q}: onde e quando executa" da fase 10, coluna Programa) tem um item em `comandos`; os comandos de um programa corporativo que só roda chamado por outro (tabela "Programas corporativos chamados por outro programa corporativo" da fase 17) não têm fila própria e não entram com um propósito curto de negócio: verbo (Consulta, Lista, Pesquisa, Inclui, Altera, Verifica) mais o assunto, sem citar tabela, programa ou tela. Dois comandos do mesmo contexto não podem ter o mesmo propósito (o nome da fila precisa ser único).
7. **Nome próprio de cada tela.** Toda tela mantida (fase 15) tem um item em `telas` com um nome do negócio, tirado da finalidade e da jornada, sem citar o arquivo. Os nomes são únicos.
8. **Nenhuma referência ao sistema atual.** Tudo será substituído: não cite telas (arquivos jsp), programas, tabelas, nomes de comando SQL do programa original, nem a palavra «legado» nos textos (só os campos `comando` e `tela` levam o identificador, exatamente como aparece nas entradas, porque é a chave). Use os símbolos do relatório (`CMD-nn` para comandos), os nomes próprios das telas, os nomes das classes de domínio e os nomes dos contextos. O gerador recusa o relatório inteiro se sobrar alguma dessas referências.

## Entradas

Leia os relatórios abaixo (`ia/report.json` de cada fase). O contrato de colunas é conferido por `prompts/verificar_prompts.py`.

@ler fase=18 bloco="Delivery Contexts" colunas="Contexto|Nome|Tipo|Componentes|Telas mantidas (fase 15)|Consumido por|Estratégia de leitura|Domain Contexts que usa|Jornada ou finalidade (IA)|Valor entregue ao usuário (IA)|Origem"
@ler fase=18 bloco="Domain Contexts" colunas="Contexto|Nome|Agregado raiz|Categoria|Componentes (classes e comandos)|Funcionalidades que o usam|Operações|Valor de negócio (IA)"
@ler fase=18 bloco="Relacionamentos do mapa de contextos" colunas="De|Nome de origem|Tipo de origem|Para|Nome de destino|Tipo de destino|Relação|Evidência|Protocolo (IA)|Por que (IA)|Origem do protocolo"
@ler fase=18 bloco="Comandos SQL mapeados dentro dos contextos" colunas="Comando|Classificação|Contexto|Nome do contexto|Tipo do contexto|Como está no contexto"
@ler fase=17 bloco="Relação por funcionalidade" colunas="Funcionalidade|Nome|Query|Programa|Operação|Natureza|Padrão SQL|Tabelas|Group Query|Agregado|Como é executada"
@ler fase=17 bloco="Programas corporativos chamados por outro programa corporativo" colunas="Programa corporativo|Chamado por|Funcionalidade|Comandos SQL que executa"
@ler fase=16 bloco="Agregados" colunas="Agregado|Categoria|Raiz|Membros|Invariantes do agregado|Por que esta fronteira"
@ler fase=15 bloco="Telas: finalidade, jornada e layout sugerido" colunas="Tela|Finalidade|Jornada|Layout sugerido|Confiança|Lacunas"
@ler fase=10 bloco="{q}: onde e quando executa" colunas="Comando original|Programa|Operação|Tabela|Linhas|Parágrafo|Cursor|Natureza"

## Saída

Um objeto JSON (um arquivo), sem texto fora do JSON.

```json
{
  "decisoes": [
    {"assunto": "...", "decisao": "o que foi decidido", "justificativa": "por quê, com a evidência", "confianca": "CONFIRMED"}
  ],
  "comandos": [{"comando": "<identificador como na fase 18>", "proposito": "Consulta dados bancários"}],
  "telas": [{"tela": "<identificador como na fase 15>", "nome": "Pesquisa de liberações de venda"}],
  "premissas": [{"assunto": "...", "detalhe": "..."}],
  "lacunas": [
    {"assunto": "...", "detalhe": "o que falta decidir e quem decide", "confianca": "UNCERTAIN", "tipos": ["MQ_REQ", "MQ_REQ_ALTA", "MQ_RSP_ALTA", "MQ_RSP"]}
  ]
}
```

Nenhum item leva o campo `cenario` (a arquitetura é uma só; o gerador o recusa). `tipos` é opcional e usa só os tipos de recurso listados acima. `comandos` e `telas` são obrigatórios e cobrem tudo (regras 6 e 7).

## Como o gerador usa a resposta

Valida os tipos, a confiança e a cobertura (regra 3) e recusa a interpretação inteira se algo não bater. No relatório, as decisões e as premissas aparecem na seção `lacunas-e-decisoes-pendentes`, junto com as pendências que o gerador calcula (recursos sem decisão, protocolo sem evidência, Kafka, projeções, bancos próprios e ReadStores sem decisão nos relatórios).
