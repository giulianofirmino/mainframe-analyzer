import sys,pathlib
R=pathlib.Path(__file__).parents[1];sys.path.insert(0,str(R/'semantic_core'))
from db2_stateful_runtime import DB2Stateful
d=DB2Stateful({},{});d.cursors['C']={'rows':[{'A':7,'B':8}],'pos':0}
r=d.execute('EXEC SQL FETCH C INTO :G.A:IND-A, :G.B END-EXEC')
assert r['into']=={'G.A':7,'G.B':8},r
print('PASS DB2 FETCH QUALIFIED')
