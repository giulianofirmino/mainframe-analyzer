from dataclasses import dataclass
@dataclass(frozen=True)
class RuntimeCapability:
 technology:str; construct:str; handler:str; executable:bool=True
_CAPS=[
('COBOL','MOVE','program_runtime.execute_program'),('COBOL','IF','program_runtime.execute_program'),('COBOL','CALL','program_runtime.execute_program'),
('CICS','LINK','program_runtime.cics_exec'),('CICS','XCTL','program_runtime.cics_exec'),('CICS','SEND_MAP','bms_runtime.send_map'),('CICS','RECEIVE_MAP','bms_runtime.receive_map'),
('CICS','PUT_CONTAINER','cics_runtime.put_container'),('CICS','GET_CONTAINER','cics_runtime.get_container'),('CICS','START','cics_runtime.start'),('CICS','RETURN','cics_runtime.return_trans'),('CICS','SYNCPOINT','cics_runtime.syncpoint'),
('CICS','ASKTIME','cics_runtime.asktime'),('CICS','FORMATTIME','cics_runtime.formattime'),('CICS','ASSIGN','cics_runtime.assign'),('CICS','GETMAIN','cics_runtime.getmain'),('CICS','FREEMAIN','cics_runtime.freemain'),('CICS','READQ','cics_runtime.readq'),('CICS','WRITEQ','cics_runtime.writeq'),('CICS','DELETEQ','cics_runtime.deleteq'),
('DB2','SELECT','sql_runtime.execute_sql'),('DB2','INSERT','sql_runtime.execute_sql'),('DB2','UPDATE','sql_runtime.execute_sql'),('DB2','DELETE','sql_runtime.execute_sql'),('DB2','COMMIT','sql_runtime.execute_sql'),('DB2','ROLLBACK','sql_runtime.execute_sql'),
('DB2','DECLARE_CURSOR','db2_cursor_runtime.CursorRuntime'),('DB2','OPEN_CURSOR','db2_cursor_runtime.CursorRuntime'),('DB2','FETCH_CURSOR','db2_cursor_runtime.CursorRuntime'),('DB2','CLOSE_CURSOR','db2_cursor_runtime.CursorRuntime'),
('VSAM','READ','vsam_runtime.read'),('VSAM','WRITE','vsam_runtime.write'),('VSAM','REWRITE','vsam_runtime.rewrite'),('VSAM','DELETE','vsam_runtime.delete'),
('IMS','GU','ims_runtime.call'),('IMS','GN','ims_runtime.call'),('IMS','GNP','ims_runtime.call'),('IMS','ISRT','ims_runtime.call'),('IMS','REPL','ims_runtime.call'),('IMS','DLET','ims_runtime.call'),
('MQ','MQOPEN','mq_runtime.mqopen'),('MQ','MQPUT','mq_runtime.mqput'),('MQ','MQGET','mq_runtime.mqget'),('MQ','MQCLOSE','mq_runtime.mqclose'),('MQ','MQCMIT','runtime_state.State.commit'),('MQ','MQBACK','runtime_state.State.rollback'),
('JCL','JOB','jcl_runtime.run_jcl'),('JCL','EXEC_PGM','jcl_runtime.run_jcl'),('JCL','EXEC_PROC','jcl_environment.expand_proc'),('JCL','PROC','jcl_environment.parse_procs'),('JCL','DD','jcl_environment.collect_dd'),('JCL','SET','jcl_runtime.run_jcl'),('JCL','COND','jcl_runtime.run_jcl'),
('JCL_UTILITY','SORT','jcl_environment.utility'),('JCL_UTILITY','ICEMAN','jcl_environment.utility'),('JCL_UTILITY','IEFBR14','jcl_environment.utility'),
('BMS','DFHMSD','bms_runtime.parse_bms'),('BMS','DFHMDI','bms_runtime.parse_bms'),('BMS','DFHMDF','bms_runtime.parse_bms')]
REGISTRY={(t,c):RuntimeCapability(t,c,h,e) for t,c,h,*x in _CAPS for e in [x[0] if x else True]}
def resolve(technology,construct):return REGISTRY.get((technology,construct))


for _c,_h in {
'GETMAIN':'cics_runtime.getmain','FREEMAIN':'cics_runtime.freemain','WRITEQ':'cics_runtime.writeq',
'READQ':'cics_runtime.readq','DELETEQ':'cics_runtime.deleteq','ASSIGN':'cics_runtime.assign',
'ASKTIME':'cics_runtime.asktime','FORMATTIME':'cics_runtime.formattime'}.items():
 REGISTRY[('CICS',_c)]=RuntimeCapability('CICS',_c,_h,True)
for _c in ('INCLUDE','SET'):
 REGISTRY[('DB2',_c)]=RuntimeCapability('DB2',_c,'sql_runtime.compile_or_set',True)
