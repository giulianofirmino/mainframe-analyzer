"""Padrão único de cores de todos os diagramas dos relatórios.

Regra: a cor diz o que o elemento é, e o mesmo elemento tem a mesma cor em qualquer diagrama.
- Classes de programa (borda colorida): COORDENADOR azul, FUNCIONAL verde, CORPORATIVO laranja, INFRAESTRUTURA vermelho.
- Comandos SQL: azul-petróleo para o que lê (SELECT, FETCH, comando estático Qnn que substitui consulta dinâmica) e roxo para o que grava (INSERT, UPDATE, DELETE, MERGE).
  Nenhuma outra categoria usa essas duas cores, para que o comando SQL se destaque em qualquer diagrama.
"""
COR_CLASSE = {'COORDENADOR': '#0072B2', 'FUNCIONAL': '#1E8E3E', 'CORPORATIVO': '#F28C00', 'INFRAESTRUTURA': '#D32F2F'}
COR_SQL_LE = '#00838F'
COR_SQL_GRAVA = '#6A1B9A'
COR_SQL = {'lê': COR_SQL_LE, 'grava': COR_SQL_GRAVA}
GRAVACAO = ('INSERT', 'UPDATE', 'DELETE', 'MERGE')


def cor_sql(comando):
    """Cor do comando SQL pelo verbo (primeira palavra do texto)."""
    p = (str(comando).split() or [''])[0].upper()
    return COR_SQL_GRAVA if p in GRAVACAO else COR_SQL_LE


# Categorias de regra: a mesma cor no diagrama macro, nos fluxos de regras e nos mapas de tipos de regra.
COR_VALIDACAO, COR_DERIVACAO, COR_AUDITORIA, COR_SUCESSO, COR_ERRO, COR_OUTRAS, COR_ROTEAMENTO = '#56B4E9', '#8D6E63', '#5E7C16', '#009E73', '#CC79A7', '#999999', '#455A64'
COR_REGRA = {'Validações': COR_VALIDACAO, 'Consultas DB2': COR_SQL_LE, 'Alterações de estado DB2': COR_SQL_GRAVA, 'Derivações e valores padrão': COR_DERIVACAO, 'Auditoria': COR_AUDITORIA,
             'Retorno de sucesso': COR_SUCESSO, 'Tratamento de erro': COR_ERRO, 'Outras regras': COR_OUTRAS, 'Chamadas Corporativas': COR_CLASSE['CORPORATIVO']}
