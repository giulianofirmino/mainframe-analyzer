import sys,pathlib
sys.path.insert(0,str(pathlib.Path(__file__).parents[1]))
from runtime_state import State
import cics_runtime as c
s=State();s.vars['_CICS_TIME']='2026-09-27T10:15:30'
assert c.asktime(s)=='2026-09-27T10:15:30'
assert c.formattime(s,c.asktime(s),'%Y-%m-%d %H.%M.%S')=='2026-09-27 10.15.30'
c.assign(s,INVOKINGPROG='TCAP1QAL',APPLID='APP1');assert s.vars['INVOKINGPROG']=='TCAP1QAL'
m=c.getmain(s,16);assert m in s.vars['_CICS_MEMORY'];assert c.freemain(s,m)
assert c.writeq(s,'Q1','A')==1;assert c.readq(s,'Q1',1)=='A'
assert c.writeq(s,'Q1','B',1)==1;assert c.readq(s,'Q1',1)=='B'
assert c.deleteq(s,'Q1');assert c.readq(s,'Q1',1) is None
print('PASS CICS ASKTIME FORMATTIME ASSIGN GETMAIN FREEMAIN READQ WRITEQ DELETEQ')
