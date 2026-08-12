"""Acesso deterministico ao Linear.

Todo caminho de leitura e de escrita passa por aqui. Nenhum agente LLM
recebe ferramenta deste pacote que escreva: a E4 expoe apenas a leitura.
"""

from sentinela_graph.linear.client import LinearClient
from sentinela_graph.linear.errors import (
    LinearAuthError,
    LinearDeterministicoError,
    LinearError,
    LinearTransienteError,
)

__all__ = [
    "LinearAuthError",
    "LinearClient",
    "LinearDeterministicoError",
    "LinearError",
    "LinearTransienteError",
]
