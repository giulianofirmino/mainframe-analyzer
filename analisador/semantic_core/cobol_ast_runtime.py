from __future__ import annotations
import re,copy,json,functools
from pathlib import Path
from cobol_functional_runtime import Runtime as BaseRuntime,State,val,expr,norm,FIGURATIVE
from cobol_condition_runtime import evaluate as eval_condition
from cobol_token_parser import parse_text
from token_utils import sql_host_pairs,perform_spec
from cobol_data_model import build_data_model
from mainframe_file_runtime import FileRuntime
from cobol_file_model import file_model
class StopRun(Exception):pass
MQI = {'MQOPEN', 'MQGET', 'MQPUT', 'MQPUT1', 'MQCLOSE', 'MQCONN', 'MQDISC'}
RESP_CICS = {'NORMAL': 0, 'NOTFND': 13, 'INVREQ': 16, 'LENGERR': 22, 'ITEMERR': 26, 'PGMIDERR': 27, 'ENDDATA': 29, 'QIDERR': 44, 'CONTAINERERR': 110, 'CHANNELERR': 122}
class GoTo(Exception):
 def __init__(self,label):super().__init__(label);self.label=label
def _igual_cobol(a,b):
 """Igualdade do EVALUATE: alfanuméricos de tamanhos diferentes são comparados com o menor completado com espaços (o valor 'O '
 de um X(02) é igual ao literal 'O')."""
 if isinstance(a,str) and isinstance(b,str):return a.rstrip(' ')==b.rstrip(' ')
 return a==b
def cobnum(v):
 if isinstance(v,(int,float)):return v
 x=str(v).strip().upper()
 if x in ('ZERO','ZEROS','ZEROES','SPACE','SPACES',''):return 0
 try:return float(x) if '.' in x else int(x)
 except:return 0
@functools.lru_cache(maxsize=None)
def read_source(path):
 """Texto do fonte lido uma vez por caminho (o runtime roda milhares de execuções sobre os mesmos programas)."""
 return Path(path).read_text(encoding='latin-1',errors='replace')

_DERIVADOS={}
_LAYOUTS={}
_LINKAGE={}


@functools.lru_cache(maxsize=None)
def _ast_do_fonte(path):
 return parse_text(read_source(path))


@functools.lru_cache(maxsize=None)
def _modelo_do_fonte(path):
 return build_data_model(read_source(path))

@functools.lru_cache(maxsize=None)
def _ref_shape(x):
 """Forma sintática de uma referência a dado (só depende do texto): ('REFMOD', nome, ini, tam) | ('IDX', nome, subscrito) | ('NAME', nome)."""
 qm=re.match(r'^([A-Z0-9-]+)\s+(?:OF|IN)\s+([A-Z0-9-]+)$',x,re.I)
 if qm:x=qm.group(2)+'.'+qm.group(1)
 x=re.sub(r'\s+','',x)
 m=re.match(r'^([A-Z0-9-]+)\(([^():]+):([^()]+)\)$',x,re.I)
 if m:return ('REFMOD',norm(m.group(1)),m.group(2),m.group(3))
 m=re.match(r'^([A-Z0-9-]+)\(([^()]+)\)$',x,re.I)
 if m:return ('IDX',norm(m.group(1)),m.group(2))
 return ('NAME',norm(x))

def field_ref(x,s):
 shape=_ref_shape(x.strip())
 if shape[0]=='REFMOD':return shape[1],('REFMOD',shape[2],shape[3])
 if shape[0]=='IDX':
  z=shape[2];return shape[1],(int(z) if z.isdigit() else int(s.vars.get(norm(z),0)))
 return shape[1],None

class _TamanhoDinamico(dict):
 """LENGTH OF com memória em bytes: grupo com OCCURS ... DEPENDING ON vale o tamanho corrente (pelo valor do campo de controle)."""
 def __init__(self,rt,s,base):super().__init__(base);self.rt=rt;self.s=s
 def get(self,k,d=None):
  import cobol_layout_codec as codec
  lay=self.rt.layout_de(k)
  if lay is not None and codec.tem_odo(lay):return len(self.rt.area_texto(self.s,k))
  return super().get(k,d)

class Runtime(BaseRuntime):
 def run(self,entry,scenario,log_path=None,jsonl_path=None):
  self.scenario=scenario
  self.accept_q={norm(k):list(v) for k,v in scenario.get('accept',{}).items()};self.keys_q=list(scenario.get('teclas',[]))  # entradas de tela por variável e teclas de saída (ESC = 2 quando a fila acaba)
  self.file_runtime=FileRuntime(scenario.get('files',{}));self.file_status_map={k.upper():v for k,v in scenario.get('file_status_map',{}).items()};self._mq=None;self._containers={};self._canais=[];self._imagens={};r=super().run(entry,scenario,log_path,jsonl_path);r['final_files']=self.file_runtime.files;r['final_queues']=(self._mq or {}).get('filas',{});return r
 def canon(self,name):
  # CAMPO OF GRUPO / GRUPO.CAMPO: como no COBOL, o qualificador só é necessário quando o nome é ambíguo no programa.
  if '.' in name:
   q,f=name.split('.',1)
   if f not in getattr(self,'ambiguous',set()):return f
  return name
 def resolve_name(self,s,name):
  v=self._resolve_name(s,name)
  # REDEFINES alfanumérico de um numérico DISPLAY (X(3) sobre 9(3)): o item enxerga os bytes do base, os dígitos com zeros à esquerda
  if isinstance(v,(int,float)) and not isinstance(v,bool) and getattr(self,'aliases',None):
   k0,idx=field_ref(name,s)
   if idx is None:
    k0=self.canon(norm(k0));base=self.aliases.get(k0)
    if base and base!=k0:
     dm=(getattr(self,'_dm_atual',None) or (None,{}))[1] or {};by=dm.get('by_name',{})
     ia,ib=by.get(k0.replace('_','-')),by.get(base.replace('_','-'))
     if ia and ib and ia['picture']['category']!='NUMERIC' and ib['picture']['category']=='NUMERIC' and not ib.get('usage') and (ib['picture']['scale'] or 0)==0:
      z=ib['picture']['digits'] or 0
      return str(abs(int(v))).zfill(z)[-z:] if z else str(abs(int(v)))
  return v
 def _resolve_name(self,s,name):
  k,idx=field_ref(name,s);k=self.canon(norm(k));k=self.aliases.get(k,k)
  if k not in s.vars and '.' not in k and not isinstance(idx,tuple):
   alt=[q for q in s.vars if isinstance(q,str) and q.endswith('.'+k)]
   if len(alt)==1:k=alt[0]
  if isinstance(idx,tuple) and idx[0]=='REFMOD':
   v=str(s.vars.get(k,''));st=int(idx[1]) if str(idx[1]).isdigit() else int(s.vars.get(norm(idx[1]),1));ln=int(idx[2]) if str(idx[2]).isdigit() else int(s.vars.get(norm(idx[2]),0));return v[st-1:st-1+ln]
  if idx is not None:
   arr=s.vars.get(k,[])
   if not isinstance(arr,(list,tuple)):return arr  # OCCURS com VALUE: toda ocorrência começa com o valor inicial
   return arr[idx-1] if 1<=idx<=len(arr) else 0
  if k in self.conds88:
   c=self.conds88[k];return s.vars.get(norm(c['parent']))==c['value']
  if k in getattr(self,'groups',{}):  # grupo lido como um todo: elementares concatenados no tamanho da PIC
   out=''
   for n,z,c in self.groups[k]:
    if n=='FILLER':out+=' '*z;continue  # FILLER guarda espaços; cauda de espaços não conta na comparação (COBOL completa o menor)
    v=s.vars.get(n,0)
    out+=(str(abs(int(v))).zfill(z)[-z:] if z else str(v)) if c=='NUMERIC' and str(v).lstrip('-').isdigit() else str(v).ljust(z)[:z] if z else str(v)
   return out.rstrip(' ') if self.groups[k][-1][0]=='FILLER' else out
  if k not in s.vars:  # campo declarado e ainda não gravado: valor inicial pela PIC (numérico 0, alfanumérico brancos)
   lv=getattr(self,'init_leaves',{}).get(k)
   if lv and len(lv)==1 and lv[0][0]==k:return lv[0][1]
  return s.vars.get(k,0)
 def sql_indicators(self,s,n,r,p):
  """Variável indicadora do INTO (:HOST :IND): -1 quando a coluna devolvida é NULL, 0 quando tem valor (pelos tokens do comando)."""
  got=r.get('into') or {}
  if not got:return
  for host,ind in sql_host_pairs(n.get('tokens') or []):
   if not ind:continue
   key=norm(host)
   if key not in got:
    tail=[q for q in got if q.split('.')[-1]==key.split('.')[-1]]
    if len(tail)!=1:continue
    key=tail[0]
   v=got[key]
   if isinstance(v,(list,tuple)):continue
   self.assign(s,ind,-1 if v is None else 0,p,n['start_line'],'SQL_INDICATOR',host)
 def assign(self,s,k,v,p,l,src,expression=None):
  name,idx=field_ref(k,s);name=self.canon(norm(name));target=self.aliases.get(name,name)
  if name in self.conds88:
   c=self.conds88[name]
   if v is True:self.assign(s,c['parent'],c['value'],p,l,'SET_88',name)
   return
  if isinstance(idx,tuple) and idx[0]=='REFMOD':
   old=str(s.vars.get(target,''));st=int(idx[1]) if str(idx[1]).isdigit() else int(s.vars.get(norm(idx[1]),1));ln=int(idx[2]) if str(idx[2]).isdigit() else int(s.vars.get(norm(idx[2]),0));nv=str(v);s.vars[target]=old[:st-1]+nv[:ln].ljust(ln)+old[st-1+ln:];self.event(s,'VARIABLE_ASSIGNMENT',program=p,line=l,variable=k,old_value=old,new_value=s.vars[target],source=src);return
  if idx is not None:
   meta=self.arrays.get(target,{});size=meta.get('size') or idx
   if meta.get('depending_on'):size=min(size,int(s.vars.get(norm(meta['depending_on']),size)))
   if idx>size:raise RuntimeError('OCCURS_BOUND_EXCEEDED '+target)
   cur=s.vars.get(target,[]);arr=list(cur) if isinstance(cur,(list,tuple)) else []
   while len(arr)<max(size,idx):arr.append(0)
   old=arr[idx-1];arr[idx-1]=v;s.vars[target]=arr;self.event(s,'VARIABLE_ASSIGNMENT',program=p,line=l,variable=f'{target}({idx})',old_value=old,new_value=v,source=src,expression=expression);return
  super().assign(s,target,v,p,l,src,expression)
  self.overlay_sync(s,target,p,l)
  gs=getattr(self,'groups',{}).get(target)
  recorte=src=='MOVE' and bool(re.search(r'\(\s*[A-Z0-9-]+\s*:\s*[A-Z0-9-]+\s*\)',str(expression or ''),re.I))
  if gs and isinstance(v,str) and v.strip() and (recorte or src in ('PROGRAM_MOCK','CICS_LINK_OUTPUT')):   # recorte de texto (CAMPO(i:n)) ou retorno de mock movido para um grupo: cada elementar recebe a sua faixa
   pos=0
   for n,z,c in gs:
    peca=v[pos:pos+z] if z else '';pos+=z
    if n=='FILLER' or not z:continue
    if c=='NUMERIC':peca=int(peca) if peca.strip().isdigit() else (peca if peca.strip() else 0)
    super().assign(s,n,peca,p,l,'MOVE_PARA_GRUPO',target)
 def overlay_sync(self,s,target,p,l):
  """REDEFINES de um campo por elementares: gravar o base preenche os filhos; gravar um filho refaz o base.
  Base '+9(n)': texto = sinal + dígitos. Base X(n): texto contínuo, cada filho ocupa sua faixa."""
  ov=getattr(self,'overlays',None)
  if not ov or getattr(self,'_ovl_busy',False):return
  self._ovl_busy=True
  def fmt(v,n,cat):
   if cat=='NUMERIC' and str(v).lstrip('-').isdigit():return str(abs(int(v))).zfill(n)[-n:] if n else str(v)
   return str(v).ljust(n)[:n] if n else str(v)
  try:
   if target in ov:
    kids=ov[target];size=max(o+n for _,o,n,_,_ in kids);v=s.vars.get(target,0)
    if kids[0][4]=='S':
     try:num=int(v);txt=('-' if num<0 else '+')+str(abs(num)).zfill(max(size-1,1))
     except (TypeError,ValueError):txt=str(v).ljust(size)
    else:txt=str(v).ljust(size)
    for name,off,n,cat,_ in kids:
     piece=txt[off:off+n]
     if cat=='NUMERIC':
      body=piece[1:] if kids[0][4]=='S' and piece[:1] in '+-' else piece
      piece=int(body) if body.isdigit() else 0
     self.assign(s,name,piece,p,l,'REDEFINES',target)
   else:
    for base,kids in ov.items():
     for name,off,n,cat,kind in kids:
      if name!=target:continue
      sv=s.vars.get(base,0)
      if kind=='S':
       neg=isinstance(sv,(int,float)) and sv<0;cv=s.vars.get(name,0)
       nv=(-1 if neg else 1)*int(cv) if cat=='NUMERIC' and str(cv).lstrip('-').isdigit() else cv
      else:
       size=max(o+z for _,o,z,_,_ in kids);txt=str(sv if isinstance(sv,str) else '').ljust(size)
       nv=(txt[:off]+fmt(s.vars.get(name,0),n,cat)+txt[off+n:]).rstrip()
      s.vars[base]=nv
      self.event(s,'VARIABLE_ASSIGNMENT',program=p,line=l,variable=base,old_value=sv,new_value=nv,source='REDEFINES')
      return
  finally:self._ovl_busy=False
 def ast(self,p):
  return _ast_do_fonte(self.programs[p])   # uma árvore por fonte no processo
 def condition(self,text,s):
  def c88(name):
   k=norm(name.strip())
   if k not in self.conds88:return None
   c=self.conds88[k];return s.vars.get(norm(c['parent']))==c['value']
  return eval_condition(text,lambda x:self.resolve_name(s,x),c88)
 def simple(self,n,s,p):
  k=n['type'];a=n.get('args','');ln=n['start_line'];self.event(s,'AST_NODE',program=p,line=ln,node_type=k,start_line=n['start_line'],end_line=n['end_line'])
  if k=='MOVE':
   m=re.match(r'(.+?)\s+TO\s+(.+)$',a,re.I)
   if not m:raise RuntimeError('UNSUPPORTED_AST_MOVE')
   srcx=re.sub(r'^([+-])\s+(\d)',r'\1\2',m.group(1).strip())
   if getattr(self,'memoria_bytes',False) and self.move_bytes(s,p,ln,srcx,m.group(2)):return
   # LENGTH OF X é o tamanho do item (val), não o campo LENGTH qualificado por X
   z=self.resolve_name(s,srcx) if re.match(r'^[A-Z0-9-]+\s*\(|^[A-Z0-9-]+\s+(?:OF|IN)\s+[A-Z0-9-]+$',srcx,re.I) and not re.match(r'^LENGTH\s+OF\s',srcx,re.I) else (self.resolve_name(s,srcx) if norm(srcx) in getattr(self,'aliases',{}) else val(srcx,s))   # nome de REDEFINES: lido pelo campo base
   # receptores podem ser qualificados (CAMPO OF GRUPO) e/ou ter subscrito/refmod
   ls=getattr(self,'_link_stack',None);il=getattr(self,'init_leaves',{})
   if ls and ls[-1]['group']:
    fr=ls[-1];sn=norm(srcx.split('(')[0].split()[0]);rn=norm(re.findall(r'[A-Z0-9-]+',m.group(2))[0]) if re.findall(r'[A-Z0-9-]+',m.group(2)) else ''
    if sn=='DFHCOMMAREA' and rn in il:  # entrada: DFHCOMMAREA -> área de trabalho do chamado
     for n,_ in il[rn]:
      if n in fr['in']:self.assign(s,f"{n.replace('_','-')} OF {rn.replace('_','-')}",fr['in'][n],p,ln,'COMMAREA_IN')
    elif rn=='DFHCOMMAREA' and sn in il:  # saída: área de trabalho do chamado -> DFHCOMMAREA
     fr['out']={n:self.resolve_name(s,f"{n.replace('_','-')} OF {sn.replace('_','-')}") for n,_ in il[sn] if n in self.ambiguous}
   og=getattr(self,'occ_groups',{});handled=set()
   if og:
    src_tab=og.get(norm(srcx));fig=FIGURATIVE.get(srcx.upper()) if srcx.upper() in FIGURATIVE else None
    for q in re.findall(r'[A-Z0-9-]+',m.group(2),re.I):
     tg=og.get(norm(q))
     if tg and (src_tab or fig is not None):
      size=self.arrays.get(tg,{}).get('size') or 0;cur=s.vars.get(src_tab,[]) if src_tab else [];cur=cur if isinstance(cur,(list,tuple)) else []
      for i in range(1,size+1):self.assign(s,f"{tg.replace('_','-')}({i})",(cur[i-1] if i<=len(cur) else 0) if src_tab else fig,p,ln,'MOVE_GROUP',m.group(1))
      handled.add(q)
   receivers=re.findall(r'[A-Z0-9-]+(?:\s+(?:OF|IN)\s+[A-Z0-9-]+)?(?:\s*\(\s*[A-Z0-9-]+\s*(?::\s*[A-Z0-9-]+\s*)?\))?',m.group(2),re.I)
   kg=self.canon(norm(srcx));lvg=il.get(kg);img=self.de_area(s,srcx) if lvg and not (len(lvg)==1 and lvg[0][0]==kg) and re.match(r'^[A-Z][A-Z0-9-]*$',srcx,re.I) else None
   for q in receivers:
    if q in handled:continue
    self.assign(s,' '.join(q.split()) if re.search(r'\s(?:OF|IN)\s',q,re.I) and '(' not in q else re.sub(r'\s+','',q),z,p,ln,'MOVE',m.group(1))
    if img is not None:   # grupo movido para uma área: a área guarda também os campos de origem (lidos de volta pelo PUT CONTAINER e pelo MQPUT)
     self._imagens=getattr(self,'_imagens',{});self._imagens[self.canon(norm(q))]=(s.vars.get(self.canon(norm(q))),img)
  elif k=='INITIALIZE':
   # receptor com subscrito (GRUPO(I) ou GRUPO (I)): só a ocorrência I de cada elementar do grupo; o subscrito não é receptor
   alvo_sub=re.findall(r'([A-Z][A-Z0-9-]*)\s*\(\s*([A-Z0-9-]+)\s*\)',a,re.I);subs={norm(x) for _,x in alvo_sub}
   for q,sub in alvo_sub:
    for lf,z in (getattr(self,'init_leaves',{}).get(norm(q)) or [(norm(q),0)]):
     try:self.assign(s,f"{lf.replace('_','-')}({sub})",z,p,ln,'INITIALIZE')
     except RuntimeError as e:   # índice fora do OCCURS (no mainframe grava fora da tabela): registra e segue, como antes
      if 'OCCURS_BOUND_EXCEEDED' not in str(e):raise
      self.event(s,'INITIALIZE_FORA_DO_OCCURS',program=p,line=ln,target=lf,index=self.resolve_name(s,sub))
   a2=re.sub(r'([A-Z][A-Z0-9-]*)\s*\(\s*[A-Z0-9-]+\s*\)','',a,flags=re.I)
   ws=a2.split();names=[w for i,w in enumerate(ws) if re.match(r'^[A-Z][A-Z0-9-]*$',w,re.I) and not (i and ws[i-1].upper() in ('OF','IN')) and w.upper() not in ('OF','IN','REPLACING','WITH','TO','BY','ALL','DATA') and norm(w) not in subs]
   for q in names:
    for lf,z in (getattr(self,'init_leaves',{}).get(norm(q)) or [(norm(q),0)]):self.assign(s,lf,z,p,ln,'INITIALIZE')
  elif k=='COMPUTE':
   m=re.match(r'([A-Z0-9-]+)\s*=\s*(.+)',a,re.I)
   if not m:raise RuntimeError('UNSUPPORTED_AST_COMPUTE')
   self.assign(s,m.group(1),expr(m.group(2),s),p,ln,'COMPUTE',m.group(2))
  elif k=='ADD':
   m=re.match(r'(.+?)\s+TO\s+([A-Z0-9-]+)',a,re.I);self.assign(s,m.group(2),cobnum(s.vars.get(norm(m.group(2)),0))+cobnum(val(m.group(1),s)),p,ln,'ADD')
  elif k=='SUBTRACT':
   m=re.match(r'(.+?)\s+FROM\s+([A-Z0-9-]+)',a,re.I);self.assign(s,m.group(2),cobnum(s.vars.get(norm(m.group(2)),0))-cobnum(val(m.group(1),s)),p,ln,'SUBTRACT')
  elif k=='MULTIPLY':
   m=re.match(r'(.+?)\s+BY\s+([A-Z0-9-]+)',a,re.I);self.assign(s,m.group(2),cobnum(s.vars.get(norm(m.group(2)),0))*cobnum(val(m.group(1),s)),p,ln,'MULTIPLY')
  elif k=='DIVIDE':
   m=re.match(r'([A-Z0-9-]+)\s+BY\s+(.+?)\s+GIVING\s+([A-Z0-9-]+)',a,re.I)
   if not m:raise RuntimeError('UNSUPPORTED_AST_DIVIDE')
   self.assign(s,m.group(3),cobnum(val(m.group(1),s))/cobnum(val(m.group(2),s)),p,ln,'DIVIDE')
  elif k=='SET':
   m=re.match(r'([A-Z0-9-]+)\s+(UP|DOWN)\s+BY\s+(.+)',a,re.I)
   if m:
    cur=cobnum(s.vars.get(norm(m.group(1)),0));delta=cobnum(val(m.group(3),s));self.assign(s,m.group(1),cur+(delta if m.group(2).upper()=='UP' else -delta),p,ln,'SET_INDEX')
   else:
    m=re.match(r'(.+?)\s+TO\s+(.+)',a,re.I)
    if not m:raise RuntimeError('UNSUPPORTED_SET')
    rhs=m.group(2).strip();z=True if rhs.upper()=='TRUE' else False if rhs.upper()=='FALSE' else val(rhs,s)
    receivers=re.findall(r'[A-Z0-9-]+(?:\s*\([^)]*\))?',m.group(1),re.I)
    if not receivers:raise RuntimeError('UNSUPPORTED_SET')
    for receiver in receivers:
     rn=re.sub(r'\s+','',receiver);c=self.conds88.get(norm(rn))
     if rhs.upper()=='TRUE' and c:self.assign(s,c['parent'],c['value'],p,ln,'SET_88')
     else:self.assign(s,rn,z,p,ln,'SET')
  elif k=='CALL':
   m=re.match(r'[\'"]?([A-Z0-9-]+)',a,re.I)
   if not m:raise RuntimeError('UNSUPPORTED_AST_CALL')
   q=m.group(1).upper()
   if q in MQI and ('mq' in getattr(self,'scenario',{}) or getattr(self,'mq_backend',None)) and q not in self.programs:   # IBM MQ simulado pelas filas do cenário, ou o de verdade (mq_backend)
    us=re.search(r'\bUSING\b(.*)$',a,re.I|re.S);args=[x for x in re.findall(r'[A-Z0-9-]+(?:\s+(?:OF|IN)\s+[A-Z0-9-]+)?',us.group(1) if us else '',re.I) if x.upper() not in ('BY','REFERENCE','CONTENT','VALUE')]
    self.event(s,'PROGRAM_CALL',program=q,mode='MQ',caller=p,line=ln);self.mq_call(s,p,ln,q,args);return
   self.event(s,'PROGRAM_CALL',program=q,mode='MOCK' if q in self.mocks else 'REAL',caller=p,line=ln);self.execute(q,s)
  elif k in ('GOBACK','STOP'):raise StopRun()
  elif k in ('CONTINUE','DISPLAY','EXIT','NEXT'):pass  # NEXT SENTENCE: o IF costuma terminar na frase, então segue para o próximo comando
  elif k=='GO':
   tk=[x for x in (n.get('arg_tokens') or []) if x[0]!='PUNCT']
   alvo=[x[1].upper() for x in tk if x[1].upper() not in ('TO',)]
   if not alvo or any(x[1].upper()=='DEPENDING' for x in tk):raise RuntimeError('UNSUPPORTED_AST_GO')
   self.event(s,'GO_TO',program=p,line=ln,target=alvo[0]);raise GoTo(alvo[0])
  elif k=='ACCEPT':self.accept(n,s,p)
  elif k=='STRING':
   m=re.search(r'(.+?)\s+INTO\s+([A-Z0-9-]+)',a,re.I)
   if not m:raise RuntimeError('UNSUPPORTED_AST_STRING')
   # cada grupo de emissores termina no seu DELIMITED BY (SIZE = inteiro; SPACE = até o primeiro espaço); um grupo pode ter vários emissores
   vals=[]
   for grupo,delim in re.findall(r'(.+?)\s+DELIMITED\s+BY\s+(SIZE|SPACES?)(?:\s+|$)',m.group(1)+' ',flags=re.I|re.S) or [(m.group(1),'SIZE')]:
    for x in re.findall(r"'(?:[^']|'')*'|\"[^\"]*\"|[A-Z0-9][A-Z0-9-]*(?:\s*\([^)]*\))?",grupo,re.I):
     v=str(val(x,s)) if x[0] in "'\"" else str(self.resolve_name(s,x))
     vals.append(v.split(' ')[0] if delim.upper().startswith('SPACE') else v)
   self.assign(s,m.group(2),''.join(vals),p,ln,'STRING',m.group(1))
  else:raise RuntimeError('UNSUPPORTED_AST_'+k)
 def accept(self,n,s,p):
  """ACCEPT de campo de tela (preenche a variável do USING/TO da SCREEN SECTION com a próxima entrada do cenário em 'accept') ou ACCEPT x FROM ESCAPE KEY (próxima tecla de 'teclas'; ESC = 2 quando a fila acaba)."""
  ln=n['start_line'];tk=[x[1].upper() for x in (n.get('arg_tokens') or [])]
  if '(' in tk:tk=tk[tk.index(')')+1:] if ')' in tk else tk  # ACCEPT (linha, coluna) campo
  alvo=tk[0] if tk else ''
  if 'ESCAPE' in tk:
   v=self.keys_q.pop(0) if self.keys_q else 2;self.assign(s,alvo,v,p,ln,'ACCEPT_KEY');self.event(s,'ACCEPT',program=p,line=ln,kind='KEY',variable=alvo,value=v);return
  var=getattr(self,'fm',{}).get('screen',{}).get(alvo,alvo);q=self.accept_q.get(norm(var))
  if q:
   v=q.pop(0);self.assign(s,var,v,p,ln,'ACCEPT',alvo);self.event(s,'ACCEPT',program=p,line=ln,kind='FIELD',variable=var,value=v)
  else:self.event(s,'ACCEPT',program=p,line=ln,kind='FIELD',variable=var,value=None)
 def cics(self,n,s,p):
  cmd=n.get('command','').strip();op=(cmd.split()[0] if cmd else '').upper();ln=n['start_line']
  def arg(name):
   m=re.search(r'\b'+re.escape(name)+r'\s*\((.*?)\)',cmd,re.I)
   if not m:return None
   x=m.group(1).strip()
   if len(x)>1 and x[0] in "'\"" and x[-1]==x[0]:return x[1:-1]
   return self.resolve_name(s,x) if re.match(r'^[A-Z0-9-]+(?:\s+(?:OF|IN)\s+[A-Z0-9-]+)?$',x,re.I) else val(x,s)
  self.event(s,'CICS_EXECUTE',program=p,line=ln,command=cmd,operation=op)
  fx=(getattr(self,'scenario',{}).get('cics_status',{}).get(f'{p}:{ln}',{}))
  self.assign(s,'EIBRESP',fx.get('EIBRESP',0),p,ln,'CICS_STATUS');self.assign(s,'EIBRESP2',fx.get('EIBRESP2',0),p,ln,'CICS_STATUS')
  if op in ('LINK','XCTL'):
   target=arg('PROGRAM')
   if target:
    q=str(target).strip().upper()
    if fx.get('EIBRESP',0):   # LINK com resposta de erro no cenário (ex.: PGMIDERR): o programa chamado não é executado
     self.event(s,'CICS_LINK_FALHOU',program=q,caller=p,line=ln,resp=fx.get('EIBRESP'))
    elif q in self.programs or q in self.mocks or q in getattr(self,'nativos',{}):
     # COMMAREA: o mesmo bloco físico tem nomes de grupo diferentes no chamador e no chamado (WRK-AREA-X x WRK-DFHCOMMAREA);
     # os campos de nome ambíguo (guardados qualificados) são copiados na ida e na volta pelo nome elementar
     cm=re.search(r'COMMAREA\s*\(\s*([A-Z0-9-]+)',cmd,re.I);frame={'group':norm(cm.group(1)) if cm else None,'in':{},'out':None}
     if frame['group'] and q in self.programs:
      for n,_ in getattr(self,'init_leaves',{}).get(frame['group'],[]):
       if n in self.ambiguous:frame['in'][n]=self.resolve_name(s,f"{n.replace('_','-')} OF {frame['group'].replace('_','-')}")
     self._link_stack=getattr(self,'_link_stack',[]);self._link_stack.append(frame)
     cnl=re.search(r'\bCHANNEL\s*\(',cmd,re.I);self._canais=getattr(self,'_canais',[]);self._canais.append(str(arg('CHANNEL')).strip() if cnl else None)
     # EIBCALEN do chamado: LENGTH do comando ou o tamanho da COMMAREA; sem COMMAREA, zero (LINK com canal). Volta ao do chamador no retorno.
     calen_ant=s.vars.get('EIBCALEN',0)
     if q in self.programs:
      ln_arg=arg('LENGTH') if re.search(r'\bLENGTH\s*\(',cmd,re.I) else None
      calen=ln_arg if isinstance(ln_arg,int) and ln_arg>0 else (getattr(s,'tamanhos',{}).get(cm.group(1).upper(),0) if cm else 0)
      self.assign(s,'EIBCALEN',calen,p,ln,'CICS_LINK_EIBCALEN')
     # WORKING-STORAGE por programa (ws_por_programa): no CICS o programa chamado por LINK tem a sua área de trabalho; só a COMMAREA
     # (os campos do grupo informado em COMMAREA, pelo nome) e os campos EIB passam. Na volta, a memória do chamador volta e só os
     # campos da COMMAREA trazem o que o chamado gravou. Mock e programa nativo continuam vendo a memória do chamador.
     isolar=getattr(self,'ws_por_programa',False) and q in self.programs
     if isolar:
      area=self.nomes_da_area(frame['group']) if frame['group'] else set()
      passa=lambda k:isinstance(k,str) and (k.startswith(('EIB','_')) or k.split('.')[-1] in area or k.split('.')[0]==frame['group'])   # noqa: E731
      chamador=dict(s.vars);s.vars.clear();s.vars.update({k:v for k,v in chamador.items() if passa(k)})
     try:self.execute(q,s)
     finally:
      self._link_stack.pop();self._canais.pop()
      if isolar:
       volta={k:v for k,v in s.vars.items() if passa(k) and not k.startswith('EIB')};s.vars.clear();s.vars.update(chamador);s.vars.update(volta)
     if q in self.programs:self.assign(s,'EIBCALEN',calen_ant,p,ln,'CICS_LINK_EIBCALEN')
     if q in self.programs:  # EIBRESP depois do LINK é o do próprio LINK, não o do último comando do chamado
      self.assign(s,'EIBRESP',fx.get('EIBRESP',0),p,ln,'CICS_STATUS');self.assign(s,'EIBRESP2',fx.get('EIBRESP2',0),p,ln,'CICS_STATUS')
     if frame['out']:
      for n,v in frame['out'].items():self.assign(s,f"{n.replace('_','-')} OF {frame['group'].replace('_','-')}",v,p,ln,'CICS_COMMAREA_RETURN')
    elif getattr(self,'pgmiderr',False):   # região com programas instalados (CSD): programa não definido = PGMIDERR, o LINK não executa
     self.assign(s,'EIBRESP',RESP_CICS['PGMIDERR'],p,ln,'CICS_STATUS');self.event(s,'CICS_LINK_FALHOU',program=q,caller=p,line=ln,resp=RESP_CICS['PGMIDERR'])
    else:
     self.event(s,'CICS_EXTERNAL_PROGRAM',program=q,caller=p,line=ln)
     fxout=getattr(self,'scenario',{}).get('cics_link_outputs',{}).get(f'{p}:{ln}',{})
     for fk,fv in fxout.items():self.assign(s,fk,fv,p,ln,'CICS_LINK_OUTPUT')
   if op=='XCTL':raise StopRun()
  elif op=='RETURN':raise StopRun()
  elif op=='ASKTIME':self.assign(s,re.search(r'ABSTIME\s*\((.*?)\)',cmd,re.I).group(1),'2000-01-01T00:00:00',p,ln,'CICS_ASKTIME')
  elif op=='FORMATTIME':
   for nm in ('YYYYMMDD','DATE','TIME'):
    m=re.search(nm+r'\s*\((.*?)\)',cmd,re.I)
    if m:self.assign(s,m.group(1),'20000101' if nm!='TIME' else '000000',p,ln,'CICS_FORMATTIME')
  elif op=='ASSIGN':
   for key,var in re.findall(r'([A-Z][A-Z0-9-]+)\s*\((.*?)\)',cmd,re.I):self.assign(s,var,0,p,ln,'CICS_ASSIGN')
  elif op=='GETMAIN':
   m=re.search(r'(?:SET|DATA)\s*\((.*?)\)',cmd,re.I)
   if m:self.assign(s,m.group(1),'MEMORY-1',p,ln,'CICS_GETMAIN')
  elif op=='FREEMAIN':pass
  elif op=='READQ':
   m=re.search(r'INTO\s*\((.*?)\)',cmd,re.I)
   if m:self.assign(s,m.group(1),0,p,ln,'CICS_READQ')
  elif op=='WRITEQ':
   m=re.search(r'FROM\s*\(\s*([A-Z0-9-]+)',cmd,re.I);fila=arg('QUEUE')
   self.event(s,'CICS_WRITEQ',program=p,line=ln,queue=str(fila or '').strip(),dados=self.area_texto(s,m.group(1)) if m else '')
  elif op=='DELETEQ':pass
  elif op in ('GET','PUT') and re.search(r'\bCONTAINER\s*\(',cmd,re.I):self.container(s,p,ln,cmd,op,arg)
  elif op=='RETRIEVE':
   # dados do START (no disparo pelo monitor de gatilho do MQ, a mensagem de disparo): cenário 'cics_retrieve'; sem ele, ENDDATA
   m=re.search(r'INTO\s*\(\s*([A-Z0-9-]+)',cmd,re.I);dados=self.scenario.get('cics_retrieve')
   if dados is None:self.assign(s,'EIBRESP',RESP_CICS['ENDDATA'],p,ln,'CICS_STATUS')
   elif m:self.para_area(s,m.group(1),dados,p,ln,'CICS_RETRIEVE')
  elif op=='SYNCPOINT':
   # confirma (ou desfaz, com ROLLBACK) a unidade de trabalho: as mensagens MQ lidas e gravadas em syncpoint
   rb=bool(re.search(r'\bROLLBACK\b',cmd,re.I));self.event(s,'CICS_SYNCPOINT',program=p,line=ln,rollback=rb)
   if hasattr(s.db2,'syncpoint'):s.db2.syncpoint(rb)   # DB2 de verdade: COMMIT/ROLLBACK da unidade de trabalho
   self.mq_syncpoint(s,rb)
  else:raise RuntimeError('UNSUPPORTED_AST_EXEC_CICS_'+op)
  m=re.search(r'\bRESP\s*\(\s*([A-Z0-9-]+)\s*\)',cmd,re.I)   # RESP(x)/RESP2(y): o código do comando vai para a variável do programa
  if m:self.assign(s,m.group(1),s.vars.get('EIBRESP',0),p,ln,'CICS_RESP')
  m=re.search(r'\bRESP2\s*\(\s*([A-Z0-9-]+)\s*\)',cmd,re.I)
  if m:self.assign(s,m.group(1),s.vars.get('EIBRESP2',0),p,ln,'CICS_RESP')
 def para_area(self,s,area,dados,p,ln,src):
  """Dados que chegam numa área: num grupo, dict = campos por nome (os elementares de mesmo nome recebem o valor); numa área elementar
  (um buffer), o conteúdo inteiro, como veio (a mensagem passa adiante sem ser desmontada)."""
  k=self.canon(norm(area));lv=getattr(self,'init_leaves',{}).get(k);grupo=bool(lv) and not (len(lv)==1 and lv[0][0]==k)
  if isinstance(dados,dict) and grupo:
   for fk,fv in dados.items():self.assign(s,fk,copy.deepcopy(fv),p,ln,src)
  else:self.assign(s,area,dados,p,ln,src)
 # ---- memória em bytes nas fronteiras (memoria_bytes): fila, container e MOVE entre grupo e área conversam por texto, no layout do grupo
 def layout_de(self,nome):
  p,dm=getattr(self,'_dm_atual',None) or (None,None)
  if not dm:return None
  cache=_LAYOUTS;k=(self.programs.get(p,p),self.canon(norm(nome)).replace('_','-'))   # um layout por fonte e grupo no processo
  if k not in cache:
   import cobol_layout_codec as codec
   lay=codec.layout(dm['items'],k[1]);cache[k]=lay if lay and not (len(lay)==1 and lay[0][0]=='E' and lay[0][1]==k[1]) else None   # elementar: sem layout
  return cache[k]
 def nomes_da_area(self,grupo):
  """Nomes (normalizados) do grupo e de tudo o que está abaixo dele no programa em execução: grupos, subgrupos e elementares."""
  _p,dm=getattr(self,'_dm_atual',None) or (None,None)
  its=(dm or {}).get('items',[]);g=grupo.replace('_','-').upper()
  i=next((k for k,x in enumerate(its) if x['name']==g and x['level'] not in (66,88)),None)
  if i is None:return {norm(g)}|{n for n,_ in getattr(self,'init_leaves',{}).get(grupo,[])}
  out={norm(g)};j=i+1
  while j<len(its) and (its[j]['level'] in (66,88) or its[j]['level']>its[i]['level']) and its[j]['level']!=77:
   out.add(norm(its[j]['name']));j+=1
  return out
 def linkage_atual(self):
  """Itens da LINKAGE SECTION do programa em execução (a COMMAREA e o que está dentro dela)."""
  p,dm=getattr(self,'_dm_atual',None) or (None,None)
  cache=_LINKAGE;chave=self.programs.get(p,p)
  if chave not in cache:
   txt=read_source(self.programs[p]) if p in self.programs else ''
   m=re.search(r'^.{6}\s*LINKAGE\s+SECTION\.(.*?)^.{6}\s*PROCEDURE\s+DIVISION',txt,re.I|re.S|re.M)
   cache[chave]=set(re.findall(r'^.{6}\s*\d\d\s+([A-Z0-9][A-Z0-9-]*)',m.group(1),re.I|re.M)) if m else set()
   cache[chave]={x.upper() for x in cache[chave]}
  return cache[chave]
 def area_texto(self,s,area):
  """Texto de uma área: grupo = os elementares no layout em bytes; elementar = o conteúdo."""
  lay=self.layout_de(area) if getattr(self,'memoria_bytes',False) else None
  if lay is None:return str(self.resolve_name(s,area))
  import cobol_layout_codec as codec
  return codec.codificar(lay,lambda n,i:self.resolve_name(s,n if i is None else f'{n}({i})'),lambda n:s.vars.get(norm(n),''))
 def texto_para_area(self,s,area,texto,p,ln,src):
  lay=self.layout_de(area)
  if lay is None:self.assign(s,area,texto,p,ln,src);return
  import cobol_layout_codec as codec
  BaseRuntime.assign(self,s,self.canon(norm(area)),texto,p,ln,src)
  codec.decodificar(lay,texto,lambda n,i,v:self.assign(s,n if i is None else f'{n}({i})',v,p,ln,src+'_CAMPO'),
                    lambda n,i:self.resolve_name(s,n if i is None else f'{n}({i})'),lambda n,v:BaseRuntime.assign(self,s,norm(n),v,p,ln,src+'_AREA'))
 def move_bytes(self,s,p,ln,srcx,dest):
  """MOVE com grupo de um dos lados: o grupo de origem vira texto e o grupo de destino recebe o texto pelo layout (como o MOVE de bytes).
  MOVE de figurativa (SPACES, ZEROS...) e de elementar para elementar seguem o caminho normal. Devolve True quando tratou o MOVE."""
  if srcx.upper() in FIGURATIVE or srcx.upper().startswith('ALL '):return False
  # COMMAREA (itens da LINKAGE SECTION): o runtime compartilha a área pelo nome entre chamador e chamado; o MOVE dela segue o caminho
  # normal (cópia dos campos qualificados na ida e na volta do LINK), não a conversão em bytes
  lk=self.linkage_atual()
  base=lambda x:norm(re.findall(r'[A-Z0-9-]+',x,re.I)[0]).replace('_','-') if re.findall(r'[A-Z0-9-]+',x,re.I) else ''   # noqa: E731
  if base(srcx) in lk or any(base(q) in lk for q in re.split(r'\s*,\s*|\s+(?=[A-Z])',dest.strip()) if q):return False
  srcx=re.sub(r'LENGTH\s+OF\s+([A-Z0-9-]+)',lambda mm:str(s.tamanhos.get(mm.group(1).upper(),0)),srcx,flags=re.I)
  simples=lambda x:re.fullmatch(r'[A-Z][A-Z0-9-]*',x.strip(),re.I) is not None   # noqa: E731
  rec=re.findall(r'[A-Z0-9-]+(?:\s+(?:OF|IN)\s+[A-Z0-9-]+)?(?:\s*\(\s*[A-Z0-9-]+\s*(?::\s*[A-Z0-9-]+\s*)?\))?',dest,re.I)
  src_grupo=simples(srcx) and self.layout_de(srcx) is not None
  dst_grupo=[q for q in rec if simples(q) and self.layout_de(q) is not None]
  if not src_grupo and not dst_grupo:return False
  if src_grupo:txt=self.area_texto(s,srcx)
  else:
   v=self.resolve_name(s,srcx) if re.match(r'^[A-Z0-9-]+\s*\(|^[A-Z0-9-]+\s+(?:OF|IN)\s+[A-Z0-9-]+$|^[A-Z][A-Z0-9-]*$',srcx,re.I) else val(srcx,s)
   if not isinstance(v,str) or not v:return False   # texto vazio (área nunca gravada) não é distribuído
   txt=v
  for q in rec:
   if q in dst_grupo:self.texto_para_area(s,q,txt,p,ln,'MOVE_BYTES')
   else:self.assign(s,' '.join(q.split()) if re.search(r'\s(?:OF|IN)\s',q,re.I) and '(' not in q else re.sub(r'\s+','',q),txt,p,ln,'MOVE',srcx)
  return True
 def de_area(self,s,area):
  """Conteúdo de uma área: grupo = campos elementares por nome (como a COMMAREA passa entre programas); elementar = o valor."""
  k=self.canon(norm(area));lv=getattr(self,'init_leaves',{}).get(k)
  if lv and not (len(lv)==1 and lv[0][0]==k):return {n.replace('_','-'):copy.deepcopy(s.vars[n]) for n,_ in lv if n in s.vars}
  img=getattr(self,'_imagens',{}).get(k)
  if img and img[0]==s.vars.get(k):return copy.deepcopy(img[1])   # área que recebeu um grupo e não mudou desde então
  return copy.deepcopy(self.resolve_name(s,area))
 def container(self,s,p,ln,cmd,op,arg):
  """PUT/GET CONTAINER: canal do comando (CHANNEL), ou o canal recebido no LINK, ou o canal da transação; o nome do container pode vir em variável.
  O conteúdo é guardado por campo (como a COMMAREA); o cenário pode trazer containers iniciais em 'cics_containers' (por nome do container)."""
  cn=str(arg('CONTAINER')).strip();ch=re.search(r'\bCHANNEL\s*\(',cmd,re.I)
  canal=str(arg('CHANNEL')).strip() if ch else ((getattr(self,'_canais',None) or [None])[-1] or 'DFHTRANSACTION')
  self._containers=getattr(self,'_containers',{});cs=self._containers.setdefault(canal,{})
  if op=='PUT':
   m=re.search(r'\bFROM\s*\(\s*([A-Z0-9-]+)',cmd,re.I)
   if getattr(self,'memoria_bytes',False):   # container guarda bytes: o grupo vira texto pelo layout; FLENGTH corta no tamanho informado
    txt=self.area_texto(s,m.group(1)) if m else '';fl=arg('FLENGTH') if re.search(r'\bFLENGTH\s*\(',cmd,re.I) else None
    cs[cn]=txt[:int(fl)].ljust(int(fl)) if isinstance(fl,(int,float)) and fl>0 else txt
   else:cs[cn]=self.de_area(s,m.group(1)) if m else ''
   self.event(s,'CICS_PUT_CONTAINER',program=p,line=ln,channel=canal,container=cn);return
  m=re.search(r'\bINTO\s*\(\s*([A-Z0-9-]+)',cmd,re.I)
  do_cenario=cn not in cs;dados=cs.get(cn,self.scenario.get('cics_containers',{}).get(cn))
  self.event(s,'CICS_GET_CONTAINER',program=p,line=ln,channel=canal,container=cn,found=dados is not None)
  if dados is None:self.assign(s,'EIBRESP',RESP_CICS['CONTAINERERR'],p,ln,'CICS_STATUS');return
  if do_cenario and isinstance(dados,dict):   # conteúdo dado pelo cenário: os campos informados vão para as variáveis de mesmo nome
   for fk,fv in dados.items():self.assign(s,fk,copy.deepcopy(fv),p,ln,'CICS_GET_CONTAINER_FIELD')
  elif m and getattr(self,'memoria_bytes',False) and isinstance(dados,str):
   self.texto_para_area(s,m.group(1),dados,p,ln,'CICS_GET_CONTAINER')
   fl=re.search(r'\bFLENGTH\s*\(\s*([A-Z0-9-]+)',cmd,re.I)
   if fl:self.assign(s,fl.group(1),len(dados),p,ln,'CICS_FLENGTH')   # FLENGTH devolve o tamanho do container
  elif m:self.para_area(s,m.group(1),dados,p,ln,'CICS_GET_CONTAINER')
 # ---- IBM MQ (MQI): filas do cenário em 'mq' = {fila: [mensagem, ...]}; mensagem = dados (dict por campo ou texto) ou {'dados': ..., 'backout': n}
 def mq_call(self,s,p,ln,q,args):
  """CALL 'MQOPEN'/'MQGET'/'MQPUT'/'MQPUT1'/'MQCLOSE' com os parâmetros da MQI na ordem do manual. Leitura e gravação em syncpoint:
  a gravação só aparece na fila no SYNCPOINT; no ROLLBACK a mensagem lida volta para a fila com o contador de backout + 1."""
  if getattr(self,'mq_backend',None):return self.mq_backend.chamar(self,s,p,ln,q,args)
  self._mq=getattr(self,'_mq',None)
  if self._mq is None:self._mq={'filas':{k.strip():[dict(x) if isinstance(x,dict) and 'dados' in x else {'dados':x} for x in v] for k,v in self.scenario.get('mq',{}).items()},'abertas':{},'lidas':[],'gravadas':[],'seq':0}
  mq=self._mq;cc_rc=lambda cc,rc:(self.assign(s,args[-2],cc,p,ln,'MQ_COMPCODE'),self.assign(s,args[-1],rc,p,ln,'MQ_REASON'))   # noqa: E731
  nome_od=lambda od:str(self.resolve_name(s,f'MQOD-OBJECTNAME OF {od}')).strip()   # noqa: E731
  if q=='MQOPEN':
   h=len(mq['abertas'])+1;mq['abertas'][h]=nome_od(args[1]);self.assign(s,args[3],h,p,ln,'MQ_HOBJ');cc_rc(0,0)
  elif q=='MQGET':
   fila=mq['abertas'].get(cobnum(self.resolve_name(s,args[1])));lista=mq['filas'].setdefault(fila,[])
   if not lista:cc_rc(2,2033);self.event(s,'MQ_GET',program=p,line=ln,queue=fila,message=None);return
   msg=lista.pop(0);mq['seq']+=1;msg.setdefault('msg_id',f'MSG{mq["seq"]:06d}');mq['lidas'].append((fila,msg))
   self.assign(s,f'MQMD-MSGID OF {args[2]}',msg['msg_id'],p,ln,'MQ_MD');self.assign(s,f'MQMD-BACKOUTCOUNT OF {args[2]}',msg.get('backout',0),p,ln,'MQ_MD')
   self.para_area(s,args[5],msg['dados'],p,ln,'MQ_GET')
   self.assign(s,args[6],len(msg['dados']) if isinstance(msg['dados'],str) else msg.get('tamanho',999999),p,ln,'MQ_DATALEN');cc_rc(0,0)
   self.event(s,'MQ_GET',program=p,line=ln,queue=fila,message=msg['msg_id'])
  elif q in ('MQPUT','MQPUT1'):
   fila=nome_od(args[1]) if q=='MQPUT1' else mq['abertas'].get(cobnum(self.resolve_name(s,args[1])))
   md=args[2];buf=args[5] if q=='MQPUT1' else args[4]
   msg={'dados':self.de_area(s,buf),'correl_id':str(self.resolve_name(s,f'MQMD-CORRELID OF {md}')).strip()}
   mq['gravadas'].append((fila,msg));cc_rc(0,0);self.event(s,'MQ_PUT',program=p,line=ln,queue=fila,correl_id=msg['correl_id'])
  else:cc_rc(0,0)   # MQCLOSE, MQCONN, MQDISC
 def mq_syncpoint(self,s,rollback):
  if getattr(self,'mq_backend',None):self.mq_backend.syncpoint(rollback);return
  mq=getattr(self,'_mq',None)
  if not mq:return
  if rollback:
   for fila,msg in reversed(mq['lidas']):msg['backout']=msg.get('backout',0)+1;mq['filas'].setdefault(fila,[]).insert(0,msg)
  else:
   for fila,msg in mq['gravadas']:mq['filas'].setdefault(fila,[]).append(msg)
  mq['lidas'],mq['gravadas']=[],[]
 def block(self,b,s,p,labels=None):
  for n in b:
   s.steps+=1
   if s.steps>self.max_steps:raise RuntimeError('MAX_STEPS')
   k=n['type']
   if k=='LABEL':continue
   if k=='IF':
    r=self.condition(n['condition'],s);s.branches.append({'program':p,'line':n['start_line'],'condition':n['condition'],'result':r});self.event(s,'BRANCH_DECISION',program=p,line=n['start_line'],condition=n['condition'],result=r);self.block(n['then'] if r else n['else_body'],s,p,labels)
   elif k=='EVALUATE':
    subj=n['subject'];matched=False;chosen=None
    for wi,w in enumerate(n['whens'],1):
     c=w['condition'];r=(not matched) and (c.upper()=='OTHER' or (self.condition(c,s) if subj.upper()=='TRUE' else _igual_cobol(self.resolve_name(s,subj),val(re.sub(r'^([+-])\s+(\d)',r'\1\2',c.strip()),s))))   # '+ 100': o sinal vem separado do número
     self.event(s,'BRANCH_DECISION',program=p,line=w['start_line'],decision_line=n['start_line'],condition=f'EVALUATE {subj} WHEN {c}',result=r,branch=f'WHEN:{wi}')
     if r:
      chosen=f'WHEN:{wi}';matched=True
      s.branches.append({'program':p,'line':n['start_line'],'condition':f'EVALUATE {subj}','result':chosen})
      # WHENs empilhados (WHEN A WHEN B ... <instruções>) compartilham o corpo do primeiro WHEN seguinte que tem instruções
      body=next((x['body'] for x in n['whens'][wi-1:] if x['body']),[])
      self.block(body,s,p,labels)
    if chosen is None:
     chosen='NO_MATCH'
     s.branches.append({'program':p,'line':n['start_line'],'condition':f'EVALUATE {subj}','result':chosen})
   elif k.startswith('FILE_'):self.file_io(n,s,p,labels)
   elif k=='SEARCH':
    arr=s.vars.get(norm(n['subject']),[]);matched=False
    for ix in range(1,len(arr)+1):
     s.vars['SEARCH_INDEX']=ix
     for w in n['whens']:
      # Replace SUBJECT(index) with current array element through temporary vars when present.
      c=w['condition'];m=re.match(r'([A-Z0-9-]+)\s*\(\s*([A-Z0-9-]+|\d+)\s*\)\s*(=|<>|!=|>|<|>=|<=)\s*(.+)',c,re.I)
      if m:
       left=self.resolve_name(s,m.group(1)+'('+str(ix)+')');right=val(m.group(4),s);op=m.group(3);r={'=':left==right,'<>':left!=right,'!=':left!=right,'>':left>right,'<':left<right,'>=':left>=right,'<=':left<=right}[op]
      else:r=self.condition(c,s)
      self.event(s,'BRANCH_DECISION',program=p,line=w['start_line'],condition='SEARCH '+c,result=r)
      if r:self.block(w['body'],s,p,labels);matched=True;break
     if matched:break
    if not matched:self.block(n.get('at_end',[]),s,p,labels)
   elif k=='EXEC_CICS':
    self.cics(n,s,p)
   elif k=='EXEC_SQL':
    sql='EXEC SQL '+n['sql']+' END-EXEC';before=copy.deepcopy(s.tables)
    om=re.match(r'\s*OPEN\s+([A-Z0-9-]+)',n['sql'],re.I)
    if om and norm(om.group(1)) not in s.db2.decl:
     raw=read_source(self.programs[p])
     fixed='\n'.join((ln[6:72] if len(ln)>=7 and (ln[6:7] not in ('*','/')) else '') for ln in raw.splitlines())
     cm=re.search(r'EXEC\s+SQL\s+DECLARE\s+'+re.escape(om.group(1))+r'\s+CURSOR(?:\s+WITH\s+ROWSET\s+POSITIONING)?\s+FOR\s+(SELECT.*?)\s+END-EXEC',fixed,re.I|re.S)
     if cm:s.db2.decl[norm(om.group(1))]=re.sub(r'\s+',' ',cm.group(1)).strip()
    self.event(s,'SQL_EXECUTE',program=p,line=n['start_line'],sql=sql,host_variables=dict(s.vars));r=s.db2.execute(sql);s.sql.append({'program':p,'line':n['start_line'],'sql':sql,'result':r});self.event(s,'SQL_RESULT',program=p,line=n['start_line'],operation=r.get('operation'),sqlcode=r.get('sqlcode'),affected=r.get('affected'),**({'erro':r['erro']} if r.get('erro') else {}))
    if r.get('status')!='OK':raise RuntimeError('UNSUPPORTED_SQL')
    for q,z in r.get('into',{}).items():self.assign(s,q,z,p,n['start_line'],'SQL_INTO',sql)
    self.sql_indicators(s,n,r,p)
    sqlfx=getattr(self,'scenario',{}).get('db2_status',{}).get(f"{p}:{n['start_line']}")
    sqlcode=(sqlfx.get('SQLCODE') if isinstance(sqlfx,dict) and 'SQLCODE' in sqlfx else r.get('sqlcode'))
    self.assign(s,'SQLCODE',sqlcode,p,n['start_line'],'SQL_STATUS')
    if 'row_count' in r:self.assign(s,'SQLERRD(3)',r.get('row_count',0),p,n['start_line'],'SQL_ROW_COUNT')
    elif r.get('affected') is not None:self.assign(s,'SQLERRD(3)',r['affected'],p,n['start_line'],'SQL_ROW_COUNT')   # INSERT/UPDATE/DELETE: linhas afetadas
    if isinstance(sqlfx,dict) and 'SQLWARN0' in sqlfx:self.assign(s,'SQLWARN0',sqlfx['SQLWARN0'],p,n['start_line'],'SQL_STATUS')
    if before!=s.tables:
     ch={'program':p,'line':n['start_line'],'operation':r.get('operation'),'table':r.get('table'),'affected':r.get('affected'),'before':before,'after':copy.deepcopy(s.tables)};s.table_changes.append(ch);self.event(s,'TABLE_MUTATION',**ch)
   elif k=='PERFORM':self.perform_node(n,s,p,labels)
   else:self.simple(n,s,p)

 def file_io(self,n,s,p,labels):
  """OPEN/CLOSE/READ/WRITE/REWRITE/DELETE/START sobre os arquivos do cenário ('files'), com o que o SELECT/FD do programa declara:
  chave primária, FILE STATUS e registro. Arquivo que não existe no cenário abre com status 30 (OPEN OUTPUT cria); READ indexado sem NEXT lê pela chave do registro;
  WRITE com chave repetida devolve 22; READ/REWRITE/DELETE de chave inexistente devolvem 23. 'file_status' ({"PROG:linha": "99"}) força o status de uma operação."""
  op=n['type'][5:];a=n.get('args','');parts=[x.upper() for x in a.split()];ln=n['start_line'];fm=getattr(self,'fm',{'files':{},'records':{},'screen':{}})
  fr=self.file_runtime;force=self.scenario.get('file_status',{}).get(f'{p}:{ln}')
  def meta(fn):
   m=fm['files'].get(fn,{});f=fr._f(fn)
   if m.get('key') and not f.get('key'):f['key']=m['key']
   if m.get('organization') and f.get('organization')=='SEQUENTIAL':f['organization']=m['organization']
   return m
  def fields(rec):
   return [x for x,_z,_c in self.groups.get(norm(rec),[])] if self.groups.get(norm(rec)) else [x for x,_ in self.init_leaves.get(norm(rec),[])]
  def load(m,rec):
   for k,v in (rec or {}).items():self.assign(s,k,v,p,ln,'FILE_READ',m.get('record'))
  def record_of(m):
   return {x:s.vars.get(norm(x),0) for x in fields(m.get('record'))} if m.get('record') else {}
  res={'file_status':'00'};files=[]
  if op=='OPEN':
   mode=parts[0] if parts else 'INPUT';files=parts[1:]
   for fn in files:
    m=meta(fn)
    if force:res={'file_status':force}
    elif mode=='OUTPUT':
     fr.files[fn]={'organization':m.get('organization','SEQUENTIAL'),'records':[],'key':m.get('key')};res=fr.open(fn,mode)
    elif fn not in fr.files:res={'file_status':'30'}
    else:res=fr.open(fn,mode)
    self._file_done(s,p,ln,op,fn,m,res)
  elif op=='CLOSE':
   files=[x for x in parts if x not in ('WITH','LOCK','NO','REWIND')]
   for fn in files:m=meta(fn);res=fr.close(fn);self._file_done(s,p,ln,op,fn,m,{'file_status':force} if force else res)
  else:
   if op in ('WRITE','REWRITE'):
    fn=fm['records'].get(parts[0],parts[0]);m=meta(fn)
    if force:res={'file_status':force,'invalid_key':True}
    else:res=fr.write(fn,record_of(m)) if op=='WRITE' else fr.rewrite(fn,record_of(m))
   else:
    fn=parts[0];m=meta(fn);kn=m.get('key');f=fr._f(fn)
    if force:res={'file_status':force,'invalid_key':True}
    elif op=='READ':
     keyed=m.get('organization')=='INDEXED' and 'NEXT' not in parts and m.get('access') in ('DYNAMIC','RANDOM') and kn
     res=fr.read_key(fn,self.resolve_name(s,kn)) if keyed else fr.read_next(fn)
     if res.get('record') is not None:
      load(m,res['record'])
      into=[x for i,x in enumerate(parts) if i and parts[i-1]=='INTO']
      if into:self.assign(s,into[0],res['record'],p,ln,'FILE_READ')
    elif op=='DELETE':res=fr.delete(fn,self.resolve_name(s,kn)) if kn else {'file_status':'23','invalid_key':True}
    elif op=='START':
     km=[x for i,x in enumerate(parts) if i and parts[i-1] in ('KEY','IS','>=','>','=') and x not in ('IS',)]
     res=fr.start(fn,self.resolve_name(s,km[-1] if km else kn)) if (km or kn) else {'file_status':'23','invalid_key':True}
   self._file_done(s,p,ln,op,fn,m,res)
  cl=n.get('clauses',{})
  if res.get('at_end'):self.block(cl.get('AT_END',[]),s,p,labels)
  elif res.get('invalid_key'):self.block(cl.get('INVALID_KEY',[]),s,p,labels)
  else:self.block(cl.get('NOT_AT_END',cl.get('NOT_INVALID_KEY',[])),s,p,labels)
 def _file_done(self,s,p,ln,op,fn,m,res):
  st=m.get('status') or self.file_status_map.get(fn.upper())
  if st:self.assign(s,st,res['file_status'],p,ln,'FILE_STATUS')
  self.event(s,'FILE_IO',program=p,line=ln,operation=op,file=fn,result=res)
 def perform_node(self,n,s,p,labels):
  """PERFORM lido pelos tokens do cabeçalho: parágrafo [THRU], n TIMES, [WITH TEST] UNTIL cond e VARYING var FROM a BY b UNTIL cond (fora de linha ou em linha)."""
  sp=perform_spec(n.get('header_tokens') or [],bool(n.get('inline')))
  if sp['after']:raise RuntimeError('UNSUPPORTED_AST_PERFORM')
  def body():
   if n.get('inline'):self.block(n['body'],s,p,labels)
   else:self.perform_paragraphs(sp['target'],sp['end'],s,p,labels)
  guard=0
  def tick():
   nonlocal guard
   guard+=1
   if guard>self.max_steps:raise RuntimeError('MAX_STEPS_PERFORM')
  if sp['varying']:
   q,start,by=sp['varying'];self.assign(s,q,val(start,s),p,n['start_line'],'PERFORM_VARYING_INIT')
   while not self.condition(sp['until'],s):
    tick();body();self.assign(s,q,s.vars.get(norm(q),0)+val(by,s),p,n['start_line'],'PERFORM_VARYING_STEP')
  elif sp['times'] is not None:
   for _ in range(max(0,int(val(sp['times'],s) or 0))):
    tick();body()
  elif sp['until'] is not None:
   if sp['test_after']:
    tick();body()
   while not self.condition(sp['until'],s):
    tick();body()
  elif n.get('inline'):raise RuntimeError('UNSUPPORTED_AST_PERFORM')
  else:body()
 def perform_paragraphs(self,target,end,s,p,labels):
  if labels is None or target not in labels:raise RuntimeError('PERFORM_TARGET_NOT_FOUND '+str(target))
  self.event(s,'ENTER_PERFORM',program=p,target=target,end=end)
  body=self._program_bodies[p]
  start=labels[target];endidx=labels.get(end,start);j=start+1
  fim=next((q for q in range(endidx+1,len(body)) if body[q]['type']=='LABEL'),len(body))  # fim da faixa: próximo parágrafo depois do último
  while j<len(body):
   if j>endidx and body[j]['type']=='LABEL':break
   try:self.block([body[j]],s,p,labels)
   except GoTo as g:
    t=labels.get(g.label)
    if t is None or not (start<=t<fim):raise  # GO TO para fora da faixa sai do PERFORM
    j=t
   j+=1
  self.event(s,'RETURN_PERFORM',program=p,target=target)
 def execute(self,p,s,depth=0):
  p=p.upper()
  if p in self.mocks:return self.mock(p,s)
  if p in getattr(self,'nativos',{}):   # programa sem fonte implementado em Python (lê e grava os campos da área pelo nome)
   self.event(s,'ENTER_PROGRAM',program=p,native=True);s.call_stack.append(p)
   try:self.nativos[p](self,s)
   finally:s.call_stack.pop();self.event(s,'RETURN_PROGRAM',program=p)
   return
  if p not in self.programs:raise RuntimeError('PROGRAM_NOT_FOUND '+p)
  s.executed_programs.add(p);s.call_stack.append(p);self.event(s,'ENTER_PROGRAM',program=p,inputs=dict(s.vars))
  text=read_source(self.programs[p]);dm=_modelo_do_fonte(self.programs[p])   # um modelo de dados por fonte no processo
  saved_tam=getattr(s,'tamanhos',{});saved_dm=getattr(self,'_dm_atual',None);self._dm_atual=(p,dm)
  s.tamanhos=_TamanhoDinamico(self,s,dm.get('sizes',{})) if getattr(self,'memoria_bytes',False) else dm.get('sizes',{})   # LENGTH OF do programa em execução
  # O modelo de dados (88, REDEFINES, OCCURS, RENAMES) é do programa em execução: ativa na entrada e restaura na saída,
  # para que o chamador não passe a enxergar os níveis 88 do programa chamado depois de um CALL/LINK.
  saved_model=(getattr(self,'conds88',{}),getattr(self,'aliases',{}),getattr(self,'arrays',{}),getattr(self,'renames',{}),getattr(self,'ambiguous',set()),getattr(self,'overlays',{}),getattr(self,'groups',{}),getattr(self,'init_leaves',{}),getattr(self,'occ_groups',{}))
  # modelo derivado do programa (88, REDEFINES, OCCURS, folhas de cada grupo): calculado uma vez por fonte no processo, como o programa
  # residente na região; o que depende da tarefa (VALUE iniciais, tabelas por REDEFINES) continua a cada entrada
  chave=self.programs.get(p);deriv=_DERIVADOS.get(chave)
  if deriv:(self.ambiguous,self.conds88,self.aliases,self.arrays,self.renames,self.groups,self.overlays,self.occ_groups,self.init_leaves)=deriv
  else:
   from collections import Counter as _C
   self.ambiguous={norm(n) for n,c in _C(it['name'] for it in dm['items'] if it.get('level')!=88).items() if c>1}
   self.conds88={norm(k):v for k,v in dm['conditions_88'].items()};self.aliases={norm(k):norm(v) for k,v in dm['aliases'].items()};self.arrays={norm(k):v for k,v in dm['arrays'].items()};self.renames={norm(k):v for k,v in dm['renames'].items()}
   self.groups={norm(g):[(norm(n),z,c) for n,z,c in kids] for g,kids in dm.get('groups',{}).items()}
   self.overlays={norm(b):[(norm(n),o,z,c,k) for n,o,z,c,k in kids] for b,kids in dm.get('overlays',{}).items()}
   # INITIALIZE: folhas elementares de cada nome (grupo -> descendentes); numérico vira 0, o resto brancos
   kids={}
   for it in dm['items']:
    if it.get('parent'):kids.setdefault(norm(it['parent']),[]).append(it)
   def leaves(nm,acc,seen=()):
    for it in kids.get(nm,[]):
     if it.get('level')==88 or norm(it['name'])=='FILLER' or it.get('redefines'):continue
     if norm(it['name']) in kids:
      if norm(it['name']) not in seen:leaves(norm(it['name']),acc,seen+(nm,))
     else:acc.append((norm(it['name']),0 if (it.get('picture') or {}).get('category','').startswith('NUMERIC') else ' '))
    return acc
   # grupos cujo único conteúdo é uma tabela OCCURS de elementares (MOVE de grupo copia posição a posição)
   self.occ_groups={}
   for it in dm['items']:
    ks=[k for k in kids.get(norm(it['name']),[]) if k.get('level')!=88 and norm(k['name'])!='FILLER']
    if it.get('level') and it['level']<50 and not it.get('pic') and len(ks)==1 and ks[0].get('occurs') and norm(ks[0]['name']) not in kids:self.occ_groups[norm(it['name'])]=norm(ks[0]['name'])
   self.init_leaves={}
   for it in dm['items']:
    nm=norm(it['name'])
    if it.get('level')==88:continue
    self.init_leaves.setdefault(nm,leaves(nm,[]) if nm in kids else [(nm,0 if (it.get('picture') or {}).get('category','').startswith('NUMERIC') else ' ')])
   _DERIVADOS[chave]=(self.ambiguous,self.conds88,self.aliases,self.arrays,self.renames,self.groups,self.overlays,self.occ_groups,self.init_leaves)
  # COBOL VALUE clauses initialize storage; explicit scenario inputs take precedence.
  for it in dm['items']:
   if it.get('level') not in (66,88) and it.get('value') is not None:
    v=it['value']
    # constantes figurativas no VALUE (ZEROS, SPACES, LOW-VALUES...) viram o valor que representam
    if isinstance(v,str) and v.upper() in FIGURATIVE:v=FIGURATIVE[v.upper()]
    s.vars.setdefault(norm(it['name']),v)
  # tabela montada por REDEFINES de VALUEs: o grupo que redefine e tem filho OCCURS recebe os elementos fatiados da imagem do grupo base
  def tamanho(pic):
   pic=(pic or '').upper();n=0;i=0
   while i<len(pic):
    c=pic[i]
    if c in 'X9AZ':
     if i+1<len(pic) and pic[i+1]=='(':
      j=pic.index(')',i);n+=int(pic[i+2:j]);i=j
     else:n+=1
    i+=1
   return n
  def imagem(nome):
   base=next((it for it in dm['items'] if norm(it['name'])==norm(nome) and not it.get('redefines')),None)
   if base is None:return None
   if base.get('pic'):
    v=base.get('value');v=FIGURATIVE.get(v.upper(),v) if isinstance(v,str) else v
    return (str(v) if v is not None else '').ljust(tamanho(base['pic']))
   out=''
   for k in dm['items']:
    if k.get('parent')==base['name'] and k.get('level')!=88 and k.get('pic'):
     v=k.get('value');v=FIGURATIVE.get(v.upper(),v) if isinstance(v,str) else v
     z=tamanho(k['pic']);out+=((str(v) if v is not None else '').ljust(z)[:z]) if not str(k['pic']).upper().startswith('9') else str(0 if v is None else v).zfill(z)[-z:]
   return out
  for it in dm['items']:
   if it.get('redefines') and not it.get('pic'):
    img=imagem(it['redefines']);off=0
    if img is None:continue
    for k in dm['items']:
     if k.get('parent')!=it['name'] or k.get('level')==88 or not k.get('pic'):continue
     z=tamanho(k['pic']);num=str(k['pic']).upper().startswith('9')
     def fat(a,b):
      x=img[a:b];return (int(x) if x.strip().isdigit() else 0) if num else x
     if k.get('occurs'):s.vars.setdefault(norm(k['name']),[fat(off+q*z,off+(q+1)*z) for q in range(k['occurs'])]);off+=z*k['occurs']
     else:s.vars.setdefault(norm(k['name']),fat(off,off+z));off+=z
  self._fm_cache=getattr(self,'_fm_cache',{});fm=self._fm_cache.get(p)
  if fm is None:fm=file_model(text);self._fm_cache[p]=fm
  saved_fm=getattr(self,'fm',None);self.fm=fm
  ast=self.ast(p);b=ast['body'];self._program_bodies=getattr(self,'_program_bodies',{});self._program_bodies[p]=b;labels={n['name']:i for i,n in enumerate(b) if n['type']=='LABEL'}
  # COBOL program entry executes the first procedure paragraph; later paragraphs are entered by PERFORM/GO TO.
  entry_end=len(b)
  first_label=next((i for i,n in enumerate(b) if n['type']=='LABEL'),None)
  if first_label is not None:
   entry_end=next((i for i in range(first_label+1,len(b)) if b[i]['type']=='LABEL'),len(b))
   entry_block=b[first_label+1:entry_end]
  else:entry_block=b
  def tem_go(x):
   if isinstance(x,dict):return x.get('type')=='GO' or any(tem_go(v) for v in x.values())
   if isinstance(x,list):return any(tem_go(v) for v in x)
   return False
  try:
   if first_label is not None and tem_go(b):
    # programa com GO TO: a execução segue de parágrafo em parágrafo (continuação natural) e o GO TO desvia para o rótulo
    pc=first_label+1
    while True:
     try:
      for j in range(pc,len(b)):self.block([b[j]],s,p,labels)
      break
     except GoTo as g:
      if g.label not in labels:raise RuntimeError('GO_TO_TARGET_NOT_FOUND '+g.label)
      pc=labels[g.label]
   else:self.block(entry_block,s,p,labels)
  except StopRun:pass
  finally:s.tamanhos=saved_tam;self._dm_atual=saved_dm;self.fm=saved_fm;self.conds88,self.aliases,self.arrays,self.renames,self.ambiguous,self.overlays,self.groups,self.init_leaves,self.occ_groups=saved_model
  self.event(s,'RETURN_PROGRAM',program=p,outputs=dict(s.vars));s.call_stack.pop()
