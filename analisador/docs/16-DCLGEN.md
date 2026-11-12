# DCLGEN

`semantic_core/dclgen_parser.py` é o analisador sintático dos membros DCLGEN (DB2 for z/OS, `LANGUAGE(COBOL)`).

## Descoberta
Qualquer arquivo da entrada, com qualquer extensão (exceto `.CBL` e `.TXT`), cujo conteúdo tenha `EXEC SQL DECLARE <tabela> TABLE` e uma estrutura `01`. Na base `tcap/codigo` isso encontra os `.DCL` e os `.CPY` da pasta `DCLGEN`.

## Gramática reconhecida
| Parte | Linhas (`kind`) |
|---|---|
| Cabeçalho | `COMMENT_OPTION` (TABLE, LIBRARY, ACTION, LANGUAGE, STRUCTURE, APOST/QUOTE, LABEL, NAMES, COLSUFFIX, INDVAR...), `COMMENT_GENERATED_BY`, `COMMENT_BANNER`, `COMMENT_TEXT` |
| Declaração SQL | `SQL_DECLARE_TABLE`, `SQL_COLUMN`, `SQL_CONTINUATION`, `SQL_END_EXEC` |
| Estrutura COBOL | `COMMENT_COBOL_DECLARATION`, `COBOL_STRUCTURE_01`, `COBOL_LEVEL_10`, `COBOL_LEVEL_49`, `COBOL_CONTINUATION` |
| Trailer | `COMMENT_COLUMN_COUNT` |
| Físico | `BLANK`, `EOF_MARKER` (Ctrl-Z); BOM UTF-8 e CRLF são tratados na leitura |

Tipos SQL: CHAR/CHARACTER, VARCHAR, CHAR VARYING, LONG VARCHAR, GRAPHIC, VARGRAPHIC, BINARY, VARBINARY, DECIMAL/DEC/NUMERIC(p,s), DECFLOAT, SMALLINT, INTEGER/INT, BIGINT, REAL, FLOAT, DOUBLE [PRECISION], DATE, TIME, TIMESTAMP(p), BLOB/CLOB/DBCLOB(n K|M|G), ROWID, XML; sufixos NOT NULL, WITH DEFAULT, FOR BIT/SBCS/MIXED DATA, CCSID, WITH/WITHOUT TIME ZONE.
Cláusulas COBOL: nível, nome, PIC/PICTURE [IS], USAGE [IS] COMP/COMP-3/COMP-4/COMP-5/COMP-1/COMP-2/BINARY/DISPLAY/PACKED-DECIMAL, OCCURS n TIMES (estrutura de indicadores).

Código e comentários são lidos pelos tokens do léxico (a PIC é expandida a partir dos tokens; só o indicador da coluna 7, o marcador Ctrl-Z e as linhas em branco são posicionais). Linha fora da gramática vira `UNRECOGNIZED` e reprova o membro.

## Validação semântica
- Uma coluna SQL para cada campo nível 10, na mesma ordem e com o mesmo nome (`_` → `-`).
- Tipo x PIC: DECIMAL(p,s) ↔ `S9(p-s)V9(s) COMP-3`; SMALLINT/INTEGER/BIGINT ↔ `S9(4)/S9(9)/S9(18) COMP`; CHAR(n) ↔ `X(n)`; DATE ↔ `X(10)`; TIME ↔ `X(8)`; TIMESTAMP ↔ `X(26)`; VARCHAR(n) ↔ grupo com `49 -LEN S9(4) COMP/COMP-5` e `49 -TEXT X(n)`.
- Trailer, opção `TABLE(...)`, opção `STRUCTURE(...)` e comentário `COBOL DECLARATION FOR TABLE` batem com o DECLARE.
- Tamanho em bytes de cada campo e do registro.

## Ligação com os programas
`program_bindings` lê cada fonte e devolve:
- `includes`: cada `EXEC SQL INCLUDE` com status `RESOLVED` (tabela e estrutura), `MISSING` ou `SYSTEM` (SQLCA/SQLDA);
- `field_references`: cada `:ESTRUTURA.CAMPO` e `CAMPO OF ESTRUTURA` ligado a `tabela.coluna`, com linhas. Status `RESOLVED`, `DCLGEN_MISSING` (INCLUDE sem membro) ou `FIELD_NOT_IN_DCLGEN`.

## Saídas no pipeline
- `dclgen-catalog.json` e `03-data-schema/{ia,human}` (fase de esquema de dados, que também traz uso das colunas, deduções e operações de cada programa nas tabelas);
- `dependency-map.json`: chaves `sql_includes` e `dclgen_fields` por programa;
- `certification-summary.json`: bloco `dclgen`.

## Relatório isolado
```bash
python3 tools/dclgen_report.py <pasta> [--out dclgen-catalog.json]
```
Sai com 0 quando todas as linhas foram reconhecidas e todas as colunas são coerentes.

## Resultado na base tcap/codigo
6 membros, 6 tabelas, 135 colunas, 510 linhas, 100% reconhecidas, 0 inconsistências. 30 INCLUDEs nos programas: 18 resolvidos, 12 membros ausentes (todos do CDPS1SAA). 117 referências a campos DCLGEN: 84 ligadas a tabela.coluna, 33 dependem dos membros ausentes.
