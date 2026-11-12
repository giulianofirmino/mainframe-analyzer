from pathlib import Path
R=Path(__file__).parents[1]
s=(R/'tools/certify_from_zero.py').read_text()
# The official runner must not import/read historical semantic artifacts.
for forbidden in ('golden-ledger','business-rule-outcome-catalog','semantic-witnesses'):
 assert forbidden not in s, forbidden
assert 'build_catalog' in s
print('PASS FROM ZERO NO HISTORY')
