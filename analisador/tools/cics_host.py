#!/usr/bin/env python3
"""Host CICS local: executa programas COBOL (interpretados pelo runtime do analisador, sem compilar) como transações disparadas por fila,
para desenvolver e testar os programas no ambiente local.

  python3 cics_host.py <config.json>

Duas formas (chave "modo"):
  internal — IBM MQ e DB2 em memória, dentro do processo: as filas e a massa do banco vêm da configuração, a mensagem confirmada numa fila
             com transação associada dispara a transação (gatilho FIRST) e a API HTTP grava e lê mensagens e consulta as tabelas;
  external — IBM MQ e DB2 de verdade: o monitor de gatilho (como o CKTI) lê a mensagem de disparo (MQTM) da fila de iniciação, acha a
             transação pelo APPLICID do processo e inicia o programa; o SQL roda no DB2 e as chamadas da MQI vão ao queue manager.

Nas duas formas, cada transação é uma tarefa: o programa recebe a mensagem de disparo no RETRIEVE, LINK/canal/containers/SYNCPOINT são do
runtime (memória em bytes nas fronteiras: fila, container e MOVE entre grupo e área) e o SYNCPOINT confirma o DB2 e depois o MQ; o que
ficou sem SYNCPOINT no fim da tarefa é desfeito. Programas chamados podem ser: executados (fonte nas pastas), nativos (Python, para
programas sem fonte: módulo "nativos" com o dicionário NATIVOS = {programa: função(runtime, estado)}) ou mockados ("mocks", no mesmo
formato dos cenários do tools/run_scenarios.py: returns, scenarios com when, default).

API HTTP: / (painel), /status, /saude, GET /cemt (CEMT INQUIRE TRANSACTION), POST /cemt?transacao=X&estado=ENABLED|DISABLED (CEMT SET),
POST /executar?transacao=X; na forma internal também /mq/<fila> (gravar e ler; na gravação, os cabeçalhos replyTo e replyToQMgr dão
a fila de resposta do pedido) e /db2/<tabela>.

Recursos como no CICS e no MQ: "csd" (um ou mais arquivos DFHCSDUP) instala as transações (DEFINE TRANSACTION ... PROGRAM) e os
programas (DEFINE PROGRAM) da região; "programas_adicionais" instala programas de outros grupos (por exemplo corporativos); LINK para
programa não instalado devolve PGMIDERR. "mqsc" (um ou mais arquivos RUNMQSC) dá a fila e a fila de iniciação de cada transação pelos
gatilhos (QLOCAL TRIGGER PROCESS -> PROCESS APPLICID) e, na forma internal, as filas em memória.

Configuração (texto ${VAR} ou ${VAR:-padrão} é trocado pela variável de ambiente):
  {"modo": "internal|external", "regiao": "nome nos logs", "fontes": [pastas], "programas": [programas a carregar; vazio = todos],
   "transacoes": {"TRN1": {"programa": "PROG1XXX", "fila": "fila de pedido"}}, "instancias": 4, "max_passos": 5000000,
   "mocks": {...}, "nativos": "arquivo.py", "http": 8080, "log_eventos": ["programa", "sql", "mq", "cics"],
   "internal": {"filas": [...], "aliases": {"alias": "fila"}, "massa": "massa.json"},
   "external": {"mq": {"host", "porta", "qmgr", "canal", "usuario", "senha", "initq"},
                "db2": {"banco", "host", "porta", "usuario", "senha", "esquemas": {"ESQPROG": "ESQBANCO"}}}}
"""
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / 'semantic_core'))
sys.path.insert(0, str(AQUI.parent / 'fases'))
from cobol_ast_runtime import Runtime  # noqa: E402
import host_backends as hb  # noqa: E402

EVENTOS = {'programa': ('ENTER_PROGRAM', 'RETURN_PROGRAM'), 'sql': ('SQL_RESULT',), 'mq': ('MQ_OPEN', 'MQ_GET', 'MQ_PUT'),
           'cics': ('CICS_SYNCPOINT', 'CICS_WRITEQ', 'CICS_LINK_FALHOU', 'CICS_PUT_CONTAINER', 'CICS_GET_CONTAINER')}


def ler_config(caminho):
    texto = Path(caminho).read_text(encoding='utf-8')
    texto = re.sub(r'\$\{(\w+)(?::-([^}]*))?\}', lambda m: os.environ.get(m.group(1), m.group(2) or ''), texto)
    cfg = json.loads(texto)
    base = Path(caminho).resolve().parent
    cfg['_base'] = base
    return cfg


def _lista(v):
    return [x.strip() for x in v.split(',')] if isinstance(v, str) else list(v or [])


def log(regiao, trace, texto):
    print(f'{datetime.now():%H:%M:%S.%f}'[:-3] + f' [traceId={trace or "NO_TRACE"}] {regiao} — {texto}', flush=True)


# ------------------------------------------------------------------------------------------------------------------------ recursos
def _comandos(caminho, continua='+'):
    """Comandos de um arquivo de definições (CSD do CICS ou MQSC): sem comentários ('*' na coluna 1), linhas de continuação juntadas."""
    out, atual = [], ''
    for linha in Path(caminho).read_text(encoding='utf-8', errors='replace').splitlines():
        if linha.startswith('*') or not linha.strip():
            continue
        s = linha.rstrip()
        if continua:   # MQSC: '+' no fim continua o comando na linha seguinte
            atual += (s[:-1] if s.endswith(continua) else s) + ' '
            if not s.endswith(continua):
                out.append(atual.strip())
                atual = ''
            continue
        if atual and linha.startswith(' '):   # CSD: a continuação é a linha seguinte recuada
            atual += ' ' + s.strip()
            continue
        if atual:
            out.append(atual.strip())
        atual = s
    if atual.strip():
        out.append(atual.strip())
    return out


def _atributos(cmd):
    return {k.upper(): v for k, _q, v in re.findall(r"(\w+)\(('?)([^')]*)\2\)", cmd)}


def ler_csd(caminhos):
    """DEFINE TRANSACTION/PROGRAM/DB2ENTRY de um ou mais CSD (formato DFHCSDUP): {'transacoes': {tran: programa}, 'programas': {...}}."""
    trans, progs, outros = {}, set(), []
    for c in ([caminhos] if isinstance(caminhos, str) else caminhos):
        cmds = _comandos(c, continua=None)
        for cmd in cmds:
            m = re.match(r'DEFINE\s+(\w+)\((\w+)\)', cmd, re.I)
            if not m:
                continue
            tipo, nome, at = m.group(1).upper(), m.group(2).upper(), _atributos(cmd)
            if tipo == 'TRANSACTION':
                trans[nome] = at.get('PROGRAM', '').upper()
            elif tipo == 'PROGRAM':
                progs.add(nome)
            else:
                outros.append(f'{tipo}({nome})')
    return {'transacoes': trans, 'programas': progs, 'outros': outros}


def ler_mqsc(caminhos):
    """DEFINE/ALTER QLOCAL, QREMOTE, QALIAS e PROCESS de um ou mais MQSC: {'filas': {nome: (tipo, atributos)}, 'processos': {...}}."""
    filas, processos = {}, {}
    for c in ([caminhos] if isinstance(caminhos, str) else caminhos):
        for cmd in _comandos(c):
            m = re.match(r"(DEFINE|ALTER)\s+(QLOCAL|QREMOTE|QALIAS|PROCESS)\('([^']+)'\)(.*)$", cmd, re.I)
            if not m:
                continue
            tipo, nome, at = m.group(2).upper(), m.group(3), _atributos(m.group(4))
            at['TRIGGER'] = bool(re.search(r'(?<!NO)TRIGGER\b', m.group(4), re.I)) or (filas.get(nome, ('', {}))[1].get('TRIGGER', False))
            if tipo == 'PROCESS':
                processos[nome] = {**processos.get(nome, {}), **at}
            else:
                filas[nome] = (tipo, {**filas.get(nome, ('', {}))[1], **at})
    return {'filas': filas, 'processos': processos}


def gatilhos(mq):
    """Transação disparada por fila (gatilho FIRST/EVERY): {transação: {'fila': nome, 'initq': fila de iniciação}}."""
    out = {}
    for nome, (tipo, at) in mq['filas'].items():
        if tipo == 'QLOCAL' and at.get('TRIGGER') and at.get('PROCESS') in mq['processos']:
            tran = mq['processos'][at['PROCESS']].get('APPLICID', '').strip().upper()
            if tran:
                out[tran] = {'fila': nome, 'initq': at.get('INITQ')}
    return out


# ------------------------------------------------------------------------------------------------------------------------ fontes
STUBS = AQUI.parent / 'fases' / 'stubs-ibm'   # books da plataforma IBM (SQLCA e books do MQ) para os fontes que não os trazem


def montar_fontes(pastas, destino):
    """Copia os fontes para uma pasta só (o último arquivo com o mesmo nome prevalece) e completa com os stubs IBM que faltarem."""
    if destino.exists():
        shutil.rmtree(destino)
    destino.mkdir(parents=True)
    nomes = set()
    for p in pastas:
        for f in Path(p).rglob('*'):
            if f.is_file() and f.suffix.upper() in ('.CBL', '.COB', '.CPY', '.CPB', '.TXT') and f.parent.name.upper() != 'RECURSOS':
                alvo = destino / f.parent.name / f.name
                alvo.parent.mkdir(exist_ok=True)
                shutil.copyfile(f, alvo)
                nomes.add(f.stem.upper())
    (destino / 'STUBS').mkdir()
    usados = []
    for f in STUBS.glob('*.CPY'):
        if f.stem.upper() not in nomes:
            shutil.copyfile(f, destino / 'STUBS' / f.name)
            usados.append(f.stem)
    return sorted(usados)


def carregar_programas(cfg):
    """Fontes das pastas numa pasta só (stubs IBM que faltarem), COPY expandido; devolve {PROGRAM-ID: fonte expandido}."""
    from static_model import library, discover_sources, expand_file
    work = Path(tempfile.mkdtemp(prefix='cics-host-'))
    montar_fontes([(cfg['_base'] / p) for p in cfg['fontes']], work / 'fontes')
    lista = cfg.get('programas') or []
    quero = {p.strip().upper() for p in (lista.split(',') if isinstance(lista, str) else lista) if p.strip()}
    if cfg.get('_instalados'):   # região com CSD: só os programas definidos (e os adicionais) são instalados
        quero = set(cfg['_instalados'])
    lib = library(work / 'fontes')
    out = {}
    for f in discover_sources(work / 'fontes'):
        lines, _o, _r = expand_file(f, lib)
        texto = '\n'.join(lines) + '\n'
        m = re.search(r'PROGRAM-ID\.\s*([A-Z0-9-]+)', texto, re.I)
        pid = (m.group(1) if m else f.stem).upper()
        if quero and pid not in quero:
            continue
        alvo = work / 'expandido' / f'{pid}.CBL'
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text(texto, encoding='latin-1')
        out[pid] = str(alvo)
    shutil.rmtree(work / 'fontes', ignore_errors=True)
    return out


def carregar_nativos(cfg):
    if not cfg.get('nativos'):
        return {}
    spec = importlib.util.spec_from_file_location('nativos_host', cfg['_base'] / cfg['nativos'])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return dict(getattr(mod, 'NATIVOS', {}))


# ------------------------------------------------------------------------------------------------------------------------ runtime
class _Campos(dict):
    """Campos do programa para os registros: {CAMPO} ou {CAMPO OF GRUPO} vira o valor (texto sem brancos à direita)."""
    def __init__(self, rt, s):
        super().__init__()
        self.rt, self.s = rt, s

    def __missing__(self, k):
        return str(self.rt.resolve_name(self.s, k)).rstrip()


class RuntimeHost(Runtime):
    """Runtime da tarefa: não guarda o rastro inteiro (a transação pode ler muitas mensagens); publica os eventos escolhidos no log e no painel."""

    def __init__(self, host, tarefa, *a, **k):
        super().__init__(*a, **k)
        self.host, self.tarefa = host, tarefa

    def event(self, s, event, **data):
        s.seq += 1
        if event in ('RETURN_PROGRAM', 'RETURN_PERFORM'):
            s.depth = max(0, s.depth - 1)
        if event in ('ENTER_PROGRAM', 'ENTER_PERFORM'):
            s.depth += 1
        self.host._rt_local.s = s
        if event == 'SQL_EXECUTE':
            self._sql = data.get('sql')
            return
        if event not in self.host.eventos:
            return
        self.host.publicar(self.tarefa, getattr(s, 'trace_id', None), event, data, getattr(self, '_sql', None))


class Host:
    def __init__(self, cfg):
        self.cfg = cfg
        self.regiao = cfg.get('regiao') or 'CICS'
        self.modo = cfg.get('modo', 'internal')
        self.transacoes = {k.upper(): v for k, v in (cfg.get('transacoes') or {}).items()}
        self.mq_defs = ler_mqsc([cfg['_base'] / x for x in _lista(cfg.get('mqsc'))]) if cfg.get('mqsc') else None
        if cfg.get('csd'):   # recursos da região instalados do CSD, como no CICS: transações e programas definidos
            csd = ler_csd([cfg['_base'] / x for x in _lista(cfg['csd'])])
            self.transacoes.update({t: {'programa': p} for t, p in csd['transacoes'].items()})
            cfg['_instalados'] = csd['programas'] | {p.upper() for p in _lista(cfg.get('programas_adicionais'))}
            log(self.regiao, None, f"CSD instalado: {len(csd['transacoes'])} transações, {len(csd['programas'])} programas"
                                   + (f", também {', '.join(csd['outros'][:3])}{'...' if len(csd['outros']) > 3 else ''}" if csd['outros'] else ''))
        if self.mq_defs:   # fila e fila de iniciação de cada transação, pelos gatilhos do MQSC
            for tran, g in gatilhos(self.mq_defs).items():
                if tran in self.transacoes:
                    self.transacoes[tran].setdefault('fila', g['fila'])
                    self.transacoes[tran].setdefault('initq', g['initq'])
        self.mocks = {k.upper(): v for k, v in (cfg.get('mocks') or {}).items()}
        self.programas = {p: f for p, f in carregar_programas(cfg).items() if p not in self.mocks}
        self.nativos = carregar_nativos(cfg)
        self.registros = {k.upper(): v for k, v in (cfg.get('registros') or {}).items()}
        self._rt_local = threading.local()
        self.eventos = {e for g in cfg.get('log_eventos', ['programa', 'sql', 'mq', 'cics']) for e in EVENTOS[g]}
        self.pool = ThreadPoolExecutor(max_workers=int(cfg.get('instancias', 4)), thread_name_prefix='tarefa')
        self.seq = 0
        self.trava = threading.Lock()
        self.ativas = {}
        self.desabilitadas = set()   # CEMT SET TRANSACTION(x) DISABLED
        self.historico = deque(maxlen=200)
        self.ultimos = deque(maxlen=500)
        if self.modo == 'internal':
            ic = cfg.get('internal', {})
            filas = set(ic.get('filas', [])) | {t['fila'] for t in self.transacoes.values() if t.get('fila')}
            if self.mq_defs:   # filas definidas no MQSC (locais e remotas viram filas em memória com o próprio nome)
                filas |= {n for n, (tp, _a) in self.mq_defs['filas'].items() if tp in ('QLOCAL', 'QREMOTE')}
            self.mq = hb.MQMemoria(filas, ic.get('aliases'))
            massa = json.loads((cfg['_base'] / ic['massa']).read_text(encoding='utf-8')) if ic.get('massa') else {}
            self.db2 = hb.DB2Memoria(massa)
            for tran, t in self.transacoes.items():
                if t.get('fila'):
                    self.mq.gatilhos[self.mq.real(t['fila'])] = (lambda f, tr=tran: self.iniciar(tr, f))
        else:
            ec = cfg['external']
            m = ec['mq']
            self.mq = hb.MQExterno(m['host'], m['porta'], m['qmgr'], m['canal'], m.get('usuario'), m.get('senha'), int(m.get('ccsid_resposta', 37)))
            d = ec['db2']
            self.db2 = hb.DB2Externo(d['banco'], d['host'], d['porta'], d['usuario'], d['senha'], d.get('esquemas'))
        log(self.regiao, None, f'região {self.regiao} ({self.modo}): {len(self.programas)} programas, {len(self.nativos)} nativos, '
                               f'{len(self.mocks)} mocks; transações ' + ', '.join(f'{k}={v["programa"]}' for k, v in self.transacoes.items()))

    # -- tarefas
    def iniciar(self, tran, fila):
        if tran in self.desabilitadas:   # como no CICS: o disparo não inicia a tarefa e a mensagem fica na fila
            log(self.regiao, None, f'{tran}: transação desabilitada (CEMT); disparo da fila {fila} não iniciado')
            return
        self.pool.submit(self.executar, tran, fila)

    def cemt(self, tran, estado):
        """CEMT SET TRANSACTION(tran) ENABLED|DISABLED. Ao habilitar, a transação é iniciada para escoar a fila (o gatilho FIRST não
        dispara de novo enquanto a fila não esvaziar)."""
        tran = tran.upper()
        if tran not in self.transacoes:
            raise KeyError(tran)
        if estado.upper().startswith('DIS'):
            self.desabilitadas.add(tran)
        else:
            self.desabilitadas.discard(tran)
            if self.transacoes[tran].get('fila'):
                self.iniciar(tran, self.transacoes[tran]['fila'])
        log(self.regiao, None, f'CEMT SET TRANSACTION({tran}) {"DISABLED" if tran in self.desabilitadas else "ENABLED"}')
        return self.inquire()

    def inquire(self):
        """CEMT INQUIRE TRANSACTION: transação, programa e estado."""
        return [{'transacao': k, 'programa': v['programa'], 'fila': v.get('fila'), 'estado': 'DISABLED' if k in self.desabilitadas else 'ENABLED'}
                for k, v in sorted(self.transacoes.items())]

    def executar(self, tran, fila):
        prog = self.transacoes[tran]['programa'].upper()
        with self.trava:
            self.seq += 1
            tarefa = {'id': self.seq, 'transacao': tran, 'programa': prog, 'fila': fila, 'inicio': time.time(), 'eventos': deque(maxlen=60)}
            self.ativas[tarefa['id']] = tarefa
        rt = RuntimeHost(self, tarefa, self.programas, mocks=self.mocks, max_steps=int(self.cfg.get('max_passos', 5_000_000)))
        rt.memoria_bytes, rt.ws_por_programa, rt.nativos = True, True, self.nativos   # bytes nas fronteiras e área de trabalho por programa
        rt.pgmiderr = bool(self.cfg.get('csd'))   # LINK para programa não instalado: PGMIDERR, como no CICS
        self._rt_local.rt = rt
        mq = rt.mq_backend = self.mq.sessao()
        sessoes = []
        rt.db2_factory = lambda r, s: sessoes.append(self.db2.sessao(r, s)) or sessoes[-1]
        log(self.regiao, None, f'{tran} tarefa {tarefa["id"]:05d} iniciada: programa {prog}, fila {fila}')
        status, erro = 'ERRO', None
        try:
            r = rt.run(prog, {'name': tran, 'cics_retrieve': {'MQTM-QNAME': fila, 'MQTM-APPLID': tran}})
            status = r['status']
            erro = '; '.join(e['message'] for e in r.get('errors', [])) or None
        except Exception as e:   # noqa: BLE001
            erro = f'{type(e).__name__}: {e}'
            traceback.print_exc()
        finally:
            for x in sessoes:
                x.fim()
            mq.fim()
        dur = time.time() - tarefa['inicio']
        log(self.regiao, None, f'{tran} tarefa {tarefa["id"]:05d} encerrada: {status} em {dur * 1000:.0f} ms' + (f' — {erro}' if erro else ''))
        with self.trava:
            self.ativas.pop(tarefa['id'], None)
            self.historico.appendleft({**{k: v for k, v in tarefa.items() if k != 'eventos'}, 'status': status, 'erro': erro,
                                       'duracao_ms': round(dur * 1000), 'eventos': list(tarefa['eventos'])})

    def registrar(self, rt, s, texto):
        """Linha de log escrita por um programa nativo ou por um registro configurado (mesmo formato dos eventos)."""
        self._linha(rt.tarefa, getattr(s, 'trace_id', None), texto)

    def _linha(self, tarefa, trace, txt):
        linha = f'{tarefa["transacao"]} tarefa {tarefa["id"]:05d} {txt}'
        tarefa['eventos'].append(f'{datetime.now():%H:%M:%S.%f}'[:-3] + ' ' + txt)
        self.ultimos.appendleft({'hora': f'{datetime.now():%H:%M:%S.%f}'[:-3], 'trace': trace, 'texto': linha})
        log(self.regiao, trace, linha)

    def publicar(self, tarefa, trace, ev, d, sql):
        p = d.get('program') or ''
        if ev == 'ENTER_PROGRAM':
            txt = f'{p} iniciado' + (' (nativo)' if d.get('native') else '')
        elif ev == 'RETURN_PROGRAM':
            txt = f'{p} encerrado'
        elif ev == 'SQL_RESULT':
            txt = f'{p} L{d.get("line")} SQL {d.get("operation")} SQLCODE {d.get("sqlcode")}' + (f' linhas {d["affected"]}' if d.get('affected') is not None else '')
            if d.get('erro'):
                txt += ' — ' + str(d['erro'])[:300]
            if os.environ.get('CICS_HOST_SQL') and sql:
                txt += ' — ' + re.sub(r'\s+', ' ', sql)[:300]
        elif ev == 'MQ_GET':
            txt = f'{p} MQGET {d.get("queue")}: ' + (f'mensagem {d.get("message")} ({d.get("tamanho")} posições)' if d.get('message') else f'sem mensagem (reason {d.get("reason")})')
        elif ev == 'MQ_PUT':
            txt = f'{p} MQPUT {d.get("queue")}: correlId {d.get("correl_id")} ({d.get("tamanho")} posições)'
        elif ev == 'MQ_OPEN':
            txt = f'{p} MQOPEN {d.get("queue")}'
        elif ev == 'CICS_SYNCPOINT':
            txt = f'{p} SYNCPOINT' + (' ROLLBACK' if d.get('rollback') else '')
        elif ev == 'CICS_WRITEQ':
            txt = f'{p} WRITEQ {d.get("queue")}: {str(d.get("dados") or "").strip()}'
        elif ev == 'CICS_LINK_FALHOU':
            txt = f'{d.get("caller")} LINK {p} falhou (RESP {d.get("resp")})'
        else:
            txt = f'{p} {ev.replace("CICS_", "")} {d.get("container") or ""}'.strip()
        self._linha(tarefa, trace, txt)
        if ev == 'RETURN_PROGRAM' and p in self.registros:   # registro configurado: linha com campos da área ao fim do programa
            rt, s = getattr(self._rt_local, 'rt', None), getattr(self._rt_local, 's', None)
            if rt is not None:
                try:
                    self._linha(tarefa, trace, self.registros[p].format_map(_Campos(rt, s)))
                except Exception as e:   # noqa: BLE001
                    self._linha(tarefa, trace, f'registro de {p} não montado: {e}')

    # -- monitor de gatilho (external): a mensagem de disparo traz a fila e o APPLICID (a transação)
    def ckti(self):
        import pymqi
        initq = self.cfg['external']['mq'].get('initq') or next((t['initq'] for t in self.transacoes.values() if t.get('initq')), None)
        while True:
            try:
                qm = self.mq.conectar()
                q = pymqi.Queue(qm, initq, pymqi.CMQC.MQOO_INPUT_SHARED | pymqi.CMQC.MQOO_FAIL_IF_QUIESCING)
                log(self.regiao, None, f'CKTI: aguardando mensagens de disparo em {initq}')
                while True:
                    md, gmo = pymqi.MD(), pymqi.GMO(Options=pymqi.CMQC.MQGMO_WAIT | pymqi.CMQC.MQGMO_FAIL_IF_QUIESCING, WaitInterval=5000)
                    try:
                        tm = q.get(None, md, gmo)
                    except pymqi.MQMIError as e:
                        if e.reason == pymqi.CMQC.MQRC_NO_MSG_AVAILABLE:
                            continue
                        raise
                    fila = tm[8:56].decode('latin-1').strip()
                    tran = tm[172:428].decode('latin-1').strip().upper()[:4]
                    if tran in self.transacoes:
                        log(self.regiao, None, f'CKTI: disparo da fila {fila} → transação {tran}')
                        self.iniciar(tran, fila)
                    else:
                        log(self.regiao, None, f'CKTI: disparo da fila {fila} para a transação {tran}, que não é desta região: ignorado')
            except Exception as e:   # noqa: BLE001
                log(self.regiao, None, f'CKTI: {type(e).__name__}: {e}; nova tentativa em 5 s')
                time.sleep(5)

    def partida(self):
        """Na subida, transação com mensagens já esperando na fila (gatilho perdido enquanto a região estava fora) é iniciada."""
        for tran, t in self.transacoes.items():
            if t.get('fila'):
                self.iniciar(tran, t['fila'])

    # -- painel e API
    def estado(self):
        with self.trava:
            ativas = [{**{k: v for k, v in t.items() if k != 'eventos'}, 'eventos': list(t['eventos'])} for t in self.ativas.values()]
            return {'regiao': self.regiao, 'modo': self.modo, 'transacoes': self.transacoes, 'desabilitadas': sorted(self.desabilitadas), 'programas': sorted(self.programas),
                    'nativos': sorted(self.nativos), 'mocks': sorted(self.mocks), 'ativas': ativas, 'historico': list(self.historico)[:50],
                    'eventos': list(self.ultimos)[:200], 'filas': self.mq.estado() if self.modo == 'internal' else None}


PAINEL = '''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Região CICS local</title><style>
:root{--bg:#fff;--fg:#1d2433;--mut:#5b6577;--bd:#d9dee7;--ok:#1e7e34;--er:#b42318;--ac:#1f5fa8}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--fg:#e6e9ef;--mut:#9aa3b2;--bd:#2b313b;--ok:#4cc26b;--er:#ff7a6b;--ac:#7fb0ff}}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif}main{max-width:1200px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:20px 0 6px}.mut{color:var(--mut)}table{border-collapse:collapse;width:100%}
td,th{border-bottom:1px solid var(--bd);padding:4px 6px;text-align:left;vertical-align:top;font-size:13px}th{color:var(--mut);font-weight:600}
code,pre{font:12px ui-monospace,monospace}pre{white-space:pre-wrap;margin:0}.ok{color:var(--ok)}.er{color:var(--er)}.wrap{overflow-x:auto}
</style></head><body><main><h1 id="t">Região CICS local</h1><div class="mut" id="sub"></div>
<h2>Tarefas em execução</h2><div class="wrap"><table id="at"></table></div>
<h2>Últimas tarefas</h2><div class="wrap"><table id="hi"></table></div>
<h2>Filas (internal)</h2><div class="wrap"><table id="fi"></table></div>
<h2>Eventos</h2><pre id="ev"></pre></main><script>
const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
async function f(){try{const d=await (await fetch('status')).json();
document.getElementById('t').textContent='Região '+d.regiao+' ('+d.modo+')';
document.getElementById('sub').textContent='transações: '+Object.entries(d.transacoes).map(([k,v])=>k+'='+v.programa).join(', ')+' · nativos: '+(d.nativos.join(', ')||'—')+' · mocks: '+(d.mocks.join(', ')||'—');
document.getElementById('at').innerHTML='<tr><th>Tarefa</th><th>Transação</th><th>Programa</th><th>Fila</th><th>Eventos</th></tr>'+(d.ativas.map(t=>`<tr><td>${t.id}</td><td>${t.transacao}</td><td>${t.programa}</td><td><code>${esc(t.fila)}</code></td><td><pre>${esc(t.eventos.slice(-8).join('\\n'))}</pre></td></tr>`).join('')||'<tr><td colspan=5 class=mut>nenhuma</td></tr>');
document.getElementById('hi').innerHTML='<tr><th>Tarefa</th><th>Transação</th><th>Programa</th><th>Resultado</th><th>Duração</th><th>Erro</th></tr>'+d.historico.map(t=>`<tr><td>${t.id}</td><td>${t.transacao}</td><td>${t.programa}</td><td class="${t.status=='SUCCESS'?'ok':'er'}">${t.status}</td><td>${t.duracao_ms} ms</td><td>${esc(t.erro||'')}</td></tr>`).join('');
document.getElementById('fi').innerHTML=d.filas?'<tr><th>Fila</th><th>Mensagens</th></tr>'+Object.entries(d.filas).map(([k,v])=>`<tr><td><code>${esc(k)}</code></td><td>${v}</td></tr>`).join(''):'<tr><td class=mut>forma external: as filas estão no IBM MQ</td></tr>';
document.getElementById('ev').textContent=d.eventos.map(e=>e.hora+' ['+(e.trace||'-')+'] '+e.texto).join('\\n');}catch(e){}}
f();setInterval(f,1000);</script></body></html>'''


def servidor(host, porta):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, cod, obj):
            b = json.dumps(obj, ensure_ascii=False, default=str).encode()
            self.send_response(cod)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path in ('/', '/painel'):
                b = PAINEL.encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(b)
            elif u.path == '/status':
                self._json(200, host.estado())
            elif u.path == '/cemt':
                self._json(200, host.inquire())
            elif u.path == '/saude':
                self._json(200, {'ok': True})
            elif u.path.startswith('/mq/') and host.modo == 'internal':
                try:
                    c = q.get('correlId', [None])[0]
                    m = host.mq.ler(u.path[4:], int(q.get('espera', ['0'])[0]), bytes.fromhex(c) if c else None)
                    self._json(200, {'dados': m['dados'], 'msgId': m['msg_id'].hex(), 'correlId': m['correl_id'].hex(), 'backout': m.get('backout', 0)})
                except hb.MQErro as e:
                    self._json(404, {'reason': e.rc})
            elif u.path.startswith('/db2/') and host.modo == 'internal':
                self._json(200, host.db2.tabelas.get(u.path[5:].upper(), []))
            else:
                self._json(404, {'erro': 'não encontrado'})

        def do_POST(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            corpo = self.rfile.read(int(self.headers.get('Content-Length', 0) or 0)).decode('utf-8')
            if u.path.startswith('/mq/') and host.modo == 'internal':
                try:
                    # cabeçalhos replyTo/replyToQMgr: a fila de resposta do pedido (MQMD.ReplyToQ/ReplyToQMgr), como o SRV informa
                    rq = self.headers.get('replyTo') or ''
                    mid = host.mq.gravar(u.path[4:], {'dados': corpo, 'trace_id': self.headers.get('traceId'), 'tipo': 1 if rq else 8,
                                                      'reply_to_q': rq, 'reply_to_qmgr': self.headers.get('replyToQMgr') or ''})
                    self._json(201, {'msgId': mid.hex()})
                except hb.MQErro as e:
                    self._json(404, {'reason': e.rc})
            elif u.path == '/cemt':
                tran, estado = q.get('transacao', [''])[0], q.get('estado', ['ENABLED'])[0]
                try:
                    self._json(200, host.cemt(tran, estado))
                except KeyError:
                    self._json(404, {'erro': f'transação {tran} não definida'})
            elif u.path == '/executar':
                tran = q.get('transacao', [''])[0].upper()
                if tran not in host.transacoes:
                    return self._json(404, {'erro': f'transação {tran} não definida'})
                host.iniciar(tran, host.transacoes[tran].get('fila', ''))
                self._json(202, {'iniciada': tran})
            else:
                self._json(404, {'erro': 'não encontrado'})

    srv = ThreadingHTTPServer(('0.0.0.0', porta), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    host = Host(ler_config(sys.argv[1]))
    if host.cfg.get('http'):
        servidor(host, int(host.cfg['http']))
        log(host.regiao, None, f'painel em http://0.0.0.0:{host.cfg["http"]}/')
    if host.modo == 'external':
        threading.Thread(target=host.ckti, daemon=True).start()
    host.partida()
    threading.Event().wait()


if __name__ == '__main__':
    main()
