from construct_ledger import build
def assess(root,execution=None):
 ledger=build(root);events=[x['kind'] for x in (execution or {}).get('trace',[])]
 # Source resolution first. Runtime-resolved DL/I verbs are additional evidence, not a way to hide missing source handlers.
 runtime_constructs=[]
 for k in events:
  if k.startswith('IMS_') and k not in ('IMS_TM_INPUT','IMS_TM_OUTPUT'):runtime_constructs.append(('IMS',k[4:]))
 total=len(ledger);supported=[x for x in ledger if x['status']=='SUPPORTED'];missing=[x for x in ledger if x['status']!='SUPPORTED']
 bytech={}
 for t in sorted({x['technology'] for x in ledger}):
  a=[x for x in ledger if x['technology']==t];ok=sum(x['status']=='SUPPORTED' for x in a);bytech[t]={'discovered':len(a),'runtime_supported':ok,'coverage':round(100*ok/len(a),2)}
 return {'status':'PASS' if total and not missing else 'FAIL','discovered_construct_occurrences':total,'runtime_supported_occurrences':len(supported),'coverage':round(100*len(supported)/total,2) if total else 0.0,'by_technology':bytech,'runtime_resolved_constructs':[{'technology':t,'construct':c} for t,c in sorted(set(runtime_constructs))],'missing_runtime':missing,'ledger':ledger}
