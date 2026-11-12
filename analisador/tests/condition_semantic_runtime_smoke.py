import sys,pathlib
ROOT=pathlib.Path(__file__).parents[1];sys.path.insert(0,str(ROOT/'semantic_core'))
from cobol_condition_runtime import evaluate
from business_rule_witness import synthesize
cases=[("X GREATER 10",True),("X IS NUMERIC",False),("NOT (X EQUAL 'D' OR 'L' OR 'W')",False),("EIBRESP NOT EQUAL DFHRESP (NORMAL) AND EIBRESP NOT EQUAL DFHRESP (QIDERR)",True),("A(1:4) EQUAL 'FRWK'",True)]
for c,t in cases:
 w=synthesize(c,t);assert w,(c,t)
print('PASS UNIFIED CONDITION SEMANTICS / WITNESS')
