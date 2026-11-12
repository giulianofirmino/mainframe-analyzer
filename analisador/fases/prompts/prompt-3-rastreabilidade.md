# Prompt 3: rastreabilidade ponta a ponta (fase 13)

O relatório **traceability** (`13 - traceability`) é calculado por script (`gerar_simulacao.py`) a partir dos relatórios das fases 5, 6, 11 e 12 e da interpretação; você não escreve texto nele. Sem o gerador, monte-o assim, com os mesmos números.

## Entradas

```contrato
@ler fase=05 bloco="Mapa de decisão — {programa}" colunas="Código|Tipo|Linha|Condição ou comandos|Regras que usam|Execução"
@ler fase=06 bloco="Regras de {programa}" colunas="Regra|Decisões|Tipo|Subtipo|Escopo|Motivo do escopo|Condições (decisão → resultado)"
```

## Diagrama de 4 colunas, um por funcionalidade

A rastreabilidade é **por funcionalidade** (as do prompt 2): uma seção `rastreio-<id da funcionalidade>` com um diagrama de 4 colunas, da esquerda para a direita: **Decisão** (borda azul `#0072B2`), **Regra determinística** (verde `#1E8E3E`), **Regra de negócio** (laranja `#F28C00`) e **Funcionalidade** (vermelho `#D32F2F`). Os programas da funcionalidade são o programa de entrada dela (ou os de entrada das regras que ela cita, mais os alcançados na fase 7, sem os CORPORATIVOS). **Nada é omitido**: entram todas as decisões desses programas e todas as regras determinísticas que a funcionalidade alcança.

- Decisão ou regra **descartada** (sem regra de negócio, laço de repetição, filtrada por infraestrutura, mecanismo implícito) aparece em **cinza tracejado**, com a legenda "descartada: <motivo curto>" no nó.
- Cada seção `rastreio-<id>` tem um checkbox "Mostrar descartados" (marcado por padrão) que esconde ou mostra os nós e ligações em cinza e as linhas descartadas da tabela, para ver só o essencial; nada é removido do relatório.
- Ligação decisão → regra: sólida quando a decisão escolhe o ramo da regra (a última da condição, sem as técnicas); tracejada quando só protege o caminho (guarda). Regra de negócio → funcionalidade ligam à funcionalidade da seção.
- Nós de cada coluna na ordem que menos cruza as ligações (varreduras de baricentro).
- A tabela do diagrama tem as colunas: Decisão · Regra determinística · Regra de negócio · Funcionalidade · Situação · **Motivo** (de todo descarte) · **Vínculo não feito** (o que faltou ligar: decisão sem regra, regra sem decisão nas condições, regra sem regra de negócio, regra de negócio sem funcionalidade). Uma linha por par, mais as decisões e regras sem par.
- A seção `funcionalidades` traz a tabela "Por funcionalidade" (contagens de decisões, regras, descartes e vínculos não feitos) e a tabela "Fora de qualquer funcionalidade" (decisões e regras que nenhuma funcionalidade alcança, com motivo).

## Rastreio ponta a ponta: layout e cálculo

A seção "Rastreio: decisão → regra determinística → regra de negócio → funcionalidade" do relatório é toda calculada dos relatórios e da sua interpretação; você não escreve texto nela, mas sem o gerador precisa montá-la assim, com os mesmos números:

1. **Destino de cada regra determinística** (fase 6, todas as tabelas `Regras de <programa>`): `regra de negócio` (está em algum grupo do prompt 1), `mecanismo implícito` (escopo da fase 6 `mecanismos implícitos`, inclusive o que a IA julgou mecanismo ou permissão de acesso; motivo = `Motivo do escopo`), `filtrada: infraestrutura` (escopo infraestrutura ou programa de infraestrutura na fase 0; motivo = `Motivo do escopo`), `filtrada: fora da abrangência` (escopo `fora da abrangência`: nenhum cenário de execução dinâmica alcança a regra; motivo = `Motivo do escopo`) ou `sem classificação` (deve ser zero).
2. **Situação de cada decisão** (fase 5, tabelas `Mapa de decisão — <programa>`, linhas de tipo `decisão`; regras = coluna `Regras que usam`): `regra de negócio` se alguma regra que ela decide está em grupo; `mecanismo implícito` se só decide regras de mecanismos implícitos; `descartada` caso contrário, com motivo: sem regra e a condição começa por `PERFORM` (laço de repetição); sem regra nenhuma (nenhum caminho com efeito de negócio depende dela); só regras filtradas (infraestrutura), com o motivo de cada uma; `sem classificação` se alguma regra dela não tem destino.
3. **Funil**: decisões por situação; regras determinísticas por destino; regras de negócio e quantas regras determinísticas as sustentam; conferência = número de decisões cuja `Regras que usam` (fase 5) difere do conjunto de regras que a citam nas condições (fase 6), que deve ser 0. Depois, tabela por programa (decisões, em regra de negócio, descartadas, de mecanismos; regras por destino) e tabelas de motivos de descarte com contagem.
4. **Tabela de rastreabilidade ponta a ponta**, colunas: Programa · Decisão (`PROGRAMA:Dnnn`) · Linha · Condição da decisão · Execução · Situação da decisão · Regra determinística (`PROGRAMA:Rnnn`) · Tipo · Subtipo · Escopo · Situação da regra · Regra de negócio (id da regra, com link para a fase 11) · Funcionalidades (com link para a fase 12, pelas funcionalidades que citam a regra de negócio) · Motivo do descarte.
   - **Uma linha por par decisão × regra determinística**; decisão sem regra e regra sem decisão nas condições também têm linha (com `—` do outro lado). **Nada é agrupado**: cada decisão e cada regra determinística aparece na sua própria linha, com o motivo individual de todo descarte.
   - Linhas de mecanismos implícitos têm fundo azul claro.
   - Ordem: por programa, linha e código da decisão. Toda decisão e toda regra determinística deve aparecer; nenhum descarte fica sem motivo.
   - Há um campo de filtro de texto sobre a tabela.

## Seções e cartões do relatório

Seções, nesta ordem: `rastreio` (texto, funil, por programa, motivos de descarte das decisões e das regras, tabela ponta a ponta) `funcionalidades` (por funcionalidade e fora de qualquer funcionalidade) e uma seção `rastreio-<id>` por funcionalidade (diagrama de 4 colunas com descartados em cinza e a tabela com Situação, Motivo e Vínculo não feito). Cartões: decisões, regras determinísticas, regras de negócio, funcionalidades. Os dois formatos (`ia/report.json` e `human/report.html`) vêm do mesmo modelo; os códigos de decisão, regra, programa e tabela viram link (programa → mapa de decisões da fase 5; tabela → esquema de dados da fase 3).
