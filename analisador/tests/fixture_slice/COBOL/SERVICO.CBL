       IDENTIFICATION DIVISION.
       PROGRAM-ID. SERVICO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WRK-AREA.
           05  AREA-OPCAO-A          PIC X(01).
           05  AREA-OPCAO-B          PIC X(01).
       77  WRK-SAIDA                 PIC 9(01).
       LINKAGE SECTION.
       01  DFHCOMMAREA               PIC X(02).
       PROCEDURE DIVISION.
       0000-PRINCIPAL SECTION.
           MOVE DFHCOMMAREA TO WRK-AREA
           IF AREA-OPCAO-A EQUAL 'S'
              PERFORM 1000-OPCAO-A
           END-IF.
           IF AREA-OPCAO-B EQUAL 'S'
              PERFORM 2000-OPCAO-B
           END-IF.
           EXEC CICS RETURN END-EXEC.
       1000-OPCAO-A SECTION.
           MOVE 1 TO WRK-SAIDA.
       1000-99-FIM. EXIT.
       2000-OPCAO-B SECTION.
           MOVE 2 TO WRK-SAIDA.
       2000-99-FIM. EXIT.
