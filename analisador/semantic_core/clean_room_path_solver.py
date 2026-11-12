from __future__ import annotations
import copy,json
from business_rule_witness import synthesize
from concolic_path_solver import target_outcome
from operation_scoped_status_solver import route_status

def state_key(s):
 return json.dumps({k:s.get(k,{}) for k in ('inputs','db2_status','cics_status')},sort_keys=True,default=str,separators=(',',':'))

def apply_delta(state,result,branch,delta):
 ns=copy.deepcopy(state);kind,site=route_status(result.get('trace',[]),branch['program'],branch['line'],delta)
 if kind=='DB2' and site is not None:
  vals={k:v for k,v in delta.items() if k.upper() in ('SQLCODE','SQLWARN0')}
  if vals:ns.setdefault('db2_status',{}).setdefault(f"{branch['program']}:{site}",{}).update(vals)
 elif kind=='CICS' and site is not None:
  vals={k:v for k,v in delta.items() if k.upper() in ('EIBRESP','EIBRESP2')}
  if vals:ns.setdefault('cics_status',{}).setdefault(f"{branch['program']}:{site}",{}).update(vals)
 else:ns.setdefault('inputs',{}).update(delta)
 return ns

def candidates(result,target,limit=8):
 rows=[]
 for b in result.get('branches',[]):
  if b.get('program')!=target['program'] or not isinstance(b.get('result'),bool) or b.get('line',10**9)>target['line']:continue
  w=synthesize(b['condition'],not b['result'],max_trials=1000)
  if not w:continue
  rows.append((abs(target['line']-b['line']),b,w['inputs']))
 return sorted(rows,key=lambda x:x[0])[:limit]

def solve(runtime,target,witness,max_depth=2,width=8):
 init={'inputs':{'EIBCALEN':1,**witness['inputs']},'tables':{},'files':{}}
 beam=[init];seen={state_key(init)}
 for depth in range(max_depth+1):
  nxt=[]
  for st in beam:
   r=runtime.run(target['program'],copy.deepcopy(st));out=target_outcome(r,target)
   if r['status']=='SUCCESS' and out=='HIT':return {'status':'HIT','scenario':st,'depth':depth}
   if r['status'] not in ('SUCCESS','ERROR','UNSUPPORTED'):continue
   for _,b,d in candidates(r,target):
    ns=apply_delta(st,r,b,d);k=state_key(ns)
    if k not in seen:seen.add(k);nxt.append(ns)
  beam=nxt[:width]
  if not beam:break
 return {'status':'SEARCH_EXHAUSTED'}
