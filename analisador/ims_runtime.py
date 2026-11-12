import re,copy
def parse_ssa(ssa):
 z=re.match(r'\s*([A-Z0-9-]+)(?:\(([^= ]+)\s*=\s*([^)]+)\))?',ssa,re.I)
 return {'segment':z.group(1).upper(),'field':z.group(2).upper() if z and z.group(2) else None,'value':z.group(3).strip("' \"") if z and z.group(3) else None} if z else None
def call(st,func,db,ssa=None,segment=None):
 f=func.upper();rows=st.ims.setdefault(db,[]);q=parse_ssa(ssa) if ssa else None
 def match(x):return not q or (x.get('_segment','').upper()==q['segment'] and (not q['field'] or str(x.get(q['field']))==str(q['value'])))
 if f in ('GU','GN','GNP'):
  r=next((x for x in rows if match(x)),None);status='  ' if r else 'GE';st.vars['IMS_STATUS']=status;st.emit('IMS_'+f,db=db,ssa=ssa,status=status,segment=r);return copy.deepcopy(r) if r else None
 if f=='ISRT':rows.append(copy.deepcopy(segment));st.vars['IMS_STATUS']='  ';st.emit('IMS_ISRT',db=db,segment=segment,status='  ');return segment
 if f=='REPL':
  r=next((x for x in rows if match(x)),None)
  if r:r.update(segment or {});status='  '
  else:status='GE'
  st.vars['IMS_STATUS']=status;st.emit('IMS_REPL',db=db,ssa=ssa,status=status);return r
 if f=='DLET':
  old=len(rows);st.ims[db]=[x for x in rows if not match(x)];status='  ' if len(st.ims[db])<old else 'GE';st.vars['IMS_STATUS']=status;st.emit('IMS_DLET',db=db,ssa=ssa,status=status);return None
 raise RuntimeError('UNSUPPORTED_IMS_CALL:'+f)
