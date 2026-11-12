import pathlib,re,hashlib
from runtime_registry import resolve
def rec(tech,construct,p,line,raw,detail=None):
 cap=resolve(tech,construct)
 return {'id':hashlib.sha1(f'{p}:{line}:{tech}:{construct}:{raw}'.encode()).hexdigest()[:12].upper(),'technology':tech,'construct':construct,'source':str(p),'line':line,'raw':raw.strip(),'status':'SUPPORTED' if cap and cap.executable else 'MISSING_RUNTIME','handler':cap.handler if cap else None,'detail':detail}
def cics_construct(body):
 u=' '.join(body.upper().split())
 pairs=[('SEND MAP','SEND_MAP'),('RECEIVE MAP','RECEIVE_MAP'),('PUT CONTAINER','PUT_CONTAINER'),('GET CONTAINER','GET_CONTAINER')]
 for x,c in pairs:
  if x in u:return c
 z=re.search(r'EXEC\s+CICS\s+([A-Z0-9-]+)',u);return z.group(1).replace('-','_') if z else 'UNKNOWN'
def sql_construct(body):
 u=' '.join(body.upper().split())
 if re.search(r'\bDECLARE\s+\S+\s+CURSOR\b',u):return 'DECLARE_CURSOR'
 for x,c in [('OPEN','OPEN_CURSOR'),('FETCH','FETCH_CURSOR'),('CLOSE','CLOSE_CURSOR'),('SELECT','SELECT'),('INSERT','INSERT'),('UPDATE','UPDATE'),('DELETE','DELETE'),('COMMIT','COMMIT'),('ROLLBACK','ROLLBACK')]:
  if re.search(r'\b'+x+r'\b',u):return c
 return 'UNKNOWN'
def scan_file(p):
 text=p.read_text(encoding='latin-1');lines=text.splitlines();out=[];i=0
 while i<len(lines):
  s=lines[i];u=s.upper();ln=i+1
  if 'EXEC CICS' in u or 'EXEC SQL' in u:
   a=[s]
   while 'END-EXEC' not in ' '.join(a).upper() and i+1<len(lines):i+=1;a.append(lines[i])
   body=' '.join(a);tech='CICS' if 'EXEC CICS' in body.upper() else 'DB2';c=cics_construct(body) if tech=='CICS' else sql_construct(body);out.append(rec(tech,c,p,ln,body));i+=1;continue
  # BMS macros
  for macro in ('DFHMSD','DFHMDI','DFHMDF'):
   if re.search(r'\b'+macro+r'\b',u):out.append(rec('BMS',macro,p,ln,s))
  # JCL is discovered structurally, not by extension.
  if s.startswith('//'):
   if re.search(r'\sJOB\b',u):out.append(rec('JCL','JOB',p,ln,s))
   if re.search(r'\sPROC\b',u):out.append(rec('JCL','PROC',p,ln,s))
   if re.search(r'\sDD\b',u):out.append(rec('JCL','DD',p,ln,s))
   if re.search(r'//\s*SET\b',u):out.append(rec('JCL','SET',p,ln,s))
   z=re.search(r'\sEXEC\s+(?:PGM=)?([A-Z0-9#$@_-]+)',u)
   if z:
    if 'PGM=' in u:
     pg=z.group(1);cap='EXEC_PGM';out.append(rec('JCL',cap,p,ln,s))
     if pg in ('SORT','ICEMAN','IEFBR14'):out.append(rec('JCL_UTILITY',pg,p,ln,s))
    else:out.append(rec('JCL','EXEC_PROC',p,ln,s))
   if 'COND=' in u:out.append(rec('JCL','COND',p,ln,s))
  # COBOL source-level constructs and service CALLs
  if re.search(r'\bMOVE\b',u):out.append(rec('COBOL','MOVE',p,ln,s))
  if re.search(r'\bIF\b',u):out.append(rec('COBOL','IF',p,ln,s))
  z=re.search(r"\bCALL\s+['\"]?([A-Z0-9_-]+)",u)
  if z:
   target=z.group(1)
   if target.startswith('MQ'):out.append(rec('MQ',target,p,ln,s))
   elif target in ('CBLTDLI','AIBTDLI'):
    # Function can be data-driven; mark adapter itself and defer concrete verb to runtime evidence.
    out.append(rec('COBOL','CALL',p,ln,s,'DL/I adapter; verb may be runtime-resolved'))
   else:out.append(rec('COBOL','CALL',p,ln,s))
  # VSAM/file verbs
  for verb in ('READ','WRITE','REWRITE','DELETE'):
   if re.search(r'\b'+verb+r'\b',u) and 'EXEC SQL' not in u:out.append(rec('VSAM',verb,p,ln,s))
  i+=1
 return out
def build(root):
 rows=[]
 for p in pathlib.Path(root).rglob('*'):
  if p.is_file():
   try:rows+=scan_file(p)
   except UnicodeDecodeError:pass
 return rows
