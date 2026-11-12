"""Configuração do projeto analisado (analise.config.json): o que depende do código-fonte ou da plataforma e não pode ficar escrito nos scripts.

Procura, nesta ordem: a variável ANALISE_CONFIG, <pasta-de-cenarios>/analise.config.json (tools/analisar.py a aponta), ./analise.config.json.
Sem arquivo, valem os padrões abaixo (plataforma CICS/DB2). Chaves:
  prefixo_core                  prefixo dos programas do core business (classificação da fase 0); vazio = sem regra de prefixo
  campos_infraestrutura         expressões regulares de campos que o ambiente de execução fornece (critério sobre eles é infraestrutura)
  sqlcode_negocio               valores de SQLCODE que são de negócio (registro não encontrado, chave duplicada); os demais são infraestrutura
  categorias_mecanismo_validacao  categorias com que a IA pode descartar regra de tipo validação como mecanismo
  api                           versão da API dos contratos (fase 20), ex.: {"versao": "v1"} (caminhos /v1/...); "prefixo" opcional na frente da versão
  programas_mainframe           programas mainframe novos (fase 19), ex.: {"funcional": "3"}: cada comando tem um coordenador <sistema>1 + 3 letras, que lê e responde
                                nas filas, e um funcional <sistema>3 + as mesmas 3 letras, que executa o SQL ou chama o programa corporativo; sem a chave, um programa só
"""
import json
import os
import re
from pathlib import Path

PADRAO = {
    'prefixo_core': '',
    'campos_infraestrutura': [r'EIB[A-Z0-9-]*', r'SQLSTATE', r'SQLCA[A-Z0-9-]*', r'SQLERR[A-Z0-9-]*', r'SQLWARN[A-Z0-9-]*', r'RETURN-CODE', r'DFHRESP'],
    'sqlcode_negocio': ['+100', '100', '-803'],
    'categorias_mecanismo_validacao': ['permissão de acesso', 'infraestrutura CICS', 'paginação'],
}


def carregar(caminho=None):
    p = caminho or os.environ.get('ANALISE_CONFIG')
    cfg = dict(PADRAO)
    if p and Path(p).is_file():
        cfg.update(json.loads(Path(p).read_text(encoding='utf-8')))
    elif (Path('analise.config.json')).is_file() and not p:
        cfg.update(json.loads(Path('analise.config.json').read_text(encoding='utf-8')))
    return cfg


def campo_infra():
    return re.compile('^(' + '|'.join(carregar()['campos_infraestrutura']) + ')$')
