"""Serviços de acesso à APIs externas.

Este subpacote contém utilidades para interagir com APIs de terceiros,
como a plataforma GoHighLevel.  Separar essa camada de acesso ao
mundo exterior facilita testes, pois permite a criação de mocks para
chamadas HTTP.  Ao centralizar a comunicação com a API aqui, o
restante da aplicação pode focar na lógica de negócio sem se
preocupar com detalhes de requisições ou formatação de URLs.
"""

__all__ = ["ghl_api"]