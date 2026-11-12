"""Execução do pipeline da análise: das fontes COBOL ao último relatório (fases 0 a 22), em uma sequência, sem intervenção humana.

Etapas, em ordem (cada uma só começa quando a anterior terminou sem erro):
  0 a 9    determinísticas: tools/analisar.py (análise estática, cenários da análise dinâmica e relatórios); `relatorios` reaproveita a execução dos
           cenários já gravada em <analise>/runtime, `refazer` executa tudo de novo;
  10 a 20  de IA: para cada prompt, a interpretação é reaproveitada se ainda vale (proveniência em ordem e as fases de entrada iguais às da última
           geração) ou refeita por uma IA isolada (Claude CLI ou Kiro CLI, escolhida na chamada), que só vê o prompt e os relatórios que o contrato
           `@ler` do prompt lista; o gerador valida a resposta e, se recusar, a mensagem de erro volta para a mesma conversa da IA (até `tentativas`
           vezes); a resposta aceita é registrada em proveniencia.py (bruto + hash do prompt) e o relatório é gerado; 14 é determinística (XML do PDC);
  21       código gerado: sobe o ambiente local (docker compose), refaz a implementação pelo prompt 12 quando necessário (a IA trabalha no repositório
           do código gerado), roda os testes unitários e ponta a ponta (local/tests/coletar-evidencias.py --executar) e gera o relatório;
  22       decisões de arquitetura (registro do dono da arquitetura, interpretacao-adr/adr.json; não é IA);
  final    referências cruzadas entre os relatórios, verificação dos prompts, da proveniência e da equivalência IA x humano, e MANIFESTO.json.
Registro de cada execução: <trabalho>/execucoes/<data-hora>.json (etapas, tempos, conversas e custo da IA) e <trabalho>/pipeline.log."""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from . import comparacao
from . import ia as agentes

# prompt -> (pasta da interpretação, gerador, fases que o gerador grava, arquivos de saída padrão, fases lidas além do @ler)
PROMPTS = {
    '5': ('interpretacao-sql', 'gerar_sql.py', ['10'], ['mapeamento.json'], []),
    '1': ('interpretacao', 'gerar_simulacao.py', ['11', '13'], ['regras.json'], []),
    '2': ('interpretacao-fluxos', 'gerar_fluxos.py', ['12'], ['funcionalidades.json'], []),
    '4': ('interpretacao-sequencia', 'gerar_sequencia.py', ['12'], ['sequencia.json'], ['00', '01', '05', '11', '12', '13']),
    '6': ('interpretacao-interface', 'gerar_interface.py', ['15'], ['telas.json'], ['11', '12']),
    '7': ('interpretacao-dominio', 'gerar_dominio.py', ['16'], ['dominio.json'], ['11', '12']),
    '8': ('interpretacao-relacao', 'gerar_responsibility_segregation.py', ['17'], ['relacao.json'], []),
    '9': ('interpretacao-contextos', 'gerar_context_discovery.py', ['18'], ['contextos.json'], []),
    '10': ('interpretacao-arquitetura', 'gerar_target_architecture.py', ['19'], ['arquitetura.json'], []),
    '11': ('interpretacao-contratos', 'gerar_contracts.py', ['20'], ['contratos.json'], []),
    '12': ('interpretacao-testes', 'gerar_traceability_to_be.py', ['21'], ['implementacao.json'], []),
    '13': ('interpretacao-design', 'gerar_ui_design.py', ['20a'], ['design.json'], ['15', '19', '20', '22']),
    '14': ('interpretacao-implementacao', 'gerar_implementation.py', ['20b'], ['padroes.json'], ['15', '19', '20', '20a', '22']),
}
NO_REPOSITORIO = ('13', '14')   # prompts que a IA executa no repositório do código gerado (o 12 tem fluxo próprio)
# ordem das etapas: (id, rótulo, prompt de IA ou None)
ETAPAS = [('0-9', 'Fases 0 a 9: análise estática, análise dinâmica e certificação', None),
          ('10', 'Fase 10: mapeamento SQL', '5'), ('11', 'Fases 11 e 13: regras de negócio e rastreabilidade', '1'),
          ('12', 'Fase 12: funcionalidades', '2'), ('12s', 'Fase 12: fluxo interno das funcionalidades', '4'),
          ('14', 'Fase 14: processos PDC', None), ('15', 'Fase 15: interface do usuário', '6'), ('16', 'Fase 16: modelo de domínio', '7'),
          ('17', 'Fase 17: segregação de responsabilidade', '8'), ('18', 'Fase 18: contextos', '9'), ('19', 'Fase 19: arquitetura alvo', '10'),
          ('20', 'Fase 20: contratos', '11'), ('20a', 'Fase 20a: design das aplicações de frontend', '13'), ('20b', 'Fase 20b: design das aplicações dos serviços', '14'),
          ('21', 'Fase 21: casos de teste, evidências e rastreabilidade', '12'),
          ('22', 'Fase 22: Architecture Decision Records', None), ('23', 'Fase 23: Enhancement Proposals', None), ('final', 'Ligações, verificações e MANIFESTO', None)]
ORDEM = [e[0] for e in ETAPAS]


class Falha(Exception):
    pass


# ── configuração e registro ──────────────────────────────────────────────────
class Pipeline:
    def __init__(self, cfg_path, opc):
        cfg = json.loads(Path(cfg_path).read_text(encoding='utf-8'))
        base = Path(cfg_path).resolve().parent
        p = lambda k: (base / cfg[k]).resolve()   # noqa: E731
        self.raiz, self.analise, self.ia_base, self.trabalho = p('raiz_analisador'), p('analise'), p('interpretacoes'), p('trabalho')
        self.fases = self.raiz / 'fases'   # geradores e prompts das fases de IA (o método, agnóstico ao sistema analisado)
        self.fontes, self.cenarios, self.pdc, self.aplicacao, self.projeto = p('fontes'), p('cenarios'), p('pdc'), p('aplicacao'), p('projeto')
        self.cfg_ia, self.opc = cfg['ia'], opc
        self.referencia, self.abaixo = None, []
        if opc.apartada:
            self.preparar_apartada()
        self.trabalho.mkdir(parents=True, exist_ok=True)
        self.estado_f = self.trabalho / 'estado.json'
        self.estado = json.loads(self.estado_f.read_text(encoding='utf-8')) if self.estado_f.exists() else {}
        self.registro = {'inicio': datetime.now().isoformat(timespec='seconds'), 'opcoes': vars(opc), 'etapas': []}
        self.env = dict(os.environ, ANALISE_RAIZ=str(self.raiz), ANALISE_INTERPRETACOES=str(self.ia_base), PYTHONHASHSEED='0')
        cfg_proj = self.cenarios / 'analise.config.json'
        if cfg_proj.exists():
            self.env['ANALISE_CONFIG'] = str(cfg_proj)
        spec = importlib.util.spec_from_file_location('proveniencia', self.fases / 'proveniencia.py')
        self.prov = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.prov)
        self.agente = agentes.criar(opc.ia_cli, self.cfg_ia, self.log, self.env) if opc.ia != 'nunca' else None
        self.tentativas = self.cfg_ia.get('comum', {}).get('tentativas', 3)

    def preparar_apartada(self):
        """Execução apartada: copia a análise de referência e a pasta das interpretações para outra pasta e trabalha só nela; a referência não muda."""
        self.referencia = Path(self.opc.referencia).resolve() if self.opc.referencia else self.analise
        ap = Path(self.opc.apartada).resolve()
        ap.mkdir(parents=True, exist_ok=True)
        ign = shutil.ignore_patterns('__pycache__', '*.cache', '_to_delete')
        if not (ap / 'analise').exists():
            shutil.copytree(self.referencia, ap / 'analise', ignore=ign)
        if not (ap / 'interpretacoes').exists():
            shutil.copytree(self.ia_base, ap / 'interpretacoes', ignore=ign)
        self.analise, self.ia_base, self.trabalho = ap / 'analise', ap / 'interpretacoes', ap / '.pipeline'

    def log(self, msg):
        linha = f'{datetime.now():%H:%M:%S} {msg}'
        print(linha, flush=True)
        with open(self.trabalho / 'pipeline.log', 'a', encoding='utf-8') as f:
            f.write(linha + '\n')

    def rodar(self, cmd, cwd=None, rotulo=None, timeout=None, env=None):
        """Executa um passo mostrando a saída no console (e no log) enquanto ele roda; erro leva o final da saída na mensagem."""
        self.log(f'  $ {" ".join(str(c) for c in cmd)}')
        p = subprocess.Popen([str(c) for c in cmd], cwd=cwd, env=env or self.env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1)
        fim = time.time() + timeout if timeout else None
        cauda = []
        for linha in p.stdout:
            linha = linha.rstrip('\n')
            self.log(f'    {linha}')
            cauda.append(linha)
            del cauda[:-60]
            if fim and time.time() > fim:
                p.kill()
                raise Falha(f'{rotulo or cmd[1]} passou do tempo limite de {timeout} s')
        p.wait()
        if p.returncode != 0:
            raise Falha(f'{rotulo or cmd[1]} terminou com código {p.returncode}:\n' + '\n'.join(cauda[-40:]))
        return '\n'.join(cauda)

    def gravar_estado(self):
        self.estado_f.write_text(json.dumps(self.estado, ensure_ascii=False, indent=1), encoding='utf-8')

    # ── fases e entradas ─────────────────────────────────────────────────────
    def pasta_fase(self, n):
        ps = sorted(self.analise.glob(f'{n}-*')) or sorted(self.analise.glob(f'{n} *'))
        if not ps:
            raise Falha(f'fase {n} não encontrada em {self.analise}')
        return ps[0]

    def entradas(self, n):
        """Fases que a IA do prompt n pode ler: as do contrato @ler e as que o prompt cita no texto (PROMPTS)."""
        txt = (self.fases / self.prov.PROMPTS[n][0]).read_text(encoding='utf-8')
        fases = set(re.findall(r'^@ler fase=(\d\d[a-z]?)', txt, re.M)) | set(PROMPTS[n][4])
        return sorted(fases)

    @staticmethod
    def _normal(v):
        """Relatório sem o que muda a cada execução e não é conteúdo: links entre relatórios e a lista de relatórios ausentes."""
        if isinstance(v, dict):
            if 'text' in v and ('links' in v or 'parts' in v):
                return v['text']
            return {k: Pipeline._normal(x) for k, x in sorted(v.items()) if k not in ('ausentes',)}
        if isinstance(v, list):
            return [Pipeline._normal(x) for x in v]
        return v

    def hash_entradas(self, n):
        h = hashlib.sha256()
        for f in self.entradas(n):
            rel = self.pasta_fase(f) / 'ia' / 'report.json'
            h.update(f.encode())
            h.update(json.dumps(self._normal(json.loads(rel.read_text(encoding='utf-8'))), ensure_ascii=False, sort_keys=True).encode())
        return h.hexdigest()

    def problemas_proveniencia(self, n):
        prompt, pasta = self.prov.PROMPTS[n]
        d, out = self.ia_base / pasta, []
        arqs = [f for f in d.glob('*.json') if f.name != 'PROVENIENCIA.json'] if d.exists() else []
        if not arqs:
            return ['sem interpretação']
        pj = d / 'PROVENIENCIA.json'
        if not pj.exists():
            return ['sem PROVENIENCIA.json']
        reg = json.loads(pj.read_text(encoding='utf-8'))
        if reg['sha256_prompt'] != self.prov.sha(self.fases / prompt):
            out.append('o prompt mudou depois da interpretação')
        for nome in reg['arquivos']:
            atual, bruto = d / nome, self.ia_base / 'bruto' / pasta / nome
            if not atual.exists() or not bruto.exists():
                out.append(f'{nome}: atual ou bruto ausente')
            elif not self.prov.so_remocoes(json.loads(bruto.read_text(encoding='utf-8')), json.loads(atual.read_text(encoding='utf-8'))):
                out.append(f'{nome}: editado à mão')
        return out

    # ── IA isolada ───────────────────────────────────────────────────────────
    def preparar_isolamento(self, n):
        """Pasta da IA: o prompt, as fases que ele pode ler (só o ia/report.json de cada uma; da fase 20, também os contratos) e a pasta de saída."""
        pasta, saida_padrao = PROMPTS[n][0], PROMPTS[n][3]
        d = self.trabalho / 'ia' / f'prompt-{n}'
        if d.exists():
            shutil.rmtree(d)
        (d / 'saida').mkdir(parents=True)
        shutil.copyfile(self.fases / self.prov.PROMPTS[n][0], d / 'PROMPT.md')
        for f in self.entradas(n):
            orig = self.pasta_fase(f)
            dest = d / 'entrada' / orig.name / 'ia'
            dest.mkdir(parents=True)
            shutil.copyfile(orig / 'ia' / 'report.json', dest / 'report.json')
            if (orig / 'ia' / 'contracts').exists():
                shutil.copytree(orig / 'ia' / 'contracts', dest / 'contracts')
        atuais = sorted(f.name for f in (self.ia_base / pasta).glob('*.json') if f.name != 'PROVENIENCIA.json') if (self.ia_base / pasta).exists() else []
        return d, atuais or saida_padrao

    def instrucao(self, n, arquivos, implementacao=False):
        base = (f'Você é a IA isolada que executa o prompt {n} do pipeline da análise. Leia o arquivo PROMPT.md e siga-o à risca: ele é a única fonte de '
                f'instrução. As entradas são os relatórios em entrada/<fase>/ia/report.json (a "pasta da análise" citada no prompt é entrada/); não há '
                f'outras entradas e você não deve procurar arquivos fora desta pasta.')
        if implementacao:
            pasta_ia = self.trabalho / 'ia' / f'prompt-{n}'
            return (f'Você é a IA que executa o prompt {n} do pipeline da análise, no repositório do código gerado (pasta atual). Leia {pasta_ia}/PROMPT.md e '
                    f'siga-o à risca. Os relatórios de entrada estão em {pasta_ia}/entrada/<fase>/ia/report.json (os contratos da fase 20 em '
                    f'entrada/20 - contracts/ia/contracts). Implemente ou corrija o que faltar, escreva e rode os testes, e grave a interpretação '
                    f'(somente JSON) em {pasta_ia}/saida/{arquivos[0]}. Ao terminar, responda só OK.')
        return base + f' Grave a resposta, somente JSON e sem texto fora dele, em saida/ com estes nomes de arquivo: {", ".join(arquivos)}. Ao terminar, responda só OK.'

    # ── etapas ───────────────────────────────────────────────────────────────
    def gerador(self, n):
        g = self.fases / PROMPTS[n][1]
        a = [sys.executable, g, self.analise, self.analise, '--interpretacao', self.ia_base]
        if n == '6':
            a += ['--aplicacao', self.aplicacao, '--pdc', self.pdc, '--cache', self.trabalho / 'cache-interface', '--limite', '100000']
        if n == '12':
            a += ['--projeto', self.projeto, '--resultados', self.projeto / 'local' / 'tests' / 'evidencias' / 'resultados-testes.json']
        if n in NO_REPOSITORIO:
            a += ['--projeto', self.projeto]
        return a

    def etapa_ia(self, n):
        pasta = PROMPTS[n][0]
        if n == '1':
            self.rodar([sys.executable, self.fases / 'podar_interpretacao.py', self.analise, '--interpretacao', self.ia_base], rotulo='poda da interpretação')
        h = self.hash_entradas(n)
        prob = self.problemas_proveniencia(n)
        anterior = self.estado.get(pasta, {}).get('entradas')
        motivo = ('modo sempre' if self.opc.ia == 'sempre' else '; '.join(prob) if prob else
                  'as fases de entrada mudaram desde a última geração' if anterior and anterior != h else None)
        info = {'prompt': n, 'interpretacao': pasta, 'ia': [], 'motivo': motivo}
        if self.opc.apartada:
            if n == '12' or n in NO_REPOSITORIO:
                self.log('  execução apartada: a implementação do código gerado não é refeita (reaproveita a interpretação e os resultados dos testes)')
                self.rodar(self.gerador(n), rotulo=PROMPTS[n][1])
            elif n == '4':
                self.log('  prompt 4 já refeito junto com o prompt 2 (os dois escrevem a fase 12)')
            else:
                self.refazer_ate_parecer(n, info)
            self.estado[pasta] = {'entradas': h, 'gerado_em': datetime.now().isoformat(timespec='seconds')}
            self.gravar_estado()
            return info
        if n == '12':
            self.preparar_fase21(info, motivo)
        elif motivo and self.opc.ia != 'nunca':
            self.refazer_ia(n, motivo, info, implementacao=n in NO_REPOSITORIO)
        else:
            if motivo:
                raise Falha(f'prompt {n} ({pasta}) precisa ser refeito ({motivo}), mas a IA está desligada (--ia nunca)')
            self.log(f'  interpretação {pasta} reaproveitada (proveniência em ordem e entradas iguais)')
            self.rodar(self.gerador(n), rotulo=PROMPTS[n][1])
        self.estado[pasta] = {'entradas': h, 'prompt': self.prov.sha(self.fases / self.prov.PROMPTS[n][0]), 'gerado_em': datetime.now().isoformat(timespec='seconds')}
        self.gravar_estado()
        return info

    def refazer_ia(self, n, motivo, info, implementacao=False, aviso=None):
        pasta = PROMPTS[n][0]
        self.log(f'  prompt {n} ({pasta}) será refeito pela IA: {motivo}')
        d, arquivos = self.preparar_isolamento(n)
        texto = self.instrucao(n, arquivos, implementacao) + (f' {aviso}' if aviso else '')
        cwd = self.projeto if implementacao else d
        sessao = None
        for tentativa in range(1, self.tentativas + 1):
            r = self.agente.executar(texto, cwd, implementacao, extra_dirs=[d] if implementacao else [], sessao=sessao)
            sessao = r.sessao
            info['ia'].append({'cli': self.agente.nome, 'tentativa': tentativa, 'sessao': sessao, 'turnos': r.turnos, 'custo_usd': r.custo_usd, 'erro': r.erro})
            novos = sorted((d / 'saida').glob('*.json'))
            erro = None
            if r.erro and not novos:
                raise Falha(f'a IA ({self.agente.nome}) não concluiu o prompt {n}: {r.erro}')
            if not novos:
                erro = f'nenhum arquivo JSON gravado em saida/ (esperado: {", ".join(arquivos)})'
            else:
                for f in novos:
                    try:
                        json.loads(f.read_text(encoding='utf-8'))
                    except ValueError as e:
                        erro = f'{f.name} não é JSON válido: {e}'
            if not erro:
                destino = self.ia_base / pasta
                reserva = self.trabalho / 'reserva' / pasta
                if reserva.exists():
                    shutil.rmtree(reserva)
                if destino.exists():
                    shutil.copytree(destino, reserva)
                    for f in destino.glob('*.json'):
                        f.unlink()
                destino.mkdir(parents=True, exist_ok=True)
                for f in novos:
                    shutil.copyfile(f, destino / f.name)
                try:
                    if implementacao:
                        self.testes(info)
                    self.rodar(self.gerador(n), rotulo=PROMPTS[n][1])
                except Falha as e:
                    erro = str(e)
                    for f in destino.glob('*.json'):
                        f.unlink()
                    if reserva.exists():
                        for f in reserva.glob('*.json'):
                            shutil.copyfile(f, destino / f.name)
            if not erro:
                self.prov.registrar(self.ia_base, n, d / 'saida', f'{self.agente.nome} CLI (IA isolada; conversa {sessao}; tentativa {tentativa})')
                self.log(f'  prompt {n} aceito pelo gerador na tentativa {tentativa}; proveniência registrada')
                return
            self.log(f'  tentativa {tentativa} recusada: {erro[:400]}')
            texto = (f'O gerador recusou a sua resposta com esta mensagem; corrija pelo prompt (não contorne a validação) e grave de novo os mesmos arquivos '
                     f'em saida/:\n{erro[-6000:]}')
        raise Falha(f'prompt {n} recusado pelo gerador depois de {self.tentativas} tentativas')

    # ── execução apartada: repete até ficar parecido com a referência ─────────
    def _guardar(self, pastas, destino):
        if destino.exists():
            shutil.rmtree(destino)
        for p in pastas:
            for orig, sub in ((self.ia_base / p, 'interpretacao'), (self.ia_base / 'bruto' / p, 'bruto')):
                if orig.exists():
                    shutil.copytree(orig, destino / sub / p)

    def _restaurar(self, pastas, origem):
        for p in pastas:
            for dest, sub in ((self.ia_base / p, 'interpretacao'), (self.ia_base / 'bruto' / p, 'bruto')):
                if (origem / sub / p).exists():
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(origem / sub / p, dest)

    def refazer_ate_parecer(self, n, info):
        """Refaz o prompt (o 2 junto com o 4) com uma conversa nova a cada ciclo até as fases que ele gera ficarem parecidas com a referência
        (nota >= limiar); sem chegar lá no limite de ciclos, fica com o melhor ciclo."""
        grupo = ['2', '4'] if n == '2' else [n]
        fases = sorted({f for g in grupo for f in PROMPTS[g][2]})
        pastas = [PROMPTS[g][0] for g in grupo]
        limiar, max_ciclos = self.opc.limiar, self.opc.ciclos
        melhor, aviso, ciclo = None, None, 0
        info['ciclos'] = []
        while True:
            ciclo += 1
            for g in grupo:
                self.refazer_ia(g, f'execução apartada, ciclo {ciclo}', info, aviso=aviso)
            notas = {f: comparacao.comparar_fase(self.referencia, self.analise, f) for f in fases}
            nota = min(x['nota'] for x in notas.values() if x)
            self.log(f'  ciclo {ciclo}: semelhança com a referência ' + ', '.join(f'fase {f} {x["nota"]:.2f}' for f, x in notas.items() if x)
                     + f' (limiar {limiar:.2f})')
            for f, x in notas.items():
                for d in (x or {}).get('diferencas', [])[:8]:
                    self.log(f'    fase {f}: {d}')
            info['ciclos'].append({'ciclo': ciclo, 'nota': nota, 'fases': {f: {k: v for k, v in x.items() if k != 'diferencas'} for f, x in notas.items() if x}})
            if melhor is None or nota > melhor[0]:
                melhor = (nota, ciclo)
                self._guardar(pastas, self.trabalho / 'melhor' / n)
            if nota >= limiar:
                info['semelhanca'] = {'nota': nota, 'ciclos': ciclo, 'situacao': 'parecido'}
                return
            if max_ciclos and ciclo >= max_ciclos:
                self.log(f'  limite de {max_ciclos} ciclos sem chegar ao limiar: fica o ciclo {melhor[1]} (nota {melhor[0]:.2f})')
                self._restaurar(pastas, self.trabalho / 'melhor' / n)
                for g in grupo:
                    self.rodar(self.gerador(g), rotulo=PROMPTS[g][1])
                info['semelhanca'] = {'nota': melhor[0], 'ciclos': ciclo, 'situacao': 'abaixo do limiar', 'ciclo_escolhido': melhor[1]}
                self.abaixo.append(n)
                return
            if self.opc.realimentar:
                difs = [d for x in notas.values() if x for d in x['diferencas'][:15]]
                aviso = ('Numa execução anterior deste prompt, o relatório gerado divergiu da referência nestes pontos; releia o prompt e as entradas '
                         'e decida de novo, sem copiar valores: ' + '; '.join(difs))

    def comparar_tudo(self):
        linhas = []
        for pasta in sorted(p.name for p in self.referencia.iterdir() if (p / 'ia' / 'report.json').exists()):
            n = pasta.split(' ')[0].split('-')[0]
            r = comparacao.comparar_fase(self.referencia, self.analise, n)
            if r:
                linhas.append({'fase': pasta, **{k: v for k, v in r.items() if k != 'diferencas'}, 'diferencas': r['diferencas'][:10]})
        (self.trabalho.parent / 'comparacao.json').write_text(json.dumps({'referencia': str(self.referencia), 'execucao': str(self.analise),
                                                                          'limiar': self.opc.limiar, 'fases': linhas}, ensure_ascii=False, indent=1), encoding='utf-8')
        self.log('  semelhança de cada fase com a referência:')
        for x in linhas:
            self.log(f'    {x["fase"]:38} {x["nota"]:.2f}  (indicadores {x["indicadores"]:.2f} · estrutura {x["estrutura"]:.2f} · conteúdo {x["conteudo"]:.2f})'
                     + ('' if x['nota'] >= self.opc.limiar else '  ABAIXO DO LIMIAR'))
        return linhas

    def ambiente(self):
        if self.opc.sem_ambiente:
            return
        dc = self.projeto / 'local' / 'docker'
        self.rodar(['docker', 'compose', 'up', '-d', '--build'], cwd=dc, rotulo='docker compose up', timeout=3600)
        for _ in range(90):
            r = subprocess.run(['docker', 'compose', 'ps', '--format', 'json'], cwd=dc, capture_output=True, text=True)
            linhas = [json.loads(ln) for ln in r.stdout.splitlines() if ln.strip()]
            pendentes = [x['Name'] for x in linhas if 'health' in x.get('Status', '') and '(healthy)' not in x['Status']]
            if not pendentes:
                self.log('  ambiente local no ar')
                return
            time.sleep(10)
        raise Falha(f'ambiente local sem saúde depois de 15 min: {pendentes}')

    def testes(self, info):
        if self.opc.sem_testes:
            self.log('  testes não executados (--sem-testes): usa local/tests/evidencias/resultados-testes.json existente')
            return
        saida = self.rodar([sys.executable, self.projeto / 'local' / 'tests' / 'coletar-evidencias.py', '--executar'], cwd=self.projeto,
                           rotulo='testes unitários e ponta a ponta (coletar-evidencias.py --executar)', timeout=7200)
        info['testes'] = saida.splitlines()[-1] if saida else ''

    def preparar_fase21(self, info, motivo):
        self.ambiente()
        if motivo and self.opc.ia != 'nunca':
            self.refazer_ia('12', motivo, info, implementacao=True)
            return
        if motivo:
            raise Falha(f'prompt 12 precisa ser refeito ({motivo}), mas a IA está desligada (--ia nunca)')
        self.testes(info)
        self.rodar(self.gerador('12'), rotulo='gerar_traceability_to_be.py')

    def deterministico(self):
        modo = self.opc.deterministico
        if modo == 'pular':
            return {'modo': modo}
        if modo == 'relatorios' and not (self.analise / 'runtime' / 'runtime-validation.json').exists():
            modo = 'refazer'
        cmd = [sys.executable, self.raiz / 'tools' / 'analisar.py', self.fontes, self.cenarios, self.analise, '--sem-ia']
        if modo == 'relatorios':
            cmd.append('--so-relatorios')
        self.rodar(cmd, cwd=self.raiz, rotulo='tools/analisar.py', timeout=14400)
        return {'modo': modo}

    def final(self):
        sys.path.insert(0, str(self.raiz / 'semantic_core'))
        import report_render
        n = report_render.ligar(self.analise)
        self.log(f'  {n} referências cruzadas ligadas entre os relatórios')
        self.rodar([sys.executable, self.fases / 'prompts' / 'verificar_prompts.py', self.analise], rotulo='verificar_prompts.py')
        try:
            self.rodar([sys.executable, self.fases / 'proveniencia.py', 'verificar', self.ia_base], rotulo='proveniencia.py verificar')
        except Falha as e:
            if not self.opc.apartada:
                raise
            self.log(f'  proveniência com pendências na execução apartada (a implementação do prompt 12 não é refeita nela): {str(e)[:300]}')
        self.rodar([sys.executable, self.raiz / 'tests' / 'relatorios_equivalencia.py', self.analise], cwd=self.raiz, rotulo='relatorios_equivalencia.py')
        sys.path.insert(0, str(self.raiz / 'tools'))
        import analisar
        man = analisar.manifesto(self.analise, self.fontes)
        (self.analise / 'MANIFESTO.json').write_text(json.dumps({'arquivos': man}, indent=1, sort_keys=True), encoding='utf-8')
        out = {'arquivos_no_manifesto': len(man)}
        if self.opc.apartada:
            out['semelhanca'] = self.comparar_tudo()
        return out

    def executar(self):
        ini = ORDEM.index(self.opc.desde) if self.opc.desde else 0
        fim = ORDEM.index(self.opc.ate) if self.opc.ate else len(ORDEM) - 1
        rc = 0
        for eid, rotulo, prompt in ETAPAS[ini:fim + 1]:
            t0 = time.time()
            self.log(f'== {rotulo}')
            item = {'etapa': eid, 'rotulo': rotulo}
            try:
                if eid == '0-9':
                    item.update(self.deterministico())
                elif eid == '14':
                    self.rodar([sys.executable, self.fases / 'gerar_pdc.py', self.analise, self.analise, '--pdc', self.pdc], rotulo='gerar_pdc.py')
                elif eid == '22':
                    self.rodar([sys.executable, self.fases / 'gerar_architecture_decisions.py', self.analise, self.analise, '--projeto', self.projeto,
                                '--interpretacao', self.ia_base], rotulo='gerar_architecture_decisions.py')
                elif eid == '23':
                    self.rodar([sys.executable, self.fases / 'gerar_enhancement_proposals.py', self.analise, self.analise, '--projeto', self.projeto,
                                '--interpretacao', self.ia_base], rotulo='gerar_enhancement_proposals.py')
                elif eid == 'final':
                    item.update(self.final())
                else:
                    item.update(self.etapa_ia(prompt))
                item['situacao'] = 'OK'
            except (Falha, subprocess.TimeoutExpired) as e:
                item['situacao'] = 'FALHA'
                item['erro'] = str(e)
                self.log(f'  FALHA: {e}')
                rc = 1
            item['segundos'] = round(time.time() - t0)
            self.registro['etapas'].append(item)
            self.log(f'   {item["situacao"]} em {item["segundos"]} s')
            if rc:
                break
        self.registro['fim'] = datetime.now().isoformat(timespec='seconds')
        if rc == 0 and self.abaixo:
            rc = 2
        self.registro['situacao'] = 'OK' if rc == 0 else 'FALHA' if rc == 1 else f'ABAIXO DO LIMIAR (prompts {", ".join(self.abaixo)})'
        (self.trabalho / 'execucoes').mkdir(exist_ok=True)
        arq = self.trabalho / 'execucoes' / f'{datetime.now():%Y%m%d-%H%M%S}.json'
        arq.write_text(json.dumps(self.registro, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
        self.log(f'pipeline {self.registro["situacao"]}; registro em {arq}')
        return rc
