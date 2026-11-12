import sys,pathlib,tempfile
ROOT=pathlib.Path(__file__).parents[1];sys.path.insert(0,str(ROOT/'semantic_core'))
from cobol_condition_runtime import evaluate
assert evaluate('X EQUAL + 100',lambda q:100)
assert evaluate('X EQUAL - 1',lambda q:-1)
print('PASS FINALIZATION')
