# mainframe-analyzer

Análise de sistemas mainframe (COBOL, CICS, DB2, MQ, VSAM, IMS, JCL), das fontes ao código modernizado, em fases numeradas de 0 a 23. A análise estática e dinâmica é feita por scripts, sobre tokens e AST, e todo número, tabela e diagrama é determinístico. O que exige julgamento (regras de negócio, funcionalidades, domínio, arquitetura alvo, contratos) é feito por uma IA isolada, guiada por prompts versionados, e o resultado da IA é validado pelos geradores antes de virar relatório.

O repositório separa três coisas:

- **analisador**: o método. Nada aqui conhece o sistema analisado (o teste `tests/agnostico_smoke.py` confere).
- **pipeline**: o comando `pipeline-analise`, que roda todas as fases em sequência, inclusive as de IA, sem intervenção humana.
- **dados de cada análise**: fontes, cenários, interpretações da IA e relatórios. Ficam fora deste repositório (ver `.gitignore`).

---

## Sumário

1. [Requisitos](#1-requisitos)
2. [Estrutura](#2-estrutura)
3. [Instalação](#3-instalação)
4. [Preparar uma análise](#4-preparar-uma-análise)
5. [Rodar tudo com o pipeline](#5-rodar-tudo-com-o-pipeline)
6. [Rodar passo a passo](#6-rodar-passo-a-passo)
7. [Fases e relatórios](#7-fases-e-relatórios)
8. [Prompts de IA](#8-prompts-de-ia)
9. [Verificações](#9-verificações)
10. [Runtime: cenários, simulador e região CICS local](#10-runtime-cenários-simulador-e-região-cics-local)
11. [Testes do analisador](#11-testes-do-analisador)
12. [Princípios da análise](#12-princípios-da-análise)
13. [Problemas comuns](#13-problemas-comuns)
14. [Documentação detalhada](#14-documentação-detalhada)

---

## 1. Requisitos

| Para | Precisa de |
|---|---|
| Analisador (fases 0 a 23, cenários, relatórios) | Python 3.10 ou superior. Só biblioteca padrão |
| Comando `pipeline-analise` | Python 3.10+ e `PyYAML` (instalado junto) |
| Fases de IA pelo pipeline | Uma CLI de IA: **Claude Code CLI** (`claude`) ou **Kiro CLI** (`kiro-cli`), autenticada |
| Região CICS local com MQ e DB2 de verdade (`tools/cics_host.py`, modo `external`) | `pymqi` (com o cliente redistribuível do IBM MQ) e `ibm_db` |
| Fase 21 (rastreabilidade do código gerado) | O repositório do código gerado, com Maven/Docker se os testes rodarem por eles |

As ferramentas rodam em Linux, macOS e Windows (no Windows, use `python` no lugar de `python3` se for o caso).

---

## 2. Estrutura

```
mainframe-analyzer/
├── analisador/
│   ├── mainframe-analyzer   atalho de linha de comando: certify, run, modelo, dclgen
│   ├── VERSION              versão do método
│   ├── semantic_core/       lexer, parser e AST do COBOL, modelo de dados, runtime COBOL sobre a AST, DB2/MQ/CICS do runtime,
│   │                        árvore de decisão, regras, linhagem, solvers, modelo e renderização dos relatórios (report_model, report_render)
│   ├── tools/               analisar.py (fases 0 a 9), certify_from_zero.py, run_scenarios.py (cenários), cics_host.py (região CICS local),
│   │                        gerar_relatorios.py, gerar_indice.py, mapa_fases.py, publicar.py, dclgen_report.py, entry_point_coverage.py
│   ├── fases/               geradores das fases 10 a 23 (gerar_*.py), prompts/ da IA, proveniencia.py, podar_interpretacao.py,
│   │                        stubs-ibm/ (books do MQ e SQLCA para fontes que não os trazem)
│   ├── *_runtime.py, cli.py simulador multi-tecnologia em nível de fixture (JCL, CICS, BMS, DB2, VSAM, IMS, MQ)
│   ├── tests/               testes do método (rodar_todos.py, *_smoke.py, agnostico_smoke.py, relatorios_equivalencia.py)
│   └── docs/                documentação detalhada (seção 14)
└── pipeline/                pacote Python do comando pipeline-analise (instalar.py, pyproject.toml, src/pipeline_analise/)
```

Dados de uma análise (fora do repositório, mas com este formato):

```
cenarios/<sistema>/              cenários da análise dinâmica (*.json) e analise.config.json do sistema
analises/<analise>/
├── pipeline.config.json         configuração do pipeline para esta análise
├── analise/                     relatórios: uma pasta por fase (NN-*/human/report.html e NN-*/ia/report.json), index.html, MANIFESTO.json
├── interpretacoes/              respostas da IA (interpretacao-*/), bruto/ (o que a IA devolveu) e PROVENIENCIA.json
└── .pipeline/                   trabalho do pipeline: estado.json, pipeline.log, execucoes/
```

---

## 3. Instalação

O analisador não precisa de instalação: basta clonar e rodar os scripts com Python.

```bash
git clone https://github.com/giulianofirmino/mainframe-analyzer.git
cd mainframe-analyzer
python3 analisador/tests/rodar_todos.py        # confere o ambiente: roda os testes do método
```

Sem uma análise gerada, `agnostico_smoke.py` e `relatorios_equivalencia.py` falham por não achar a pasta da análise: eles conferem os relatórios de uma análise e precisam dela como argumento (seção 11). Os demais testes rodam sozinhos.

O comando `pipeline-analise`:

```bash
cd pipeline
python3 instalar.py               # usa pipx, uv ou pip, o que existir; sem nenhum, instala em ~/.local/bin
python3 instalar.py --editavel    # o comando usa o código desta pasta (alterações valem na hora)
python3 instalar.py --desinstalar
# ou, como pacote Python padrão:
pipx install .     # ou: uv tool install .   ou: pip install .
```

Confira com `pipeline-analise --help`. No Windows o instalador cria `%USERPROFILE%\.local\bin\pipeline-analise.cmd`; essa pasta precisa estar no `PATH`.

---

## 4. Preparar uma análise

### 4.1 Fontes

Uma pasta com os fontes do sistema: programas (`.CBL`/`.COB`), copybooks (`.CPY`) e DCLGEN. Subpastas `COBOL/`, `COPYBOOK/` e `DCLGEN/` são o formato mais simples, mas o analisador procura os membros em toda a árvore. Copybook ausente é tolerado: os campos dele viram "deduzidos" pelo uso. Os books do MQ e o SQLCA que faltarem vêm de `analisador/fases/stubs-ibm/`.

Para as fases 14, 15 e 20a/20b/21 são necessários também, quando existirem:
- **PDC**: a pasta com os XML dos processos (fases 14 e 15);
- **aplicação web antiga** (Java, JSF/JSP, Spring), para o mapeamento das telas (fase 15);
- **repositório do código gerado**, para as fases 20a, 20b, 21, 22 e 23.

### 4.2 Configuração do sistema: `cenarios/<sistema>/analise.config.json`

É o único lugar onde ficam características do sistema analisado. Nenhuma chave é obrigatória; sem o arquivo valem os padrões.

```json
{
  "prefixo_core": "ABCD",
  "campos_infraestrutura": ["EIB[A-Z0-9-]*", "SQLSTATE", "SQLCA[A-Z0-9-]*", "SQLERR[A-Z0-9-]*", "SQLWARN[A-Z0-9-]*", "RETURN-CODE", "DFHRESP"],
  "sqlcode_negocio": ["+100", "100", "-803"],
  "categorias_mecanismo_validacao": ["permissão de acesso", "infraestrutura CICS", "paginação"]
}
```

| Chave | Significado |
|---|---|
| `prefixo_core` | Prefixo dos programas do núcleo do negócio. Programa sem ele só pode ser CORPORATIVO ou INFRAESTRUTURA na classificação (fase 0). Sem a chave, a classificação não usa nomes |
| `campos_infraestrutura` | Expressões dos campos fornecidos pelo ambiente (CICS, DB2). Uma condição sobre eles é infraestrutura, não regra de negócio |
| `sqlcode_negocio` | SQLCODE tratados como regra de negócio (registro não encontrado, chave duplicada). Os demais são infraestrutura |
| `categorias_mecanismo_validacao` | Categorias com que a IA pode descartar uma validação como mecanismo técnico |

### 4.3 Configuração do pipeline: `analises/<analise>/pipeline.config.json`

Caminhos relativos são relativos ao próprio arquivo.

```json
{
  "recorte": "Nome do recorte analisado (título da página de entrada)",
  "raiz_analisador": "../../analisador",
  "analise": "analise",
  "interpretacoes": "interpretacoes",
  "trabalho": ".pipeline",
  "fontes": "<pasta-dos-fontes>",
  "cenarios": "../../cenarios/<sistema>",
  "pdc": "<pasta-dos-xml-do-pdc>",
  "aplicacao": "<pasta-da-aplicacao-web-antiga>",
  "projeto": "<repositorio-do-codigo-gerado>",
  "ia": {
    "comum":  {"tentativas": 3, "max_turnos": 80, "tempo_limite_s": 5400, "max_turnos_implementacao": 400, "tempo_limite_implementacao_s": 14400},
    "claude": {"comando": "claude", "modelo": null, "ferramentas_isolada": ["Read", "Write", "Glob", "Grep"],
               "ferramentas_implementacao": ["Read", "Edit", "Write", "Glob", "Grep", "Bash(mvn:*)", "Bash(docker:*)", "Bash(python3:*)"]},
    "kiro":   {"comando": "kiro-cli", "modelo": null, "agente": null, "ferramentas_isolada": ["fs_read", "fs_write"], "ferramentas_implementacao": "todas"}
  }
}
```

| Chave | Significado |
|---|---|
| `raiz_analisador` | Pasta `analisador/` deste repositório |
| `analise` | Onde ficam os relatórios das fases |
| `interpretacoes` | Onde ficam as respostas da IA e a proveniência |
| `trabalho` | Estado e registro das execuções do pipeline |
| `fontes`, `cenarios`, `pdc`, `aplicacao`, `projeto` | Entradas da seção 4.1 |
| `ia.comum` | Tentativas por prompt quando o gerador recusa, turnos e tempo limite da conversa da IA |
| `ia.claude`, `ia.kiro` | Comando, modelo e ferramentas permitidas da IA isolada e da IA de implementação (fase 21) |

---

## 5. Rodar tudo com o pipeline

Na pasta da análise (`analises/<analise>/`), ou em qualquer lugar com `--config`:

```bash
pipeline-analise --ia-cli claude                           # tudo; refaz só os prompts cuja interpretação não vale mais
pipeline-analise --ia-cli kiro --ia sempre                 # refaz todos os prompts com o Kiro CLI
pipeline-analise --ia nunca                                # só reaproveita as interpretações (falha se alguma não valer)
pipeline-analise --ia-cli claude --desde 16 --ate 20       # um intervalo de etapas
pipeline-analise --ia-cli claude --deterministico refazer  # executa de novo os cenários da análise dinâmica
pipeline-analise --config analises/<analise>/pipeline.config.json --ia-cli claude
```

A configuração vem de `--config`, da variável `PIPELINE_ANALISE_CONFIG` ou de `./pipeline.config.json`.

| Etapa | O que faz |
|---|---|
| `0-9` | Fases determinísticas (`tools/analisar.py`): análise estática, cenários da análise dinâmica, certificação e relatórios |
| `10` a `20` | Fases de IA: reaproveita a interpretação que ainda vale ou a refaz pela IA isolada. O gerador valida; se recusar, a mensagem volta para a mesma conversa da IA (até `tentativas` vezes). A resposta aceita é registrada na proveniência. A `14` (PDC) é determinística |
| `21` | Sobe o ambiente local do código gerado, refaz a implementação pelo prompt 12 quando necessário, roda os testes e gera a rastreabilidade to-be |
| `22` | Architecture Decision Records (registro do dono da arquitetura em `interpretacao-adr/adr.json`, não é IA) |
| `23` | Enhancement Proposals (registro do dono da arquitetura em `interpretacao-ep/ep.json`, não é IA) |
| `final` | Referências cruzadas entre relatórios, verificação dos prompts, da proveniência e da equivalência IA x humano, e `MANIFESTO.json` |

Uma interpretação de IA vale quando o prompt não mudou, o arquivo é o que a IA devolveu (no máximo com a poda determinística) e as fases que o prompt lê não mudaram desde a última geração (hash em `<trabalho>/estado.json`).

**Registro**: tudo aparece no console e em `<trabalho>/pipeline.log`, inclusive o que a IA faz. Cada execução fica em `<trabalho>/execucoes/<data-hora>.json` (etapas, situação, tempo, motivo de refazer cada prompt, sessão, turnos e custo da IA). Código de saída 0 quando tudo terminou, 1 quando uma etapa falhou.

**Execução apartada** (para medir a estabilidade dos prompts):

```bash
pipeline-analise --ia-cli claude --apartada <pasta> [--referencia <analise>] [--limiar 0.85] [--ciclos 5] [--realimentar]
```

Copia a análise de referência para `<pasta>`, refaz todos os prompts e compara cada fase gerada com a da referência (nota de 0 a 1). Enquanto a nota fica abaixo do limiar, repete o prompt com uma conversa nova; no limite de ciclos fica com o melhor. `--realimentar` mostra à IA onde o ciclo anterior divergiu. O resultado fica em `<pasta>/comparacao.json`; o código de saída é 2 quando alguma fase ficou abaixo do limiar.

---

## 6. Rodar passo a passo

Os comandos abaixo partem da raiz do repositório. `<fontes>` é a pasta dos fontes, `<cenarios>` a pasta `cenarios/<sistema>`, `<analise>` a pasta dos relatórios e `<interp>` a pasta das interpretações.

### 6.1 Certificação sem cenários (fases 0 a 6, 8 e 9)

```bash
analisador/mainframe-analyzer certify <fontes> <saida>
# equivalente:
python3 analisador/tools/certify_from_zero.py <fontes-ou-zip> <saida>
```

Classifica os programas, descobre dependências, monta esquemas de programa e de dados, linhagem, mapa de decisão, regras determinísticas, golden cases e certificação. A pasta de saída é apagada e recriada a cada execução.

### 6.2 Cenários da análise dinâmica (fase 7)

1. Gere os cenários-modelo, com as entradas candidatas e os mocks previstos de cada entry point:

   ```bash
   analisador/mainframe-analyzer modelo <fontes> entry-points <saida-modelos>
   # ou para um programa:  analisador/mainframe-analyzer modelo <fontes> <PROGRAMA> <saida-modelos>
   ```

2. Escreva os cenários em `cenarios/<sistema>/*.json`, a partir dos modelos. O procedimento (catálogo de casos, esperado tirado do código, laço de cobertura) está no prompt `analisador/fases/prompts/prompt-0-cenarios-de-teste.md`, e o formato completo em `analisador/docs/17-RUNTIME-CENARIOS.md`. Exemplo mínimo:

   ```json
   {
     "name": "consulta inicial com 2 registros",
     "entry_point": "PROGRAMA1",
     "inputs": {"EIBCALEN": 100},
     "tables": {"ESQUEMA.TABELA": [{"COLUNA_A": 10, "COLUNA_B": 501}]},
     "mock_policy": "infra_and_external",
     "mocks": {"PROGCORP": {"returns": {"CAMPO-COD-RETORNO": 0}}},
     "db2_status": {"PROGRAMA3:313": {"SQLCODE": -911}},
     "cics_status": {"PROGRAMA1:390": {"EIBRESP": 13}},
     "expected": {"status": "SUCCESS", "outputs": {"CAMPO-COD-RETORNO": 0}}
   }
   ```

3. Rode os cenários contra a análise estática:

   ```bash
   analisador/mainframe-analyzer run <fontes> <cenarios> <saida> [--rapido]
   # equivalente:  python3 analisador/tools/run_scenarios.py <fontes> <cenarios> <saida> [--rapido] [--execucoes 3]
   ```

   Saída: `analise/` (pipeline completo, pulado com `--rapido`), `static/` (fontes expandidos e `static-model.json`), `cenarios/<nome>/` (resultado, `trace.log` e `trace.jsonl` de cada cenário) e `runtime-validation.json`. Código de saída 0 só quando todos os cenários passam.

### 6.3 Fases 0 a 9 completas, com relatórios

```bash
python3 analisador/tools/analisar.py <fontes> <cenarios> <analise> --sem-ia
```

| Opção | Efeito |
|---|---|
| `--sem-ia` | Não gera os relatórios de IA (fases 10 a 13) |
| `--so-relatorios` | Não refaz análise nem cenários: só regenera os relatórios e o `MANIFESTO.json` de uma pasta existente |
| `--simulacao-ia <interp>` | Gera também as fases 10 a 13 a partir das interpretações da IA dessa pasta |
| `--config <arquivo>` | `analise.config.json` do sistema (padrão: `<cenarios>/analise.config.json`) |
| `--prefixo-core <PREFIXO>` | Prefixo do núcleo do negócio, se não estiver na configuração |
| `--cache <pasta>` | Cache dos cenários (padrão: `<analise>.cache`). Permite retomar uma rodada interrompida |
| `--comparar <pasta>` | Lista o que difere de uma análise de referência (pelo `MANIFESTO.json`) |

O `MANIFESTO.json` guarda o SHA-256 de cada arquivo gerado, ignorando o caminho absoluto dos fontes. Duas execuções com os mesmos fontes geram o mesmo manifesto, em qualquer máquina. Se o seu ambiente corta comandos longos, repita o mesmo comando: o cache retoma de onde parou e o resultado é idêntico.

### 6.4 Fases de IA (10 a 21), uma por prompt

Cada fase de IA segue o mesmo ciclo: preparar a entrada isolada, rodar a IA, registrar o que ela devolveu e gerar o relatório. O pipeline faz isso sozinho; à mão:

1. **Entrada isolada**: uma pasta só com o prompt e os `ia/report.json` das fases que o contrato `@ler` do prompt lista. A IA não vê o código analisado (exceto no prompt 0) nem interpretações anteriores.
2. **Rodar a IA**, pedindo que leia o prompt inteiro e grave o JSON no formato que ele define.
3. **Registrar o bruto** da IA na proveniência:

   ```bash
   python3 analisador/fases/proveniencia.py registrar <interp> <n-do-prompt> <pasta-com-o-JSON-da-IA> [--executor TEXTO]
   ```

4. **Gerar o relatório** da fase (tabela abaixo). Se o gerador recusar, devolva a mensagem dele à mesma IA para ela corrigir. Não edite o JSON à mão: a proveniência acusa.

| Fase | Prompt | Comando |
|---|---|---|
| 10 sql-mapping | 5 | `python3 analisador/tools/analisar.py <fontes> <cenarios> <analise> --so-relatorios --simulacao-ia <interp>` (gera 10 a 13) |
| 11 business-rules | 1 | idem (ou `fases/gerar_simulacao.py <analise> <analise> --interpretacao <interp>`) |
| 12 business-flows | 2 e 4 | idem; o fluxo interno (prompt 4): `fases/gerar_sequencia.py <analise> <analise> --interpretacao <interp>` |
| 13 traceability | 3 (só script) | gerada junto com a 11 |
| 14 pdc-mapping | — | `fases/gerar_pdc.py <analise> <analise> --pdc <pasta-pdc>` |
| 15 user-interface-mapping | 6 | `fases/gerar_interface.py <analise> <analise> --aplicacao <aplicacao> --pdc <pasta-pdc> --interpretacao <interp>` |
| 16 domain-model | 7 | `fases/gerar_dominio.py <analise> <analise> --interpretacao <interp>` |
| 17 responsibility-segregation | 8 | `fases/gerar_responsibility_segregation.py <analise> <analise> --interpretacao <interp>` |
| 18 context-discovery | 9 | `fases/gerar_context_discovery.py <analise> <analise> --interpretacao <interp>` |
| 19 target-architecture | 10 | `fases/gerar_target_architecture.py <analise> <analise> --interpretacao <interp>` |
| 20 contracts | 11 | `fases/gerar_contracts.py <analise> <analise> --interpretacao <interp> [--planilha]` |
| 20a ui-design | 13 | `fases/gerar_ui_design.py <analise> <analise> --projeto <projeto> --interpretacao <interp>` |
| 20b implementation | 14 | `fases/gerar_implementation.py <analise> <analise> --projeto <projeto> --interpretacao <interp>` |
| 21 traceability-to-be | 12 | `fases/gerar_traceability_to_be.py <analise> <analise> --projeto <projeto> --resultados <resultados-testes.json> --interpretacao <interp>` |
| 22 architecture-decision-records | — (registro) | `fases/gerar_architecture_decisions.py <analise> <analise> --projeto <projeto> --interpretacao <interp>` |
| 23 enhancement-proposals | — (registro) | `fases/gerar_enhancement_proposals.py <analise> <analise> --projeto <projeto> --interpretacao <interp>` |

`fases/` é `analisador/fases/`. Ordem dos prompts nas fases 10 a 13: **5 → 1 → 2 → 4** (gerando os relatórios entre um e outro). Depois de gerar as fases 11 e 12, a poda mantém a interpretação coerente com os relatórios (só remove, nunca escreve texto):

```bash
python3 analisador/fases/podar_interpretacao.py <analise> --interpretacao <interp>
```

### 6.5 Fechamento da análise

```bash
python3 -c "import sys; sys.path[:0]=['analisador/semantic_core']; import report_render; print(report_render.ligar('<analise>'))"   # referências cruzadas
python3 analisador/tools/gerar_indice.py <analise>                       # index.html da análise: números e resumo das fases por etapa
python3 analisador/tools/mapa_fases.py <analise> [arquivo.html]           # mapa das fases: quem lê o quê e a utilidade de cada dado
python3 analisador/tools/publicar.py <pasta-gerada> <pasta-destino>       # copia e confere arquivo a arquivo com o MANIFESTO
```

---

## 7. Fases e relatórios

Cada fase gera `NN - nome/human/report.html` (para leitura) e `NN - nome/ia/report.json` (o mesmo modelo, para a IA das fases seguintes). O HTML é a projeção exata do JSON.

| Fase | Relatório | Etapa | Quem faz |
|---|---|---|---|
| 00 | program-classification: classe, confiança e recomendação por programa | Discovery | script |
| 01 | discovery-dependencies: copybooks, CALL/LINK/XCTL, SQL, tabelas, CICS, arquivos | Discovery | script |
| 02 | program-schema: interfaces e áreas dos programas | Discovery | script |
| 03 | data-schema: tabelas, colunas e DCLGEN | Discovery | script |
| 04 | data-lineage: linhagem campo a campo entre programas e tabelas | Reverse | script |
| 04b | lineage-summary: resumo da linhagem | Reverse | script |
| 05 | decision-map: decisões (Dnnn) e caixas (Ennn) por programa | Discovery | script |
| 06 | deterministic-rules: regras determinísticas (validação, erro, estado, roteamento, derivação) | Reverse | script |
| 07 | dynamic-analysis: execução dos cenários, cobertura e motivo dos ramos não cobertos | Reverse | script + cenários |
| 08 | golden-cases: cenários verificados com hash do trace | Reverse | script |
| 09 | certification: status final por outcome | Reverse | script |
| 10 | sql-mapping: comandos SQL estáticos e dinâmicos (`<PROGRAMA>-Qnn`) | Reverse | IA (prompt 5) + script |
| 11 | business-rules: regras de negócio em grupos | Reverse | IA (prompt 1) + script |
| 12 | business-flows: funcionalidades e fluxo interno de cada uma | Reverse | IA (prompts 2 e 4) + script |
| 13 | traceability: da decisão do código à regra e à funcionalidade | Forward | script |
| 14 | pdc-mapping: processo PDC → ação → transação → programa | Discovery | script |
| 15 | user-interface-mapping: telas, campos e campos da transação | Reverse | IA (prompt 6) + script |
| 16 | domain-model: modelo de domínio lógico (DDD) | Modernization | IA (prompt 7) + script |
| 17 | responsibility-segregation: propriedade dos dados e estratégia de acesso | Modernization | IA (prompt 8) + script |
| 18 | context-discovery: Domain e Delivery Contexts | Modernization | IA (prompt 9) + script |
| 19 | target-architecture: arquitetura alvo, recursos e diagramas | Forward | IA (prompt 10) + script |
| 20 | contracts: OpenAPI 3.1 e copybooks das filas | Forward | IA (prompt 11) + script |
| 20a | ui-design: design das aplicações de frontend | Forward | IA (prompt 13) + script |
| 20b | implementation: design das aplicações de serviço | Forward | IA (prompt 14) + script |
| 21 | traceability-to-be: da regra de negócio ao teste do código gerado | Forward | IA (prompt 12) + testes + script |
| 22 | architecture-decision-records | Consolidation | registro do dono da arquitetura |
| 23 | enhancement-proposals | Consolidation | registro do dono da arquitetura |

Arquivos estruturados na raiz da análise (fases 0 a 9): `phase-0-program-classification.json`, `dependency-map.json`, `dclgen-catalog.json`, `decision-trees.json`, `decision-map.json`, `deterministic-rules.json`, `data-lineage.json`, `data-usage.json`, `catalog.json`, `goldens.json`, `outcome-status.json`, `certification-summary.json`.

---

## 8. Prompts de IA

Ficam em `analisador/fases/prompts/`. Cada um declara as fases que lê (linhas `@ler`) e o formato do JSON de saída.

| Prompt | Arquivo | Fase | Saída (em `<interp>`) |
|---|---|---|---|
| 0 | `prompt-0-cenarios-de-teste.md` | 7 | cenários em `cenarios/<sistema>/` (a IA lê o código) |
| 1 | `prompt-1-regras-de-negocio.md` | 11 e 13 | `interpretacao/regras.json` |
| 2 | `prompt-2-funcionalidades.md` | 12 | `interpretacao-fluxos/funcionalidades.json` |
| 3 | `prompt-3-rastreabilidade.md` | 13 | nenhuma (a fase é calculada; o prompt descreve) |
| 4 | `prompt-4-sequencia-de-funcionalidades.md` | 12 | `interpretacao-sequencia/sequencia.json` |
| 5 | `prompt-5-mapeamento-sql.md` | 10 | `interpretacao-sql/mapeamento.json` |
| 6 | `prompt-6-telas-e-campos.md` | 15 | `interpretacao-interface/telas.json` |
| 7 | `prompt-7-modelo-de-dominio.md` | 16 | `interpretacao-dominio/dominio.json` |
| 8 | `prompt-8-chamadas-e-n-mais-1.md` | 17 | `interpretacao-relacao/relacao.json` |
| 9 | `prompt-9-contextos.md` | 18 | `interpretacao-contextos/contextos.json` |
| 10 | `prompt-10-arquitetura-alvo.md` | 19 | `interpretacao-arquitetura/arquitetura.json` |
| 11 | `prompt-11-contratos.md` | 20 | `interpretacao-contratos/contratos.json` |
| 12 | `prompt-12-implementacao-e-testes.md` | 21 | `interpretacao-testes/implementacao.json` (a IA trabalha no repositório do código gerado) |
| 13 | `prompt-13-design-de-interfaces.md` | 20a | `interpretacao-design/design.json` |
| 14 | `prompt-14-implementacao.md` | 20b | `interpretacao-implementacao/padroes.json` |

Confira que toda tabela e coluna citada nos contratos `@ler` existe nos relatórios:

```bash
python3 analisador/fases/prompts/verificar_prompts.py <analise>
```

Mudar um prompt invalida a interpretação dele e a das fases seguintes: o pipeline refaz, e a verificação de proveniência acusa se não for refeita.

---

## 9. Verificações

Todas devem passar ao fim de uma análise:

| Verificação | Comando | O que prova |
|---|---|---|
| Equivalência IA x humano | `python3 analisador/tests/relatorios_equivalencia.py <analise>` | o HTML é a projeção exata do `report.json` |
| Contrato dos prompts | `python3 analisador/fases/prompts/verificar_prompts.py <analise>` | toda tabela e coluna que um prompt usa existe |
| Agnosticismo | `python3 analisador/tests/agnostico_smoke.py <analise>` | nenhum nome do sistema analisado em scripts ou prompts |
| Proveniência | `python3 analisador/fases/proveniencia.py verificar <interp>` | interpretação = bruto da IA (ou só com a poda) e prompt atual = prompt usado |
| Determinismo | `python3 analisador/tests/determinismo_hashseed.py <cópia-da-analise>` | relatórios idênticos sob 3 sementes de hash |
| Reprodução do zero | duas execuções de `analisar.py ... --sem-ia` em pastas diferentes e `--comparar` | mesmos bytes |
| Suíte do analisador | `python3 analisador/tests/rodar_todos.py <analise>` | testes do motor e do runtime |

---

## 10. Runtime: cenários, simulador e região CICS local

### 10.1 Runtime dos cenários

O runtime executa o COBOL sobre a AST, sem compilar, com DB2, MQ e CICS simulados (tabelas, filas, containers e status dados pelo cenário) e mocks para os programas que não se quer executar. É o que roda a fase 7 (seção 6.2). Formato dos cenários, mocks, entradas deduzidas e validações: `analisador/docs/17-RUNTIME-CENARIOS.md`.

### 10.2 Simulador multi-tecnologia (fixtures)

```bash
python3 analisador/cli.py <raiz> --scenario <cenario.json> [--out mainframe-simulation.json]
# exemplo com a fixture dos testes:
python3 analisador/cli.py analisador/tests/fixture --scenario analisador/tests/scenario.json --out simulacao.json
```

### 10.3 Região CICS local (`tools/cics_host.py`)

Executa programas COBOL como transações disparadas por fila, interpretados pelo runtime, para testar o código mainframe de um sistema modernizado de ponta a ponta.

```bash
python3 analisador/tools/cics_host.py <config.json>
```

| Modo | Como funciona |
|---|---|
| `internal` | IBM MQ e DB2 em memória, no próprio processo. Filas e massa do banco vêm da configuração |
| `external` | IBM MQ e DB2 de verdade (`pymqi`, `ibm_db`). Um monitor de gatilho, como o CKTI, lê a mensagem de disparo (MQTM) da fila de iniciação e inicia a transação |

Configuração (`${VAR}` e `${VAR:-padrão}` são trocados pela variável de ambiente):

```json
{
  "modo": "internal",
  "regiao": "NOMEREGIAO",
  "fontes": ["<pasta-dos-fontes>", "<outra-pasta>"],
  "csd": ["<arquivo-DFHCSDUP>"],
  "mqsc": ["<arquivo-RUNMQSC>"],
  "programas_adicionais": ["PROGCORP"],
  "instancias": 4,
  "max_passos": 5000000,
  "nativos": "nativos.py",
  "mocks": {},
  "http": 8080,
  "log_eventos": ["programa", "sql", "mq", "cics"],
  "internal": {"filas": [], "aliases": {}, "massa": "massa.json"},
  "external": {"mq":  {"host": "${MQ_HOST}", "porta": 1414, "qmgr": "QM1", "canal": "DEV.APP.SVRCONN", "usuario": "app", "senha": "${MQ_SENHA}"},
               "db2": {"banco": "LOCALDB", "host": "${DB2_HOST}", "porta": 50000, "usuario": "db2inst1", "senha": "${DB2_SENHA}",
                       "esquemas": {"ESQUEMA_DO_PROGRAMA": "ESQUEMA_DO_BANCO"}}}
}
```

- **`csd`**: arquivos DFHCSDUP. `DEFINE TRANSACTION ... PROGRAM` e `DEFINE PROGRAM` instalam as transações e os programas; `LINK` para programa não instalado devolve PGMIDERR.
- **`mqsc`**: arquivos RUNMQSC. Os gatilhos (`QLOCAL ... TRIGGER PROCESS` → `PROCESS APPLICID`) dão a fila de cada transação; no modo `internal`, as filas definidas viram filas em memória.
- **`nativos`**: módulo Python com `NATIVOS = {programa: função(runtime, estado)}`, para programas sem fonte (por exemplo corporativos em Assembler).
- **`mocks`**: mesmo formato dos cenários (`returns`, `scenarios` com `when`, `default`).

API HTTP (na porta `http`): `/` (painel com tarefas e eventos), `/status`, `/saude`, `GET /cemt` (CEMT INQUIRE TRANSACTION), `POST /cemt?transacao=X&estado=ENABLED|DISABLED` (CEMT SET), `POST /executar?transacao=X`. No modo `internal` também `POST /mq/<fila>` (grava; os cabeçalhos `replyTo` e `replyToQMgr` dão a fila de resposta), `GET /mq/<fila>?correlId=<id>&espera=<ms>` (lê) e `GET /db2/<tabela>`.

---

## 11. Testes do analisador

```bash
python3 analisador/tests/rodar_todos.py <analise>       # todos os *_smoke.py e a equivalência dos relatórios da análise
python3 analisador/tests/rodar_todos.py <analise> --parte=1/4   # só uma fatia (para shells com limite de tempo)
python3 analisador/tests/agnostico_smoke.py <analise>   # nenhum nome do sistema analisado em scripts e prompts
python3 analisador/tests/relatorios_equivalencia.py <analise>   # HTML = projeção exata do report.json
```

`<analise>` é a pasta de relatórios de uma análise (saída do `analisar.py`). Os testes do motor e do runtime usam as fixtures de `analisador/tests/` e não precisam dela; `agnostico_smoke.py` e `relatorios_equivalencia.py` precisam, porque tiram os nomes do sistema e os relatórios dessa pasta. Código de saída 1 se algum teste falhar.

---

## 12. Princípios da análise

1. **Determinístico vem de script.** Números, tabelas, diagramas, ids (`Q01`, `F01`, `Dnnn`) e o HTML saem dos scripts, sem edição manual.
2. **Julgamento vem de prompt.** A IA devolve JSON; o gerador valida (citação, id, cenário, coerência) e recusa o que não tem evidência.
3. **O método não conhece o sistema.** Nomes de programas, tabelas e campos vêm dos relatórios em tempo de execução; o que é do sistema fica em `analise.config.json` e nos dados da análise.
4. **A IA executa isolada**, só com o prompt e as fases do contrato `@ler`.
5. **Nada de edição manual da saída da IA.** A proveniência guarda o bruto e o hash do prompt; a única alteração permitida é a poda determinística, que só remove.
6. **Erro do validador volta para a mesma IA**, que corrige pelo prompt.
7. **Mesma entrada, mesma saída.** O `MANIFESTO.json` e o teste de determinismo garantem.

---

## 13. Problemas comuns

| Mensagem | Causa e o que fazer |
|---|---|
| `UNSUPPORTED_AST_<VERBO>` / `UNSUPPORTED_AST_EXEC_CICS_<OP>` | Verbo COBOL ou comando CICS que o runtime ainda não executa. Veja `docs/14-EXTENSAO-DE-NOVOS-RECURSOS.md` |
| `PERFORM_TARGET_NOT_FOUND` | Parágrafo ou seção inexistente no fonte expandido. Confira se os copybooks estão nas pastas de fontes |
| `PROGRAM_NOT_FOUND` / PGMIDERR | Programa chamado sem fonte: inclua o fonte, um mock no cenário ou um nativo na região CICS |
| `MAX_STEPS` | Laço que não termina com os dados do cenário, ou limite baixo: revise o cenário ou aumente `max_passos` |
| `UNSUPPORTED_SQL` | Comando SQL fora do que o DB2 do runtime trata: use `db2_status` ou um mock |
| Resultado diferente entre execuções | Rode `tests/determinismo_hashseed.py`; confira se a pasta de fontes é a mesma e se não há cache antigo (`<analise>.cache`) |
| Interpretação "não vale" no pipeline | O prompt mudou, o JSON foi editado à mão ou uma fase de entrada mudou: deixe o pipeline refazer o prompt |
| Comando cortado por tempo limite do shell | Repita o mesmo comando; o cache retoma e o resultado é idêntico |

Mais casos em `analisador/docs/13-TROUBLESHOOTING.md`.

---

## 14. Documentação detalhada

| Documento | Assunto |
|---|---|
| `analisador/docs/01-INSTALACAO-E-QUICKSTART.md` | Instalação e primeiros comandos |
| `analisador/docs/02-ARQUITETURA.md` | Arquitetura do analisador |
| `analisador/docs/03-DISCOVERY-TOKENS-AST.md` | Discovery, tokens e AST |
| `analisador/docs/04-COBOL-E-MEMORIA.md` | COBOL e memória no runtime sobre AST |
| `analisador/docs/05-CICS-E-BMS.md` | CICS e BMS/3270 |
| `analisador/docs/06-DB2.md` | DB2 |
| `analisador/docs/07-VSAM-IMS-MQ.md` | VSAM, IMS e MQ |
| `analisador/docs/08-JCL.md` | JCL |
| `analisador/docs/09-RUNTIME-E-TRACE.md` | Runtime determinístico e trace |
| `analisador/docs/10-CENARIOS-E-GOLDEN-CASES.md` | Cenários e golden cases |
| `analisador/docs/11-REGRAS-DE-NEGOCIO.md` | Regras de negócio |
| `analisador/docs/12-CERTIFICACAO.md` | Certificação |
| `analisador/docs/13-TROUBLESHOOTING.md` | Problemas e soluções |
| `analisador/docs/14-EXTENSAO-DE-NOVOS-RECURSOS.md` | Como estender o analisador |
| `analisador/docs/15-REFERENCIA-CLI-E-ARQUIVOS.md` | Referência de comandos e arquivos de saída |
| `analisador/docs/16-DCLGEN.md` | DCLGEN |
| `analisador/docs/17-RUNTIME-CENARIOS.md` | Formato dos cenários, mocks e validação |
| `analisador/docs/18-RELATORIOS-E-REPRODUCAO.md` | Relatórios de cada fase |
| `analisador/docs/19-REPRODUCAO-COMPLETA.md` | Roteiro completo de reprodução, do código aos relatórios de IA |
| `pipeline/README.md` | Comando `pipeline-analise` |
