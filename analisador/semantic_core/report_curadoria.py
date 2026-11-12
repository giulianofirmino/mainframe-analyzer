"""Curadoria dos relatórios: o que cada página mostra e como, sobre o modelo já gerado (ia/report.json).

Para cada fase: o objetivo (no lugar do subtítulo), os números principais, descrições curtas para cada diagrama com a legenda uma vez só,
textos longos resumidos ou virados ficha ou tabela, tabelas que repetem outra retiradas ou fundidas e os itens repetidos agrupados por
título. O subtítulo e o resumo completo (summary) ficam no modelo como estavam: a página de entrada (index.html) usa os dois.

Idempotente: roda no fim de cada geração (report_render.reindexar) e sobre relatórios já entregues (tools/curar_relatorios.py) sem
regerar as fases; rodar de novo não muda nada."""
import re

COMO_LER = 'Como ler'


def _t(v):
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return (v.get('text') or ''.join(p if isinstance(p, str) else p.get('text', '') for p in v.get('parts') or [])
                or ' '.join(l.get('text', '') for l in v.get('links') or []))
    return '' if v is None else str(v)


def fase(m):
    """'04b-lineage-summary' → '04b'; '10 - sql-mapping' → '10'."""
    return (m.get('phase') or '').split('-')[0].strip()


def X(text, title=None):
    return {'type': 'text', 'title': title, 'text': text}


def ficha(title, pares):
    return {'type': 'table', 'title': title, 'columns': ['Campo', 'Conteúdo'], 'rows': [list(p) for p in pares], 'note': None}


def tabela(title, cols, rows, note=None):
    return {'type': 'table', 'title': title, 'columns': cols, 'rows': [list(r) for r in rows], 'note': note}


# ----------------------------------------------------------------------------- configuração por fase
# objetivo: frase do topo da página. destaques: rótulos do summary que viram os números da página (rótulo ou (rótulo, rótulo exibido)).
# textos: (padrão, novo) com re.fullmatch sobre textos de seção, blocos de texto e notas; novo é texto (com \1…) ou função(match) que devolve
#   texto ou, num bloco de texto, uma lista de blocos. diagramas: (padrão do título, descrição curta com \1…). legendas: (padrão do título do
#   diagrama, bloco) — o bloco entra uma vez, antes do primeiro diagrama que casa. remover: padrões de título (ou (id da seção, padrão)) de
#   blocos repetidos. fundir: tabelas de mesma chave numa só. grupos: (padrão do id da seção, título do grupo, descrição do grupo).
#   titulos: {id da seção: título}. termos: trocas de termos em títulos, textos e notas.

def _num(m, i):
    return m.group(i)


FASES = {
    '00': {
        'objetivo': 'Classificar cada programa pelo papel que ele cumpre (interface, coordenador, funcional, corporativo ou infraestrutura) para decidir como cada um é tratado na modernização.',
        'destaques': ['programas', 'COORDENADOR', 'FUNCIONAL', 'CORPORATIVO', 'INFRAESTRUTURA'],
    },
    '01': {
        'objetivo': 'Mapear quem chama quem e quais tabelas e copybooks cada programa usa, e confirmar na execução o que é chamado de fato.',
        'destaques': ['programas', 'chamadas', 'tabelas DB2', 'copybooks', 'chamadas não resolvidas'],
        'diagramas': [(r'Chamadas entre programas.*', 'Quem chama quem (LINK e CALL). Cor = classe do programa: azul coordenador, verde funcional, laranja corporativo, vermelho infraestrutura.'),
                      (r'Programa → copybook', 'Copybooks que cada programa inclui.'),
                      (r'Programa → tabela.*', 'Tabelas DB2 que cada programa acessa, com o cursor resolvido até a tabela.')],
    },
    '02': {
        'objetivo': 'Identificar, em cada programa, os campos de entrada e de saída de cada copybook e os que não são usados.',
        'destaques': ['programas', 'copybooks', 'copybooks usados'],
        'textos': [(r'Um diagrama por programa: as entradas à esquerda.*',
                    'Um diagrama por programa: campos de entrada (lidos) à esquerda e de saída (escritos) à direita. Tracejado = campo não usado ou '
                    'programa que nenhum cenário alcançou. Só entram os copybooks do próprio programa que são entrada ou saída dele.')],
        'diagramas': [(r'(\S+): campos de entrada e saída dos copybooks', r'Campos que \1 lê (à esquerda) e grava (à direita) em cada copybook.')],
        'remover': [r'Tabela do diagrama: relacionamentos — .*'],
    },
    '03': {
        'objetivo': 'Descrever as tabelas DB2 do sistema, as colunas e o uso de cada uma, deduzindo o esquema onde falta o DCLGEN.',
        'destaques': ['tabelas', 'com DCLGEN', 'sem DCLGEN (deduzidas)', 'colunas usadas'],
        'textos': [(r'Cada diagrama mostra uma tabela e todas as suas colunas\..*',
'Um diagrama por tabela, com todas as colunas, e logo abaixo a tabela das colunas (tipo, campo COBOL e uso). Coluna riscada em vermelho (✕) = nunca usada no código ou não exercitada pelos cenários; '
                    'tabela cinza tracejada = nenhum cenário a alcançou. Situação: usada = algum programa usa o campo mapeado ou cita a coluna no SQL. '
                    'Tipo "(inferido)" = sem DCLGEN, deduzido do uso no SQL, da PIC do campo ou dos valores vistos nos cenários; "indeterminado" = nenhuma pista do tipo.')],
        'diagramas': [(r'Tabelas do sistema por papel', 'Tabelas do sistema e os vínculos entre elas, pela cor do papel.'),
                      (r'(\S+): (protagonista|coadjuvante|figurante).*', r'Colunas de \1 (\2).')],
        'remover': [r'Tabela do diagrama: colunas — .*', r'Tabela do diagrama: relacionamentos — .*'],
    },
    '04': {
        'objetivo': 'Rastrear, tabela a tabela, de onde vem cada dado gravado ou usado como filtro e para onde vai cada coluna lida.',
        'destaques': ['tabelas', 'comandos SQL', 'comandos que gravam', 'comandos que consultam', 'tabelas não alcançadas'],
        'fundir': [{'a': r'Quem grava e quem consulta cada tabela', 'b': r'Comandos SQL por tabela e tipo.*', 'chave_a': 'Tabela', 'chave_b': 'Tabela',
                    'titulo': 'Comandos SQL por tabela: quem grava, quem consulta e os tipos de comando'}],
        'diagramas': [(r'Fluxo de dados — (\S+) no programa (\S+)( \[.*\])?', r'Caminho de cada dado entre \2 e \1: a origem do que é gravado ou filtrado e o destino do que é lido.')],
        'grupos': [(r'tab-.*', 'Linhagem por tabela',
                    'Nos diagramas, gravação: origem → campos por onde o valor passa → TABELA.COLUNA; filtro (WHERE): origem → campos → TABELA.COLUNA → comando; '
                    'consulta: comando → TABELA.COLUNA → campo que recebe → destino (gravação, chave de outra consulta ou saída do programa). '
                    'O caminho pelos programas e as condições estão nas tabelas de cada seção.')],
    },
    '04b': {
        'objetivo': 'Resumir por programa a linhagem da fase anterior: chamadas, comandos SQL, tabelas e o fluxo de dados de todos os comandos.',
        'destaques': ['programas', 'comandos SQL', 'comandos executados', 'tabelas'],
        'textos': [(r'Relatório gerado por script \(nenhuma IA\).*', 'Resumo por programa da linhagem de dados, gerado por script, sem IA.')],
        'inicio': {'leitura': [ficha('Como ler cada programa', [
            ['Relação', 'Programas que o chamam, os que ele chama, os comandos SQL dele e as tabelas.'],
            ['Encadeamento', 'Qual comando lê o dado que outro usa e qual só executa conforme o status de outro.'],
            ['Fluxo de dados', 'Um diagrama com todos os comandos: de onde vem cada condição (WHERE) e cada parâmetro (VALUES, SET), até a origem mais distante, e para onde vai cada coluna lida.'],
            ['Não executado', 'Cinza tracejado: nenhum cenário da análise dinâmica executou. A caixa da seção esconde esses itens.'],
            ['Referência completa', 'Os links levam ao comando na Linhagem de dados.']])]},
        'diagramas': [(r'Relação de (\S+): chamadas, comandos SQL e tabelas', r'Quem chama \1, quem ele chama, os comandos SQL dele e as tabelas. Cor do programa = classe; comando verde-água lê, roxo grava.'),
                      (r'Encadeamento dos comandos SQL de (\S+)', r'Ordem entre os comandos SQL de \1: linha cheia = dado que um comando passa ao outro; tracejada = só executa conforme o status do anterior.'),
                      (r'Fluxo de dados de (\S+): todos os comandos SQL', r'Entradas de \1 à esquerda (marrom = WHERE, cinza-azulado = parâmetro VALUES ou SET) e colunas lidas à direita, com a condição que escolhe cada origem.')],
        'grupos': [(r'rp-.*', 'Linhagem por programa', None)],
    },
    '05': {
        'objetivo': 'Tornar legível cada decisão e cada trecho de comandos do código, parágrafo a parágrafo, e mostrar o que a execução não alcançou.',
        'destaques': ['programas', 'decisões', 'trechos não executados'],
        'textos': [(r'Cada decisão \(Dnnn\) e caixa de execução \(Ennn\) aparece cinza tracejada.*',
                    'Cinza tracejado = nenhum cenário passou pela decisão (Dnnn) ou pela caixa de execução (Ennn); fundo amarelo claro = mockada (programa não '
                    'executado de verdade ou chamada com retorno definido pelo cenário). O motivo de cada trecho está na tabela "Trechos não executados" do programa.'),
                   (r'(\d+ decisões e \d+ caixas de execução em \d+ parágrafos)\. Losango = .*?\. (\d+) trechos não executados pelos cenários\.', r'\1; \2 trechos não executados pelos cenários.')],
        'diagramas': [(r'Chamadas entre parágrafos — (\S+)', r'Como os parágrafos de \1 se chamam (PERFORM).'),
                      (r'(\S+) — (\S+)', r'Decisões e comandos do parágrafo \2.')],
        'grupos': [(r'prog-.*', 'Mapa de decisão por programa',
                    'Losango = decisão (IF/ELSIF; EVALUATE vira cadeia IF/ELSIF); retângulo = comandos do trecho, na ordem do código; a cor é o tipo do que o trecho faz.')],
    },
    '06': {
        'objetivo': 'Extrair do código, sem interpretação de negócio, cada caminho de decisão com os efeitos dele (a regra determinística).',
        'destaques': ['regras', 'de negócio', 'de infraestrutura', 'mecanismos implícitos', 'programas com regras'],
        'grupos': [(r'reg-.*', 'Regras por programa', None)],
    },
    '07': {
        'objetivo': 'Executar os cenários contra a análise estática e medir a cobertura de ramos e de regras.',
        'destaques': ['cenários', 'aprovados', 'ramos exercitados', 'regras exercitadas'],
        'diagramas': [(r'Fluxo de execução — (\S+)', r'Programas que o entry point \1 executa, com o percentual de ramos alcançáveis que os cenários exercitaram.')],
    },
    '10': {
        'objetivo': 'Reunir todos os comandos SQL do sistema, unificar os equivalentes e explicar o propósito, as colunas e as condições de cada um.',
        'destaques': ['comandos SQL estáticos', 'queries (após unificar)', 'tabelas', 'consultas dinâmicas'],
        'textos': [(r'(\d+) comandos SQL estáticos \(agrupados por programa, tabela e cursor\) em (\d+) programas, \d+ linhas de comando na compilação, (\d+) tabelas\. '
                    r'Os comandos de leitura com o mesmo FROM e o mesmo WHERE.*?: (\d+) comandos viraram (\d+) queries, e o total é de (\d+) queries\. '
                    r'Consultas dinâmicas descobertas: (\d+).*?internalizadas em (\d+) comando.*',
                    r'\1 comandos SQL estáticos em \2 programas e \3 tabelas. Leituras com o mesmo FROM e o mesmo WHERE viram uma query única (\4 comandos em \5 queries; \6 queries no total). '
                    r'\7 consulta dinâmica, internalizada em \8 comandos Qnn. Cada comando é explicado: propósito, colunas, condições e retorno.'),
                   (r'Comandos de leitura \(SELECT\) com o mesmo FROM e o mesmo WHERE são a mesma consulta.*',
                    'Leituras com o mesmo FROM e o mesmo WHERE são a mesma consulta: a query única leva o menor código e devolve a união das colunas. '
                    'Gravações e leituras com FROM ou WHERE diferentes não são unificadas.'),
                   (r'A análise determinística só vê tabelas citadas em comandos SQL\..*',
                    'Tabelas que um serviço genérico lê porque o chamador passa o nome por parâmetro. Na modernização cada consulta dinâmica vira comando '
                    'estático com a tabela fixada (código Qnn).')],
        'diagramas': [(r'Programas, comandos SQL e tabelas: .*', 'Quem lê e quem grava cada tabela: programa → comando SQL → tabela, só o que a execução alcançou.'),
                      (r'Programa (\S+): quem o chama, comandos SQL que executa e tabelas envolvidas', r'Quem chama \1, os comandos SQL que ele executa e as tabelas.'),
                      (r'Relação de dados entre os comandos SQL de (\S+)', r'Dados que um comando SQL de \1 entrega a outro.'),
                      (r'Origem dos dados de (\S+) \(consulta dinâmica (\S+) internalizada\)', r'De onde vêm o nome da tabela e os parâmetros de \1 (consulta dinâmica \2) e quem usa as colunas lidas.'),
                      (r'Origem dos dados de (\S+)', r'De onde vêm as condições e os parâmetros de \1 e para onde vão as colunas lidas.')],
        'legendas': [(r'Programa (\S+): quem o chama.*', X('Borda do programa = classe (azul coordenador, verde funcional, laranja corporativo, vermelho infraestrutura). '
                                                          'Comando azul-petróleo lê, roxo grava; ◇ Qnn = comando estático que substitui consulta dinâmica. '
                                                          'Nos diagramas de origem, marrom = WHERE e cinza-azulado = parâmetro VALUES ou SET. Cinza tracejado: nenhum cenário executou.', COMO_LER))],
        'remover': [('compilacao-sql', r'Comandos SQL por programa'), r'Relação de dados entre os comandos SQL de \S+: tabela'],
        'grupos': [(r'prog-.*', 'Comandos SQL por programa', None), (r'([A-Z0-9]{8})-Q\d+', r'Queries de \1', None), (r'(dinamicas|D\d+)', 'Consultas dinâmicas', None)],
        'fichas': r'[A-Z0-9]{8}-Q\d+|D\d+',
    },
    '11': {
        'objetivo': 'Transformar as regras determinísticas de escopo de negócio em regras de negócio legíveis, cada uma com a evidência e as lacunas.',
        'destaques': ['regras determinísticas', 'filtradas (infraestrutura)', 'em regra de negócio', 'regras de negócio'],
        'textos': [(r'(\d+) campos são testados pelas regras de negócio; (\d+) têm significado.*',
                    r'\1 campos testados pelas regras de negócio, \2 com significado deduzido pela IA (nome, valores comparados e uso). A confiança diz quanto a evidência sustenta.'),
                   (r'Cada regra de negócio pertence a um único programa.*',
                    'Uma regra de negócio por programa (sufixo do id), exceto nos programas corporativos, cujas regras servem a vários entry points. '
                    'Cada regra tem a sua seção, agrupada pela categoria: ficha, campos testados e a evidência das regras determinísticas.')],
        'grupos': 'categoria',
        'fichas': r'[A-Z]\d\d\.\S+',
    },
    '12': {
        'objetivo': 'Descrever o que cada funcionalidade faz, em que ordem, com que dados e regras, só com o que a execução alcançou.',
        'destaques': ['funcionalidades', 'de entry point', 'de programa corporativo', 'tabelas alcançadas'],
        'textos': [(r'(\d+) entry points e (\d+) programas corporativos alcançados; (\d+) funcionalidades descritas\..*',
                    r'\3 funcionalidades: \1 de entry point e \2 de programa corporativo. Só entra o que algum cenário alcançou na análise dinâmica.'),
                   (r'Cada linha é uma funcionalidade: F = baseada em entry point.*',
                    'Uma linha por funcionalidade (F = entry point, FC = programa corporativo), com as regras de negócio por categoria na ordem em que acontecem. '
                    'Comando que lê em azul-petróleo, que grava em roxo.'),
                   (r'(\d+) funcionalidades; (\d+) regras de negócio posicionadas nos fluxos internos; (\d+) chamadas a funcionalidades corporativas dentro dos fluxos; '
                    r'(\d+) ligações internas, (\d+) de confiança alta \((\d+%)\); (\d+) lacunas.*',
                    r'\2 regras de negócio e \3 chamadas corporativas nos fluxos internos das \1 funcionalidades; \4 ligações, \5 de confiança alta (\6); \7 lacunas.')],
        'diagramas': [(r'Relação entre as funcionalidades: quem chama quem', 'Que funcionalidade de entry point (F, borda azul) chama que funcionalidade corporativa (FC, borda laranja).'),
                      (r'(\S+): fluxo interno.*', r'Ordem das regras de negócio e das chamadas corporativas de \1, da ENTRADA à SAÍDA.')],
        'remover': [r'Fluxo de F\S+', r'Tabela do fluxo de F\S+'],
        'grupos': [(r'F\d+', 'Funcionalidades de entry point',
                    'No fluxo interno, a seta diz por que um passo vem depois do outro: dado (o que um produz o outro usa), condição, estado (tabela gravada e lida), '
                    'chama (funcionalidade corporativa) ou ordem. As cores são as categorias das regras do diagrama macro.'),
                   (r'FC\d+', 'Funcionalidades corporativas', None)],
        'fichas': r'FC?\d+',
    },
    '13': {
        'objetivo': 'Ligar cada decisão do código à regra de negócio, à funcionalidade e às classes do código que a implementam.',
        'destaques': ['decisões', 'regras determinísticas', 'regras de negócio', 'funcionalidades', 'classes que implementam regras'],
        'textos': [(r'Linhas com fundo azul: regras .*',
                    'Uma linha por par decisão × regra determinística, da decisão (fase 5) à regra de negócio, sem agrupar. Fundo azul = mecanismo implícito; '
                    '"—" = decisão sem regra ou regra sem decisão.'),
                   (r'Cada regra de negócio do rastreio vai até onde foi implementada.*',
                    'Cada regra de negócio até o caso de uso, a aplicação e as classes do código gerado; o link leva ao trecho em Casos de teste e evidências.')],
        'diagramas': [(r'Rastreabilidade de (\S+)', r'Decisões → regras determinísticas → regras de negócio → \1.')],
        'remover': [r'Tabela do diagrama — F\S+'],
        'titulos': {'funcionalidades': 'Resumo por funcionalidade'},
        'grupos': [(r'(funcionalidades|rastreio-F.*)', 'Rastreabilidade por funcionalidade',
                    'Colunas do diagrama, da esquerda para a direita: decisão, regra determinística, regra de negócio e funcionalidade. Cinza tracejado = não chega a regra de negócio '
                    '(o motivo está no nó e na tabela ponta a ponta); linha cheia = decisão que escolhe o ramo da regra, pontilhada = decisão de guarda do caminho.')],
    },
    '14': {
        'objetivo': 'Ligar os processos do PDC (processo, ação e transação) aos programas analisados.',
        'destaques': ['processos distintos', 'ações', 'transações (programas PDC)', 'com programa analisado'],
        'textos': [(r'(\d+) arquivos XML lidos em pdc; (\d+) processos .*?, (\d+) processos distintos, (\d+) ações e (\d+) transações\..*?'
                    r'Correlação com os programas analisados: (\d+) transação\(ões\) com o mesmo nome de um programa; (\d+) por layout .*?; (\d+) fora da análise.*',
                    r'\1 arquivos XML do PDC: \3 processos distintos (\2 contando versões), \4 ações e \5 transações. Correlação com os programas analisados: '
                    r'\6 pelo nome, \7 pelo layout e \8 fora da análise.'),
                   (r'(\d+) linhas: (\d+) processos distintos em (\d+) transações .*',
                    r'\2 processos distintos em \3 transações cujo programa não está entre os fontes analisados (\1 linhas, uma por processo e transação).')],
        'textos_bloco': [(r'A transação FWO do PDC é o identificador da transação mainframe.*', lambda m: [ficha('Critério da correlação', [
            ['Chave', 'A transação FWO do PDC identifica a transação mainframe.'],
            ['Pelo nome', 'Programa com o mesmo nome da transação.'],
            ['Pelo layout', 'Programa que inclui por COPY os registros (TCAPWxxx) que a transação trafega; um layout em vários programas liga a transação a todos (coordenador e funcional).'],
            ['Sem correlação', 'Nem o nome nem o layout coincidem com um programa analisado.']])])],
        'diagramas': [(r'Processo PDC → ação → transação → programa analisado', 'Processo PDC → ação → transação → programa analisado. Borda = classe do programa; cinza tracejado = não executado de verdade.')],
    },
    '15': {
        'objetivo': 'Ligar cada processo do PDC às telas, classes e endpoints da intranet e os campos de cada tela aos campos da transação.',
        'destaques': ['processos PDC', ('processos detalhados (programa executado)', 'processos detalhados'), 'telas mantidas no funil', ('campos de tela ligados a campos de transação', 'campos de tela ligados')],
        'textos': [(r'Universo: (\d+) programa\(s\) correlacionado\(s\) a transações do PDC .*?; (\d+) executado\(s\) na análise dinâmica\..*',
                    r'Universo: \1 programas correlacionados a transações do PDC, \2 executados na análise dinâmica.')],
        'textos_bloco': [(r'Critério do funil: .*?Ficam as telas que usam pelo menos (\d+) dos (\d+) programas.*?Resultado: (\d+) tela\(s\) mantida\(s\), (\d+) omitida\(s\) por cobertura baixa, (\d+) omitida\(s\) sem programa\.',
                          lambda m: [ficha('Critério do funil', [
                              ['Relação direta', 'Campo ou botão da tela ligado ao processo.'],
                              ['Relação por bean', 'A tela usa um managed bean que chega ao serviço do processo.'],
                              ['Mantida', f'A tela usa pelo menos {m.group(1)} dos {m.group(2)} programas (80% do universo ou a maior cobertura encontrada).'],
                              ['Omitida', 'Cobertura menor (aparece só na tabela de cobertura) ou nenhum programa mapeado.'],
                              ['Resultado', f'{m.group(3)} telas mantidas, {m.group(4)} omitidas por cobertura baixa e {m.group(5)} sem programa.']])])],
        'diagramas': [(r'Telas → Processos → Programas', 'Da tela ao processo que ela usa e do processo ao programa da transação; programa apagado = não executado.'),
                      (r'Caminho de (\S+): da tela ao programa mainframe', r'Da tela ao programa mainframe de \1: tela → ação → managed bean → serviço → processo PDC → transação.'),
                      (r'Campos de (\S+): saída.*', r'Campos que a transação de \1 devolve, até a tela.'),
                      (r'Campos de (\S+): entrada.*', r'Campos que o usuário informa na tela, até a transação de \1.')],
        'grupos': [(r'proc-.*', 'Processos detalhados',
                    'Cores do caminho: azul-índigo = tela; laranja = ação da tela; verde-água = managed bean; marrom = serviço; cinza-azulado = processo PDC; '
                    'azul = transação e programa coordenador. Tela sem botão do fluxo liga ao bean por um campo vinculado.')],
    },
    '16': {
        'objetivo': 'Traduzir o modelo físico (tabelas e vínculos) em modelo de domínio: classes, associações, agregados e invariantes.',
        'destaques': ['classes de domínio', 'agregados', 'relacionamentos', ('tabelas (atingidas na execução dinâmica)', 'tabelas atingidas')],
        'textos_bloco': [(r'Escopo: só as tabelas que a análise dinâmica atingiu.*', lambda m: [ficha('Como o modelo foi montado', [
            ['Escopo', 'Tabelas que a análise dinâmica atingiu (fase 4) e as tabelas dinâmicas do mapeamento SQL; as não atingidas ficam de fora.'],
            ['Entrada', 'Tabelas, colunas, tipos e nulidade (fase 3); WHERE, chaves de busca e gravações com a origem de cada valor (fase 4).'],
            ['Tradução', 'Tabela → classe; coluna → atributo (sem prefixo SQL, abreviações expandidas, CamelCase, singular); vínculo → associação 1:1, 1:N ou N:N; '
                         'NOT NULL, identidade e filtros de estado → invariantes.'],
            ['Agregado', 'Raiz única como ponto de entrada, que garante as invariantes.'],
            ['Fora', 'Código, anotações de framework e o agrupamento em contextos (próxima fase).']])])],
        'diagramas': [(r'Classes de domínio e associações.*', 'Classes de domínio e associações, agrupadas por agregado. «Agregado» = raiz, «Entidade» = membro; a seta vai do todo para a parte (1:1, 1:N ou N:N).')],
    },
    '17': {
        'objetivo': 'Definir como cada funcionalidade acessa os dados (agregado, Group Query ou programa corporativo) e avaliar chamadas, latência e N+1.',
        'destaques': ['funcionalidades', 'comandos SQL', 'queries multi-owner', 'com N+1'],
        'textos': [(r'As leituras de uma só tabela são executadas pelos agregados; as de várias tabelas ficam em Query Legacy, e (\d+) delas foram agrupadas em (\d+) Group Queries.*',
                    r'Leituras de uma tabela e gravações ficam nos agregados; leituras de várias tabelas ficam em Query Legacy (\1 delas reunidas em \2 Group Queries); '
                    r'os agregados corporativos chamam os programas corporativos originais (LEGACY).'),
                   (r'Resume as chamadas e o N\+1 das funcionalidades na estratégia adotada.*',
                    'Chamadas e N+1 de cada funcionalidade na estratégia adotada. A evidência é calculada dos relatórios; o julgamento é da IA, sem tempos nem volumes.')],
        'diagramas': [(r'Funcionalidade → Group Query ou Agregado.*', 'Funcionalidade → agregado ou Group Query → comando SQL ou programa corporativo, só com ligações diretas. Comando verde-água lê, roxo grava; LEGACY = chamada ao programa corporativo original.'),
                      (r'Cursor → chamada a cada linha.*', 'Chamadas repetidas a cada linha de um cursor (N+1): vermelho sem mitigação, laranja mitigado pelo fluxo, verde sem chamada por linha, cinza sem análise.')],
    },
    '18': {
        'objetivo': 'Agrupar as funcionalidades em contextos de domínio e de entrega e mapear como esses contextos se relacionam.',
        'destaques': [('Domain Contexts', 'contextos de domínio'), ('Delivery Contexts', 'contextos de entrega'), 'relacionamentos', 'comandos SQL mapeados'],
        'termos': [('Domain Contexts', 'contextos de domínio'), ('Delivery Contexts', 'contextos de entrega'), ('Domain Context', 'contexto de domínio'), ('Delivery Context', 'contexto de entrega')],
        'titulos': {'telas': 'Evidência das telas', 'capacidades': 'Capacidades de negócio e opção de modernização', 'ddms': 'Classificação DDMS',
                    'dominios': 'Contextos de domínio', 'entregas': 'Contextos de entrega', 'mapa': 'Mapa de contextos'},
        'textos': [(r'Telas mantidas no funil da fase 15 são as analisadas em detalhe\..*',
                    'As telas mantidas no funil (fase 15) definem a entrega mínima: entry points na mesma tela ficam no mesmo contexto de entrega. A IA junta mais entregas quando uma tela depende da outra.'),
                   (r'Cada agregado da fase 16 \(uma raiz\) é um contexto de domínio\..*',
                    'Um contexto de domínio por agregado (fase 16): as classes do agregado e os comandos SQL que ele executa (no corporativo, os programas chamados por LEGACY).'),
                   (r'Funcionalidades usadas na mesma tela, ou em telas que dependem uma da outra, formam uma só entrega.*',
                    'Funcionalidades usadas na mesma tela, ou em telas dependentes, formam uma só entrega. As Group Queries ficam sempre num contexto de entrega do tipo Query; os nomes são do negócio, sem nomes do legado.'),
                   (r'As queries de várias tabelas continuam como Legacy Query dentro de uma Group Query.*',
                    'Queries de várias tabelas ficam como Legacy Query dentro de uma Group Query, num contexto de entrega do tipo Query; os contextos de domínio corporativos trazem só o agregado e os programas corporativos (LEGACY).')],
        'textos_bloco': [(r'Calculado só dos relatórios das fases 12 .*', lambda m: [ficha('Como o mapa foi montado', [
            ['Fontes', 'Fases 12 (funcionalidades), 15 (telas), 16 (agregados) e 17 (estratégia de acesso aos dados).'],
            ['Contextos de domínio', 'Um por agregado.'],
            ['Contextos de entrega', 'Entry points em Presentation; funcionalidades corporativas e Group Queries em Query.'],
            ['Relacionamentos', 'Só os que existem diretamente nas fases de origem, sem transitividade.'],
            ['Julgamento da IA', 'Capacidades, opção de modernização, classe DDMS, agrupamento das entregas, valor de negócio, estratégia de leitura e protocolo, validados contra a evidência.']])])],
        'diagramas': [(r'Semantic Context Map.*', 'Contextos de entrega e de domínio, com os componentes de cada um e as relações diretas entre eles; seta rotulada async = assíncrona.')],
        'fundir': [{'a': r'Capacidades de negócio e opção de modernização', 'b': r'Classificação DDMS das capacidades', 'chave_a': 'Capacidade', 'chave_b': 'Capacidade',
                    'colunas': [('Classe DDMS (IA)', None), ('Por que (IA)', 'Por que a classe DDMS (IA)')]}],
        'remover': [r'Tabela do diagrama: componentes de cada contexto — .*'],
    },
    '19': {
        'objetivo': 'Definir os recursos, os protocolos e os diagramas da solução modernizada a partir dos contextos.',
        'destaques': ['recursos', 'integrações', 'casos de uso'],
        'textos': [(r'A arquitetura alvo adota os padrões arquiteturais (.*?)\. Cada padrão vem dos tipos de recurso.*',
                    r'Padrões adotados: \1. Cada um vem de tipos de recurso do modelo de recursos.'),
                   (r'Cada linha liga a regra do fluxo de negócio da fase 12 .*?(\d+) regras de negócio aparecem nos diagramas de sequência; (\d+) do fluxo não aparecem.*',
                    r'Cada regra do fluxo (fase 12) até a nota que a mostra nos diagramas de sequência e o caso de uso em que aparece; uma regra fica em um só caso de uso de cada aplicação. '
                    r'\1 regras aparecem nos diagramas de sequência e \2 ficam fora.'),
                   (r'(Comando|Programa corporativo) (\S+) a pedido de (\S+): .*', r'\1 \2 a pedido de \3.')],
        'textos_bloco': [(r'Calculada só dos relatórios das fases 03 .*', lambda m: [ficha('Como a arquitetura foi montada', [
            ['Fontes', 'Fases 03, 10, 12, 15, 16, 17 e 18.'],
            ['Evidência', 'Nenhum recurso sem evidência: sem decisão registrada, a confiança é UNCERTAIN ou UNKNOWN e o recurso vai para "Lacunas e decisões pendentes".'],
            ['Nomes', 'Nomes de programas e copybooks já usados no código são mantidos; só comando novo recebe nome pela regra.'],
            ['Fora do escopo', 'Identidade, observabilidade e segurança de plataforma.'],
            ['Modelo canônico', 'architecture-resource-model.yaml, na pasta ia da fase.']])])],
        'diagramas': [(r'Fluxo de integração com o mainframe', 'Os números das ligações são os passos da tabela do fluxo.'),
                      (r'C4 nível 1.*', 'Usuários, sistema modernizado e mainframe; os relatórios não mostram sistemas externos nem provedor de identidade.'),
                      (r'C4 nível 2.*', 'Containers do modelo de recursos e o protocolo de cada ligação; o detalhe está nos diagramas de nível 3.'),
                      (r'C4 nível 3 \(componentes\) de (\S+)', r'Componentes de \1 (endpoints, casos de uso, domínio e portas de saída), com quem o chama e o que ele chama.'),
                      (r'Casos de uso e regras de negócio de (\S+)', r'Casos de uso de \1 e as regras de negócio (caixas amarelas) que cada um aplica.'),
                      (r'Sequência de (\S+) · (.*)', r'Ordem das chamadas de \1 (\2) entre o BFMF, os serviços de dados e as filas.')],
        'legendas': [(r'C4 nível 3 \(componentes\) de tcap-(vas|srv)-.*', X('Nos serviços, cada comando SQL (ou programa corporativo) tem um MQAdapter que fala direto com as filas de baixa e de alta '
                                                                           'e com o programa mainframe que o executa; os comandos aparecem expandidos nas portas de saída. Não há Kafka: nenhum relatório o decide.', COMO_LER)),
                     (r'Casos de uso e regras de negócio de .*', X('Uma regra aparece em um só caso de uso: no BFMF, validação do pedido, decisão e composição de serviços; no serviço de dados, as regras '
                                                                  'ligadas aos comandos SQL dele (nos corporativos, aos programas corporativos). Tracejadas = regras que continuam dentro dos programas corporativos.', COMO_LER)),
                     (r'Sequência de .*', X('O BFMF conduz o fluxo de negócio: valida o pedido, chama cada serviço de dados só pelo que precisa, decide e trata o erro (notas no BFMF). '
                                            'O serviço executa só os comandos SQL do passo e cuida das invariantes deles (notas amarelas). Passos alternativos saem da mesma validação e só um executa '
                                            'por pedido. As aplicações falam com as filas pelo MQ_ADAPTER; o programa mainframe de cada comando está na seção de programas mainframe.', COMO_LER)),
                     (r'Programa mainframe .*', X('A aplicação envia o pedido à fila de baixa, que o encaminha à fila de alta; o coordenador chama o funcional (LINK), que executa o SQL no DB2 '
                                                  '(ou chama o programa corporativo original); a resposta volta pelas filas de alta e de baixa. O formato das mensagens está nos contratos.', COMO_LER))],
        'remover': [r'Tabela do diagrama: componentes de cada contexto — .*'],
    },
    '20': {
        'objetivo': 'Especificar os contratos de integração: o OpenAPI de cada aplicação e o copybook de cada fila MQ.',
        'destaques': ['contratos OpenAPI', 'operações', 'copybooks'],
        'textos': [(r'Application → MQ REQ baixa → MQ REQ alta .*',
                    'Fluxo: aplicação → fila de pedido (baixa → alta) → programa mainframe → fila de resposta (alta → baixa). Copybooks em formato fixo (colunas 8 a 72), '
                    'caixa alta, sem acentos; o campo do contrato REST correspondente está no layout.'),
                   (r'Cada contrato é conferido antes de gravar: .*',
                    'Cada contrato é conferido antes de gravar: OpenAPI 3.1, referências e nomes (camelCase, sem nomes do sistema atual fora de x-legacy); nos copybooks, '
                    'formato fixo, PIC e nomes únicos de até 30 caracteres.')],
        'textos_bloco': [(r'Calculados dos relatórios das fases 03 .*', lambda m: [ficha('Como os contratos foram montados', [
            ['Fontes', 'Fases 03 (tipos), 10 (colunas, parâmetros e linhagem), 12 (funcionalidades e regras), 17 e 18 (contextos) e 19 (recursos, filas e programas).'],
            ['Operações', 'Uma por funcionalidade de negócio em cada BFMF, VAS e Domain Microservice.'],
            ['Campos', 'Entrada = campos que a linhagem liga ao programa de entrada; saída = colunas lidas.'],
            ['Nomes', 'camelCase e descrições da IA (prompt 11), validados contra os campos calculados; os copybooks usam o nome do campo da linhagem.'],
            ['Paginação', 'Listas paginadas recebem página e tamanho e devolvem página, tamanho, total de itens e total de páginas.'],
            ['Versão', 'Caminhos sob /v1 (analise.config.json); mudança incompatível cria a versão seguinte ao lado da atual.'],
            ['Arquivos', 'ia/contracts/']])])],
    },
    '20a': {
        'objetivo': 'Mostrar como o micro frontend e o BFF foram construídos e as diretrizes que os próximos recortes seguem ao reestruturar as telas.',
        'destaques': [('aplicações de frontend (micro frontend e BFF)', 'aplicações de frontend'), ('telas (rotas com componente)', 'telas'), 'componentes',
                      ('casos de uso do BFF (classes UseCase)', 'casos de uso do BFF'), ('diretrizes de interface registradas', 'diretrizes de interface')],
        'textos': [(r'Aplicações de frontend: aplicações de frontend do recorte: (.*)', lambda m: m.group(1)[0].upper() + m.group(1)[1:])],
        'diagramas': [(r'Da tela do legado à operação do contrato', 'Tela do legado (fase 15) → tela nova do micro frontend → componentes → serviço Angular → operação do contrato do BFF (fase 20).')],
        'grupos': [(r'remodelagem|telas', 'Telas', None), (r'ux-.*', 'Diretrizes de interface (UX)', None), (r'pf-.*', 'Padrões do BFF (PF)', None)],
    },
    '20b': {
        'objetivo': 'Mostrar como os serviços, as filas, os programas mainframe e o banco foram construídos e os padrões que as próximas implementações seguem.',
        'destaques': [('aplicações da arquitetura alvo implementadas', 'aplicações'), ('casos de uso (classes UseCase)', 'casos de uso'),
                      ('pares de programas mainframe (coordenador + funcional)', 'pares de programas mainframe'), ('tabelas do banco usadas pelos programas', 'tabelas do banco'),
                      ('padrões conformes no repositório', 'padrões conformes')],
        'grupos': [(r'pi-.*', 'Padrões e convenções (PI)', None)],
    },
    '21': {
        'objetivo': 'Provar, cenário a cenário, que cada regra de negócio está implementada e se comporta como no legado.',
        'destaques': ['regras de negócio', 'cenários de teste', 'cenários em falha', 'regras divergentes'],
        'textos': [(r'tcap-modernizacao: ambiente de teste (\S+) .*Resultados coletados em (\S+)\.',
                    r'Ambiente de teste \1 (teste.env), separado do de desenvolvimento e recriado a cada rodada: DB2 com a carga ACT, IBM MQ distribuído e do mainframe, '
                    r'região CICS com os programas, os SRVs, o BFF e a fundação. A suíte ponta a ponta cria e remove a própria massa. Resultados de \2.'),
                   (r'Cada linha do rastreio por regra vai da regra de negócio .*',
                    'Cada linha vai da regra de negócio (fase 11) às decisões de origem (13), ao caso de uso (19), aos endpoints (20), ao código e aos cenários de teste com o resultado. '
                    'A regra está garantida quando o código foi localizado e todos os cenários que a citam passaram; linha destacada = teste em falha ou ausente, ou comportamento divergente.'),
                   (r'Cada pedido que o serviço pôs na fila .*',
                    'Cada pedido posto na fila (log do adaptador MQ) é casado pelo id da mensagem com a tarefa da região CICS que o leu. O teste falha quando o pedido não foi atendido '
                    'pelo coordenador, sem o funcional ou sem SYNCPOINT; com a transação desabilitada, o correto é nenhuma tarefa ler o pedido.')],
        'fundir': [{'a': r'Cenários de teste: entrada, esperado, obtido e resultado', 'b': r'Evidências de cada cenário', 'chave_a': 'Cenário', 'chave_b': 'Cenário',
                    'colunas': [('Página de evidências', 'Evidências'), ('Tipos', 'Tipos de evidência')], 'titulo': 'Cenários de teste: entrada, esperado, obtido, resultado e evidências',
                    'nota': 'Entrada e obtido longos aparecem resumidos («…» expande). Tempo: duração da chamada HTTP, da consulta ao banco ou da leitura do log (ponta a ponta) e do método '
                            'de teste (unitário). Evidências: abre sobre o relatório, numa janela, a página do cenário com requisição e resposta HTTP, logs de cada container com o traceId, programas executados na região CICS '
                            'e consultas ao DB2 (ponta a ponta), ou o código do teste e o resultado do JUnit (unitário).'},
                   {'a': r'Programas mainframe por coordenador', 'b': r'Transações da região CICS e cenários que as exercitaram', 'chave_a': 'Coordenador', 'chave_b': 'Programa coordenador',
                    'colunas': [('Situação', 'Situação da transação')],
                    'nota': 'Somado sobre os pedidos ao mainframe dos cenários ponta a ponta. Programas chamados: funcional e corporativos que a tarefa do coordenador executou (LINK). '
                            'Situação da transação (definida no arquivo de recursos CICS do repositório): exercitada, só indisponibilidade ou sem cenário.'}],
    },
    '22': {
        'objetivo': 'Registrar as decisões tomadas sobre a arquitetura alvo, com contexto, alternativas, consequências e evidências.',
        'destaques': ['decisões', 'repositórios do DDA', 'aplicações encaixadas', 'endpoints em /ni/v1'],
        'textos': [(r'Cada ADR traz a ficha, o contexto, a decisão, as alternativas descartadas e as consequências.*',
                    'Cada ADR traz a ficha, o contexto, a decisão, as alternativas e as consequências, com as evidências das fases 10 a 21 e do repositório. '
                    'ADRs que mudam nomes têm diagrama de-para e a tabela completa; o nome desta fase prevalece sobre o das fases 19, 20 e 21.')],
        'textos_bloco': [(r'As decisões vêm do registro do dono da arquitetura .*', lambda m: [ficha('Como as decisões foram registradas', [
            ['Origem', 'Registro do dono da arquitetura (interpretacao-adr/adr.json), não IA.'],
            ['Cálculo', 'Comandos SQL, programas corporativos, filas e copybooks (fase 19); tabelas DB2 (fase 10); operações (fase 20); filas, endpoints, clientes Feign e âncoras do repositório.'],
            ['Recusa', 'Fila nova fora do gerenciador local ou sem uso no repositório dono; fila ou nome anterior ainda presente; endpoint ou cliente Feign sem o prefixo; '
                       'operação do contrato sem endpoint; âncora inexistente.']])])],
        'grupos': [(r'adr-.*', 'ADRs', None)],
    },
    '23': {
        'objetivo': 'Registrar as propostas de melhoria do processo de análise e de modernização levantadas no recorte.',
        'destaques': ['propostas', 'exemplos', 'fases afetadas'],
        'textos': [(r'Propostas de melhoria do processo de análise e de modernização levantadas no recorte, no formato das enhancement proposals.*',
                    'Cada proposta segue o formato das enhancement proposals: motivação, objetivos, proposta, exemplos com antes e depois, fases afetadas e riscos. '
                    'Aceita e aplicada à arquitetura alvo, a decisão vai para as Decisões Arquiteturais. Status: Proposta, Aceita, Implementada ou Recusada.')],
        'textos_bloco': [(r'As propostas vêm do registro do dono da arquitetura .*', lambda m: [ficha('Como as propostas foram registradas', [
            ['Origem', 'Registro do dono da arquitetura (interpretacao-ep/ep.json), não IA.'],
            ['Escopo', 'Mudanças no processo: como os recortes são feitos, o que as fases analisam e o que o analisador verifica.'],
            ['Conferência', 'Os exemplos citam linhas dos fontes, conferidas a cada geração; âncora inexistente, ADR fora do registro ou status inválido recusam o relatório.']])])],
        'grupos': [(r'ep-.*', 'EPs', None)],
    },
}

# links quebrados que têm destino conhecido em outra fase (a tabela dinâmica não está no esquema de dados: a referência completa é a consulta dinâmica)
LINKS = {('03-data-schema', 'tabela-TTPO_CANAL'): ('10 - sql-mapping', 'D01')}


# ----------------------------------------------------------------------------- passos
def _blocos(m):
    for s in m['sections']:
        for i, b in enumerate(s['blocks']):
            yield s, i, b


def _trocar_termos(m, termos):
    def tr(x):
        for a, b in termos:
            x = x.replace(a, b)
        return x
    for s in m['sections']:
        s['title'] = tr(s['title'])
        if isinstance(s.get('text'), str):
            s['text'] = tr(s['text'])
        for b in s['blocks']:
            if b.get('title'):
                b['title'] = tr(b['title'])
            if b['type'] == 'text' and isinstance(b.get('text'), str) and not b.get('pre') and not b.get('sql'):
                b['text'] = tr(b['text'])
            if isinstance(b.get('note'), str):
                b['note'] = tr(b['note'])


def _reescrever(texto, regras):
    if not isinstance(texto, str):
        return texto
    for pad, novo in regras:
        mt = re.fullmatch(pad, texto, re.S)
        if mt:
            return novo(mt) if callable(novo) else mt.expand(novo)
    return texto


def _textos(m, cfg):
    regras, em_bloco = cfg.get('textos') or [], cfg.get('textos_bloco') or []
    for s in m['sections']:
        s['text'] = _reescrever(s.get('text'), regras)
        novos = []
        for b in s['blocks']:
            if b['type'] == 'text' and isinstance(b.get('text'), str) and not b.get('pre') and not b.get('sql'):
                if not b.get('title') and b['text'].startswith('Como ler: '):   # "Como ler: …" vira o aviso em destaque
                    b['title'], b['text'] = COMO_LER, b['text'][len('Como ler: '):][:1].upper() + b['text'][len('Como ler: ') + 1:]
                troca = next(((pad, f) for pad, f in em_bloco if re.fullmatch(pad, b['text'], re.S)), None)
                if troca:
                    novos.extend(troca[1](re.fullmatch(troca[0], b['text'], re.S)))
                    continue
                b['text'] = _reescrever(b['text'], regras)
                novos.extend(_lista_numerada(b))
                continue
            if isinstance(b.get('note'), str):
                b['note'] = _reescrever(b['note'], regras)
            novos.append(b)
        s['blocks'] = novos


def _lista_numerada(b):
    """Texto longo com itens (1) … (2) … vira o texto de abertura e uma tabela com os itens."""
    t = b['text']
    if len(t) < 400 or not re.search(r'\(1\) .*\(2\) ', t, re.S):
        return [b]
    ini = t.index('(1) ')
    cab, corpo = t[:ini].rstrip(), t[ini:]
    partes = re.split(r'(?:;\s*(?:e\s+)?)?\((\d+)\)\s+', corpo)
    itens = [(partes[i], partes[i + 1].strip().rstrip(';')) for i in range(1, len(partes) - 1, 2)]
    ultimo = itens[-1][1]
    resto = ''
    fim = re.search(r'\.\s+(?=[A-ZÁÉÍÓÚ])', ultimo)
    if fim:
        itens[-1] = (itens[-1][0], ultimo[:fim.start()])
        resto = ultimo[fim.end():].strip()
    frase = cab.split('. ')[-1].rstrip(':').strip()
    abertura = cab[:len(cab) - len(cab.split('. ')[-1])].strip()
    out = [dict(b, text=abertura + (' ' + resto if resto else ''))] if (abertura or resto) else []
    out.append(tabela(frase[:1].upper() + frase[1:], ['#', 'Item'], [[n, it[:1].upper() + it[1:]] for n, it in itens]))
    return out


def _casa(pad, s, b):
    if isinstance(pad, tuple):
        return s['id'] == pad[0] and re.fullmatch(pad[1], b.get('title') or '', re.S)
    return re.fullmatch(pad, b.get('title') or '', re.S)


def _so_ligacoes(b):
    """Tabela que só repete as setas do diagrama (De, Ligação, Para): o diagrama já mostra o mesmo."""
    return (b['type'] == 'table' and (b.get('title') or '').startswith('Tabela do diagrama')
            and (b['columns'] in (['De', 'Ligação', 'Para'], ['De', 'Para'], ['De', 'Para', 'Coluna em comum']) or not b['rows']))


def _remover(m, cfg):
    pads = cfg.get('remover') or []
    for s in m['sections']:
        fica = [b for b in s['blocks'] if not _so_ligacoes(b) and not any(_casa(p, s, b) for p in pads)]
        if any(b['type'] == 'graph' and b.get('sem_tabela') for b in fica) and not any(b['type'] == 'table' for b in fica):
            fica = [b for b in s['blocks'] if not any(_casa(p, s, b) for p in pads)]   # a tabela do diagrama sem tabela automática fica
        s['blocks'] = fica


def _fundir(m, cfg):
    for f in cfg.get('fundir') or []:
        achar = lambda pad: next(((s, b) for s, _i, b in _blocos(m) if b['type'] == 'table' and re.fullmatch(pad, b.get('title') or '')), (None, None))
        sa, a = achar(f['a'])
        sb, b = achar(f['b'])
        if not a or not b or a is b or f['chave_a'] not in a['columns'] or f['chave_b'] not in b['columns']:
            continue
        ka, kb = a['columns'].index(f['chave_a']), b['columns'].index(f['chave_b'])
        linhas = {}
        for r in b['rows']:
            linhas.setdefault(_t(r[kb]).strip(), r)
        if not all(_t(r[ka]).strip() in linhas for r in a['rows']) or len(linhas) > len(a['rows']):
            continue   # sem correspondência de uma para uma: as duas tabelas ficam
        cols = f.get('colunas') or [(c, None) for c in b['columns'] if c != f['chave_b']]
        for origem, destino in cols:
            if origem not in b['columns']:
                continue
            ib = b['columns'].index(origem)
            nome = destino or origem
            if nome in a['columns']:
                ia = a['columns'].index(nome)
                for r in a['rows']:
                    r[ia] = linhas[_t(r[ka]).strip()][ib]
            else:
                a['columns'].append(nome)
                for r in a['rows']:
                    r.append(linhas[_t(r[ka]).strip()][ib])
        if f.get('titulo'):
            a['title'] = f['titulo']
        if f.get('nota'):
            a['note'] = f['nota']
        sb['blocks'] = [x for x in sb['blocks'] if x is not b]


def _resumir(v, limite=320):
    """Valor longo de ficha: a primeira frase, com «…» para abrir o texto completo."""
    if not isinstance(v, str) or len(v) <= limite:
        return v
    fim = re.search(r'(?<=[a-z0-9)\]"\'])\. (?=[A-ZÁÉÍÓÚ"(])', v[60:])
    return {'text': v[:60 + fim.start() + 1] if fim else v[:limite].rsplit(' ', 1)[0] + '…', 'detalhe': v}


def _fichas_item(m, pad):
    """Seção de um item (regra, query, funcionalidade): os textos soltos (descrição, "Rótulo: valor", "a: b · c: d"), o retorno e as lacunas
    numa ficha só, no lugar do primeiro deles."""
    for s in m['sections']:
        if not re.fullmatch(pad, s['id']) or any((b.get('title') or '').endswith('· ficha') for b in s['blocks']):
            continue
        pares, novos, pos = [], [], None
        for b in s['blocks']:
            ttl, txt = b.get('title') or '', b.get('text')
            solto = b['type'] == 'text' and not ttl and isinstance(txt, str) and not b.get('pre') and not b.get('sql')
            rotulo = re.match(r'([A-ZÁÉÍÓÚ][\wçãõáéíóúâê ]{1,40}): (.+)', txt, re.S) if solto else None
            if solto and ' · ' in txt and all(': ' in p for p in txt.split(' · ') if not re.fullmatch(r'\d+ regras determinísticas', p.strip())):
                for parte in txt.split(' · '):
                    k, _, v = parte.partition(': ')
                    n = re.fullmatch(r'(\d+) regras determinísticas', parte.strip())
                    pares.append(['Regras determinísticas', n.group(1)] if n else [k[:1].upper() + k[1:], v])
            elif rotulo and len(rotulo.group(1).split()) <= 5:
                pares.append([rotulo.group(1), _resumir(rotulo.group(2))])
            elif solto:
                pares.append(['Descrição' if any(k == 'O que faz' for k, _v in pares) else 'O que faz', _resumir(txt)])
            elif b['type'] == 'table' and ttl.endswith('COD-RETORNO, COD-ERRO e COD-MENSAGEM'):
                vals = [' · '.join(f'{c} {_t(v)}' for c, v in zip(b['columns'][1:], r[1:])) for r in b['rows']]
                if len(set(vals)) <= 1:
                    pares.append(['Retorno', vals[0] if vals else '—'])
                else:
                    pares.append(['Retorno', {'text': '; '.join(f'{_t(r[0])}: {v}' for r, v in zip(b['rows'], vals)),
                                              'parts': [p for k, (r, v) in enumerate(zip(b['rows'], vals)) for p in ((['; '] if k else []) + (r[0].get('parts') if isinstance(r[0], dict) and r[0].get('parts') else [_t(r[0])]) + [f': {v}'])]}])
            elif b['type'] == 'text' and ttl.endswith(': lacunas'):
                pares.append(['Lacunas', txt if not isinstance(txt, str) else _resumir('; '.join(x.strip() for x in txt.split(' | ')))])
            else:
                novos.append(b)
                continue
            if pos is None:
                pos = len(novos)
        if pares:
            novos.insert(pos, ficha(f'{s["id"]} · ficha', pares))
            s['blocks'] = novos


def _diagramas(m, cfg):
    descr = cfg.get('diagramas') or []
    for s in m['sections']:
        for b in s['blocks']:
            if b['type'] != 'graph':
                continue
            for pad, novo in descr:
                mt = re.fullmatch(pad, b.get('title') or '', re.S)
                if mt:
                    b['note'] = mt.expand(novo)
                    break
    for pad, bloco in cfg.get('legendas') or []:
        presente = any(x.get('title') == bloco.get('title') and x.get('text') == bloco.get('text') and x.get('rows') == bloco.get('rows') for _s, _i, x in _blocos(m))
        if presente:
            continue
        for s in m['sections']:
            i = next((k for k, b in enumerate(s['blocks']) if b['type'] == 'graph' and re.fullmatch(pad, b.get('title') or '', re.S)), None)
            if i is not None:
                s['blocks'].insert(i, dict(bloco, rows=[list(r) for r in bloco['rows']]) if bloco['type'] == 'table' else dict(bloco))
                break


def _inicio(m, cfg):
    for sid, blocos in (cfg.get('inicio') or {}).items():
        s = next((x for x in m['sections'] if x['id'] == sid), None)
        if s and not any(b.get('title') == blocos[0].get('title') for b in s['blocks']):
            s['blocks'][0:0] = [dict(b, rows=[list(r) for r in b['rows']]) if b['type'] == 'table' else dict(b) for b in blocos]


def _notas_repetidas(m):
    """A mesma nota em três ou mais tabelas da página fica só na primeira."""
    vistas = {}
    for _s, _i, b in _blocos(m):
        if isinstance(b.get('note'), str) and b['note']:
            vistas[b['note']] = vistas.get(b['note'], 0) + 1
    primeira = set()
    for _s, _i, b in _blocos(m):
        n = b.get('note')
        if isinstance(n, str) and vistas.get(n, 0) >= 3 and b['type'] == 'table':
            if n in primeira:
                b['note'] = None
            else:
                primeira.add(n)


def _fichas_linha(m):
    """Tabela larga de uma linha só (sem âncora de linha) vira ficha: um campo por coluna."""
    for s in m['sections']:
        for i, b in enumerate(s['blocks']):
            if (b['type'] == 'table' and len(b['rows']) == 1 and len(b['columns']) >= 5 and not any(b.get('row_ids') or [])
                    and not any(b.get('row_marks') or []) and b['columns'] != ['Campo', 'Conteúdo']
                    and not (b.get('title') or '').endswith('chamadas e comandos SQL')   # fase 10: as chamadas e comandos de cada programa ficam sempre em tabela
                    and not (b.get('title') or '').startswith('Tabelas dinâmicas descobertas')):   # fase 16: pode haver mais de uma tabela dinâmica
                s['blocks'][i] = dict(ficha(b.get('title'), [[c, v] for c, v in zip(b['columns'], b['rows'][0]) if _t(v).strip() not in ('', '—')]), note=b.get('note'))


def _lacunas(m):
    """Lacunas escritas como lista em texto ("a | b | c"): entram na ficha da seção, ou viram tabela quando são duas ou mais."""
    for s in m['sections']:
        fichas = [b for b in s['blocks'] if b['type'] == 'table' and b['columns'] == ['Campo', 'Conteúdo']]
        novos = []
        for b in s['blocks']:
            ttl = b.get('title') or ''
            if b['type'] == 'text' and isinstance(b.get('text'), str) and (ttl.endswith(': lacunas') or (not ttl and b['text'].startswith('Propósito: '))):
                if fichas:
                    if ttl:
                        fichas[0]['rows'].append(['Lacunas', '; '.join(x.strip() for x in b['text'].split(' | ') if x.strip())])
                    else:
                        fichas[0]['rows'].insert(0, ['Propósito', b['text'][len('Propósito: '):]])
                    continue
                itens = [x.strip() for x in b['text'].split(' | ') if x.strip()]
                if ttl and len(itens) >= 2:
                    novos.append(tabela(ttl, ['Lacuna'], [[x] for x in itens]))
                    continue
            novos.append(b)
        s['blocks'] = novos


def _grupos(m, cfg):
    g = cfg.get('grupos')
    if not g:
        return
    grupos = m.setdefault('grupos', {})
    if g == 'categoria':   # fase 11: o grupo é a categoria escrita no começo do texto da seção ("Validações de entrada: …")
        for s in m['sections']:
            if re.fullmatch(r'[A-Z]\d\d\.\S+', s['id']) and isinstance(s.get('text'), str) and ': ' in s['text']:
                nome, _, desc = s['text'].partition(': ')
                s['grupo'], s['text'] = nome, None
                grupos.setdefault(nome, desc)
        return
    for s in m['sections']:
        for pad, titulo, desc in g:
            mt = re.fullmatch(pad, s['id'])
            if mt:
                s['grupo'] = mt.expand(titulo)
                if desc and s['grupo'] not in grupos:
                    grupos[s['grupo']] = desc
                grupos.setdefault(s['grupo'], None)
                break


def _destaques(m, cfg):
    rot = cfg.get('destaques')
    if not rot:
        return
    resumo = {c['label']: c['value'] for c in m.get('summary') or []}
    m['destaques'] = [{'label': r[1] if isinstance(r, tuple) else r, 'value': resumo[r[0] if isinstance(r, tuple) else r]}
                      for r in rot if (r[0] if isinstance(r, tuple) else r) in resumo]


def curar(m):
    """Aplica a curadoria da fase ao modelo (no lugar) e o devolve."""
    cfg = FASES.get(fase(m))
    if not cfg:
        return m
    if cfg.get('termos'):
        _trocar_termos(m, cfg['termos'])
    _textos(m, cfg)
    _remover(m, cfg)
    _fundir(m, cfg)
    if cfg.get('fichas'):
        _fichas_item(m, cfg['fichas'])
    _inicio(m, cfg)
    _diagramas(m, cfg)
    _notas_repetidas(m)
    _fichas_linha(m)
    _lacunas(m)
    _grupos(m, cfg)
    for sid, t in (cfg.get('titulos') or {}).items():
        for s in m['sections']:
            if s['id'] == sid:
                s['title'] = t
    m['sections'] = [s for s in m['sections'] if s['blocks'] or s.get('text')]
    if cfg.get('objetivo'):
        m['objetivo'] = cfg['objetivo']
    _destaques(m, cfg)
    return m


def ancoras(m):
    """Ids de seção e de linha do relatório (os destinos possíveis de um link)."""
    a = set()
    for s in m['sections']:
        a.add(s['id'])
        for b in s['blocks']:
            a.update(x for x in b.get('row_ids') or [] if x)
    return a


def corrigir_links(m, ancoras_por_fase):
    """Links para âncoras que não existem: o destino conhecido (LINKS) ou, para uma tabela sem âncora no esquema de dados, a linhagem da tabela."""
    def fix(o):
        if isinstance(o, dict):
            if 'phase' in o and 'text' in o and o['phase'] in ancoras_por_fase and o.get('anchor') and o['anchor'] not in ancoras_por_fase[o['phase']]:
                destino = LINKS.get((o['phase'], o['anchor']))
                if not destino and o['phase'] == '03-data-schema' and o['anchor'].startswith('tabela-'):
                    alvo = 'tab-' + o['anchor'][len('tabela-'):]
                    destino = ('04-data-lineage', alvo) if alvo in ancoras_por_fase.get('04-data-lineage', ()) else None
                if destino:
                    o['phase'], o['anchor'] = destino
            for v in o.values():
                fix(v)
        elif isinstance(o, list):
            for v in o:
                fix(v)
    fix(m['sections'])
