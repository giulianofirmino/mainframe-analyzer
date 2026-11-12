import re
from cobol_token_parser import parse_text
def norm(x):return str(x).upper().replace('-','_')
def add(g,var,origin,**kw):
 if not var:return
 g.setdefault(norm(var),[])
 z={'origin':origin,**kw}
 if z not in g[norm(var)]:g[norm(var)].append(z)
def build(program_texts):
 g={}
 for p,text in program_texts.items():
  ast=parse_text(text)
  def walk(nodes):
   for n in nodes:
    k=n.get('type')
    if k=='EXEC_SQL':
     q=re.sub(r':\s+([A-Z0-9-]+)',r':\1',n.get('sql',''),flags=re.I);tm=re.search(r'\bFROM\s+([A-Z0-9_.-]+)',q,re.I);table=tm.group(1).upper() if tm else None
     im=re.search(r'\bINTO\s+(.+?)\s+FROM\b',q,re.I|re.S)
     sm=re.search(r'\bSELECT\s+(.+?)\s+INTO\b',q,re.I|re.S)
     hosts=re.findall(r':([A-Z0-9-]+)',im.group(1)) if im else []
     cols=[x.strip().split()[-1].split('.')[-1].upper() for x in sm.group(1).split(',')] if sm else []
     for i,h in enumerate(hosts):add(g,h,'TABLE',program=p,table=table,column=cols[i] if i<len(cols) else None,sql=q,line=n.get('start_line'))
     # host vars in WHERE are controllable inputs to query, but do not override stronger output lineage.
     wm=re.search(r'\bWHERE\s+(.+)',q,re.I|re.S)
     if wm:
      wh=wm.group(1)
      for h in re.findall(r':([A-Z0-9-]+)',wh):add(g,h,'SQL_INPUT',program=p,table=table,line=n.get('start_line'))
      for col,h in re.findall(r'([A-Z0-9_.-]+)\s*=\s*:([A-Z0-9-]+)',wh,re.I):
       add(g,h,'SQL_KEY',program=p,table=table,column=col.split('.')[-1].upper(),line=n.get('start_line'))
    elif k=='FILE_READ':
     a=n.get('args','');parts=a.split();fn=parts[0].upper() if parts else None;im=re.search(r'\bINTO\s+([A-Z0-9-]+)',a,re.I)
     if im:add(g,im.group(1),'FILE',program=p,file=fn,line=n.get('start_line'))
    elif k=='CALL':
     a=n.get('args','');m=re.match(r'[\'"]?([A-Z0-9-]+)',a,re.I);um=re.search(r'\bUSING\s+(.+)',a,re.I)
     if m and um:
      callee=m.group(1).upper()
      if callee not in program_texts:
       for x in um.group(1).split():
        if x.upper() not in ('BY','REFERENCE','CONTENT','VALUE'):add(g,x,'PROGRAM',program=p,callee=callee,line=n.get('start_line'))
    elif k=='EXEC_CICS':
     q=n.get('command','');pm=re.search(r'PROGRAM\s*\(\s*[\'"]?([A-Z0-9-]+)',q,re.I);cm=re.search(r'COMMAREA\s*\(\s*([A-Z0-9-]+)',q,re.I)
     if pm and cm:add(g,cm.group(1),'PROGRAM',program=p,callee=pm.group(1).upper(),transport='COMMAREA',line=n.get('start_line'))
    elif k in ('MOVE','COMPUTE','ADD','SUBTRACT','MULTIPLY','DIVIDE','SET'):
     a=n.get('args','');dest=None
     if k=='MOVE':
      m=re.search(r'\bTO\s+([A-Z0-9-]+)',a,re.I);dest=m.group(1) if m else None
     elif k=='COMPUTE':
      m=re.match(r'([A-Z0-9-]+)\s*=',a,re.I);dest=m.group(1) if m else None
     if dest:add(g,dest,'DERIVED',program=p,expression=a,line=n.get('start_line'))
    for key in ('then','else_body','body'):
     if isinstance(n.get(key),list):walk(n[key])
    for w in n.get('whens',[]) or []:walk(w.get('body',[]))
  walk(ast.get('body',[]))
 return g
def resolve(var,g):
 xs=g.get(norm(var),[])
 rank={'TABLE':0,'FILE':1,'PROGRAM':2,'SQL_KEY':3,'SQL_INPUT':4,'DERIVED':5}
 return sorted(xs,key=lambda z:rank.get(z['origin'],9))[0] if xs else {'origin':'INPUT'}
