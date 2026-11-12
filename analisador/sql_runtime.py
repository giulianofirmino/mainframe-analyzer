import re
from db2_runtime import select,insert,update,delete
from db2_cursor_runtime import CursorRuntime
def hv(st,x):return st.vars.get(x.lstrip(':').upper()) if x is not None else None
def execute_sql(st,sql):
 s=' '.join(sql.replace('\n',' ').split());u=s.upper()
 cur=getattr(st,'_cursor_runtime',None)
 if cur is None:cur=CursorRuntime(st);st._cursor_runtime=cur
 z=re.match(r'DECLARE\s+([A-Z0-9_-]+)\s+CURSOR\s+FOR\s+(.+)',s,re.I)
 if z:cur.declare(z.group(1),z.group(2));return
 z=re.match(r'OPEN\s+([A-Z0-9_-]+)',s,re.I)
 if z:cur.open(z.group(1));return
 z=re.match(r'FETCH\s+([A-Z0-9_-]+)\s+INTO\s+(.+)',s,re.I)
 if z:cur.fetch(z.group(1),[x.strip().lstrip(':') for x in z.group(2).split(',')]);return
 z=re.match(r'CLOSE\s+([A-Z0-9_-]+)',s,re.I)
 if z:cur.close(z.group(1));return
 z=re.match(r'SELECT\s+([A-Z0-9_-]+)\s+INTO\s+:([A-Z0-9_-]+)\s+FROM\s+([A-Z0-9_.-]+)(?:\s+WHERE\s+([A-Z0-9_-]+)\s*=\s*:([A-Z0-9_-]+))?',s,re.I)
 if z:
  where={z.group(4).upper():hv(st,z.group(5))} if z.group(4) else None;return select(st,z.group(3),where,z.group(1).upper(),z.group(2).upper())
 z=re.match(r'INSERT\s+INTO\s+([A-Z0-9_.-]+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)',s,re.I)
 if z:
  cols=[x.strip().upper() for x in z.group(2).split(',')];vals=[hv(st,x.strip()) if x.strip().startswith(':') else x.strip("' ") for x in z.group(3).split(',')];return insert(st,z.group(1),dict(zip(cols,vals)))
 z=re.match(r'UPDATE\s+([A-Z0-9_.-]+)\s+SET\s+([A-Z0-9_-]+)\s*=\s*:([A-Z0-9_-]+)\s+WHERE\s+([A-Z0-9_-]+)\s*=\s*:([A-Z0-9_-]+)',s,re.I)
 if z:return update(st,z.group(1),{z.group(4).upper():hv(st,z.group(5))},{z.group(2).upper():hv(st,z.group(3))})
 z=re.match(r'DELETE\s+FROM\s+([A-Z0-9_.-]+)\s+WHERE\s+([A-Z0-9_-]+)\s*=\s*:([A-Z0-9_-]+)',s,re.I)
 if z:return delete(st,z.group(1),{z.group(2).upper():hv(st,z.group(3))})
 if u.startswith('COMMIT'):st.commit();st.begin();return
 if u.startswith('ROLLBACK'):st.rollback();st.begin();return
 raise RuntimeError('UNSUPPORTED_SQL:'+s)
