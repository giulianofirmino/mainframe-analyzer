import sys,pathlib
ROOT=pathlib.Path(__file__).parents[1];sys.path.insert(0,str(ROOT/'semantic_core'))
from cobol_token_parser import parse_text
from decision_business_rule_audit import audit,summarize
src="""       IDENTIFICATION DIVISION.
       PROGRAM-ID. X.
       PROCEDURE DIVISION.
           IF A = 1
              MOVE 1 TO B
           ELSE
              CONTINUE
           END-IF.
           IF C = 2
              CONTINUE
           END-IF.
"""
rows=audit('X',parse_text(src));s=summarize(rows)
assert s['decisions']==2 and s['accounted']==2 and s['unaccounted']==0
assert {x['classification'] for x in rows}=={'BUSINESS_RULE','EXCLUDED'}
assert all(x['reason'] for x in rows)
print('PASS DECISION->BUSINESS-RULE ACCOUNTABILITY')
