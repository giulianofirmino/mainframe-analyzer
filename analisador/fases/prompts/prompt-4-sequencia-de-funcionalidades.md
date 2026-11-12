# Prompt 4 (teste): fluxo interno de cada funcionalidade (regras em sequência e chamadas corporativas)

Cole este arquivo inteiro para a IA, junto com os arquivos listados em "Entradas". A IA devolve a interpretação (JSON) com a qual o gerador `gerar_sequencia.py` monta, **por funcionalidade**, um diagrama do **fluxo interno**: as regras de negócio dela, **e as chamadas às funcionalidades corporativas quando houver**, numa sequência que faz sentido pela **entrada e saída de cada regra**, cada ligação com a evidência. Não há relacionamento entre funcionalidades neste teste: cada funcionalidade é descrita sozinha. É um teste: usa só o que as fases oficiais já geraram de visão de IA (a fase de teste 4b não entra).

## Papel

Você é uma IA que moderniza um sistema legado. Já existem a lista de funcionalidades (relatório business-flows, fase 12) e as regras de negócio (fase 11). Sua tarefa é descobrir, **dentro de cada funcionalidade**, em que ordem as regras acontecem, onde ela chama uma funcionalidade corporativa e o que cada regra ou chamada entrega à seguinte. Você **não** lê código-fonte, não abre outro arquivo e **não inventa**: toda ligação cita a evidência que a sustenta; o que for hipótese é marcado como hipótese; o que faltar vai para `lacunas`.

## Entradas

Todas em `<pasta-da-entrada>/<fase>/ia/report.json` (formato: `sections[]` → `blocks[]`; blocos `table` têm `columns[]` e `rows[]`; célula pode ser texto, número, lista ou objeto `{"text": ..., "links"|"parts": ...}`: leia o campo `text`; blocos `graph` têm `nodes[]` e `edges[]`):


- `12 - business-flows`: a fonte principal das funcionalidades. Uma seção por funcionalidade (`F01`.., `FC01`.. corporativas): resumo, tipo, entradas de negócio, **passos** (programas e tabelas, na ordem de execução), saídas, cenários, **regras de negócio relacionadas** (tabela com os ids), **relação com as chamadas corporativas** (tabela, quando a funcionalidade chama corporativas), lacunas; o diagrama "quem chama quem" (seção `hierarquia`) e o diagrama macro em faixas (seção `diagrama`: por funcionalidade, as regras por categoria e a coluna "Chamadas Corporativas").
- `11 - business-rules`: as regras de negócio. Tabela "Regras de negócio reunidas" (id, entry points, categoria, programas, funcionalidades) e **uma seção por regra** (`V01.PROGRAMA`...) com as tabelas "COD-RETORNO, COD-ERRO e COD-MENSAGEM" (**saída** da regra), "campos testados e valores comparados" (**entrada** da regra) e "evidência, condições e efeitos de cada regra determinística" (o que a regra faz: valores derivados, tabelas gravadas, programas chamados, retornos). Categoria pela letra do id: `V` validação, `C` consulta, `D` derivação e valores padrão, `A` alteração de estado, `U` auditoria, `S` retorno de sucesso, `E` tratamento de erro, `P`/`O`/`X` outras.
- `01-discovery-dependencies`: "Todas as chamadas" (quem chama quem, mecanismo, área de comunicação, linha), "Acesso por programa e tabela", "Programas: chamados ou não", "Tabelas: usadas ou não".
- `00-program-classification`: classe de cada programa.
- `13 - traceability`: a rastreabilidade; por funcionalidade (`rastreio-<id>`), o que a fase 11 deixou de fora **por escopo** (infraestrutura, mecanismo implícito, fora da abrangência) e o motivo. O gerador lista essas regras por funcionalidade; você não as posiciona no fluxo e elas **não são lacuna**.
- `05-decision-map`: o mapa de decisão (árvore de decisão) de cada programa, com **todo o código** dele: seção `prog-<PROGRAMA>`, um diagrama por parágrafo com as caixas de execução (`Ennn`: comandos, SQL, PERFORM, CALL, CICS) e as decisões (`Dnnn`: a condição escrita como no fonte), e a tabela de cada diagrama. **Em dúvida, leia aqui**: ordem entre regras, de onde vem um valor, em que parágrafo e depois de qual decisão acontece uma gravação ou uma chamada, qual regra chama uma corporativa, condição que o texto da regra não deixa claro. O programa de uma regra é o sufixo do id (`<código>.<PROGRAMA>` → `<PROGRAMA>`).

Quando o texto das fases 11 e 12 não basta para decidir uma ordem, uma ligação ou onde uma corporativa é chamada, consulte o `05-decision-map` do programa (parágrafo, decisão `Dnnn`, caixa `Ennn`) antes de registrar lacuna ou problema; cite o literal que achou lá. Só registre em `lacunas`/`problemas` o que nem o mapa de decisão resolve.

Considere só o que a análise dinâmica alcançou (programa diferente de `não chamado`, tabela `usada`).

## Raciocínio

1. **Componentes de cada funcionalidade F** (não `D..`): as regras de negócio (tabela "regras de negócio relacionadas" da seção de F, o diagrama macro e a coluna "Funcionalidades" da fase 11) e as **funcionalidades corporativas** que F chama (`FC..`: tabela "relação com as chamadas corporativas" da seção de F, coluna "Chamadas Corporativas" do diagrama macro e aresta de F no diagrama `hierarquia`). Cada regra tem **entrada** (campos testados e valores comparados) e **saída** (retorno/código de erro/mensagem e os efeitos: valores derivados, tabelas gravadas, programas chamados). Cada `FC..` tem entradas e saídas na própria seção da fase 12. O pedido da funcionalidade é o nó virtual `ENTRADA` (campos de negócio da seção de F) e o resultado, o nó virtual `SAIDA` (saídas da seção de F). Quando F não chama corporativa nenhuma, o fluxo não tem nó `FC..`.
2. **Onde a corporativa é chamada.** Cada `FC..` entra no fluxo **na posição em que é chamada**: ache a regra (ou o passo) cujos efeitos citam o programa chamador/chamado (fase 1 "Todas as chamadas", passos da fase 12, efeitos da regra na fase 11) e ligue a regra à `FC..` por `chama`; a `FC..` entrega seu retorno (o que a seção dela diz que devolve) à regra seguinte que o usa, por `dado`. Se não for possível dizer qual regra chama, ligue a partir da regra mais próxima pelo passo e marque `ordem`/confiança baixa e a lacuna.
3. **Ordene pela entrada e saída de cada regra**, não por id nem só por categoria. Regra B vem depois de A quando:
   - `dado`: um valor que A **produz** (derivação, coluna lida, retorno de FC, campo preenchido) é um campo que B **testa ou usa**. Cite o campo nos efeitos/saída de A e nos campos testados de B.
   - `condicao`: B só é alcançada se A passar (ou falhar): validação que barra o caminho, `E..` que trata o erro de A. Cite o retorno/código/mensagem de A (ou a condição) que decide.
   - `estado`: A grava uma tabela (ou campo de tabela) que B lê ou confirma.
   - `chama`: F ou uma regra chama a funcionalidade corporativa (`FC..`).
   - `ordem`: sem relação de dado, mas o passo da fase 12 coloca A antes de B (cite o passo); é a ligação mais fraca.
   A categoria dá a ordem natural quando não há dado nem condição: validação → consulta → derivação → alteração → auditoria → retorno de sucesso; as regras `E..` saem como **ramo de erro** da regra que as aciona, sem entrar na linha principal; regras de outras categorias entram onde o dado ou o passo indicar.
4. **Cada funcionalidade só tem as regras que a fase 12 lista para ela** (tabela "regras de negócio relacionadas"): as regras de uma funcionalidade corporativa ficam no fluxo dela, não no da funcionalidade de entry point que a chama (esta só tem o nó `FC..` da chamada), nem o contrário; o gerador falha se um nó de regra não for dela. 4. **Cada regra e cada corporativa aparecem uma vez** como nó, com a posição (`etapa`: 1, 2, ... na sequência principal; os que podem rodar no mesmo ponto compartilham a etapa). Nó sem ligação de dado com nenhum outro entra por `ordem` e ganha lacuna se a posição for dedutiva demais. **Não ligue** por proximidade de id.
5. **Confiança e lacunas**: `alta` (ligação por dado, condição ou chamada com citação nos dois lados), `média` (um lado por inferência do texto), `baixa` (ordem só pelo passo da fase 12, sem apoio no mapa de decisão, ou hipótese).

## Consulta dinâmica internalizada (regra nova com o comando SQL estático)


## Regras de evidência

- `cita` é uma lista de literais (campo, tabela, programa, código de retorno, id de regra ou de funcionalidade) que **existem no texto dos relatórios**, nas seções dos componentes envolvidos (as duas regras, a funcionalidade **com as seções das regras que a fase 12 lista para ela**, a FC) ou no mapa de decisão (`05-decision-map`) do programa de uma das pontas ou, para `chama`, na fase 1 / no diagrama `hierarquia` (aresta escrita `F03→FC01`). O gerador confere cada literal e **falha** se não existir.
- Escopo exato do `cita` (o gerador confere): o texto da seção de cada ponta da ligação (regra ou `FC..`), a seção da funcionalidade com as seções das regras que a fase 12 lista para ela, a fase 13 (`rastreio-<id>`), a fase 1 inteira, a hierarquia da fase 12 e o mapa de decisão dos programas das pontas. Para ligações com `ENTRADA`, `SAIDA` ou nó virtual, a ponta é a própria funcionalidade (seu entry point ou programa corporativo e as regras dela). Um literal que só existe no mapa de decisão de outro programa não vale.
- Nós de erro (`E..`) ligam-se à regra que os aciona e à `SAIDA`; regras de qualquer categoria (`X..`, `U..`, `D..`) são nós de tipo `regra`; ramo que o mapa de decisão marca como não executado pela análise dinâmica entra por `ordem` com a confiança que o mapa sustenta (a ordem estática dos `PERFORM`, citada com o parágrafo e a decisão do mapa, é `alta`) e a lacuna registra que a análise dinâmica não o exercitou.
- Nunca ligue por nome parecido, por ordem de id (`F01`, `V02`) nem por vizinhança de tabela sem leitura/gravação que a sustente.
- Funcionalidade ou regra sem ligação ainda aparece, com a lacuna explicando.

## Saída

Um objeto JSON (gravar em `interpretacao-sequencia/sequencia.json`):

```json
{
  "funcionalidades": [
    {
      "id": "F01",
      "fluxo": {
        "nos": [
          {"id": "ENTRADA", "tipo": "entrada", "rotulo": "pedido: campos de negócio", "etapa": 0},
          {"id": "V01.PROG", "tipo": "regra", "etapa": 1, "entra": "campos que a regra testa", "sai": "o que entrega: retorno, valor derivado, tabela gravada"},
          {"id": "FC01", "tipo": "corporativa", "etapa": 2, "entra": "o que recebe", "sai": "o que devolve"},
          {"id": "E01.PROG", "tipo": "erro", "etapa": 1, "entra": "...", "sai": "..."},
          {"id": "SAIDA", "tipo": "saida", "rotulo": "resultado devolvido", "etapa": 9}
        ],
        "ligacoes": [
          {"de": "ENTRADA", "para": "V01.PROG", "tipo": "dado | condicao | estado | chama | ordem", "porque": "...", "cita": ["literal"], "confianca": "alta"}
        ]
      },
      "lacunas": ["o que não se consegue afirmar"]
    }
  ],
  "problemas": ["afirmação que você queria fazer e não conseguiu sustentar"]
}
```

Uma entrada em `funcionalidades` para **cada** seção `F..` e `FC..` da fase 12 (nas funcionalidades sem regra, `fluxo` pode ter só os nós virtuais). `fluxo.nos` traz **todas** as regras da funcionalidade (as que a fase 12 lista em "regras de negócio relacionadas") e as `FC..` que ela chama, **se houver**; todo nó de regra ou corporativa tem `etapa`, `entra` e `sai` escritos com as palavras dos relatórios. Tipos válidos em `fluxo.ligacoes`: `dado`, `condicao`, `estado`, `chama`, `ordem`; confiança: `alta`, `média`, `baixa`.

## Relatório final (gerado por script)

O gerador `gerar_sequencia.py <pasta-da-entrada> <saida> --interpretacao <pasta>` confere ids, tipos, confiança, se todas as regras e FCs de cada funcionalidade estão no fluxo e as citações, e monta `13 - feature-sequence/human/report.html` e `ia/report.json` (mesmo modelo): por funcionalidade, o diagrama do fluxo interno (ENTRADA → regras e corporativas por etapa → SAIDA, erros em ramo) com as tabelas de nós e de ligações. Você não monta o relatório.

## Revisão final e meta de ligação

Depois de montar todos os fluxos, faça uma **revisão pelo `05-decision-map`**, funcionalidade por funcionalidade: para cada nó e cada ligação, confira no mapa de decisão do programa (parágrafo, ordem dos `PERFORM`, decisão `Dnnn`, caixa `Ennn`) que a ordem e a condição estão certas; corrija o que o mapa contradiz. A meta é **100% ligado**:

- todo nó tem caminho desde `ENTRADA` e chega a `SAIDA` (erro e corporativa incluídos), sem ciclo;
- toda ligação é `alta`: o que o mapa de decisão confirma (ordem dos `PERFORM`, ramo de uma decisão, chamada `LINK`/`CALL`) é `alta` e leva a citação do parágrafo ou da decisão; `média` e `baixa` só para o que nem o mapa decide, e vão acompanhadas de `lacunas`;
- a chamada a uma corporativa costuma ser, na fase 13, uma regra determinística de **roteamento** (mecanismo fora do escopo de negócio): posicione `chama` pela decisão do mapa de decisão, cite o id dessa regra (`<PROGRAMA>:Rnnn`, da fase 13) e a decisão, e registre `alta`; isso **não** é problema;
- `lacunas` e `problemas` só guardam o que o código e os relatórios **não** decidem (módulo fora dos fontes, texto de regra que contradiz a condição, regra que a fase 11 não traz). O que as fases oficiais deixam de fora **por escopo** (infraestrutura, mecanismo implícito, fora da abrangência) não é lacuna: o gerador lista essas regras à parte.

## Regras de ouro

- **COD-RETORNO e COD-ERRO.** Em todo texto que você escreve (títulos, textos, resumos, entradas, saídas, `entra`/`sai`, lacunas), chame o código de retorno de `COD-RETORNO`, o código de erro de `COD-ERRO` e o código de mensagem de `COD-MENSAGEM` (por exemplo, `COD-RETORNO 08`, `COD-ERRO 0001`), nunca "retorno", "código de erro" ou "mensagem" soltos quando se referem a esses campos. As tabelas dos relatórios já usam esses nomes nas colunas.

- **Atributos sem o nome do copybook.** Nome de campo vem dos relatórios com o prefixo do copybook (`<COPYBOOK>-E-NOME-CAMPO`). Em todo texto que você escreve (nomes, resumos, entradas, saídas, passos, `entra`/`sai`, lacunas, `porque`, `cita`) escreva o atributo **sem o nome do copybook**: `E-NOME-CAMPO`, nunca `<COPYBOOK>-E-NOME-CAMPO`. Os copybooks estão listados na fase 2 ("Copybooks: usados ou não"); só o prefixo que é nome de copybook sai, o resto do nome fica como está. O gerador confere as citações ignorando o prefixo e tira o prefixo de copybook que sobrar dos relatórios de regras de negócio e de fluxos.

- Só o que está nos relatórios e só o que a análise dinâmica alcançou.
- Toda ligação tem tipo, motivo, citação e confiança; hipótese é hipótese; ordem por entrada e saída, não por id.
- Corporativa só aparece quando a funcionalidade a chama; sem relação entre funcionalidades.
- Mesmos relatórios devem levar aos mesmos fluxos; o que for incerto vai para `lacunas` ou `problemas`.
- `problemas` só trata do fluxo interno e das chamadas corporativas: cada item começa pelo id da funcionalidade e diz o nó, a ligação ou a corporativa que não se consegue sustentar e por quê. Não registre relação entre funcionalidades (fora do escopo) nem o que já está em `lacunas`.
