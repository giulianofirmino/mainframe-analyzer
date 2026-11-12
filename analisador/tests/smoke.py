import pathlib,sys,json,shutil,tempfile
sys.path.insert(0,str(pathlib.Path(__file__).parents[1]))
from simulation_completeness import assess
from simulator import deterministic
root=pathlib.Path(__file__).parent/'fixture';s=json.loads((pathlib.Path(__file__).parent/'scenario.json').read_text())
a=assess(root);assert a['status']=='PASS' and a['coverage']==100.0 and a['discovered_construct_occurrences']==a['runtime_supported_occurrences']
r=deterministic(root,s,3);assert r['deterministic'] and r['execution']['status']=='SUCCESS'
a2=assess(root,r['execution']);assert {'technology':'IMS','construct':'GU'} in a2['runtime_resolved_constructs']
with tempfile.TemporaryDirectory() as d:
 shutil.copytree(root,d,dirs_exist_ok=True);p=pathlib.Path(d)/'APP1.cbl';p.write_text(p.read_text().replace("EXEC CICS SEND MAP('MAINMAP') END-EXEC","EXEC CICS ENQ RESOURCE('X') END-EXEC\n EXEC CICS SEND MAP('MAINMAP') END-EXEC"));q=assess(d);assert q['status']=='FAIL' and any(x['technology']=='CICS' and x['construct']=='ENQ' for x in q['missing_runtime'])
with tempfile.TemporaryDirectory() as d:
 shutil.copytree(root,d,dirs_exist_ok=True);p=pathlib.Path(d)/'APP1.cbl';p.write_text(p.read_text().replace("EXEC SQL SELECT STATUS INTO :STATUS FROM CUSTOMER WHERE ID = :CUSTOMER_ID END-EXEC","EXEC SQL MERGE INTO CUSTOMER USING X ON 1=1 END-EXEC"));q=assess(d);assert q['status']=='FAIL' and any(x['technology']=='DB2' and x['construct']=='UNKNOWN' for x in q['missing_runtime'])
print('PASS',a['discovered_construct_occurrences'],a['coverage'],r['execution']['trace_hash'])
