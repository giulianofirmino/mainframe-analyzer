import sys,pathlib
R=pathlib.Path(__file__).parents[1];sys.path.insert(0,str(R/'semantic_core'))
from business_rule_witness import synthesize
assert synthesize('SQLCODE EQUAL - 803',True,1000)['inputs']['SQLCODE']==-803
print('PASS CLEAN ROOM EXECUTABLE')
