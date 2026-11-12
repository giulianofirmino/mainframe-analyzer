"""SQL do runtime: indicador de NULL no INTO, agregação (MAX(x)+1), parênteses do WHERE e tokens de trechos longos."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'semantic_core'))

from db2_functional_sql import execute_select, predicate
from token_utils import tokens_of, sql_host_pairs

# 1) variável indicadora: :HOST :IND e :HOST:IND, lidas pelos tokens (o trecho passa da coluna 72)
long_sql = ("SELECT AAAAAAAAAAAAAAAAAAAA , BBBBBBBBBBBBBBBBBBBB , CCCCCCCCCCCCCCCCCCCC INTO :T.X :N , :Y:I2 , :Z "
            "FROM T WHERE A = 'X   Y' AND QQQQQQQQQQQQQQ = 1")
toks = tokens_of(long_sql)
assert [t[1] for t in toks][-3:] == ['QQQQQQQQQQQQQQ', '=', '1'], 'trecho longo perdeu tokens'
assert sql_host_pairs(toks) == [('T.X', 'N'), ('Y', 'I2'), ('Z', None)], sql_host_pairs(toks)
assert sql_host_pairs(tokens_of('FETCH C INTO :T.X :N ,:Y')) == [('T.X', 'N'), ('Y', None)]
assert sql_host_pairs(tokens_of('INSERT INTO T (A) VALUES (:A :NA)')) == []

# 2) MAX(coluna) + 1: com linhas soma 1; sem linhas dá NULL e SQLCODE -305 (sem indicador) ou 0 (com indicador)
T = {'DB2PRD.TLC': [{'P': 10, 'C': 503, 'N': 1}, {'P': 10, 'C': 503, 'N': 4}]}
sql = "EXEC SQL SELECT MAX(N) + 1 INTO :S.N FROM DB2PRD.TLC WHERE P = :S.P AND C = :S.C END-EXEC"
r = execute_select(sql, T, {'P': 10, 'C': 503})
assert r['into'] == {'S.N': 5} and r['sqlcode'] == 0, r['into']
r = execute_select(sql, T, {'P': 99, 'C': 503})
assert r['into'] == {'S.N': None} and r['sqlcode'] == -305
r = execute_select(sql.replace(':S.N ', ':S.N :IND '), T, {'P': 99, 'C': 503})
assert r['sqlcode'] == 0
r = execute_select("EXEC SQL SELECT COUNT(*) INTO :S.N FROM DB2PRD.TLC WHERE P = :S.P END-EXEC", T, {'P': 10})
assert r['into'] == {'S.N': 2}
r = execute_select("EXEC SQL SELECT COUNT(*) INTO :S.N FROM DB2PRD.TLC WHERE P = :S.P END-EXEC", T, {'P': 77})
assert r['into'] == {'S.N': 0} and r['sqlcode'] == 0

# 3) WHERE com grupos entre parênteses lado a lado: '(a) OR (b)' não pode perder o parêntese de fora
row = {'INI': 1000, 'FIM': 1999}
ctx = {'W1': 1500, 'W2': 2500}
w = "(((INI <= :W1 AND FIM >= :W1) OR (INI <= :W2 AND FIM >= :W2)) OR ((INI >= :W1 AND FIM <= :W2)))"
assert predicate(w, row, ctx) is True
assert predicate("(1=2) OR (2=2)", row, ctx) is True
assert predicate("(1=2) AND (2=2)", row, ctx) is False
assert predicate("((1=1))", row, ctx) is True
print('sql_runtime_smoke OK')
