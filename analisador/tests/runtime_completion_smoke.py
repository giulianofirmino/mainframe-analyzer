import sys,pathlib,tempfile
ROOT=pathlib.Path(__file__).parents[1];sys.path.insert(0,str(ROOT/'semantic_core'))
from cobol_token_parser import parse_text
from cobol_functional_runtime import State,cond
assert cond("I GREATER 50",State(vars={'I':51})) is True
assert cond("I LESS 50",State(vars={'I':49})) is True
a=parse_text("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. X.
       PROCEDURE DIVISION.
       0000-MAIN SECTION.
           PERFORM VARYING I FROM 1 BY 1 UNTIL I GREATER 3
              MOVE I TO O
           END-PERFORM.
       1000-X SECTION.
           EXIT.
""")
assert any(n.get('name')=='0000-MAIN' for n in a['body'])
print('PASS RUNTIME COMPLETION / VERBAL CONDITIONS')
