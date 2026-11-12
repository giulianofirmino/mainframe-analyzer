# Prompt 13: Design das aplicações de frontend: criar ou estender o micro frontend e o BFF, reestruturando as telas do legado, e registrar o design

Cole este arquivo inteiro para a IA que trabalha **no repositório do código gerado** (o repositório indicado na execução), junto com os arquivos listados em "Entradas". A IA cria ou estende as aplicações de frontend do recorte (o micro frontend e o BFF que o serve), reestruturando as telas do legado, e devolve o registro de design (JSON) com o qual o gerador `gerar_ui_design.py` monta o relatório da fase 20a (Design das Aplicações de Frontend). Os serviços, as filas, os programas mainframe e o banco são do prompt 14.

O gerador calcula sozinho, do repositório: os módulos de frontend (micro frontend e BFF, pelo tipo de aplicação da arquitetura alvo) com a pilha, as classes, os testes, os pacotes, a estrutura de diretórios e as tecnologias; do micro frontend, as rotas (protegidas, carregadas sob demanda), os módulos expostos pela federação, os componentes (seletor, componentes que usa, entradas e saídas), as chamadas HTTP dos serviços com a operação do contrato (fase 20) que cada uma usa e o tema. A IA registra o que só ela decide: a correspondência de cada tela do legado com a tela nova e o que mudou na reestruturação, as diretrizes de interface e os padrões do BFF.

## Objetivo

1. **Obedecer aos insumos.** Decisões arquiteturais (fase 22) prevalecem; depois a arquitetura alvo (fase 19: o micro frontend, o BFF, os casos de uso do BFF e as regras que ficam nele), o contrato do BFF (fase 20) e a interface do legado (fase 15). Endpoint que o contrato do BFF não tem não existe; tela que as decisões deixam fora do recorte não é criada.
2. **Reestruturar, não copiar.** Cada tela do legado do recorte (fase 15: componentes, campos, eventos, regras de apresentação, ações e origem dos dados) vira uma tela do micro frontend segundo as diretrizes de interface (fase 20a): uma rota por tela do legado, com pesquisa, resultados e manutenção na mesma página; campos pelos componentes compartilhados; estados explícitos (carregando, vazio, erro, sessão expirada); ações conforme as permissões da identidade; chamadas ao BFF só pelos serviços Angular, com as operações do contrato do BFF e o prefixo das decisões. O que a tela do legado fazia em várias páginas ou com uma chamada por linha é reorganizado; nada de comportamento de negócio é perdido.
3. **BFF pelos padrões.** O BFF segue os padrões registrados (fase 20a, PF-nn): camadas (port, usecase, domain, adapter/http, config, web), um cliente OpenFeign e um adaptador por serviço chamado, uma regra de negócio por método com o comentário `Regra <F>.<R> · <título>`, prefixo /ni, erros em problem+json, token validado, traceId de ponta a ponta e testes de regra com o ID do cenário. O BFF compõe os serviços; regra de domínio fica no serviço dono dos dados.
4. **Registrar o design.** Para cada tela: o nome, a rota, o componente, a(s) tela(s) do legado, os serviços Angular e as operações do contrato que ela usa, as ações e o que mudou na reestruturação. As diretrizes de interface (ids estáveis UX-nn) e os padrões do BFF (ids estáveis PF-nn), cada um com a regra, a origem (fases e ADRs), exemplos ancorados no código e, quando conferível, uma verificação automática.
5. **Diretrizes e padrões são o padrão, não o retrato.** Não são afrouxados para o código atual passar: se o código não cumpre, corrija o código ou deixe o item como está (o relatório destaca o que está fora). Item novo só com exemplo real no código.

## Entradas

@ler fase=15 bloco="Telas: finalidade, jornada e layout sugerido" colunas="Tela|Finalidade|Jornada|Layout sugerido|Confiança|Lacunas"
@ler fase=15 bloco="Campos de {x}" colunas="Campo|Componente atual|Direção|Significado|Obrigatoriedade|Tipo do dado|Componente sugerido|Relação com a transação"
@ler fase=15 bloco="Ações de {x}" colunas="Ação|Significado|Resultado"
@ler fase=15 bloco="Agrupamentos de {x}" colunas="Grupo|Descrição|Componentes (em ordem)"
@ler fase=19 bloco="Especificação UX de {x}" colunas="Micro Frontend|Tela|Finalidade|Jornada|Layout sugerido|Confiança"
@ler fase=19 bloco="Rastreio das regras de negócio" colunas="Funcionalidade de origem da regra|Regra de negócio|Aplicação|Caso de uso"
@ler fase=20 bloco="Operações dos contratos" colunas="Arquivo|Método|Caminho|operationId|Funcionalidade|Campos de entrada|Campos de saída"
@ler fase=20a bloco="Diretrizes de interface" colunas="Id|Título|Categoria|Conformidade no repositório"
@ler fase=20a bloco="UX-{x} · ficha" colunas="Campo|Conteúdo"
@ler fase=20a bloco="Padrões e convenções do BFF" colunas="Id|Título|Categoria|Conformidade no repositório"
@ler fase=20a bloco="PF-{x} · ficha" colunas="Campo|Conteúdo"
@ler fase=20a bloco="Módulos do frontend" colunas="Módulo|Tipo (arquitetura alvo)|Aplicações da arquitetura alvo|Pilha"
@ler fase=20a bloco="Componentes do micro frontend" colunas="Componente|Seletor|Tipo|Componentes que usa|Entradas|Saídas|Arquivo"
@ler fase=20a bloco="Cores" colunas="Nome|Valor"
@ler fase=22 bloco="Decisões Arquiteturais" colunas="ADR|Título|Status|Data|Fases de origem"

Também: o código do micro frontend e do BFF (os módulos existentes servem de modelo: copie a estrutura, não o conteúdo) e as telas do legado (pasta da aplicação atual).

## Saída

`interpretacao-design/design.json`:

```json
{
 "descricao": "uma frase com o estilo das aplicações de frontend (framework, navegação, estrutura das telas, BFF)",
 "telas": [
  {"tela": "nome da tela nova", "rota": "/rota", "componente": "ClasseDoComponente",
   "legado": ["caminho da tela do legado, relativo à pasta da aplicação atual"],
   "servicos": ["nome do serviço Angular (arquivo sem .service.ts)"], "operacoes": ["operationId do contrato"],
   "acoes": ["ação da tela"], "reestruturacao": "o que mudou da tela do legado para a tela nova e por quê",
   "exemplos": [{"raiz": "projeto", "arquivo": "caminho no repositório", "ancora": "trecho literal", "papel": "o que mostra"}]}
 ],
 "diretrizes": [
  {"id": "UX-01", "categoria": "Estrutura", "titulo": "…", "regra": "…", "origem": {"fases": ["15 - user-interface-mapping"], "adrs": ["ADR-007"]},
   "exemplos": [{"raiz": "projeto", "arquivo": "…", "ancora": "…", "papel": "…"}],
   "verificacao": {"tipo": "conteudo | linhas | par | estrutura", "raiz": "projeto", "arquivos": "glob", "deve_conter | nao_deve_conter | seleciona+formato": "regex"}}
 ],
 "padroes": [
  {"id": "PF-01", "categoria": "Estrutura | Integração | Regras no código | Endpoints | Segurança | Observabilidade | Testes | Interfaces", "titulo": "…", "regra": "…",
   "origem": {"fases": ["19 - target-architecture"], "adrs": ["ADR-003"]}, "exemplos": [{"raiz": "projeto", "arquivo": "…", "ancora": "…", "papel": "…"}],
   "verificacao": {"tipo": "…", "raiz": "projeto", "arquivos": "glob do BFF", "…": "regex"}}
 ],
 "fora": {"motivo": "o que não faz parte do recorte e por quê", "componentes": ["…"], "servicos": ["…"], "caminhos": ["…"], "modulos": ["…"], "arquivos": ["glob"]}
}
```

Tipos de verificação: `conteudo` (cada arquivo contém, ou não, a expressão; `apos` limita ao texto depois de um marcador), `linhas` (toda linha que casa com `seleciona` segue `formato`), `par` (cada arquivo tem o par trocando `de` por `para` no nome) e `estrutura` (cada módulo tem as pastas). O bloco `fora` tira do relatório e das verificações o que não faz parte do recorte (por exemplo, a plataforma de identidade).

## Regras que o gerador valida

1. Toda tela do legado citada existe na pasta da aplicação atual; todo componente citado existe no micro frontend.
2. Toda âncora de exemplo é encontrada no arquivo (trecho literal, nunca descrição).
3. Ids de diretriz e de padrão únicos; categoria, título, regra e exemplos obrigatórios; tipo de verificação conhecido; a verificação acha o que verificar (glob sem arquivo recusa o registro).

## Restrições

1. Não altere os contratos da fase 20 nem as decisões da fase 22: chamada que precisa de operação que o contrato não tem vira lacuna para o prompt 11, não um endpoint inventado.
2. Não leve regra de domínio para a tela nem para o BFF: a tela valida formato e obrigatoriedade; o BFF compõe e executa só as regras que a arquitetura alvo põe nele; as demais ficam no serviço (prompt 14).
3. Mantenha os ids entre execuções; item retirado sai do registro com a justificativa na mensagem da execução.
