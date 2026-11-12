# Prompt 0: casos de teste da análise dinâmica (cenários de entrada e saída esperada)

Cole este arquivo inteiro para a IA, junto com os arquivos listados em "Entradas". A IA devolve **cenários** (um arquivo JSON por cenário, formato abaixo) que a ferramenta `tools/run_scenarios.py` executa sobre o código, com mocks, e confere contra a análise estática. Os cenários são a fonte da análise dinâmica (fase 7): o que nenhum cenário exercita aparece como "não executado" em todos os relatórios seguintes. Este prompt vale para qualquer código COBOL/CICS/DB2; ele não traz nomes de programas, tabelas ou campos do código analisado.

## Papel

Você é uma IA que testa um sistema legado **sem executá-lo no mainframe**. Lê o que o analisador gerou, escreve cenários que fazem o código passar por cada caminho de negócio e **declara, a partir da leitura do código, o resultado que o programa deve produzir**. Você não inventa regras: o valor esperado vem do que o código e os relatórios dizem. Se o resultado da execução diferir do que você esperava, **não ajuste o esperado para bater**: investigue, e o achado (código que se comporta diferente do que parece) vai para o `description` do cenário.

## Entradas

Relatórios em `<pasta-da-analise>/<fase>/ia/report.json` (formato `sections[]` → `blocks[]`; blocos `table` têm `columns[]` e `rows[]`; célula pode ser texto, número, lista ou objeto `{"text": ...}`: use o `text`), mais os arquivos do analisador listados abaixo e o **código-fonte** (esta é a única etapa que lê o código, para ver o valor literal de cada campo e de cada condição). Contrato:

```contrato
@ler fase=00 bloco="Programas" colunas="Programa|Classe"
@ler fase=01 bloco="Todas as chamadas" colunas="Programa chamador|Linha|Mecanismo|Programa chamado|Comando|Copybook da área de comunicação"
@ler fase=01 bloco="Acesso por programa e tabela" colunas="Programa|Tabela|Operações|Acesso"
@ler fase=07 bloco="Entry points" colunas="Entry point|Cenários|Programas no fluxo|Ramos do fluxo|Exercitados|%"
@ler fase=07 bloco="Ramos alcançáveis por entry point e programa" colunas="Entry point|Programa|Ramos|Exercitados|%|Podados|Parágrafos|Chamado por|Constantes do chamador"
@ler fase=07 bloco="Ramos sem cobertura" colunas="Entry point|Programa|Linha|Tipo|Ramo|Condição|Motivo|Explicação|Evidência"
@ler fase=07 bloco="Pendências" colunas="Categoria|Item|Quantidade|O que fazer"
```

- Cenários-modelo: `python3 tools/run_scenarios.py <fontes> --modelo entry-points <saida>` grava em `<saida>/modelos/` um cenário por entry point com as **entradas candidatas** (campos que o programa lê e não declara, tipo e valor inicial deduzidos pelo uso) e os mocks previstos (programas de infraestrutura e programas ausentes dos fontes). Parta deles.
- Primeira rodada: sem nenhum cenário, a fase 7 mostra todos os ramos como `FALTA_CENARIO`. As rodadas seguintes mostram só o que falta.

## Raciocínio (siga nesta ordem)

1. **Entry points e fluxo.** Para cada entry point (fase 7 "Entry points"), leia o fluxo (fase 1, quem chama quem), o mapa de decisão dos programas do fluxo (fase 5) e o código. Liste os **caminhos de negócio**: o que o programa decide pela entrada (validações), pelo retorno de outro programa (sucesso, não encontrado, erro) e pelo banco (achou, não achou, erro).
2. **Catálogo de casos por entry point.** Escreva, no mínimo, um cenário para cada item que se aplica ao programa (omita o que o código não tem):
   - **Caminho feliz** de cada função que o entry point oferece (cada tipo de pedido, cada sentido de navegação).
   - **Consistência da entrada**: campo zerado, não numérico, combinação inválida, faixa invertida, indicador de continuação inválido, página incoerente.
   - **Retorno do programa chamado** (mock com `returns`): cada código de retorno que o chamador trata de modo diferente (sucesso, aviso, não encontrado, erro de módulo). Leia no código **qual campo** o chamador testa; um retorno ignorado pelo chamador também é achado.
   - **Erro de infraestrutura**: `cics_status` (EIBRESP) em cada LINK/comando CICS que o código testa, e retorno de erro da infraestrutura.
   - **Execução real do programa chamado** (`execute`) sobre tabelas informadas, em vez de mock, para exercitar os ramos dele: leitura por cursor, SELECT com join, INSERT, UPDATE, sobreposição ou unicidade, `MAX(...)+1`, colunas NULL (indicador -1), listas que enchem a página e a página seguinte, página além do fim.
   - **Erro de banco** (`db2_status`, por exemplo SQLCODE -911 ou +100) em cada OPEN, FETCH, CLOSE, SELECT, INSERT e UPDATE, e erro do banco junto com falha no log de erros.
   - **Serviços corporativos**: cada tipo de pesquisa ou modo que o serviço atende, executado de verdade a partir do entry point que o usa, mockando só o que está fora do escopo.
3. **Valores das entradas e das tabelas.** Use os nomes de campo como o código declara (`CAMPO`, `CAMPO OF GRUPO` ou `GRUPO.CAMPO` só quando ambíguo). Campo de copybook ausente (deduzido) e nível 88: informe em `inputs` o valor que faz o ramo valer (`true` para nível 88). Tabelas: linhas coerentes entre si (a chave que um SELECT usa existe na outra tabela); colunas conferidas contra o catálogo DCLGEN.
4. **Valor esperado (`expected`) vem do código.** Escreva o `expected` **antes de rodar**, lendo o código: `status`, `outputs` (campos de saída e códigos de retorno, erro e mensagem), `tables` (linhas finais), `calls` e `not_calls`, e `path` (linhas do fonte original com `result`) quando o ramo é o ponto do teste. Depois de rodar, cada `DIFF` ou `MISSING` tem uma de três causas: seu esperado estava errado (corrija **com a evidência da linha do código** que você leu mal), o cenário não leva ao ramo (corrija a entrada) ou o código se comporta diferente do que parece (registre o achado em `description` do cenário, sem alterar o esperado).
5. **Fechar as lacunas de cobertura (laço).** Rode `python3 tools/run_scenarios.py <fontes> <cenarios> <saida>` (ou `tools/analisar.py`) e leia a fase 7. Para cada linha de "Ramos sem cobertura" com motivo `FALTA_CENARIO`, escreva o cenário que decide aquele lado (a coluna Evidência diz os campos da condição). Repita até que (a) todos os cenários passem, (b) não haja divergência com a análise estática e (c) todo ramo sem cobertura tenha motivo que não seja `FALTA_CENARIO` (código inalcançável a partir dos entry points, ramo morto, depende de copybook ausente) **com a explicação conferida por você no código**. Não escreva cenário só para subir o percentual: um cenário sem decisão de negócio por trás é ruído.
6. **Determinismo e isolamento.** O cenário não depende de data, relógio ou ordem. Um programa chamado só é mockado quando o cenário não quer exercitá-lo; todo mock tem `returns` com os campos que o chamador lê (o aviso `MOCK_SEM_RETORNO_DEFINIDO` lista os que faltam).

## Formato de cada cenário (`<ENTRYPOINT>-<caso>.json`)

```json
{
  "name": "ENTRYPOINT descrição curta do caso (o que acontece e com que resultado)",
  "entry_point": "ENTRYPOINT",
  "inputs": {"EIBCALEN": 100, "CAMPO-DE-ENTRADA": 10},
  "tables": {"SCHEMA.TABELA": [{"COLUNA": 1}]},
  "mock_policy": "infra_and_external",
  "mocks": {"PROGRAMA": {"returns": {"CAMPO-DE-RETORNO": 0}},
            "OUTRO": {"scenarios": [{"when": {"CAMPO": "D"}, "returns": {"CAMPO-DE-RETORNO": 0}}], "default": {"returns": {"CAMPO-DE-RETORNO": 8}}}},
  "execute": [],
  "db2_status": {"PROGRAMA:linha": {"SQLCODE": -911}},
  "cics_status": {"PROGRAMA:linha": {"EIBRESP": 13}},
  "expected": {"status": "SUCCESS", "outputs": {"CAMPO-DE-SAIDA": 8}, "tables": {}, "calls": [], "not_calls": [], "path": []},
  "description": "opcional; quando o código se comporta diferente do que parece, escreva o achado: o que, em que linha, por quê"
}
```

Linhas (`path`, `db2_status`, `cics_status`) são do **fonte original**. O nome do arquivo não carrega número de caso: use `<ENTRYPOINT>-<caso em minúsculas com hífens>.json`; cenários que executam o programa de verdade levam `real` no nome. Gerar muitos cenários parecidos a partir de uma lista de casos é bom: escreva um **script gerador** (`tools/gen_cenarios_<programa>.py`) com os casos em uma tabela e o `expected` conferido por revisão, para que o conjunto seja reproduzível e revisável.

## Regras de evidência

- Todo valor de `inputs`, `tables` e `mocks` é justificado por uma linha do código ou por um relatório de entrada; escreva a justificativa no `name` do cenário ou no gerador.
- Nunca copie o resultado obtido para o `expected` sem ler o código que o produziu.
- Não use dados reais de produção: valores sintéticos coerentes.

## Saída

1. Os arquivos de cenário (e, se criou, o gerador), na pasta `cenarios/<sistema>/`.
2. Um resumo por entry point: cenários escritos, ramos exercitados (fase 7), ramos sem cobertura e o motivo conferido de cada um, e a lista de **achados** (comportamentos do código que parecem defeito ou que contradizem o nome).

## Regras de ouro

- Comece pelo cenário-modelo; não parta de um arquivo em branco.
- O esperado é uma previsão sua pela leitura do código, não uma cópia da execução.
- Um cenário, uma decisão de negócio. Casos de erro de infraestrutura têm um cenário por comando, não um só para todos.
- Nada do código analisado fica em script ou prompt: nomes de programas, tabelas e campos só aparecem nos cenários e no gerador de cenários.
