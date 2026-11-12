def select(st,table,where=None,column=None,into=None):
 rows=st.db.get(table.upper(),[]);hit=next((r for r in rows if not where or all(str(next((rv for rk,rv in r.items() if rk.upper()==k.upper()),None))==str(v) for k,v in where.items())),None)
 code=0 if hit else 100;st.vars['SQLCODE']=code
 if hit and into:st.vars[into]=next((rv for rk,rv in hit.items() if rk.upper()==column.upper()),None)
 st.emit('DB2_SELECT',table=table.upper(),where=where,column=column,into=into,sqlcode=code,value=next((rv for rk,rv in hit.items() if rk.upper()==column.upper()),None) if hit and column else None);return hit
def insert(st,table,row):st.db.setdefault(table.upper(),[]).append(dict(row));st.vars['SQLCODE']=0;st.emit('DB2_INSERT',table=table.upper(),row=row)
def update(st,table,where,changes):
 n=0
 for r in st.db.get(table.upper(),[]):
  if all(str(next((rv for rk,rv in r.items() if rk.upper()==k.upper()),None))==str(v) for k,v in where.items()):r.update(changes);n+=1
 st.vars['SQLCODE']=0;st.emit('DB2_UPDATE',table=table.upper(),where=where,changes=changes,count=n);return n
def delete(st,table,where):
 rows=st.db.get(table.upper(),[]);keep=[r for r in rows if not all(str(next((rv for rk,rv in r.items() if rk.upper()==k.upper()),None))==str(v) for k,v in where.items())];n=len(rows)-len(keep);st.db[table.upper()]=keep;st.vars['SQLCODE']=0;st.emit('DB2_DELETE',table=table.upper(),where=where,count=n);return n
