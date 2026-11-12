import argparse,json,pathlib
from simulator import deterministic
from simulation_completeness import assess
def main():
 a=argparse.ArgumentParser();a.add_argument('root');a.add_argument('--scenario',required=True);a.add_argument('--out',default='mainframe-simulation.json');x=a.parse_args()
 comp=assess(x.root);s=json.loads(pathlib.Path(x.scenario).read_text())
 if comp['status']=='PASS':
  r=deterministic(x.root,s,3);comp=assess(x.root,r['execution'])
 else:r={'deterministic':False,'execution':{'status':'BLOCKED_BY_COMPLETENESS','trace':[],'trace_hash':None}}
 r['simulation_completeness']=comp;pathlib.Path(x.out).write_text(json.dumps(r,indent=2,ensure_ascii=False))
 ok=comp['status']=='PASS' and r['deterministic'] and r['execution']['status']=='SUCCESS'
 print(json.dumps({'status':'PASS' if ok else 'FAIL','coverage':comp['coverage'],'constructs':comp['discovered_construct_occurrences'],'missing':len(comp['missing_runtime']),'execution':r['execution']['status']}));raise SystemExit(0 if ok else 2)
if __name__=='__main__':main()
