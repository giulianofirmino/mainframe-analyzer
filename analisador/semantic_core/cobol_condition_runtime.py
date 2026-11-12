import re,functools

def _split(s, word):
 out=[];cur=[];depth=0;quote=None;toks=re.findall(r"'[^']*'|\"[^\"]*\"|\(|\)|[^\s()]+",s)
 for t in toks:
  if t=='(': depth+=1
  elif t==')': depth-=1
  if depth==0 and t.upper()==word:
   out.append(' '.join(cur));cur=[]
  else: cur.append(t)
 out.append(' '.join(cur));return out

def _strip_outer(s):
 s=s.strip()
 while s.startswith('(') and s.endswith(')'):
  d=0;ok=True
  for i,ch in enumerate(s):
   if ch=='(':d+=1
   elif ch==')':d-=1
   if d==0 and i<len(s)-1:ok=False;break
  if not ok:break
  s=s[1:-1].strip()
 return s

@functools.lru_cache(maxsize=None)
def _norm(s):
 s=' '.join(s.split())
 s=re.sub(r'\bIS\s+(NOT\s+)?NUMERIC\b',lambda m:('NOT ' if m.group(1) else '')+'NUMERIC',s,flags=re.I)
 reps=[
 (r'\bIS\s+NOT\s+EQUAL\s+TO\b','!='),(r'\bIS\s+EQUAL\s+TO\b','='),(r'\bNOT\s+EQUAL\s+TO\b','!='),(r'\bEQUAL\s+TO\b','='),
 (r'\bIS\s+GREATER\s+THAN\s+OR\s+EQUAL\s+TO\b','>='),(r'\bIS\s+LESS\s+THAN\s+OR\s+EQUAL\s+TO\b','<='),
 (r'\bGREATER\s+THAN\s+OR\s+EQUAL\s+TO\b','>='),(r'\bLESS\s+THAN\s+OR\s+EQUAL\s+TO\b','<='),
 (r'\bIS\s+GREATER\s+THAN\b','>'),(r'\bGREATER\s+THAN\b','>'),(r'\bIS\s+LESS\s+THAN\b','<'),(r'\bLESS\s+THAN\b','<'),
 (r'\bNOT\s+EQUAL\b','!='),(r'\bEQUAL\b','='),(r'\b(?:IS\s+)?GREATER\b','>'),(r'\b(?:IS\s+)?LESS\b','<'),
 ]
 for a,b in reps:s=re.sub(a,f' {b} ',s,flags=re.I)
 # NOT antes do operador relacional (X NOT = 1, X NOT > 2): vira o operador oposto
 for a,b in ((r'\bNOT\s*>=','<'),(r'\bNOT\s*<=','>'),(r'\bNOT\s*=','!='),(r'\bNOT\s*>','<='),(r'\bNOT\s*<','>=')):s=re.sub(a,f' {b} ',s,flags=re.I)
 return ' '.join(s.split())

def _literal(x, resolve):
 x=_strip_outer(x.strip())
 # Token parser may preserve unary sign as a separate token ('+ 100', '- 1').
 x=re.sub(r'^([+-])\s+(\d)',r'\1\2',x)
 mresp=re.fullmatch(r'DFHRESP\s*\(\s*([^)]+)\s*\)',x,re.I)
 if mresp:
  name=mresp.group(1).strip().upper();return {'NORMAL':0,'QIDERR':44,'NOTFND':13,'LENGERR':22,'INVREQ':16,'ITEMERR':26,'PGMIDERR':27,'ENDDATA':29,'CONTAINERERR':110,'CHANNELERR':122}.get(name,1)
 if x.upper() in ('ZERO','ZEROS','ZEROES'):return 0
 if x.upper() in ('SPACE','SPACES'):return ' '
 if x.upper() in ('LOW-VALUE','LOW-VALUES'):return '\x00'
 if x.upper() in ('HIGH-VALUE','HIGH-VALUES'):return '\xff'
 if len(x)>=2 and x[0] in "'\"" and x[-1]==x[0]:return x[1:-1].replace("''", "'")
 if re.fullmatch(r'[+-]?\d+(?:[.,]\d+)?',x):return float(x.replace(',','.')) if ('.' in x or ',' in x) else int(x)
 return resolve(x)

def _asnum(v):
 if isinstance(v,bool):return None
 if isinstance(v,(int,float)):return v
 t=str(v).strip()
 if re.fullmatch(r'[+-]?\d+(?:[.,]\d+)?',t):return float(t.replace(',','.')) if ('.' in t or ',' in t) else int(t)
 return None

def _coerce(a,b):
 """Comparação COBOL: numérica quando os dois lados são numéricos; senão alfanumérica com brancos à direita ignorados."""
 na,nb=_asnum(a),_asnum(b)
 if na is not None and nb is not None:return na,nb
 return ('' if a is None else str(a)).rstrip(' '),('' if b is None else str(b)).rstrip(' ')

def evaluate(text, resolve, condition88=None):
 s=_strip_outer(_norm(text))
 if re.match(r'^NOT\s+',s,re.I):return not evaluate(re.sub(r'^NOT\s+','',s,count=1,flags=re.I),resolve,condition88)
 # OR/AND with COBOL abbreviated combined relations. Carry lhs/op to bare following operands.
 for word in ('OR','AND'):
  ps=_split(s,word)
  if len(ps)>1:
   first=ps[0];m=re.match(r'(.+?)\s*(>=|<=|!=|<>|=|>|<)\s*(.+)$',first)
   if m:
    lhs,op=m.group(1).strip(),m.group(2)
    ps=[first]+[(f'{lhs} {op} {p}' if not re.search(r'(>=|<=|!=|<>|=|>|<|\bNUMERIC\b)',p,re.I) else p) for p in ps[1:]]
   vals=[evaluate(p,resolve,condition88) for p in ps]
   return any(vals) if word=='OR' else all(vals)
 m=re.match(r'(.+?)\s+(NOT\s+)?NUMERIC$',s,re.I)
 if m:
  v=_literal(m.group(1),resolve);r=isinstance(v,(int,float)) or bool(re.fullmatch(r'[+-]?\d+(?:[.,]\d+)?',str(v).strip()))
  return (not r) if m.group(2) else r
 m=re.match(r'(.+?)\s*(>=|<=|!=|<>|=|>|<)\s*(.+)$',s)
 if m:
  a,b=_coerce(_literal(m.group(1),resolve),_literal(m.group(3),resolve));op=m.group(2)
  try:return {'=':a==b,'!=':a!=b,'<>':a!=b,'>':a>b,'<':a<b,'>=':a>=b,'<=':a<=b}[op]
  except (TypeError,ValueError):return False
 if condition88:
  q=condition88(s)
  if q is not None:return bool(q)
 return bool(_literal(s,resolve))
