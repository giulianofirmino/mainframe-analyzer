# Prompt 7: modelo de domínio (DDD) a partir do modelo físico

Cole este arquivo inteiro para a IA, junto com os arquivos listados em "Entradas". A IA devolve a interpretação (JSON) com a qual o gerador `gerar_dominio.py` completa o relatório **domain-model** (`16 - domain-model/human/report.html` e `16 - domain-model/ia/report.json`, o mesmo conteúdo nos dois formatos, como nas outras fases). O gerador já calculou, **só dos relatórios das fases 3 e 4**, a evidência: as tabelas e colunas, as chaves candidatas, os vínculos fortes e fracos entre tabelas, as colunas transversais, as candidatas a tabela de junção e a agregado, e o dicionário de prefixos e abreviações dos nomes físicos. Você traduz isso em um **modelo de domínio lógico** e o gerador confere cada afirmação.

## Objetivo

Documentar o modelo de domínio (lógico) a partir do modelo físico (tabelas e relacionamentos), com os padrões do Domain-Driven Design (Eric Evans). O estilo é o de um mapeamento lógico tipo JPA (classes, atributos, associações 1:1, 1:N e N:N, cascata), mas **sem código Java/JPA e sem pressupor framework**: tudo em estrutura (JSON), nunca em anotações (`@Entity`, `@Column`, `@OneToMany`), nem em `class`, `import` ou pseudocódigo de linguagem.

O que você faz:

1. Tabelas viram **classes de domínio** (`TCLIENTE` → `ClientePessoa`).
2. Colunas viram **atributos lógicos** (`NCLIENTE` → `numeroCliente`, `DCLIENTE` → `descricaoCliente`, `VLLIMITE_CREDITO` → `valorLimiteCredito`, `DTVALIDADE` → `dataValidade`).
3. Chaves estrangeiras (os vínculos entre tabelas) viram **associações semânticas** 1:1, 1:N ou N:N (a tabela `TCONTATO_CLIENTE` vira a associação 1:N `contatoCliente` de `ClientePessoa` para `Contato`).
4. Restrições (not null, identidade, valores fixos) viram **invariantes** do agregado.
5. As classes se organizam em **agregados**, cada um com uma raiz.

**Não agrupe em Bounded Contexts.** O agrupamento em contextos delimitados é a próxima fase (Context Discovery). Nada de `contexto`, `subdomínio` ou `módulo` na saída; o gerador rejeita chaves desconhecidas.

## Convenções de nomes

- **Plural → singular.** `PRODUTOS` → `Produto`.
- **MAIÚSCULAS_COM_SUBLINHADO → CamelCase.** Classes e agregados em UpperCamelCase (`Pedido`); atributos e associações em lowerCamelCase (`numeroPlano`, `contatoCliente`). Sem sublinhado.
- **Tire o jargão SQL dos prefixos**: `T` (tabela), `N` (número), `D` (descrição/data), `V` e `VL` (valor), `DT` (data), `I` (identificador/descrição), e assim por diante. O prefixo diz o **tipo** da coluna; o nome de domínio diz **o que é**: o prefixo vira o tipo lógico e a palavra de domínio (`valor`, `data`, `numero`, `descricao`, `codigo`, `indicador`, `quantidade`) abre o nome do atributo, como em `VLLIMITE_CREDITO` → `valorLimiteCredito`. A tabela "Prefixos dos nomes físicos" do relatório mostra, por letra, os tipos SQL em que cada prefixo aparece neste sistema: **confirme o significado do prefixo nos dados, não suponha**.
- **Expanda as abreviações**: `CLI` → `Cliente`, `PROD` → `Produto`, `CATG` → `Categoria`, `ESTQ` → `Estoque`. A tabela "Abreviações nos nomes físicos" lista cada abreviação com exemplos de coluna. Expanda pelo contexto do sistema (use os outros nomes onde a mesma abreviação aparece, o campo COBOL, o uso no SQL); se a expansão for incerta, escolha a mais provável e registre a dúvida em `lacunas`.
- O nome da classe e o dos atributos **não repetem o nome físico**, não têm sublinhado e não começam por prefixo SQL (`nPlano`, `dtValidade`, `vlLimite` são rejeitados).

## Conceitos DDD usados

- **Entidade (Entity):** objeto com identidade própria (a chave primária) e ciclo de vida próprio. Toda tabela vira uma entidade.
- **Raiz de agregado (Aggregate Root):** a entidade que encapsula as outras do agregado, valida as invariantes e é o **único ponto de entrada**: ninguém altera um membro sem passar pela raiz. Exemplos: `ClientePessoa` com `ContatoCliente`; `Pedido` com `ItemPedido`; `Produto` com `VariacaoEsku`.
- **Relacionamentos:** `1:1` (cada instância tem no máximo uma do outro lado); `1:N` (uma do todo tem várias partes; **quando a parte não vive sem o todo, a exclusão do todo apaga as partes: `cascata: true`**); `N:N` (muitas de cada lado, **sempre por uma tabela de junção** que você informa em `tabela_juncao`).
- **Invariante:** regra que deve valer sempre para o agregado inteiro (campo obrigatório, identidade única, valor de estado fixo que os programas sempre filtram, soma ou limite entre partes).

## Entradas

Todas em `<pasta-da-analise>/<fase>/ia/report.json`. Formato: `sections[]` → `blocks[]`; blocos `type: "table"` têm `columns[]` e `rows[]`. Uma célula pode ser texto, número, lista ou objeto `{"text": ...}` (use o `text`).

```contrato
@ler fase=03 bloco="Tabelas, papel e o que justifica o papel" colunas="Tabela|Papel|Por quê|Comandos de gravação|Comandos de consulta|Programas"
@ler fase=03 bloco="Colunas por tabela" colunas="Tabela|Coluna|Tipo|Aceita nulo|Origem da coluna|Campo COBOL|PIC|Programas que usam o campo|Programas que declaram e não usam|Uso no SQL|Situação"
@ler fase=04 bloco="Condições SQL (WHERE) dos comandos sobre {tabela}" colunas="Critério|Comando|Operação|Conector|Coluna|Operador|Valor|Papel do predicado|Origem do valor"
@ler fase=04 bloco="Chaves de busca em {tabela}" colunas="Comando|Operação|Campo da chave|Origem"
@ler fase=04 bloco="Gravações em {tabela}" colunas="Comando|Operação|Coluna|Valor gravado|Origem"
@ler fase=04 bloco="Comandos SQL sobre {tabela}" colunas="Id|Comando|Programa|Linha|SQL"
@ler fase=10 bloco="Tabelas passadas por parâmetro" colunas="Consulta|Tabela descoberta|No mapeamento DB2 das fases 1 e 3|Campo de parâmetro|Serviço que executa a consulta|Programas que passam o nome"
@ler fase=10 bloco="{consulta}: colunas e condições inferidas dos chamadores" colunas="Parte do SQL|Coluna|Posição na saída ou parâmetro|Operador|Quando"
@ler fase=16 bloco="Tabelas dinâmicas descobertas no sql-mapping" colunas="Tabela|Consulta|Serviço que executa|Classe do serviço|Campo de parâmetro|Programas que passam o nome|Colunas inferidas"
@ler fase=16 bloco="Chaves candidatas" colunas="Tabela|Colunas|Chave candidata|Primeira coluna do DCLGEN (indício fraco)|Papel (fase 3)|Natureza provável no domínio"
@ler fase=16 bloco="Papel na execução e natureza no domínio" colunas="Papel (fase 3)|Natureza provável|Leitura|Tabelas"
@ler fase=16 bloco="Acesso por classe de programa" colunas="Tabela|Categoria|Programas do business core (coordenador/funcional)|Programas corporativos|Business core grava"
@ler fase=16 bloco="Vínculos fortes" colunas="Tabela referenciada (pai)|Tabela que referencia (filho)|Colunas (pai ← filho)|Tipo de evidência|Cardinalidade candidata (pai → filho)|Onde aparece|Comandos"
@ler fase=16 bloco="Vínculos fracos" colunas="Coluna|Tabelas (tipo)|Tabelas em que é chave|Tipos compatíveis|Também em vínculo forte"
@ler fase=16 bloco="Colunas transversais" colunas="Coluna|Tabelas"
@ler fase=16 bloco="Candidatas a tabela de junção" colunas="Tabela|Liga"
@ler fase=16 bloco="Candidatas a agregado" colunas="Raiz candidata|Partes ligadas"
@ler fase=16 bloco="Prefixos dos nomes físicos" colunas="Prefixo|Colunas por tipo|Exemplos"
@ler fase=16 bloco="Abreviações nos nomes físicos" colunas="Abreviação|Ocorrências|Exemplos"
```

Quando existirem, leia também as fases 11 (regras de negócio) e 12 (funcionalidades) dos programas que acessam cada tabela (coluna "Programas" da fase 3): elas dizem o que o programa decide e valida com cada coluna, o que ajuda a dar o nome e a explicar o significado dos atributos.

**Protagonista, coadjuvante e figurante ajudam a classificar o domínio.** A fase 3 classifica cada tabela pelo que a execução faz com ela: **protagonista** (algum programa faz INSERT, UPDATE ou DELETE: o sistema governa o dado, é o **núcleo** do domínio e onde ficam as raízes e os membros dos agregados que o sistema altera); **coadjuvante** (só consulta, mas vários programas ou entry points a leem: dado mantido fora do sistema, **entidade de referência** somente leitura, tipicamente a raiz de um agregado externo que o núcleo apenas aponta); **figurante** (só consulta e aparece pouco: dado de **apoio**, tabela de códigos, candidata a objeto de valor ou enumerado). Cada entidade recebe `natureza` (`núcleo`, `referência` ou `apoio`) coerente com isso; a exceção precisa de explicação em `lacunas`. Use a natureza também para a fronteira dos agregados: um agregado do núcleo referencia entidades de referência por identidade, sem absorvê-las; elas ficam em agregados próprios (de uma entidade, somente leitura).

**Business core x corporativo.** O gerador separa as tabelas em **Business core** (algum programa coordenador ou funcional, das fases anteriores, as grava, ou eles são a maioria dos que a acessam) e **Corporativo** (só programas corporativos as acessam), pela classe dos programas da fase 0 (tabela "Acesso por classe de programa"). A categoria **não é decisão sua**: vem da evidência e o relatório desenha os agregados em duas caixas, uma por categoria. O que você faz é respeitar a fronteira: **um agregado não mistura tabelas das duas categorias** (separe em agregados distintos e ligue por relacionamento, o do business core apontando o corporativo por identidade). As associações entre as duas caixas são o ponto de integração: descreva-as com cuidado.

**O banco do relatório não declara chave primária, estrangeira nem unique.** A coluna "Chave" do diagrama da fase 3 é só a primeira coluna do DCLGEN e **não é** chave primária. Por isso o gerador deduz:

- **Chave candidata** = o conjunto de colunas que os programas comparam com `=` a um campo do programa nas cláusulas WHERE (busca por identidade). Filtros com valor fixo (`CINDCD_ATIVO = 1`) **não** são chave: são filtros de estado e viram invariante ou lacuna.
- **Vínculo forte** = o valor usado numa coluna (procurado no WHERE ou gravado) veio, na linhagem, de uma coluna de outra tabela (`tabela: DB2PRD.X.COL`). Na **busca**, a tabela procurada é a referenciada (pai) e a tabela de onde veio o valor guarda a referência (filho). Na **gravação**, a tabela gravada guarda a referência (filho) para a de onde veio o valor (pai). Quando a maior parte das colunas de uma tabela é gravada a partir de outra tabela, é uma **cópia de colunas** (tabela de controle, histórico ou espelho): modele como associação com nome que diga isso, não como 17 chaves estrangeiras.
- **Vínculo fraco** = só o nome da coluna é igual em tabelas diferentes. É um indício, não uma prova. **Colunas transversais** (auditoria e controle, presentes em várias tabelas sem vínculo nem chave) não são relacionamentos.

**Tabelas dinâmicas (sql-mapping).** Além das tabelas das fases 3 e 4, entram as **tabelas descobertas no sql-mapping (fase 10)**: consultas dinâmicas em que o nome da tabela passa por parâmetro a um serviço genérico, de modo que nenhum DCLGEN nem comando estático a mostra. O relatório da fase 16 as traz na tabela "Tabelas dinâmicas descobertas no sql-mapping" e nas demais tabelas como qualquer outra. As colunas, a posição no retorno e o significado vêm do que os programas chamadores leem e filtram (fase 10: "colunas e condições inferidas dos chamadores", "uso do serviço por chamador", propósito da consulta fixada); o tipo SQL é indeterminado, então decida o `tipo_logico` pelo uso (por exemplo código lido nas posições 1 a 3 de uma área de retorno, descrição nas posições seguintes) e registre a incerteza em `lacunas`. A categoria (business core ou corporativo) segue a classe do **serviço que executa a consulta**, não a de quem passa o nome. Procure vínculos dessas tabelas com as demais (a mesma coluna de código aparece como chave em tabelas do núcleo).

**Escopo.** O relatório só traz as **tabelas atingidas pela execução dinâmica** (fase 4, coluna "Alcançada pela execução dinâmica"); as demais foram ignoradas e não entram no modelo (a seção "Como o modelo foi montado" lista quais). Para as tabelas **sem DCLGEN**, use as colunas e os tipos **deduzidos** na fase 3 (coluna "Origem da coluna" = `deduzida do SQL`, tipo com "(inferido)"): são a melhor evidência disponível; para elas "Aceita nulo" vem vazio, então decida `obrigatorio` pelo uso (coluna de chave de busca ⇒ `true`) e registre a incerteza em `lacunas`.

## Raciocínio (siga nesta ordem)

### A. Classes (uma por tabela, sem exceção)
Para cada tabela: `nome` da classe em UpperCamelCase e no singular; `descricao` do que a entidade representa no negócio (uma ou duas frases, a partir do papel da tabela, das colunas e dos programas que a usam); `identidade` com as colunas que identificam uma instância (use a chave candidata; se a tabela não tem chave candidata, use o que a evidência sustentar e `confianca: "baixa"`), a `origem` da dedução e a `cita` (um trecho literal de uma tabela do relatório, por exemplo o critério `NPEDIDO = ...` ou o nome da coluna; o gerador procura o trecho nos relatórios).

`natureza`: `núcleo`, `referência` ou `apoio` (veja acima).

### B. Atributos (um por coluna, sem exceção)
Para toda coluna da tabela: `coluna` (o nome físico exato), `nome` lógico (convenções acima), `tipo_logico` (um de `Codigo`, `Numero`, `Texto`, `Descricao`, `Data`, `Hora`, `DataHora`, `Valor`, `Quantidade`, `Percentual`, `Indicador`, `Identificador`, `Enumerado`), `obrigatorio` (`true` quando a coluna **não** aceita nulo, `false` quando aceita; para colunas deduzidas, sem informação de nulo, use a evidência de uso), `descricao` (o significado). Use o tipo SQL, o campo COBOL, o PIC e o uso no SQL para decidir o tipo lógico (`CHAR(1)` com valores `S`/`N` é `Indicador`; `DECIMAL(15,2)` de dinheiro é `Valor`; `DECIMAL(n,0)` que o programa compara com um domínio de códigos é `Codigo`).

### C. Relacionamentos (semânticos, 1:1, 1:N e N:N)
Para cada **vínculo forte** do relatório, descreva um relacionamento. Para cada **vínculo fraco**, decida: ou aceita como relacionamento (`base: "vínculo fraco"`, com as colunas comuns) ou o descarta em `descartes` com o motivo (por exemplo "coluna de auditoria", "mesmo domínio de códigos, sem posse"). Todo relacionamento tem:

- `de` e `para` (nomes físicos das tabelas): `de` é o **todo** (a referenciada) e `para` a **parte**; a cardinalidade se lê de `de` para `para` (um `ClientePessoa` tem N `ContatoCliente`: `de: TCLIENTE`, `para: TCONTATO_CLIENTE`, `1:N`);
- `nome` da associação em lowerCamelCase, na perspectiva do todo (`contatoCliente`, `itemPedido`);
- `cardinalidade`: `1:1`, `1:N` ou `N:N`. Para `N:N`, a tabela de junção em `tabela_juncao` (as tabelas da ponta ficam em `de` e `para`); nesse caso as colunas ficam vazias;
- `colunas_de` e `colunas_para`: as colunas físicas que ligam (mesmo número nos dois lados);
- `cascata`: `true` se a parte não vive sem o todo (a exclusão do todo apaga a parte), `false` caso contrário;
- `base`: `vínculo forte`, `vínculo fraco` ou `dedução` (quando você infere sem vínculo no relatório, explicando na `descricao`);
- `cita`: trecho literal de uma tabela do relatório que sustenta o vínculo (pode ser a origem `tabela: DB2PRD.X.COL` ou a coluna comum); para `dedução` pode ficar vazio;
- `descricao`: o que a associação significa no negócio.

Cópia de colunas (tabela de controle ou histórico): modele como `1:1` ou `1:N` com `nome` que diga o papel (`controlePedido`, `historico`), e explique na `descricao`.

### D. Agregados
Agrupe as entidades em agregados. Regras: cada tabela está em **um e só um** agregado (uma entidade sem partes é a raiz do próprio agregado, com `membros` vazio ou só ela); a `raiz` é a entidade que os outros não podem existir sem; os `membros` têm relacionamento com a raiz ou com outro membro do agregado; use as "Candidatas a agregado" como ponto de partida, mas decida pelo negócio. **Critérios de fronteira** (confira cada um antes de fechar os agregados; o agregado vira, mais adiante, um serviço de domínio com um recurso REST e subrecursos, então a fronteira errada só aparece nos contratos, quando já é caro corrigir): (1) **mesmo identificador, mesmo agregado**: tabelas cuja chave é a mesma ou contém a chave da outra, lidas pelas mesmas funcionalidades e pelos mesmos programas, e que aparecem juntas no mesmo comando SQL (junção) são um agregado só, com a tabela que existe por si mesma (o cadastro, o catálogo) como raiz e as demais como membros, mesmo que o vínculo seja fraco ou dedução (registre a dúvida em `lacunas` e em `confianca`); (2) **regra que atravessa tabelas pertence ao agregado**: regra de unicidade «no máximo um X por Y», «cada tipo uma vez por Y» ou de estado que usa colunas de duas tabelas (por exemplo, o tipo numa e a situação noutra) mostra que as tabelas são um agregado; (3) **somente leitura não é motivo para separar**: separe só quando o ciclo de vida, o dono dos dados ou a invariante forem diferentes; (4) **tabela de códigos compartilhada** por mais de um agregado (referenciada por eles por identidade) fica em agregado próprio; (5) **teste do caminho**: se dois agregados seriam sempre acessados como `/x/{id}` e `/x/{id}/y`, com o mesmo `{id}`, e nunca um sem o outro, são um agregado só; (6) **dono diferente separa**: o que o sistema grava não se mistura com o cadastro de referência mantido fora, mesmo que a chave do primeiro contenha a do segundo (o primeiro aponta o segundo por identidade). Dê o `nome` do agregado (UpperCamelCase, em geral o da raiz), a `justificativa` da fronteira e as `invariantes` do agregado inteiro (regras que envolvem raiz e membros). **Não agrupe agregados em contextos.**

### E. Invariantes das entidades
Em cada entidade, as regras que a evidência sustenta: `base: "não nulo"` (colunas que não aceitam nulo), `"identidade"` (as colunas de identidade devem ser únicas; cite o critério WHERE), `"valor fixo"` (filtro de estado que os programas sempre aplicam, por exemplo `CINDCD_ATIVO = 1` significa que só registros ativos valem; cite o critério), `"vínculo"` (a coluna referencia outra entidade e deve existir lá) ou `"dedução"`. Cada invariante: `regra` (frase), `colunas` (existentes na tabela), `base`, `cita`.

### F. Lacunas
Tudo que a evidência não permite decidir: tabela sem coluna conhecida, tabela sem chave candidata, abreviação incerta, vínculo ambíguo, domínio de códigos sem tabela de apoio. Cada lacuna: `assunto` e `detalhe`. **Registre as dúvidas em vez de inventar.**

## Saída

Um objeto JSON (um arquivo, ou vários arquivos que se somam, por exemplo um por agregado), sem texto fora do JSON:

```json
{
  "entidades": [
    {
      "tabela": "TPEDIDO",
      "nome": "Pedido",
      "natureza": "núcleo",
      "descricao": "…",
      "identidade": {"colunas": ["NPEDIDO"], "origem": "chave candidata: comparada com `=` a campo do programa nos WHERE", "cita": "NPEDIDO", "confianca": "alta"},
      "atributos": [
        {"coluna": "NPEDIDO", "nome": "numeroPedido", "tipo_logico": "Numero", "obrigatorio": true, "descricao": "…"}
      ],
      "invariantes": [
        {"regra": "…", "colunas": ["NPEDIDO"], "base": "identidade", "cita": "NPEDIDO"}
      ]
    }
  ],
  "relacionamentos": [
    {"de": "TPEDIDO", "para": "TITEM_PEDIDO", "nome": "itemPedido", "cardinalidade": "1:N", "colunas_de": ["NPEDIDO"], "colunas_para": ["NPEDIDO"],
     "cascata": true, "tabela_juncao": "", "base": "vínculo forte", "cita": "tabela: DB2PRD.TITEM_PEDIDO.NPEDIDO", "descricao": "…"}
  ],
  "descartes": [
    {"coluna": "CUSUAR_INCL", "tabelas": ["TPEDIDO", "TCLIENTE"], "motivo": "coluna de auditoria (usuário que incluiu o registro), sem relação entre as entidades"}
  ],
  "agregados": [
    {"nome": "Pedido", "raiz": "TPEDIDO", "membros": ["TITEM_PEDIDO"], "justificativa": "…",
     "invariantes": [{"regra": "…", "colunas": ["NPEDIDO"]}]}
  ],
  "lacunas": [
    {"assunto": "…", "detalhe": "…"}
  ]
}
```

`descartes[].tabelas` é opcional: sem ela, o descarte vale para todas as tabelas que têm a coluna.

## Regras de qualidade

- **Descrições com conteúdo.** A `descricao` de um atributo explica o significado de negócio com o que a evidência mostra (uso no SQL, valores comparados, campo COBOL, programas que a leem ou gravam, colunas vizinhas); **nunca** repete só as palavras do nome (`Código de centro lucro sap` é rejeitado). Quando a evidência não diz mais que o nome, escreva o que se sabe (tipo, obrigatoriedade, onde é usada) e registre a incerteza em `lacunas`; agrupe em uma lacuna as colunas de auditoria ou de significado desconhecido em vez de fingir que sabe.
- **Sem misturar categorias.** Todas as tabelas de um agregado têm a mesma categoria (business core ou corporativo) na tabela "Acesso por classe de programa".
- **Natureza coerente.** `natureza` de toda entidade, de acordo com o papel da fase 3 (protagonista ⇒ `núcleo`; coadjuvante ⇒ `referência`; figurante ⇒ `apoio`).
- **Cobertura total.** Toda tabela vira uma entidade; toda coluna vira um atributo (uma só vez); toda tabela está em um agregado; todo vínculo forte vira um relacionamento; todo vínculo fraco com tipos compatíveis é aceito (relacionamento) ou descartado com motivo. O gerador lista o que faltar.
- **Nomes.** Siga as convenções; classe e atributo não repetem o nome físico; sem prefixo SQL; sem sublinhado; sem repetir atributo dentro da classe nem classe entre entidades.
- **Obrigatoriedade.** `obrigatorio` acompanha a coluna: `não` em "Aceita nulo" ⇒ `true`; `sim` ⇒ `false`.
- **Evidência.** Toda `cita` é **um único trecho contíguo e literal** (copie e cole; não junte vários nomes numa lista nem reescreva: `CTPO_CANAL, NPEDIDO` não existe como texto, `NPEDIDO` sim) que existe nas tabelas dos relatórios (da tabela citada ou da outra ponta do relacionamento). Não cite o que não está lá; use `dedução` e explique.
- **Sem código e sem framework.** Nada de anotações, `class`, `import`, tipos de linguagem ou nomes de framework. O modelo é estrutural.
- **Sem Bounded Contexts.** Não agrupe agregados em contextos, módulos ou subdomínios.
- **Sem invenção.** Não crie atributos, tabelas ou relacionamentos que a evidência não mostra. Chave, cardinalidade e cascata são **deduções**: marque `confianca` e `base` com honestidade e registre dúvidas em `lacunas`.
- **Cascata só onde a parte não vive sem o todo**, isto é, quando a chave da parte contém a do todo.
