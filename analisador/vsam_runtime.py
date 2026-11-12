def read(st,name,key):
 rows=st.files.setdefault(name,[]);r=next((x for x in rows if str(x.get('key'))==str(key)),None);st.vars['FILE_STATUS']='00' if r else '23';st.emit('VSAM_READ',file=name,key=key,status=st.vars['FILE_STATUS'],record=r);return r
def write(st,name,row):
 a=st.files.setdefault(name,[])
 if any(str(x.get('key'))==str(row.get('key')) for x in a):st.vars['FILE_STATUS']='22';st.emit('VSAM_WRITE',file=name,status='22');return False
 a.append(dict(row));st.vars['FILE_STATUS']='00';st.emit('VSAM_WRITE',file=name,status='00',record=row);return True
def rewrite(st,name,key,row):
 a=st.files.setdefault(name,[]);r=next((x for x in a if str(x.get('key'))==str(key)),None)
 if not r:st.vars['FILE_STATUS']='23';return False
 r.update(row);st.vars['FILE_STATUS']='00';st.emit('VSAM_REWRITE',file=name,key=key,status='00');return True
def delete(st,name,key):
 a=st.files.setdefault(name,[]);b=[x for x in a if str(x.get('key'))!=str(key)];st.files[name]=b;st.vars['FILE_STATUS']='00' if len(b)<len(a) else '23';st.emit('VSAM_DELETE',file=name,key=key,status=st.vars['FILE_STATUS']);return len(b)<len(a)
def browse(st,name,start=None):
 a=sorted(st.files.setdefault(name,[]),key=lambda x:str(x.get('key')));r=[x for x in a if start is None or str(x.get('key'))>=str(start)];st.emit('VSAM_BROWSE',file=name,start=start,count=len(r));return r
