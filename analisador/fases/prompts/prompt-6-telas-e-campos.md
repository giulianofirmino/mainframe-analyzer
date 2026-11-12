# Prompt 6: telas, campos e remodelagem da interface (aplicação web ↔ transações mainframe)

Cole este arquivo inteiro para a IA, junto com os arquivos listados em "Entradas". A IA devolve a interpretação (JSON) com a qual o gerador `gerar_interface.py` completa o relatório **user-interface-mapping** (`15 - user-interface-mapping/human/report.html` e `15 - user-interface-mapping/ia/report.json`, o mesmo conteúdo nos dois formatos, como nas outras fases). O gerador já calculou, **só dos arquivos da aplicação e do PDC**, o caminho de cada processo (tela → endpoint → ação → managed bean → serviço → processo → transação → programa) e a relação campo a campo entre a tela e o layout da transação mainframe. Esta etapa não refaz esse levantamento: ela dá **sentido de negócio** às telas e aos campos e propõe a **remodelagem** da interface.

### Como ler o relatório da fase 15

- **Escopo (funil).** O relatório só detalha as telas que usam todos ou quase todos os programas da fase pdc-mapping (seção "Funil de telas": situação `mantida`; o diagrama e a tabela "Telas → Processos → Programas" mostram, nessa ordem, a tela, os processos PDC que ela usa e o programa mainframe de cada transação). Telas sem programa mapeado e telas de cobertura baixa não aparecem no restante do relatório; processos sem relação com telas também foram omitidos. Só os programas da fase pdc-mapping contam. Na tabela "Cobertura de programas por tela", `Analisados que a tela não usa` e `Usados mas não executados` são pontos de atenção que você deve citar na `visao_geral` e nas `lacunas` das telas.
- **Setas.** Toda relação é desenhada e escrita com seta no sentido do dado. Caminho do processo: tela → ação → managed bean.método → serviço → processo → transação → programa (o endpoint/tile não fica no meio: a tela aciona o bean direto; o tile aparece só na seção de endpoints). Campos: entrada = campo da tela → propriedade (VO) → campo do processo → campo da transação → programa; saída = programa → campo da transação → campo do processo → propriedade (VO) → campo da tela. Nos selos e na coluna "Relação com a transação", `este campo → …` é entrada e `… → este campo` é saída. Nunca inverta o sentido.
- **Eventos.** Cada tela tem a tabela "Eventos de {tela}", organizada por evento: `onLoad` (ao abrir a tela: construtor/@PostConstruct do bean, getter lido na renderização ou método de entrada sem chamador), `onClick → onSubmit` (botão/link), `onChange`/`onSelect` (ajax do campo), troca de página (paginação). Para cada evento a tabela mostra o componente que dispara, o método do bean, os **beans relacionados**, os componentes afetados (dados carregados), os componentes atualizados na tela (reRender), o processo/programa e a cadeia de chamadas.
- **Origem dos dados.** "Origem dos dados de {tela}" diz, para cada combo, tabela e campo de saída, de qual processo/transação/programa vem, qual método do bean carrega e **quando** (em qual evento).
- **Regras de apresentação.** "Regras de apresentação de {tela}" lista o que esconde/exibe (`rendered`), ativa/desativa (`disabled`, `readonly`), torna obrigatório (`required`), limita (`maxlength`), restringe a digitação por script (máscaras, `onkeypress`) ou muda o estilo, com a propriedade do bean que comanda a regra e os métodos que a alteram (e o valor atribuído).

## Papel

Você é uma IA que moderniza um sistema legado. Recebe só os relatórios do analisador e explica, para quem vai redesenhar a interface: para que serve cada tela, quem a usa e em que momento; o que cada campo significa (a partir do rótulo, do nome da propriedade, do campo do processo e do campo do layout da transação, com seu PIC e tamanho); como os campos devem ser agrupados; e qual componente visual moderno substitui cada componente atual. Você não inventa regras: tudo o que afirmar precisa estar sustentado pelos relatórios, e o que não estiver vai para `lacunas`.

## Entradas

Todas em `<pasta-da-analise>/<fase>/ia/report.json`. Formato: `sections[]` → `blocks[]`; blocos `type: "table"` têm `columns[]` e `rows[]`; blocos `type: "wire"` trazem a árvore de componentes da tela (`arvore[]` com `tipo`, `id`, `rotulo`, `liga`, `acao`, `direcao`, `colunas`, `relacionado`, `filhos`). Uma célula pode ser texto, número, lista ou objeto `{"text": ...}` (use o `text`).

```contrato
@ler fase=14 bloco="Processos distintos" colunas="Processo|Transação (programa PDC)|Programa analisado|Execução"
@ler fase=14 bloco="Programas analisados" colunas="Programa|Classe|Situação na execução|Transações PDC|Processos"
@ler fase=15 bloco="Telas → Processos → Programas" colunas="Tela|Processo|Transação|Programa mainframe|Execução|Relação com a tela|Serviços|Managed beans"
@ler fase=15 bloco="Caminho no backend" colunas="Managed bean|Método do bean|Cadeia de chamadas até o serviço|Onde o bean guarda o retorno|Argumentos passados"
@ler fase=15 bloco="Campos: tela" colunas="Tela|Componente|Id|Rótulo|Ligação (EL)|Direção|Propriedade (VO)|Campo do processo|Transação|Campo do layout|PIC|Bytes|Programa"
@ler fase=15 bloco="Componentes de {tela}" colunas="#|Componente|Tag|Id|Rótulo / texto|Ligação (EL)|Posição na grade|Ação|Relação com a transação|Opções fixas (valor = texto)"
@ler fase=15 bloco="Cobertura de programas por tela" colunas="Tela|Situação no funil|Programas (relação direta)|Programas (direta + bean)|Programas que a tela usa|Analisados que a tela não usa|Usados mas não executados|Usados só por bean (sem campo/ação)|Processos da tela sem programa mapeado"
@ler fase=15 bloco="Processo → transação → programa → adaptador → serviço → bean → telas" colunas="Processo|Transação|Programa mainframe|Programa executado|Adaptador|Serviço (classe.método)|Managed beans|Telas|Exemplos de tela"
@ler fase=15 bloco="Eventos de {tela}" colunas="Evento|Componente que dispara|Atributo|Método do bean acionado|Beans relacionados|Componentes afetados (dados carregados)|Atualizados na tela (reRender)|Processo (programa)|Cadeia de chamadas"
@ler fase=15 bloco="Regras de apresentação de {tela}" colunas="Componente|Tag (id)|Tipo de regra|Atributo|Expressão ou valor|Propriedade que comanda a regra|Onde a propriedade muda (método → valor atribuído)|Componentes afetados"
@ler fase=15 bloco="Origem dos dados de {tela}" colunas="Componente|Tipo|Processo → transação → programa|Campos do layout|Método do bean que carrega|Quando é carregado (evento)|Cadeia de chamadas"
@ler fase=15 bloco="Endpoints das telas relacionadas" colunas="Tela|Tile(s)|Chegada (regras de navegação)|Saída (ação → resultado → destino)|Padrões de URL do servlet"
```

Quando existirem, leia também os relatórios de regras de negócio (fase 11) e de funcionalidades (fase 12) dos programas citados em "Programa mainframe": eles dizem o que o programa decide e valida, o que ajuda a explicar a finalidade e a obrigatoriedade dos campos.

## Raciocínio (siga nesta ordem)

### A. Uma análise por tela (obrigatória para toda tela com componentes na seção `telas`)

Para **cada** tela da seção `telas` (a tabela "Componentes de {tela}" tem o nome dela), sem pular nenhuma:

1. **Finalidade (`finalidade`).** Em uma ou duas frases de negócio: o que o usuário faz nesta tela (consultar, incluir, alterar, escolher um item etc.). Deduza dos botões e suas ações (coluna `Ação`), dos processos ligados aos campos (coluna `Transação`/`Campo do layout`), dos rótulos e do destino da navegação (relatório de endpoints). Nunca use o nome do arquivo como explicação.
2. **Jornada (`jornada`).** Use as tabelas "Eventos de {tela}" e "Origem dos dados de {tela}": diga quando cada combo, tabela e campo é carregado (ao abrir a tela, ao clicar, ao alterar um campo) e o que o evento atualiza. De onde o usuário chega (coluna `Chegada` dos endpoints), o que faz e para onde vai (`Saída`). Se a chegada não aparecer, diga que não há evidência.
3. **Agrupamentos (`agrupamentos`).** Divida os componentes em grupos que façam sentido para o usuário (por exemplo, filtros de pesquisa, resultado, dados do cadastro, ações). Cada grupo: `nome`, `descricao` (por que estes campos andam juntos) e `componentes` (lista de **ids ou rótulos** que existam na tabela de componentes da tela, na ordem em que devem aparecer).
4. **Campos (`campos`).** Uma entrada para **cada componente de entrada ou de saída que tenha rótulo ou id** (caixa de texto, combobox, calendário, checkbox, radio, texto exibido, coluna da listagem), sem pular nenhum: `campo` (o id, ou o rótulo quando não houver id; exatamente como está na tabela), `significado` (o que o dado representa para o negócio, deduzido do rótulo, do nome da propriedade e, quando houver, do campo do layout da transação e do seu PIC/tamanho: por exemplo, um campo numérico de 3 posições que identifica uma categoria é um código; de 30 posições alfanumérico é uma descrição), `obrigatoriedade` (`obrigatório`, `opcional` ou `não determinado`; só afirme obrigatório se a evidência mostrar validação ou uso indispensável na entrada da transação), `tipo_dado` (`código`, `descrição`, `texto livre`, `número`, `valor monetário`, `data`, `indicador sim/não` ou `outro`; vale também o que o PIC indica) e `componente_sugerido` (um dos valores do vocabulário abaixo; escolha pelo significado, não copie o componente atual).
5. **Ações (`acoes`).** Uma entrada para **cada botão ou link com ação**: `acao` (id ou rótulo como está na tabela), `significado` (o que o botão faz para o usuário) e `resultado` (o que acontece depois: processo acionado, mensagem, tela de destino).
6. **Eventos (`eventos`).** Uma entrada para **cada linha** da tabela "Eventos de {tela}": `evento` (como na tabela: onLoad, onClick → onSubmit..., onChange...), `disparador` (o componente que dispara, exatamente como na coluna "Componente que dispara", ou `abertura da tela` para onLoad e entradas externas), `significado` (o que o evento representa para o usuário), `afetados` (o que ele carrega ou atualiza: combos, tabelas, campos, e os componentes do reRender) e `remodelagem` (como o evento deve se comportar na nova interface: carregar ao montar a tela, recarregar ao escolher um valor, desabilitar enquanto carrega etc.). Cite os beans relacionados quando ajudarem a entender a responsabilidade.
7. **Regras de apresentação (`regras_apresentacao`).** Uma entrada para **cada linha** da tabela "Regras de apresentação de {tela}" (agrupe só linhas idênticas do mesmo componente): `componente` (rótulo ou id como na tabela), `regra` (exibir/ocultar, ativar/desativar, somente leitura, obrigatoriedade, limite de tamanho, máscara/restrição de entrada, estilo condicional), `significado` (em linguagem de negócio, em que situação o componente aparece, fica ativo ou é restrito, deduzido da propriedade que comanda a regra e dos métodos que a alteram; se a condição não estiver clara, diga em `lacunas`) e `remodelagem` (como reproduzir a regra na nova interface). Telas sem nenhuma regra devolvem lista vazia.
8. **Layout sugerido (`layout_sugerido`).** Uma descrição da disposição remodelada (ordem dos grupos, o que fica em destaque, o que vira filtro recolhível, onde ficam as ações), em linguagem de produto, sem código.
9. **Confiança** (`alta` quando finalidade e campos têm evidência nos relatórios; `média` quando algum significado é inferido pelo nome; `baixa` quando é suposição) e **lacunas** (o que não se consegue afirmar).

Vocabulário de `componente_sugerido`: `caixa de texto`, `área de texto`, `campo numérico`, `campo monetário`, `campo de data`, `seleção única (lista)`, `seleção única com busca`, `seleção múltipla`, `caixa de marcação`, `opção exclusiva (radio)`, `interruptor sim/não`, `texto somente leitura`, `tabela`, `tabela com paginação`, `botão primário`, `botão secundário`, `link`, `mensagem`, `aba`, `outro`.

### B. Uma análise por processo detalhado

Para **cada** processo da tabela "Telas → Processos → Programas" (um item por processo, mesmo que ele apareça em mais de uma tela; só processos ligados às telas mantidas): `processo` (o nome completo), `finalidade` (o que a transação faz para o negócio, deduzida dos campos de entrada/saída do layout e do programa), `entradas` (os dados que a tela precisa fornecer, com os nomes dos rótulos), `saidas` (o que a transação devolve e como a tela o usa), `confianca`, `lacunas`. Quando um campo do serviço não tem componente de tela (linha com tela "—"), diga em `lacunas` o que isso significa para a remodelagem (valor fixo no serviço, derivado ou não exibido).

### C. Visão do conjunto

`visao_geral`: em um parágrafo, a cobertura do funil (quais telas ficaram e quais programas elas não usam ou não executam), como as telas analisadas se ligam em uma jornada completa do usuário e o que a nova interface deve unificar (por exemplo, filtros repetidos em várias telas, listas de opções carregadas do mesmo processo, ações equivalentes).

## Saída

Um objeto JSON (gravar em `interpretacao-interface/telas.json`; se preferir dividir o trabalho, grave vários arquivos `interpretacao-interface/*.json` com o mesmo formato: cada tela em exatamente um arquivo, `processos` e `visao_geral` em pelo menos um; o gerador junta todos). O gerador `gerar_interface.py <pasta-da-analise> <saida> --aplicacao <pasta> --pdc <pasta> --interpretacao <pasta>` monta o relatório e **falha** se: alguma tela da seção `telas` não tiver análise; um `campo`, `acao` ou item de `agrupamentos[].componentes` não existir na tabela de componentes da tela; algum componente de entrada/saída com rótulo ou id ficar sem entrada em `campos`; `componente_sugerido` fora do vocabulário; algum `evento` ou `regras_apresentacao` citar um `disparador`/`componente` que não existe na tela, ou tiver `significado`/`remodelagem` vazio; algum processo detalhado ficar sem análise; `obrigatoriedade`, `tipo_dado` ou `confianca` fora dos valores permitidos.

```json
{
  "telas": [
    {
      "tela": "<nome da tela exatamente como no título 'Componentes de {tela}'>",
      "finalidade": "...",
      "jornada": "...",
      "agrupamentos": [{"nome": "...", "descricao": "...", "componentes": ["<id ou rótulo>"]}],
      "campos": [{"campo": "<id ou rótulo>", "significado": "...", "obrigatoriedade": "obrigatório|opcional|não determinado",
                  "tipo_dado": "código|descrição|texto livre|número|valor monetário|data|indicador sim/não|outro", "componente_sugerido": "<vocabulário>"}],
      "acoes": [{"acao": "<id ou rótulo>", "significado": "...", "resultado": "..."}],
      "eventos": [{"evento": "<como na tabela Eventos>", "disparador": "<componente que dispara ou 'abertura da tela'>", "significado": "...", "afetados": "...", "remodelagem": "..."}],
      "regras_apresentacao": [{"componente": "<id ou rótulo>", "regra": "exibir/ocultar|ativar/desativar|somente leitura|obrigatoriedade|limite de tamanho|máscara|estilo condicional", "significado": "...", "remodelagem": "..."}],
      "layout_sugerido": "...",
      "confianca": "alta|média|baixa",
      "lacunas": ["..."]
    }
  ],
  "processos": [
    {"processo": "<nome completo do processo>", "finalidade": "...", "entradas": "...", "saidas": "...", "confianca": "alta|média|baixa", "lacunas": ["..."]}
  ],
  "visao_geral": "..."
}
```

## Regras de qualidade

- Cada tela e cada campo é explicado **sozinho**; não escreva "igual à tela anterior". Telas que repetem os mesmos campos ainda recebem uma análise cada uma, citando o contexto de cada uma.
- Não invente regras de negócio, validações, máscaras ou textos de mensagem que não apareçam nos relatórios; o que não for sustentado vai para `lacunas`.
- O significado do campo vem do **rótulo mostrado ao usuário** e do campo do layout (nome, PIC, tamanho); quando o rótulo vem como `«chave»` (texto de mensagem não resolvido), use o nome da propriedade e diga isso em `lacunas`.
- Linguagem de negócio, sem termos da tecnologia da aplicação (bean, tile, JSP etc.) nos textos; esses nomes servem só para identificar o componente na evidência.
- Descreva sempre os relacionamentos com setas no sentido do dado (origem → destino), nunca com setas invertidas ou sem seta.
- Não explique telas, processos ou programas fora do funil; um processo sem relação com tela mantida não entra.
- Para a remodelagem, respeite a direção do dado: campo de **entrada** alimenta a transação; campo de **saída** é exibição; um combobox de entrada tem **opções** carregadas por outro processo (veja as linhas `(opções) valor` e `(opções) rótulo`) ou **opções fixas** da própria tela (coluna "Opções fixas (valor = texto)" de "Componentes de {tela}").
- **Domínio do campo.** Quando o combo tem opções fixas, o `significado` do campo traz o domínio exatamente como a tela mostra, valor e texto (por exemplo «1 = Sim, 2 = Não» e, no filtro, «0 = Todos»), e o `tipo_do_dado` reflete esse domínio (por exemplo `indicador sim/não`); não escreva que as opções não aparecem nos relatórios.
