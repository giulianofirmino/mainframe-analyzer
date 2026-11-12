"""Backends de fila e de banco do host CICS (tools/cics_host.py), nas duas formas:

  internal  — IBM MQ e DB2 em memória, dentro do processo: filas compartilhadas entre as transações (com syncpoint, backout e gatilho)
              e as tabelas do analisador (db2_stateful_runtime), carregadas de uma massa JSON;
  external  — IBM MQ e DB2 de verdade: pymqi (cliente MQ) e ibm_db (cliente DB2), importados só nesta forma.

Os dois lados têm a mesma interface, ligada ao runtime (cobol_ast_runtime) pelos ganchos mq_backend e db2_factory:
  sessão MQ: chamar(rt, s, programa, linha, verbo, args) para MQOPEN/MQGET/MQPUT/MQPUT1/MQCLOSE e syncpoint(rollback);
  sessão DB2: execute(sql) -> {'status', 'operation', 'into', 'sqlcode', 'affected'|'row_count'} e syncpoint(rollback).
Uma sessão por transação (como a unidade de trabalho do CICS); o SYNCPOINT confirma o DB2 e depois o MQ.
"""
from __future__ import annotations

import copy
import os
import datetime as _dt
import re
import threading
import time
from collections import deque
from decimal import Decimal

from db2_stateful_runtime import DB2Stateful
from db2_functional_sql import norm

MQCC_OK, MQCC_FAILED = 0, 2
MQRC_NO_MSG_AVAILABLE, MQRC_UNKNOWN_OBJECT_NAME = 2033, 2085
MQGMO_WAIT, MQGMO_SYNCPOINT, MQPMO_SYNCPOINT = 1, 2, 2
CONEXAO_QUEBRADA = {2009, 2018, 2019, 2059, 2161, 2162, 2202}   # conexão com o queue manager perdida: a próxima tarefa reconecta
CODEPAGE = {37: 'cp037', 500: 'cp500', 1140: 'cp1140', 1208: 'utf-8', 819: 'latin-1', 1252: 'cp1252', 850: 'cp850'}


# ----------------------------------------------------------------------------------------------------------------- MQ: comum ao runtime
class _SessaoMQ:
    """Tradução das chamadas da MQI feitas pelo programa (CALL 'MQGET' USING ...) para o gerenciador de filas da forma escolhida."""

    def __init__(self):
        self.abertas = {}

    def _cc(self, rt, s, p, ln, args, cc, rc):
        rt.assign(s, args[-2], cc, p, ln, 'MQ_COMPCODE')
        rt.assign(s, args[-1], rc, p, ln, 'MQ_REASON')

    @staticmethod
    def _num(rt, s, nome):
        try:
            return int(rt.resolve_name(s, nome) or 0)
        except (TypeError, ValueError):
            return 0

    def chamar(self, rt, s, p, ln, q, args):
        txt = lambda n: str(rt.resolve_name(s, n)).strip()   # noqa: E731
        if q == 'MQOPEN':
            nome = txt(f'MQOD-OBJECTNAME OF {args[1]}')
            try:
                h = self.abrir(nome, self._num(rt, s, args[2]))
            except MQErro as e:
                return self._cc(rt, s, p, ln, args, e.cc, e.rc)
            self.abertas[h] = nome
            rt.assign(s, args[3], h, p, ln, 'MQ_HOBJ')
            rt.event(s, 'MQ_OPEN', program=p, line=ln, queue=nome)
            return self._cc(rt, s, p, ln, args, MQCC_OK, 0)
        if q == 'MQGET':
            h, md, gmo = self._num(rt, s, args[1]), args[2], args[3]
            opcoes = self._num(rt, s, f'MQGMO-OPTIONS OF {gmo}')
            espera = self._num(rt, s, f'MQGMO-WAITINTERVAL OF {gmo}') if opcoes & MQGMO_WAIT else 0
            try:
                m = self.ler(h, opcoes, espera)
            except MQErro as e:
                rt.event(s, 'MQ_GET', program=p, line=ln, queue=self.abertas.get(h), message=None, reason=e.rc)
                return self._cc(rt, s, p, ln, args, e.cc, e.rc)
            rt.assign(s, f'MQMD-MSGID OF {md}', m['msg_id'].decode('latin-1'), p, ln, 'MQ_MD')
            rt.assign(s, f'MQMD-CORRELID OF {md}', m['correl_id'].decode('latin-1'), p, ln, 'MQ_MD')
            rt.assign(s, f'MQMD-BACKOUTCOUNT OF {md}', m.get('backout', 0), p, ln, 'MQ_MD')
            rt.assign(s, f'MQMD-PERSISTENCE OF {md}', m.get('persistencia', 2), p, ln, 'MQ_MD')
            rt.texto_para_area(s, args[5], m['dados'], p, ln, 'MQ_GET')
            rt.assign(s, args[6], len(m['dados']), p, ln, 'MQ_DATALEN')
            s.trace_id = m.get('trace_id') or m['msg_id'].hex()[:16]
            rt.event(s, 'MQ_GET', program=p, line=ln, queue=self.abertas.get(h), message=m['msg_id'].hex(), trace_id=s.trace_id,
                     tamanho=len(m['dados']))
            return self._cc(rt, s, p, ln, args, MQCC_OK, 0)
        if q in ('MQPUT', 'MQPUT1'):
            if q == 'MQPUT1':
                fila, md, pmo, tam, buf = txt(f'MQOD-OBJECTNAME OF {args[1]}'), args[2], args[3], args[4], args[5]
            else:
                fila, md, pmo, tam, buf = self.abertas.get(self._num(rt, s, args[1])), args[2], args[3], args[4], args[5]
            n = self._num(rt, s, tam)
            dados = rt.area_texto(s, buf)
            dados = dados[:n].ljust(n) if n > 0 else dados
            corr = str(rt.resolve_name(s, f'MQMD-CORRELID OF {md}')).encode('latin-1', 'replace')[:24].ljust(24, b'\0')
            m = {'dados': dados, 'correl_id': corr, 'tipo': self._num(rt, s, f'MQMD-MSGTYPE OF {md}'),
                 'persistencia': self._num(rt, s, f'MQMD-PERSISTENCE OF {md}'), 'trace_id': getattr(s, 'trace_id', None)}
            try:
                mid = self.gravar(fila, m, bool(self._num(rt, s, f'MQPMO-OPTIONS OF {pmo}') & MQPMO_SYNCPOINT))
            except MQErro as e:
                return self._cc(rt, s, p, ln, args, e.cc, e.rc)
            rt.event(s, 'MQ_PUT', program=p, line=ln, queue=fila, message=mid.hex(), correl_id=corr.hex(), trace_id=m['trace_id'], tamanho=len(dados))
            return self._cc(rt, s, p, ln, args, MQCC_OK, 0)
        if q == 'MQCLOSE':
            h = self._num(rt, s, args[1])
            self.fechar(h)
            self.abertas.pop(h, None)
        return self._cc(rt, s, p, ln, args, MQCC_OK, 0)   # MQCLOSE, MQCONN, MQDISC

    def fim(self):
        """Fim da tarefa: o que ficou sem SYNCPOINT é desfeito (como no CICS ao terminar a transação sem confirmar)."""
        self.syncpoint(True)
        for h in list(self.abertas):
            self.fechar(h)
        self.abertas.clear()


class ErroSQL(Exception):
    def __init__(self, sqlcode, msg=''):
        super().__init__(f'SQLCODE {sqlcode} {msg}'.strip())
        self.sqlcode = sqlcode


class MQErro(Exception):
    def __init__(self, cc, rc):
        super().__init__(f'MQ CC={cc} RC={rc}')
        self.cc, self.rc = cc, rc


# ----------------------------------------------------------------------------------------------------------------- MQ: internal
class MQMemoria:
    """Gerenciador de filas em memória: filas locais, aliases, leitura com espera, unidade de trabalho e gatilho FIRST.
    gatilhos = {fila: callback(fila)}: chamado quando uma mensagem confirmada chega a uma fila vazia sem leitor aberto."""

    def __init__(self, filas=(), aliases=None):
        self.filas = {f: deque() for f in filas}
        self.aliases = dict(aliases or {})
        self.leitores = {}
        self.gatilhos = {}
        self.cv = threading.Condition()
        self.seq = 0

    def real(self, nome):
        nome = nome.strip()
        return self.aliases.get(nome, nome)

    def novo_id(self):
        self.seq += 1
        return f'MEM{int(time.time() * 1000):013d}{self.seq:08d}'.encode()[:24].ljust(24, b'\0')

    def gravar(self, fila, m):
        """Gravação fora de unidade de trabalho (API HTTP e confirmação de syncpoint)."""
        disparar = None
        with self.cv:
            f = self.real(fila)
            if f not in self.filas:
                raise MQErro(MQCC_FAILED, MQRC_UNKNOWN_OBJECT_NAME)
            m.setdefault('msg_id', self.novo_id())
            m.setdefault('correl_id', b'\0' * 24)
            m.setdefault('backout', 0)
            vazia = not self.filas[f]
            self.filas[f].append(m)
            self.cv.notify_all()
            if vazia and not self.leitores.get(f) and f in self.gatilhos:
                disparar = self.gatilhos[f]
        if disparar:
            disparar(f)
        return m['msg_id']

    def ler(self, fila, espera_ms=0, correl_id=None):
        """Leitura destrutiva fora de unidade de trabalho (API HTTP); correl_id escolhe a resposta de um pedido."""
        fim = time.time() + espera_ms / 1000
        with self.cv:
            f = self.real(fila)
            if f not in self.filas:
                raise MQErro(MQCC_FAILED, MQRC_UNKNOWN_OBJECT_NAME)
            while True:
                for m in list(self.filas[f]):
                    if correl_id is None or m['correl_id'] == correl_id:
                        self.filas[f].remove(m)
                        return m
                resto = fim - time.time()
                if resto <= 0:
                    raise MQErro(MQCC_FAILED, MQRC_NO_MSG_AVAILABLE)
                self.cv.wait(resto)

    def sessao(self):
        return _SessaoMQMemoria(self)

    def estado(self):
        with self.cv:
            return {f: len(q) for f, q in self.filas.items()}


class _SessaoMQMemoria(_SessaoMQ):
    def __init__(self, gm):
        super().__init__()
        self.gm, self.lidas, self.gravadas, self.h = gm, [], [], 0

    def abrir(self, nome, opcoes):
        f = self.gm.real(nome)
        if f not in self.gm.filas:
            raise MQErro(MQCC_FAILED, MQRC_UNKNOWN_OBJECT_NAME)
        self.h += 1
        if opcoes & 0x7:   # MQOO_INPUT_*: leitor aberto (o gatilho FIRST não dispara enquanto houver leitor)
            with self.gm.cv:
                self.gm.leitores[f] = self.gm.leitores.get(f, 0) + 1
            self._leitura = getattr(self, '_leitura', set()) | {self.h}
        return self.h

    def fechar(self, h):
        if h in getattr(self, '_leitura', set()):
            f = self.gm.real(self.abertas.get(h, ''))
            with self.gm.cv:
                self.gm.leitores[f] = max(0, self.gm.leitores.get(f, 1) - 1)
            self._leitura.discard(h)
            disparar = None
            with self.gm.cv:   # mensagens que chegaram enquanto o leitor estava aberto: novo gatilho
                if self.gm.filas.get(f) and not self.gm.leitores.get(f) and f in self.gm.gatilhos:
                    disparar = self.gm.gatilhos[f]
            if disparar:
                disparar(f)

    def ler(self, h, opcoes, espera_ms):
        f = self.gm.real(self.abertas[h])
        fim = time.time() + espera_ms / 1000
        with self.gm.cv:
            while not self.gm.filas[f]:
                resto = fim - time.time()
                if resto <= 0:
                    raise MQErro(MQCC_FAILED, MQRC_NO_MSG_AVAILABLE)
                self.gm.cv.wait(resto)
            m = self.gm.filas[f].popleft()
        if opcoes & MQGMO_SYNCPOINT:
            self.lidas.append((f, m))
        return m

    def gravar(self, fila, m, syncpoint):
        if self.gm.real(fila) not in self.gm.filas:
            raise MQErro(MQCC_FAILED, MQRC_UNKNOWN_OBJECT_NAME)
        if m.get('msg_id') is None:   # MsgId informado pelo programa (módulo MQ com "forçar ids") é mantido
            m['msg_id'] = self.gm.novo_id()
        if syncpoint:
            self.gravadas.append((fila, m))
        else:
            self.gm.gravar(fila, m)
        return m['msg_id']

    def syncpoint(self, rollback):
        lidas, gravadas, self.lidas, self.gravadas = self.lidas, self.gravadas, [], []
        if rollback:
            with self.gm.cv:
                for f, m in reversed(lidas):
                    m['backout'] = m.get('backout', 0) + 1
                    self.gm.filas[f].appendleft(m)
                self.gm.cv.notify_all()
        else:
            for fila, m in gravadas:
                self.gm.gravar(fila, m)


# ----------------------------------------------------------------------------------------------------------------- MQ: external
class MQExterno:
    """IBM MQ de verdade pelo cliente (pymqi). Uma conexão por sessão (a unidade de trabalho do MQ é da conexão)."""

    def __init__(self, host, porta, qmgr, canal, usuario=None, senha=None, ccsid_resposta=37):
        import pymqi   # noqa: F401  (só na forma external)
        self.cfg = dict(host=host, porta=int(porta), qmgr=qmgr, canal=canal, usuario=usuario, senha=senha)
        self.ccsid_resposta = ccsid_resposta

    def conectar(self):
        import pymqi
        c = self.cfg
        cd = pymqi.CD(ChannelName=c['canal'].encode(), ConnectionName=f"{c['host']}({c['porta']})".encode(),
                      ChannelType=pymqi.CMQXC.MQCHT_CLNTCONN, TransportType=pymqi.CMQXC.MQXPT_TCP)
        qm = pymqi.QueueManager(None)
        kw = {'user': c['usuario'], 'password': c['senha']} if c['usuario'] else {}
        qm.connect_with_options(c['qmgr'], cd=cd, **kw)
        return qm

    def sessao(self):
        return _SessaoMQExterna(self)

    def conexao(self):
        """Conexão da linha de execução da região, reaproveitada pelas tarefas seguintes (como o adaptador CICS-MQ da região)."""
        local = self.__dict__.setdefault('_local', threading.local())
        if getattr(local, 'qm', None) is None:
            local.qm = self.conectar()
        return local.qm

    def descartar(self):
        local = self.__dict__.setdefault('_local', threading.local())
        qm, local.qm = getattr(local, 'qm', None), None
        if qm is not None:
            try:
                qm.disconnect()
            except Exception:   # noqa: BLE001
                pass


def _texto(dados, ccsid):
    return dados.decode(CODEPAGE.get(ccsid, 'latin-1'), errors='replace')


class _SessaoMQExterna(_SessaoMQ):
    def __init__(self, gm):
        super().__init__()
        self.gm, self.qm, self.filas = gm, gm.conexao(), {}

    def abrir(self, nome, opcoes):
        import pymqi
        try:
            q = pymqi.Queue(self.qm, nome, opcoes)
        except pymqi.MQMIError as e:
            if e.reason in CONEXAO_QUEBRADA:
                self.gm.descartar()
            raise MQErro(e.comp, e.reason)
        h = len(self.filas) + 1
        self.filas[h] = q
        return h

    def fechar(self, h):
        q = self.filas.pop(h, None)
        if q:
            try:
                q.close()
            except Exception:   # noqa: BLE001
                pass

    def ler(self, h, opcoes, espera_ms):
        import pymqi
        md, gmo = pymqi.MD(), pymqi.GMO(Version=pymqi.CMQC.MQGMO_VERSION_4, Options=opcoes, WaitInterval=espera_ms)   # versão 4: MsgHandle
        mh = None
        try:   # propriedades da mensagem (traceId) num handle, sem cabeçalho RFH2 no corpo
            mh = pymqi.MessageHandle(self.qm)
            gmo.MsgHandle = mh.msg_handle
            gmo.Options |= pymqi.CMQC.MQGMO_PROPERTIES_IN_HANDLE
        except Exception:   # noqa: BLE001
            mh = None
        try:
            dados = self.filas[h].get(None, md, gmo)
        except pymqi.MQMIError as e:
            raise MQErro(e.comp, e.reason)
        trace = None
        if mh:
            try:
                trace = mh.properties.get(b'traceId', max_value_length=256)   # pymqi 1.12: nome em bytes
                trace = trace.decode() if isinstance(trace, bytes) else trace
            except Exception:   # noqa: BLE001
                trace = None
        txt = lambda b: bytes(b).decode('latin-1').rstrip(' \0')   # noqa: E731
        return {'dados': _texto(dados, md.CodedCharSetId), 'msg_id': bytes(md.MsgId), 'correl_id': bytes(md.CorrelId),
                'backout': md.BackoutCount, 'persistencia': md.Persistence, 'trace_id': (trace or '').strip() or None,
                'reply_to_q': txt(md.ReplyToQ), 'reply_to_qmgr': txt(md.ReplyToQMgr), 'expiracao': md.Expiry,
                'formato': bytes(md.Format).decode('latin-1'), 'tipo': md.MsgType, 'prioridade': md.Priority, 'feedback': md.Feedback}

    def gravar(self, fila, m, syncpoint):
        """m: dados, correl_id e, quando o programa os informa (módulo MQ como o SBAT3510), msg_id (mantido), tipo, prioridade,
        formato, reply_to_q/reply_to_qmgr, expiracao (décimos de segundo; -1 = sem expiração), report e feedback."""
        import pymqi
        C = pymqi.CMQC
        b = lambda v, n: str(v or '').encode('latin-1', 'replace')[:n].ljust(n)   # noqa: E731
        kw = dict(CorrelId=m['correl_id'], MsgType=m.get('tipo') or C.MQMT_DATAGRAM,
                  Format=b(m['formato'], 8) if m.get('formato') is not None else C.MQFMT_STRING,
                  CodedCharSetId=self.gm.ccsid_resposta, Persistence=m.get('persistencia', C.MQPER_PERSISTENCE_AS_Q_DEF))
        if m.get('msg_id') is not None:
            kw['MsgId'] = m['msg_id']
        for chave, campo, n in (('reply_to_q', 'ReplyToQ', 48), ('reply_to_qmgr', 'ReplyToQMgr', 48)):
            if m.get(chave) is not None:
                kw[campo] = b(m[chave], n)
        for chave, campo in (('expiracao', 'Expiry'), ('prioridade', 'Priority'), ('report', 'Report'), ('feedback', 'Feedback')):
            if m.get(chave) is not None:
                kw[campo] = int(m[chave])
        md = pymqi.MD(**kw)
        pmo = pymqi.PMO(Options=(pymqi.CMQC.MQPMO_SYNCPOINT if syncpoint else pymqi.CMQC.MQPMO_NO_SYNCPOINT) | pymqi.CMQC.MQPMO_FAIL_IF_QUIESCING)
        try:
            self.qm.put1(fila, m['dados'].encode(CODEPAGE.get(self.gm.ccsid_resposta, 'latin-1'), errors='replace'), md, pmo)
        except pymqi.MQMIError as e:
            raise MQErro(e.comp, e.reason)
        return bytes(md.MsgId)

    def syncpoint(self, rollback):
        (self.qm.backout if rollback else self.qm.commit)()

    def fim(self):
        try:
            super().fim()   # desfaz o que ficou sem SYNCPOINT e fecha as filas; a conexão fica para a próxima tarefa
        except Exception:   # noqa: BLE001
            self.gm.descartar()   # conexão quebrada: a próxima tarefa abre outra


# ----------------------------------------------------------------------------------------------------------------- DB2: internal
class DB2Memoria:
    """Tabelas em memória compartilhadas pelas transações (massa JSON: {tabela: [linhas]}); uma transação por vez altera o banco."""

    def __init__(self, tabelas):
        self.tabelas = {k.upper(): v for k, v in (tabelas or {}).items()}
        self.trava = threading.RLock()

    def sessao(self, rt, s):
        return _SessaoDB2Memoria(self, s)


class _SessaoDB2Memoria(DB2Stateful):
    """Unidade de trabalho sobre as tabelas compartilhadas: o primeiro comando SQL pega a trava do banco e guarda a imagem para o
    ROLLBACK; o SYNCPOINT (ou o fim da tarefa) confirma ou desfaz e solta a trava. Sem SQL (coordenador esperando a fila), não trava."""

    def __init__(self, banco, s):
        self.banco, self.imagem = banco, None
        super().__init__(banco.tabelas, s.vars)

    def execute(self, sql):
        q = re.sub(r'^\s*EXEC\s+SQL\s+', '', sql, flags=re.I).strip().upper()
        if q.startswith(('COMMIT', 'ROLLBACK')):
            self.syncpoint(q.startswith('ROLLBACK'))
            return {'status': 'OK', 'operation': q.split()[0], 'sqlcode': 0}
        if self.imagem is None:
            self.banco.trava.acquire()
            self.imagem = copy.deepcopy(self.banco.tabelas)
        return super().execute(sql)

    def syncpoint(self, rollback):
        if self.imagem is None:
            return
        if rollback:
            self.banco.tabelas.clear()
            self.banco.tabelas.update(self.imagem)
        self.imagem = None
        self.banco.trava.release()

    def fim(self):
        self.syncpoint(True)

    def consultar(self, sql):
        """SELECT sem variáveis host, para programas nativos: lista de linhas {coluna: valor}; tabela inexistente = erro -204."""
        tab = re.search(r'\bFROM\s+([\w.]+)', sql, re.I)
        if tab and not any(k.split('.')[-1] == tab.group(1).upper().split('.')[-1] for k in self.tables):
            raise ErroSQL(-204, f'{tab.group(1)} não existe')
        r = self.execute('EXEC SQL ' + sql + ' END-EXEC')
        return [{norm(k): v for k, v in x.items()} for x in r.get('rows', [])]


# ----------------------------------------------------------------------------------------------------------------- DB2: external
class DB2Externo:
    """DB2 de verdade pelo cliente ibm_db. esquemas = {'ESQPROG': 'ESQBANCO'}: troca o qualificador das tabelas dos programas pelo do banco."""

    def __init__(self, banco, host, porta, usuario, senha, esquemas=None):
        import ibm_db   # noqa: F401  (só na forma external)
        self.dsn = f'DATABASE={banco};HOSTNAME={host};PORT={porta};PROTOCOL=TCPIP;UID={usuario};PWD={senha};'
        self.esquemas = {k.upper(): v for k, v in (esquemas or {}).items()}

    def sessao(self, rt, s):
        return _SessaoDB2Externa(self, rt, s)

    def conexao(self):
        """Conexão da linha de execução da região, reaproveitada pelas tarefas seguintes (como as threads do DB2ENTRY)."""
        import ibm_db
        local = self.__dict__.setdefault('_local', threading.local())
        if getattr(local, 'conn', None) is None:
            local.conn = ibm_db.connect(self.dsn, '', '')
            ibm_db.autocommit(local.conn, ibm_db.SQL_AUTOCOMMIT_OFF)
        return local.conn

    def descartar(self):
        import ibm_db
        local = self.__dict__.setdefault('_local', threading.local())
        conn, local.conn = getattr(local, 'conn', None), None
        if conn is not None:
            try:
                ibm_db.close(conn)
            except Exception:   # noqa: BLE001
                pass


_HOST = re.compile(r':\s*([A-Z0-9][A-Z0-9-]*(?:\.[A-Z0-9][A-Z0-9-]*)?)(?:\s*(?:INDICATOR\s*)?:\s*([A-Z0-9][A-Z0-9-]*))?', re.I)


class _SessaoDB2Externa:
    def __init__(self, banco, rt, s):
        self.banco, self.rt, self.s = banco, rt, s
        self.conn = banco.conexao()
        self.decl, self.cursores = {}, {}

    @property
    def cursors(self):   # nome usado pelo relatório final do runtime
        return self.cursores

    # -- variáveis host
    def _valor(self, nome, ind=None):
        vs = self.s.vars
        if ind:
            iv = self._le(ind)
            try:
                if iv is not None and float(iv) < 0:
                    return None
            except (TypeError, ValueError):
                pass
        return self._le(nome)

    def _le(self, nome):
        k = norm(nome)
        vs = self.s.vars
        if k in vs:
            return vs[k]
        cauda = k.split('.')[-1]
        alt = [q for q in vs if isinstance(q, str) and (q == cauda or q.endswith('.' + cauda))]
        if len(alt) == 1:
            return vs[alt[0]]
        if '.' in nome:
            g, c = nome.split('.', 1)
            return self.rt.resolve_name(self.s, f'{c} OF {g}')
        return self.rt.resolve_name(self.s, nome)

    def _tipo(self, nome):
        """CAST do marcador pelo PIC da variável host (o DB2 precisa do tipo de um ? em comparações e funções)."""
        _p, dm = getattr(self.rt, '_dm_atual', None) or (None, None)
        it = (dm or {}).get('by_name', {}).get(nome.split('.')[-1].upper()) if dm else None
        if not it or not it.get('pic'):
            return None
        pi = it['picture']
        if pi['category'] == 'NUMERIC':
            d = max(pi['digits'] or 1, 1)
            return f'DECIMAL({min(d, 31)},{pi["scale"] or 0})'
        return f'VARCHAR({max(pi["digits"] or 1, 1)})'

    def _preparar(self, sql):
        """Troca as variáveis host por marcadores (com CAST pelo PIC) e o esquema; OFFSET/FETCH FIRST recebem o número direto."""
        params = []
        for k, v in self.banco.esquemas.items():
            sql = re.sub(rf'\b{re.escape(k)}\.', v + '.', sql, flags=re.I)

        sql = re.sub(r'\b(OFFSET|FETCH\s+FIRST)\s+:\s*([A-Z0-9][\w.-]*)', lambda m: f'{m.group(1)} {int(float(self._valor(m.group(2)) or 0))}',
                     sql, flags=re.I)

        def troca(m):
            params.append(_db2(self._valor(m.group(1), m.group(2))))
            t = self._tipo(m.group(1))
            return f'CAST(? AS {t})' if t else '?'
        texto = _HOST.sub(troca, sql)
        if os.environ.get('CICS_HOST_SQL'):
            print(f'SQL> {re.sub(chr(92) + "s+", " ", texto)[:400]} {params}', flush=True)
        return texto, params

    def execute(self, sql):
        import ibm_db
        q = re.sub(r'^\s*EXEC\s+SQL\s+', '', sql, flags=re.I)
        q = re.sub(r'\s*END-EXEC\.?\s*$', '', q, flags=re.I).strip()
        try:
            m = re.match(r'SET\s*:\s*([\w.-]+)\s*=\s*(CURRENT[_ ](?:TIMESTAMP|DATE|TIME))', q, re.I)
            if m:
                st = ibm_db.exec_immediate(self.conn, f'VALUES {m.group(2).replace("_", " ")}')
                v = _cobol(ibm_db.fetch_tuple(st)[0])
                return {'status': 'OK', 'operation': 'SET', 'into': {norm(m.group(1)): v}, 'sqlcode': 0}
            if re.match(r'(COMMIT|ROLLBACK)\b', q, re.I):
                (ibm_db.commit if q.upper().startswith('COMMIT') else ibm_db.rollback)(self.conn)
                return {'status': 'OK', 'operation': q.split()[0].upper(), 'sqlcode': 0}
            m = re.match(r'DECLARE\s+([\w-]+)\s+CURSOR\s+(?:WITH\s+HOLD\s+)?FOR\s+(.+)', q, re.I | re.S)
            if m:
                self.decl[norm(m.group(1))] = m.group(2)
                return {'status': 'OK', 'operation': 'DECLARE_CURSOR', 'sqlcode': 0}
            m = re.match(r'OPEN\s+([\w-]+)', q, re.I)
            if m:
                c = norm(m.group(1))
                texto, params = self._preparar(self.decl[c])
                st = ibm_db.prepare(self.conn, texto)
                ibm_db.execute(st, tuple(params))
                self.cursores[c] = st
                return {'status': 'OK', 'operation': 'OPEN_CURSOR', 'cursor': c, 'sqlcode': 0}
            m = re.match(r'FETCH\s+(?:NEXT\s+)?(?:FROM\s+)?([\w-]+)\s+INTO\s*(.+)', q, re.I | re.S)
            if m:
                hs = [norm(x.group(1)) for x in _HOST.finditer(m.group(2))]
                st = self.cursores[norm(m.group(1))]
                row = ibm_db.fetch_tuple(st)
                if not row:
                    return {'status': 'OK', 'operation': 'FETCH', 'into': {}, 'row_count': 0, 'sqlcode': 100}
                return {'status': 'OK', 'operation': 'FETCH', 'into': dict(zip(hs, _tipados(st, row))), 'row_count': 1, 'sqlcode': 0}
            m = re.match(r'CLOSE\s+([\w-]+)', q, re.I)
            if m:
                st = self.cursores.pop(norm(m.group(1)), None)
                if st:
                    ibm_db.free_result(st)
                return {'status': 'OK', 'operation': 'CLOSE_CURSOR', 'sqlcode': 0}
            m = re.match(r'(SELECT\b.*?)\bINTO\b(.+?)\bFROM\b(.*)$', q, re.I | re.S)
            if m:
                hs = [norm(x.group(1)) for x in _HOST.finditer(m.group(2))]
                texto, params = self._preparar(m.group(1) + ' FROM ' + m.group(3))
                st = ibm_db.prepare(self.conn, texto)
                ibm_db.execute(st, tuple(params))
                row = ibm_db.fetch_tuple(st)
                if not row:
                    return {'status': 'OK', 'operation': 'SELECT', 'into': {}, 'sqlcode': 100, 'row_count': 0}
                mais = ibm_db.fetch_tuple(st)
                ibm_db.free_result(st)
                if mais:
                    return {'status': 'OK', 'operation': 'SELECT', 'into': dict(zip(hs, _tipados(st, row))), 'sqlcode': -811, 'row_count': 1}
                return {'status': 'OK', 'operation': 'SELECT', 'into': dict(zip(hs, _tipados(st, row))), 'sqlcode': 0, 'row_count': 1}
            op = q.split()[0].upper()
            texto, params = self._preparar(q)
            st = ibm_db.prepare(self.conn, texto)
            ibm_db.execute(st, tuple(params))
            n = ibm_db.num_rows(st)
            return {'status': 'OK', 'operation': op, 'affected': n, 'sqlcode': 100 if op in ('UPDATE', 'DELETE') and n == 0 else 0}
        except Exception as e:   # noqa: BLE001
            msg = str(e) + ' ' + (ibm_db.stmt_errormsg() or '')
            m = re.search(r'SQLCODE=(-?\d+)', msg)
            if not m:
                raise
            return {'status': 'OK', 'operation': q.split()[0].upper(), 'into': {}, 'sqlcode': int(m.group(1)), 'erro': msg.strip()[:300]}

    def syncpoint(self, rollback):
        import ibm_db
        (ibm_db.rollback if rollback else ibm_db.commit)(self.conn)

    def consultar(self, sql):
        """SELECT sem variáveis host, para programas nativos: lista de linhas {coluna: valor}."""
        import ibm_db
        q, _ = self._preparar(sql)
        try:
            st = ibm_db.exec_immediate(self.conn, q)
        except Exception as e:   # noqa: BLE001
            m = re.search(r'SQLCODE=(-?\d+)', str(e) + ' ' + (ibm_db.stmt_errormsg() or ''))
            raise ErroSQL(int(m.group(1)) if m else -999, str(e)[:300])
        nomes = [ibm_db.field_name(st, i).upper() for i in range(ibm_db.num_fields(st))]
        out, row = [], ibm_db.fetch_tuple(st)
        while row:
            out.append(dict(zip(nomes, _tipados(st, row))))
            row = ibm_db.fetch_tuple(st)
        return out

    def fim(self):
        import ibm_db
        for st in self.cursores.values():
            try:
                ibm_db.free_result(st)
            except Exception:   # noqa: BLE001
                pass
        try:
            ibm_db.rollback(self.conn)   # o que ficou sem SYNCPOINT é desfeito; a conexão fica para a próxima tarefa
        except Exception:   # noqa: BLE001
            self.banco.descartar()   # conexão quebrada: a próxima tarefa abre outra


def _tipados(st, row):
    """Linha do ibm_db com os tipos do COBOL: DECIMAL/NUMERIC vêm como texto do driver e viram número pelo tipo da coluna."""
    import ibm_db
    out = []
    for i, v in enumerate(row):
        if isinstance(v, str) and ibm_db.field_type(st, i) in ('decimal', 'numeric', 'real', 'float', 'double'):
            v = Decimal(v)
        out.append(_cobol(v))
    return out


def _db2(v):
    if isinstance(v, str):
        return v.rstrip() if v.strip() else v[:1]
    return v


def _cobol(v):
    """Valor do DB2 para o campo COBOL: DECIMAL inteiro vira int; data 'AAAA-MM-DD'; timestamp 'AAAA-MM-DD-HH.MM.SS.NNNNNN'."""
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() and v.as_tuple().exponent >= 0 else float(v)
    # ano com 4 dígitos sempre (o strftime não completa anos < 1000: 0001-01-01 sairia 1-01-01)
    if isinstance(v, _dt.datetime):
        return f'{v.year:04d}-{v.month:02d}-{v.day:02d}-{v.hour:02d}.{v.minute:02d}.{v.second:02d}.{v.microsecond:06d}'
    if isinstance(v, _dt.date):
        return f'{v.year:04d}-{v.month:02d}-{v.day:02d}'
    if isinstance(v, _dt.time):
        return f'{v.hour:02d}.{v.minute:02d}.{v.second:02d}'
    return v


def copia(x):
    return copy.deepcopy(x)
