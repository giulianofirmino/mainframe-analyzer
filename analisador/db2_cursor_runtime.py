import re
def _get(row,k):return next((v for x,v in row.items() if x.upper()==k.upper()),None)
class CursorRuntime:
 def __init__(self,st):self.st=st;self.defs={};self.opened={}
 def declare(self,name,sql):self.defs[name.upper()]=sql;self.st.emit('DB2_DECLARE_CURSOR',cursor=name.upper())
 def open(self,name):
  n=name.upper();sql=self.defs[n];z=re.search(r'SELECT\s+(.+?)\s+FROM\s+([A-Z0-9_.-]+)',sql,re.I);cols=[x.strip().upper() for x in z.group(1).split(',')];rows=self.st.db.get(z.group(2).upper(),[])
  self.opened[n]={'rows':rows,'i':0,'cols':cols};self.st.vars['SQLCODE']=0;self.st.emit('DB2_OPEN_CURSOR',cursor=n,count=len(rows))
 def fetch(self,name,into):
  n=name.upper();c=self.opened[n]
  if c['i']>=len(c['rows']):self.st.vars['SQLCODE']=100;self.st.emit('DB2_FETCH',cursor=n,sqlcode=100);return None
  r=c['rows'][c['i']];c['i']+=1
  for col,var in zip(c['cols'],into):self.st.vars[var.upper()]=_get(r,col)
  self.st.vars['SQLCODE']=0;self.st.emit('DB2_FETCH',cursor=n,sqlcode=0,values={v:self.st.vars[v.upper()] for v in into});return r
 def close(self,name):self.opened.pop(name.upper(),None);self.st.vars['SQLCODE']=0;self.st.emit('DB2_CLOSE_CURSOR',cursor=name.upper())
