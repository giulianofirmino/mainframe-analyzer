from __future__ import annotations
import json,html
from pathlib import Path

def _dump(p,obj): p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj,indent=2,default=str),encoding='utf-8')
def _html_value(v):
    if isinstance(v,(dict,list)): return '<pre>'+html.escape(json.dumps(v,indent=2,default=str))+'</pre>'
    return html.escape(str(v))
def publish(root,step,model,title):
    base=Path(root)/step; ia=base/'ia';ia.mkdir(parents=True,exist_ok=True)
    _dump(ia/'result.json',model)
    schema={'artifact_contract':'MFAA_STEP_ARTIFACT_V1','step':step,'canonical_model':'result.json','human_projection':'../human/report.html','report_model':'report.json'};_dump(ia/'schema.json',schema)
    evidence={'step':step,'evidence_policy':'All semantic claims must retain source/program/line/path identifiers when available.'};_dump(ia/'evidence.json',evidence)
    # human/report.html é gerado por tools/gerar_relatorios.py (mesmo modelo do ia/report.json)
    return {'ia':str(ia/'result.json'),'human':str(base/'human'/'report.html')}
