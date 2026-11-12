# Prompt 5: mapeamento dos comandos SQL (estáticos e dinâmicos)

Cole este arquivo inteiro para a IA, junto com os arquivos listados em "Entradas". A IA devolve a interpretação (JSON) com a qual o gerador `gerar_sql.py` monta o relatório **sql-mapping** (`10 - sql-mapping/human/report.html` e `10 - sql-mapping/ia/report.json`, o mesmo conteúdo nos dois formatos, como nas fases da análise). Esta fase vem **antes** das regras de negócio (prompt 1) e das funcionalidades (prompt 2): os dois usam o mapeamento como entrada. Este prompt vale para qualquer código COBOL/CICS/DB2; ele não traz nomes de programas, tabelas ou campos do código analisado.

## Papel

Você é uma IA que moderniza um sistema legado. Recebe só os relatórios gerados por um analisador estático e dinâmico e explica **cada query** (comando SQL de cada programa; comandos de leitura equivalentes formam uma query única, ver A.0): o que ele faz para o negócio, o que cada coluna significa, o que cada condição do WHERE seleciona e o que o programa faz com o retorno. Depois descobre as **tabelas que o analisador não enxerga** por serem passadas por parâmetro (consultas dinâmicas) e substitui cada uma por um comando SQL estático. Você **não** lê código-fonte, não abre outro arquivo e não inventa. Quando faltar informação, escreve a lacuna.

## Entradas

Todas em `<pasta-da-analise>/<fase>/ia/report.json`. Formato: `sections[]` → `blocks[]`; blocos `type: "table"` têm `columns[]` e `rows[]`. Uma célula pode ser texto, número, lista ou objeto `{"text": ...}` (use o `text`). A compilação dos comandos SQL estáticos de todos os programas é o **script** que a faz (relatório `10 - sql-mapping`, seção `compilacao-sql`): você recebe os comandos já agrupados por programa, tabela e cursor, com código `<PROGRAMA>-Qnn` (fase 4b). Contrato de entrada (conferido por `verificar_prompts.py`):

```contrato
@ler fase=00 bloco="Programas" colunas="Programa|Classe"
@ler fase=01 bloco="Programas: chamados ou não" colunas="Programa|Classe|Situação|Motivo"
@ler fase=01 bloco="Tabelas: usadas ou não" colunas="Tabela|Situação|Programas que a acessaram na execução|Programas que a acessam no código|Motivo"
@ler fase=01 bloco="Todas as chamadas" colunas="Programa chamador|Linha|Mecanismo|Programa chamado|Comando|Copybook da área de comunicação"
@ler fase=04 bloco="Comandos SQL sobre {tabela}" colunas="Id|Comando|Cursor|Programa|Linha|Parágrafo|SQL|Entry points"
@ler fase=04b bloco="Comandos SQL de {programa}" colunas="Código (link fase 4)|Operação|Tabela|Linhas|Parágrafo|Cursor|Natureza|Executa quando (condições de negócio)|Só executa conforme o status de|Recebe dado de|Entrega dado a|Entry points|Executado"
@ler fase=04b bloco="Condições do WHERE de {programa}" colunas="Comando SQL|Linha|Parte do comando|Trecho do SQL|Papel|Origem mais distante|Tipo da origem|Percurso entre programas|Condição que escolhe esta origem"
@ler fase=04b bloco="Campos como parâmetro de {programa}" colunas="Comando SQL|Linha|Parte do comando|Trecho do SQL|Papel|Origem mais distante|Tipo da origem|Percurso entre programas"
@ler fase=04b bloco="Saídas de {programa}" colunas="Comando SQL|Linha|Coluna lida|Campo que recebe|Uso no código|Destino|Até onde o dado vai|Tipo do fim|Percurso entre programas"
@ler fase=05 bloco="Mapa de decisão — {programa}" colunas="Código|Tipo|Parágrafo|Linha|Condição ou comandos|Execução"
@ler fase=07 bloco="Ramos alcançáveis por entry point e programa" colunas="Entry point|Programa|Chamado por|Constantes do chamador"
@ler fase=07 bloco="Entry points" colunas="Entry point|Cenários|Programas no fluxo|Ramos do fluxo|Exercitados|%"
```

## Raciocínio (siga nesta ordem)

### A. Comandos SQL estáticos: uma análise individual por comando

0. **Unificar as queries equivalentes.** Antes de explicar, compare os comandos SELECT (de todos os programas): os que têm o **mesmo FROM e o mesmo WHERE** (ignore a lista de colunas lidas, o `INTO`, o `ORDER BY`, espaços e maiúsculas; os nomes das variáveis do WHERE contam) são **uma query só**, mesmo que leiam colunas diferentes ou estejam em programas diferentes. O script faz essa mesma unificação no relatório. Dê **uma entrada só** em `comandos_estaticos` para a query única, com `codigo` = o de **menor código** do grupo e `unifica` = os demais códigos; `colunas` é a **união** das colunas lidas pelos comandos do grupo, `proposito` e `retorno` dizem o que cada programa faz com ela (cite o código do comando). Comandos que gravam, ou cujo FROM ou WHERE difere, ficam como estavam.

Para **cada** código `<PROGRAMA>-Qnn` da tabela "Comandos SQL de {programa}" (fase 4b) que não foi unificado em outro, sem pular nenhum, faça:

1. **Ler o comando.** O texto SQL está na fase 4 (tabela "Comandos SQL sobre {tabela}", linha cujo `Id` é `programa@linha:tabela` de uma das linhas do comando). Veja a `Natureza` (lê ou grava), o parágrafo, o cursor, `Executa quando` e `Só executa conforme o status de` (quando o comando executa), `Recebe dado de` e `Entrega dado a` (relação de dados com outros comandos).
2. **Propósito (`proposito`).** Em uma ou duas frases de negócio, para que o programa executa o comando: o que busca, grava ou altera, e para qual decisão ou resultado do programa. Use o nome da tabela, as colunas, as condições e o que o programa faz com o dado (tabela "Saídas"), nunca o nome do programa como explicação.
3. **Colunas (`colunas`).** Uma entrada para **cada coluna** que o comando lê (tabela "Saídas": `Coluna lida`) ou grava (lista de colunas do INSERT, lado esquerdo do SET do UPDATE): `coluna`, `significado` (o que a coluna representa para o negócio, deduzido do nome da coluna, da condição em que aparece, do campo que a recebe e do destino do dado; se o nome não bastar, diga "significado não deduzível dos relatórios" em vez de inventar) e `cita` (literal presente na evidência: trecho do SQL, campo que recebe, destino).
4. **Condições (`condicoes`).** Uma entrada para **cada trecho do WHERE** (tabela "Condições do WHERE", coluna `Trecho do SQL`): `coluna` (a coluna do trecho), `significado` (que linhas a condição escolhe e por quê, usando a origem do valor: `Origem mais distante`, `Tipo da origem` e o percurso entre programas; junções entre tabelas e predicados de ordenação ou limite também são explicados) e `cita`. Se vários trechos usam a mesma coluna, um `significado` que os cubra todos basta, mas a diferença entre eles (por exemplo igualdade e maior-que na paginação) deve aparecer no texto.
5. **Retorno (`retorno`).** O que o programa faz com o resultado: o que acontece quando acha, não acha (SQLCODE +100), erro, quando devolve mais de uma linha (cursor, FETCH em laço), e para onde o dado vai (tabela "Saídas": `Destino` e `Até onde o dado vai`). Cite os campos de retorno que aparecem nos relatórios.
6. **Relação com outros comandos.** Quando `Recebe dado de` ou `Entrega dado a` não está vazio, diga em `proposito` ou `retorno` qual dado passa de um comando a outro (a coluna lida de um que vira condição ou valor do outro). O diagrama do relatório mostra essa relação; o texto a explica.
7. **Confiança** (`alta` quando propósito, colunas e condições estão sustentados por evidência nos dois lados; `média` quando algum significado é inferido pelo nome; `baixa` quando o propósito é suposição) e **lacunas** (o que não se consegue afirmar).

Cada query é explicada **sozinha**: não escreva "igual ao comando anterior". Comandos de cursor do mesmo cursor (DECLARE, OPEN, FETCH, CLOSE) já vêm agrupados em um código; explique o conjunto uma vez, dizendo o papel de cada etapa no `retorno`.

### B. Consultas dinâmicas (tabelas passadas por parâmetro)

A análise determinística só liga programa a tabela quando o nome aparece num comando SQL. Quando um programa pede dados a um **serviço genérico** (um programa chamado que lê "o que lhe mandarem") e informa **qual tabela ou objeto** num campo do bloco de parâmetros, a tabela só existe como valor. Procure esse comportamento assim, sem partir de nenhum nome conhecido:

1. **Candidatos**: nos comandos do mapa de decisão (fase 5, coluna `Condição ou comandos`, execuções `executado`) e nas `Constantes do chamador` (fase 7), ache valores fixos atribuídos a campos cujo nome indica tabela, objeto, entidade, arquivo ou domínio, perto de um CALL/LINK/XCTL a outro programa (use as chamadas da fase 1 para ver o programa chamado e a área de comunicação). Vale também o inverso: um programa com EXEC SQL com nome de tabela em variável ou PREPARE/EXECUTE IMMEDIATE.
2. **Confirmar o repasse**: no programa chamado (se não for só mock), procure onde esse campo é copiado para outro campo ou usado para acionar outro programa; isso mostra que o valor decide o que é lido.
3. **Completar a análise**: cada literal descoberto é uma tabela consultada pelo programa que o passa e, por consequência, pelos entry points que alcançam esse programa (colunas `Entry point` e `Chamado por` da fase 7).
4. **Tabelas fora do mapeamento**: a tabela descoberta pode não constar nas fases 1 e 3; registre isso (o script marca) e não invente colunas nem relacione com tabelas DB2 mapeadas pelo nome parecido. Programa **só mockado** pode esconder consultas dinâmicas: escreva em `lacunas`.
5. **Usos (`usos`, obrigatório).** Leia **como cada chamador usa** o serviço (comandos do mapa de decisão dos chamadores, cenários, chamadas) e registre uma linha por chamador e tipo de consulta: `chamador`, `tipo_consulta` (tipo de pesquisa, modo ou ramo que o chamador aciona, com chave e quantidade pedidas), `finalidade` (a necessidade que o chamador resolve com o resultado), `colunas_lidas` (posições ou colunas que o chamador lê da saída), `retorno_tratado` (COD-RETORNO, COD-ERRO e COD-MENSAGEM que ele aceita, converte ou trata como erro) e `cita` (literal do comando do chamador). Quem decide, depois, se esses usos viram uma ou mais funcionalidades é o prompt 2.
6. **Internalizar a consulta (regra de modernização).** Consulta montada por parâmetro **não é preservada**: no sistema novo ela é um **comando estático com a tabela fixada dentro do programa**. Preencha `internalizacao`: `proposito` (o novo propósito em uma frase, focado no que a tabela serve para o negócio), `comando_fixo` (o **comando SQL estático** que substitui a execução dinâmica, com a tabela fixa e variáveis hospedeiras), `origem` (`montagem detectada` quando o texto SQL montado aparece na fase 1, com `montagem` copiando esse texto; ou `inferido dos parâmetros`), `executa_em` (o código `PROGRAMA:Ennn` da **caixa de execução do mapa de decisão (fase 5) do serviço** que executa o comando principal: normalmente o `PERFORM` do parágrafo que monta e roda aquela consulta; o gerador usa a coluna `Execução` dessa caixa para mostrar tracejado o comando que nenhum cenário executou), `variantes` (um SQL por modo de pesquisa que muda o comando, com `quando` e o `executa_em` da caixa que o executa, do mesmo jeito), `colunas_select` (cada coluna do SELECT com `posicao` na área de saída e `usada_em`, inferidas pelo uso nos chamadores) e `condicoes_where` (cada condição com `coluna`, `operador`, `parametro`, `para` e `cita`). O gerador numera cada comando estático resultante com o código `<SERVIÇO>-Qnn` (o programa que executa a consulta, continuando a numeração dos comandos estáticos dele, no mesmo padrão da fase 4b) e o explica como os comandos da parte A (origem, colunas, condições).
7. **Confiança** e **lacunas**.

## Saída

Um objeto JSON (gravar em `interpretacao-sql/mapeamento.json`). O gerador `gerar_sql.py <pasta-da-analise> <saida> --interpretacao <pasta>` monta o relatório e **falha** se: algum comando estático da fase 4b não tiver explicação; uma coluna lida ou gravada, ou um trecho do WHERE, ficar sem explicação; um literal citado não existir na evidência do comando; em `consultas_dinamicas`, o serviço não for alcançado, a citação do campo e da tabela não existir nos comandos do programa que a passa, ou o `comando_fixo` não for SQL nem citar a tabela fixada, ou o `executa_em` do comando principal ou de uma variante não for uma caixa de execução (`Tipo` = execução) do mapa de decisão do serviço.

```json
{
  "comandos_estaticos": [
    {
      "codigo": "<PROGRAMA>-Qnn (como na fase 4b; na query única, o menor código do grupo)",
      "unifica": ["outros códigos <PROGRAMA>-Qnn unificados nesta query única (omitir se não há)"],
      "proposito": "para que o programa executa o comando, em português de negócio",
      "colunas": [{"coluna": "COLUNA_X", "significado": "o que representa para o negócio", "cita": "literal da evidência (trecho do SQL, campo que recebe, destino)"}],
      "condicoes": [{"coluna": "COLUNA_X", "significado": "que linhas a condição escolhe e por quê", "cita": "literal da evidência (trecho do SQL ou origem)"}],
      "retorno": "o que o programa faz com o resultado: achou, não achou, erro, várias linhas, para onde vai o dado",
      "confianca": "alta | média | baixa",
      "lacunas": ["o que não se consegue afirmar"]
    }
  ],
  "consultas_dinamicas": [
    {
      "id": "D01",
      "titulo": "o que o serviço genérico lê, em português de negócio",
      "servico": "PROGRAMA genérico que executa a consulta (alcançado na análise dinâmica)",
      "parametro": "CAMPO-DE-PARAMETRO que recebe o nome da tabela",
      "mecanismo": "como o nome chega à consulta (quem move o valor, para onde é repassado)",
      "resumo": "...",
      "passos": ["como você descobriu, na ordem"],
      "tabelas": [{"nome": "NOME_DA_TABELA", "passado_por": ["PROGRAMA que preenche o campo"], "cita": "CAMPO-DE-PARAMETRO = \"NOME_DA_TABELA\" (como aparece na coluna Condição ou comandos do mapa de decisão desses programas)"}],
      "cita": ["literal do repasse dentro do serviço, se visível"],
      "usos": [{"chamador": "PROGRAMA", "tipo_consulta": "tipo de pesquisa, chave e quantidade", "finalidade": "para que usa o resultado", "colunas_lidas": "posições ou colunas lidas", "retorno_tratado": "COD-RETORNO, COD-ERRO, COD-MENSAGEM tratados", "cita": "literal do comando do chamador"}],
      "internalizacao": {"proposito": "o novo propósito, focado na tabela, em uma frase", "comando_fixo": "SELECT ... FROM TABELA_FIXA WHERE ... = :variavel (comando estático)", "origem": "montagem detectada | inferido dos parâmetros", "montagem": "texto montado como aparece na fase 1 (só em montagem detectada)", "executa_em": "PROGRAMA:Ennn", "variantes": [{"quando": "condição da entrada", "sql": "comando estático", "executa_em": "PROGRAMA:Ennn"}], "colunas_select": [{"coluna": "COLUNA_X", "posicao": "AREA-DE-SAIDA[1:3]", "usada_em": ["PROGRAMA"], "cita": "literal do comando do chamador"}], "condicoes_where": [{"coluna": "COLUNA_X", "operador": "=", "parametro": ":variavel-hospedeira", "para": "comando principal ou o quando da variante", "cita": "literal do comando do chamador"}], "colunas_nao_inferidas": "só se nenhuma coluna puder ser inferida"},
      "usada_por": ["ENTRYPOINT que alcança o serviço"],
      "confianca": "média",
      "lacunas": ["..."]
    }
  ]
}
```

Os nomes de tabela são os que aparecem no relatório da fase 1 (com o qualificador do mapeamento, por exemplo `DB2PRD.TABELA`); a comparação ignora o qualificador.

## Relatório final: layout (quando a ferramenta não existe)

Entregue o relatório **sql-mapping** no mesmo modelo das fases da análise, em dois formatos com o mesmo conteúdo: `ia/report.json` (`{title, subtitle, summary, sections:[{id, title, text, blocks}]}`) e `human/report.html` (projeção desse JSON, sem JSON na página). Nos diagramas, cada nó leva `data-n` (o id do nó) e cada ligação e o seu rótulo levam `data-a` e `data-b` (os ids das duas pontas): passar o mouse (ou tocar) num nó destaca as ligações dele e os nós da outra ponta e apaga o resto, como na página que o gerador monta. Seções, nesta ordem: `cobertura` (comandos por programa); `unificacao` (tabela "Queries equivalentes unificadas": Query única, Comandos unificados, Programas, Tabelas, FROM e WHERE equivalentes, Colunas lidas (união)); `visao-geral` (diagrama programa → comando SQL → tabela e a tabela equivalente); `compilacao-sql` (todos os comandos, por programa e linha); uma seção `prog-<PROGRAMA>` por programa (diagrama de quem o chama, comandos que executa e tabelas, tabela equivalente, diagrama da relação de dados entre os comandos do programa e tabela); uma seção por comando `<PROGRAMA>-Qnn` (texto SQL, propósito, retorno, onde e quando executa, diagrama de **origem dos dados** do comando: comandos que entregam dado, origem mais distante, trecho do SQL, comando, coluna lida, fim do caminho, comandos que recebem dado; colunas explicadas; condições explicadas; campos como parâmetro; lacunas); `dinamicas` e uma seção por consulta dinâmica `Dnn`; os comandos dinâmicos têm seção própria `<SERVIÇO>-Qnn` como os estáticos, e o diagrama `visao-geral` liga programa → comando SQL → tabela só para os comandos (estáticos e dinâmicos) que a análise dinâmica executou. Todo diagrama tem a tabela equivalente; cores: comando que lê azul-petróleo, comando que grava roxo, borda do programa pela classe.

## Regras de ouro

- **Uma query, uma análise.** Cada query (comando SQL, ou o grupo de SELECT com o mesmo FROM e WHERE) é explicada individualmente, com colunas e condições; nenhuma fica só "mostrada". Os códigos unificados vão em `unifica`.
- **COD-RETORNO e COD-ERRO.** Em todo texto que você escreve, chame o código de retorno de `COD-RETORNO`, o código de erro de `COD-ERRO` e o código de mensagem de `COD-MENSAGEM`.
- **Atributos sem o nome do copybook.** Nome de campo vem dos relatórios com o prefixo do copybook (`<COPYBOOK>-E-NOME-CAMPO`). Em todo texto que você escreve (propósito, significados, retorno, `cita`, lacunas) escreva o atributo **sem o nome do copybook**: `E-NOME-CAMPO`. Os copybooks estão na fase 2 ("Copybooks: usados ou não"). O gerador confere as citações ignorando o prefixo.
- Só o que está nos relatórios e só o que a análise dinâmica alcançou, no caso das consultas dinâmicas. Significado que o nome não permite deduzir vai como "não deduzível" e entra em `lacunas`, nunca como suposição.
- Mesmos relatórios devem levar às mesmas explicações; o que for incerto vai para `lacunas`.
