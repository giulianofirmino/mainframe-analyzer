# Prompt 14: Design das aplicações dos serviços: criar ou estender os serviços, as filas, os programas mainframe e o acesso ao banco do recorte, obedecendo à arquitetura, aos contratos e às decisões

Cole este arquivo inteiro para a IA que trabalha **no repositório do código gerado** (o repositório indicado na execução), junto com os arquivos listados em "Entradas". A IA cria ou estende os serviços de domínio (e o serviço de consulta), as filas IBM MQ, os programas mainframe e o acesso ao banco do recorte seguindo os padrões e convenções já registrados, e devolve o registro de padrões (JSON) com o qual o gerador `gerar_implementation.py` monta o relatório da fase 20b (Design das Aplicações dos Serviços). O micro frontend e o BFF são do prompt 13.

O gerador calcula sozinho, do repositório: os módulos dos serviços (pelo tipo de aplicação da arquitetura alvo) e dos programas mainframe, com a pilha, as classes, os testes, o Dockerfile, a configuração, os pacotes, a estrutura de diretórios e as tecnologias; os pares de programas mainframe (transação, copybooks, SQL, LINK, seções); as tabelas do banco usadas pelos programas (com o schema e a carga do ambiente local); e os recursos de plataforma. A IA registra os padrões e as convenções, com a origem, exemplos ancorados no código e a verificação automática.

## Objetivo

1. **Obedecer aos insumos, nesta ordem.** Decisões arquiteturais (fase 22) prevalecem sobre os nomes das fases anteriores; depois a arquitetura alvo (fase 19: serviços, casos de uso, filas, programas e o rastreio das regras) e os contratos (fase 20: operações dos serviços, campos, copybooks). Nada é criado fora disso: serviço que a arquitetura não pede não existe; endpoint que o contrato não tem não existe; nome que uma ADR mudou usa o nome novo.
2. **Encaixar antes de criar.** Cada serviço da fase 19 vai para o repositório que as decisões indicam (repositórios do DDA e encaixe das aplicações): estender um módulo existente quando a decisão manda, criar um módulo novo só quando ela pede. Reaproveitar serviços e agregados que já existem (por exemplo, uma regra que precisa de outro agregado usa o caso de uso dele).
3. **Seguir os padrões registrados (fase 20b).** Serviços em camadas (port, usecase, domain, adapter MQ, config, web), uma regra de negócio por método com o comentário `Regra <F>.<R> · <título>`, endpoints com o prefixo e a versão das decisões, erros em problem+json, um adapter MQ por coordenador com as filas de baixa no padrão das decisões, traceId de ponta a ponta, programas mainframe em par coordenador e funcional (coordenador sem SQL, pedido e resposta em containers do canal, transação no padrão das decisões, estilo do legado nos fontes), SQL só nos funcionais (o serviço nunca acessa o banco), testes de regra com o ID do cenário e as regras, testes integrados em Java fora do build.
4. **Registrar os padrões.** Ao terminar, atualize o registro de padrões: mantenha os ids (PI-nn), acrescente um padrão novo só quando ele existe no código com exemplo real e, quando conferível, com verificação automática restrita aos módulos dos serviços e aos programas. Padrão não é afrouxado para o código passar: código fora do padrão é corrigido (ou o relatório o destaca).
5. **Provar.** O código novo segue para o prompt 12 (casos de teste e evidências): cada regra de negócio com teste unitário e, quando o ambiente provoca, cenário ponta a ponta com a prova de que os programas mainframe rodaram.

## Entradas

@ler fase=22 bloco="Decisões Arquiteturais" colunas="ADR|Título|Status|Data|Fases de origem"
@ler fase=22 bloco="Encaixe das aplicações da fase 19 nos repositórios do DDA" colunas="Aplicação (fase 19)|Tipo|Nome|Contexto (fase 18)|Repositório do DDA|Módulo no tcap-modernizacao"
@ler fase=19 bloco="Modelo de recursos aprovados" colunas="Id|Tipo|Nome|Contexto de origem (fase 18)|Confiança"
@ler fase=19 bloco="Rastreio das regras de negócio" colunas="Funcionalidade de origem da regra|Regra de negócio|Aplicação|Caso de uso"
@ler fase=19 bloco="Comandos SQL: fila de pedido, programa e fila de resposta" colunas="Comando (ou programa corporativo chamado)|Executado por|MQ_REQ|MQ_REQ alta|Copybook de requisição|Coordenador (PROGRAM_COORD)"
@ler fase=20 bloco="Operações dos contratos" colunas="Arquivo|Método|Caminho|operationId|Funcionalidade|Campos de entrada|Campos de saída"
@ler fase=20 bloco="Copybooks" colunas="Arquivo|Lado|Fila de baixa|Fila de alta|Programa"
@ler fase=20b bloco="Padrões e convenções" colunas="Id|Título|Categoria|Conformidade no repositório"
@ler fase=20b bloco="PI-{x} · ficha" colunas="Campo|Conteúdo"
@ler fase=20b bloco="Módulos do repositório" colunas="Módulo|Tipo (arquitetura alvo)|Aplicações da arquitetura alvo|Pilha"
@ler fase=20b bloco="Pacotes e pastas por módulo" colunas="Módulo|Pacote-base|Pacote ou pasta|Camada|Arquivos|Exemplos"
@ler fase=20b bloco="Pares coordenador e funcional" colunas="Coordenador|Funcional|Transação|Copybooks"
@ler fase=20b bloco="Tabelas do banco" colunas="Tabela|Colunas no schema local|Linhas na carga inicial|Operações SQL dos programas|Programas funcionais"

Também: o código dos serviços e dos programas (os módulos existentes servem de modelo: copie a estrutura, não o conteúdo) e os arquivos de recursos do mainframe (CSD e MQSC).

## Saída

`interpretacao-implementacao/padroes.json`:

```json
{
 "descricao": "uma frase sobre o que o registro cobre",
 "padroes": [
  {"id": "PI-01", "categoria": "Estrutura | Regras no código | Endpoints | Integração MQ | Programas mainframe | Observabilidade | Testes",
   "titulo": "…", "regra": "o que toda implementação nova deve fazer",
   "origem": {"fases": ["19 - target-architecture"], "adrs": ["ADR-009"]},
   "exemplos": [{"raiz": "projeto", "arquivo": "caminho no repositório", "ancora": "trecho literal", "papel": "o que mostra"}],
   "verificacao": {"tipo": "conteudo | linhas | par | estrutura", "raiz": "projeto", "arquivos": "glob", "deve_conter | nao_deve_conter | seleciona+formato": "regex"}}
 ]
}
```

Tipos de verificação: `conteudo` (cada arquivo contém, ou não, a expressão; `apos` limita ao texto depois de um marcador), `linhas` (toda linha que casa com `seleciona` segue `formato`), `par` (cada arquivo tem o par trocando `de` por `para` no nome) e `estrutura` (cada módulo, pelo glob `modulos`, tem as `pastas`).

## Regras que o gerador valida

1. Toda âncora de exemplo é encontrada no arquivo (trecho literal, nunca descrição).
2. Ids únicos; categoria, título, regra e exemplos obrigatórios; tipo de verificação conhecido; a verificação acha o que verificar (glob sem arquivo recusa o registro).
3. A conformidade de cada padrão é recalculada no repositório a cada geração; o que estiver fora aparece destacado no relatório.

## Restrições

1. Não altere os contratos da fase 20 nem as decisões da fase 22; complemento necessário vira lacuna para o prompt 11 ou proposta de ADR, nunca uma mudança silenciosa.
2. Não modernize os programas corporativos: são chamados por LINK do funcional (ADR dos corporativos).
3. Regras de domínio ficam no agregado do serviço; os programas mainframe executam SQL e LINK; o BFF e a tela (prompt 13) não acessam filas nem banco.
4. Mudança de processo (como estruturar código ou testes) é padrão deste registro, não ADR.
