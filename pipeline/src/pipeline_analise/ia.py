"""Agentes de IA que executam os prompts do pipeline sem intervenção humana: Claude Code CLI (`claude -p`) e Kiro CLI (`kiro-cli chat --no-interactive`).

Os dois mostram no console, enquanto trabalham, tudo o que fazem (texto da IA, cada ferramenta usada com os argumentos e o resultado) e gravam o
mesmo conteúdo no log do pipeline. A resposta de cada prompt é o arquivo JSON que a IA grava na pasta de saída; o pipeline valida pelo gerador e,
se recusar, devolve a mensagem de erro para a mesma conversa (Claude: `--resume <sessão>`; Kiro: `--resume`, que retoma a conversa da pasta)."""
import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field

ANSI = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]')


@dataclass
class Resultado:
    sessao: str | None = None
    turnos: int | None = None
    custo_usd: float | None = None
    texto_final: str = ''
    erro: str | None = None
    extras: dict = field(default_factory=dict)


class Agente:
    """Base: executa o comando, transmite cada linha ao console (via `log`) e aplica o tempo limite."""
    nome = 'ia'

    def __init__(self, cfg, log, env):
        self.cfg, self.log, self.env = cfg, log, env

    def _env(self):
        # a IA roda como processo independente: sem as variáveis da sessão do Claude Code que eventualmente chamou o pipeline
        return {k: v for k, v in self.env.items() if not (k.startswith('CLAUDE_CODE') or k in ('CLAUDECODE', 'CLAUDE_PID'))}

    def _transmitir(self, cmd, cwd, tempo_limite, ao_ler):
        self.log(f'  [{self.nome}] $ {" ".join(cmd[:2])} … (cwd {cwd})')
        p = subprocess.Popen(cmd, cwd=cwd, env=self._env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding='utf-8', errors='replace', bufsize=1)
        estourou = []

        def vigia():
            fim = time.time() + tempo_limite
            while p.poll() is None:
                if time.time() > fim:
                    estourou.append(True)
                    p.kill()
                    return
                time.sleep(2)
        threading.Thread(target=vigia, daemon=True).start()
        for linha in p.stdout:
            ao_ler(linha.rstrip('\n'))
        p.wait()
        if estourou:
            return p.returncode, f'tempo limite de {tempo_limite} s esgotado'
        return p.returncode, None

    def executar(self, texto, cwd, implementacao=False, extra_dirs=(), sessao=None) -> Resultado:
        raise NotImplementedError


class AgenteClaude(Agente):
    """Claude Code em modo não interativo, com eventos em stream-json (cada mensagem, ferramenta e resultado aparece assim que acontece)."""
    nome = 'claude'

    @staticmethod
    def _curto(v, n=300):
        s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        s = ' '.join(s.split())
        return s if len(s) <= n else s[:n] + ' …'

    def executar(self, texto, cwd, implementacao=False, extra_dirs=(), sessao=None):
        c = self.cfg
        ferr = c['ferramentas_implementacao'] if implementacao else c['ferramentas_isolada']
        cmd = [c['comando'], '-p', texto, '--output-format', 'stream-json', '--verbose', '--permission-mode', 'acceptEdits',
               '--allowedTools', ','.join(ferr), '--max-turns', str(c['max_turnos_implementacao'] if implementacao else c['max_turnos'])]
        for d in extra_dirs:
            cmd += ['--add-dir', str(d)]
        if c.get('modelo'):
            cmd += ['--model', c['modelo']]
        if sessao:
            cmd += ['--resume', sessao]
        res = Resultado()

        def ao_ler(linha):
            try:
                ev = json.loads(linha)
            except ValueError:
                if linha.strip():
                    self.log(f'  [claude] {linha}')
                return
            t = ev.get('type')
            if t == 'system' and ev.get('subtype') == 'init':
                res.sessao = ev.get('session_id')
                self.log(f'  [claude] sessão {res.sessao} · modelo {ev.get("model")}')
            elif t == 'assistant':
                for b in ev.get('message', {}).get('content', []):
                    if b.get('type') == 'text' and b.get('text', '').strip():
                        for ln in b['text'].strip().splitlines():
                            self.log(f'  [claude] {ln}')
                    elif b.get('type') == 'tool_use':
                        self.log(f'  [claude] → {b.get("name")} {self._curto(b.get("input"))}')
                    elif b.get('type') == 'thinking' and b.get('thinking', '').strip():
                        self.log(f'  [claude] (pensando) {self._curto(b["thinking"], 200)}')
            elif t == 'user':
                for b in ev.get('message', {}).get('content', []) if isinstance(ev.get('message', {}).get('content'), list) else []:
                    if b.get('type') == 'tool_result':
                        cont = b.get('content')
                        if isinstance(cont, list):
                            cont = ' '.join(x.get('text', '') for x in cont if isinstance(x, dict))
                        self.log(f'  [claude] ← {"ERRO " if b.get("is_error") else ""}{self._curto(cont, 200)}')
            elif t == 'result':
                res.sessao = ev.get('session_id') or res.sessao
                res.turnos, res.custo_usd, res.texto_final = ev.get('num_turns'), ev.get('total_cost_usd'), str(ev.get('result') or '')
                if ev.get('is_error'):
                    res.erro = f'{ev.get("subtype")}: {res.texto_final[:1000]}'
                self.log(f'  [claude] fim: {ev.get("subtype")} · {res.turnos} turnos · US$ {res.custo_usd}')
        rc, erro = self._transmitir(cmd, cwd, c['tempo_limite_implementacao_s'] if implementacao else c['tempo_limite_s'], ao_ler)
        res.erro = erro or res.erro or (f'código de saída {rc}' if rc else None)
        return res


class AgenteKiro(Agente):
    """Kiro CLI em modo não interativo: a saída da conversa (texto e ferramentas) é transmitida linha a linha, sem os códigos de cor do terminal."""
    nome = 'kiro'

    def executar(self, texto, cwd, implementacao=False, extra_dirs=(), sessao=None):
        c = self.cfg
        cmd = [c['comando'], 'chat', '--no-interactive']
        ferr = c['ferramentas_implementacao'] if implementacao else c['ferramentas_isolada']
        cmd += ['--trust-all-tools'] if ferr == 'todas' else [f'--trust-tools={",".join(ferr)}']
        if c.get('modelo'):
            cmd += ['--model', c['modelo']]
        if c.get('agente'):
            cmd += ['--agent', c['agente']]
        if sessao:
            cmd += ['--resume']   # retoma a última conversa desta pasta (cwd)
        if extra_dirs:
            texto += ' Pastas adicionais que você pode ler: ' + ', '.join(str(d) for d in extra_dirs) + '.'
        cmd.append(texto)
        res = Resultado(sessao=f'kiro:{cwd}')
        ultimas = []

        def ao_ler(linha):
            limpa = ANSI.sub('', linha).rstrip()
            if limpa.strip():
                self.log(f'  [kiro] {limpa}')
                ultimas.append(limpa)
                del ultimas[:-40]
        rc, erro = self._transmitir(cmd, cwd, c['tempo_limite_implementacao_s'] if implementacao else c['tempo_limite_s'], ao_ler)
        res.texto_final = '\n'.join(ultimas[-5:])
        res.erro = erro or (f'código de saída {rc}: ' + ' / '.join(ultimas[-5:]) if rc else None)
        return res


AGENTES = {'claude': AgenteClaude, 'kiro': AgenteKiro}


def criar(nome, cfg_ia, log, env):
    if nome not in AGENTES:
        raise SystemExit(f'agente de IA desconhecido: {nome} (use {", ".join(AGENTES)})')
    cfg = dict(cfg_ia.get('comum', {}))
    cfg.update(cfg_ia.get(nome, {}))
    if not cfg.get('comando'):
        raise SystemExit(f'pipeline.config.json: ia.{nome}.comando não informado')
    if not any(os.access(os.path.join(d, cfg['comando']), os.X_OK) for d in os.environ.get('PATH', '').split(os.pathsep)) and not os.path.isfile(cfg['comando']):
        raise SystemExit(f'comando da IA não encontrado no PATH: {cfg["comando"]} (instale o {nome} CLI ou ajuste ia.{nome}.comando)')
    return AGENTES[nome](cfg, log, env)
