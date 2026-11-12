import copy,hashlib,json
class State:
 def __init__(self,scenario=None):
  s=scenario or {};self.vars=copy.deepcopy(s.get('inputs',{}));self.db=copy.deepcopy(s.get('db2',{}));self.files=copy.deepcopy(s.get('files',{}))
  self.ims=copy.deepcopy(s.get('ims',{}));self.queues=copy.deepcopy(s.get('mq',{}));self.trace=[];self.tx=[]
 def emit(self,kind,**data):self.trace.append({'seq':len(self.trace)+1,'kind':kind,**data})
 def snapshot(self):return {'vars':copy.deepcopy(self.vars),'db2':copy.deepcopy(self.db),'files':copy.deepcopy(self.files),'ims':copy.deepcopy(self.ims),'mq':copy.deepcopy(self.queues)}
 def begin(self):self.tx.append(self.snapshot());self.emit('TX_BEGIN')
 def commit(self):
  if self.tx:self.tx.pop()
  self.emit('TX_COMMIT')
 def rollback(self):
  if self.tx:
   x=self.tx.pop();self.vars=x['vars'];self.db=x['db2'];self.files=x['files'];self.ims=x['ims'];self.queues=x['mq']
  self.emit('TX_ROLLBACK')
 def trace_hash(self):return hashlib.sha256(json.dumps(self.trace,sort_keys=True,separators=(',',':')).encode()).hexdigest()
