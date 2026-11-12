# Prompt 9: Domain Contexts e Delivery Contexts (DDMS), na estratégia de acesso aos dados da fase 17 (responsibility-segregation)

Cole este arquivo inteiro para a IA, junto com os arquivos listados em "Entradas". A IA devolve a interpretação (JSON) com a qual o gerador `gerar_context_discovery.py` completa o relatório **context-discovery** (`18 - context-discovery/human/report.html` e `18 - context-discovery/ia/report.json`, o mesmo conteúdo nos dois formatos, como nas outras fases). O gerador já calcula, só dos relatórios, os Domain Contexts, o conteúdo de cada contexto e os relacionamentos diretos; a IA entrega o que depende de julgamento.

## Objetivo

Mapear **Domain Contexts** e **Delivery Contexts**, com base no conceito de **DDMS (Delivery and Domain Model Segregation)**, em um sistema legado mainframe, nas etapas sequenciais de refinamento, **na estratégia de acesso aos dados da fase 17**: queries de uma tabela e gravações nos agregados; queries de várias tabelas como Legacy Query dentro de Group Query; os agregados **corporativos** chamam os programas corporativos originais por meio de **LEGACY**, em vez de executar SQL.

1. **Capability Modernization Options.** Classifique cada capacidade de negócio em uma opção de modernização.
2. **DDMS Classification.** Classifique cada capacidade em `Domain`, `Delivery` ou `Mixed_Unresolved`.
3. **Domain Contexts Discovery.** Limite de entrega de valor de negócio: um por agregado.
4. **Delivery Contexts Discovery.** Limite de entrega de valor ao usuário: agrupe as funcionalidades e as Group Queries.
5. **Semantic Context Map.** Relacionamentos entre os contextos e o protocolo de integração.

Você **não** gera código, não presume arquitetura e não lê código-fonte legado: consome os relatórios das fases 12, 15, 16 e 17. Quando faltar informação, registre a lacuna.

## Definições

- **Capacidade de negócio:** grupo coeso de funcionalidades que entrega valor a um stakeholder, independente da forma técnica (programa COBOL, tabela DB2, arquivo VSAM).
- **Bounded Context:** limite semântico com contorno e contrato explícito.
- **Entrega (Delivery) é entrega de valor ao usuário.** Funcionalidades entregues de forma separada só valem se, sozinhas, entregam valor: o que é usado em uma só tela, ou em telas que dependem uma da outra, é **uma entrega só**. Use a fase 15 (telas, jornada e navegação) para decidir o que pode ser agrupado.
- **Nomes próprios, desacoplados do legado:** todo contexto e toda capacidade tem um nome do negócio, que representa o que o contexto é de forma coesa e fechada. O nome **não** cita programa, transação, tabela, query, Group Query, tela (arquivo jsp), classe técnica nem nome de agregado/classe da fase 16 (por exemplo, não use `PlanoCaptacao`, `GQ_...`, `TCAP...`, `TLIBRC_...`): nomeie pelo que o negócio chama (por exemplo, «Liberação de venda por canal», «Catálogo de canais de contratação»).
- **Domain:** o contexto tem lógica de negócio pura (funcionalidades e regras de negócio).
- **Delivery:** o contexto é caracterizado por um propósito de entrega: jornadas de usuário, com operações e estratégia de leitura próprias (consulta original, projeção, API Composition).
- **Domain Context:** se baseia em agregados. **Delivery Context:** se baseia nas funcionalidades e nos grupos de queries consultadas.
- **Semantic Context Map:** grafo de contextos conectados, mostrando os relacionamentos (delivery e domain) e os protocolos (síncrono e assíncrono).

## Fluxo de refinamento

```
[1] Domain Model (fase 16) e estratégia de acesso aos dados (fase 17)
    ↓
[2] Delivery Contexts (baseados em jornadas de usuário)
    → funcionalidades entry point agrupadas  → 1 Delivery Context do tipo Presentation
    → funcionalidades corporativas agrupadas → 1 Delivery Context do tipo Query
    → Group Queries agrupadas → 1 Delivery Context do tipo Query
    ↓
[3] Domain Contexts (baseados em agregados)
    → cada agregado (uma raiz) → 1 Domain Context   (id fixo: DM-<nome do agregado>)
    ↓
[4] Semantic Context Map (Domain Contexts + Delivery Contexts + relacionamentos)
```

## Conferência antes de entregar

Cada Domain Context vira um serviço de domínio (um recurso REST com subrecursos). Antes de fechar a resposta, confira: (1) dois Domain Contexts que as funcionalidades sempre chamam juntos, pela mesma chave, e cuja relação no mapa é só «referência por identidade» de um para o outro **talvez sejam um agregado só**: registre em `lacunas` a sugestão de voltar à fase 16 em vez de aceitar a fragmentação; (2) a relação **Domain→Domain** só existe quando algum caminho de funcionalidade passa de um contexto para o outro; referência por identidade é associação, não chamada (use `protocolos_padrao` com essa justificativa e não crie exceções para elas); (3) um contexto `Query` cuja Group Query foi desfeita por a junção estar dentro de um agregado não existe mais: não o crie; (4) a quantidade de Domain Contexts deve ser a de agregados da fase 16, nem mais nem menos.

## Regras que o gerador valida

1. **Capacidades:** cada funcionalidade da fase 12 (entry points e corporativas) está em **exatamente uma** capacidade. `opcao` é uma de `Retain`, `Rehost`, `Replatform`, `Refactor`, `Rearchitect`, `Rebuild`, `Replace`, `Retire` (Retain: manter; Rehost: mover sem alterar; Replatform: mover com ajustes pequenos; Refactor: reorganizar o código; Rearchitect: mudar o desenho preservando as regras; Rebuild: reescrever a partir das regras; Replace: trocar por produto ou serviço pronto; Retire: desligar). `classe_ddms` é `Domain`, `Delivery` ou `Mixed_Unresolved`. Use `Mixed_Unresolved` quando a evidência mostrar regra de negócio e entrega misturadas que ainda não dá para separar, e diga o que falta em `justificativa_ddms`.
2. **Delivery Contexts:** `tipo` é `Presentation` (jornada do usuário; precisa de ao menos uma funcionalidade **entry point**; recebe também as funcionalidades corporativas que a entrega usa) ou `Query` (leitura entregue separadamente; **precisa ter queries**: Group Queries com Legacy Queries). Cada funcionalidade está em **exatamente um** Delivery Context, e cada Group Query da fase 17 está em exatamente um. Ids livres, únicos, que **não** começam por `DM-` (por exemplo `DC-P01`, `DC-Q01`).
   - **Telas (fase 15).** Entry points que aparecem na **mesma tela mantida** no funil (tabela "Cobertura de programas por tela", coluna "Programas que a tela usa"; programa da funcionalidade = o programa do entry point na fase 12) e, por transitividade, em telas que compartilham funcionalidades, formam a entrega mínima: **devem estar no mesmo Delivery Context** (o gerador recusa o contrário). Vá além quando a jornada das telas (fase 15, "Telas: finalidade, jornada e layout sugerido" e "Endpoints das telas relacionadas") mostrar que uma tela leva à outra (por exemplo, pesquisa → formulário → voltar à pesquisa): é uma entrega só, porque entregar uma sem a outra não dá valor ao usuário. Telas fora do funil (omitidas por cobertura baixa) não foram analisadas: use-as só como indício de reuso de uma funcionalidade por outra entrega.
   - **Funcionalidades corporativas.** Ficam dentro do `Presentation` da entrega que as usa (liste-as em `funcionalidades` dele). Um contexto `Query` **não** pode ter só funcionalidades: se um contexto de leitura não tem queries, empurre as funcionalidades para o Presentation que as usa. Se uma funcionalidade corporativa é usada por mais de uma entrega, deixe-a no Presentation da entrega principal e registre a dependência em `lacunas` ou `premissas`.
   - **Queries de várias tabelas.** As Group Queries **nunca ficam dentro do Presentation:** ficam sempre em um Delivery Context do tipo `Query` (o gerador recusa o contrário); agrupe-as pela **finalidade de leitura** (a mesma pergunta de negócio ou as mesmas tabelas) e o Presentation passa a consumi-las. Todo `Query` informa `group_queries` (não vazio), `estrategia_leitura` (`consulta_original`: a Legacy Query continua como está; `projecao`: modelo de leitura mantido a partir dos domínios; `api_composition`: resposta composta chamando os domínios) e `valor_de_entrega`: o valor que **ele entrega por si só** ao usuário. Se não houver valor próprio, junte as queries a outro contexto Query.
3. **Domain Contexts:** uma entrada por agregado da fase 16, com `nome` próprio do contexto (do negócio, sem o nome do legado nem o nome técnico do agregado) e `valor_de_negocio` (a entrega de valor de negócio que o limite protege). O id do contexto é `DM-<agregado>`.
4. **Relacionamentos** (calculados pelo gerador, só os que existem **diretamente** nas fases de origem, sem transitividade):
   - **Delivery → Domain:** a funcionalidade do contexto usa o agregado (coluna "Agregado" da tabela "Relação por funcionalidade");
   - **Presentation → Query / Query → Query:** a funcionalidade chama uma funcionalidade corporativa de **outro** Delivery Context ("funcionalidades que chamam funcionalidades corporativas"), ou a funcionalidade usa uma Group Query que está em **outro** Delivery Context;
   - **Query (Group Query) → Domain:** a Group Query lê tabelas de um agregado;
   - **Domain → Domain:** associação entre classes de agregados diferentes (fase 16, "Associações entre as classes").
   Relacionamentos dentro do mesmo contexto não existem.
5. **Protocolos.** Em `protocolos_padrao`, uma entrada por **tipo de relacionamento que ocorre no mapa** (`Presentation→Presentation`, `Presentation→Query`, `Presentation→Domain`, `Query→Query`, `Query→Domain`, `Domain→Domain`), com `protocolo` = `sincrono` (chamada que espera a resposta) ou `assincrono` (mensagem ou evento sem espera) e a `justificativa`. Em `protocolos`, **exceções** por par (`de`, `para`, ids dos contextos) quando um relacionamento específico tem protocolo diferente do padrão do tipo. Base do julgamento: o fluxo da fase 12 (a funcionalidade precisa da resposta para seguir? há consistência eventual aceitável?), os cursores da fase 17 (leitura por linha em protocolo assíncrono não faz sentido), e o fato de que `Domain→Domain` é referência por identidade (decida se a consistência entre agregados é imediata ou eventual). Se o relatório não permite afirmar, escolha o mais conservador (`sincrono`) e registre a lacuna.

Não escreva tempos nem quantidades de registros nos textos. Declare em `premissas` o que você supôs e em `lacunas` o que a evidência não permite decidir.

## Entradas

Todas em `<pasta-da-analise>/<fase>/ia/report.json`. Formato: `sections[]` → `blocks[]`; blocos `type: "table"` têm `columns[]` e `rows[]`. Uma célula pode ser texto, número, lista ou objeto `{"text": ...}` (use o `text`).

```contrato
@ler fase=12 bloco="Funcionalidades" colunas="Id|Funcionalidade|Base (referência)|Tipo|Confiança"
@ler fase=12 bloco="{f}: fluxo passo a passo" colunas="Passo|O que acontece|Programas"
@ler fase=15 bloco="Telas → Processos → Programas" colunas="Tela|Processo|Transação|Programa mainframe|Execução|Relação com a tela|Serviços|Managed beans"
@ler fase=15 bloco="Cobertura de programas por tela" colunas="Tela|Situação no funil|Programas (relação direta)|Programas que a tela usa"
@ler fase=15 bloco="Telas: finalidade, jornada e layout sugerido" colunas="Tela|Finalidade|Jornada|Layout sugerido|Confiança|Lacunas"
@ler fase=15 bloco="Endpoints das telas relacionadas" colunas="Tela|Tile(s)|Chegada (regras de navegação)|Saída (ação → resultado → destino)"
@ler fase=16 bloco="Agregados" colunas="Agregado|Categoria|Raiz|Membros|Invariantes do agregado|Por que esta fronteira"
@ler fase=16 bloco="Classes de domínio: tabela física → classe" colunas="Tabela|Classe|Categoria|Agregado|Papel no agregado|Natureza no domínio|Descrição"
@ler fase=16 bloco="Associações entre as classes" colunas="De (todo)|Associação|Cardinalidade|Para (parte)|Cascata|Base|Descrição"
@ler fase=17 bloco="Relação por funcionalidade" colunas="Funcionalidade|Nome|Query|Programa|Operação|Natureza|Padrão SQL|Tabelas|Group Query|Agregado|Como é executada"
@ler fase=17 bloco="Group Queries" colunas="Group Query|Tabelas|Legacy Queries ligadas|Funcionalidades|Por que"
@ler fase=17 bloco="Funcionalidades que chamam funcionalidades corporativas" colunas="Funcionalidade que chama|Nome|Tipo de quem chama|Funcionalidade corporativa chamada|Nome da corporativa"
```

Leia primeiro a fase 15 (telas, jornada e navegação: base do agrupamento das entregas), depois a fase 17 (as tabelas da estratégia são a evidência dos relacionamentos), os agregados e as associações da fase 16 e, para o propósito de cada funcionalidade e as dependências de resposta, o fluxo passo a passo da fase 12.

## Saída

Um objeto JSON (um arquivo), sem texto fora do JSON. Nos Domain Contexts **corporativos** os agregados chamam os programas corporativos originais por meio de LEGACY, então o gerador mostra nessas caixas só o agregado e os nomes dos programas (sem comandos SQL nem FILTERED_SELECT/DIRECT_SELECT).

```json
{
  "capacidades": [
    {"id": "C01", "nome": "Consultar planos de captação", "descricao": "O que a capacidade entrega ao stakeholder",
     "funcionalidades": ["F01", "F08"], "opcao": "Rearchitect", "justificativa_opcao": "por que esta opção",
     "classe_ddms": "Delivery", "justificativa_ddms": "por que Domain, Delivery ou Mixed_Unresolved", "confianca": "alta"}
  ],
  "entregas": [
    {"id": "DC-P01", "tipo": "Presentation", "nome": "Gestão de liberações de venda por canal", "funcionalidades": ["F01", "F08"], "group_queries": [],
     "estrategia_leitura": "", "jornada": "a jornada do usuário que o contexto atende (telas e o que o usuário faz nelas)", "valor_de_entrega": "o valor que a entrega dá ao usuário"},
    {"id": "DC-Q01", "tipo": "Query", "nome": "Consulta consolidada de liberações", "funcionalidades": [], "group_queries": ["GQ_LiberacaoCanalContrato_PlanoCaptacao"],
     "estrategia_leitura": "consulta_original", "jornada": "a pergunta de negócio que o contexto responde", "valor_de_entrega": "por que, sozinho, dá valor ao usuário"}
  ],
  "dominios": [
    {"agregado": "PlanoCaptacao", "nome": "Planos de capitalização", "valor_de_negocio": "o valor de negócio que o limite protege"}
  ],
  "protocolos_padrao": [
    {"relacao": "Presentation→Domain", "protocolo": "sincrono", "justificativa": "por quê"}
  ],
  "protocolos": [
    {"de": "DM-LiberacaoCanalContrato", "para": "DM-PlanoCaptacao", "protocolo": "assincrono", "justificativa": "exceção ao padrão do tipo, por quê"}
  ],
  "premissas": [{"assunto": "...", "detalhe": "..."}],
  "lacunas": [{"assunto": "...", "detalhe": "..."}]
}
```

Regras do JSON: ids de funcionalidade como na fase 12 (`F01`, `FC01`); nomes de Group Query como na fase 17; `confianca` é `alta`, `média` ou `baixa`; `protocolos` pode ser vazio. Nenhum item leva o campo `cenario` (o gerador o recusa).

## Como o gerador usa a resposta

Valida tudo contra os relatórios (cobertura das funcionalidades, das Group Queries e dos agregados; entry points das mesmas telas mantidas no mesmo contexto; contexto Query só com queries (funcionalidades sem query ficam no Presentation); Group Query sempre em contexto Query; valor próprio dos contextos Query; nomes sem o legado; tipos permitidos; protocolo padrão para cada tipo de relacionamento que ocorre) e recusa a interpretação inteira se algo não bater. No relatório, as etapas 1 a 5 trazem o diagrama do mapa de contextos mostrando, dentro de cada contexto, os componentes que o constituem (funcionalidades, Group Queries e Legacy Queries nos Delivery Contexts; classes do agregado e comandos SQL nos Domain Contexts; nos corporativos, o agregado e os programas corporativos chamados por meio de LEGACY), e um resumo do mapa.
