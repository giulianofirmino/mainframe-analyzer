import re,copy
from db2_functional_sql import execute_select,norm
def hv(x,c):
 x=x.strip().rstrip(',.')
 # host variable com variável indicadora (:CAMPO :IND ou :CAMPO:IND): indicador negativo = NULL
 mi=re.match(r'^(:\s*[\w.-]+)\s*:\s*([\w.-]+)$',x)
 if mi:
  ind=c.get(norm(mi.group(2)))
  try:
   if ind is not None and float(ind)<0:return None
  except (TypeError,ValueError):pass
  x=mi.group(1).replace(' ','')
 if x.startswith(':'):
  k=norm(x[1:])
  if k in c or '.' not in k:return c.get(k)
  tail=k.split('.')[-1]
  alt=[q for q in c if q==tail or (isinstance(q,str) and q.endswith('.'+tail))]
  return c.get(alt[0]) if len(alt)==1 else c.get(tail)
 if len(x)>1 and x[0] in "'\"" and x[-1]==x[0]:return x[1:-1]
 if re.fullmatch(r'[+-]?\d+(?:\.\d+)?',x):return float(x) if '.' in x else int(x)
 return None if x.upper()=='NULL' else c.get(norm(x),x)
def key(n,t):
 n=n.upper()
 if n in t:return n
 m=[k for k in t if k.split('.')[-1]==n.split('.')[-1]]
 return m[0] if len(m)==1 else n
def ok(w,r,c):
 if not w:return True
 a=re.split(r'\s+AND\s+',w,flags=re.I)
 if len(a)>1:return all(ok(x,r,c) for x in a)
 m=re.match(r'(.+?)\s*(<>|!=|>=|<=|=|>|<)\s*(.+)$',w.strip())
 if not m:return False
 x=r.get(norm(m.group(1).split('.')[-1]));y=hv(m.group(3),c);o=m.group(2)
 try:return {'=':x==y,'<>':x!=y,'!=':x!=y,'>':x>y,'<':x<y,'>=':x>=y,'<=':x<=y}[o]
 except:return False
class DB2Stateful:
 def __init__(self,t,c):self.tables=t;self.ctx=c;self.committed=copy.deepcopy(t);self.decl={};self.cursors={}
 def execute(self,sql):
  q=re.sub(r'^\s*EXEC\s+SQL\s+','',sql,flags=re.I);q=re.sub(r'\s*END-EXEC\.?\s*$','',q,flags=re.I).strip()
  m=re.match(r'SET\s*:?\s*([\w.-]+)\s*=\s*CURRENT[_ ]TIMESTAMP',q,re.I)
  if m:
   v=self.ctx.get('_DB2_CURRENT_TIMESTAMP','2000-01-01-00.00.00.000000');self.ctx[norm(m.group(1))]=v
   return {'status':'OK','operation':'SET','into':{norm(m.group(1)):v},'sqlcode':0}
  if re.match(r'^SELECT\b',q,re.I):return {'operation':'SELECT',**execute_select(sql,self.tables,self.ctx)}
  m=re.match(r'INSERT\s+INTO\s+([\w.]+)\s*\((.*?)\)\s*VALUES\s*\((.*?)\)',q,re.I|re.S)
  if m:
   k=key(m.group(1),self.tables);cs=[norm(x) for x in m.group(2).split(',')];vs=[hv(x,self.ctx) for x in m.group(3).split(',')];row=dict(zip(cs,vs));self.tables.setdefault(k,[]).append(row);return {'status':'OK','operation':'INSERT','table':k,'affected':1,'sqlcode':0}
  m=re.match(r'UPDATE\s+([\w.]+)\s+SET\s+(.+?)(?:\s+WHERE\s+(.+))?$',q,re.I|re.S)
  if m:
   k=key(m.group(1),self.tables);sets={}
   for z in m.group(2).split(','):
    x=re.match(r'([\w.-]+)\s*=\s*(.+)',z.strip());sets[norm(x.group(1).split('.')[-1])]=hv(x.group(2),self.ctx)
   n=0
   for row in self.tables.get(k,[]):
    rr={norm(a):b for a,b in row.items()}
    if ok(m.group(3),rr,self.ctx):row.clear();rr.update(sets);row.update(rr);n+=1
   return {'status':'OK','operation':'UPDATE','table':k,'affected':n,'sqlcode':0 if n else 100}
  m=re.match(r'DELETE\s+FROM\s+([\w.]+)(?:\s+WHERE\s+(.+))?$',q,re.I|re.S)
  if m:
   k=key(m.group(1),self.tables);old=self.tables.get(k,[]);keep=[r for r in old if not ok(m.group(2),{norm(a):b for a,b in r.items()},self.ctx)];n=len(old)-len(keep);self.tables[k]=keep;return {'status':'OK','operation':'DELETE','table':k,'affected':n,'sqlcode':0 if n else 100}
  m=re.match(r'DECLARE\s+([\w-]+)\s+CURSOR\s+FOR\s+(.+)',q,re.I|re.S)
  if m:self.decl[norm(m.group(1))]=m.group(2);return {'status':'OK','operation':'DECLARE_CURSOR','sqlcode':0}
  m=re.match(r'OPEN\s+([\w-]+)',q,re.I)
  if m:
   c=norm(m.group(1));r=execute_select('EXEC SQL '+self.decl[c]+' END-EXEC',self.tables,self.ctx);self.cursors[c]={'rows':r.get('rows',[]),'pos':0};return {'status':'OK','operation':'OPEN_CURSOR','cursor':c,'row_count':len(r.get('rows',[])),'sqlcode':0}
  m=re.match(r'FETCH(?:\s+NEXT\s+ROWSET\s+FROM)?\s+([\w-]+)(?:\s+FOR\s*:?\s*([\w.-]+)\s+ROWS)?\s+INTO\s*:?\s*(.+)',q,re.I|re.S)
  if m:
   c=norm(m.group(1));u=self.cursors[c]
   if u['pos']>=len(u['rows']):return {'status':'OK','operation':'FETCH','into':{},'row_count':0,'sqlcode':100}
   hs=[]
   for item in m.group(3).split(','):
    item=item.strip();mm=re.match(r':?([\w.-]+)',item)
    if mm:hs.append(norm(mm.group(1)))
   if m.group(2):
    n=int(self.ctx.get(norm(m.group(2)),1) or 1);chunk=u['rows'][u['pos']:u['pos']+n];u['pos']+=len(chunk)
    into={h:[] for h in hs}
    for row in chunk:
     vs=list(row.values())
     for i,h in enumerate(hs):into[h].append(vs[i] if i<len(vs) else None)
    # DB2: um FETCH de rowset que devolve menos linhas que as pedidas sinaliza fim de dados (+100) com SQLERRD(3)=linhas devolvidas
    return {'status':'OK','operation':'FETCH','into':into,'row_count':len(chunk),'sqlcode':0 if len(chunk)==n else 100}
   row=u['rows'][u['pos']];u['pos']+=1;vs=list(row.values())
   return {'status':'OK','operation':'FETCH','into':dict(zip(hs,vs)),'row_count':1,'sqlcode':0}
  m=re.match(r'CLOSE\s+([\w-]+)',q,re.I)
  if m:self.cursors.pop(norm(m.group(1)),None);return {'status':'OK','operation':'CLOSE_CURSOR','sqlcode':0}
  if re.match(r'COMMIT\b',q,re.I):self.committed=copy.deepcopy(self.tables);return {'status':'OK','operation':'COMMIT','sqlcode':0}
  if re.match(r'ROLLBACK\b',q,re.I):self.tables.clear();self.tables.update(copy.deepcopy(self.committed));return {'status':'OK','operation':'ROLLBACK','sqlcode':0}
  return {'status':'UNSUPPORTED','operation':'UNKNOWN'}
