"""Scripts utilitários para tarefas de manutenção.

Esta pasta contém scripts autônomos que podem ser executados a partir
da linha de comando.  Eles realizam tarefas auxiliares que não fazem
parte do fluxo principal de tratamento de webhooks, como a atualização
de tokens do GoHighLevel, sincronização de usuários e atualização de
campos personalizados ou atribuição de contatos.  Os scripts foram
mantidos aqui para compatibilidade com o código legado, mas foram
adaptados para utilizar o diretório de dados definido em
``ia_zoi.config``.

Cada script pode ser chamado individualmente via ``python -m
ia_zoi.scripts.nome_do_script`` ou através do roteador em
``ia_zoi.web.router``.  Quando possível, procure migrar a lógica para
módulos de serviço reutilizáveis em vez de scripts.
"""

__all__ = [
    "refresh_tokens",
    "get_users",
    "update_user_list",
    "process_contact_assignment",
    "fetch_locations",
    "init_token",
    "oauth_setup",
]