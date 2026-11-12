import sys,pathlib
R=pathlib.Path(__file__).parents[1];sys.path.insert(0,str(R/'semantic_core'))
from operation_scoped_status_solver import producer_before,route_status
tr=[{'event':'CICS_EXECUTE','program':'P','line':10},{'event':'CICS_EXECUTE','program':'P','line':30},{'event':'CICS_EXECUTE','program':'P','line':90}]
assert producer_before(tr,'P',50,'CICS_EXECUTE')['line']==30
assert route_status(tr,'P',50,{'EIBRESP':1})==('CICS',30)
print('PASS OPERATION SCOPED STATUS')
