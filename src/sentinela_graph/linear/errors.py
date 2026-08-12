"""Duas classes de falha, tratadas de formas opostas.

Transiente ganha retry dentro do no e nao consome tentativa do ciclo de
correcao — o implementador nao errou. Deterministico falha na hora e vira
outcome `erro`.
"""


class LinearError(Exception):
    """Raiz de tudo que este pacote levanta."""


class LinearTransienteError(LinearError):
    """5xx, rede, rate limit. Vale retry."""


class LinearDeterministicoError(LinearError):
    """Chave ausente, argumento invalido, entidade inexistente. Retry nao ajuda."""


class LinearAuthError(LinearDeterministicoError):
    """Chave rejeitada.

    Herda de deterministico de proposito: um no que trata
    `LinearDeterministicoError` tem que pegar isto tambem, porque chave
    errada nao melhora tentando de novo.
    """
