from __future__ import annotations
import re,json,copy
from pathlib import Path
from dataclasses import dataclass,field
from db2_functional_sql import execute_select,norm
from db2_stateful_runtime import DB2Stateful

FIGURATIVE={'ZERO':0,'ZEROS':0,'ZEROES':0,'SPACE':' ','SPACES':' ','LOW-VALUE':'\x00','LOW-VALUES':'\x00','HIGH-VALUE':'\xff','HIGH-VALUES':'\xff'}
def val(x,s):
 x=x.strip().rstrip('.')
 if x.startswith(':'):x=x[1:]
 if x.upper() in FIGURATIVE:return FIGURATIVE[x.upper()]
 m=re.fullmatch(r'LENGTH\s+OF\s+([A-Z0-9-]+)',x,re.I)
 if m:return getattr(s,'tamanhos',{}).get(m.group(1).upper(),0)   # LENGTH OF: tamanho em bytes do item no programa em execução
 if (len(x)>1 and x[0] in "'\"" and x[-1]==x[0]):return x[1:-1].replace("''","'")
 if re.fullmatch(r'[+-]?\d+(?:[.,]\d+)?',x):return float(x.replace(',','.')) if ('.' in x or ',' in x) else int(x)
 return s.vars.get(norm(x),0)
def expr(e,s):
 e=e.strip().replace('**','^'); toks=re.findall(r"'[^']*'|\"[^\"]*\"|[A-Z0-9-]+|[()+*/^-]",e,re.I)
 # com parênteses: precedência do COBOL (** antes de * e /, antes de + e -; sinal unário); sem parênteses segue a conta da esquerda para a direita
 if '(' in toks or ')' in toks:return _arit(toks,s)
 if len(toks)==1:return val(toks[0],s)
 acc=val(toks[0],s)
 for i in range(1,len(toks),2):
  b=val(toks[i+1],s);op=toks[i]
  if op=='+':acc+=b
  elif op=='-':acc-=b
  elif op=='*':acc*=b
  elif op=='/':acc/=b
  elif op=='^':acc=acc**b
 return acc
def _arit(toks,s):
 pos=[0]
 def ver():return toks[pos[0]] if pos[0]<len(toks) else None
 def tira():t=toks[pos[0]];pos[0]+=1;return t
 def fator():
  t=tira()
  if t=='(':v=soma();tira();return v
  if t=='-':return -fator()
  if t=='+':return fator()
  v=val(t,s);return v if isinstance(v,(int,float)) else (float(v) if str(v).strip().lstrip('-').replace('.','',1).isdigit() else 0)
 def pot():
  v=fator()
  while ver()=='^':tira();v=v**fator()
  return v
 def prod():
  v=pot()
  while ver() in ('*','/'):
   op=tira();b=pot();v=v*b if op=='*' else (v/b if b else 0)
  return v
 def soma():
  v=prod()
  while ver() in ('+','-'):
   op=tira();b=prod();v=v+b if op=='+' else v-b
  return v
 r=soma();return int(r) if isinstance(r,float) and r.is_integer() else r
def cond(c,s):
 c=' '+c.strip().strip('()')+' '
 c=re.sub(r'\s+(?:IS\s+)?NOT\s+EQUAL\s+TO\s+',' <> ',c,flags=re.I)
 c=re.sub(r'\s+(?:IS\s+)?EQUAL(?:\s+TO)?\s+',' = ',c,flags=re.I)
 c=re.sub(r'\s+(?:IS\s+)?GREATER\s+THAN\s+OR\s+EQUAL(?:\s+TO)?\s+',' >= ',c,flags=re.I)
 c=re.sub(r'\s+(?:IS\s+)?LESS\s+THAN\s+OR\s+EQUAL(?:\s+TO)?\s+',' <= ',c,flags=re.I)
 c=re.sub(r'\s+(?:IS\s+)?GREATER(?:\s+THAN)?\s+',' > ',c,flags=re.I)
 c=re.sub(r'\s+(?:IS\s+)?LESS(?:\s+THAN)?\s+',' < ',c,flags=re.I)
 c=c.strip()
 if re.match(r'^NOT\s+',c,re.I):return not cond(re.sub(r'^NOT\s+','',c,flags=re.I),s)
 ors=re.split(r'\s+OR\s+',c,flags=re.I)
 if len(ors)>1:return any(cond(x,s) for x in ors)
 ands=re.split(r'\s+AND\s+',c,flags=re.I)
 if len(ands)>1:return all(cond(x,s) for x in ands)
 m=re.match(r'(.+?)\s+(NOT\s+)?IN\s*\((.+)\)$',c,re.I)
 if m:
  a=val(m.group(1),s);vs=[val(x,s) for x in m.group(3).split(',')];return (a not in vs) if m.group(2) else (a in vs)
 m=re.match(r'(.+?)\s+BETWEEN\s+(.+?)\s+AND\s+(.+)$',c,re.I)
 if m:
  a=val(m.group(1),s);return val(m.group(2),s)<=a<=val(m.group(3),s)
 m=re.match(r'(.+?)\s*(<>|!=|>=|<=|=|>|<)\s*(.+)$',c)
 if not m:return bool(val(c,s))
 a,b=val(m.group(1),s),val(m.group(3),s);op=m.group(2)
 try:return {'=':a==b,'<>':a!=b,'!=':a!=b,'>':a>b,'<':a<b,'>=':a>=b,'<=':a<=b}[op]
 except:return False

@dataclass
class State:
 vars:dict=field(default_factory=dict);tables:dict=field(default_factory=dict);trace:list=field(default_factory=list)
 executed_programs:set=field(default_factory=set);mocked_programs:set=field(default_factory=set);sql:list=field(default_factory=list)
 branches:list=field(default_factory=list);errors:list=field(default_factory=list);steps:int=0;seq:int=0;depth:int=0
 log_file:object=None;jsonl_file:object=None;call_stack:list=field(default_factory=list);perform_stack:list=field(default_factory=list);initial_tables:dict=field(default_factory=dict);db2:object=None;table_changes:list=field(default_factory=list)

def source_lines(text):
 out=[]
 for n,r in enumerate(text.splitlines(),1):
  x=r[7:72] if len(r)>=7 and (r[:6].strip().isdigit() or not r[:6].strip()) else r
  if x.strip() and not x.lstrip().startswith(('*','*>')):out.append((n,x.strip()))
 return out
def statements(text):
 ls=source_lines(text);out=[];i=next((k+1 for k,(_,x) in enumerate(ls) if re.match(r'^PROCEDURE\s+DIVISION',x,re.I)),0)
 while i<len(ls):
  n,x=ls[i]
  if re.match(r'EXEC\s+SQL\b',x,re.I):
   a=[x]
   if re.search(r'END-EXEC',x,re.I):
    out.append({'line':n,'verb':'EXEC SQL','text':x});i+=1;continue
   i+=1
   while i<len(ls):
    a.append(ls[i][1])
    if re.search(r'END-EXEC',ls[i][1],re.I):break
    i+=1
   out.append({'line':n,'verb':'EXEC SQL','text':' '.join(a)});i+=1;continue
  one=re.match(r'^([A-Z0-9][A-Z0-9-]*)\s*\.$',x,re.I)
  control={'END-PERFORM','END-EVALUATE','END-IF','GOBACK','CONTINUE','EXIT','STOP'}
  if re.match(r'^[A-Z0-9][A-Z0-9-]*\s+SECTION\s*\.$',x,re.I) or (one and one.group(1).upper() not in control):
   out.append({'line':n,'verb':'LABEL','text':x,'label':re.split(r'\s+',x)[0].rstrip('.').upper()});i+=1;continue
  out.append({'line':n,'verb':x.split()[0].upper().rstrip('.'),'text':x});i+=1
 return out

class Runtime:
 def __init__(self,programs,mocks=None,max_steps=10000):
  self.programs={k.upper():v for k,v in programs.items()};self.mocks={k.upper():v for k,v in (mocks or {}).items()};self.max_steps=max_steps
 def human(self,r,d):
  pad='  '*max(d,0);q=f"[{r['seq']:06d}]";e=r['event']
  if e=='STATEMENT':return f"{pad}{q} STATEMENT L{r.get('line')}  {r.get('text')}"
  if e=='VARIABLE_ASSIGNMENT':return f"{pad}{q} ASSIGN {r.get('variable')}: {r.get('old_value')!r} -> {r.get('new_value')!r} [{r.get('source')}]"
  if e=='BRANCH_DECISION':return f"{pad}{q} BRANCH {r.get('condition')} => {str(r.get('result')).upper()}"
  if e=='ENTER_PROGRAM':return f"{pad}{q} PROGRAM {r.get('program')} [ENTER]"
  if e=='RETURN_PROGRAM':return f"{pad}{q} PROGRAM {r.get('program')} [RETURN]"
  if e=='ENTER_PERFORM':return f"{pad}{q} PERFORM {r.get('target')} [ENTER]"
  if e=='RETURN_PERFORM':return f"{pad}{q} PERFORM {r.get('target')} [RETURN]"
  if e=='PROGRAM_CALL':return f"{pad}{q} CALL -> {r.get('program')} [{r.get('mode')}]"
  if e=='SCENARIO_INPUT':return '\n'.join([f"{q} SCENARIO INPUT"]+[f"  {k} = {v!r}" for k,v in r.get('inputs',{}).items()])
  if e=='SCENARIO_OUTPUT':return '\n'.join([f"{q} SCENARIO OUTPUT status={r.get('status')}"]+[f"  {k} = {v!r}" for k,v in r.get('outputs',{}).items()])
  if e=='SQL_EXECUTE':return f"{pad}{q} SQL EXECUTE L{r.get('line')}\n{pad}  {r.get('sql')}"
  if e=='SQL_RESULT':return f"{pad}{q} SQL RESULT rows={r.get('row_count')} SQLCODE={r.get('sqlcode')}"
  return f"{pad}{q} {e}"
 def event(self,s,event,**data):
  s.seq+=1
  if event in ('RETURN_PROGRAM','RETURN_PERFORM'):s.depth=max(0,s.depth-1)
  r={'seq':s.seq,'event':event,'depth':s.depth,**data};s.trace.append(r)
  if s.jsonl_file:s.jsonl_file.write(json.dumps(r,ensure_ascii=False,default=str)+'\n');s.jsonl_file.flush()
  if s.log_file:s.log_file.write(self.human(r,s.depth)+'\n');s.log_file.flush()
  if event in ('ENTER_PROGRAM','ENTER_PERFORM'):s.depth+=1
 def assign(self,s,k,v,p,l,src,expression=None):
  k=norm(k);old=s.vars.get(k);s.vars[k]=v;self.event(s,'VARIABLE_ASSIGNMENT',program=p,line=l,variable=k,old_value=old,new_value=v,source=src,expression=expression)
 def mock(self,p,s):
  spec=self.mocks[p];scs=spec.get('scenarios',spec if isinstance(spec,list) else [])
  for sc in scs:
   if sc.get('default') is True or all(s.vars.get(norm(k))==v for k,v in sc.get('when',{}).items()):
    for k,v in sc.get('returns',{}).items():self.assign(s,k,v,p,0,'PROGRAM_MOCK')
    s.mocked_programs.add(p);self.event(s,'MOCK_PROGRAM',program=p,when=sc.get('when',{}),returns=sc.get('returns',{}));return
  raise RuntimeError('MOCK_SCENARIO_NOT_FOUND '+p)
 def execute(self,p,s,depth=0):
  p=p.upper()
  if p in self.mocks:return self.mock(p,s)
  if p not in self.programs:raise RuntimeError('PROGRAM_NOT_FOUND '+p)
  s.executed_programs.add(p);s.call_stack.append(p);self.event(s,'ENTER_PROGRAM',program=p,inputs=dict(s.vars))
  st=statements(Path(self.programs[p]).read_text(encoding='latin-1',errors='replace'));labels={x['label']:i for i,x in enumerate(st) if x['verb']=='LABEL'}
  pc=0;ifs=[];performs=[];evals=[];loops=[]
  while pc<len(st):
   s.steps+=1
   if s.steps>self.max_steps:raise RuntimeError('MAX_STEPS')
   x=st[pc];t=x['text'].strip();v=x['verb'];ln=x['line'];self.event(s,'STATEMENT',program=p,line=ln,text=t)
   # paragraph return boundary
   if v=='LABEL' and performs and performs[-1].get('return_at_label')==x['label']:
    f=performs.pop();s.perform_stack.pop();self.event(s,'RETURN_PERFORM',program=p,target=f['target']);pc=f['return_pc'];continue
   active=all(ifs) if ifs else True
   if evals:active=active and all(e.get('active',True) for e in evals)
   if v=='IF':
    c=re.sub(r'^IF\s+','',t,flags=re.I).rstrip('.');r=cond(c,s) if active else False;ifs.append(active and r);s.branches.append({'program':p,'line':ln,'condition':c,'result':r});self.event(s,'BRANCH_DECISION',program=p,line=ln,condition=c,result=r)
   elif v=='ELSE':
    if ifs:ifs[-1]=(not ifs[-1]) and all(ifs[:-1])
   elif v=='END-IF':
    if ifs:ifs.pop()
   elif v=='EVALUATE':
    subj=re.sub(r'^EVALUATE\s+','',t,flags=re.I).rstrip('.').strip();evals.append({'subject':subj,'matched':False,'active':False,'parent_active':active})
   elif v=='WHEN':
    if not evals:raise RuntimeError('WHEN_WITHOUT_EVALUATE')
    e=evals[-1];w=re.sub(r'^WHEN\s+','',t,flags=re.I).rstrip('.').strip()
    if not e['parent_active'] or e['matched']:r=False
    elif w.upper()=='OTHER':r=True
    elif e['subject'].upper()=='TRUE':r=cond(w,s)
    else:r=(val(e['subject'],s)==val(w,s))
    e['active']=r;e['matched']=e['matched'] or r;s.branches.append({'program':p,'line':ln,'condition':f"EVALUATE {e['subject']} WHEN {w}",'result':r});self.event(s,'BRANCH_DECISION',program=p,line=ln,condition=f"EVALUATE {e['subject']} WHEN {w}",result=r)
   elif v=='END-EVALUATE':
    if evals:evals.pop()
   elif not active:pc+=1;continue
   elif v=='MOVE':
    m=re.match(r'MOVE\s+(.+?)\s+TO\s+(.+?)(?:\.)?$',t,re.I)
    if m:
     z=val(m.group(1),s)
     for k in re.split(r'\s+',m.group(2).rstrip('.')):self.assign(s,k,z,p,ln,'MOVE',m.group(1))
   elif v=='INITIALIZE':
    for k in re.split(r'\s+',re.sub(r'^INITIALIZE\s+','',t,flags=re.I).rstrip('.')):self.assign(s,k,0,p,ln,'INITIALIZE')
   elif v=='COMPUTE':
    m=re.match(r'COMPUTE\s+([A-Z0-9-]+)\s*=\s*(.+?)(?:\.)?$',t,re.I)
    if m:self.assign(s,m.group(1),expr(m.group(2).rstrip('.'),s),p,ln,'COMPUTE',m.group(2))
   elif v in ('ADD','SUBTRACT','MULTIPLY','DIVIDE'):
    patterns={
     'ADD':r'ADD\s+(.+?)\s+TO\s+([A-Z0-9-]+)',
     'SUBTRACT':r'SUBTRACT\s+(.+?)\s+FROM\s+([A-Z0-9-]+)',
     'MULTIPLY':r'MULTIPLY\s+(.+?)\s+BY\s+([A-Z0-9-]+)',
     'DIVIDE':r'DIVIDE\s+([A-Z0-9-]+)\s+BY\s+(.+?)\s+GIVING\s+([A-Z0-9-]+)'}
    m=re.match(patterns[v],t,re.I)
    if not m:raise RuntimeError('UNSUPPORTED_ARITHMETIC '+t)
    if v=='ADD':self.assign(s,m.group(2),s.vars.get(norm(m.group(2)),0)+val(m.group(1),s),p,ln,v)
    elif v=='SUBTRACT':self.assign(s,m.group(2),s.vars.get(norm(m.group(2)),0)-val(m.group(1),s),p,ln,v)
    elif v=='MULTIPLY':self.assign(s,m.group(2),s.vars.get(norm(m.group(2)),0)*val(m.group(1),s),p,ln,v)
    else:self.assign(s,m.group(3),val(m.group(1),s)/val(m.group(2),s),p,ln,v)
   elif v=='SET':
    m=re.match(r'SET\s+([A-Z0-9-]+)\s+TO\s+(TRUE|FALSE|.+?)(?:\.)?$',t,re.I)
    if not m:raise RuntimeError('UNSUPPORTED_SET')
    self.assign(s,m.group(1),True if m.group(2).upper()=='TRUE' else False if m.group(2).upper()=='FALSE' else val(m.group(2),s),p,ln,'SET')
   elif v=='STRING':
    m=re.match(r'STRING\s+(.+?)\s+INTO\s+([A-Z0-9-]+)',t,re.I)
    if not m:raise RuntimeError('UNSUPPORTED_STRING')
    parts=re.split(r'\s+DELIMITED\s+BY\s+(?:SIZE|SPACE)\s*',m.group(1),flags=re.I);z=''.join(str(val(q,s)) for q in parts if q.strip());self.assign(s,m.group(2),z,p,ln,'STRING')
   elif v=='INSPECT':
    m=re.match(r'INSPECT\s+([A-Z0-9-]+)\s+REPLACING\s+ALL\s+(.+?)\s+BY\s+(.+?)(?:\.)?$',t,re.I)
    if not m:raise RuntimeError('UNSUPPORTED_INSPECT')
    self.assign(s,m.group(1),str(val(m.group(1),s)).replace(str(val(m.group(2),s)),str(val(m.group(3),s))),p,ln,'INSPECT')
   elif v=='EXEC SQL':
    self.event(s,'SQL_EXECUTE',program=p,line=ln,sql=t,host_variables=dict(s.vars));before=copy.deepcopy(s.tables);r=s.db2.execute(t);s.sql.append({'program':p,'line':ln,'sql':t,'result':r})
    self.event(s,'SQL_RESULT',program=p,line=ln,operation=r.get('operation'),table=r.get('table'),affected=r.get('affected'),row_count=r.get('row_count'),sqlcode=r.get('sqlcode'),into=r.get('into',{}))
    if r.get('status')!='OK':raise RuntimeError('UNSUPPORTED_SQL')
    for k,z in r.get('into',{}).items():self.assign(s,k,z,p,ln,'SQL_INTO',t)
    self.assign(s,'SQLCODE',r.get('sqlcode'),p,ln,'SQL_STATUS')
    if before!=s.tables:
     ch={'program':p,'line':ln,'operation':r.get('operation'),'table':r.get('table'),'affected':r.get('affected'),'before':before,'after':copy.deepcopy(s.tables)};s.table_changes.append(ch);self.event(s,'TABLE_MUTATION',**ch)
   elif v=='CALL':
    m=re.search(r'CALL\s+[\'"]?([A-Z0-9-]+)',t,re.I)
    if not m:raise RuntimeError('UNSUPPORTED_CALL')
    q=m.group(1).upper();self.event(s,'PROGRAM_CALL',program=q,mode='MOCK' if q in self.mocks else 'REAL',caller=p,line=ln);self.execute(q,s,depth+1)
   elif v=='PERFORM':
    # inline UNTIL/VARYING
    mu=re.match(r'PERFORM\s+UNTIL\s+(.+)',t,re.I);mv=re.match(r'PERFORM\s+VARYING\s+([A-Z0-9-]+)\s+FROM\s+(.+?)\s+BY\s+(.+?)\s+UNTIL\s+(.+)',t,re.I)
    if mu or mv:
     end=next((j for j in range(pc+1,len(st)) if st[j]['verb']=='END-PERFORM'),None)
     if end is None:raise RuntimeError('UNSUPPORTED_INLINE_PERFORM')
     if mv:
      k,start,by,c=mv.groups();self.assign(s,k,val(start,s),p,ln,'PERFORM_VARYING_INIT');loops.append({'start':pc+1,'end':end,'condition':c,'var':k,'by':val(by,s)})
     else:loops.append({'start':pc+1,'end':end,'condition':mu.group(1).rstrip('.'),'var':None,'by':None})
     if cond(loops[-1]['condition'],s):loops.pop();pc=end+1;continue
    else:
     m=re.match(r'PERFORM\s+([A-Z0-9-]+)(?:\s+THRU(?:GH)?\s+([A-Z0-9-]+))?',t,re.I)
     if not m or m.group(1).upper() not in labels:raise RuntimeError('PERFORM_TARGET_NOT_FOUND')
     target=m.group(1).upper();endlabel=(m.group(2) or target).upper();idx=labels.get(endlabel)
     nxt=sorted((i,l) for l,i in labels.items() if i>idx);frame={'target':target,'return_pc':pc+1,'return_at_label':nxt[0][1] if nxt else None};performs.append(frame);s.perform_stack.append(frame);self.event(s,'ENTER_PERFORM',program=p,target=target,end=endlabel);pc=labels[target];continue
   elif v=='END-PERFORM':
    if loops and loops[-1]['end']==pc:
     q=loops[-1]
     if q['var']:self.assign(s,q['var'],s.vars.get(norm(q['var']),0)+q['by'],p,ln,'PERFORM_VARYING_STEP')
     if cond(q['condition'],s):loops.pop()
     else:pc=q['start'];continue
   elif v in ('GO','GOTO'):
    md=re.match(r'(?:GO\s+TO|GOTO)\s+(.+?)\s+DEPENDING\s+ON\s+([A-Z0-9-]+)',t,re.I)
    if md:
     labs=md.group(1).split();n=int(val(md.group(2),s))
     if n<1 or n>len(labs):pc+=1;continue
     q=labs[n-1].upper()
    else:
     m=re.search(r'(?:GO\s+TO|GOTO)\s+([A-Z0-9-]+)',t,re.I);q=m.group(1).upper() if m else ''
    if q not in labels:raise RuntimeError('UNSUPPORTED_GOTO')
    pc=labels[q];continue
   elif v=='NEXT':
    if re.match(r'NEXT\s+SENTENCE',t,re.I):
     j=pc+1
     while j<len(st) and not st[j]['text'].rstrip().endswith('.'):j+=1
     pc=min(j+1,len(st));continue
   elif v=='EXIT':
    if re.match(r'EXIT\s+PERFORM',t,re.I):
     if not loops:raise RuntimeError('EXIT_PERFORM_OUTSIDE_LOOP')
     pc=loops.pop()['end']+1;continue
   elif v in ('GOBACK','STOP'):break
   elif v in ('CONTINUE','DISPLAY','LABEL'):pass
   elif v=='UNSTRING':raise RuntimeError('UNSUPPORTED_UNSTRING_COMPLEX')
   pc+=1
  self.event(s,'RETURN_PROGRAM',program=p,outputs=dict(s.vars));s.call_stack.pop()
 def run(self,entry,scenario,log_path=None,jsonl_path=None):
  s=State(vars=copy.deepcopy({norm(k):v for k,v in scenario.get('inputs',{}).items()}),tables=copy.deepcopy({k.upper():v for k,v in scenario.get('tables',{}).items()}))
  if log_path:s.log_file=open(log_path,'w',encoding='utf-8',buffering=1)
  if jsonl_path:s.jsonl_file=open(jsonl_path,'w',encoding='utf-8',buffering=1)
  s.initial_tables=copy.deepcopy(s.tables);fab=getattr(self,'db2_factory',None);s.db2=fab(self,s) if fab else DB2Stateful(s.tables,s.vars)   # db2_factory: DB2 de verdade no lugar da base em memória
  self.event(s,'SCENARIO_INPUT',entry_program=entry.upper(),inputs=dict(s.vars));self.event(s,'TABLE_MOCK_STATE',tables={k:len(v) for k,v in s.tables.items()})
  try:self.execute(entry,s);status='SUCCESS'
  except Exception as e:
   import os,traceback
   if os.environ.get('RT_TRACEBACK'):traceback.print_exc()
   status='UNSUPPORTED' if str(e).startswith(('UNSUPPORTED','PERFORM_TARGET')) else 'ERROR';s.errors.append({'type':type(e).__name__,'message':str(e)})
  self.event(s,'SCENARIO_OUTPUT',status=status,outputs=dict(s.vars),errors=s.errors)
  for f in (s.log_file,s.jsonl_file):
   if f:f.flush();f.close()
  return {'scenario':scenario.get('name','scenario'),'status':status,'inputs':{norm(k):v for k,v in scenario.get('inputs',{}).items()},'outputs':dict(s.vars),'final_state':dict(s.vars),'executed_programs':sorted(s.executed_programs),'mocked_programs':sorted(s.mocked_programs),'branches':s.branches,'sql':s.sql,'trace':s.trace,'errors':s.errors,'steps':s.steps,'call_stack':s.call_stack,'perform_stack':s.perform_stack,'initial_tables':s.initial_tables,'final_tables':s.tables,'table_changes':s.table_changes,'open_cursors':list(s.db2.cursors) if s.db2 else []}
