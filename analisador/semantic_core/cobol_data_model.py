from cobol_token_lexer import lex
import re
def V(t):return t.value.upper()
def literal(x):
 if x is None:return None
 if len(x)>1 and x[0] in "'\"" and x[-1]==x[0]:return x[1:-1]
 try:return int(x)
 except:
  try:return float(x)
  except:return x
def picture_info(pic):
 if not pic:return {'category':'GROUP','digits':None,'scale':0,'signed':False}
 p=pic.upper().replace(' ','');signed=p.startswith('S');scale=0
 if 'V' in p:
  right=p.split('V',1)[1];m=re.search(r'9\((\d+)\)',right);scale=int(m.group(1)) if m else right.count('9')
 # posições: cada símbolo repetido (9(4), X(30), -(9)) vale o número entre parênteses; S e V não ocupam posição
 digits=len(re.sub(r'(.)\((\d+)\)',lambda m:m.group(1)*int(m.group(2)),p).replace('S','').replace('V',''))
 return {'category':'ALPHANUMERIC' if 'X' in p else 'NUMERIC','digits':digits or None,'scale':scale,'signed':signed}
def overlays_of(items):
 """REDEFINES de um campo por um grupo de elementares: {base: [(filho, deslocamento, tamanho, categoria)]} (posição em bytes dentro do base)."""
 out={};pics={x['name']:(x.get('pic') or '') for x in items if x['level'] not in (66,88)}
 for i,it in enumerate(items):
  if not it.get('redefines') or it['level'] in (66,88):continue
  base=it['redefines'];pos=0;kids=[]
  bp=pics.get(base,'')[:1]
  if bp not in ('+','-','X'):continue  # idioma do sinal editado à esquerda, ou campo alfanumérico refeito em elementares
  kind='S' if bp in ('+','-') else 'X'
  if it.get('pic'):continue
  for k in items[i+1:]:
   if k['level']<=it['level']:break
   if k['level']==88 or not k.get('pic'):continue
   n=k['picture']['digits'] or 0
   if k['name']!='FILLER':kids.append((k['name'],pos,n,k['picture']['category'],kind))
   pos+=n
  if kids:out.setdefault(base,[]).extend(kids)
 return out
def groups_of(items):
 """Grupos com elementares: {grupo: [(campo, tamanho, categoria)]} (sem REDEFINES/OCCURS), para ler o grupo como texto contínuo."""
 out={}
 for i,it in enumerate(items):
  if it.get('pic') or it['level'] in (66,88) or it['name']=='FILLER' or it.get('redefines') or it.get('occurs'):continue
  kids=[]
  for k in items[i+1:]:
   if k['level']<=it['level']:break
   if k['level']==88 or not k.get('pic') or k.get('redefines') or k.get('occurs'):continue
   kids.append((k['name'],k['picture']['digits'] or 0,k['picture']['category']))
  if kids:out[it['name']]=kids
 return out
def byte_sizes(items):
 """Tamanho em bytes de cada item (LENGTH OF): elementar pela PIC e USAGE (COMP-3 = dígitos/2+1; COMP/BINARY = 2, 4 ou 8),
 grupo = soma dos filhos (REDEFINES não soma), vezes o OCCURS. {nome: tamanho}; nome repetido fica com o primeiro."""
 out={}
 def elem(it):
  d=it['picture']['digits'] or 0;u=it.get('usage')
  if u=='COMP-3':return d//2+1
  if u in ('COMP','BINARY','COMP-4','COMP-5'):return 2 if d<=4 else 4 if d<=9 else 8
  return d
 def tam(i):
  it=items[i]
  if it.get('pic'):n=elem(it);j=i+1
  else:
   n=0;j=i+1
   while j<len(items) and (items[j]['level'] in (66,88) or items[j]['level']>it['level']) and items[j]['level']!=77:
    k=items[j]
    if k['level'] in (66,88):j+=1;continue
    m,fim=tam(j)
    if not k.get('redefines'):n+=m
    j=fim
  return n*(it.get('occurs_max') or it.get('occurs') or 1),j
 i=0
 while i<len(items):
  if items[i]['level'] in (66,88):i+=1;continue
  n,_=tam(i);out.setdefault(items[i]['name'],n);i+=1
 return out
def build_data_model(text):
 t=lex(text);i=0;items=[];stack=[]
 while i<len(t) and not (V(t[i])=='DATA' and i+1<len(t) and V(t[i+1])=='DIVISION'):i+=1
 while i<len(t) and not (V(t[i])=='PROCEDURE' and i+1<len(t) and V(t[i+1])=='DIVISION'):
  if t[i].type=='NUMBER' and str(t[i].value).isdigit() and int(t[i].value) in list(range(1,50))+[66,77,88] and i+1<len(t):
   level=int(t[i].value);name=V(t[i+1]);start=t[i];i+=2;a=[]
   while i<len(t) and t[i].type!='PERIOD':a.append(t[i]);i+=1
   end=t[i] if i<len(t) else (a[-1] if a else start);i+=1 if i<len(t) else 0;vals=[V(x) for x in a]
   def after(k,n=1):
    return V(a[vals.index(k)+n]) if k in vals and vals.index(k)+n<len(a) else None
   pic=None
   if 'PIC' in vals:
    j=vals.index('PIC')+1;parts=[]
    while j<len(a) and V(a[j]) not in {'USAGE','COMP','COMP-3','BINARY','VALUE','OCCURS','REDEFINES','INDEXED'}:parts.append(a[j].value);j+=1
    pic=''.join(parts)
   usage='COMP-3' if 'COMP-3' in vals else 'COMP' if 'COMP' in vals else 'BINARY' if 'BINARY' in vals else after('USAGE')
   occurs=int(after('OCCURS')) if after('OCCURS') and after('OCCURS').isdigit() else None
   occ_max=int(after('OCCURS',3)) if occurs is not None and after('OCCURS',2)=='TO' and (after('OCCURS',3) or '').isdigit() else occurs   # OCCURS n TO m: m
   depending=after('ON',1) if 'DEPENDING' in vals and 'ON' in vals else None
   indexed=after('BY') if 'INDEXED' in vals and 'BY' in vals else None
   redefines=after('REDEFINES');renames=None
   if level==66 and 'RENAMES' in vals:
    j=vals.index('RENAMES');renames=[V(x) for x in a[j+1:] if V(x) not in ('THRU','THROUGH')]
   value=after('VALUE')
   if level==88:parent=stack[-1]['name'] if stack else None
   elif level==66:parent=stack[-1]['parent'] if stack else None
   else:
    if level==77:stack.clear()  # 77 é item independente (nunca filho do grupo anterior)
    while stack and stack[-1]['level']>=level:stack.pop()
    parent=stack[-1]['name'] if stack else None
   it={'level':level,'name':name,'parent':parent,'pic':pic,'picture':picture_info(pic),'usage':usage,'occurs':occurs,'occurs_max':occ_max,'depending_on':depending,'indexed_by':indexed,'redefines':redefines,'renames':renames,'value':literal(value),'start_line':start.line,'end_line':end.line}
   items.append(it)
   if level not in (66,88):stack.append(it)
   continue
  i+=1
 return {'overlays':overlays_of(items),'groups':groups_of(items),'items':items,'by_name':{x['name']:x for x in items},'conditions_88':{x['name']:{'parent':x['parent'],'value':x['value']} for x in items if x['level']==88},'aliases':{x['name']:x['redefines'] for x in items if x['redefines']},'arrays':{x['name']:{'size':x['occurs'],'depending_on':x['depending_on'],'indexed_by':x['indexed_by']} for x in items if x['occurs']},'renames':{x['name']:x['renames'] for x in items if x['renames']},'sizes':byte_sizes(items)}
