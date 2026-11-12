from __future__ import annotations
from business_rule_witness import synthesize

def merge_inputs(a,b):
 out=dict(a)
 for k,v in b.items():
  if k in out and out[k]!=v:return None
  out[k]=v
 return out

def desired(target):
 b=target["branch"]
 return True if b=="TRUE" else False if b=="FALSE" else b

def target_outcome(result,target):
 bs=[b for b in result.get("branches",[]) if b.get("program")==target["program"] and b.get("line")==target["line"]]
 if not bs:return "NOT_REACHED"
 d=desired(target)
 return "HIT" if any(b.get("result")==d or b.get("branch")==d for b in bs) else "REACHED_OTHER"

def flip_candidates(result,target,limit=15):
 out=[]
 for b in result.get("branches",[]):
  if b.get("program")!=target["program"] or not isinstance(b.get("result"),bool):continue
  w=synthesize(b["condition"],not b["result"])
  if w:out.append({"line":b["line"],"condition":b["condition"],"branch":not b["result"],"inputs":w["inputs"]})
 return out[-limit:]

def solve_one_flip(runtime,target,base_inputs):
 base=runtime.run(target["program"],{"inputs":dict(base_inputs),"tables":{},"files":{}})
 if target_outcome(base,target)=="HIT":return {"status":"HIT","inputs":dict(base_inputs),"depth":0}
 for c in reversed(flip_candidates(base,target)):
  inp=merge_inputs(base_inputs,c["inputs"])
  if inp is None:continue
  rr=runtime.run(target["program"],{"inputs":inp,"tables":{},"files":{}})
  if target_outcome(rr,target)=="HIT":
   return {"status":"HIT","inputs":inp,"depth":1,"flip":c}
 return {"status":"NOT_SOLVED"}
