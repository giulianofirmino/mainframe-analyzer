import copy,sys,pathlib
R=pathlib.Path(__file__).parents[1];sys.path.insert(0,str(R/'semantic_core'))
from db2_functional_sql import execute_select
tabs={'A':[{'ID':1,'X':7}],'B':[{'ID':1,'Y':8}]}
q="SELECT A.X, B.Y FROM A A INNER JOIN B B ON A.ID = B.ID WITH UR"
r=execute_select(q,tabs,{})
assert r['status']=='OK' and r['rows']==[{'X':7,'Y':8}],r
assert tabs=={'A':[{'ID':1,'X':7}],'B':[{'ID':1,'Y':8}]}
print('PASS RUNTIME ISOLATION/JOIN')
