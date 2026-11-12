from __future__ import annotations
def producer_before(trace, program, target_line, event):
 candidates=[e for e in trace if e.get("event")==event and e.get("program")==program and isinstance(e.get("line"),int) and e["line"]<target_line]
 return max(candidates,key=lambda e:e["line"]) if candidates else None
def route_status(trace,program,target_line,delta):
 keys={k.upper() for k in delta}
 if keys & {"EIBRESP","EIBRESP2"}:
  e=producer_before(trace,program,target_line,"CICS_EXECUTE")
  return ("CICS",e["line"]) if e else (None,None)
 if keys & {"SQLCODE","SQLWARN0"}:
  e=producer_before(trace,program,target_line,"SQL_EXECUTE")
  return ("DB2",e["line"]) if e else (None,None)
 return ("INPUT",None)
