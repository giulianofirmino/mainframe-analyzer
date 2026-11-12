      ******************************************************************
      * DCLGEN TABLE(DB2PRD.TK)                                        *
      *        LIBRARY(AD.DB2.DCLGEN(KNOWN1))                          *
      *        ACTION(REPLACE)                                         *
      *        LANGUAGE(COBOL)                                         *
      *        STRUCTURE(KNOWN1)                                       *
      *        APOST                                                   *
      * ... IS THE DCLGEN COMMAND THAT MADE THE FOLLOWING STATEMENTS   *
      ******************************************************************
           EXEC SQL DECLARE DB2PRD.TK TABLE
           ( K_ID                           DECIMAL(8, 0) NOT NULL,
             K_NOME                         CHAR(10)
           ) END-EXEC.
      ******************************************************************
      * COBOL DECLARATION FOR TABLE DB2PRD.TK                          *
      ******************************************************************
       01  KNOWN1.
           10 K-ID                 PIC S9(8)V USAGE COMP-3.
           10 K-NOME               PIC X(10).
      ******************************************************************
      * THE NUMBER OF COLUMNS DESCRIBED BY THIS DECLARATION IS 2       *
      ******************************************************************
