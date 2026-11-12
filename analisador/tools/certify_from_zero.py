#!/usr/bin/env python3
from pathlib import Path
import sys,json,copy,hashlib,collections,shutil,zipfile,tempfile
R=Path(__file__).parents[1];sys.path.insert(0,str(R/'semantic_core'))
from cobol_token_parser import parse_text
from clean_room_catalog import build_catalog
from business_rule_witness import synthesize
from cobol_ast_runtime import Runtime
from concolic_path_solver import target_outcome
from operation_scoped_status_solver import route_status
from clean_room_path_solver import solve
from program_classifier import classify_programs
from decision_tree import build as build_decision_tree, business_rules_from_tree
from dependency_map import build as build_dependency_map
from data_usage import build as build_data_usage
from artifact_renderer import publish
from dclgen_parser import build_catalog as build_dclgen_catalog, program_bindings as dclgen_program_bindings

def tracehash(r):return hashlib.sha256(json.dumps([{k:v for k,v in e.items() if k!='seq'} for e in r['trace']],sort_keys=True,default=str).encode()).hexdigest()
def discover(root):
    pats=('*.CBL','*.cbl','*.COB','*.cob')
    found=[]
    for pat in pats: found.extend(root.rglob(pat))
    # Avoid duplicate alternate text renderings such as X.CBL.TXT; runtime consumes canonical COBOL source.
    uniq={}
    for p in sorted(set(found)):
        data=p.read_bytes(); key=hashlib.sha256(data).hexdigest(); uniq.setdefault(key,p)
    return sorted(uniq.values())
import time
_T0=time.time();_LAST=[_T0]
def log(msg):
 """Progresso com tempo total e da etapa (stderr, sem buffer) para ver onde o pipeline gasta tempo."""
 now=time.time();print(f'[certify {now-_T0:7.1f}s +{now-_LAST[0]:6.1f}s] {msg}',file=sys.stderr,flush=True);_LAST[0]=now
def main():
 inp=Path(sys.argv[1]); outdir=Path(sys.argv[2] if len(sys.argv)>2 else R/'from-zero-output')
 if outdir.exists():shutil.rmtree(outdir)
 outdir.mkdir(parents=True)
 tmp=None
 if inp.is_file() and inp.suffix.lower()=='.zip':
    tmp=Path(tempfile.mkdtemp(prefix='mfaa-')); zipfile.ZipFile(inp).extractall(tmp); src=tmp
 else: src=inp
 files=discover(src);log(f'{len(files)} fontes descobertos')
 if not files: raise SystemExit('No canonical COBOL sources (.CBL or .COB) found')
 # PHASE 0: classification is advisory. It never silently removes a program from certification.
 # Parse is structural infrastructure for classification; no semantic category uses names/prefixes.
 provisional={}
 for f in files:
  txt=Path(f).read_bytes().decode('latin-1'); a=parse_text(txt)
  pid=(a.get('program_id') or Path(f).stem).upper(); provisional[pid]=(str(f),txt,a)
 asts={p:v[2] for p,v in provisional.items()};log('lexer+parser: AST de cada programa')
 import static_model
 model=static_model.build(src);log('modelo estático (chamadas resolvidas, copybooks expandidos)')
 classification=classify_programs(asts,{p:x['text'] for p,x in model['programs'].items()});log('classificação de programas')
 (outdir/'phase-0-program-classification.json').write_text(json.dumps({'phase':'PROGRAM_CLASSIFICATION','programs':classification},indent=2),encoding='utf-8')
 programs={p:v[0] for p,v in provisional.items()}
 texts={p:v[1] for p,v in provisional.items()}
 # Independent program-level products: dependency map, decision trees, tree-derived rules.
 dependencies={p:build_dependency_map(p,asts[p],texts[p]) for p in asts}
 log('mapa de dependências')
 # DCLGEN: parse sintático de todo membro DCLGEN da entrada e ligação INCLUDE/host variable -> tabela.coluna
 dclgen=build_dclgen_catalog(src)
 dclgen_bindings={p:dclgen_program_bindings(p,texts[p],dclgen) for p in texts}
 for p in dependencies:
  dependencies[p]['sql_includes']=dclgen_bindings[p]['includes']
  dependencies[p]['dclgen_fields']=dclgen_bindings[p]['field_references']
 dclgen_summary={**dclgen['summary'],'includes':sum(b['summary']['includes'] for b in dclgen_bindings.values()),'includes_resolved':sum(b['summary']['includes_resolved'] for b in dclgen_bindings.values()),'includes_missing':sorted({m for b in dclgen_bindings.values() for m in b['summary']['includes_missing']}),'field_references':sum(b['summary']['field_references'] for b in dclgen_bindings.values()),'field_references_resolved':sum(b['summary']['field_references_resolved'] for b in dclgen_bindings.values()),'field_references_dclgen_missing':sum(b['summary']['field_references_dclgen_missing'] for b in dclgen_bindings.values())}
 (outdir/'dclgen-catalog.json').write_text(json.dumps({'summary':dclgen_summary,'tables':dclgen['tables'],'members':dclgen['members'],'program_bindings':dclgen_bindings},indent=2),encoding='utf-8')
 log('DCLGEN: catálogo e ligações')
 trees={p:build_decision_tree(p,asts[p]) for p in asts};log('árvores de decisão')
 tree_rules={p:business_rules_from_tree(trees[p]) for p in asts};log('regras de negócio pela árvore')
 (outdir/'dependency-map.json').write_text(json.dumps(dependencies,indent=2),encoding='utf-8')
 (outdir/'decision-trees.json').write_text(json.dumps(trees,indent=2),encoding='utf-8')
 (outdir/'business-rules-from-decision-tree.json').write_text(json.dumps(tree_rules,indent=2),encoding='utf-8')
 data_usage={p:build_data_usage(p,texts[p]) for p in asts};log('uso de dados')
 (outdir/'data-usage.json').write_text(json.dumps(data_usage,indent=2),encoding='utf-8')
 cat=build_catalog(asts); rt=Runtime(programs,max_steps=30000); gold=[]; pending=[]
 direct=[x for x in cat if x['synthesis_class']=='DIRECT_CONSTRAINT'];log(f'catálogo de desfechos: {len(cat)} alvos, {len(direct)} com restrição direta')
 def promote(t,st,strategy,depth=0):
  hs=[]
  for _ in range(3):
   rr=rt.run(t['program'],copy.deepcopy(st))
   if rr['status']!='SUCCESS' or target_outcome(rr,t)!='HIT':return None
   hs.append(tracehash(rr))
  if len(set(hs))!=1:return None
  return {'target_id':t['target_id'],'program':t['program'],'line':t['line'],'branch':t['branch'],'scenario':st,'strategy':strategy,'depth':depth,'trace_hash':hs[0]}
 for n_t,t in enumerate(direct,1):
  if n_t%100==0:log(f'testemunhas diretas {n_t}/{len(direct)}: {len(gold)} goldens, {len(pending)} pendentes')
  w=synthesize(t['condition'],t['branch']=='TRUE',1000)
  if w is None:pending.append((t,{'inputs':{},'trials':0}));continue  # sem testemunha sintetizável (por exemplo, condição sem variável de entrada): segue para o solver de caminho
  st={'inputs':{'EIBCALEN':1,**w['inputs']},'tables':{},'files':{}}
  r=rt.run(t['program'],copy.deepcopy(st)); o=target_outcome(r,t); z=None
  if r['status']=='SUCCESS' and o=='HIT':z=promote(t,st,'FRESH_WITNESS')
  elif o=='REACHED_OTHER':
   kind,site=route_status(r.get('trace',[]),t['program'],t['line'],w['inputs'])
   if kind=='DB2' and site is not None:st.setdefault('db2_status',{})[f"{t['program']}:{site}"]={k:v for k,v in w['inputs'].items() if k.upper() in ('SQLCODE','SQLWARN0')}
   elif kind=='CICS' and site is not None:st.setdefault('cics_status',{})[f"{t['program']}:{site}"]={k:v for k,v in w['inputs'].items() if k.upper() in ('EIBRESP','EIBRESP2')}
   z=promote(t,st,'FRESH_PRODUCER')
  if z:gold.append(z)
  else:pending.append((t,w))
 log(f'testemunhas diretas concluídas: {len(gold)} goldens, {len(pending)} pendentes')
 path=[]
 for n_p,(t,w) in enumerate(pending[:180],1):
  if n_p%20==0:log(f'solver de caminho {n_p}/{min(180,len(pending))}: {len(path)} resolvidos')
  z=solve(rt,t,w,max_depth=1,width=5)
  if z['status']=='HIT':
   q=promote(t,z['scenario'],'FRESH_FIRST_DIVERGENCE',z['depth'])
   if q:path.append(q)
 gold.extend(path);log(f'solver de caminho concluído: {len(path)} goldens extras')
 verified={g['target_id'] for g in gold}
 statuses=[]
 for t in cat:
  if t['target_id'] in verified: status='GOLDEN_VERIFIED'; reason='deterministic 3-run executable proof'
  elif t['synthesis_class']=='NEEDS_88_LINEAGE': status='UNKNOWN_DEPENDENCY'; reason='88-level lineage requires copybook/declaration resolution in next bounded stage'
  else: status='UNKNOWN_DEPENDENCY'; reason='bounded dynamic proof not established; no unsupported runtime semantic was demonstrated'
  statuses.append({'target_id':t['target_id'],'program':t['program'],'line':t['line'],'branch':t['branch'],'status':status,'reason':reason})
 counts=collections.Counter(x['status'] for x in statuses)
 summary={'sources':len(files),'phase0':dict(collections.Counter(x['classification'] for x in classification)),'recommendations':dict(collections.Counter(x['recommendation'] for x in classification)),'outcomes':len(cat),'direct':sum(x['synthesis_class']=='DIRECT_CONSTRAINT' for x in cat),'needs_88':sum(x['synthesis_class']=='NEEDS_88_LINEAGE' for x in cat),'evaluate':sum(x['synthesis_class']=='EVALUATE_BRANCH' for x in cat),'terminal_status':dict(counts),'clean_room_goldens':len(gold),'historical_inputs_used':False,'decision_trees':sum(len(x['decisions']) for x in trees.values()),'tree_business_rules':sum(len(x['business_rules']) for x in tree_rules.values()),'decision_branch_audit':sum(len(x['branch_audit']) for x in tree_rules.values()),'dependency_programs':len(dependencies),'dclgen':{k:dclgen_summary[k] for k in ('members','tables','columns','coverage_percent','status','includes','includes_resolved','includes_missing','field_references_resolved','field_references_dclgen_missing')},'certification':'PASS' if counts['UNKNOWN_DEPENDENCY']==0 and counts['UNSUPPORTED']==0 else 'FAIL'}
 manifest=[{'program':p,'file':str(Path(f).relative_to(src)),'sha256':hashlib.sha256(Path(f).read_bytes()).hexdigest()} for p,f in programs.items()]
 (outdir/'catalog.json').write_text(json.dumps({'summary':summary,'source_manifest':manifest,'targets':cat},indent=2)); (outdir/'goldens.json').write_text(json.dumps({'summary':summary,'goldens':gold},indent=2)); (outdir/'outcome-status.json').write_text(json.dumps({'summary':summary,'outcomes':statuses},indent=2)); (outdir/'certification-summary.json').write_text(json.dumps(summary,indent=2))
 log('certificação calculada, publicando relatórios')
 # Uniform IA-use + Human-use artifacts, all projected from the same canonical models.
 import static_model,data_flow,rule_paths,table_roles,decision_map,schema_analysis,field_lineage
 from dependency_map import declared_cursors
 from readable_code import Namer
 groupinfo={p:decision_map.group_names(x) for p,x in model['programs'].items()}
 dmaps={p:decision_map.build(p,x['ast'],groupinfo[p][0],x['linemap'].source_line,groupinfo[p][1],declared_cursors(x['text'])) for p,x in model['programs'].items()};log('mapa de decisão')
 namers={p:Namer(*groupinfo[p]) for p in groupinfo}
 flows=data_flow.build(model);data_rules=rule_paths.build(model,flows,dmaps,namers);log('fluxo de dados e regras determinísticas por caminho de decisão')
 field_lin=field_lineage.build(model,flows,dmaps,data_rules);log('linhagem por campo entre programas')
 (outdir/'data-lineage.json').write_text(json.dumps(field_lin,indent=2,default=str),encoding='utf-8')
 (outdir/'decision-map.json').write_text(json.dumps(dmaps,indent=2,default=str),encoding='utf-8')
 (outdir/'data-flow.json').write_text(json.dumps(flows,indent=2,default=str),encoding='utf-8');(outdir/'deterministic-rules.json').write_text(json.dumps(data_rules,indent=2,default=str),encoding='utf-8')
 roles=table_roles.build(model['edges'],set(model['programs']),{x['program']:x['classification'] for x in classification},dependencies,{m['table']:[k] for k,m in dclgen['members'].items() if m.get('table')})
 dtab={m['table']:{c['name'] for c in m['columns']} for m in dclgen['members'].values() if m.get('table')}
 schema=schema_analysis.analyze(model,dependencies,dtab,roles);log('análise de esquema das tabelas')
 publish(outdir,'00-program-classification',{'programs':classification},'Program Classification')
 publish(outdir,'01-discovery-dependencies',{'programs':dependencies},'Resources and Dependency Map')
 publish(outdir,'05-decision-map',{'decision_map':dmaps,'decision_trees':trees,'catalog_summary':summary},'Decision Map')
 publish(outdir,'02-program-schema',{'programs':dependencies},'Program Schema')
 publish(outdir,'03-data-schema',{'summary':dclgen_summary,'tables':dclgen['tables'],'members':{k:{x:v for x,v in r.items() if x!='line_kinds'} for k,r in dclgen['members'].items()},'program_bindings':dclgen_bindings,'usage':data_usage,'roles':roles,'schema':schema},'Data Schema: Tables, Columns, Usage and Operations')
 publish(outdir,'04-data-lineage',{'lineage':field_lin,'programs':flows},'Data Lineage')
 publish(outdir,'06-deterministic-rules',{'programs':tree_rules,'data_rules':data_rules},'Deterministic Rules')
 dyn={'goldens':gold,'summary':{'executions_verified':len(gold),'deterministic_replays':3}}
 publish(outdir,'07-dynamic-analysis',dyn,'Dynamic Analysis')
 publish(outdir,'08-golden-cases',{'goldens':gold},'Golden Cases')
 publish(outdir,'09-certification',{'summary':summary,'outcomes':statuses},'Certification')
 sys.path.insert(0,str(Path(__file__).resolve().parent));import gerar_relatorios;gerar_relatorios.gerar(outdir);log('relatórios publicados');print(json.dumps(summary,sort_keys=True))
 if tmp: shutil.rmtree(tmp,ignore_errors=True)
if __name__=='__main__':main()
