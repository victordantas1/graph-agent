"""Duble do endpoint GraphQL do Linear.

Nenhum teste deste pacote toca a rede: o `httpx.MockTransport` intercepta
antes do socket. O `Espiao` grava o que saiu para que os testes possam
afirmar sobre o filtro e as variaveis enviadas, nao so sobre o retorno.
"""

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from sentinela_graph.linear.client import LinearClient

CHAVE_FALSA = "lin_api_CHAVE_DE_TESTE"


@dataclass
class Chamada:
    documento: str
    variaveis: dict[str, Any]
    authorization: str | None


def dados(payload: dict[str, Any]) -> httpx.Response:
    """Resposta de sucesso do GraphQL."""
    return httpx.Response(200, json={"data": payload})


def erro_graphql(mensagem: str, codigo: str | None = None) -> httpx.Response:
    """HTTP 200 com `errors` — o caso que o status code sozinho nao pega."""
    extensions = {"extensions": {"code": codigo}} if codigo else {}
    return httpx.Response(200, json={"data": None, "errors": [{"message": mensagem, **extensions}]})


@dataclass
class Espiao:
    """Serve respostas em sequencia e grava as chamadas e as esperas."""

    respostas: list[httpx.Response]
    chamadas: list[Chamada] = field(default_factory=list)
    esperas: list[float] = field(default_factory=list)

    def _handler(self, request: httpx.Request) -> httpx.Response:
        corpo = json.loads(request.content)
        self.chamadas.append(
            Chamada(
                documento=corpo["query"],
                variaveis=corpo.get("variables") or {},
                authorization=request.headers.get("authorization"),
            )
        )
        if not self.respostas:
            raise AssertionError(
                f"o duble recebeu {len(self.chamadas)} chamadas e so tinha respostas para "
                f"{len(self.chamadas) - 1}"
            )
        return self.respostas.pop(0)

    def cliente(self) -> LinearClient:
        return LinearClient(
            CHAVE_FALSA,
            transport=httpx.MockTransport(self._handler),
            dormir=self.esperas.append,
        )

    @property
    def ultima(self) -> Chamada:
        return self.chamadas[-1]


@pytest.fixture
def espiao():
    """Fabrica de espioes: `espiao(dados({...}), dados({...}))`."""

    def cria(*respostas: httpx.Response) -> Espiao:
        return Espiao(respostas=list(respostas))

    return cria
