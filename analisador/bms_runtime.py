import re
def parse_bms(text):
 maps={};current=None
 for ln,s in enumerate(text.splitlines(),1):
  z=re.match(r'\s*([A-Z0-9-]+)\s+DFHMDI\b(.*)',s,re.I)
  if z:current=z.group(1).upper();maps[current]={'name':current,'fields':[]};continue
  z=re.match(r'\s*([A-Z0-9-]+)\s+DFHMDF\b(.*)',s,re.I)
  if z and current:
   tail=z.group(2);pos=re.search(r'POS=\((\d+),(\d+)\)',tail,re.I);length=re.search(r'LENGTH=(\d+)',tail,re.I);init=re.search(r"INITIAL='([^']*)'",tail,re.I)
   maps[current]['fields'].append({'name':z.group(1).upper(),'row':int(pos.group(1)) if pos else 1,'col':int(pos.group(2)) if pos else 1,'length':int(length.group(1)) if length else 1,'initial':init.group(1) if init else '','attrb':(re.search(r'ATTRB=\(([^)]*)\)|ATTRB=([^, ]+)',tail,re.I).group(1) or re.search(r'ATTRB=\(([^)]*)\)|ATTRB=([^, ]+)',tail,re.I).group(2)).upper().split(',') if re.search(r'ATTRB=\(([^)]*)\)|ATTRB=([^, ]+)',tail,re.I) else [],'color':(re.search(r'COLOR=([^, ]+)',tail,re.I).group(1).upper() if re.search(r'COLOR=([^, ]+)',tail,re.I) else None),'hilight':(re.search(r'HILIGHT=([^, ]+)',tail,re.I).group(1).upper() if re.search(r'HILIGHT=([^, ]+)',tail,re.I) else None)})
 return maps
def render(screen):
 rows=[[' ']*80 for _ in range(24)]
 for f in screen['fields']:
  v=str(f.get('value',f['initial']))[:f['length']]
  for i,c in enumerate(v):
   r=f['row']-1;c0=f['col']-1+i
   if 0<=r<24 and 0<=c0<80:rows[r][c0]=c
 return '\n'.join(''.join(x).rstrip() for x in rows).rstrip()
def send_map(st,maps,name,values=None):
 m=copy_map(maps[name]);values=values or {}
 for f in m['fields']:f['value']=values.get(f['name'],st.vars.get(f['name'],f['initial']))
 st.emit('CICS_SEND_MAP',map=name,screen=render(m));return m
def receive_map(st,maps,name,input_fields,aid='ENTER'):
 for k,v in input_fields.items():
  f=next((x for x in maps[name]['fields'] if x['name']==k.upper()),None)
  if not f or 'PROT' not in f.get('attrb',[]):st.vars[k.upper()]=v
 st.vars['EIBAID']=aid;st.emit('CICS_RECEIVE_MAP',map=name,fields=input_fields,aid=aid)
def copy_map(x):return {'name':x['name'],'fields':[dict(f) for f in x['fields']]}
