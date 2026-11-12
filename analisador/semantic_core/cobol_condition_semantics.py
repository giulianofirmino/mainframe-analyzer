import re
def clean(s):
 s=' '.join(str(s).replace('(',' ( ').replace(')',' ) ').split())
 s=re.sub(r'\bIS\s+NOT\s+EQUAL\s+TO\b',' NOT EQUAL ',s,flags=re.I)
 s=re.sub(r'\bIS\s+EQUAL\s+TO\b',' EQUAL ',s,flags=re.I)
 s=re.sub(r'\bNOT\s+EQUAL\s+TO\b',' NOT EQUAL ',s,flags=re.I)
 s=re.sub(r'\bEQUAL\s+TO\b',' EQUAL ',s,flags=re.I)
 s=re.sub(r'\bIS\s+GREATER\s+THAN\s+OR\s+EQUAL\s+TO\b',' >= ',s,flags=re.I)
 s=re.sub(r'\bIS\s+LESS\s+THAN\s+OR\s+EQUAL\s+TO\b',' <= ',s,flags=re.I)
 s=re.sub(r'\bGREATER\s+THAN\s+OR\s+EQUAL\s+TO\b',' >= ',s,flags=re.I)
 s=re.sub(r'\bLESS\s+THAN\s+OR\s+EQUAL\s+TO\b',' <= ',s,flags=re.I)
 s=re.sub(r'\bIS\s+GREATER\s+THAN\b',' > ',s,flags=re.I);s=re.sub(r'\bGREATER\s+THAN\b',' > ',s,flags=re.I)
 s=re.sub(r'\bIS\s+LESS\s+THAN\b',' < ',s,flags=re.I);s=re.sub(r'\bLESS\s+THAN\b',' < ',s,flags=re.I)
 s=re.sub(r'\bNOT\s+EQUAL\b',' != ',s,flags=re.I);s=re.sub(r'\bEQUAL\b',' = ',s,flags=re.I)
 return ' '.join(s.split())
def split_top(s,word):
 toks=s.split();depth=0;parts=[];cur=[]
 for t in toks:
  depth+=t.count('(');depth-=t.count(')')
  if depth==0 and t.upper()==word:parts.append(' '.join(cur));cur=[]
  else:cur.append(t)
 parts.append(' '.join(cur));return parts
def atom(s):
 s=s.strip().strip('() ').strip()
 m=re.match(r'(.+?)\s+(NOT\s+)?NUMERIC$',s,re.I)
 if m:return {'kind':'CLASS','var':m.group(1).strip(),'class':'NUMERIC','negated':bool(m.group(2)),'raw':s}
 m=re.match(r'(.+?)\s*(=|!=|<>|>=|<=|>|<)\s*(ZERO|ZEROS|ZEROES|SPACE|SPACES|LOW-VALUES|HIGH-VALUES)$',s,re.I)
 if m:return {'kind':'SPECIAL','var':m.group(1).strip(),'op':m.group(2),'value':m.group(3).upper(),'raw':s}
 m=re.match(r'(.+?)\s*(=|!=|<>|>=|<=|>|<)\s*(.+)$',s)
 if m:return {'kind':'CMP','var':m.group(1).strip(),'op':m.group(2),'value':m.group(3).strip(),'raw':s}
 if s:return {'kind':'CONDITION_NAME','name':s,'raw':s}
 return {'kind':'UNKNOWN','raw':s}
def parse(s):
 s=clean(s).strip()
 # remove balanced outer parens conservatively
 while s.startswith('(') and s.endswith(')'):
  d=0;ok=True
  for i,ch in enumerate(s):
   d += 1 if ch=='(' else -1 if ch==')' else 0
   if d==0 and i<len(s)-1:ok=False;break
  if not ok:break
  s=s[1:-1].strip()
 ps=split_top(s,'OR')
 if len(ps)>1:return {'kind':'OR','items':[parse(x) for x in ps],'raw':s}
 ps=split_top(s,'AND')
 if len(ps)>1:return {'kind':'AND','items':[parse(x) for x in ps],'raw':s}
 return atom(s)
def leaves(n):
 if n.get('kind') in ('AND','OR'):
  return sum((leaves(x) for x in n['items']),[])
 return [n]
def supported(n):
 return all(x.get('kind')!='UNKNOWN' for x in leaves(n))
