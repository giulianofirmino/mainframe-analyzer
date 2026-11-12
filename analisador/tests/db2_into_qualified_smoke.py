import sys,pathlib
R=pathlib.Path(__file__).parents[1];sys.path.insert(0,str(R/'semantic_core'))
from db2_functional_sql import parse_select
from cobol_ast_runtime import field_ref
q=parse_select('EXEC SQL SELECT X INTO:A.X:IND FROM T WHERE K=:A.K END-EXEC')
assert q.columns==['X'] and q.into==['A.X']
assert field_ref('X OF A',None)[0]=='A.X'
print('PASS DB2 INTO QUALIFIED')
