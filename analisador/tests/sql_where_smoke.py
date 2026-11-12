"""WHERE do SQL lido dos tokens: predicados, conectores, grupos, BETWEEN, IN, IS NULL, operando invertido, apelidos de tabela."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / 'semantic_core'))
from sql_where import predicates, aliases, resolve
from token_utils import tokens_of, find

sql = tokens_of("SELECT A.X FROM SCH.T1 A, SCH.T2 AS B WHERE A.X = B.Y AND :H = B.Z AND (A.K <= :P OR A.K >= 5) "
                "AND A.D BETWEEN 1 AND 2 AND B.N IS NOT NULL AND A.C IN (5, 6) ORDER BY A.X")
al = aliases(sql)
assert al['A'] == 'SCH.T1' and al['B'] == 'SCH.T2', al
w = predicates(sql[find(sql, ('WHERE',)) + 1:])
assert [x['connector'] for x in w] == [None, 'AND', 'AND', 'OR', 'AND', 'AND', 'AND'], [x['connector'] for x in w]
assert w[0]['value_kind'] == 'coluna' and w[0]['qualifier'] == 'A' and w[0]['field'] == 'X'
assert w[1]['hosts'] == ['H'] and w[1]['field'] == 'Z' and w[1]['op'] == '=', w[1]
assert w[2]['group'] == 'G1' and w[3]['group'] == 'G1' and w[0]['group'] == ''
assert w[4]['op'] == 'BETWEEN' and w[4]['value'] == '1 AND 2', w[4]
assert w[5]['op'] == 'IS NOT NULL' and w[6]['op'] == 'IN' and w[6]['value'] == '(5, 6)'
assert resolve(w[1], al) == 'SCH.T2' and resolve(w[0], al) == 'SCH.T1'
one = aliases(tokens_of("SELECT X FROM SCH.T1 WHERE X = 1"))
assert resolve({'qualifier': ''}, one) == 'SCH.T1'
from sql_where import resolve_value, role
# junção: apelido resolvido no valor; filtro por campo/valor fixo; coluna da mesma tabela
v, tabs = resolve_value(w[0]['value'], al, 'SCH.T1')
assert v == 'T2.Y' and tabs == ['SCH.T2'], (v, tabs)
assert role(w[0], 'SCH.T1', tabs) == 'ligação entre tabelas'
assert role(w[1], 'SCH.T2', []) == 'filtro por campo do programa' and role(w[3], 'SCH.T1', []) == 'filtro por valor fixo'
mesma = predicates(tokens_of('A.X = A.Y'))[0]
assert role(mesma, 'SCH.T1', ['SCH.T1']) == 'comparação entre colunas da mesma tabela'
print('sql_where smoke OK')
