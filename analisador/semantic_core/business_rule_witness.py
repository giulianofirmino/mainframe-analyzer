import re,itertools
from cobol_condition_runtime import evaluate

def normref(x):
 x=' '.join(str(x).split());x=re.sub(r'\s*([():])\s*',r'\1',x);return x

def refs(condition):
 # LHS references of comparisons/classes; sufficient for DIRECT_CONSTRAINT synthesis.
 c=' '.join(condition.split())
 found=[]
 pat=r'([A-Z][A-Z0-9-]*(?:\s+(?:OF|IN)\s+[A-Z][A-Z0-9-]*)?(?:\s*\([^)]*\))?)\s+(?=(?:IS\s+)?(?:NOT\s+)?(?:EQUAL|GREATER|LESS|NUMERIC)|[<>=])'
 for m in re.finditer(pat,c,re.I):
  q=normref(m.group(1));
  if q.upper() in ('IS','NOT'):continue
  if q not in found:found.append(q)
 return found

def literals(condition):
 out=[0,1,-1,'',' ','X','N','Y']
 for q in re.findall(r"'([^']*)'|\"([^\"]*)\"",condition):out.append(q[0] or q[1])
 for q in re.findall(r'(?<![A-Z0-9-])(?:-\s*)?\d+(?![A-Z0-9-])',condition,re.I):out.append(int(re.sub(r'\s+','',q)))
 return list(dict.fromkeys(out))

def _base_assignment(ref,v):
 r=normref(ref);m=re.match(r'^([A-Z0-9-]+)\(([^)]*)\)$',r,re.I)
 if not m:return {r:v}
 base,inside=m.groups()
 if ':' in inside:
  a,b=inside.split(':',1);st=int(a) if a.isdigit() else 1;ln=int(b) if b.isdigit() else max(len(str(v)),1)
  return {base:' '*(st-1)+str(v)[:ln].ljust(ln)}
 idx=int(inside) if inside.isdigit() else 1
 arr=[0]*idx;arr[idx-1]=v;return {base:arr}

def synthesize(condition,truth,max_trials=10000):
 rs=refs(condition);vals=literals(condition)
 # Include values around numeric literals.
 for v in list(vals):
  if isinstance(v,int):vals.extend([v-1,v+1])
 vals=list(dict.fromkeys(vals))
 if not rs:return None
 trials=0
 for combo in itertools.product(vals,repeat=len(rs)):
  d={}
  for r,v in zip(rs,combo):d.update(_base_assignment(r,v))
  def resolve(q):
   q=normref(q);m=re.match(r'^([A-Z0-9-]+)\(([^)]*)\)$',q,re.I)
   if m:
    base,inside=m.groups();z=d.get(base,0)
    if ':' in inside:
     a,b=inside.split(':',1);st=int(a) if a.isdigit() else 1;ln=int(b) if b.isdigit() else 0;return str(z)[st-1:st-1+ln]
    idx=int(inside) if inside.isdigit() else 1;return z[idx-1] if isinstance(z,list) and 1<=idx<=len(z) else 0
   return d.get(q,0)
  try:r=evaluate(condition,resolve)
  except Exception:r=None
  trials+=1
  if r is truth:return {'inputs':d,'trials':trials}
  if trials>=max_trials:break
 return None
