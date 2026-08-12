"""Transporte GraphQL do Linear: autenticacao, retry e classificacao de erro."""

import os
import time
from collections.abc import Callable
from types import TracebackType
from typing import Any

import httpx

from sentinela_graph.linear.errors import (
    LinearAuthError,
    LinearDeterministicoError,
    LinearTransienteError,
)

ENDPOINT = "https://api.linear.app/graphql"
MAX_TENTATIVAS = 3
BACKOFF_BASE_S = 0.5
TIMEOUT_S = 30.0

# O Linear devolve o limite de requisicoes como HTTP 400 com este codigo em
# `extensions`, nao como 429. Sem esta excecao a regra "4xx falha na hora"
# faria o grafo desistir de uma condicao que a spec chama de transiente.
CODIGO_RATE_LIMIT = "RATELIMITED"


def _codigos(corpo: dict[str, Any]) -> set[str]:
    return {
        str((erro.get("extensions") or {}).get("code"))
        for erro in corpo.get("errors") or []
        if (erro.get("extensions") or {}).get("code")
    }


def _mensagens(corpo: dict[str, Any]) -> str:
    erros = corpo.get("errors") or []
    return "; ".join(str(e.get("message", "erro sem mensagem")) for e in erros) or "sem detalhe"


class LinearClient:
    """Cliente sincrono do GraphQL do Linear.

    `transport` e `dormir` existem para os testes: `httpx.MockTransport`
    intercepta antes do socket e `dormir` torna o backoff observavel sem
    gastar tempo de relogio.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        chave = api_key or os.environ.get("LINEAR_API_KEY")
        if not chave:
            raise LinearDeterministicoError(
                "LINEAR_API_KEY ausente. Preencha no .env da raiz do projeto "
                "(modelo em .env.template) ou exporte a variavel antes de rodar."
            )
        self._chave = chave
        self._dormir = dormir
        self._http = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(TIMEOUT_S),
            headers={"Content-Type": "application/json"},
        )

    def __repr__(self) -> str:
        # A chave nunca sai daqui: este objeto aparece em traceback de no.
        return "LinearClient(api_key=***)"

    def __enter__(self) -> "LinearClient":
        return self

    def __exit__(
        self,
        tipo: type[BaseException] | None,
        valor: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def executar(self, documento: str, variaveis: dict[str, Any] | None = None) -> dict[str, Any]:
        """Roda uma operacao e devolve `data`. Levanta em qualquer erro."""
        ultima: Exception | None = None
        for tentativa in range(MAX_TENTATIVAS):
            try:
                return self._uma_chamada(documento, variaveis or {})
            except LinearTransienteError as erro:
                ultima = erro
                if tentativa < MAX_TENTATIVAS - 1:
                    self._dormir(BACKOFF_BASE_S * (2**tentativa))
        raise LinearTransienteError(
            f"Linear indisponivel apos {MAX_TENTATIVAS} tentativas: {ultima}"
        ) from ultima

    def _uma_chamada(self, documento: str, variaveis: dict[str, Any]) -> dict[str, Any]:
        try:
            resposta = self._http.post(
                ENDPOINT,
                json={"query": documento, "variables": variaveis},
                headers={"Authorization": self._chave},
            )
        except httpx.TransportError as erro:
            # Cobre ConnectError, ReadTimeout e afins — todos recuperaveis.
            # O texto da excecao nao entra na mensagem: pode conter a URL
            # com credencial em cenarios de proxy.
            raise LinearTransienteError(f"falha de rede: {type(erro).__name__}") from None

        corpo = self._corpo(resposta)
        codigos = _codigos(corpo)
        status = resposta.status_code

        if status in (401, 403):
            raise LinearAuthError(
                f"LINEAR_API_KEY rejeitada pelo Linear (HTTP {status}). "
                "Gere outra em Settings > Security & access > Personal API keys."
            )
        if status == 429 or CODIGO_RATE_LIMIT in codigos:
            raise LinearTransienteError(f"rate limit do Linear (HTTP {status})")
        if status >= 500:
            raise LinearTransienteError(f"Linear respondeu HTTP {status}")
        if status >= 400:
            raise LinearDeterministicoError(
                f"Linear recusou a chamada (HTTP {status}): {_mensagens(corpo)}"
            )
        if corpo.get("errors"):
            # HTTP 200 com `errors` e o caso normal do GraphQL para entidade
            # inexistente. Olhar so o status code deixaria passar como sucesso.
            raise LinearDeterministicoError(f"Linear devolveu erro: {_mensagens(corpo)}")

        dados = corpo.get("data")
        if not isinstance(dados, dict):
            raise LinearDeterministicoError("Linear devolveu resposta sem `data`")
        return dados

    @staticmethod
    def _corpo(resposta: httpx.Response) -> dict[str, Any]:
        try:
            corpo = resposta.json()
        except ValueError:
            return {}
        return corpo if isinstance(corpo, dict) else {}
