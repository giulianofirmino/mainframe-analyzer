import hashlib,json
OBS={'MOVE','COMPUTE','ADD','SUBTRACT','MULTIPLY','DIVIDE','SET','EXEC_SQL','EXEC_CICS','FILE_WRITE','FILE_REWRITE','FILE_DELETE','STRING','UNSTRING','INSPECT','CALL'}
def descendants(nodes):
 out=[]
 def walk(ns):
  for n in ns:
   out.append(n)
   for k in ('body','then','else_body','at_end'):
    if isinstance(n.get(k),list):walk(n[k])
   for x in n.get('whens',[]) or []:walk(x.get('body',[]))
   for x in (n.get('clauses') or {}).values():
    if isinstance(x,list):walk(x)
 walk(nodes);return out
def audit(program,ast):
 rows=[]
 for n in descendants(ast.get('body',[])):
  typ=n.get('type')
  if typ not in ('IF','EVALUATE','SEARCH'):continue
  if typ=='IF':branches=[('TRUE',n.get('then',[])),('FALSE',n.get('else_body',[]))]
  else:
   branches=[('WHEN:'+str(i+1),w.get('body',[])) for i,w in enumerate(n.get('whens',[]))]
   if typ=='SEARCH':branches.append(('AT_END',n.get('at_end',[])))
  effects=[]
  for label,b in branches:
   effects += [{'branch':label,'type':x.get('type'),'line':x.get('start_line'),'detail':x.get('args') or x.get('sql') or x.get('command')} for x in descendants(b) if x.get('type') in OBS]
  cond=n.get('condition') or n.get('subject') or ''
  technical=any(x in cond.upper() for x in ('EIBRESP','SQLCODE','FILE STATUS','FILE-STATUS','RESP2'))
  if effects:
   errorish=technical  # decisão sobre status de runtime (SQLCODE, EIBRESP, status de arquivo); nenhum vocabulário do domínio
   classification='BUSINESS_ERROR' if errorish else 'BUSINESS_RULE';reason='DECISION_CONTROLS_OBSERVABLE_EFFECT'
  else:classification='EXCLUDED';reason='NO_OBSERVABLE_FUNCTIONAL_EFFECT'
  core={'program':program,'line':n.get('start_line'),'type':typ,'condition':cond}
  rows.append({'decision_id':'DEC-'+hashlib.sha1(json.dumps(core,sort_keys=True).encode()).hexdigest()[:12].upper(),**core,'classification':classification,'reason':reason,'branch_count':len(branches),'observable_effects':effects})
 return rows
def summarize(rows):
 from collections import Counter
 c=Counter(x['classification'] for x in rows);r=Counter(x['reason'] for x in rows)
 accounted=sum(c.values())
 return {'decisions':len(rows),'accounted':accounted,'decision_accountability_pct':round(100*accounted/len(rows),2) if rows else 100.0,'classifications':dict(c),'reasons':dict(r),'unaccounted':len(rows)-accounted}
