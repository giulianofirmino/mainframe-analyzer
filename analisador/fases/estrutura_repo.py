#!/usr/bin/env python3
"""Estrutura de diretórios e tecnologias de módulos de um repositório, para os relatórios de design das interfaces e de implementação.

arvore(pasta): árvore das pastas com a quantidade de arquivos de cada uma e os arquivos de topo do módulo; cadeias de pastas com um único filho e sem
  arquivos (por exemplo, os pacotes Java br/com/...) ficam numa linha só. Pastas de build e dependências (node_modules, target, dist…) ficam de fora.
tecnologias(projeto, modulos): (tecnologia, versão, onde, finalidade) lidas dos arquivos de build e de execução: dependências e plugins Maven (versão
  resolvida pelas propriedades e pelo BOM do pom raiz), dependências npm (package.json), imagens base dos Dockerfiles e recursos usados nos fontes COBOL
  (EXEC CICS, EXEC SQL, chamadas MQ). A finalidade vem de um mapa por nome de artefato, genérico (nenhum nome do sistema analisado)."""
import json
import re
from collections import defaultdict
from pathlib import Path

IGNORAR = {'node_modules', 'target', 'dist', '.git', '.angular', '.idea', '.vscode', 'coverage', '__pycache__', 'test-results', 'playwright-report'}
FINALIDADE = [   # (trecho do nome do artefato ou da imagem, finalidade): a primeira que casar
    ('spring-boot-starter-web', 'API REST (Spring MVC, Tomcat embutido)'), ('spring-boot-starter-validation', 'Validação de entrada (Bean Validation)'),
    ('spring-boot-starter-actuator', 'Saúde e métricas (Actuator)'), ('spring-boot-starter-security', 'Segurança (Spring Security)'),
    ('oauth2-resource-server', 'Validação de token JWT (OAuth2 resource server)'), ('oauth2-client', 'Login OIDC (OAuth2 client)'),
    ('spring-boot-starter-test', 'Testes (JUnit 5, Mockito, MockMvc)'), ('spring-security-test', 'Testes de segurança'),
    ('spring-boot-maven-plugin', 'Empacotamento executável'), ('openfeign', 'Cliente HTTP declarativo (OpenFeign)'),
    ('mq-jms-spring-boot-starter', 'IBM MQ por JMS no Spring'), ('com.ibm.mq.allclient', 'Cliente IBM MQ'), ('springdoc', 'Documentação OpenAPI (Swagger UI)'),
    ('lombok', 'Redução de código repetitivo (Lombok)'), ('jackson', 'JSON (Jackson)'), ('commons-lang3', 'Utilitários (Apache Commons Lang)'),
    ('jakarta.validation-api', 'API de validação (Jakarta)'), ('org.json', 'JSON (org.json)'), ('json', 'JSON'), ('jacoco', 'Cobertura de testes (JaCoCo)'),
    ('@angular/core', 'Framework do micro frontend (Angular)'), ('@angular/router', 'Rotas'), ('@angular/forms', 'Formulários reativos'),
    ('@angular/animations', 'Animações'), ('@angular/common', 'HttpClient e diretivas comuns'), ('@angular/platform-browser', 'Execução no navegador'),
    ('@angular/compiler', 'Compilação dos templates'), ('@angular/cli', 'Ferramenta de build (Angular CLI)'), ('@angular-devkit/build-angular', 'Build do Angular'),
    ('@angular-builders/custom-webpack', 'Build com webpack customizado (Module Federation)'), ('webpack', 'Empacotamento e Module Federation'),
    ('@types/', 'Tipos do TypeScript'), ('eslint', 'Análise estática (ESLint)'), ('rxjs', 'Programação reativa (RxJS)'), ('zone.js', 'Detecção de mudanças'), ('tslib', 'Auxiliares do TypeScript'), ('typescript', 'Linguagem (TypeScript)'),
    ('tailwindcss', 'Estilos utilitários e tema (Tailwind CSS)'), ('postcss', 'Processamento de CSS'), ('autoprefixer', 'Prefixos de CSS'),
    ('jest-preset-angular', 'Testes unitários de Angular (Jest)'), ('jest-environment-jsdom', 'DOM simulado nos testes'), ('ts-jest', 'TypeScript nos testes'),
    ('jest', 'Testes unitários (Jest)'), ('@playwright/test', 'Testes de ponta a ponta no navegador (Playwright)'),
    ('eclipse-temurin', 'Execução Java (imagem)'), ('maven', 'Build Java (imagem)'), ('node', 'Build do micro frontend (imagem)'), ('nginx', 'Servidor web do micro frontend (imagem)'),
    ('python', 'Execução da região CICS local (imagem)'), ('db2', 'Banco de dados (imagem)'), ('ibm-messaging/mq', 'Filas IBM MQ (imagem)')]


def finalidade(nome):
    return next((f for k, f in FINALIDADE if k in nome), '—')


def _ler(p):
    try:
        return Path(p).read_text(encoding='utf-8')
    except UnicodeDecodeError:
        return Path(p).read_text(encoding='latin-1')
    except FileNotFoundError:
        return ''


def arvore(pasta, max_nivel=7, excluir=()):
    """Árvore textual das pastas do módulo (com a quantidade de arquivos) e os arquivos de topo; excluir = pastas que ficam de fora."""
    pasta = Path(pasta)
    fora = {Path(x).resolve() for x in excluir}

    def filhos(p):
        try:
            itens = sorted(p.iterdir(), key=lambda x: x.name.lower())
        except OSError:
            return [], []
        return ([x for x in itens if x.is_dir() and x.name not in IGNORAR and not x.name.startswith('.') and x.resolve() not in fora],
                [x for x in itens if x.is_file() and not x.name.startswith('.')])

    linhas = [pasta.name + '/']

    def andar(p, prefixo, nivel):
        dirs, _arqs = filhos(p)
        for i, d in enumerate(dirs):
            nome, atual = d.name, d
            while True:   # compacta cadeias com um único filho e sem arquivos (pacotes Java, por exemplo)
                sub, arqs = filhos(atual)
                if len(sub) == 1 and not arqs:
                    atual = sub[0]
                    nome += '/' + atual.name
                else:
                    break
            sub, arqs = filhos(atual)
            ultimo = i == len(dirs) - 1
            linhas.append(f'{prefixo}{"└── " if ultimo else "├── "}{nome}/' + (f'  ({len(arqs)} arquivo{"s" if len(arqs) != 1 else ""})' if arqs else ''))
            if nivel < max_nivel:
                andar(atual, prefixo + ('    ' if ultimo else '│   '), nivel + 1)

    andar(pasta, '', 1)
    _dirs, topo = filhos(pasta)
    linhas += [f'{n}' for n in [x.name for x in topo]]
    return '\n'.join(linhas)


def _props(pom):
    return dict(re.findall(r'<([\w.-]+)>([^<${}]+)</\1>', re.search(r'<properties>(.*?)</properties>', pom, re.S).group(1))) if '<properties>' in pom else {}


def camada(nome, onde):
    if nome.startswith(('CICS', 'DB2', 'IBM MQ (API', 'COBOL')):
        return 'Programas mainframe'
    if nome.startswith('imagem '):
        return 'Imagens de execução e build'
    return 'Serviços e BFF' if ':' in nome else 'Micro frontend'


def tecnologias(projeto, modulos, extra=None):
    """[(camada, tecnologia, versão, onde, finalidade)] dos módulos (nomes de pasta), agrupadas por tecnologia e versão; extra = {(nome, versão): onde}."""
    projeto = Path(projeto)
    raiz = _ler(projeto / 'pom.xml')
    props = _props(raiz)
    gerenciadas = {a: v for g, a, v in re.findall(r'<dependency>\s*<groupId>([^<]+)</groupId>\s*<artifactId>([^<]+)</artifactId>\s*<version>([^<]+)</version>',
                                                  re.search(r'<dependencyManagement>(.*?)</dependencyManagement>', raiz, re.S).group(1))} if '<dependencyManagement>' in raiz else {}
    gerenciadas.update({a: v for a, v in re.findall(r'<plugin>\s*<groupId>[^<]+</groupId>\s*<artifactId>([^<]+)</artifactId>\s*<version>([^<]+)</version>', raiz)})
    boot = props.get('spring.boot.version') or (re.search(r'spring-boot-starter-parent</artifactId>\s*<version>([^<]+)', raiz) or [None, ''])[1]
    resolver = lambda v: re.sub(r'\$\{([^}]+)\}', lambda m: props.get(m.group(1), m.group(0)), v or '')   # noqa: E731
    onde = defaultdict(set)
    for mod in modulos:
        p = projeto / mod
        pom = _ler(p / 'pom.xml')
        for tipo, g, a, v in re.findall(r'<(dependency|plugin)>\s*(?:<groupId>([^<]+)</groupId>\s*)?<artifactId>([^<]+)</artifactId>(?:\s*<version>([^<]+)</version>)?', pom):
            if a.endswith(('-bom', '-dependencies')):
                continue
            ver = resolver(v) or resolver(gerenciadas.get(a, '')) or (boot if (g or '').startswith('org.springframework.boot') else '')
            onde[(f'{g}:{a}' if g else a, ver or 'gerenciada pelo BOM')].add(mod)
        pj = p / 'package.json'
        if pj.exists():
            d = json.loads(_ler(pj))
            for sec in ('dependencies', 'devDependencies'):
                for nome, ver in (d.get(sec) or {}).items():
                    onde[(nome, ver.lstrip('^~'))].add(mod)
        for df in sorted(p.glob('Dockerfile*')):
            for img in re.findall(r'^FROM\s+(\S+)', _ler(df), re.M):
                nome, _s, ver = img.partition(':')
                onde[(f'imagem {nome}', ver or 'latest')].add(mod)
        cobol = ' '.join(_ler(f) for f in sorted(p.glob('COBOL/*.CBL')))
        if cobol:
            onde[('COBOL', '—')].add(mod)
            for marca, nome in (('EXEC CICS', 'CICS (EXEC CICS: LINK, canais e containers)'), ('EXEC SQL', 'DB2 (SQL embutido)'), ("CALL 'MQ", 'IBM MQ (API MQI: MQGET, MQPUT)')):
                if marca in cobol:
                    onde[(nome, '—')].add(mod)
    for k, v in (extra or {}).items():
        onde[k].add(v)
    out = []
    for (nome, ver), mods in onde.items():
        fin = finalidade(nome.split(':')[-1] if ':' in nome else nome)
        if nome.startswith(('CICS', 'DB2', 'IBM MQ (API', 'COBOL')):
            fin = 'Linguagem e recursos dos programas mainframe'
        out.append((camada(nome, mods), nome, ver, ', '.join(sorted(mods)), fin))
    ordem = ['Serviços e BFF', 'Micro frontend', 'Programas mainframe', 'Imagens de execução e build']
    return sorted(out, key=lambda r: (ordem.index(r[0]), r[4] == '—', r[1]))


def imagens_compose(compose):
    """Imagens de terceiros do docker compose (as construídas localmente, tag :local, ficam de fora): {(imagem, versão): onde}."""
    out = {}
    for img in re.findall(r'^\s+image:\s*(\S+)', _ler(compose), re.M):
        if img.endswith(':local'):
            continue
        nome, sep, ver = img.partition('@') if '@' in img else img.partition(':')
        out[(f'imagem {nome}', (ver[:19] + '…') if sep == '@' else (ver or 'latest'))] = 'ambiente local (docker compose)'
    return out
