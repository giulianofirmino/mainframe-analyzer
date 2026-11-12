import copy
class FileRuntime:
 def __init__(self,files=None):
  self.files=copy.deepcopy(files or {});self.pos={};self.open_modes={};self.current_key={}
 def _f(self,n):
  n=n.upper()
  if n not in self.files:self.files[n]={'organization':'SEQUENTIAL','records':[],'key':None}
  if isinstance(self.files[n],list):self.files[n]={'organization':'SEQUENTIAL','records':self.files[n],'key':None}
  return self.files[n]
 def open(self,n,mode):
  self._f(n);self.open_modes[n.upper()]=mode.upper();self.pos[n.upper()]=0;return {'file_status':'00'}
 def close(self,n):
  self.open_modes.pop(n.upper(),None);return {'file_status':'00'}
 def read_next(self,n):
  f=self._f(n);k=n.upper();i=self.pos.get(k,0)
  if i>=len(f['records']):return {'file_status':'10','at_end':True,'record':None}
  self.pos[k]=i+1;return {'file_status':'00','at_end':False,'record':copy.deepcopy(f['records'][i]),'index':i}
 def read_key(self,n,key):
  f=self._f(n);kn=f.get('key')
  for i,r in enumerate(f['records']):
   if isinstance(r,dict) and r.get(kn)==key:self.pos[n.upper()]=i+1;self.current_key[n.upper()]=key;return {'file_status':'00','invalid_key':False,'record':copy.deepcopy(r),'index':i}
  return {'file_status':'23','invalid_key':True,'record':None}
 def start(self,n,key,op='>='):
  f=self._f(n);kn=f.get('key')
  for i,r in enumerate(f['records']):
   v=r.get(kn) if isinstance(r,dict) else None
   ok=(v>=key if op=='>=' else v>key if op=='>' else v==key)
   if ok:self.pos[n.upper()]=i;return {'file_status':'00','invalid_key':False}
  return {'file_status':'23','invalid_key':True}
 def write(self,n,record):
  f=self._f(n);kn=f.get('key')
  if kn and isinstance(record,dict) and any(isinstance(r,dict) and r.get(kn)==record.get(kn) for r in f['records']):return {'file_status':'22','invalid_key':True}
  f['records'].append(copy.deepcopy(record));return {'file_status':'00','invalid_key':False}
 def rewrite(self,n,record):
  f=self._f(n);kn=f.get('key')
  if not kn:return {'file_status':'49','invalid_key':True}
  key=record.get(kn)
  for i,r in enumerate(f['records']):
   if r.get(kn)==key:f['records'][i]=copy.deepcopy(record);return {'file_status':'00','invalid_key':False}
  return {'file_status':'23','invalid_key':True}
 def delete(self,n,key):
  f=self._f(n);kn=f.get('key')
  for i,r in enumerate(f['records']):
   if isinstance(r,dict) and r.get(kn)==key:f['records'].pop(i);return {'file_status':'00','invalid_key':False}
  return {'file_status':'23','invalid_key':True}
