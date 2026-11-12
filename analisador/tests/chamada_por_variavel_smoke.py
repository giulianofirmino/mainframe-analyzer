"""CALL/LINK cujo destino é variável sem VALUE: vale o único literal que o procedimento move para ela; com mais de um literal, fica sem destino."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'semantic_core'))
import static_model as sm
from cobol_token_parser import parse_text
from cobol_data_model import build_data_model

FONTE = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGX.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       77  WRK-MOD-A   PIC X(008) VALUE SPACES.
       77  WRK-MOD-B   PIC X(008) VALUE SPACES.
       77  WRK-MOD-C   PIC X(008) VALUE 'FIXO'.
       PROCEDURE DIVISION.
       0000-PRINCIPAL.
           MOVE 'ALVO1' TO WRK-MOD-A.
           CALL WRK-MOD-A.
           MOVE 'ALVO2' TO WRK-MOD-B.
           MOVE 'ALVO3' TO WRK-MOD-B.
           CALL WRK-MOD-B.
           CALL WRK-MOD-C.
           GOBACK.
'''
ast, dm = parse_text(FONTE), build_data_model(FONTE)
r = {c['raw']: (c['target'], c['resolution']) for c in sm._calls(ast, dm)}
assert r['WRK-MOD-A'] == ('ALVO1', 'MOVE'), r
assert r['WRK-MOD-B'] == (None, 'VARIAVEL_COM_VARIOS_MOVE'), r
assert r['WRK-MOD-C'] == ('FIXO', 'VALUE'), r
print('chamada_por_variavel smoke OK')
