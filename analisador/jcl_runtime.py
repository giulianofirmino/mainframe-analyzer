import re
from program_runtime import execute_program
from jcl_environment import Catalog,parse_procs,expand_proc,collect_dd,utility
def subst(s,symbols):
 for k,v in symbols.items():s=s.replace('&'+k+'.',str(v)).replace('&'+k,str(v))
 return s
def run_jcl(text,sources,st,env):
 symbols={};st.emit('JOB_START');last_rc=0
 procs=env.get('procs',{});lines=expand_proc(text.splitlines(),procs);dds=collect_dd(lines,Catalog(st))
 text='\n'.join(lines)
 for ln,raw in enumerate(text.splitlines(),1):
  s=subst(raw,symbols)
  z=re.match(r'//\s*SET\s+([A-Z0-9]+)=(.+)',s,re.I)
  if z:symbols[z.group(1).upper()]=z.group(2).strip();st.emit('JCL_SET',name=z.group(1).upper(),value=z.group(2).strip());continue
  z=re.match(r'//([A-Z0-9#$@]+)\s+EXEC\s+(.+)',s,re.I)
  if not z:continue
  step=z.group(1).upper();body=z.group(2);pg=re.search(r'\bPGM=([A-Z0-9-]+)',body,re.I);cond=re.search(r'\bCOND=\((\d+),(EQ|NE|LT|LE|GT|GE)\)',body,re.I)
  if cond:
   n=int(cond.group(1));op=cond.group(2).upper();skip={'EQ':last_rc==n,'NE':last_rc!=n,'LT':last_rc<n,'LE':last_rc<=n,'GT':last_rc>n,'GE':last_rc>=n}[op]
   if skip:st.emit('STEP_SKIPPED',step=step,cond=cond.group(0),previous_rc=last_rc);continue
  if not pg:raise RuntimeError('UNSUPPORTED_PROC_EXEC:'+body)
  pa=re.search(r"\bPARM=(?:'([^']*)'|\"([^\"]*)\"|([^,\s]+))",body,re.I)
  if pa:st.vars['PARM']=next(x for x in pa.groups() if x is not None);st.emit('JCL_PARM',step=step,value=st.vars['PARM'])
  st.emit('STEP_START',step=step,program=pg.group(1).upper());prog=pg.group(1).upper()
  if prog in sources:execute_program(prog,sources,st,env)
  else:last_rc=utility(st,prog,dds.get(step,{}))
  last_rc=int(st.vars.get('RETURN-CODE',last_rc));st.emit('STEP_END',step=step,rc=last_rc)
 st.emit('JOB_END',rc=last_rc)
