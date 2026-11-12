# VSAM, IMS e MQ (simulador multi-tecnologia)

Estes runtimes são usados por `program_runtime.py` (Motor 2). O pipeline oficial trata arquivos via `semantic_core/mainframe_file_runtime.py` e não simula IMS nem MQ.

## VSAM (`vsam_runtime.py`)
READ/WRITE/REWRITE/DELETE por chave, browse simples, FILE STATUS 00/22/23.

## IMS DB (`ims_runtime.py`)
SSA simples; GU/GN/GNP/ISRT/REPL/DLET via `CALL 'CBLTDLI'`/`'AIBTDLI'`; IMS_STATUS.

## MQ (`mq_runtime.py`)
MQOPEN/MQPUT/MQGET/MQCLOSE, message id determinístico, correl_id, reply_to_q, RC 2033; MQCMIT/MQBACK ligados a commit/rollback do estado.
