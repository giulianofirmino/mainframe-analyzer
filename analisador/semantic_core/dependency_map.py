from __future__ import annotations
import re
from copybook_resolver import copy_refs
from token_utils import tokens_of, V, sql_tables, dotted_name, join_tokens


def declared_cursors(source_text):
 """{cursor: {'line','tables','sql'}} lendo os tokens de EXEC SQL DECLARE <cursor> CURSOR ... FOR SELECT ... END-EXEC."""
 toks=tokens_of(source_text,fixed=False);out={};i=0
 while i<len(toks)-3:
  if V(toks[i])=='EXEC' and V(toks[i+1])=='SQL' and V(toks[i+2])=='DECLARE' and toks[i+3][0]=='IDENT':
   j=i+3
   while j<len(toks) and V(toks[j])!='END-EXEC':j+=1
   body=toks[i+3:j]
   if len(body)>1 and V(body[1])=='CURSOR':
    k=next((x for x,t in enumerate(body) if V(t)=='SELECT'),None)
    if k is not None:
     name=dotted_name(body,0)[0]
     out[name.upper()]={'line':toks[i][2] if len(toks[i])>2 else None,'tables':[t.upper() for t in sql_tables(body[k:])],'sql':join_tokens(body[k:])}
   i=j
  i+=1
 return out
def _walk(ns):
 for n in ns:
  yield n
  for k in ('body','then','else_body','at_end'):
   if isinstance(n.get(k),list):yield from _walk(n[k])
  for w in n.get('whens',[]) or []:yield from _walk(w.get('body',[]))
def build(program,ast,source_text=''):
 d={'program':program,'copybooks':[],'program_calls':[],'sql_commands':[],'tables':[],'columns':[],'cics':[],'files':[]}
 d['copybooks']=sorted({r['name'] for r in copy_refs(source_text) if r['kind']=='COPY'})
 tabs=set();cols=set();curs=declared_cursors(source_text);used={};access=[]
 for n in _walk(ast.get('body',[])):
  typ=n.get('type');line=n.get('start_line')
  if typ=='CALL':d['program_calls'].append({'line':line,'mechanism':'CALL','detail':n.get('args','')})
  elif typ=='EXEC_CICS':
   cmd=n.get('command','');d['cics'].append({'line':line,'command':cmd});
   if re.search(r'\b(LINK|XCTL)\b',cmd,re.I):d['program_calls'].append({'line':line,'mechanism':'CICS','detail':cmd})
  elif typ=='EXEC_SQL':
   sql=n.get('sql','');op=(re.match(r'\s*([A-Z]+)',sql,re.I).group(1).upper() if re.match(r'\s*([A-Z]+)',sql,re.I) else 'UNKNOWN');d['sql_commands'].append({'line':line,'operation':op,'sql':sql})
   cn=next((t for t in tokens_of(sql) if V(t) in curs),None) if op in ('OPEN','CLOSE','FETCH') else None
   if cn:
    used.setdefault(V(cn),[]).append({'line':line,'operation':op})
    for t in curs[V(cn)]['tables']:access.append({'line':line,'table':t,'operation':op,'via_cursor':V(cn)})
    continue
   for t in sql_tables(tokens_of(sql)):
    if t.upper() not in curs:access.append({'line':line,'table':t.upper(),'operation':op,'via_cursor':None})
   for m in re.finditer(r'\b(?:FROM|JOIN|UPDATE|INTO|DELETE\s+FROM|MERGE\s+INTO)\s+([A-Z0-9_.-]+)',sql,re.I):tabs.add(m.group(1).upper())
   for q in re.finditer(r'\b([A-Z][A-Z0-9_-]*)\.([A-Z][A-Z0-9_-]*)\b',sql,re.I):cols.add(q.group(0).upper())
  elif typ.startswith('FILE_'):d['files'].append({'line':line,'operation':typ,'detail':n.get('args','')})
 tabs-=set(curs)
 for c,x in curs.items():tabs.update(x['tables'])
 d['cursors']=[{'cursor':c,'declared_line':x['line'],'tables':x['tables'],'operations':used.get(c,[])} for c,x in sorted(curs.items())]
 d['table_access']=access
 d['tables']=sorted(tabs);d['columns']=sorted(cols);return d
