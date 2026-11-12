# CICS e BMS/3270 (simulador multi-tecnologia)

> Descreve `cics_runtime.py`/`bms_runtime.py` (Motor 2). `program_runtime.py` despacha apenas LINK, XCTL, RETURN, PUT/GET CONTAINER, START, SYNCPOINT, SEND MAP e RECEIVE MAP; as demais funções existem mas não são chamadas a partir do COBOL. O pipeline oficial trata CICS em `semantic_core/cobol_ast_runtime.py` (ver doc 04).
## CICS
Implementados no runtime atual: LINK, XCTL, RETURN, COMMAREA, channels/containers, START, SYNCPOINT, GETMAIN/FREEMAIN, ASSIGN, ASKTIME/FORMATTIME e TS Queue READQ/WRITEQ/DELETEQ. RESP/RESP2 são registrados pelo runtime.
### TS Queue
```python
writeq(state,"FILA","dados")
readq(state,"FILA",1)
deleteq(state,"FILA")
```
WRITEQ com `item` substitui o item, cobrindo o uso REWRITE encontrado nos fontes certificados.
## BMS
Parser de DFHMDI/DFHMDF, posição/tamanho, INITIAL, ATTRB, COLOR/HILIGHT, render 24x80, campos protegidos e entrada com AID/EIBAID.
## Limite
Comandos CICS não registrados entram como `MISSING_RUNTIME`; não são ignorados.
