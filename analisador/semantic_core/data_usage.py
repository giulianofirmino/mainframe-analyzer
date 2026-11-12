from __future__ import annotations
from cobol_data_model import build_data_model
from cobol_token_lexer import lex

def build(program,text):
    dm=build_data_model(text); toks=lex(text)
    proc=0
    for i,t in enumerate(toks[:-1]):
        if str(t.value).upper()=='PROCEDURE' and str(toks[i+1].value).upper()=='DIVISION': proc=i+2; break
    refs={str(t.value).upper() for t in toks[proc:] if getattr(t,'type',None) in ('IDENT','WORD','KEYWORD')}
    rows=[]
    for x in dm['items']:
        if x['level']==88: continue
        used=x['name'] in refs
        rows.append({'name':x['name'],'level':x['level'],'parent':x['parent'],'pic':x['pic'],'mapped':True,'used':used,'status':'MAPPED_AND_USED' if used else 'MAPPED_NOT_USED','declaration_line':x['start_line']})
    declared={x['name'] for x in dm['items']}
    return {'program':program,'summary':{'mapped':len(rows),'mapped_and_used':sum(x['used'] for x in rows),'mapped_not_used':sum(not x['used'] for x in rows)},'fields':rows,'conditions_88':dm['conditions_88']}
