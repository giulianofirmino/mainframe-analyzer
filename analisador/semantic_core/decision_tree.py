from __future__ import annotations
import hashlib,json,re

EFFECT={'PERFORM','MOVE','COMPUTE','ADD','SUBTRACT','MULTIPLY','DIVIDE','SET','CALL','EXEC_SQL','EXEC_CICS','FILE_WRITE','FILE_REWRITE','FILE_DELETE','STRING','UNSTRING','INSPECT'}
DATA_MUTATION={'MOVE','COMPUTE','ADD','SUBTRACT','MULTIPLY','DIVIDE','SET','STRING','UNSTRING','INSPECT'}
PERSISTENT_EFFECT={'FILE_WRITE','FILE_REWRITE','FILE_DELETE'}

def _id(p,n):
    return 'DT-'+hashlib.sha1(f"{p}:{n.get('start_line')}:{n.get('start_column')}:{n.get('type')}".encode()).hexdigest()[:12].upper()

def _sql_details(raw):
    s=' '.join(str(raw or '').split())
    up=s.upper()
    kind=_sql_kind(s)
    tables=[]
    for pat in (r'\bFROM\s+([A-Z0-9_.-]+)',r'\bJOIN\s+([A-Z0-9_.-]+)',r'\bUPDATE\s+([A-Z0-9_.-]+)',r'\bINTO\s+([A-Z0-9_.-]+)',r'\bDELETE\s+FROM\s+([A-Z0-9_.-]+)',r'\bMERGE\s+INTO\s+([A-Z0-9_.-]+)'):
        tables += re.findall(pat,up,re.I)
    # Host variables are concrete COBOL/SQL mappings, not semantic inference by name.
    host_variables=re.findall(r':([A-Z0-9_-]+(?:\.[A-Z0-9_-]+)?)',up,re.I)
    columns=[]
    if kind=='SELECT':
        m=re.search(r'\bSELECT\s+(.*?)\s+INTO\s*:?',s,re.I)
        if m: columns=[x.strip() for x in m.group(1).split(',') if x.strip()]
    elif kind=='UPDATE':
        m=re.search(r'\bSET\s+(.*?)(?:\s+WHERE\s+|$)',s,re.I)
        if m: columns=[x.split('=')[0].strip() for x in m.group(1).split(',') if '=' in x]
    elif kind=='INSERT':
        m=re.search(r'\bINSERT\s+INTO\s+[A-Z0-9_.-]+\s*\((.*?)\)',s,re.I)
        if m: columns=[x.strip() for x in m.group(1).split(',') if x.strip()]
    where=[]
    m=re.search(r'\bWHERE\s+(.*?)(?:\s+ORDER\s+BY|\s+GROUP\s+BY|\s+WITH\s+UR|$)',s,re.I)
    if m: where=[m.group(1).strip()]
    return {'operation':kind,'statement':s,'tables':list(dict.fromkeys(tables)),'columns':columns,'host_variables':list(dict.fromkeys(host_variables)),'predicates':where}

def _cics_details(raw):
    s=' '.join(str(raw or '').split())
    kind=_cics_kind(s)
    d={'operation':kind,'statement':s}
    if kind in ('LINK','XCTL'):
        m=re.search(r'\bPROGRAM\s*\(([^)]+)\)',s,re.I)
        if m:d['program_reference']=m.group(1).strip()
    for key in ('COMMAREA','LENGTH','MAP','MAPSET','CHANNEL','CONTAINER','QUEUE'):
        m=re.search(r'\b'+key+r'\s*\(([^)]+)\)',s,re.I)
        if m:d[key.lower()]=m.group(1).strip()
    return d

def _effect(n):
    raw=n.get('args') or n.get('sql') or n.get('command') or n.get('header') or ''
    e={'type':n.get('type'),'line':n.get('start_line'),'detail':raw}
    if n.get('type')=='EXEC_SQL': e['resolved_detail']=_sql_details(raw)
    elif n.get('type')=='EXEC_CICS': e['resolved_detail']=_cics_details(raw)
    elif n.get('type')=='CALL': e['resolved_detail']={'operation':'CALL','target':str(raw).strip()}
    return e

def _sql_kind(detail):
    s=str(detail or '').lstrip().upper()
    m=re.match(r'(SELECT|INSERT|UPDATE|DELETE|MERGE|CALL|SET)\b',s)
    return m.group(1) if m else 'OTHER'

def _cics_kind(detail):
    s=str(detail or '').upper()
    # Structural CICS verbs only. Program/resource names never participate.
    for k in ('LINK','XCTL','SEND MAP','RECEIVE MAP','SEND TEXT','RECEIVE','START','RETURN','SYNCPOINT','READQ','WRITEQ','DELETEQ','GETMAIN','FREEMAIN','ASKTIME','FORMATTIME','ASSIGN','GET CONTAINER','PUT CONTAINER'):
        if re.search(r'\b'+re.escape(k).replace(r'\ ',r'\s+')+r'\b',s): return k
    return 'OTHER'

def classify_branch(branch, decision):
    """Generic semantic classification from structural effects only.

    Names/prefixes, literal business vocabulary and corpus-specific identifiers are
    intentionally ignored. UNKNOWN is preferred over inventing business meaning.
    """
    effects=branch.get('effects') or []
    children=branch.get('children') or []
    types=[e.get('type') for e in effects]
    evidence=[]
    if not effects:
        if children:
            return 'FLOW_CONTROL','branch only routes to nested decisions',[f'nested_decisions={len(children)}']
        return 'FLOW_CONTROL','branch has no observable effect',[]

    persistent=[e for e in effects if e.get('type') in PERSISTENT_EFFECT]
    sql=[(_sql_kind(e.get('detail')),e) for e in effects if e.get('type')=='EXEC_SQL']
    sql_write=[e for k,e in sql if k in ('INSERT','UPDATE','DELETE','MERGE')]
    sql_read=[e for k,e in sql if k=='SELECT']
    calls=[e for e in effects if e.get('type')=='CALL']
    performs=[e for e in effects if e.get('type')=='PERFORM' and e.get('resolved')]
    cics=[(_cics_kind(e.get('detail')),e) for e in effects if e.get('type')=='EXEC_CICS']
    functional_cics=[e for k,e in cics if k in ('LINK','XCTL','SEND MAP','SEND TEXT','START','PUT CONTAINER')]
    technical_cics=[e for k,e in cics if k in ('SYNCPOINT','READQ','WRITEQ','DELETEQ','GETMAIN','FREEMAIN','ASKTIME','FORMATTIME','ASSIGN','GET CONTAINER')]
    mutations=[e for e in effects if e.get('type') in DATA_MUTATION]

    if persistent or sql_write:
        evidence += [f'persistent_writes={len(persistent)+len(sql_write)}']
        return 'BUSINESS','decision path controls persistent state change',evidence
    if calls or functional_cics:
        evidence += [f'functional_invocations_or_outputs={len(calls)+len(functional_cics)}']
        return 'BUSINESS','decision path controls an externally observable functional invocation/output',evidence
    if technical_cics and not (mutations or sql_read):
        evidence += [f'technical_runtime_effects={len(technical_cics)}']
        return 'TECHNICAL','effects are limited to runtime/resource mechanics',evidence
    if sql_read and (mutations or children):
        evidence += [f'data_reads={len(sql_read)}',f'data_mutations={len(mutations)}']
        return 'BUSINESS','decision path consumes persisted data and changes program state/flow',evidence
    if mutations:
        # A mutation alone may be business data, output mapping, or temporary control
        # state. Without lineage to an external boundary we must not guess.
        evidence += [f'in_memory_mutations={len(mutations)}']
        return 'UNKNOWN','in-memory effects require data-lineage/boundary evidence to determine business meaning',evidence
    if technical_cics:
        evidence += [f'technical_runtime_effects={len(technical_cics)}']
        return 'TECHNICAL','runtime/resource mechanics dominate branch effects',evidence
    return 'UNKNOWN','observable effects exist but structural evidence is insufficient for semantic classification',[f'effect_types={sorted(set(types))}']

def _paragraphs(ast):
    out={}; current=None
    for n in ast.get('body',[]):
        if n.get('type')=='LABEL':
            current=str(n.get('name') or '').upper(); out.setdefault(current,[])
        elif current:
            out[current].append(n)
    return out

def _perform_target(header):
    s=str(header or '').strip().upper()
    m=re.match(r'([A-Z0-9-]+)',s)
    return m.group(1) if m else None

def _expanded_effects(items, paragraphs, seen=None):
    seen=set(seen or ()); out=[]
    for n in items:
        typ=n.get('type')
        if typ in EFFECT and typ!='PERFORM': out.append(_effect(n))
        if typ=='PERFORM':
            if n.get('inline'):
                out.extend(_expanded_effects(n.get('body',[]),paragraphs,seen))
            else:
                target=_perform_target(n.get('header'))
                if target and target in paragraphs and target not in seen:
                    out.append({'type':'PERFORM','line':n.get('start_line'),'detail':target,'resolved':True})
                    out.extend(_expanded_effects(paragraphs[target],paragraphs,seen|{target}))
                else:
                    out.append({'type':'PERFORM','line':n.get('start_line'),'detail':target or n.get('header') or '', 'resolved':False})
        # Nested IF/EVALUATE branches are separate decision-tree nodes. Do not
        # merge mutually-exclusive descendant effects into the parent rule.
        # This keeps every Business Rule path-specific and prevents a parent
        # branch from claiming SQL/CICS effects that only occur in a child branch.
    return out

def build(program,ast):
    roots=[];flat=[]; paragraphs=_paragraphs(ast); cur={'p':None}
    def walk(items,path):
        effects=[]
        for n in items:
            typ=n.get('type')
            if typ=='LABEL':cur['p']=str(n.get('name') or '').upper()
            if typ in EFFECT:effects.append(_effect(n))
            if typ=='IF':
                x={'decision_id':_id(program,n),'program':program,'line':n.get('start_line'),'type':'IF','expression':n.get('condition'),'paragraph':cur['p'],'path_context':list(path),'branches':[]};flat.append(x);roots.append(x) if not path else None
                for label,body in [('TRUE',n.get('then',[])),('FALSE',n.get('else_body',[]))]:
                    b={'result':label,'effects':[],'children':[]}; before=len(flat); walk(body,path+[{'decision_id':x['decision_id'],'result':label}]); b['effects']=_expanded_effects(body,paragraphs); b['children']=[q['decision_id'] for q in flat[before:] if len(q['path_context'])==len(path)+1]
                    cls,reason,ev=classify_branch(b,x);b['semantic_classification']=cls;b['classification_reason']=reason;b['classification_evidence']=ev;x['branches'].append(b)
            elif typ=='EVALUATE':
                x={'decision_id':_id(program,n),'program':program,'line':n.get('start_line'),'type':'EVALUATE','expression':n.get('subject'),'paragraph':cur['p'],'path_context':list(path),'branches':[]};flat.append(x);roots.append(x) if not path else None
                for i,w in enumerate(n.get('whens',[]) or []):
                    label=f'WHEN_{i+1}';b={'result':label,'when':w.get('condition'),'effects':[],'children':[]};before=len(flat);walk(w.get('body',[]),path+[{'decision_id':x['decision_id'],'result':label,'when':w.get('condition')}]);b['effects']=_expanded_effects(w.get('body',[]),paragraphs);b['children']=[q['decision_id'] for q in flat[before:] if len(q['path_context'])==len(path)+1]
                    cls,reason,ev=classify_branch(b,x);b['semantic_classification']=cls;b['classification_reason']=reason;b['classification_evidence']=ev;x['branches'].append(b)
                # WHENs empilhados sem instruções executam o corpo do próximo WHEN com instruções.
                ws=n.get('whens',[]) or []
                for i,b in enumerate(x['branches']):
                    if not ws[i].get('body'):
                        j=next((k for k in range(i,len(ws)) if ws[k].get('body')),None)
                        if j is not None and j!=i:b['falls_through_to']=x['branches'][j]['result']
        return effects
    walk(ast.get('body',[]),[])
    return {'program':program,'root_decisions':[x['decision_id'] for x in roots],'decisions':flat}

def business_rules_from_tree(tree):
    """Return final rules plus a complete audit of every traversed branch."""
    final=[];audit=[]
    for d in tree['decisions']:
        for b in d['branches']:
            path=d['path_context']+[{'decision_id':d['decision_id'],'line':d['line'],'expression':d['expression'],'result':b['result'],'when':b.get('when')}]
            core={'program':tree['program'],'path':path,'effects':b['effects']}
            rid='BR-'+hashlib.sha1(json.dumps(core,sort_keys=True,default=str).encode()).hexdigest()[:12].upper()
            cls=b.get('semantic_classification','UNKNOWN')
            row={'rule_id':rid,'program':tree['program'],'decision_path':path,'effects':b['effects'],'sql_effects':[e.get('resolved_detail') for e in b['effects'] if e.get('type')=='EXEC_SQL'],'cics_effects':[e.get('resolved_detail') for e in b['effects'] if e.get('type')=='EXEC_CICS'],'call_effects':[e.get('resolved_detail') for e in b['effects'] if e.get('type')=='CALL'],'semantic_classification':cls,'classification_reason':b.get('classification_reason'),'classification_evidence':b.get('classification_evidence',[]),'source':'DECISION_TREE_TRAVERSAL'}
            row['status']='BUSINESS_RULE' if cls in ('BUSINESS','BUSINESS_ERROR') else 'AUDITED_NON_BUSINESS'
            audit.append(row)
            if cls in ('BUSINESS','BUSINESS_ERROR'):final.append(row)
    return {'business_rules':final,'branch_audit':audit}
