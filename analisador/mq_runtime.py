import hashlib,json
def mqopen(st,q):st.emit('MQOPEN',queue=q,cc=0,rc=0);return q
def mqput(st,q,msg,reply_to=None,correl_id=None):
 seq=len(st.queues.setdefault(q,[]))+1;mid=hashlib.sha256(f'{q}:{seq}:{json.dumps(msg,sort_keys=True)}'.encode()).hexdigest()[:24].upper()
 item={'data':msg,'msg_id':mid,'correl_id':correl_id,'reply_to_q':reply_to};st.queues[q].append(item);st.emit('MQPUT',queue=q,descriptor=item,cc=0,rc=0);return item
def mqget(st,q,correl_id=None):
 a=st.queues.setdefault(q,[]);idx=next((i for i,x in enumerate(a) if correl_id is None or x.get('correl_id')==correl_id),None)
 if idx is None:st.emit('MQGET',queue=q,cc=2,rc=2033);return None
 x=a.pop(idx);st.emit('MQGET',queue=q,descriptor=x,cc=0,rc=0);return x
def mqclose(st,q):st.emit('MQCLOSE',queue=q,cc=0,rc=0)
