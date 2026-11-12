# Prompt 8: chamadas, latência e N+1 por funcionalidade, na estratégia de acesso aos dados

Cole este arquivo inteiro para a IA, junto com os arquivos listados em "Entradas". A IA devolve a interpretação (JSON) com a qual o gerador `gerar_responsibility_segregation.py` completa a análise por funcionalidade do relatório **responsibility-segregation** (`17 - responsibility-segregation/human/report.html` e `17 - responsibility-segregation/ia/report.json`, o mesmo conteúdo nos dois formatos, como nas outras fases). O gerador já calculou, **só dos relatórios das fases 10, 12 e 17**, a evidência de cada funcionalidade. Você **julga** essa evidência e o gerador confere cada afirmação.

## Objetivo

O relatório descreve a estratégia de acesso aos dados do sistema modernizado. **Os comandos de gravação (INSERT, UPDATE, DELETE) são executados dentro dos agregados** e contam como uma chamada ao agregado dono da tabela.

- As queries de leitura de **uma só tabela** são executadas pelo agregado dono (a funcionalidade compõe chamando o agregado, uma chamada).
- As queries de **várias tabelas** são mantidas como foram descobertas, cada uma em **Query Legacy** executando o próprio SQL: uma chamada por query, mesmo as de lista. Quando duas ou mais Legacy Queries usam **as mesmas tabelas**, ou uma query é usada por **mais de uma funcionalidade**, elas são agrupadas em um **Group Query** (nome coeso `GQ_` + as classes de domínio das tabelas, por exemplo `GQ_LiberacaoCanalContrato_PlanoCaptacao`), que executa as Legacy Queries e é o que a funcionalidade chama. O Group Query só agrupa e organiza: não muda o que cada query faz nem remove chamadas por linha do fluxo. Uma Legacy Query sem par tem um Group Query só dela.
- Os **agregados corporativos** não executam SQL: chamam o **programa corporativo original** por meio de uma camada **LEGACY**, que traduz a chamada do domínio para a interface do programa. A chamada ao programa conta como uma chamada, no lugar da execução do SQL; o tempo do programa e da camada LEGACY entra na latência. O cursor do agregado corporativo é aberto dentro do programa corporativo.
- **A funcionalidade nunca liga direto a um comando SQL**: liga ao agregado (Business core ou corporativo) ou ao Group Query, e esses executam os comandos ou chamam o programa corporativo. O entry point que usa um programa corporativo liga à funcionalidade corporativa, e a corporativa que chama outra corporativa liga a ela; só as ligações que existem são representadas.

Para **cada funcionalidade**, analise a quantidade de chamadas, os problemas de **latência** e, nas que leem **lista ou cursor**, se o fluxo cai no caso **N+1**: a leitura traz N linhas (1 chamada) e, **a cada linha**, o fluxo faz mais uma consulta ou chamada (N chamadas), de modo que o custo cresce com o número de linhas.

## Queries únicas

Na fase 10, comandos SELECT com o mesmo FROM e o mesmo WHERE (mesmo lendo colunas diferentes, em programas diferentes) são **uma query só** (tabela "Queries equivalentes unificadas"). Nas tabelas da fase 17 cada query aparece uma vez, com o código da query única, e as funcionalidades de todos os programas que a executam a chamam. Cite sempre o código da query única (o gerador também aceita o código de um comando unificado e o troca pela query única). Duas leituras que antes eram duas chamadas e agora são uma query contam uma chamada.

## Classificação dos comandos

Cada comando SQL é classificado em um destes sete padrões, e só neles: `AGGREGATION`, `CONDITIONAL_UPDATE`, `DIRECT_INSERT`, `DIRECT_SELECT`, `FILTERED_SELECT`, `MULTI_TABLE_JOIN`, `SELECT_CURSOR` (coluna "Padrão SQL"). A chamada ao programa corporativo aparece como `LEGACY`.

## Fronteira do agregado (já decidida na fase 16)

Uma query que junta tabelas do **mesmo agregado** é consulta do agregado e não entra em Group Query (o gerador já faz assim). Só a junção entre agregados diferentes vira Legacy Query com Group Query. Se, ao julgar as chamadas, você notar que dois agregados são sempre chamados juntos pela mesma chave, e a junção entre eles aparece como Group Query ou como chamada extra, **não contorne no texto**: registre em `lacunas` que a fronteira da fase 16 provavelmente está errada (agregados de mesma chave, usados juntos, são um só: critérios do prompt 7), para a fase 16 ser corrigida antes de seguir.

## Chamada direta, sem proxy

Cada funcionalidade chama **diretamente** cada agregado de que precisa; um agregado não chama outro para devolver o dado do segundo. Descreva `chamadas` assim e não conte referências por identidade entre agregados (fase 16) como chamada. Se a evidência mostrar que uma chamada só se completa passando por outro agregado, diga isso na `latencia` e na `lacuna`.

## O que os relatórios não trazem

Tempo de resposta, número real de linhas e frequência de chamada **não existem** nos relatórios. **Não escreva tempos nem quantidades de registros** (nada de "200 ms", "1000 linhas"): fale de **como o custo cresce** (fixo, cresce com N, cresce com N vezes M) e de **qual chamada é a causa**. O gerador rejeita números de tempo ou volume nos textos. Declare em `premissas` o que você supôs e em `lacunas` o que precisa ser confirmado com dados de produção. A análise de desempenho é **qualitativa**.

## Como julgar

1. **Chamadas.** Conte, a partir da evidência, as chamadas **fixas** (uma vez por execução), as de **cursor** (uma leitura em laço) e as **por linha** (repetidas para cada linha). Some as chamadas corporativas. A fórmula do gerador (`fixas + cursores + N × por linha`) já considera uma chamada por query (ou por chamada ao programa corporativo); confirme ou corrija.
2. **Candidatas a chamada por linha.** Uma leitura que **recebe dado** de um cursor (coluna "Recebe dado de" da fase 10) executa depois de cada linha lida, **se** estiver no laço. Confirme lendo o fluxo da fase 12: o passo diz se acontece "para cada" linha, "quando o código difere do anterior", em um laço ou uma só vez. O que entrega dado ao cursor (executa antes) **não** é por linha.
3. **Chamadas corporativas** (fase 12, "relação com as chamadas corporativas"): dentro do laço são N chamadas de serviço, o N+1 mais caro; fora do laço são fixas.
4. **Veredito de N+1** (um por funcionalidade):
   - `sim`: a cada linha há consulta ou chamada, sem redução. Informe em `por_linha`.
   - `mitigado`: haveria repetição, mas o fluxo a reduz (consulta só quando o valor muda em relação à linha anterior, reaproveita o resultado, limita por página). Explique em `mitigacao` e informe o que ainda se repete.
   - `nao`: lê cursor, mas nada é chamado por linha. `por_linha` vazio.
   - `sem_cursor`: a funcionalidade não lê cursor. Sem `cursores`, sem `por_linha`, gravidade `nenhuma`.
5. **Latência.** Descreva, em palavras, o que faz a latência crescer (soma de chamadas fixas, chamadas por linha, chamada de rede de serviço corporativo, chamada ao programa corporativo por meio de LEGACY, leitura local) e do que ela depende (número de linhas, paginação). `gravidade`: `alta` (N+1 sem mitigação com chamada corporativa ou várias consultas por linha), `média` (N+1 mitigado ou uma chamada por linha), `baixa` (sem chamada por linha, poucas chamadas fixas), `nenhuma` (sem cursor e poucas chamadas).
6. **Recomendação.** Uma ação concreta: reunir as leituras por linha em uma chamada única, carregar os dados em lote antes do laço, reaproveitar o resultado de linhas com o mesmo código, ou manter como está.

## Entradas

Todas em `<pasta-da-analise>/<fase>/ia/report.json`. Formato: `sections[]` → `blocks[]`; blocos `type: "table"` têm `columns[]` e `rows[]`. Uma célula pode ser texto, número, lista ou objeto `{"text": ...}` (use o `text`).

```contrato
@ler fase=12 bloco="Funcionalidades" colunas="Id|Funcionalidade|Base (referência)|Tipo|Confiança"
@ler fase=12 bloco="{f}: fluxo passo a passo" colunas="Passo|O que acontece|Programas"
@ler fase=12 bloco="{f}: relação com as chamadas corporativas" colunas="Relação|Nome|Base (referência)"
@ler fase=10 bloco="Todos os comandos SQL" colunas="Id (fase 4)|Comando|Programa|Linha|Parágrafo|Operação|Cursor|Tabela|SQL"
@ler fase=10 bloco="Queries equivalentes unificadas" colunas="Query única|Comandos unificados|Programas|Tabelas|FROM e WHERE equivalentes|Colunas lidas (união)"
@ler fase=10 bloco="{q}: onde e quando executa" colunas="Comando original|Programa|Operação|Tabela|Linhas|Parágrafo|Cursor|Natureza|Executa quando (condições de negócio)|Recebe dado de|Entrega dado a|Entry points"
@ler fase=17 bloco="Relação por funcionalidade" colunas="Funcionalidade|Nome|Query|Programa|Operação|Natureza|Padrão SQL|Tabelas|Group Query|Agregado|Como é executada"
@ler fase=17 bloco="Group Queries" colunas="Group Query|Tabelas|Legacy Queries ligadas|Funcionalidades|Por que"
@ler fase=17 bloco="Funcionalidades que chamam funcionalidades corporativas" colunas="Funcionalidade que chama|Nome|Tipo de quem chama|Funcionalidade corporativa chamada|Nome da corporativa"
@ler fase=17 bloco="Chamadas por funcionalidade" colunas="Id|Funcionalidade|Queries executadas|Queries com cursor|Chamadas corporativas|Candidatas a chamada por linha (evidência)|Chamadas fixas|Fórmula de chamadas"
@ler fase=17 bloco="Cursores e candidatas a N+1" colunas="Funcionalidade|Query com cursor|Tabela|Executa em|Dado entregue a|Candidatas por linha (evidência)|Executam antes do cursor (evidência)|Passos com laço (fase 12)"
```

Leia primeiro a fase 17 (as tabelas da estratégia são a evidência), depois o fluxo passo a passo de cada funcionalidade da fase 12 e, para cada leitura com cursor ou candidata, a tabela "onde e quando executa" da fase 10.

**O que é evidência e o que é palpite do gerador.** As candidatas vêm só do dado encadeado entre comandos; os passos com laço vêm de palavras como "para cada", "do anterior" e "percorre". Os dois podem errar: uma validação que "percorre" uma lista de erros não é laço. **Você decide** lendo o passo inteiro.

## Saída

Um objeto JSON (um arquivo), sem texto fora do JSON. **Uma entrada por funcionalidade da fase 12.** `cursores` lista as **queries com cursor** (`Q-nn`; o cursor do agregado corporativo é o do programa corporativo que ele chama) e `por_linha` lista queries (`Q-nn`) e `FCnn`:

```json
{
  "funcionalidades": [
    {"funcionalidade": "F01", "veredito": "mitigado", "cursores": ["PGM1XXX-Q01"], "por_linha": ["FC02"],
     "mitigacao": "só chama o serviço quando o código difere do da linha anterior",
     "chamadas": "1 cursor e 1 chamada fixa; a cada linha lida, 1 chamada corporativa quando o código muda",
     "latencia": "cresce com o número de linhas do cursor porque cada mudança de código espera uma chamada de serviço",
     "gravidade": "média", "recomendacao": "…", "confianca": "média", "evidencia": ["PGM1XXX-Q01", "F01 passo 4"]},
    {"funcionalidade": "F02", "veredito": "sem_cursor", "cursores": [], "por_linha": [], "mitigacao": "",
     "chamadas": "…", "latencia": "…", "gravidade": "nenhuma", "recomendacao": "…", "confianca": "alta", "evidencia": ["PGM1ZZZ-Q01"]}
  ],
  "premissas": [{"item": "…", "detalhe": "…"}],
  "lacunas": [{"assunto": "…", "detalhe": "…"}]
}
```

## Regras de qualidade

- **Cobertura total.** Toda funcionalidade da fase 12 tem uma entrada. O gerador lista o que faltar.
- **Coerência com a evidência.** `cursores` só aceita o que a tabela de cursores mostra; `sem_cursor` só para funcionalidade sem cursor, e funcionalidade com cursor nunca é `sem_cursor`. `por_linha`: só queries simples da funcionalidade ou `FCnn` que ela chama.
- **Veredito e chamadas por linha combinam.** `sim` e `mitigado` listam o que se repete por linha; `nao` não lista nada; `mitigado` explica a mitigação.
- **Evidência verificável.** `evidencia` cita passos no formato `F03 passo 5` (o passo existe na fase 12), ids de funcionalidade e comandos `Q-nn`.
- **Sem números de tempo ou volume.** Fale de como o custo cresce e da causa. Textos com "ms", "segundos", "registros" ou "linhas" precedidos de número são rejeitados.
- **Texto próprio e curto.** `chamadas`, `latencia` e `recomendacao` em uma ou duas frases, no vocabulário do relatório (Query Legacy, Group Query, agregado, cursor, programa corporativo, LEGACY).
- **Sem invenção.** Não crie comandos, funcionalidades, agregados nem passos. Decisão de arquitetura é proposta, não fato.
