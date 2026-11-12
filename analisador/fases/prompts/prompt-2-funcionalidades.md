# Prompt 2: descoberta de funcionalidades a partir dos relatórios gerados

Cole este arquivo inteiro para a IA, junto com os arquivos listados em "Entradas", com o resultado do prompt 5 (o mapeamento dos comandos SQL, relatório `10 - sql-mapping`) e com o resultado do prompt 1 (as regras de negócio agrupadas). A IA devolve a interpretação (JSON) com a qual o gerador `gerar_fluxos.py` monta o relatório **business-flows** (`12 - business-flows/human/report.html` e `12 - business-flows/ia/report.json`, o mesmo conteúdo nos dois formatos, como nas fases da análise): as mesmas funcionalidades, o mesmo raciocínio e as mesmas informações de saída, ligadas às regras de negócio. Este relatório **não** procura funcionalidades ocultas (compartilhadas entre entry points) nem descobre consultas dinâmicas (isso é do prompt 5): só uma funcionalidade por entry point, o desdobramento das consultas dinâmicas e a ligação ao mapeamento SQL.

## Papel

Você é uma IA que moderniza um sistema legado. Recebe só os relatórios gerados por um analisador estático e dinâmico de COBOL/CICS/DB2 e descobre **o que o sistema faz para o negócio**: uma funcionalidade por entry point, mais a **decisão de desdobrar** o programa corporativo que executa consulta dinâmica em várias funcionalidades, conforme as regras de negócio (fase 11). Você **não** lê código-fonte, não abre outro arquivo e não inventa. Quando faltar informação, escreve a lacuna. As funcionalidades **são** os fluxos de negócio: não crie uma camada separada de "fluxos".

## Entradas

Todas em `<pasta-da-analise>/<fase>/ia/report.json`, mais as regras de negócio do prompt 1 (`grupos` com ids `V01`, `E01`...). Formato: `sections[]` → `blocks[]`; blocos `type: "table"` têm `columns[]` e `rows[]`. Uma célula pode ser texto, número, lista, objeto `{"text": ...}` ou **objeto de dados `{campo: valor}`**: as colunas `Entradas`, `Tabelas de entrada`, `Status DB2/CICS simulados` e `Saídas esperadas` dos cenários vêm assim (por exemplo `{"CAMPO": 100}`), e `Saídas esperadas` traz `outputs`, `calls` e `not_calls`. Não trate objeto como vazio. Contrato de entrada (conferido por `verificar_prompts.py`):

```contrato
@ler fase=00 bloco="Programas" colunas="Programa|Classe"
@ler fase=01 bloco="Programas: chamados ou não" colunas="Programa|Classe|Situação|Motivo"
@ler fase=01 bloco="Tabelas: usadas ou não" colunas="Tabela|Situação|Programas que a acessaram na execução|Programas que a acessam no código|Motivo"
@ler fase=01 bloco="Todas as chamadas" colunas="Programa chamador|Linha|Mecanismo|Programa chamado|Comando|Copybook da área de comunicação"
@ler fase=01 bloco="Recursos por programa" colunas="Programa|Chamadas|Comandos SQL|Tabelas|Cursores|Comandos CICS|Arquivos|Copybooks"
@ler fase=01 bloco="Acesso por programa e tabela" colunas="Programa|Tabela|Operações|Acesso"
@ler fase=06 bloco="Regras de {programa}" colunas="Regra|Tipo|Escopo|Condições (decisão → resultado)|Efeitos de negócio (fluxo, natureza)|Tabelas gravadas|Programas chamados|Entry points"
@ler fase=05 bloco="Mapa de decisão — {programa}" colunas="Código|Tipo|Parágrafo|Linha|Condição ou comandos|Execução"
@ler fase=07 bloco="Ramos alcançáveis por entry point e programa" colunas="Entry point|Programa|Chamado por|Constantes do chamador"
@ler fase=07 bloco="Cenários" colunas="Cenário|Entry point|Status|Entradas|Saídas esperadas"
@ler fase=10 bloco="Tabelas passadas por parâmetro" colunas="Consulta|Tabela descoberta|Serviço que executa a consulta|Programas que passam o nome|Entry points|Como fica na modernização (consulta fixada)"
@ler fase=10 bloco="{x}: uso do serviço por chamador" colunas="Chamador|Tipo de consulta|Finalidade no chamador|Colunas lidas|Retorno tratado|Evidência"
@ler fase=10 bloco="{x}: comando SQL estático que substitui a execução dinâmica" colunas="Código|Quando|Comando SQL estático|Origem|Texto montado no código"
@ler fase=07 bloco="Entry points" colunas="Entry point|Cenários|Programas no fluxo|Ramos do fluxo|Exercitados|%"
```

## Raciocínio (siga nesta ordem)

1. **Escopo da análise dinâmica.** Considere **só** programas e tabelas que algum cenário alcançou: programa com `Situação` diferente de `não chamado` (inclui os "chamados só como mock", que existem mas cujo interior não é conhecido) e tabela com `Situação = usada`. Ignore o resto, em programas, tabelas, regras e linhas de fluxo. Anote o que ficou de fora (vira o problema "análise dinâmica reduz o escopo").
2. **Entry points.** São os valores da coluna `Entry point` da tabela de cenários (fase 7) e as regras (fase 6); o fluxo de cada um se monta com "Todas as chamadas", "Recursos por programa" e "Acesso por programa e tabela" (fase 1). Para cada um, reúna: os programas alcançados com o caminho de chamada e a classe (fase 0), as regras por tipo, as tabelas gravadas e consultadas (só as usadas), os retornos e campos de entrada que aparecem nos cenários (fase 7), e a cobertura.
3. **Entender o que cada entry point faz** lendo, nesta ordem: os **nomes dos cenários** (descrevem o comportamento em cada situação: caso feliz, validação, erro de negócio, erro técnico, borda); as entradas e saídas esperadas; as regras de negócio do prompt 1 cujas regras o entry point alcança (coluna `Entry points`); e as tabelas que ele grava ou só consulta.
4. **Tipo da funcionalidade** (derivável do que toca e de como): `inclusão`/`alteração`/`exclusão` quando grava a tabela com INSERT/UPDATE/DELETE; `consulta` quando só lê; `consulta paginada` quando usa cursor e guarda posição entre chamadas; `consulta de detalhe` quando lê um registro por chave; `lista de domínio` quando devolve opções de preenchimento; `orquestração` quando só chama outro programa.
5. **Escrever a funcionalidade**: nome de negócio (o que o usuário faz), resumo, entradas de negócio (só campos do pedido, sem os técnicos de área de comunicação), **passos** na ordem de execução (cada um com os programas/tabelas que o sustentam), saídas (retornos e mensagens), grupos de regras (ids do prompt 1) que se aplicam, cenários que sustentam o texto e `lacunas`.
6. **Decidir o desdobramento pelas regras de negócio (obrigatório para cada programa que executa consulta dinâmica).** Os comandos SQL dinâmicos e as tabelas passadas por parâmetro foram descobertos e internalizados no prompt 5 (relatório `10 - sql-mapping`, ids `<PROGRAMA>-Qnn`); **não os repita nem os cite aqui**. Na fase 11 (prompt 1) cada um deles já sustenta uma regra de negócio: **você só se refere às regras de negócio (ids `V01`, `C02`...) e nunca aos comandos SQL nem às tabelas dessas consultas** (nada de `PROGRAMA-Qnn` nem de nome de tabela descoberta por parâmetro nos textos). Para cada programa que a fase 10 mostra como serviço de uma consulta dinâmica (seção `dinamicas`, coluna do serviço):
   - **A funcionalidade do serviço assume o novo propósito.** Consulta montada por parâmetro não é preservada: no sistema novo ela é uma consulta fixa. A funcionalidade do serviço genérico descreve o que as regras de negócio dele fazem para o negócio, não "executar o que mandarem"; nome, resumo, entradas e saídas descrevem essa finalidade. As regras de negócio do serviço que **só validam, completam ou roteiam o parâmetro** (nome da tabela, tipo de pesquisa, quantidade pedida, escolha do módulo que executa) deixam de existir na modernização e **não são imitadas**: registre-as em `filtro_consulta_dinamica` (`id`, `tema`, `grupos`, `motivo`). O que continua é o que a consulta fixa faz para o negócio.
   - **Decida se existe mais de uma funcionalidade pela necessidade atendida.** Compare as regras de negócio (prompt 1) do serviço e como cada chamador as aproveita. Uma funcionalidade é tudo o que, em um fluxo, concorre para **um mesmo resultado**: caminhos de sucesso e de erro diferentes, e variações de chave, ponto de partida ou quantidade, ainda atendem a **uma só necessidade**. Quando o serviço sustenta **regras de negócio de consulta distintas, com resultados de formatos diferentes que servem a necessidades e fluxos distintos dos chamadores**, há **mais de uma necessidade** e portanto **mais de uma funcionalidade**. Pergunte, para cada chamador: "que necessidade ele resolve com o resultado dessas regras, e em que fluxo dele?". Chamadores cujas regras atendem à mesma necessidade formam **uma** funcionalidade. Diferenças só de tratamento do retorno pelo chamador são regras do chamador e não criam funcionalidade.
   - **Registre a decisão** em `desdobramentos` (uma entrada por programa-serviço): `programa` (o serviço, como na fase 10), `decisao` (`separar` ou `manter`) e `criterio` (as necessidades identificadas, citando regras de negócio, e por que são uma ou mais).
   - Ao **separar**: não descreva a funcionalidade do programa como um todo; descreva **uma funcionalidade por finalidade**, cada uma como entrada de `funcionalidades` com o mesmo `programa` do serviço, mais `usada_por` (os chamadores, entry points ou programas corporativos, que a usam) e `grupos` (os grupos de regras de negócio do prompt 1 que valem para aquela finalidade; **dois desdobramentos não podem ter o mesmo conjunto de `grupos`**); cada chamador passa a chamar só as funcionalidades de que se serve. Ao **manter**: uma só funcionalidade do programa, com `desdobramentos` registrando por que não se separa.
   - Tabelas descobertas pelo mapeamento pertencem às funcionalidades cujos entry points alcançam o serviço; programa só mockado pode esconder consultas dinâmicas (já registrado em `lacunas` do mapeamento).
7. **Ligar às regras de negócio — sem misturar funcionalidades de entry point e corporativas.** **Cada funcionalidade só lista os grupos cujas regras estão nos programas do seu próprio fluxo**: a funcionalidade de entry point não incorpora regras de programas corporativos (nem das funcionalidades corporativas que ela chama), e a funcionalidade corporativa não incorpora regras do entry point que a chama: a relação entre elas é a chamada (coluna "Chamadas Corporativas" e hierarquia), nunca a cópia das regras. O gerador confere e falha se um grupo citado não tem regras do programa da funcionalidade.  Em cada funcionalidade liste em `grupos` os ids do prompt 1 que a explicam. Todo grupo do prompt 1 deve ser citado por pelo menos uma funcionalidade (como o prompt 1 cria um grupo por retorno, confira os ids novos, por exemplo `V09`, e cite todos os ids de cada assunto nas funcionalidades que os alcançam); todo grupo citado deve ter ao menos uma regra do analisador que o entry point alcança (coluna `Entry points`). Uma regra de negócio pertence a um único programa: cite o id base (por exemplo `C04`) e o gerador liga a funcionalidade às regras de negócio desse id (ids `<código>.<programa>`, por exemplo `C04.PROGA`) cujos programas pertencem ao entry point dela; cite só ids que tenham regras que alcancem esse entry point.
8. **Diagrama macro (para o relatório).** Para cada funcionalidade o diagrama mostra, nesta ordem, validação, consulta, alteração de estado, derivações e valores padrão, auditoria e retorno de sucesso, e ao lado tratamento de erro, outras regras e chamadas corporativas. Quem decide a coluna é a **categoria do grupo** (`V`→validações, `C`→consultas, `A`→alterações, `D`→derivações e valores padrão, `U`→auditoria, `S`→retorno de sucesso, `E`→tratamento de erro, `P`,`O`,`X`→outras regras); as tabelas DB2 entram em consultas (só lidas) ou alterações (gravadas).
8a. **Filtrar regras que não descrevem a funcionalidade.** Antes de montar o diagrama, você decide, sem lista fixa e com justificativa, quais regras de negócio do prompt 1 são controle da plataforma ou do mecanismo e não dizem o que a funcionalidade faz para o negócio. Tema que você sempre avalia: **paginação** (regras que só controlam a continuação, o reinício ou a recusa de uma listagem por faixas). Permissão de acesso não chega aqui: não é regra de negócio (prompt 1). Pergunte de cada grupo: "se o grupo sumisse da descrição desta funcionalidade, o leitor ainda entenderia o que ela faz para o negócio?". Se sim, registre-o na chave `filtro_paginacao`, com `id`, `tema`, `grupos` (ids do prompt 1, por exemplo `V08`) e `motivo` (por que filtrar; o que fica de fora e onde o controle continua descrito). Regra de tipo validação do domínio não é paginação: não a filtre por parecer técnica; filtre só a que é de fato controle do mecanismo, e diga isso no motivo. O gerador tira esses grupos do diagrama macro e da lista de regras de cada funcionalidade, mostra a seção "Regras filtradas das funcionalidades" com o seu motivo. Se nenhum grupo precisa ser filtrado, omita a chave. Filtro sem motivo ou com id de regra inexistente faz o gerador falhar.
9. **Citar a evidência.** A *evidência de um entry point* é a união, em texto: o nome, as entradas e as saídas esperadas dos cenários dele; todas as colunas das regras que o alcançam; os programas alcançados com o caminho; as tabelas gravadas e consultadas; as chamadas (fase 1) feitas pelos programas alcançados; os comandos desses programas no mapa de decisão (fase 5); e as constantes do chamador do entry point (fase 7). Na funcionalidade oculta, a evidência é a união da dos entry points de `usada_por`. `cita` lista literais (nomes de programa, tabela, retorno, constante) que o texto usa e que devem existir na evidência dos entry points envolvidos (regras, cenários, programas, tabelas). `cenarios_contem` lista trechos de nome de cenário que sustentam o texto; cada trecho precisa existir em algum cenário do entry point (ou, na oculta, de algum dos que a usam).
10. **Confiança** (`alta`, `média`, `baixa`) e **lacunas** (nome de negócio não existe nos relatórios, quem chama o entry point, significado de códigos, ordem de uso, conteúdo de programa só mockado).

## Ids, programas corporativos e nomes

Toda funcionalidade tem `id`: `F01`, `F02`... para as de entry point (campo `entry`) e `FC01`... para as de **programa corporativo** (campo `programa` no lugar de `entry`: programa de classe CORPORATIVO na fase 0 que tem regras de negócio dos grupos do prompt 1 e é chamado por entry points ou por outro corporativo; um corporativo com um só chamador também ganha `FC`, porque as regras dele não podem entrar na funcionalidade do chamador). Um dos dois campos, nunca os dois. Exceção: quando a análise do uso de uma consulta dinâmica (passo 6a) decide **separar**, várias funcionalidades têm o **mesmo** `programa`, cada uma com `consulta`, `comandos` e `usada_por`, e cada uma tem o seu próprio id (`FC..`); o gerador cria uma raiz por funcionalidade e as relaciona aos chamadores certos. O `nome` é uma **ação de negócio no infinitivo** (a primeira palavra é um verbo no infinitivo: "Consultar dados do ...", "Listar ...", "Incluir ...", "Alterar ..."; substantivos como "Consulta", "Listagem" ou "Inclusão" no início são recusados), é de negócio, **não cita programa** e **nunca é genérico**: palavras como "serviço comum", "genérico", "variante", "módulo", "rotina" são recusadas, e dois nomes iguais também. Quando o fluxo é genérico (um serviço que lê "o que lhe mandarem", ou uma listagem parecida com outra), descubra o propósito pelas **tabelas que ele acessa** (as próprias, as dos corporativos que chama e as descobertas por consulta dinâmica) e pelo que diferencia o SQL (junções, filtros): o nome precisa conter ao menos um termo que venha do nome de uma tabela do fluxo (o validador confere os quatro primeiros caracteres de cada componente, por exemplo `TTPO_ITEM` → "item", "tipo").  o programa de referência aparece no relatório como "Referência base". O relatório mostra, por funcionalidade, a coluna "Chamadas Corporativas" com os programas corporativos que o fluxo usa.

## Saída

Um objeto JSON (gravar em `interpretacao-fluxos/funcionalidades.json`). O gerador `gerar_fluxos.py <pasta-da-analise> <saida> --interpretacao <pasta>` monta o relatório e **falha** se: algum entry point alcançado não tiver funcionalidade; um literal, grupo ou cenário citado não existir na evidência; um programa que executa consulta dinâmica (fase 10) ficar sem entrada em `desdobramentos`, ou desdobrar funcionalidades sem `usada_por` e `grupos`; um texto citar comando SQL `PROGRAMA-Qnn`.

```json
{
  "filtro_paginacao": {"id": "FL02", "tema": "Paginação", "grupos": ["<id de grupo do prompt 1>"], "motivo": "por que não descreve a funcionalidade e onde o controle continua descrito"},
  "filtro_consulta_dinamica": {"id": "FL03", "tema": "Parâmetros da consulta dinâmica", "grupos": ["E00"], "motivo": "regras que só validam ou roteiam o parâmetro da consulta; na modernização a consulta é estática e fixa"},
  "funcionalidades": [
    {
      "id": "F01",
      "entry": "ENTRYPOINT",
      "nome": "o que o usuário faz, em português de negócio",
      "tipo": "inclusão | alteração | exclusão | consulta | consulta paginada | consulta de detalhe | lista de domínio | orquestração | outro: <texto>",
      "resumo": "o que a função faz e com que regras de negócio",
      "entradas": "campos de negócio do pedido",
      "passos": [{"texto": "o que acontece", "programas": "PROG1 → PROG2 → TABELA"}],
      "saidas": "o que devolve, incluindo retornos e mensagens",
      "grupos": ["V01", "E01", "A01"],
      "cenarios_contem": ["trecho do nome de um cenário"],
      "cita": ["literal que existe na evidência"],
      "confianca": "alta",
      "lacunas": ["o que não se consegue afirmar"]
    }
  ],
  "desdobramentos": [
    {
      "programa": "PROGRAMA que executa consulta dinâmica (como no relatório 10 - sql-mapping)",
      "decisao": "separar | manter",
      "criterio": "as necessidades identificadas, citando regras de negócio, e por que há ou não finalidades distintas entre os chamadores"
    }
  ]
}
```

Um grupo de regras (prompt 1) cujas tabelas nenhum cenário usou continua válido; cite-o e registre a lacuna ("não exercitado na análise dinâmica"). Os nomes de tabela são os que aparecem no relatório da fase 1 (com o qualificador do mapeamento, por exemplo `DB2PRD.TABELA`); a comparação ignora o qualificador.

## Relatório final: layout (quando a ferramenta não existe)

Se você não tem o gerador, entregue o relatório **business-flows** no mesmo modelo das fases da análise, em dois formatos com o mesmo conteúdo: `ia/report.json` (`{title, subtitle, summary:[{label,value}], sections:[{id, title, text, blocks}]}`, com blocos `text`, `table` ou `bands`) e `human/report.html` (a projeção desse JSON: um `<h2>` por seção, uma `<table>` por tabela, o diagrama em SVG, sem JSON na página). O relatório traz só o conteúdo abaixo, nesta ordem de seções. Todo diagrama tem a tabela equivalente. Nos diagramas, cada nó leva `data-n` (o id do nó) e cada ligação e o seu rótulo levam `data-a` e `data-b` (os ids das duas pontas): passar o mouse (ou tocar) num nó destaca as ligações dele e os nós da outra ponta e apaga o resto, como na página que o gerador monta.

1. Cartões do topo: funcionalidades, de entry point, de programa corporativo, tabelas alcançadas.
2. `cobertura`: texto (entry points alcançados, funcionalidades descritas, afirmações sem evidência) e tabela entry point × funcionalidade × tipo × confiança.
3. `diagrama`: **diagrama macro** em faixas (uma linha por funcionalidade; da esquerda para a direita validação, consulta, alteração de estado e retorno de sucesso em ordem de execução, e ao lado tratamento de erro e outras regras; tabelas DB2 em cada coluna, ◇ nas descobertas por consulta dinâmica) mais a tabela equivalente, com link de cada id para a regra de negócio no relatório business-rules.
4. `desdobramentos`: tabela do programa, decisão, critério e funcionalidades (com link). Sem comandos SQL nem tabelas dinâmicas: eles estão na fase 10.
5. Uma seção por entry point, com `id` = entry point e título `ENTRY · nome`: resumo; tipo e confiança; entradas de negócio; passos (passo, o que acontece, programas); saídas; diagrama do fluxo e sua tabela; programas alcançados com regras e fluxos de detalhe; cenários que sustentam o texto; regras de negócio relacionadas (com link; só na visão para IA); lacunas.

Não inclua mapa de dados, grupos por dado gravado nem tabela de programas compartilhados como seções próprias.

## Regras de ouro

- **COD-RETORNO e COD-ERRO.** Em todo texto que você escreve (títulos, textos, resumos, entradas, saídas, `entra`/`sai`, lacunas), chame o código de retorno de `COD-RETORNO`, o código de erro de `COD-ERRO` e o código de mensagem de `COD-MENSAGEM` (por exemplo, `COD-RETORNO 08`, `COD-ERRO 0001`), nunca "retorno", "código de erro" ou "mensagem" soltos quando se referem a esses campos. As tabelas dos relatórios já usam esses nomes nas colunas.

- **Atributos sem o nome do copybook.** Nome de campo vem dos relatórios com o prefixo do copybook (`<COPYBOOK>-E-NOME-CAMPO`). Em todo texto que você escreve (nomes, resumos, entradas, saídas, passos, `entra`/`sai`, lacunas, `porque`, `cita`) escreva o atributo **sem o nome do copybook**: `E-NOME-CAMPO`, nunca `<COPYBOOK>-E-NOME-CAMPO`. Os copybooks estão listados na fase 2 ("Copybooks: usados ou não"); só o prefixo que é nome de copybook sai, o resto do nome fica como está. O gerador confere as citações ignorando o prefixo e tira o prefixo de copybook que sobrar dos relatórios de regras de negócio e de fluxos.

- Só o que está nos relatórios e só o que a análise dinâmica alcançou.
- Funcionalidade = fluxo de negócio. Nada de camada separada de "fluxos".
- Todo entry point descrito; não procure funcionalidades ocultas; todo grupo de regras ligado a alguma funcionalidade.
- Mesmos relatórios devem levar às mesmas funcionalidades; o que for incerto vai para `lacunas`.
