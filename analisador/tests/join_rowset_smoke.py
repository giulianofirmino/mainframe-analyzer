import sys,pathlib
R=pathlib.Path(__file__).parents[1];sys.path.insert(0,str(R/'semantic_core'))
from db2_functional_sql import execute_select
from db2_stateful_runtime import DB2Stateful
tabs={'A':[{'ID':1,'V':7}],'B':[{'ID':1,'N':'X'}]}
q='EXEC SQL SELECT A.V, IFNULL(B.N, \' \' ) FROM A A, B B WHERE A.ID = B.ID AND (A.V = 7 OR A.V = 8) WITH UR END-EXEC'
r=execute_select(q,tabs,{})
assert r['status']=='OK' and r['row_count']==1,r
# LEFT OUTER JOIN: linha sem par recebe nulos; condição do WHERE em coluna da tabela externa vale depois da junção
lt={'P':[{'N':1,'K':5},{'N':2,'K':6},{'N':3,'K':None}],'S':[{'K':5,'T':2}]}
q2='EXEC SQL SELECT P.N, S.T FROM P P LEFT OUTER JOIN S S ON S.K = P.K WHERE P.N >= :MIN ORDER BY P.N END-EXEC'
r=execute_select(q2,lt,{'MIN':1})
assert r['status']=='OK' and r['rows']==[{'N':1,'T':2},{'N':2,'T':None},{'N':3,'T':None}],r
r=execute_select('EXEC SQL SELECT P.N FROM P P LEFT JOIN S S ON S.K = P.K WHERE S.T IS NULL END-EXEC',lt,{})
assert [x['N'] for x in r['rows']]==[2,3],r
d=DB2Stateful({}, {'N':10});d.cursors['C']={'rows':[{'A':1,'B':2},{'A':3,'B':4}],'pos':0}
f=d.execute('EXEC SQL FETCH NEXT ROWSET FROM C FOR :N ROWS INTO :X, :Y END-EXEC')
assert f['into']=={'X':[1,3],'Y':[2,4]} and f['row_count']==2,f
print('PASS JOIN ROWSET')
