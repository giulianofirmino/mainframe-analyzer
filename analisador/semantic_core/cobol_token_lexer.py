from dataclasses import dataclass,asdict
import re
@dataclass
class Token:
 type:str; value:str; line:int; column:int; offset:int
 def json(self):return asdict(self)
KEYWORDS=set("""IDENTIFICATION DIVISION PROGRAM-ID DATA WORKING-STORAGE LINKAGE PROCEDURE USING SECTION IF ELSE END-IF EVALUATE WHEN OTHER END-EVALUATE MOVE TO INITIALIZE COMPUTE ADD SUBTRACT MULTIPLY DIVIDE GIVING SET TRUE FALSE PERFORM THRU THROUGH UNTIL VARYING FROM BY END-PERFORM EXIT GO GOTO DEPENDING ON CALL CONTINUE GOBACK STOP RUN DISPLAY STRING UNSTRING INSPECT REPLACING ALL NEXT SENTENCE EXEC SQL END-EXEC AND OR NOT IN IS NULL OPEN FETCH CLOSE DECLARE CURSOR FOR COMMIT ROLLBACK INSERT UPDATE DELETE SELECT SEARCH AT END END-SEARCH TIMES PIC VALUE REDEFINES OCCURS USAGE COMP COMP-3 BINARY INDEXED UP DOWN SIZE ERROR ON INVALID KEY NOT-INVALID-KEY RENAMES OPEN INPUT OUTPUT I-O EXTEND CLOSE READ WRITE REWRITE DELETE START FILE STATUS RECORD INTO AT END NOT INVALID KEY END-READ END-WRITE END-REWRITE END-DELETE END-START CICS LINK XCTL PROGRAM COMMAREA LENGTH RESP RESP2 RETURN""".split())
def normalize_lines(text):
 out=[];off=0
 for n,raw in enumerate(text.splitlines(True),1):
  line=raw.rstrip('\r\n')
  # fixed-format: cols 1-6 sequence, col 7 indicator, 8-72 source
  fixed=len(line)>=7 and (line[:6].strip().isdigit() or line[:6].strip()=='' or line[6:7] in ('*','/','-','D','d',' '))
  if fixed:
   ind=line[6:7];src=line[7:72]
   if ind in ('*','/'):off+=len(raw);continue
   # continuation marker: lexical whitespace is enough; token stream joins it.
   basecol=8
  else:src=line;basecol=1
  if src.lstrip().startswith('*>'):off+=len(raw);continue
  out.append((n,src,basecol,off));off+=len(raw)
 return out
def lex(text):
 toks=[];in_sql=False
 for ln,s,base,off in normalize_lines(text):
  i=0
  while i<len(s):
   if s[i].isspace():i+=1;continue
   col=base+i
   if s.startswith('*>',i):break
   if s[i] in "'\"":
    q=s[i];j=i+1
    while j<len(s):
     if s[j]==q:
      if j+1<len(s) and s[j+1]==q:j+=2;continue
      j+=1;break
     j+=1
    toks.append(Token('STRING',s[i:j],ln,col,off+i));i=j;continue
   m=re.match(r'(>=|<=|<>|!=|=|>|<|\+|-|\*|/|\(|\)|,|\.)',s[i:])
   if m:
    v=m.group(1);toks.append(Token('PERIOD' if v=='.' else 'SYMBOL',v,ln,col,off+i));i+=len(v);continue
   m=re.match(r'[0-9]+-[A-Za-z0-9_-]+',s[i:])
   if m:
    v=m.group(0);toks.append(Token('IDENT',v.upper(),ln,col,off+i));i+=len(v);continue
   m=re.match(r'[0-9]+(?:[.,][0-9]+)?',s[i:])
   if m:
    v=m.group(0);toks.append(Token('NUMBER',v,ln,col,off+i));i+=len(v);continue
   m=re.match(r'[A-Za-z][A-Za-z0-9_-]*',s[i:])
   if m:
    v=m.group(0);u=v.upper();toks.append(Token('KEYWORD' if u in KEYWORDS else 'IDENT',u,ln,col,off+i));i+=len(v);continue
   toks.append(Token('SYMBOL',s[i],ln,col,off+i));i+=1
 toks.append(Token('EOF','',len(text.splitlines())+1,1,len(text)));return toks
