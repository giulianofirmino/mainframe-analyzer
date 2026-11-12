import re
from sql_runtime import execute_sql
from bms_runtime import send_map,receive_map
from mq_runtime import *
from ims_runtime import call as ims_call
from cics_runtime import put_container,get_container,start,syncpoint,return_trans
from vsam_runtime import *
def value(st,x):
 x=x.strip().rstrip('.')
 if (x.startswith("'") and x.endswith("'")) or (x.startswith('"') and x.endswith('"')):return x[1:-1]
 try:return int(x)
 except:return st.vars.get(x.upper(),x)
def condition(st,e):
 z=re.match(r"\s*([A-Z0-9_-]+)\s*(=|<>|!=|>=|<=|>|<)\s*(.+)",e,re.I)
 if not z:return False
 a=value(st,z.group(1));b=value(st,z.group(3));op=z.group(2)
 try:return {'=':a==b,'<>':a!=b,'!=':a!=b,'>':a>b,'<':a<b,'>=':a>=b,'<=':a<=b}[op]
 except:return False
def blocks(text):
 lines=text.splitlines();i=0
 while i<len(lines):
  s=lines[i];u=s.upper()
  if 'EXEC SQL' in u or 'EXEC CICS' in u:
   acc=[s];start=i+1
   while 'END-EXEC' not in ' '.join(acc).upper() and i+1<len(lines):i+=1;acc.append(lines[i])
   yield start,' '.join(x.strip() for x in acc)
  else:yield i+1,s
  i+=1
def arg(stmt,name):
 z=re.search(r'\b'+name+r'\s*\(\s*[\'"]?([^)\s\'"]+)',stmt,re.I);return z.group(1) if z else None
def cics_exec(stmt,st,env,sources,stack):
 u=stmt.upper()
 z=re.search(r'\b(LINK|XCTL)\b',u)
 if z:
  pg=arg(stmt,'PROGRAM')
  if not pg:raise RuntimeError('CICS_MISSING_PROGRAM:'+stmt)
  st.vars['_COMMAREA']=value(st,arg(stmt,'COMMAREA')) if arg(stmt,'COMMAREA') else st.vars.get('_COMMAREA')
  st.emit('CICS_'+z.group(1),program=pg.upper(),commarea=st.vars.get('_COMMAREA'));return execute_program(pg.upper(),sources,st,env,stack)
 if re.search(r'\bPUT\s+CONTAINER\b',u):
  cn,ch,fr=arg(stmt,'CONTAINER'),arg(stmt,'CHANNEL'),arg(stmt,'FROM')
  if cn and ch and fr:return put_container(st,ch.upper(),cn.upper(),value(st,fr))
 if re.search(r'\bGET\s+CONTAINER\b',u):
  cn,ch,it=arg(stmt,'CONTAINER'),arg(stmt,'CHANNEL'),arg(stmt,'INTO')
  if cn and ch and it:st.vars[it.upper()]=get_container(st,ch.upper(),cn.upper());return
 if re.search(r'\bSTART\b',u):
  tr=arg(stmt,'TRANSID')
  if tr:return start(st,tr.upper(),value(st,arg(stmt,'FROM')) if arg(stmt,'FROM') else None)
 if re.search(r'\bSYNCPOINT\b',u):return syncpoint(st,'ROLLBACK' in u)
 if re.search(r'\bRETURN\b',u):return return_trans(st,arg(stmt,'TRANSID'),value(st,arg(stmt,'COMMAREA')) if arg(stmt,'COMMAREA') else st.vars.get('_COMMAREA'))
 z=re.search(r'\bSEND\s+MAP\b',u)
 if z:
  mp=arg(stmt,'MAP')
  if mp:return send_map(st,env['bms'],mp.upper())
 z=re.search(r'\bRECEIVE\s+MAP\b',u)
 if z:
  mp=arg(stmt,'MAP')
  if mp:
   inp=env.get('screen_inputs',{}).get(mp.upper(),{});return receive_map(st,env['bms'],mp.upper(),inp.get('fields',inp),inp.get('aid','ENTER') if isinstance(inp,dict) else 'ENTER')
 raise RuntimeError('UNSUPPORTED_CICS:'+stmt)
def execute_program(name,sources,st,env,stack=None):
 stack=(stack or [])+[name]
 if stack.count(name)>1:raise RuntimeError('RECURSIVE_CALL:'+name)
 if name not in sources:raise RuntimeError('UNRESOLVED_PROGRAM:'+name)
 st.emit('PROGRAM_ENTER',program=name);active=[True]
 for ln,s in blocks(sources[name]):
  u=s.strip();U=u.upper()
  z=re.search(r'\bIF\s+(.+?)(?:\s+THEN)?$',u,re.I)
  if z: r=condition(st,z.group(1));active.append(active[-1] and r);st.emit('BRANCH_DECISION',program=name,line=ln,expression=z.group(1),result=r);continue
  if U.rstrip('.')=='ELSE':active[-1]=active[-2] and not active[-1];continue
  if 'END-IF' in U:
   if len(active)>1:active.pop()
   continue
  if not active[-1]:continue
  if 'EXEC SQL' in U:
   body=re.sub(r'.*?EXEC\s+SQL','',u,flags=re.I);body=re.sub(r'END-EXEC.*','',body,flags=re.I);execute_sql(st,body);continue
  if 'EXEC CICS' in U:cics_exec(u,st,env,sources,stack);continue
  z=re.search(r"\bMOVE\s+(.+?)\s+TO\s+([A-Z0-9_-]+)",u,re.I)
  if z:st.vars[z.group(2).upper()]=value(st,z.group(1));st.emit('ASSIGN',program=name,line=ln,target=z.group(2).upper(),value=st.vars[z.group(2).upper()]);continue
  z=re.search(r'\bREAD\s+([A-Z0-9_-]+)\s+KEY\s+(?:IS\s+)?([A-Z0-9_-]+)\s+INTO\s+([A-Z0-9_-]+)',u,re.I)
  if z:st.vars[z.group(3).upper()]=read(st,z.group(1).upper(),value(st,z.group(2)));continue
  z=re.search(r'\bWRITE\s+([A-Z0-9_-]+)\s+FROM\s+([A-Z0-9_-]+)',u,re.I)
  if z:write(st,z.group(1).upper(),value(st,z.group(2)));continue
  z=re.search(r'\bDELETE\s+([A-Z0-9_-]+)\s+KEY\s+(?:IS\s+)?([A-Z0-9_-]+)',u,re.I)
  if z:delete(st,z.group(1).upper(),value(st,z.group(2)));continue
  z=re.search(r"\bCALL\s+['\"]?([A-Z0-9_-]+)",u,re.I)
  if z:
   target=z.group(1).upper()
   if target in sources:execute_program(target,sources,st,env,stack);continue
   args=re.findall(r'\bUSING\b\s+(.+)',u,re.I);aa=args[0].split() if args else []
   if target in ('MQOPEN','MQPUT','MQGET','MQCLOSE','MQCMIT','MQBACK'):
    q=str(value(st,aa[0])) if aa else 'DEFAULT'
    if target=='MQOPEN':mqopen(st,q)
    elif target=='MQPUT':mqput(st,q,value(st,aa[1]) if len(aa)>1 else None)
    elif target=='MQGET':
     x=mqget(st,q)
     if len(aa)>1:st.vars[aa[1].upper()]=x['data'] if x else None
    elif target=='MQCLOSE':mqclose(st,q)
    elif target=='MQCMIT':st.commit();st.begin()
    else:st.rollback();st.begin()
    continue
   if target in ('CBLTDLI','AIBTDLI'):
    f=str(value(st,aa[0])) if aa else '';db=str(value(st,aa[1])) if len(aa)>1 else '';ssa=str(value(st,aa[2])) if len(aa)>2 else None;res=ims_call(st,f,db,ssa)
    if len(aa)>3:st.vars[aa[3].upper()]=res
    continue
   raise RuntimeError('UNSUPPORTED_CALL:'+target)
 st.emit('PROGRAM_EXIT',program=name)
