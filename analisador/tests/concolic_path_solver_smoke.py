import sys,pathlib
R=pathlib.Path(__file__).parents[1];sys.path.insert(0,str(R/'semantic_core'))
from concolic_path_solver import merge_inputs
assert merge_inputs({'A':1},{'B':2})=={'A':1,'B':2}
assert merge_inputs({'A':1},{'A':2}) is None
print('PASS CONCOLIC PATH SOLVER')
