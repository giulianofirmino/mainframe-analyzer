import re,copy
class Catalog:
 def __init__(self,state):self.state=state;self.gdg=state.vars.setdefault('_GDG',{})
 def resolve(self,dsn):
  z=re.match(r'(.+)\(([+-]?\d+)\)$',dsn)
  if not z:return dsn
  base,n=z.group(1),int(z.group(2));gens=self.gdg.setdefault(base,[])
  if n>0:
   name=f'{base}.G{len(gens)+n:04d}V00'
   if name not in gens:gens.append(name)
   return name
  return gens[n-1] if gens and abs(n)<=len(gens) else dsn
def parse_procs(texts):
 procs={}
 for text in texts:
  cur=None;buf=[]
  for s in text.splitlines():
   z=re.match(r'//([A-Z0-9#$@]+)\s+PROC\b(.*)',s,re.I)
   if z:cur=z.group(1).upper();buf=[];continue
   if cur and re.match(r'//\s*PEND\b',s,re.I):procs[cur]=buf;cur=None;continue
   if cur:buf.append(s)
 return procs
def expand_proc(lines,procs):
 out=[]
 for s in lines:
  z=re.match(r'//([A-Z0-9#$@]+)\s+EXEC\s+(?:PROC=)?([A-Z0-9#$@]+)(?:,(.*))?$',s,re.I)
  if z and z.group(2).upper() in procs:
   vals={}
   if z.group(3):
    for x in z.group(3).split(','):
     if '=' in x:k,v=x.split('=',1);vals[k.strip().upper()]=v.strip()
   for q in procs[z.group(2).upper()]:
    for k,v in vals.items():q=q.replace('&'+k+'.',v).replace('&'+k,v)
    out.append(q)
  else:out.append(s)
 return out
def collect_dd(lines,catalog):
 dd={};curstep=None;i=0
 while i<len(lines):
  s=lines[i];z=re.match(r'//([A-Z0-9#$@]+)\s+EXEC\b',s,re.I)
  if z:curstep=z.group(1).upper();dd.setdefault(curstep,{})
  z=re.match(r'//([A-Z0-9#$@]+)\s+DD\s+(.*)',s,re.I)
  if z and curstep:
   name=z.group(1).upper();tail=z.group(2);d=re.search(r'DSN=([^,\s]+)',tail,re.I)
   if d:dd[curstep][name]={'dsn':catalog.resolve(d.group(1)),'raw':tail}
   elif tail.strip() in ('*','DATA'): # instream
    data=[];i+=1
    while i<len(lines) and not lines[i].startswith('/*') and not re.match(r'//\S+\s+',lines[i]):data.append(lines[i]);i+=1
    dd[curstep][name]={'instream':'\n'.join(data),'raw':tail};continue
  i+=1
 return dd
def utility(st,pgm,dds):
 p=pgm.upper()
 if p=='IEFBR14':st.emit('UTILITY_IEFBR14',dds=dds);return 0
 if p in ('SORT','ICEMAN'):
  inp=dds.get('SORTIN',{}).get('dsn');out=dds.get('SORTOUT',{}).get('dsn');rows=copy.deepcopy(st.files.get(inp,[]));rows.sort(key=lambda x:str(x));st.files[out]=rows;st.emit('UTILITY_SORT',input=inp,output=out,count=len(rows));return 0
 raise RuntimeError('UNSUPPORTED_UTILITY:'+p)
