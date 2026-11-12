#!/usr/bin/env python3
"""Relatório de design das aplicações de frontend (fase 20a): o micro frontend e o BFF implementados, e as diretrizes de interface e os padrões do BFF que
os próximos recortes seguem ao reestruturar as telas do legado.

  python3 gerar_ui_design.py <pasta-da-analise> [pasta-de-saida] --projeto <repositório> [--interpretacao PASTA]

Calculado do repositório: os módulos de frontend (micro frontend com angular.json e o BFF, pelo tipo de aplicação da arquitetura alvo; função descrever do
gerar_implementation), com pilha, classes, testes, pacotes, estrutura de diretórios e tecnologias; do micro frontend, as rotas (protegidas, sob demanda),
os módulos expostos pela federação, os componentes (seletor, componentes que usa, entradas e saídas), as chamadas HTTP dos serviços com a operação do
contrato (fase 20) que cada uma usa e o tema (tailwind). Do registro do prompt 13 (interpretacao-design/design.json): as telas (correspondência de cada
tela do legado, fase 15, com a tela nova e o que mudou na reestruturação), as diretrizes de interface (UX-nn) e os padrões do BFF (PF-nn), com exemplos
ancorados no código e verificação automática de conformidade (registro_padroes). Uma âncora ou uma tela do legado que não existe recusa o relatório.
Saída: <saida>/20a - ui-design/{human/report.html, ia/report.json}."""
import json
import re
import sys
from pathlib import Path

import gerar_enhancement_proposals as EP
import gerar_target_architecture as TA
import estrutura_repo as ER
import registro_padroes as RP
import report_model as rm

S = TA.S
FASE = '20a - ui-design'
INTERP = 'interpretacao-design'
COR = {'legado': '#8a6d00', 'tela': '#0072B2', 'componente': '#1E8E3E', 'servico': '#7B3FA0', 'operacao': '#D55E00'}


def ler(p):
    return Path(p).read_text(encoding='utf-8') if Path(p).exists() else ''


def remodelagem(ana, P):
    """Telas do legado na nova interface: a tabela de nomes (fase 19) com finalidade, jornada e layout sugerido (fase 15) e, quando a fase 15 traz a
    interpretação das telas (prompt 6, seção só para IA), os blocos dela: campos, agrupamentos, eventos, regras, ações e processos. A coluna "Relação com
    a transação" fica na fase 15 (tabela Componentes da tela), sem repetir aqui. Devolve (tabela de telas, blocos da interpretação ou None)."""
    ux = P['ux']['telas']
    ordem = list(ux)   # a ordem das telas na fase 15 (a jornada: pesquisa antes do formulário), a mesma das tabelas por tela
    nomes = sorted(P['simb'].tela.items(), key=lambda kv: (ordem.index(kv[0]) if kv[0] in ordem else len(ordem), kv[1]))
    tab = rm.T('Telas: nome, finalidade, jornada e layout sugerido', ['Nome da tela', 'Tela do legado', 'Finalidade', 'Jornada', 'Layout sugerido', 'Confiança', 'Lacunas'],
               [(sym, t, *((ux.get(t) or {}).get(c) or '—' for c in ('Finalidade', 'Jornada', 'Layout sugerido', 'Confiança', 'Lacunas'))) for t, sym in nomes],
               note='Nome dado à tela na arquitetura alvo (fase 19); finalidade, jornada e layout sugerido levantados nas interfaces com o usuário (fase 15).')
    sec = next((x for x in S.fase(ana, '15 ')['sections'] if x['id'] == 'interpretacao'), None)
    if not sec:
        return tab, None
    blocos = []
    for b in json.loads(json.dumps(sec['blocks'])):
        if (b.get('title') or '').startswith('Telas: finalidade, jornada e layout sugerido'):
            blocos.append(tab)   # mesma informação da tabela de nomes: uma tabela só
            continue
        if b['type'] == 'table' and 'Relação com a transação' in b['columns']:
            i = b['columns'].index('Relação com a transação')
            tela = re.sub(r'^Campos de (.*?):.*', r'\1', b.get('title') or '')
            b['columns'] = b['columns'][:i] + b['columns'][i + 1:]
            b['rows'] = [r[:i] + r[i + 1:] for r in b['rows']]
            b['note'] = f'A relação de cada campo com a transação está nas interfaces com o usuário (fase 15), tabela Componentes de {tela}.'
        blocos.append(b)
    return tab, blocos


def modulo_fed(projeto):
    m = sorted(p.parent for p in Path(projeto).glob('*/angular.json'))
    if not m:
        raise SystemExit('nenhum micro frontend (módulo com angular.json) no repositório')
    return m[0]


def rotas(app):
    """Rotas do arquivo de rotas: (caminho, componente importado, protegida, redireciona para)."""
    out, protegida = [], False
    for f in sorted(app.rglob('*.routes.ts')):
        for l in ler(f).splitlines():
            guarda = 'canActivate' in l
            protegida = protegida or guarda
            for m in re.finditer(r"path:\s*'([^']*)'(?:[^}]*?loadComponent:\s*\(\)\s*=>\s*import\('([^']+)'\)\.then\(m => m\.(\w+)\)|[^}]*?component:\s*(\w+)|[^}]*?redirectTo:\s*'([^']*)')?", l):
                caminho, imp, comp, comp2, redir = m.groups()
                if comp or comp2 or redir is not None:
                    out.append({'arquivo': f.relative_to(app.parent.parent).as_posix(), 'caminho': '/' + caminho if caminho not in ('**',) else caminho,
                                'componente': comp or comp2, 'sob_demanda': bool(imp), 'protegida': protegida,
                                'redireciona': redir})
            if l.strip().startswith('] }') or l.strip().startswith(']}'):
                protegida = False
    return out


def componentes(app):
    out = []
    for f in sorted(app.rglob('*.component.ts')):
        t = ler(f)
        cls = re.search(r'export class (\w+)', t)
        sel = re.search(r"selector:\s*'([^']+)'", t)
        tpl = re.search(r"templateUrl:\s*'([^']+)'", t)
        html = ler(f.parent / tpl.group(1)) if tpl else (re.search(r'template:\s*`(.*?)`', t, re.S) or [None, ''])[1] or ''
        usa = sorted(set(re.findall(r'<(app-[a-z0-9-]+)', html)))
        ent = re.findall(r'@Input\(\)\s*(?:readonly\s+)?(\w+)|(\w+)\s*=\s*input(?:\.required)?[<(]', t)
        sai = re.findall(r'@Output\(\)\s*(?:readonly\s+)?(\w+)|(\w+)\s*=\s*output[<(]', t)
        tipo = 'página' if '/pages/' in f.as_posix() else 'compartilhado' if '/shared/' in f.as_posix() else 'estrutura' if '/components/' in f.as_posix() else 'raiz'
        out.append({'classe': cls.group(1) if cls else f.stem, 'seletor': sel.group(1) if sel else '—', 'arquivo': f.relative_to(app.parent.parent).as_posix(),
                    'tipo': tipo, 'usa': usa, 'entradas': [a or b for a, b in ent], 'saidas': [a or b for a, b in sai]})
    return out


def chamadas(app):
    """Chamadas HTTP dos serviços: (serviço, método do serviço que a faz, verbo, caminho normalizado com {parâmetros}). O método é o último
    método da classe declarado antes da chamada; o caminho resolve this.base e o método privado de caminho, quando há."""
    out = []
    for f in sorted(app.rglob('*.service.ts')):
        t = ler(f)
        bases = dict(re.findall(r"get (\w+)\(\)[^{]*\{\s*return [^;]*?'([^']+)'", t))   # get base() { return ... + '/ni/v1' }
        cam_priv = dict((n, c) for n, c in re.findall(r"private (\w+)\([^)]*\)[^`]*`\$\{this\.base\}([^`]*)`", t))
        metodos = [(m.start(), m.group(1)) for m in re.finditer(r'^  (?:async\s+)?(\w+)\([^)]*\)[^\n]*\{', t, re.M)]
        for m in re.finditer(r"this\.http\.(get|post|put|delete|patch)\b[^(]*\(\s*([^,)]+(?:\([^)]*\))?)", t):
            verbo, arg = m.group(1).upper(), m.group(2).strip()
            nome = next((n for pos, n in reversed(metodos) if pos < m.start()), '?')
            pc = re.match(r'this\.(\w+)\(', arg)
            if pc and pc.group(1) in cam_priv:
                cam = bases.get('base', '') + cam_priv[pc.group(1)]
            else:
                cam = re.sub(r"this\.(\w+)\s*\+\s*'", lambda x: bases.get(x.group(1), '{' + x.group(1) + '}'), arg)
                cam = re.sub(r'\$\{this\.(\w+)\}', lambda x: bases.get(x.group(1), '{' + x.group(1) + '}'), cam).strip("`'")
                cam = re.sub(r"^this\.contexto\.(\w+)\s*\+\s*'", r'{\1}', cam).strip("`'")
            cam = re.sub(r'\$\{[^}]*?\.?(\w+)\}', r'{\1}', cam)
            out.append({'servico': f.stem.replace('.service', ''), 'metodo': nome, 'verbo': verbo, 'caminho': cam,
                        'arquivo': f.relative_to(app.parent.parent).as_posix()})
    return out


def operacao(ch, ops):
    """Operação do contrato que a chamada usa: mesmo verbo e mesmo caminho (o prefixo /ni do código, ADR do prefixo, sai na comparação)."""
    alvo = re.sub(r'\{[^}]+\}', '{}', re.sub(r'^/ni(?=/)', '', ch['caminho']))
    for o in ops:
        if o['metodo'] == ch['verbo'] and re.sub(r'\{[^}]+\}', '{}', o['caminho']) == alvo:
            return o
    return None


def tema(fed):
    f = next(iter(sorted(fed.glob('tailwind.config.*'))), None)
    t = ler(f) if f else ''
    bloco = lambda nome: (re.search(rf'{nome}:\s*\{{(.*?)\n\s{{6}}\}}', t, re.S) or [None, ''])[1]   # noqa: E731
    cores = re.findall(r"'?([\w-]+)'?:\s*'(#[0-9A-Fa-f]{3,8})'", bloco('colors'))
    fontes = re.findall(r"'([\w-]+)':\s*\[([^\]]*)\]", bloco('fontFamily'))
    telas = re.findall(r"(\w+):\s*'(\d+px)'", bloco('screens'))
    anim = re.findall(r"'([\w-]+)':\s*'([^']+)'", bloco('animation'))
    sombras = re.findall(r"(\w+):\s*'([^']+)'", bloco('boxShadow'))
    return (f.relative_to(fed.parent).as_posix() if f else '—'), cores, fontes, telas, anim, sombras


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
    reg = json.loads((Path(base) / INTERP / 'design.json').read_text(encoding='utf-8'))
    fed = modulo_fed(projeto)
    app = fed / 'src' / 'app'
    fora = reg.get('fora') or {}   # o que não faz parte do recorte (por exemplo, a plataforma de identidade): fora do relatório e das verificações
    rs = [r for r in rotas(app) if r['componente'] not in fora.get('componentes', [])]
    cs = [c for c in componentes(app) if c['classe'] not in fora.get('componentes', [])]
    chs = [c for c in chamadas(app) if c['servico'] not in fora.get('servicos', []) and not any(c['caminho'].startswith(x) for x in fora.get('caminhos', []))]
    import gerar_traceability_to_be as TB
    ops = TB.ler_contratos(ana, 'C')
    P = TA.preparar(ana, base)   # nomes das telas da arquitetura alvo (fase 19) e a finalidade da fase 15
    t_telas, remod = remodelagem(ana, P)
    erros = []
    achados = RP.validar(reg['diretrizes'], ana, projeto, erros, 'diretriz', fora.get('arquivos', []))
    achados_pf = RP.validar(reg.get('padroes', []), ana, projeto, erros, 'padrão', fora.get('arquivos', []))   # padrões do BFF
    import gerar_implementation as GI
    fe = GI.descrever(projeto, ana, base, 'frontend', fora)   # micro frontends e BFF, pelo tipo de aplicação da arquitetura alvo
    telas_reg = []
    for t in reg['telas']:
        for leg in t.get('legado', []):
            if not (EP.raiz('aplicacao', ana, projeto) / leg).exists():
                erros.append(f'tela {t["tela"]}: tela do legado não existe na aplicação: {leg}')
        exs = [loc for r in t.get('exemplos', []) for loc in [EP.localizar(r, ana, projeto, f'tela {t["tela"]}', erros)] if loc]
        if t.get('componente') and t['componente'] not in {c['classe'] for c in cs}:
            erros.append(f'tela {t["tela"]}: componente {t["componente"]} não existe no micro frontend')
        telas_reg.append((t, exs))
    if erros:
        raise SystemExit('registro de design recusado:\n  ' + '\n  '.join(erros))

    # telas e rotas
    t_rotas = [(r['caminho'], r['componente'] or f'→ {r["redireciona"]}', 'sim' if r['protegida'] else 'não', 'sim' if r['sob_demanda'] else 'não', r['arquivo'])
               for r in rs]
    expostos = re.findall(r"'(\./[\w/-]+)':\s*'([^']+)'", ler(next(iter(sorted(fed.glob('webpack.config.*'))), fed / '_')))
    t_legado = [(t['tela'], t.get('rota', '—'), t.get('componente', '—'), ', '.join(t.get('legado', [])) or '—', t.get('reestruturacao', ''),
                 '; '.join(t.get('acoes', [])) or '—') for t, _e in telas_reg]
    # componentes
    t_comp = [(c['classe'], c['seletor'], c['tipo'], ', '.join(c['usa']) or '—', ', '.join(c['entradas']) or '—', ', '.join(c['saidas']) or '—', c['arquivo'])
              for c in cs]
    # chamadas
    t_cham, marcas_cham, usadas = [], [], set()
    for ch in chs:
        o = operacao(ch, ops)
        if o:
            usadas.add(o['operationId'])
        t_cham.append((ch['servico'], ch['metodo'], ch['verbo'], ch['caminho'],
                       rm.with_links('', [rm.link(f'{o["operationId"]} ({o["app"]})', '21 - traceability-to-be', o['ancora'])]) if o else 'fora dos contratos (fundação)',
                       ch['arquivo']))
        marcas_cham.append(o is None and '/ni/' in ch['caminho'])
    # tema
    arq_tema, cores, fontes, bps, anim, sombras = tema(fed)
    # diagrama: tela do legado → tela nova → componentes → serviço → operação do contrato
    nos, arestas = {}, set()
    def no(i, label, sub, col):
        nos.setdefault(i, {'id': i, 'label': label, 'sub': sub, 'col': col})
    comp_por_classe = {c['classe']: c for c in cs}
    sel_para_classe = {c['seletor']: c['classe'] for c in cs}
    for t, _e in telas_reg:
        if not t.get('componente'):
            continue
        tn = f'T:{t["componente"]}'
        no(tn, t['tela'], t.get('rota', ''), 1)
        for leg in t.get('legado', []):
            no(f'L:{leg}', Path(leg).name, str(Path(leg).parent), 0)
            arestas.add((f'L:{leg}', tn))
        for s_ in [t['componente']] + [sel_para_classe.get(u) for u in comp_por_classe[t['componente']]['usa'] if sel_para_classe.get(u)]:
            c = comp_por_classe[s_]
            no(f'C:{s_}', c['seletor'], c['tipo'], 2)
            arestas.add((tn, f'C:{s_}'))
        for sv in t.get('servicos', []):
            no(f'S:{sv}', sv, 'serviço Angular', 3)
            arestas.add((f'C:{t["componente"]}', f'S:{sv}'))
            for ch in chs:
                o = operacao(ch, ops)
                if ch['servico'] == sv and o and o['operationId'] in t.get('operacoes', [o['operationId']]):
                    no(f'O:{o["operationId"]}', o['operationId'], f'{o["metodo"]} {o["caminho"]}', 4)
                    arestas.add((f'S:{sv}', f'O:{o["operationId"]}'))
    diag = rm.G('Da tela do legado à operação do contrato', list(nos.values()), [{'from': a, 'to': b} for a, b in sorted(arestas)], kind='colunas',
                note='Tela do legado (fase 15) → tela nova do micro frontend → componentes que ela usa → serviço Angular → operação do contrato do BFF (fase 20).')
    diag['columns'] = [{'name': n, 'color': COR[k]} for n, k in (('Tela do legado', 'legado'), ('Tela nova', 'tela'), ('Componentes', 'componente'),
                                                                     ('Serviço Angular', 'servico'), ('Operação do contrato', 'operacao'))]
    diag['nw'] = 210

    n_dir, n_verif, n_conf = RP.resumo_conformidade(achados)
    n_pf, n_pf_verif, n_pf_conf = RP.resumo_conformidade(achados_pf)
    papeis = fe['papeis_mod']
    resumo = [('aplicações de frontend (micro frontend e BFF)', len(fe['t_mod'])), ('casos de uso do BFF (classes UseCase)', sum(papeis[m]['UseCase'] for m in papeis)),
              ('clientes dos serviços no BFF (OpenFeign)', sum(papeis[m]['Client'] for m in papeis)),('telas (rotas com componente)', sum(1 for r in rs if r['componente'])), ('telas do legado reestruturadas', sum(len(t.get('legado', [])) for t, _ in telas_reg)),
              ('componentes', len(cs)), ('componentes compartilhados', sum(1 for c in cs if c['tipo'] == 'compartilhado')),
              ('chamadas HTTP dos serviços', len(chs)), ('operações do contrato do BFF usadas pela interface', f'{len(usadas)} de {len({o["operationId"] for o in ops if "bff" in o["app"]})}'),
              ('módulos expostos pela federação', len(expostos)), ('cores do tema', len(cores)), ('famílias de fonte', len(fontes)),
              ('diretrizes de interface registradas', n_dir), ('diretrizes conformes no repositório', f'{n_conf} de {n_verif}'),
              ('padrões do BFF registrados', n_pf), ('padrões do BFF conformes no repositório', f'{n_pf_conf} de {n_pf_verif}')]
    secs = [
        rm.S('resumo', 'Resumo', [
            rm.X(f'Aplicações de frontend: {reg.get("descricao", "")}', 'Como ler'),
            *([rm.T('Fora deste relatório', ['Motivo', 'Componentes', 'Serviços', 'Chamadas'],
                    [(fora.get('motivo', ''), ', '.join(fora.get('componentes', [])) or '—', ', '.join(fora.get('servicos', [])) or '—',
                      ', '.join(fora.get('caminhos', [])) or '—')])] if fora else []),
            diag]),
        rm.S('aplicacoes', 'Aplicações de frontend', [
            rm.T('Módulos do frontend', ['Módulo', 'Tipo (arquitetura alvo)', 'Aplicações da arquitetura alvo', 'Pilha', 'Arquivos de código', 'Testes', 'Dockerfile',
                                       'Configuração'], fe['t_mod']),
            rm.T('Pacotes e pastas por módulo', ['Módulo', 'Pacote-base', 'Pacote ou pasta', 'Camada', 'Arquivos', 'Exemplos'], fe['estrutura'])]),
        rm.S('estrutura', 'Estrutura de diretórios', [rm.COD(ER.arvore(Path(projeto) / m[0], excluir=fe['pastas_fora']),
                                                             f'{m[0]}: pastas com a quantidade de arquivos e os arquivos de topo') for m in fe['t_mod']] + [
            rm.X('Pastas de build e de dependências (target, node_modules…) e o que o registro deixa fora do recorte não aparecem. Cadeias de pastas com um '
                 'único filho (os pacotes Java, por exemplo) ficam numa linha só.')]),
        *([rm.S('remodelagem', 'Remodelagem das telas legadas', remod, 'Texto escrito pela IA a partir das interfaces com o usuário (fase 15, prompt 6); '
                                                                       'o script confere cada tela, campo e ação contra a evidência.')] if remod else []),
        rm.S('telas', 'Telas reestruturadas', [
            *([] if remod else [t_telas]),
            rm.T('Telas do legado reestruturadas', ['Tela nova', 'Rota', 'Componente', 'Tela(s) do legado (fase 15)', 'O que mudou na reestruturação', 'Ações'], t_legado,
                 note='Correspondência registrada pelo prompt 13; a tela do legado é procurada na aplicação e o componente no micro frontend a cada geração.'),
            rm.T('Rotas do micro frontend', ['Rota', 'Componente', 'Protegida (autenticação)', 'Carregada sob demanda', 'Arquivo'], t_rotas),
            rm.T('Módulos expostos pela federação', ['Módulo exposto', 'Arquivo'], expostos or [('—', '—')])]),
        rm.S('componentes', 'Componentes', [
            rm.T('Componentes do micro frontend', ['Componente', 'Seletor', 'Tipo', 'Componentes que usa', 'Entradas', 'Saídas', 'Arquivo'], t_comp)]),
        rm.S('integracao', 'Chamadas ao BFF', [
            rm.T('Chamadas HTTP dos serviços e a operação do contrato', ['Serviço', 'Método do serviço', 'Verbo', 'Caminho', 'Operação do contrato (fase 20)', 'Arquivo'],
                 t_cham, marks=marcas_cham, note='Linha destacada: chamada ao BFF de negócio sem operação correspondente no contrato.')]),
        rm.S('tecnologias', 'Tecnologias utilizadas', [
            rm.T('Tecnologias do frontend', ['Camada', 'Tecnologia', 'Versão', 'Onde', 'Para que'], ER.tecnologias(projeto, [m[0] for m in fe['t_mod']]),
                 note='Lidas do package.json e do Dockerfile do micro frontend e do pom.xml (versão pelas propriedades e pelo BOM do pom raiz) e do Dockerfile do BFF.')]),
        rm.S('tema', 'Tema visual', [
            rm.T('Cores', ['Nome', 'Valor'], cores, note=f'Tokens de cor do tema ({arq_tema}).'),
            rm.T('Fontes', ['Nome', 'Famílias'], [(n, f.replace("'", '')) for n, f in fontes]),
            rm.T('Breakpoints, sombras e animações', ['Tipo', 'Nome', 'Valor'], [('breakpoint', n, v) for n, v in bps] + [('sombra', n, v) for n, v in sombras] +
                 [('animação', n, v) for n, v in anim])]),
        *RP.secoes(reg['diretrizes'], achados, 'Diretrizes de interface', 'diretrizes', FASE),
        *RP.secoes(reg.get('padroes', []), achados_pf, 'Padrões e convenções do BFF', 'padroes-bff', FASE)]
    cards = [rm.card(k, v) for k, v in resumo]   # os números do design em cartões, como na página de entrada
    S.escrever(saida, FASE, rm.model('Design das Aplicações de Frontend', 'Micro frontend e BFF implementados: estrutura, tecnologias, telas, componentes, tema e chamadas, e as '
                                                                    'diretrizes e os padrões que os próximos recortes seguem ao reestruturar as telas do legado', cards, secs))
    print(f'{len(fe["t_mod"])} módulos, {len(rs)} rotas, {len(cs)} componentes, {len(chs)} chamadas ({len(usadas)} operações do contrato), {n_dir} diretrizes '
          f'({n_conf}/{n_verif} conformes), {n_pf} padrões do BFF ({n_pf_conf}/{n_pf_verif} conformes)')


if __name__ == '__main__':
    main()
