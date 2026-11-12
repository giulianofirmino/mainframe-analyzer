# pipeline-analise

Roda a análise inteira, das fontes COBOL ao último relatório (fases 0 a 23), em uma sequência e sem intervenção humana. As etapas de IA são executadas por uma CLI de IA escolhida na chamada: **Claude Code CLI** (`claude`) ou **Kiro CLI** (`kiro-cli`). As duas mostram no console tudo o que fazem: o texto da IA, cada ferramenta usada com os argumentos e o resultado.

## Instalação

```
python3 instalar.py            # pipx, uv ou pip, se existir; senão instala direto em ~/.local/bin
python3 instalar.py --editavel # usa o código desta pasta (alterações valem na hora)
python3 instalar.py --desinstalar
```

Também é um pacote Python padrão: `pipx install .`, `uv tool install .` ou `pip install .` criam o comando `pipeline-analise`, inclusive no Windows.

## Uso

```
pipeline-analise --ia-cli claude                 # tudo, refazendo só os prompts cuja interpretação não vale mais
pipeline-analise --ia-cli kiro --ia sempre       # refaz todos os prompts com o Kiro CLI
pipeline-analise --ia nunca                      # só reaproveita as interpretações (falha se alguma não valer)
pipeline-analise --ia-cli claude --desde 16 --ate 20
pipeline-analise --ia-cli claude --deterministico refazer   # executa de novo os cenários da análise dinâmica
```

A configuração vem de `--config`, da variável `PIPELINE_ANALISE_CONFIG` ou de `./pipeline.config.json` (cada análise tem o seu, em `analises/<análise>/`): o analisador (`raiz_analisador`, com os geradores e prompts em `fases/`), a pasta dos relatórios, a das interpretações, das fontes COBOL, dos cenários, do PDC, da aplicação web antiga e do repositório do código gerado, e as opções de cada CLI (comando, modelo, ferramentas permitidas, tentativas, turnos e tempo limite).

## Etapas

| Etapa | O que faz |
|---|---|
| `0-9` | Fases determinísticas (`tools/analisar.py`): análise estática, cenários da análise dinâmica, certificação e relatórios |
| `10` a `20` | Fases de IA: reaproveita a interpretação que ainda vale ou a refaz pela IA isolada; o gerador valida e, se recusar, a mensagem volta para a mesma conversa da IA (até `tentativas` vezes); a resposta aceita é registrada na proveniência. A `14` (PDC) é determinística |
| `21` | Sobe o ambiente local, refaz a implementação pelo prompt 12 quando necessário (a IA trabalha no repositório do código gerado), roda os testes unitários e ponta a ponta e gera a rastreabilidade to-be |
| `22` | Architecture Decision Records (registro do dono da arquitetura, não é IA) |
| `23` | Enhancement Proposals (propostas de melhoria do processo; registro do dono da arquitetura, não é IA) |
| `final` | Referências cruzadas, verificação dos prompts, da proveniência e da equivalência IA x humano, e `MANIFESTO.json` |

Uma interpretação de IA vale quando a proveniência está em ordem (o prompt não mudou e o arquivo é o que a IA devolveu, no máximo com a poda determinística) e as fases que o prompt lê não mudaram desde a última geração (hash guardado em `<trabalho>/estado.json`).

A IA isolada roda numa pasta de trabalho só com o `PROMPT.md`, as fases que o contrato `@ler` do prompt lista (`entrada/<fase>/ia/report.json`) e a pasta `saida/`; ela não vê o código analisado nem interpretações anteriores.

## Registro

- Console e `<trabalho>/pipeline.log`: cada passo, a saída dos scripts e tudo o que a IA faz (`[claude]` ou `[kiro]`).
- `<trabalho>/execucoes/<data-hora>.json`: etapas, situação, tempo, motivo de refazer cada prompt, conversas da IA (sessão, turnos e custo, quando a CLI informa).
- Código de saída 0 quando tudo terminou; 1 quando uma etapa falhou (a mensagem diz qual e por quê).

## Execução apartada

```
pipeline-analise --ia-cli claude --apartada <pasta> [--referencia <analise>] [--limiar 0.85] [--ciclos 5] [--realimentar]
```

Copia a análise de referência e as interpretações para `<pasta>` (a referência não muda), refaz todos os prompts pela IA e, a cada prompt, compara as fases geradas com as da referência (indicadores, estrutura e conteúdo das tabelas; nota de 0 a 1). Enquanto a nota fica abaixo do limiar, repete o prompt com uma conversa nova (os prompts 2 e 4, que escrevem juntos a fase 12, repetem juntos); no limite de ciclos (0 = sem limite) fica com o melhor ciclo. Com `--realimentar`, a IA recebe onde o ciclo anterior divergiu. A implementação do código gerado (prompt 12) não é refeita: a fase 21 reaproveita a interpretação e os resultados dos testes. No fim, `<pasta>/comparacao.json` traz a nota de cada fase; o código de saída é 2 quando alguma ficou abaixo do limiar.
