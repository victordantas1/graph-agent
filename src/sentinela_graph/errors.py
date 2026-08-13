"""Erros do grafo.

Todos deterministicos: quando um deles sobe, o run termina com outcome
`erro`. Erro transiente nao vira excecao — vira retry dentro do no.
"""


class SentinelaError(Exception):
    """Base de todo erro deterministico do grafo."""


class RegistryError(SentinelaError):
    """Registry ausente, malformado ou incoerente. Para o boot."""


class WorkspaceError(SentinelaError):
    """Worktree impossivel de preparar ou de finalizar com seguranca."""


class GateError(SentinelaError):
    """Os gates nao puderam sequer ser executados (diff impossivel, root ausente)."""
