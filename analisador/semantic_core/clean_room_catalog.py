from __future__ import annotations
import hashlib
from decision_business_rule_audit import audit
from cobol_condition_semantics import parse,leaves
def walk(nodes):
 for n in nodes:
  yield n
  for k in ("body","then","else_body","at_end"):
   if isinstance(n.get(k),list): yield from walk(n[k])
  for w in n.get("whens",[]) or []: yield from walk(w.get("body",[]))
def build_catalog(asts):
 idx={(p,n["start_line"],n["type"]):n for p,a in asts.items() for n in walk(a.get("body",[])) if n.get("type") in ("IF","EVALUATE")}
 out=[]
 for p,a in asts.items():
  for d in audit(p,a):
   if d["classification"]=="EXCLUDED": continue
   n=idx[(p,d["line"],d["type"])]
   if d["type"]=="IF": branches=["TRUE","FALSE"]
   else:
    branches=[f"WHEN:{i+1}" for i in range(len(n.get("whens",[])))]
    if not any(w.get("condition","").strip().upper()=="OTHER" for w in n.get("whens",[])): branches.append("NO_MATCH")
   for b in branches:
    if d["type"]=="EVALUATE": sc="EVALUATE_BRANCH"
    else:
     ls=leaves(parse(d["condition"]))
     sc="NEEDS_88_LINEAGE" if any(x.get("kind")=="CONDITION_NAME" for x in ls) else "DIRECT_CONSTRAINT"
    core={"program":p,"line":d["line"],"decision_type":d["type"],"classification":d["classification"],"condition":d["condition"],"branch":b,"synthesis_class":sc}
    raw="|".join(str(core[k]) for k in ("program","line","decision_type","classification","condition","branch"))
    out.append({"target_id":"CR-"+hashlib.sha256(raw.encode()).hexdigest()[:16].upper(),**core})
 return out
