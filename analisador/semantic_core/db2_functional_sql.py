from __future__ import annotations
import re,itertools,functools
from sql_aggregate import parse_aggregate,evaluate
from token_utils import tokens_of,sql_host_pairs
from dataclasses import dataclass,field

@functools.lru_cache(maxsize=None)
def _norm_str(n): return n.strip().upper().replace('-','_')
def norm(n): return _norm_str(n) if isinstance(n,str) and n else str(n or '').strip().upper().replace('-','_')
def strip_exec(sql):
 s=re.sub(r'^\s*EXEC\s+SQL\s+','',sql,flags=re.I);return re.sub(r'\s+END-EXEC\s*\.?\s*$','',s,flags=re.I).strip()
def csvsplit(s):
 out=[];cur='';depth=0;quote=None
 for c in s:
  if quote:
   cur+=c
   if c==quote:quote=None
  elif c in "'\"":quote=c;cur+=c
  elif c=='(':depth+=1;cur+=c
  elif c==')':depth-=1;cur+=c
  elif c==',' and depth==0:out.append(cur.strip());cur=''
  else:cur+=c
 if cur.strip():out.append(cur.strip())
 return out

@dataclass
class Query:
 raw:str; columns:list=field(default_factory=list); into:list=field(default_factory=list); tables:list=field(default_factory=list)
 where:str=''; left_joins:list=field(default_factory=list); order_by:list=field(default_factory=list); distinct:bool=False; limit:int|str|None=None; offset:int|str|None=None; supported:bool=True; unsupported:list=field(default_factory=list)

def parse_select(sql):
 s=' '.join(strip_exec(sql).replace('\n',' ').split())
 # DB2 isolation suffix does not change result-set semantics in this deterministic simulator.
 s=re.sub(r'\s+WITH\s+UR\s*$','',s,flags=re.I)
 s=re.sub(r'\s*\.\s*','.',s)
 # COBOL embedded SQL commonly emits INTO:HOST without whitespace after tokenization.
 s=re.sub(r'\bINTO\s*:', 'INTO :', s, flags=re.I)
 # paginação do DB2 (OFFSET n ROWS e FETCH FIRST n ROWS ONLY), com número ou variável host; sai do texto antes de separar as cláusulas
 pag={}
 for k,rx in (('offset',r'\s+OFFSET\s+(:?[\w.-]+)\s+ROWS?\b'),('limit',r'\s+FETCH\s+FIRST\s+(:?[\w.-]+)\s+ROWS?\s+ONLY\b')):
  m=re.search(rx,s,re.I)
  if m:pag[k]=int(m.group(1)) if m.group(1).isdigit() else m.group(1);s=s[:m.start()]+s[m.end():]
 q=Query(s);q.offset=pag.get('offset');q.limit=pag.get('limit')
 m=re.match(r'SELECT\s+(DISTINCT\s+)?(.+?)\s+INTO\s+(.+?)\s+FROM\s+(.+)$',s,re.I)
 if not m:
  m=re.match(r'SELECT\s+(DISTINCT\s+)?(.+?)\s+FROM\s+(.+)$',s,re.I)
  if not m:q.supported=False;q.unsupported=['SELECT_SHAPE'];return q
  dist,cols,tail=m.groups();into=''
 else:dist,cols,into,tail=m.groups()
 q.distinct=bool(dist);q.columns=csvsplit(cols)
 # Host indicators may be written :HOST:INDICATOR without whitespace.
 raw_into=csvsplit(into);q.into=[]
 for x in raw_into:
  hs=re.findall(r':([A-Z0-9_.-]+)',x,re.I)
  q.into.append(hs[0] if hs else x.strip().lstrip(':'))
 # split clauses
 parts=re.split(r'\s+(WHERE|ORDER\s+BY|FETCH\s+FIRST)\s+',tail,flags=re.I); frm=parts[0].strip(); clauses={}
 for i in range(1,len(parts),2):clauses[parts[i].upper().replace('  ',' ')]=parts[i+1].strip()
 # ANSI JOIN normalized into table list + ON predicates; LEFT [OUTER] JOIN fica à parte (q.left_joins: nome, alias, ON)
 on=[]
 if re.search(r'\b(RIGHT|FULL)\s+(OUTER\s+)?JOIN\b',frm,re.I):
  q.unsupported.append('OUTER_JOIN');q.supported=False
 seg=re.split(r'\s+((?:LEFT\s+(?:OUTER\s+)?|INNER\s+)?)JOIN\s+',frm,flags=re.I)
 first=seg[0]
 table_chunks=[(x,None) for x in csvsplit(first)]
 for tipo,x in zip(seg[1::2],seg[2::2]):
  z=re.split(r'\s+ON\s+',x,maxsplit=1,flags=re.I)
  if tipo.strip().upper().startswith('LEFT'):table_chunks.append((z[0].strip(),z[1].strip() if len(z)>1 else ''));continue
  table_chunks.append((z[0].strip(),None))
  if len(z)>1:on.append(z[1].strip())
 for x,left_on in table_chunks:
  p=x.split()
  if not p:continue
  name=p[0];alias=p[-1] if len(p)>1 and p[-2].upper()!='AS' else (p[-1] if len(p)>2 else name.split('.')[-1])
  if len(p)==1:alias=name.split('.')[-1]
  if left_on is None:q.tables.append((name.upper(),alias.upper()))
  else:q.left_joins.append((name.upper(),alias.upper(),left_on))
 q.where=' AND '.join(on+([clauses.get('WHERE','')] if clauses.get('WHERE') else []))
 if 'ORDER BY' in clauses:q.order_by=csvsplit(re.split(r'\s+FETCH\s+FIRST\s+',clauses['ORDER BY'],flags=re.I)[0])
 for bad in ('GROUP BY','HAVING','UNION','INTERSECT','EXCEPT','FOR UPDATE'):
  if re.search(r'\b'+bad+r'\b',s,re.I):q.unsupported.append(bad);q.supported=False
 return q

def value(expr,row,ctx):
 e=expr.strip()
 def fig(v):
  return 0 if isinstance(v,str) and v.upper() in ('ZERO','ZEROS','ZEROES') else (' ' if isinstance(v,str) and v.upper() in ('SPACE','SPACES') else v)
 mf=re.match(r'(?:IFNULL|COALESCE|VALUE)\s*\(\s*(.+?)\s*,\s*(.+)\)$',e,re.I)
 if mf:
  v=value(mf.group(1),row,ctx)
  return v if v is not None else value(mf.group(2),row,ctx)
 mi=re.fullmatch(r':\s*([\w.-]+)\s*:\s*([\w.-]+)',e)   # :CAMPO :INDICADOR — indicador negativo = NULL
 if mi:
  ind=value(':'+mi.group(2),row,ctx)
  try:
   if ind is not None and float(ind)<0:return None
  except (TypeError,ValueError):pass
  e=':'+mi.group(1)
 if e.startswith(':'):
  k=norm(e[1:])
  if k in ctx:return fig(ctx.get(k))
  # Runtime may hold a COBOL qualified item by its unqualified field name.
  tail=k.split('.')[-1]
  matches=[v for q,v in ctx.items() if q==tail or q.endswith('.'+tail)]
  return fig(matches[0]) if len(matches)==1 else fig(ctx.get(tail))
 if (e.startswith("'") and e.endswith("'")) or (e.startswith('"') and e.endswith('"')):return e[1:-1].replace("''","'")
 if re.fullmatch(r'[+-]?\d+(?:\.\d+)?',e):return float(e) if '.' in e else int(e)
 key=norm(e)
 if key in row:return row[key]
 # unqualified column if unique
 matches=[v for k,v in row.items() if k.endswith('.'+key)]
 return matches[0] if len(matches)==1 else ctx.get(key)


def boolsplit(expr,word):
 out=[];cur=[];depth=0;quote=None;i=0;u=expr.upper();token=' '+word.upper()+' '
 while i<len(expr):
  c=expr[i]
  if quote:
   cur.append(c)
   if c==quote:quote=None
   i+=1;continue
  if c in "'\"":quote=c;cur.append(c);i+=1;continue
  if c=='(':depth+=1
  elif c==')':depth=max(0,depth-1)
  if depth==0 and u.startswith(token,i):
   out.append(''.join(cur).strip());cur=[];i+=len(token);continue
  cur.append(c);i+=1
 out.append(''.join(cur).strip())
 return out

def _wrapped(e):
 """True só quando o primeiro '(' fecha no último ')' (ex.: '(a) OR (b)' NÃO está embrulhado)."""
 if not (e.startswith('(') and e.endswith(')')):return False
 depth=0;quote=None
 for i,c in enumerate(e):
  if quote:
   if c==quote:quote=None
   continue
  if c in "'\"":quote=c;continue
  if c=='(':depth+=1
  elif c==')':
   depth-=1
   if depth==0:return i==len(e)-1
 return False

def predicate(expr,row,ctx):
 if not expr:return True
 # basic parentheses and AND/OR
 e=expr.strip()
 while _wrapped(e):e=e[1:-1].strip()
 parts=boolsplit(e,'OR')
 if len(parts)>1:return any(predicate(x,row,ctx) for x in parts)
 parts=boolsplit(e,'AND')
 if len(parts)>1:return all(predicate(x,row,ctx) for x in parts)
 m=re.match(r'(.+?)\s+IS\s+(NOT\s+)?NULL$',e,re.I)
 if m:return (value(m.group(1),row,ctx) is None) != bool(m.group(2))   # IS NULL: nulo; IS NOT NULL: não nulo
 m=re.match(r'(.+?)\s+(NOT\s+)?IN\s*\((.+)\)$',e,re.I)
 if m:
  ok=value(m.group(1),row,ctx) in [value(x,row,ctx) for x in csvsplit(m.group(3))]
  return not ok if m.group(2) else ok
 m=re.match(r'(.+?)\s+BETWEEN\s+(.+?)\s+AND\s+(.+)$',e,re.I)
 if m:
  x,a,b=(value(m.group(i),row,ctx) for i in (1,2,3));return a<=x<=b
 m=re.match(r'(.+?)\s*(=|<>|!=|>=|<=|>|<)\s*(.+)$',e)
 if not m:return False
 a,b=value(m.group(1),row,ctx),value(m.group(3),row,ctx);op=m.group(2)
 try:return {'=':a==b,'<>':a!=b,'!=':a!=b,'>':a>b,'<':a<b,'>=':a>=b,'<=':a<=b}[op]
 except TypeError:return False

def _filtrar_antes_da_juncao(q,datasets,ctx):
 """Junção: cada condição do WHERE (ligada por AND no nível de cima) que só cita colunas de uma tabela (ALIAS.COLUNA) filtra essa
 tabela antes do produto; o WHERE inteiro continua sendo avaliado nas combinações, então o resultado é o mesmo, só mais rápido."""
 if not q.where or len(boolsplit(q.where,'OR'))>1:return datasets
 aliases=[ds[0][0] if ds else None for ds in datasets]
 nomes={norm(a) for a in aliases if a}
 out=[list(ds) for ds in datasets]
 for cj in boolsplit(q.where,'AND'):
  refs={norm(m.group(1)) for m in re.finditer(r'(?<![:\w.])([A-Z][A-Z0-9_]*)\.[A-Z][A-Z0-9_-]*',cj,re.I)}
  sem_alias=re.search(r'(?<![:\w.])[A-Z][A-Z0-9_]*(?![\w.(])',re.sub(r"'[^']*'|:\s*[\w.-]+|\b(?:AND|OR|NOT|IN|IS|NULL|BETWEEN|LIKE|VALUE|COALESCE|IFNULL)\b",' ',cj,flags=re.I),re.I)
  if len(refs)!=1 or not refs<=nomes or sem_alias:continue
  i=[norm(a) if a else None for a in aliases].index(next(iter(refs)))
  out[i]=[(al,r) for al,r in out[i] if predicate(cj,{norm(al+'.'+k):v for k,v in r.items()},ctx)]
 return out

def execute_select(sql,tables,ctx=None):
 ctx={norm(k):v for k,v in (ctx or {}).items()};q=parse_select(sql)
 if not q.supported:return {'status':'UNSUPPORTED','query':q.__dict__,'rows':[]}
 datasets=[]
 for name,alias in q.tables:
  data=tables.get(name,tables.get(name.split('.')[-1],[]))
  datasets.append([(alias,r) for r in data])
 if len(datasets)>1:datasets=_filtrar_antes_da_juncao(q,datasets,ctx)
 # com LEFT JOIN, o produto das tabelas internas usa só as condições que não citam as tabelas da junção externa;
 # cada linha recebe as linhas que atendem ao ON (ou uma linha de nulos) e o WHERE inteiro vale depois
 externos={norm(a) for _n,a,_o in q.left_joins}
 cita_externo=lambda cj:any(norm(m.group(1)) in externos for m in re.finditer(r'(?<![:\w.])([A-Z][A-Z0-9_]*)\.[A-Z]',cj,re.I))   # noqa: E731
 antes=' AND '.join(cj for cj in boolsplit(q.where,'AND') if not cita_externo(cj)) if q.left_joins and q.where and len(boolsplit(q.where,'OR'))==1 else ('' if q.left_joins else q.where)
 rows=[]
 for combo in itertools.product(*datasets) if datasets else [()]:
  rr={}
  for alias,r in combo:
   for k,v in r.items():rr[norm(alias+'.'+k)]=v
  if predicate(antes,rr,ctx):rows.append(rr)
 for name,alias,cond in q.left_joins:
  data=tables.get(name,tables.get(name.split('.')[-1],[]))
  nulos={norm(alias+'.'+k):None for r in data for k in r}
  estendidas=[]
  for rr in rows:
   achou=[{**rr,**{norm(alias+'.'+k):v for k,v in r.items()}} for r in data]
   achou=[x for x in achou if predicate(cond,x,ctx)]
   estendidas.extend(achou or [{**rr,**nulos}])
  rows=estendidas
 if q.left_joins and q.where:rows=[rr for rr in rows if predicate(q.where,rr,ctx)]
 if q.order_by:
  # DB2 ORDER BY is applied before projection; stable sorts support mixed ASC/DESC keys.
  for term in reversed(q.order_by):
   desc=bool(re.search(r'\s+DESC$',term,re.I))
   expr=re.sub(r'\s+(ASC|DESC)$','',term,flags=re.I)
   rows.sort(key=lambda rr:(value(expr,rr,ctx) is None,value(expr,rr,ctx)),reverse=desc)
 aggs=[parse_aggregate(c) for c in q.columns]
 if any(aggs):
  # SELECT com agregação devolve sempre uma linha (MAX sem linhas = NULL); NULL sem variável indicadora é SQLCODE -305
  vals=[(norm(c.split('.')[-1]),evaluate(a,rows,lambda col,r:value(col,r,ctx)) if a else None) for c,a in zip(q.columns,aggs)]
  projected=[dict(vals)];rows=[]
  into={norm(h):vals[i][1] if i<len(vals) else None for i,h in enumerate(q.into)}
  pairs=sql_host_pairs(tokens_of(strip_exec(sql)))
  nulls=[h for (h,ind),(_,v) in zip(pairs,vals) if v is None and not ind]
  return {'status':'OK','query':q.__dict__,'rows':projected,'row_count':1,'into':into,'sqlcode':-305 if nulls else 0}
 projected=[]
 for rr in rows:
  vals=[]
  for c in q.columns:
   alias=None
   ma=re.match(r'(.+?)\s+AS\s+([A-Z0-9_-]+)$',c,re.I)
   expr=ma.group(1) if ma else c;alias=ma.group(2) if ma else c.split('.')[-1]
   vals.append((norm(alias),value(expr,rr,ctx)))
  projected.append(dict(vals))
 if q.distinct:
  seen=set();tmp=[]
  for r in projected:
   k=tuple(r.items())
   if k not in seen:seen.add(k);tmp.append(r)
  projected=tmp
 hv_=lambda x:x if isinstance(x,int) else (lambda v:int(v) if v is not None and str(v).lstrip('-').isdigit() else 0)(ctx.get(norm(str(x).lstrip(':')),ctx.get(norm(str(x).lstrip(':')).split('.')[-1])))   # noqa: E731
 if q.offset is not None:projected=projected[max(hv_(q.offset),0):]
 if q.limit is not None:projected=projected[:max(hv_(q.limit),0)]
 into={}
 if q.into and projected:
  vals=list(projected[0].values())
  into={norm(h):vals[i] if i<len(vals) else None for i,h in enumerate(q.into)}
 return {'status':'OK','query':q.__dict__,'rows':projected,'row_count':len(projected),'into':into,'sqlcode':0 if projected else 100}
