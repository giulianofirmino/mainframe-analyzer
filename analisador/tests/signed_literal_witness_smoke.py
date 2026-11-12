import sys,pathlib
R=pathlib.Path(__file__).parents[1];sys.path.insert(0,str(R/'semantic_core'))
from business_rule_witness import synthesize
w=synthesize('SQLCODE EQUAL - 803',True,1000)
assert w and w['inputs']['SQLCODE']==-803,w
print('PASS SIGNED LITERAL WITNESS')
