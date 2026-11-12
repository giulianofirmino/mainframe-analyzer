def response(st,command,resp=0,resp2=0):st.vars['EIBRESP']=resp;st.vars['EIBRESP2']=resp2;st.emit('CICS_RESPONSE',command=command,resp=resp,resp2=resp2)
def put_container(st,channel,name,data):st.vars.setdefault('_CHANNELS',{}).setdefault(channel,{})[name]=data;response(st,'PUT_CONTAINER')
def get_container(st,channel,name):x=st.vars.setdefault('_CHANNELS',{}).setdefault(channel,{}).get(name);response(st,'GET_CONTAINER',0 if x is not None else 122);return x
def start(st,transid,data=None):st.vars.setdefault('_STARTED_TRANS',[]).append({'transid':transid,'data':data});response(st,'START');st.emit('CICS_START',transid=transid,data=data)
def syncpoint(st,rollback=False):
 if rollback:st.rollback();st.begin();response(st,'SYNCPOINT_ROLLBACK')
 else:st.commit();st.begin();response(st,'SYNCPOINT')
def return_trans(st,transid=None,commarea=None):st.vars['_RETURN_TRANSID']=transid;st.vars['_COMMAREA']=commarea;response(st,'RETURN');st.emit('CICS_RETURN',transid=transid,commarea=commarea)

def getmain(st,length,key=None):
 n=int(length);mem=bytearray(n);ident=key or f"MEM{len(st.vars.setdefault('_CICS_MEMORY',{}))+1}";st.vars['_CICS_MEMORY'][ident]=mem;response(st,'GETMAIN');st.emit('CICS_GETMAIN',id=ident,length=n);return ident
def freemain(st,ident):
 ok=st.vars.setdefault('_CICS_MEMORY',{}).pop(ident,None) is not None;response(st,'FREEMAIN',0 if ok else 16);st.emit('CICS_FREEMAIN',id=ident);return ok
def writeq(st,queue,data,item=None):
 q=st.vars.setdefault('_CICS_TSQ',{}).setdefault(queue,[])
 if item is None:q.append(data);item=len(q)
 else:
  i=int(item)-1
  while len(q)<=i:q.append(None)
  q[i]=data
 response(st,'WRITEQ');st.emit('CICS_WRITEQ',queue=queue,item=item);return item
def readq(st,queue,item=1):
 q=st.vars.setdefault('_CICS_TSQ',{}).setdefault(queue,[]);i=int(item)-1
 if i<0 or i>=len(q) or q[i] is None:response(st,'READQ',44);return None
 response(st,'READQ');st.emit('CICS_READQ',queue=queue,item=item);return q[i]
def deleteq(st,queue):
 ok=st.vars.setdefault('_CICS_TSQ',{}).pop(queue,None) is not None;response(st,'DELETEQ',0 if ok else 44);st.emit('CICS_DELETEQ',queue=queue);return ok
def assign(st,**values):
 st.vars.update(values);response(st,'ASSIGN');st.emit('CICS_ASSIGN',values=values);return values
def asktime(st):
 # deterministic logical clock; scenario may seed _CICS_TIME
 v=st.vars.get('_CICS_TIME','2000-01-01T00:00:00');response(st,'ASKTIME');st.emit('CICS_ASKTIME',value=v);return v
def formattime(st,value,fmt='%Y-%m-%d %H:%M:%S'):
 from datetime import datetime
 try:d=datetime.fromisoformat(str(value));v=d.strftime(fmt)
 except Exception:v=str(value)
 response(st,'FORMATTIME');st.emit('CICS_FORMATTIME',value=v);return v
