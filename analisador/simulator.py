import pathlib,re,copy
from runtime_state import State
from bms_runtime import parse_bms
from jcl_runtime import run_jcl
from jcl_environment import parse_procs
def load(root):
 root=pathlib.Path(root);src={};jobs=[];maps={};jcltexts=[]
 for p in root.rglob('*'):
  if not p.is_file():continue
  try:t=p.read_text(encoding='latin-1')
  except:continue
  z=re.search(r'\bPROGRAM-ID\.\s*([A-Z0-9-]+)',t,re.I)
  if z:src[z.group(1).upper()]=t
  if re.search(r'^\s*//\S+\s+JOB\b',t,re.M):jobs.append(t)
  if re.search(r'^\s*//\S+\s+(?:JOB|PROC)\b',t,re.M):jcltexts.append(t)
  if 'DFHMDI' in t.upper():maps.update(parse_bms(t))
 return src,jobs,maps,parse_procs(jcltexts)
def execute(root,scenario):
 src,jobs,maps,procs=load(root);st=State(scenario);env={'bms':maps,'screen_inputs':scenario.get('screens',{}),'procs':procs};st.begin()
 try:
  for j in jobs:run_jcl(j,src,st,env)
  st.commit();status='SUCCESS'
 except Exception as e:
  st.rollback();st.emit('SIMULATION_ERROR',error=str(e));status='FAILED'
 return {'status':status,'state':st.snapshot(),'trace':st.trace,'trace_hash':st.trace_hash(),'screens':[e for e in st.trace if e['kind']=='CICS_SEND_MAP']}
def deterministic(root,scenario,runs=3):
 xs=[execute(root,copy.deepcopy(scenario)) for _ in range(runs)];hs=[x['trace_hash'] for x in xs];return {'deterministic':len(set(hs))==1,'trace_hashes':hs,'execution':xs[0]}
