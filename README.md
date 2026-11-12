# mainframe-analyzer

Análise de sistemas mainframe (COBOL/CICS/DB2), das fontes ao código modernizado, em fases (0 a 22). O repositório separa o **analisador** (o método, agnóstico ao sistema analisado), o **pipeline** (a orquestração que roda tudo sem intervenção humana) e os **dados** de cada análise.

```
mainframe-analyzer/
├── analisador/              o método: nada aqui conhece o sistema analisado (tests/agnostico_smoke.py confere)
│   ├── semantic_core/       motor da análise estática e dinâmica e dos relatórios (modelo, HTML, ligações)
│   ├── *_runtime.py, simulator.py, cli.py …   runtime dos cenários (CICS, DB2, MQ, VSAM, JCL …)
│   ├── tools/               analisar.py (fases 0 a 9), run_scenarios.py, certificação, relatórios
│   ├── fases/               geradores das fases 10 a 22 (gerar_*.py), prompts/ da IA, proveniencia.py e poda
│   ├── tests/               testes do método (rodar_todos.py; agnostico_smoke.py; relatorios_equivalencia.py)
│   ├── docs/                documentação do método
│   └── mainframe-analyzer   atalho de linha de comando (certify, run, modelo, dclgen)
├── pipeline/                pacote Python do comando pipeline-analise (instalar.py, pyproject.toml)
├── cenarios/<sistema>/      cenários da análise dinâmica e analise.config.json do sistema (dados)
└── analises/<análise>/      dados de cada análise: relatórios (analise/), respostas da IA (interpretacoes/),
                             pipeline.config.json e o trabalho do pipeline (.pipeline/)
```

- **Analisador**: `analisador/tools/analisar.py <fontes> <cenarios> <saida>` gera as fases 0 a 9; os geradores de `analisador/fases/` geram as fases 10 a 22 a partir dos relatórios e das interpretações da IA (`--interpretacao <pasta>` ou a variável `ANALISE_INTERPRETACOES`). O que depende do sistema analisado fica em `cenarios/<sistema>/analise.config.json` e nos dados da análise (interpretações, `nomes-atribuidos.json`, `interpretacao-adr/adr.json`), nunca nos scripts ou nos prompts.
- **Pipeline**: `pipeline-analise --ia-cli claude|kiro`, rodado na pasta da análise (ou com `--config`), executa todas as fases em sequência; a IA escolhida refaz os prompts cuja interpretação não vale mais e mostra no console tudo o que faz. `--apartada <pasta>` roda numa cópia e repete cada prompt até o resultado ficar parecido com a análise de referência. Ver `pipeline/README.md`.
- **Análises**: `analises/validacao-sql` é a análise de referência do TCAP (fases 0 a 22). As demais pastas de `analises/` são experimentos anteriores, com cópias antigas dos geradores; para rodá-los, use `ANALISE_RAIZ=<caminho>/analisador`.
