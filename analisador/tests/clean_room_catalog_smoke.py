import sys,pathlib
R=pathlib.Path(__file__).parents[1];sys.path.insert(0,str(R/'semantic_core'))
from cobol_token_parser import parse_text
from clean_room_catalog import build_catalog
src='       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n       PROCEDURE DIVISION.\n       P.\n           IF A = 1\n              MOVE 2 TO B\n           END-IF.\n'
a=parse_text(src);c=build_catalog({'T':a})
assert len(c)==2 and {x['branch'] for x in c}=={'TRUE','FALSE'}
print('PASS CLEAN ROOM CATALOG')
