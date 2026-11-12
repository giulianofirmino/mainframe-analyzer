#!/usr/bin/env python3
"""Relatório de design das aplicações dos serviços (fase 20b): serviços de domínio, filas, programas mainframe e banco de dados, com a estrutura, as
tecnologias e os padrões e convenções que as próximas implementações dos serviços seguem.

  python3 gerar_implementation.py <pasta-da-analise> [pasta-de-saida] --projeto <repositório> [--interpretacao PASTA]

Calculado do repositório, só para os módulos da camada de serviços (função descrever, também usada pelo design das aplicações de frontend com a camada
'frontend'): os módulos escolhidos pelo tipo de aplicação da arquitetura alvo (fase 19, pela correlação aplicação → módulo da interpretação do prompt 12)
mais a pasta com COBOL, com a pilha, as classes, os testes, o Dockerfile e os perfis de configuração; os pacotes por camada; os programas mainframe em
pares coordenador e funcional (o dígito do funcional vem de programas_mainframe.funcional na configuração da análise), com a transação (arquivo de recursos
CICS), os copybooks, os comandos SQL, os LINK e as seções; as tabelas do banco usadas pelos programas (com o schema e a carga do ambiente local); os
recursos de plataforma (CSD, MQSC, compose). Do registro do prompt 14 (interpretacao-implementacao/padroes.json): os padrões e convenções, com origem
(ADR, fase), exemplos ancorados no código e verificação automática de conformidade (registro_padroes). Uma âncora que não existe recusa o relatório.
Saída: <saida>/20b - implementation/{human/report.html, ia/report.json}."""
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import gerar_target_architecture as TA
import estrutura_repo as ER
import registro_padroes as RP
import report_model as rm

S = TA.S
FASE = '20b - implementation'
INTERP = 'interpretacao-implementacao'
IGNORAR = ('node_modules', 'target', '.git', 'dist', '.angular')
PAPEIS = ['UseCase', 'Resource', 'MQAdapter', 'HttpAdapter', 'Adapter', 'Port', 'Gateway', 'Client', 'Config', 'Properties', 'Filter', 'Handler', 'Exception',
          'Request', 'Response', 'Dto', 'Mapper', 'Layout', 'Application']


def ler(p):
    try:
        return Path(p).read_text(encoding='utf-8')
    except UnicodeDecodeError:
        return Path(p).read_text(encoding='latin-1')
    except FileNotFoundError:
        return ''


def arquivos(base, padrao):
    return sorted(p for p in Path(base).glob(padrao) if p.is_file() and not any(x in IGNORAR for x in p.parts))


def papel(nome):
    return next((s for s in PAPEIS if nome.endswith(s)), 'outro')


def modulos(projeto):
    """(nome, tipo de módulo): módulos Maven do pom raiz, micro frontends (angular.json) e pastas com programas COBOL."""
    pom = ler(Path(projeto) / 'pom.xml')
    out = [(m, 'java') for m in re.findall(r'<module>([^<]+)</module>', pom)]
    out += [(p.parent.name, 'angular') for p in sorted(Path(projeto).glob('*/angular.json'))]
    out += [(p.parent.name, 'cobol') for p in sorted(Path(projeto).glob('*/COBOL')) if p.is_dir()]
    return out


def pacotes_java(mod):
    """Pacotes do módulo (relativos ao pacote-base comum): {pacote: [classes]}."""
    src = mod / 'src' / 'main' / 'java'
    por = defaultdict(list)
    for f in arquivos(src, '**/*.java'):
        por[f.parent.relative_to(src).as_posix()].append(f.stem)
    if not por:
        return '', {}
    partes = [p.split('/') for p in por]
    base = []
    for col in zip(*partes):
        if len(set(col)) == 1:
            base.append(col[0])
        else:
            break
    if len(base) == min(len(p) for p in partes):   # o pacote-base também tem classes: ele fica como raiz
        base = base[:-1] if base else base
    pre = '/'.join(base)
    return pre.replace('/', '.'), {(p[len(pre):].lstrip('/') or '(raiz)'): sorted(c) for p, c in sorted(por.items())}


def angular(mod):
    app = mod / 'src' / 'app'
    por = defaultdict(list)
    for f in arquivos(app, '**/*.ts'):
        if f.name.endswith('.spec.ts'):
            continue
        por[f.parent.relative_to(app).as_posix() or '(raiz)'].append(f.name)
    return {k: sorted(v) for k, v in sorted(por.items())}


def instrucoes(texto):
    """Instruções de um arquivo de recursos com continuação por '+' no fim da linha (MQSC, CSD)."""
    out, cur = [], ''
    for l in texto.splitlines():
        l = l.strip()
        if not l or l.startswith('*'):
            continue
        cur += ' ' + l.rstrip('+').strip()
        if not l.endswith('+'):
            out.append(cur.strip())
            cur = ''
    return out


def recursos_mainframe(mod):
    csd = ' '.join(ler(f) for f in arquivos(mod, '**/*CSD*.txt'))
    mq = [i for f in arquivos(mod, '**/*MQSC*.txt') for i in instrucoes(ler(f))]
    trans = {p: t for t, p in re.findall(r'DEFINE TRANSACTION\((\w+)\)[^\n]*?PROGRAM\((\w+)\)', csd)}
    tipos_mq = Counter(re.match(r'DEFINE (\w+)', i).group(1) for i in mq if re.match(r'DEFINE (\w+)', i))
    return trans, tipos_mq, len(re.findall(r'DEFINE PROGRAM\(', csd))


def programa(f, valores):
    t = ler(f)
    copys = re.findall(r'^\s{7,}COPY\s+(\w+)', t, re.M)
    sql = re.findall(r'EXEC SQL\s+(SELECT|INSERT|UPDATE|DELETE|DECLARE|OPEN|FETCH|CLOSE)\b', t)
    tabelas = sorted(set(re.findall(r'\b(?:FROM|INTO|UPDATE|JOIN)\s+(?:\w+\.)?(T[A-Z0-9_]{4,})', t)))
    links = []
    for alvo in re.findall(r'LINK\s+PROGRAM\s*\(\s*\'?([\w-]+)', t):
        links.append(valores.get(alvo, alvo))
    secoes = len(re.findall(r'^\s{7}[0-9A-Z][\w-]*\s+SECTION\.', t, re.M))
    return copys, Counter(sql), tabelas, sorted(set(links)), secoes


CAMADAS = {'frontend': {'HOST', 'MFE', 'BFMF'}, 'servicos': {'DOMAIN_MICROSERVICE', 'VAS'}}   # tipos de recurso da arquitetura alvo de cada camada


def descrever(projeto, ana, base, camada, fora):
    """Módulos da camada ('frontend': micro frontends e BFF; 'servicos': serviços de domínio, VAS e programas mainframe), escolhidos pelo tipo de
    aplicação da arquitetura alvo, com as tabelas de módulos, pacotes, programas, copybooks, recursos de plataforma e tabelas usadas pelos programas."""
    imp = json.loads((Path(base) / 'interpretacao-testes' / 'implementacao.json').read_text(encoding='utf-8'))
    import gerar_traceability_to_be as TB
    tipos = TB.tipos_aplicacao(ana)
    cfg = json.loads(Path(os.environ['ANALISE_CONFIG']).read_text(encoding='utf-8')) if os.environ.get('ANALISE_CONFIG') else {}
    dig_func = (cfg.get('programas_mainframe') or {}).get('funcional', '3')
    pastas_fora = {Path(projeto) / g.split('*')[0].rstrip('/') for g in fora.get('arquivos', [])}
    apps_do_modulo = defaultdict(list)
    for a in imp['aplicacoes']:
        if a.get('modulo'):
            apps_do_modulo[a['modulo']].append(a['aplicacao'])
    pom_raiz = ler(Path(projeto) / 'pom.xml')
    boot = (re.search(r'<artifactId>spring-boot-starter-parent</artifactId>\s*<version>([^<]+)', pom_raiz) or [None, '?'])[1]
    java = (re.search(r'<java\.version>([^<]+)', pom_raiz) or [None, '?'])[1]

    def da_camada(nome, tipo_mod):
        if nome in fora.get('modulos', []):
            return False
        if tipo_mod == 'angular':
            return camada == 'frontend'
        if tipo_mod == 'cobol':
            return camada == 'servicos'
        return bool({tipos.get(a) for a in apps_do_modulo.get(nome, [])} & CAMADAS[camada])

    t_mod, estrutura, papeis_mod = [], [], defaultdict(Counter)
    progs_mf, copy_rows, plataforma, tab_prog = [], [], [], defaultdict(lambda: {'programas': set(), 'operacoes': Counter()})
    for nome, tipo_mod in [x for x in modulos(projeto) if da_camada(*x)]:
        mod = Path(projeto) / nome
        apps = apps_do_modulo.get(nome, [])
        tipo_app = ', '.join(sorted({tipos.get(a, '?') for a in apps})) or '—'
        cfgs = ', '.join(p.name for p in arquivos(mod / 'src' / 'main' / 'resources', 'application*.y*ml')) or '—'
        docker = 'sim' if (mod / 'Dockerfile').exists() else 'não'
        if tipo_mod == 'java':
            pre, pacs = pacotes_java(mod)
            n_cls = sum(len(c) for c in pacs.values())
            n_test = len(arquivos(mod / 'src' / 'test', '**/*Test.java'))
            t_mod.append((nome, tipo_app, ', '.join(apps) or '— (sem aplicação da arquitetura alvo)', f'Java {java} · Spring Boot {boot}', n_cls, n_test, docker, cfgs))
            for pac, cls in pacs.items():
                camada = pac.split('/')[0]
                estrutura.append((nome, pre, pac.replace('/', '.'), camada, len(cls), ', '.join(cls[:6]) + (f' e mais {len(cls) - 6}' if len(cls) > 6 else '')))
                for c in cls:
                    papeis_mod[nome][papel(c)] += 1
        elif tipo_mod == 'angular':
            pj = ler(mod / 'package.json')
            ng = (re.search(r'"@angular/core":\s*"([^"]+)"', pj) or [None, '?'])[1]
            pastas = {k: v for k, v in angular(mod).items() if (mod / 'src' / 'app' / k) not in pastas_fora}
            n_ts = sum(len(v) for v in pastas.values())
            n_test = len(arquivos(mod / 'src', '**/*.spec.ts'))
            t_mod.append((nome, tipo_app if apps else 'MFE', ', '.join(apps) or '—', f'Angular {ng}', n_ts, n_test, docker, ', '.join(p.name for p in arquivos(mod, '*.conf')) or '—'))
            for pasta, fs in pastas.items():
                estrutura.append((nome, 'src/app', pasta, pasta.split('/')[0], len(fs), ', '.join(fs[:6]) + (f' e mais {len(fs) - 6}' if len(fs) > 6 else '')))
        else:
            cobol = arquivos(mod, 'COBOL/*.CBL')
            copybooks = arquivos(mod, 'COPYBOOK/*.CPY')
            t_mod.append((nome, 'programas mainframe', '—', 'COBOL CICS + DB2 + IBM MQ', len(cobol), 0, docker, ', '.join(p.name for p in arquivos(mod, 'RECURSOS/*.txt')) or '—'))
            valores = dict(re.findall(r"(WRK-[\w-]+)\s+PIC\s+X\(\d+\)\s+VALUE\s+'([\w-]+)'", ' '.join(ler(f) for f in cobol + copybooks)))
            trans, tipos_mq, n_prog_csd = recursos_mainframe(mod)
            usos = defaultdict(set)
            info = {}
            for f in cobol:
                info[f.stem] = programa(f, valores)
                for cp in info[f.stem][0]:
                    usos[cp].add(f.stem)
            coords = [p for p in info if p in trans]
            for c in coords:
                func = c[:4] + dig_func + c[5:]
                cc, cs, ct, cl, csec = info[c]
                fc, fs, ft, fl, fsec = info.get(func, ([], Counter(), [], [], 0))
                for tab in ft:
                    tab_prog[tab]['programas'].add(func)
                    tab_prog[tab]['operacoes'].update(fs)
                progs_mf.append((c, func, trans.get(c, '—'), ', '.join(sorted(set(cc) | set(fc))),
                                 ', '.join(f'{k} {v}' for k, v in sorted((cs + fs).items())) or '—', ', '.join(ft) or '—', ', '.join(fl) or '—', f'{csec} + {fsec}'))
            copy_rows = [(cp, ', '.join(sorted(ps)), len(ps)) for cp, ps in sorted(usos.items())]
            plataforma = [('transações CICS (CSD)', len(trans)), ('programas no CSD', n_prog_csd)] + [(f'MQSC: {k}', v) for k, v in sorted(tipos_mq.items())] + \
                         [('copybooks', len(copybooks)), ('programas COBOL', len(cobol))]
    return {'t_mod': t_mod, 'estrutura': estrutura, 'papeis_mod': papeis_mod, 'progs_mf': progs_mf, 'copy_rows': copy_rows, 'plataforma': plataforma,
            'apps_do_modulo': {m: a for m, a in apps_do_modulo.items() if any(r[0] == m for r in t_mod)}, 'tab_prog': tab_prog, 'pastas_fora': pastas_fora}


def banco(projeto, tab_prog):
    """Tabelas do banco usadas pelos programas: colunas no schema do ambiente local, linhas da carga inicial, operações SQL e programas funcionais."""
    init = Path(projeto) / 'local' / 'docker' / 'db2-init'
    ddl = ' '.join(ler(f) for f in arquivos(init, '*schema*.sql'))
    colunas = {t: len(re.findall(r'^\s+[A-Z][A-Z0-9_]+\s+(?:DECIMAL|CHAR|VARCHAR|DATE|TIMESTAMP|INTEGER|SMALLINT|BIGINT|TIME)', corpo, re.M))
               for t, corpo in re.findall(r'CREATE TABLE \w+\.(\w+)\s*\((.*?)\n\);', ddl, re.S)}
    carga = {}
    for f in arquivos(init, '[0-9][0-9]-*.sql'):
        m = re.match(r'\d\d-(\w+)\.sql$', f.name)
        if m:
            carga[m.group(1)] = len(re.findall(r'^\s+\(', ler(f), re.M))
    linhas = []
    for t in sorted(set(tab_prog) | set(colunas)):
        v = tab_prog.get(t, {'programas': set(), 'operacoes': Counter()})
        linhas.append((t, colunas.get(t, '—'), carga.get(t, '—'), ', '.join(f'{k} {n}' for k, n in sorted(v['operacoes'].items())) or '— (sem programa novo: lida pelos programas corporativos chamados por LINK, ou só carga)',
                       ', '.join(sorted(v['programas'])) or '—'))
    return linhas


def main():
    args = sys.argv[1:]
    opc = {}
    for nome in ('--interpretacao', '--projeto'):
        if nome in args:
            i = args.index(nome)
            opc[nome] = Path(args[i + 1]).resolve()
            del args[i:i + 2]
    if not args or '--projeto' not in opc:
        sys.exit(__doc__)
    base = opc.get('--interpretacao', TA.BASE)
    ana = Path(args[0])
    saida = Path(args[1]) if len(args) > 1 else ana
    projeto = opc['--projeto']
    reg = json.loads((Path(base) / INTERP / 'padroes.json').read_text(encoding='utf-8'))
    fora = reg.get('fora') or {}   # o que não faz parte do recorte (por exemplo, a plataforma de identidade): fora do relatório e das verificações
    erros = []
    achados = RP.validar(reg['padroes'], ana, projeto, erros, 'padrão', fora.get('arquivos', []))
    if erros:
        raise SystemExit('registro de padrões recusado:\n  ' + '\n  '.join(erros))

    d = descrever(projeto, ana, base, 'servicos', fora)
    t_mod, estrutura, papeis_mod, progs_mf, copy_rows, plataforma, apps_do_modulo, tab_prog, pastas_fora = (d[k] for k in (
        't_mod', 'estrutura', 'papeis_mod', 'progs_mf', 'copy_rows', 'plataforma', 'apps_do_modulo', 'tab_prog', 'pastas_fora'))
    t_banco = banco(projeto, tab_prog)
    compose = Path(projeto) / 'local' / 'docker' / 'docker-compose.yml'
    servicos = re.findall(r'^  ([a-z0-9-]+):\s*$', ler(compose), re.M)
    plataforma = (plataforma if progs_mf else []) + [('serviços do docker compose local', len(servicos)), ('ambientes do compose (desenvolvimento e teste)',
                                                                                                            1 + len(arquivos(compose.parent, '*.env'))),
                                                     ('arquivos de carga do DB2', len(arquivos(compose.parent / 'db2-init', '[0-9][0-9]-*.sql')))]
    n_pad, n_verif, n_conf = RP.resumo_conformidade(achados)
    resumo = [('módulos do repositório', len(t_mod)), ('aplicações da arquitetura alvo implementadas', sum(len(v) for v in apps_do_modulo.values())),
              ('classes Java (código principal)', sum(r[4] for r in t_mod if str(r[3]).startswith('Java'))),
              ('casos de uso (classes UseCase)', sum(papeis_mod[m]['UseCase'] for m in papeis_mod)),
              ('adaptadores MQ', sum(papeis_mod[m]['MQAdapter'] for m in papeis_mod)),
              ('pares de programas mainframe (coordenador + funcional)', len(progs_mf)), ('tabelas do banco usadas pelos programas', sum(1 for x in t_banco if x[4] != '—')),
              ('padrões e convenções registrados', n_pad),
              ('padrões com verificação automática', n_verif), ('padrões conformes no repositório', f'{n_conf} de {n_verif}')]
    secs = [
        rm.S('resumo', 'Resumo', [
            *([rm.T('Fora deste relatório', ['Motivo', 'Módulos'], [(fora.get('motivo', ''), ', '.join(fora.get('modulos', [])) or '—')])] if fora else []),
            ]),
        rm.S('aplicacoes', 'Serviços e programas', [
            rm.T('Módulos do repositório', ['Módulo', 'Tipo (arquitetura alvo)', 'Aplicações da arquitetura alvo', 'Pilha', 'Arquivos de código', 'Testes', 'Dockerfile',
                                          'Configuração'], t_mod),
            rm.T('Pacotes e pastas por módulo', ['Módulo', 'Pacote-base', 'Pacote ou pasta', 'Camada', 'Arquivos', 'Exemplos'], estrutura)]),
        rm.S('estrutura', 'Estrutura de diretórios', [rm.COD(ER.arvore(Path(projeto) / r[0], excluir=pastas_fora), f'{r[0]}: pastas com a quantidade de arquivos e os arquivos de topo')
                                                      for r in t_mod] + [
            rm.X('Pastas de build e de dependências (target, node_modules…) não aparecem. Cadeias de pastas com um único filho (os pacotes Java, por exemplo) '
                 'ficam numa linha só.')]),
        rm.S('tecnologias', 'Tecnologias utilizadas', [
            rm.T('Tecnologias das aplicações e dos programas', ['Camada', 'Tecnologia', 'Versão', 'Onde', 'Para que'],
                 ER.tecnologias(projeto, [r[0] for r in t_mod], extra=ER.imagens_compose(compose)),
                 note='Lidas dos pom.xml (versão pelas propriedades e pelo BOM do pom raiz), do package.json, dos Dockerfiles, do docker compose do ambiente local '
                      '(imagens de terceiros) e dos fontes COBOL (EXEC CICS, EXEC SQL, chamadas MQ).')]),
        rm.S('programas', 'Programas mainframe', [
            rm.T('Pares coordenador e funcional', ['Coordenador', 'Funcional', 'Transação', 'Copybooks', 'Comandos SQL', 'Tabelas', 'LINK',
                                                 'Seções (coord. + func.)'], progs_mf,
                 note='Transação do coordenador no arquivo de recursos CICS.'),
            rm.T('Copybooks e programas que os usam', ['Copybook', 'Programas', 'Quantidade'], copy_rows if progs_mf else [])]),
        rm.S('banco', 'Banco de dados', [
            rm.T('Tabelas do banco', ['Tabela', 'Colunas no schema local', 'Linhas na carga inicial', 'Operações SQL dos programas', 'Programas funcionais'], t_banco,
                 note='Operações SQL dos programas funcionais que usam a tabela (EXEC SQL); colunas do schema e linhas da carga inicial do DB2 do ambiente local (db2-init). '
                      'Os serviços não acessam o banco: pedem cada comando pela fila ao programa (Legacy Database Indirect Access).')]),
        rm.S('plataforma', 'Recursos de plataforma', [rm.T('Recursos', ['Recurso', 'Quantidade'], plataforma)]),
        *RP.secoes(reg['padroes'], achados, 'Padrões e convenções', 'padroes', FASE)]
    cards = [rm.card(k, v) for k, v in resumo]   # os números do design em cartões, como na página de entrada
    S.escrever(saida, FASE, rm.model('Design das Aplicações dos Serviços', 'Serviços de domínio, filas, programas mainframe e banco de dados: estrutura, tecnologias e os '
                                                                     'padrões e convenções que as próximas implementações dos serviços seguem', cards, secs))
    print(f'{len(t_mod)} módulos, {len(progs_mf)} pares de programas, {n_pad} padrões ({n_conf}/{n_verif} conformes)')


if __name__ == '__main__':
    main()
