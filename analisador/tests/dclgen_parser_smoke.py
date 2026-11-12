import sys, pathlib, tempfile
ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'semantic_core'))
from dclgen_parser import parse_dclgen, build_catalog, program_bindings

S = '       '  # colunas 1-7 (sequência + indicador em branco)
C = '      *'  # comentário


def member(columns_sql, fields, count, extra_header=''):
    lines = [C + '*' * 66,
             C + ' DCLGEN TABLE(DB2PRD.TX)',
             C + '        LIBRARY(AD.DB2.DCLGEN(TXB001))',
             C + '        ACTION(REPLACE)',
             C + '        LANGUAGE(COBOL)',
             C + '        STRUCTURE(TXB001)',
             C + '        APOST',
             C + '        LABEL(YES)' + extra_header,
             C + ' ... IS THE DCLGEN COMMAND THAT MADE THE FOLLOWING STATEMENTS',
             S + '    EXEC SQL DECLARE DB2PRD.TX TABLE',
             S + '    ( ' + columns_sql[0]]
    lines += [S + '      ' + c for c in columns_sql[1:]]
    lines += [S + '    ) END-EXEC.',
              C + ' COBOL DECLARATION FOR TABLE DB2PRD.TX',
              ' ' * 7 + '01  TXB001.']
    lines += [S + '    ' + f for f in fields]
    lines += [C + f' THE NUMBER OF COLUMNS DESCRIBED BY THIS DECLARATION IS {count}', '\x1a']
    return '﻿'.encode('utf-8').decode('latin-1') + '\r\n'.join(lines) + '\r\n'


COLS = ['K_ID                 DECIMAL(8, 0) NOT NULL,',
        'VALOR                DECIMAL(15, 2),',
        'QTD                  INTEGER,',
        'PEQ                  SMALLINT NOT NULL WITH DEFAULT,',
        'NOME                 CHAR(40) NOT NULL,',
        'DT                   DATE,',
        'HR                   TIME,',
        'TS                   TIMESTAMP NOT NULL,',
        'OBS                  VARCHAR(200) NOT NULL']
FIELDS = ['10 K-ID                PIC S9(8)V USAGE COMP-3.',
          '10 VALOR               PIC S9(13)V9(2) USAGE COMP-3.',
          '10 QTD                 PIC S9(9) USAGE COMP.',
          '10 PEQ                 PIC S9(4) USAGE COMP.',
          '10 NOME                PIC X(40).',
          '10 DT                  PIC X(10).',
          '10 HR                  PIC X(8).',
          '10 TS                  PIC X(26).',
          '10 OBS.',
          '   49 OBS-LEN          PIC S9(4) USAGE COMP-5.',
          '   49 OBS-TEXT         PIC X(200).']

# 1. membro completo: 100% das linhas reconhecidas e coerente
r = parse_dclgen(member(COLS, FIELDS, 9))
assert r['status'] == 'PASS', (r['issues'], r['unrecognized'])
assert r['coverage']['percent'] == 100.0 and r['coverage']['unrecognized'] == 0
assert r['table'] == 'DB2PRD.TX' and r['structure'] == 'TXB001' and len(r['columns']) == 9
assert r['options']['STRUCTURE'] == 'TXB001' and r['options']['APOST'] is True
v = next(c for c in r['columns'] if c['name'] == 'VALOR')
assert (v['precision'], v['scale'], v['nullable']) == (15, 2, True)
assert next(c for c in r['columns'] if c['name'] == 'PEQ')['default'] is True
assert all(m['compatible'] for m in r['mapping'])
assert r['record_length'] == 5 + 8 + 4 + 2 + 40 + 10 + 8 + 26 + 2 + 200
assert r['coverage']['by_kind']['EOF_MARKER'] == 1 and r['coverage']['by_kind']['COBOL_LEVEL_49'] == 2

# 2. PIC incompatível com o tipo SQL
bad = list(FIELDS); bad[1] = '10 VALOR               PIC S9(13)V9(3) USAGE COMP-3.'
r = parse_dclgen(member(COLS, bad, 9))
assert r['status'] == 'FAIL' and any('VALOR' in x for x in r['issues'])

# 3. contagem do trailer divergente
r = parse_dclgen(member(COLS, FIELDS, 8))
assert r['status'] == 'FAIL' and any('trailer' in x for x in r['issues'])

# 4. tipo SQL desconhecido vira linha não reconhecida
r = parse_dclgen(member(COLS[:-1] + ['OBS                  WHATEVER(200)'], FIELDS, 9))
assert r['status'] == 'FAIL' and r['unrecognized'] and r['coverage']['unrecognized'] > 0

# 5. cláusula COBOL desconhecida
bad = list(FIELDS); bad[4] = '10 NOME                PIC X(40) JUSTIFIED.'
r = parse_dclgen(member(COLS, bad, 9))
assert r['status'] == 'FAIL' and any('JUSTIFIED' in x['reason'] for x in r['unrecognized'])

# 6. catálogo + ligação com programa (INCLUDE resolvido/ausente e host variables)
with tempfile.TemporaryDirectory() as d:
    p = pathlib.Path(d)
    (p / 'TXB001.CPY').write_bytes(member(COLS, FIELDS, 9).encode('latin-1'))
    cat = build_catalog(p)
    assert cat['summary']['status'] == 'PASS' and cat['summary']['tables'] == 1
    prog = '\n'.join([S + 'WORKING-STORAGE SECTION.',
                      S + '    EXEC SQL',
                      S + '         INCLUDE TXB001',
                      S + '    END-EXEC.',
                      S + '    EXEC SQL INCLUDE SQLCA END-EXEC.',
                      S + '    EXEC SQL INCLUDE TXB999 END-EXEC.',
                      S + 'PROCEDURE DIVISION.',
                      S + '    EXEC SQL SELECT NOME INTO :TXB001.NOME FROM DB2PRD.TX',
                      S + '     WHERE K_ID = :TXB001.K-ID END-EXEC.',
                      S + '    MOVE 1 TO K-ID OF TXB001.',
                      S + '    MOVE 10 TO OBS-LEN OF TXB001.',
                      S + '    MOVE 2 TO CAMPO-Z OF TXB999.'])
    b = program_bindings('P', prog, cat)
    st = {x['name']: x['status'] for x in b['includes']}
    assert st == {'TXB001': 'RESOLVED', 'SQLCA': 'SYSTEM', 'TXB999': 'MISSING'}
    refs = {x['field']: x for x in b['field_references']}
    assert refs['NOME']['column'] == 'NOME' and refs['K-ID']['forms'] == ['HOST_VARIABLE', 'QUALIFIED_OF']
    assert refs['OBS-LEN']['column'] == 'OBS'
    assert refs['CAMPO-Z']['status'] == 'DCLGEN_MISSING'
    assert b['summary']['includes_missing'] == ['TXB999']

print('PASS DCLGEN PARSER')
