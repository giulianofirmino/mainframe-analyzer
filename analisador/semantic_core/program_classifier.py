"""Fase 0 — classificação dos programas pela estrutura (tokens/AST e grafo de chamadas resolvido; nenhum nome de programa é usado).

Classes: INTERFACE_USUARIO, COORDENADOR, FUNCIONAL, CORPORATIVO, INFRAESTRUTURA.
1. Pontuação por sinais do programa (heurística) -> classe-base (INFRAESTRUTURA e COORDENADOR saem daqui).
2. Relações do grafo de chamadas decidem o restante (FUNCIONAL só se não for chamado por FUNCIONAL; chamado por funcional = CORPORATIVO), nesta ordem:
   PONTO DE ENTRADA (nenhum chamador) = COORDENADOR; INFRAESTRUTURA pela heurística; CORPORATIVO = chamado por mais de um programa (qualquer classe de chamador);
   COORDENADOR pela heurística; FUNCIONAL = demais programas com lógica de negócio (chamados só por coordenadores,
   por um único programa, ou ponto de entrada).
3. Revisão pelo fim do fluxo (relatada na fase 0): FUNCIONAL ou CORPORATIVO sem consulta de dados nem alteração de estado, sem chamar outro
   programa da base e chamado por programa de negócio -> INFRAESTRUTURA. `classification` é a classe final; `phase0_classification` a da estrutura."""
from __future__ import annotations
import collections
import os
import re

CATS = ('INTERFACE_USUARIO', 'COORDENADOR', 'FUNCIONAL', 'CORPORATIVO', 'INFRAESTRUTURA')

CRITERIOS = [
    ('Fora do core business (prefixo configurado)', 'Só vale quando se informa o prefixo dos programas do core business (--prefixo-core): programa sem esse prefixo só pode ser CORPORATIVO ou INFRAESTRUTURA (framework). É INFRAESTRUTURA se a pontuação técnica vence; senão, CORPORATIVO. Vale antes de todas as outras regras; o refinamento pelo fim do fluxo ainda pode torná-lo INFRAESTRUTURA.',
     'Nome do programa (única heurística por nome) e a pontuação técnica dos sinais.'),
    ('COORDENADOR (ponto de entrada)', 'Programa que nenhum outro programa chama (ponto de entrada) é COORDENADOR, qualquer que seja a pontuação dos seus sinais. Vale antes de todas as outras regras.',
     'Grafo de chamadas resolvido: nenhum chamador.'),
    ('INFRAESTRUTURA (framework)', 'Pontuação técnica vence as demais: operações de memória, fila, tempo e runtime (GETMAIN, TS/TD queue, ASKTIME, ABEND etc.) no programa; +bônus se é chamado por 3 programas ou mais.',
     'Heurística de sinais técnicos (mantida). Recomendação: simular (mock) se tem efeito observável; senão excluir da análise funcional.'),
    ('CORPORATIVO', 'Chamado por mais de um programa distinto, não importa se os chamadores são coordenadores ou funcionais (exceto os classificados como infraestrutura pela regra anterior).',
     'Grafo de chamadas resolvido (CALL/LINK/XCTL, inclusive alvo em variável com VALUE).'),
    ('COORDENADOR', 'Pontuação de orquestração vence as demais: invoca dois ou mais programas e o volume de chamadas de saída predomina sobre decisões e SQL próprios.',
     'Chamadas de saída (outbound), decisões e SQL contados nos tokens (heurística mantida).'),
    ('FUNCIONAL', 'Demais programas com lógica de negócio (decisões, SQL, arquivos) e NENHUM chamador FUNCIONAL: chamado por coordenador (ou outro chamador que não seja funcional). Chamado por um FUNCIONAL só pode ser CORPORATIVO ou INFRAESTRUTURA.',
     'Classe final dos chamadores no grafo de chamadas.'),
    ('INTERFACE_USUARIO', 'Pontuação de interface vence as demais: operações de tela (SEND/RECEIVE MAP, SEND TEXT etc.).', 'Operações CICS de interface nos tokens.'),
]


def _walk(ns):
    for n in ns:
        yield n
        for k in ('body', 'then', 'else_body', 'at_end'):
            if isinstance(n.get(k), list):
                yield from _walk(n[k])
        for w in n.get('whens', []) or []:
            yield from _walk(w.get('body', []))


def _call_target(n):
    s = (n.get('args') or n.get('command') or '')
    m = re.search(r"(?:CALL\s+|PROGRAM\s*\(\s*)['\"]?([A-Z0-9-]+)", s, re.I)
    return m.group(1).upper() if m else None


def _resolved_calls(asts, texts):
    """Chamadas com o alvo resolvido (literal ou variável com VALUE) quando os textos estão disponíveis."""
    if not texts:
        return None
    import static_model as sm
    from cobol_data_model import build_data_model
    out = {}
    for p, a in asts.items():
        if p not in texts:
            return None
        out[p] = [c['target'].upper() for c in sm._calls(a, build_data_model(texts[p])) if c.get('target')]
    return out


def classify_programs(asts, texts=None, core_prefix=None):
    """core_prefix (ou a variável ANALISE_PREFIXO_CORE; opção --prefixo-core de tools/analisar.py): prefixo que todo programa do core business tem. Com ele, programa sem o prefixo
    só pode ser CORPORATIVO ou INFRAESTRUTURA (nunca COORDENADOR, FUNCIONAL nem INTERFACE_USUARIO); sem ele a classificação não usa nomes."""
    core_prefix = (core_prefix or os.environ.get('ANALISE_PREFIXO_CORE') or '').strip().upper()
    feats, calls_of = {}, {}
    resolved = _resolved_calls(asts, texts)
    for p, a in asts.items():
        ns = list(_walk(a.get('body', [])))
        calls = []
        for n in ns:
            if n.get('type') in ('CALL', 'EXEC_CICS'):
                t = _call_target(n)
                if t:
                    calls.append(t)
        if resolved is not None:
            calls = resolved[p]
        f = {'nodes': len(ns), 'decisions': sum(n.get('type') in ('IF', 'EVALUATE', 'SEARCH') for n in ns), 'sql': sum(n.get('type') == 'EXEC_SQL' for n in ns),
             'cics': sum(n.get('type') == 'EXEC_CICS' for n in ns)}
        f.update(_extra_features(ns, calls))
        feats[p] = f
        calls_of[p] = calls
    callers = collections.defaultdict(set)
    for p, cs in calls_of.items():
        for t in cs:
            if t != p and t in asts:
                callers[t].add(p)
    incoming = {p: len(callers[p]) for p in asts}
    base = {}
    rows = []
    for p, f in feats.items():
        s = {k: 0 for k in CATS}
        ev = []
        if f['ui']:
            s['INTERFACE_USUARIO'] += 18 + 4 * f['ui']; ev.append(f'user-interface CICS operations={f["ui"]}')
        if f['outbound'] >= 2:
            s['COORDENADOR'] += 7 + min(12, f['outbound']); ev.append(f'outbound program invocations={f["outbound"]}')
        if f['decisions'] >= 5:
            s['FUNCIONAL'] += 5 + min(12, f['decisions'] // 4); ev.append(f'decision nodes={f["decisions"]}')
        if f['sql']:
            s['FUNCIONAL'] += min(8, 2 + f['sql'] // 3); ev.append(f'SQL operations={f["sql"]}')
        if incoming[p] >= 2:
            s['CORPORATIVO'] += 8 + min(10, incoming[p]); ev.append(f'called by {incoming[p]} distinct programs')
        technical = f['memory_time_queue']
        if technical:
            s['INFRAESTRUTURA'] += 7 + min(12, technical * 2); ev.append(f'technical runtime/queue/memory/time operations={technical}')
        if incoming[p] >= 3 and technical:
            s['INFRAESTRUTURA'] += 6
        if f['outbound'] >= 4 and f['outbound'] > max(1, f['decisions'] / 3):
            s['COORDENADOR'] += 8
        heur = max(('FUNCIONAL', 'INTERFACE_USUARIO', 'COORDENADOR', 'INFRAESTRUTURA'), key=lambda x: s[x])   # sem nenhum sinal: FUNCIONAL (decidido pelo grafo)
        base[p] = (heur, s, ev)
    # 1) classe pela estrutura. Quem só pode ser FUNCIONAL depende da classe final dos chamadores (iterado até estabilizar).
    fixed, cand = {}, []
    for p, (heur, s, ev) in base.items():
        if core_prefix and not p.upper().startswith(core_prefix):
            if heur == 'INFRAESTRUTURA':
                fixed[p] = ('INFRAESTRUTURA', f'fora do core business (sem o prefixo {core_prefix}): só pode ser corporativo ou framework; pontuação técnica indica framework')
            else:
                fixed[p] = ('CORPORATIVO', f'fora do core business (sem o prefixo {core_prefix}): só pode ser corporativo ou framework; sem pontuação técnica predominante, é corporativo')
        elif incoming[p] == 0:
            fixed[p] = ('COORDENADOR', 'ponto de entrada: nenhum programa o chama, então coordena o fluxo')
        elif heur == 'INFRAESTRUTURA':
            fixed[p] = ('INFRAESTRUTURA', 'pontuação técnica (memória/fila/tempo/runtime) vence')
        elif incoming[p] >= 2:
            fixed[p] = ('CORPORATIVO', f'chamado por {incoming[p]} programas distintos')
        elif heur == 'COORDENADOR':
            fixed[p] = ('COORDENADOR', 'pontuação de orquestração (chamadas de saída) vence')
        elif heur == 'INTERFACE_USUARIO':
            fixed[p] = ('INTERFACE_USUARIO', 'pontuação de operações de tela vence')
        else:
            cand.append(p)
    cur = {p: v[0] for p, v in fixed.items()}
    for p in cand:
        cur[p] = 'FUNCIONAL'
    why_c = {}
    for _ in range(len(cand) + 2):
        changed = False
        for p in sorted(cand):
            fcs = sorted(c for c in callers[p] if cur.get(c) == 'FUNCIONAL')
            if fcs:
                new_c, why = 'CORPORATIVO', 'chamado por programa FUNCIONAL (' + ', '.join(fcs) + '): quem é chamado por funcional só pode ser corporativo ou framework'
            else:
                new_c, why = 'FUNCIONAL', 'lógica de negócio chamada por ' + ', '.join(sorted(f'{c} ({cur.get(c)})' for c in callers[p]))
            if cur[p] != new_c:
                cur[p], changed = new_c, True
            why_c[p] = why
        if not changed:
            break
    for p in cand:
        fixed[p] = (cur[p], why_c[p])
    # 2) refinamento pelo fim do fluxo: sem consulta de dados nem alteração de estado e sem chamar outro programa da base
    #    (ignorando os já reclassificados), chamado por programa de negócio -> infraestrutura. Repete até estabilizar.
    refined = {}
    for _ in range(len(asts) + 1):
        changed = False
        for p in sorted(asts):
            if p in refined or fixed[p][0] not in ('FUNCIONAL', 'CORPORATIVO'):
                continue
            f = feats[p]
            onward = [t for t in set(calls_of[p]) if t != p and t in asts and t not in refined]
            biz_callers = [c for c in callers[p] if (refined.get(c) or fixed[c][0]) in ('COORDENADOR', 'FUNCIONAL', 'CORPORATIVO') and c not in refined]
            if f['data_ops'] == 0 and not onward and biz_callers:
                refined[p] = ('INFRAESTRUTURA', 'fim do fluxo sem consulta de dados nem alteração de estado, chamado por ' + ', '.join(sorted(biz_callers)))
                changed = True
        if not changed:
            break
    for p, (heur, s, ev) in base.items():
        f = feats[p]
        cs = sorted(callers[p])
        cat0, why0 = fixed[p]
        cat, why = refined.get(p, (cat0, why0))
        vals = sorted(s.values(), reverse=True)
        margin = vals[0] - vals[1]
        conf0 = 'HIGH' if margin >= 7 or cat0 in ('CORPORATIVO', 'FUNCIONAL') and incoming[p] else ('MEDIUM' if margin >= 3 else 'LOW')
        if incoming[p] == 0:
            conf0 = 'HIGH'   # ponto de entrada é regra estrutural, sem margem de pontuação
        conf = conf0
        confirm = ''
        if p in refined:
            conf, confirm = 'HIGH', 'o fim do fluxo sem dados confirma o papel técnico'
        elif cat == 'FUNCIONAL' and f['data_ops'] and cs and all(fixed[c][0] == 'COORDENADOR' for c in cs):
            conf, confirm = 'HIGH', 'acessa dados e é chamado só por coordenador'
        elif cat == 'COORDENADOR' and f['data_ops'] == 0 and f['outbound'] >= 2:
            conf, confirm = 'HIGH', 'só orquestra: nenhum acesso a dados próprio'
        elif cat == 'CORPORATIVO' and f['data_ops']:
            conf, confirm = 'HIGH', 'serviço compartilhado que acessa dados'
        rec, reason = 'ANALYZE', 'Program participates in functional analysis.'
        if cat == 'INFRAESTRUTURA':
            if incoming[p] or f['sql'] or f['file_io'] or f['cics']:
                rec, reason = 'MOCK_RECOMMENDED', 'Technical behavior has observable effects consumed in analyzed scope.'
            else:
                rec, reason = 'EXCLUDE_RECOMMENDED', 'No observable functional effect found in analyzed scope; exclusion still requires dependency review.'
        rows.append({'program': p, 'classification': cat, 'confidence': conf, 'recommendation': rec, 'reason': reason, 'incoming_references': incoming[p],
                     'callers': cs, 'criterion': why, 'scores': s, 'evidence': ev, 'features': f,
                     'phase0_classification': cat0, 'phase0_confidence': conf0, 'phase0_criterion': why0,
                     'refinement': ({'from': cat0, 'to': cat, 'reason': why, 'confidence_before': conf0, 'confidence_after': conf} if p in refined else None),
                     'confidence_note': confirm if conf != conf0 else ''})
    # classe dos chamadores (depois que todas as classes finais são conhecidas)
    cls = {r['program']: r['classification'] for r in rows}
    for r in rows:
        r['caller_classes'] = {c: cls[c] for c in r['callers']}
    return sorted(rows, key=lambda x: x['program'])


def _extra_features(ns, calls):
    """Contagens por tipo de nó (E/S de arquivo, interface, runtime técnico) e as chamadas de saída."""
    cmd = lambda n: n.get('command', '')
    return {'data_ops': _data_ops(ns), 'file_io': sum(n.get('type', '').startswith('FILE_') for n in ns), 'calls': calls, 'outbound': len(calls),
            'ui': sum(n.get('type') == 'EXEC_CICS' and re.search(r'\b(SEND|RECEIVE)\s+(MAP|TEXT)', cmd(n), re.I) is not None for n in ns),
            'memory_time_queue': sum(n.get('type') == 'EXEC_CICS' and re.search(r'\b(GETMAIN|FREEMAIN|ASKTIME|FORMATTIME|READQ|WRITEQ|DELETEQ)\b', cmd(n), re.I) is not None for n in ns)}


DATA_VERBS = {'READ', 'WRITE', 'REWRITE', 'DELETE', 'STARTBR', 'READNEXT', 'READPREV', 'ENDBR', 'RESETBR', 'READQ', 'WRITEQ', 'DELETEQ'}


def _data_ops(ns):
    """Consulta de dados ou alteração de estado: SQL, E/S de arquivo e comandos CICS de arquivo ou fila (palavras do comando, sem expressão regular)."""
    n = 0
    for x in ns:
        t = x.get('type', '')
        if t == 'EXEC_SQL' or t.startswith('FILE_'):
            n += 1
        elif t == 'EXEC_CICS' and (DATA_VERBS & set((x.get('command') or '').upper().replace('(', ' ').replace(')', ' ').split())):
            n += 1
    return n
