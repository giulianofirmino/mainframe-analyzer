       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGX.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WRK-AREA.
           05  WRK-COD-RET           PIC 9(02).
           05  WRK-MSG               PIC X(08).
       01  WRK-TAB.
           05  WRK-ID                PIC 9(04).
           05  WRK-NOME              PIC X(10).
           EXEC SQL
               DECLARE CSR-PESSOA CURSOR FOR
                   SELECT ID_PESSOA, NM_PESSOA
                     FROM ESQ.TB_PESSOA
                    WHERE ID_PESSOA = :WRK-ID
           END-EXEC.
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  LNK-ID                PIC 9(04).
           05  LNK-RET               PIC 9(02).
           05  LNK-MSG               PIC X(08).
       PROCEDURE DIVISION USING DFHCOMMAREA.
       0000-PRINCIPAL SECTION.
           MOVE LNK-ID TO WRK-ID
           IF LNK-ID EQUAL ZEROS
               MOVE 08 TO LNK-RET
               MOVE 'SEM-ID' TO LNK-MSG
               EXEC CICS RETURN END-EXEC
           END-IF
           EXEC SQL OPEN CSR-PESSOA END-EXEC
           EXEC SQL FETCH CSR-PESSOA INTO :WRK-ID, :WRK-NOME END-EXEC
           IF SQLCODE NOT EQUAL ZEROS
               MOVE 12 TO LNK-RET
               MOVE 'ERRO-DB2' TO LNK-MSG
           ELSE
               MOVE WRK-NOME TO LNK-MSG
           END-IF
           EXEC SQL CLOSE CSR-PESSOA END-EXEC
           EXEC CICS RETURN END-EXEC.
