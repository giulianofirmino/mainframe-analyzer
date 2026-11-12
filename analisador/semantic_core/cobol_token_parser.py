import re
from cobol_token_lexer import lex
STRUCT={'AT','END-SEARCH','END-READ','END-WRITE','END-REWRITE','END-DELETE','END-START','INVALID','NOT'}
START={'IF','EVALUATE','MOVE','INITIALIZE','COMPUTE','ADD','SUBTRACT','MULTIPLY','DIVIDE','SET','PERFORM','GO','GOTO','ACCEPT','CALL','CONTINUE','GOBACK','STOP','DISPLAY','STRING','UNSTRING','INSPECT','NEXT','EXEC','EXIT','SEARCH','OPEN','CLOSE','READ','WRITE','REWRITE','DELETE','START'}
def V(t):return t.value.upper()
def TK(a):
 # tokens do léxico que o nó consumiu, como tuplas (tipo, valor, linha, coluna): a semântica sobre eles não precisa reler texto
 return [(t.type,t.value,t.line,t.column) for t in a]
def N(k,s,e=None,**x):
 e=e or s
 el=e.get('end_line') if isinstance(e,dict) else e.line
 ec=e.get('end_column') if isinstance(e,dict) else e.column
 return {'type':k,'start_line':s.line,'start_column':s.column,'end_line':el,'end_column':ec,**x}
class Parser:
 def __init__(self,t):self.t=t;self.i=0;self.per=0;self.ifd=0  # per: pontos já consumidos; ifd: profundidade de IF (o ponto encerra todos os IF abertos)
 def c(self):return self.t[min(self.i,len(self.t)-1)]
 def peek(self,n=1):return self.t[min(self.i+n,len(self.t)-1)]
 def pop(self):
  x=self.c()
  if V(x)!='EOF':self.i+=1
  if x.type=='PERIOD':self.per+=1
  return x
 def acc(self,v):
  if V(self.c())==v:self.pop();return True
  return False
 def txt(self,a):
  z=' '.join(x.value for x in a)
  z=re.sub(r'\s*:\s*',':',z)
  z=re.sub(r'\s*\.\s*','.',z)
  z=re.sub(r'\s*,\s*',', ',z)
  z=re.sub(r'\(\s+','(',z);z=re.sub(r'\s+\)',')',z)
  return z
 def until(self,stops,period=True):
  a=[];d=0
  while self.c().type!='EOF':
   v=V(self.c())
   if d==0 and (v in stops or (period and self.c().type=='PERIOD')):break
   if v=='(':d+=1
   elif v==')':d=max(0,d-1)
   a.append(self.pop())
  return a
 def parse(self):
  pid=None
  while self.c().type!='EOF':
   if pid is None and V(self.c())=='PROGRAM-ID':
    nx=self.peek(2) if self.peek().type=='PERIOD' else self.peek()
    if nx.type in ('IDENT','KEYWORD'):pid=V(nx)
   if V(self.c())=='PROCEDURE' and V(self.peek())=='DIVISION':
    self.pop();self.pop();hdr=[]
    while self.c().type!='EOF' and self.c().type!='PERIOD':hdr.append(self.pop())
    self.acc('.');break
   self.pop()
  using=[];vals=[V(t) for t in hdr] if 'hdr' in dir() else []
  if 'USING' in vals:
   for t in hdr[vals.index('USING')+1:]:
    if V(t) in ('RETURNING','BY','REFERENCE','CONTENT','VALUE'):
     if V(t)=='RETURNING':break
     continue
    if t.type in ('IDENT','KEYWORD'):using.append(V(t))
  return {'type':'PROGRAM','program_id':pid,'procedure_using':using,'body':self.block(set())}
 def block(self,stops):
  out=[];guard=0
  while self.c().type!='EOF' and V(self.c()) not in stops:
   guard+=1
   if guard>10000:raise RuntimeError('PARSER_NO_PROGRESS '+V(self.c()))
   pos=self.i;per0=self.per
   if self.c().type in ('IDENT','KEYWORD') and V(self.peek())=='SECTION' and self.t[min(self.i+2,len(self.t)-1)].type=='PERIOD':
    s=self.pop();self.pop();e=self.pop();out.append(N('LABEL',s,e,name=V(s),section=True))
   elif self.c().type in ('IDENT','KEYWORD') and self.peek().type=='PERIOD' and V(self.c()) not in START:
    s=self.pop();e=self.pop();out.append(N('LABEL',s,e,name=V(s),section=False))
   else:
    q=self.stmt()
    if q:out.append(q)
   if self.i==pos:self.pop()
   if self.ifd and self.per>per0:break  # ponto final de frase: encerra o IF aberto (e os aninhados) mesmo sem END-IF
  return out
 def simple(self):
  s=self.pop();k=V(s);a=self.until(START|STRUCT|{'ELSE','END-IF','WHEN','END-EVALUATE','END-PERFORM'})
  e=a[-1] if a else s;self.acc('.');return N(k,s,e,args=self.txt(a),arg_tokens=TK(a))
 def stmt(self):
  v=V(self.c())
  if v=='IF':return self.if_()
  if v=='EVALUATE':return self.eval_()
  if v=='PERFORM':return self.perform()
  if v=='SEARCH':return self.search()
  if v in ('OPEN','CLOSE','READ','WRITE','REWRITE','DELETE','START'):return self.fileio()
  if v=='EXEC':return self.sql()
  if v in START:return self.simple()
  return None
 def if_(self):
  s=self.pop();c=self.until(START|{'ELSE','END-IF'});self.ifd+=1;per0=self.per
  try:
   th=self.block({'ELSE','END-IF'});el=[]
   if self.per==per0 and self.acc('ELSE'):el=self.block({'END-IF','ELSE'})  # ELSE depois de ponto não existe; o ELSE que sobra pertence ao IF de fora
  finally:self.ifd-=1
  e=self.c()
  if self.acc('END-IF'):e=self.t[self.i-1];self.acc('.')
  return N('IF',s,e,condition=self.txt(c),condition_tokens=TK(c),then=th,else_body=el)
 def eval_(self):
  s=self.pop();sub=self.until({'WHEN','END-EVALUATE'});ws=[]
  while self.acc('WHEN'):
   w=self.t[self.i-1];c=self.until(START|{'WHEN','END-EVALUATE'});b=self.block({'WHEN','END-EVALUATE'});ws.append(N('WHEN',w,b[-1] if b else w,condition=self.txt(c),condition_tokens=TK(c),body=b))
  e=self.c()
  if self.acc('END-EVALUATE'):e=self.t[self.i-1];self.acc('.')
  return N('EVALUATE',s,e,subject=self.txt(sub),subject_tokens=TK(sub),whens=ws)
 def perform(self):
  s=self.pop();h=self.until(START|{'END-PERFORM','END-IF','ELSE','WHEN','END-EVALUATE'});inline=bool(h and (V(h[0]) in ('UNTIL','VARYING') or (V(h[0])=='WITH' and len(h)>1 and V(h[1])=='TEST') or (len(h)==2 and V(h[1])=='TIMES')));b=[];e=h[-1] if h else s
  if inline:
   b=self.block({'END-PERFORM'});e=self.c()
   if self.acc('END-PERFORM'):e=self.t[self.i-1];self.acc('.')
  else:self.acc('.')
  return N('PERFORM',s,e,header=self.txt(h),header_tokens=TK(h),inline=inline,body=b)
 def fileio(self):
  s=self.pop();op=V(s);head=self.until(START|STRUCT|{'AT','INVALID','NOT','END-READ','END-WRITE','END-REWRITE','END-DELETE','END-START'})
  clauses={}
  while self.c().type!='EOF' and self.c().type!='PERIOD':
   if self.acc('AT'):
    self.acc('END');clauses['AT_END']=self.block({'NOT','END-READ'})
   elif self.acc('INVALID'):
    self.acc('KEY');clauses['INVALID_KEY']=self.block({'NOT','END-READ','END-WRITE','END-REWRITE','END-DELETE','END-START'})
   elif self.acc('NOT'):
    if self.acc('AT'):
     self.acc('END');clauses['NOT_AT_END']=self.block({'END-READ'})
    elif self.acc('INVALID'):
     self.acc('KEY');clauses['NOT_INVALID_KEY']=self.block({'END-READ','END-WRITE','END-REWRITE','END-DELETE','END-START'})
    else:self.pop()
   else:break
  for e in ('END-READ','END-WRITE','END-REWRITE','END-DELETE','END-START'):
   if self.acc(e):break
  self.acc('.');e=self.t[self.i-1] if self.i else s
  return N('FILE_'+op,s,e,args=self.txt(head),arg_tokens=TK(head),clauses=clauses)
 def search(self):
  s=self.pop();subject=self.pop();at_end=[];whens=[]
  while self.c().type!='EOF' and V(self.c())!='END-SEARCH':
   if self.acc('AT'):
    self.acc('END');at_end=self.block({'WHEN','END-SEARCH'})
   elif self.acc('WHEN'):
    w=self.t[self.i-1];c=self.until(START|STRUCT|{'WHEN','END-SEARCH','AT'});b=self.block({'WHEN','END-SEARCH','AT'});whens.append(N('WHEN',w,b[-1] if b else w,condition=self.txt(c),condition_tokens=TK(c),body=b))
   else:self.pop()
  e=self.c()
  if self.acc('END-SEARCH'):e=self.t[self.i-1];self.acc('.')
  return N('SEARCH',s,e,subject=V(subject),subject_tokens=TK([subject]),at_end=at_end,whens=whens)
 def sql(self):
  s=self.pop()
  if self.acc('CICS'):
   a=[]
   while self.c().type!='EOF' and V(self.c())!='END-EXEC':a.append(self.pop())
   e=self.c()
   if self.acc('END-EXEC'):e=self.t[self.i-1];self.acc('.')
   return N('EXEC_CICS',s,e,command=self.txt(a),tokens=TK(a))
  if not self.acc('SQL'):return N('UNSUPPORTED',s,s,reason='EXEC_NOT_SQL_OR_CICS')
  a=[]
  while self.c().type!='EOF' and V(self.c())!='END-EXEC':a.append(self.pop())
  e=self.c()
  if self.acc('END-EXEC'):e=self.t[self.i-1];self.acc('.')
  return N('EXEC_SQL',s,e,sql=self.txt(a),tokens=TK(a))
def parse_text(s):return Parser(lex(s)).parse()
