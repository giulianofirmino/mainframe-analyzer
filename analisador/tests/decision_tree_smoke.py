import sys,pathlib; sys.path.insert(0,str(pathlib.Path(__file__).parents[1]))
from semantic_core.decision_tree import build,business_rules_from_tree

def run():
 ast={'body':[{'type':'LABEL','name':'MAIN','start_line':1},{'type':'IF','start_line':2,'start_column':1,'condition':'A = 1','then':[{'type':'EXEC_SQL','start_line':3,'sql':'UPDATE T SET C = :X'}],'else_body':[]} ]}
 t=build('P',ast); r=business_rules_from_tree(t)
 assert len(r['business_rules'])==1
 assert r['business_rules'][0]['semantic_classification']=='BUSINESS'
 assert len(r['branch_audit'])==2
 assert r['branch_audit'][1]['semantic_classification']=='FLOW_CONTROL'
if __name__=='__main__':run();print('PASS')
