"""SQL dinâmico: acha PREPARE / EXECUTE IMMEDIATE / EXECUTE <comando> e monta o texto do comando SQL a partir dos valores que o programa atribui ao campo que o carrega.

Só o texto do programa (já com os copybooks expandidos), tokens e AST; nenhum nome fixo. O campo que carrega o comando é rastreado até a origem:
  MOVE literal TO campo; MOVE outro-campo TO campo (segue o outro campo); STRING a b c INTO campo (concatena os pedaços, cada um rastreado); valor inicial (VALUE) do campo;
  grupo sem atribuição: concatenação dos campos filhos (cada um pelo mesmo rastreio).
Campo cuja origem não é literal (entrada do programa, coluna lida, resultado de função) aparece como <NOME> no texto montado. Há uma montagem por caminho de atribuição (no máximo MAX_ALT).
Devolve, por comando dinâmico: as linhas que o compõem (PREPARE, EXECUTE, e OPEN/FETCH/CLOSE de cursor declarado sobre ele), as montagens e as tabelas que as montagens citam."""
import re
from itertools import product

from cobol_token_parser import parse_text
from cobol_data_model import build_data_model
from token_utils import tokens_of, V, sql_tables

MAX_ALT = 12
MAX_PROF = 8
FIGURATIVAS = {'SPACE', 'SPACES', 'LOW-VALUE', 'LOW-VALUES', 'HIGH-VALUE', 'HIGH-VALUES', 'QUOTE', 'QUOTES'}
ZEROS = {'ZERO', 'ZEROS', 'ZEROES'}
_TOK = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|[A-Za-z0-9][A-Za-z0-9_-]*(?:\([^)]*\))?|\S")
_FIM_STRING = {'END-STRING', 'WITH', 'POINTER', 'ON', 'NOT', 'OVERFLOW'}


def _walk(ns):
    for n in ns:
        yield n
        for k in ('body', 'then', 'else_body', 'at_end'):
            if isinstance(n.get(k), list):
                yield from _walk(n[k])
        for w in n.get('whens', []) or []:
            yield from _walk(w.get('body', []))


def _toks(args):
    return _TOK.findall(args or '')


def _literal(t):
    return len(t) >= 2 and t[0] in '\'"' and t[-1] == t[0]


def _sem_refmod(t):
    return re.sub(r'\([^)]*\)$', '', t)


def _nome(t):
    return _sem_refmod(t).upper()


def _atribuicoes(ast):
    """{campo: [{'tipo': 'MOVE'|'STRING', 'fonte': token | 'partes': [(token, delimitador)], 'linha'}]} de todo o procedimento."""
    out = {}
    for n in _walk(ast.get('body', [])):
        typ, ln = n.get('type'), n.get('start_line')
        if typ == 'MOVE':
            tk = _toks(n.get('args', ''))
            up = [x.upper() for x in tk]
            if 'TO' not in up or up[0] in ('CORRESPONDING', 'CORR'):
                continue
            i = up.index('TO')
            fonte = ' '.join(tk[:i]) if i != 1 else tk[0]
            if i != 1 and not (i == 2 and up[0] == 'FUNCTION'):
                continue
            for t in tk[i + 1:]:
                if re.match(r'^[A-Za-z0-9][A-Za-z0-9_-]*', t) and t.upper() not in ('TO',):
                    out.setdefault(_nome(t), []).append({'tipo': 'MOVE', 'fonte': fonte, 'linha': ln})
        elif typ == 'STRING':
            tk = _toks(n.get('args', ''))
            up = [x.upper() for x in tk]
            if 'INTO' not in up:
                continue
            k = up.index('INTO')
            alvo = _nome(tk[k + 1]) if k + 1 < len(tk) else None
            partes, i = [], 0
            while i < k:
                t = tk[i]
                if up[i] in ('DELIMITED', 'BY'):
                    i += 1
                    continue
                parte, delim = t, None
                if i + 3 < len(tk) + 1 and i + 1 < k and up[i + 1] == 'DELIMITED':
                    j = i + 2
                    if j < k and up[j] == 'BY':
                        j += 1
                    delim = tk[j] if j < k else None
                    i = j
                partes.append((parte, delim))
                i += 1
            if alvo:
                out.setdefault(alvo, []).append({'tipo': 'STRING', 'partes': partes, 'linha': ln})
    return out


class _Rastreio:
    def __init__(self, model, atrib):
        self.itens = {}
        self.filhos = {}
        for it in model:
            if it['level'] in (66, 88):
                continue
            self.itens.setdefault(it['name'], it)
            if it.get('parent'):
                self.filhos.setdefault(it['parent'], []).append(it)
        self.atrib = atrib

    def _fonte(self, t, prof, vistos):
        if _literal(t):
            q = t[0]
            return [t[1:-1].replace(q * 2, q)]
        up = t.upper()
        if up in FIGURATIVAS:
            return [''] if up in ('SPACE', 'SPACES', 'LOW-VALUE', 'LOW-VALUES', 'HIGH-VALUE', 'HIGH-VALUES') else ['"']
        if up in ZEROS or re.fullmatch(r'[+-]?\d+(\.\d+)?', t):
            return ['0' if up in ZEROS else t]
        if t.upper().startswith('FUNCTION'):
            return ['<' + t + '>']
        return self.valor(_nome(t), prof + 1, vistos)

    def valor(self, nome, prof=0, vistos=()):
        """Alternativas de texto do campo `nome`, uma por caminho de atribuição."""
        if prof > MAX_PROF or nome in vistos:
            return ['<' + nome + '>']
        vistos = tuple(vistos) + (nome,)
        alts = []
        for a in self.atrib.get(nome, []):
            if a['tipo'] == 'MOVE':
                alts += self._fonte(a['fonte'], prof, vistos)
            else:
                pedacos = []
                for parte, delim in a['partes']:
                    vals = self._fonte(parte, prof, vistos)
                    if delim and delim.upper() in ('SPACE', 'SPACES') and not _literal(parte):
                        vals = [v.split(' ')[0] if v.strip() else v for v in vals]
                    pedacos.append(vals)
                for combo in product(*pedacos) if pedacos else []:
                    alts.append(''.join(combo))
                    if len(alts) > MAX_ALT * 4:
                        break
        if not alts:
            it = self.itens.get(nome)
            fs = self.filhos.get(nome) if it else None
            if it and it.get('value') not in (None, ''):
                alts = [str(it['value'])]
            elif fs:
                pedacos = [self._elementar(f, prof, vistos) for f in fs]
                alts = [''.join(c) for c in product(*pedacos)][:MAX_ALT * 4]
            else:
                alts = ['<' + nome + '>']
        out = []
        for a in alts:
            if a not in out:
                out.append(a)
        return out[:MAX_ALT]

    def _elementar(self, it, prof, vistos):
        if it['name'] != 'FILLER' and (self.atrib.get(it['name']) or it.get('value') in (None, '')):
            return self.valor(it['name'], prof + 1, vistos)
        if it.get('value') not in (None, ''):
            return [str(it['value'])]
        return [' ']


def _norm(txt):
    return ' '.join(str(txt).split())


def _sql_toks(sql):
    return _toks(sql)


def analisar(source_text):
    """Comandos SQL dinâmicos do programa: [{'linha', 'campo', 'comando', 'montagens', 'tabelas', 'operacao', 'linhas'}]."""
    ast = parse_text(source_text)
    model = build_data_model(source_text)['items']
    ras = _Rastreio(model, _atribuicoes(ast))
    prep, exec_ = {}, {}
    imediatos, cursores, usos = [], {}, []
    for n in _walk(ast.get('body', [])):
        if n.get('type') != 'EXEC_SQL':
            continue
        sql, ln = n.get('sql', ''), n.get('start_line')
        tk = _sql_toks(sql)
        up = [t.upper() for t in tk]
        if not up:
            continue
        if up[0] == 'PREPARE' and 'FROM' in up:
            stmt = up[1]
            fonte = tk[up.index('FROM') + 1:]
            prep[stmt] = {'linha': ln, 'fonte': ''.join(fonte)}
        elif up[0] == 'EXECUTE' and len(up) > 1 and up[1] == 'IMMEDIATE':
            imediatos.append({'linha': ln, 'fonte': ''.join(tk[2:]).split('USING')[0]})
        elif up[0] == 'EXECUTE' and len(up) > 1:
            exec_.setdefault(up[1], []).append(ln)
        elif up[0] == 'DECLARE' and 'CURSOR' in up and 'FOR' in up and up[up.index('FOR') + 1] != 'SELECT':
            cursores[up[1]] = {'stmt': up[up.index('FOR') + 1], 'linha': ln}
        elif up[0] in ('OPEN', 'FETCH', 'CLOSE') and len(up) > 1:
            usos.append((up[1], ln))
    cmds = []

    def montar(fonte):
        f = fonte.strip()
        if f.startswith(':'):
            vals = ras.valor(_nome(f[1:].split(':')[0]))
        elif _literal(f):
            vals = [f[1:-1]]
        else:
            vals = ras.valor(_nome(f))
        return [_norm(v) for v in vals if _norm(v)]

    def tabelas(montagens):
        ts = set()
        for m in montagens:
            for t in sql_tables(tokens_of(m.replace('<', ' ').replace('>', ' '))):
                ts.add(t.upper())
        return sorted(ts)

    def op(montagens):
        m = re.match(r'\s*([A-Za-z]+)', montagens[0]) if montagens else None
        return m.group(1).upper() if m else 'SQL DINÂMICO'

    for stmt, p in sorted(prep.items(), key=lambda kv: kv[1]['linha'] or 0):
        linhas = [p['linha']] + exec_.get(stmt, [])
        for c, d in cursores.items():
            if d['stmt'] == stmt:
                linhas += [d['linha']] + [l for (nome, l) in usos if nome == c]
        mont = montar(p['fonte'])
        cmds.append({'linha': p['linha'], 'campo': p['fonte'].lstrip(':'), 'comando': stmt, 'montagens': mont, 'tabelas': tabelas(mont), 'operacao': op(mont), 'linhas': sorted({l for l in linhas if l})})
    for i in imediatos:
        mont = montar(i['fonte'])
        cmds.append({'linha': i['linha'], 'campo': i['fonte'].lstrip(':'), 'comando': '', 'montagens': mont, 'tabelas': tabelas(mont), 'operacao': op(mont), 'linhas': [i['linha']]})
    return cmds
