"""O cliente e a unica coisa entre o grafo e a rede: retry, classificacao e sigilo."""

import httpx
import pytest

from sentinela_graph.linear.client import BACKOFF_BASE_S, MAX_TENTATIVAS, LinearClient
from sentinela_graph.linear.errors import (
    LinearAuthError,
    LinearDeterministicoError,
    LinearTransienteError,
)

from .conftest import CHAVE_FALSA, dados, erro_graphql


def rate_limited() -> httpx.Response:
    """O formato real do rate limit do Linear: HTTP 400, nao 429."""
    return httpx.Response(
        400,
        json={"errors": [{"message": "Rate limit", "extensions": {"code": "RATELIMITED"}}]},
    )


def test_authorization_e_a_chave_crua(espiao):
    e = espiao(dados({"viewer": {"id": "u1"}}))
    with e.cliente() as c:
        c.executar("{ viewer { id } }")
    # O Linear usa a chave crua; prefixar "Bearer " faz a chamada falhar com 401.
    assert e.ultima.authorization == CHAVE_FALSA


def test_5xx_faz_retry_com_backoff_exponencial(espiao):
    e = espiao(
        httpx.Response(503, text="unavailable"),
        httpx.Response(500, text="boom"),
        dados({"viewer": {"id": "u1"}}),
    )
    with e.cliente() as c:
        assert c.executar("{ viewer { id } }") == {"viewer": {"id": "u1"}}
    assert len(e.chamadas) == 3
    assert e.esperas == [BACKOFF_BASE_S, BACKOFF_BASE_S * 2]


def test_4xx_falha_na_primeira_chamada(espiao):
    e = espiao(httpx.Response(400, json={"errors": [{"message": "Argument Validation Error"}]}))
    with e.cliente() as c, pytest.raises(LinearDeterministicoError, match="Argument Validation"):
        c.executar("{ viewer { id } }")
    assert len(e.chamadas) == 1
    assert e.esperas == []


def test_rate_limit_em_400_e_transiente(espiao):
    # Discrimina a decisao 2 do plano: a regra literal "4xx falha na hora"
    # trataria isto como definitivo e o grafo desistiria de algo recuperavel.
    e = espiao(rate_limited(), dados({"viewer": {"id": "u1"}}))
    with e.cliente() as c:
        assert c.executar("{ viewer { id } }") == {"viewer": {"id": "u1"}}
    assert len(e.chamadas) == 2


def test_429_tambem_e_transiente(espiao):
    e = espiao(httpx.Response(429, text="slow down"), dados({"ok": True}))
    with e.cliente() as c:
        assert c.executar("{ ok }") == {"ok": True}
    assert len(e.chamadas) == 2


def test_esgota_apos_max_tentativas(espiao):
    e = espiao(*[httpx.Response(500) for _ in range(MAX_TENTATIVAS)])
    with e.cliente() as c, pytest.raises(LinearTransienteError, match=str(MAX_TENTATIVAS)):
        c.executar("{ ok }")
    assert len(e.chamadas) == MAX_TENTATIVAS
    assert len(e.esperas) == MAX_TENTATIVAS - 1


def test_falha_de_rede_e_transiente():
    tentativas = []

    def cai(request: httpx.Request) -> httpx.Response:
        tentativas.append(request)
        raise httpx.ConnectError("sem rota para o host", request=request)

    esperas: list[float] = []
    c = LinearClient(CHAVE_FALSA, transport=httpx.MockTransport(cai), dormir=esperas.append)
    with c, pytest.raises(LinearTransienteError):
        c.executar("{ ok }")
    assert len(tentativas) == MAX_TENTATIVAS


def test_erro_em_http_200_e_deterministico(espiao):
    # O GraphQL responde 200 com `errors`; olhar so o status code deixaria
    # passar uma issue inexistente como se fosse sucesso.
    e = espiao(erro_graphql("Entity not found: Issue"))
    with e.cliente() as c, pytest.raises(LinearDeterministicoError, match="Entity not found"):
        c.executar("{ issue { id } }")
    assert len(e.chamadas) == 1


def test_resposta_sem_data_e_deterministico(espiao):
    e = espiao(httpx.Response(200, json={}))
    with e.cliente() as c, pytest.raises(LinearDeterministicoError, match="sem `data`"):
        c.executar("{ ok }")


def test_chave_rejeitada_vira_auth_error(espiao):
    e = espiao(httpx.Response(401, json={"errors": [{"message": "Authentication required"}]}))
    with e.cliente() as c, pytest.raises(LinearAuthError, match="Settings"):
        c.executar("{ viewer { id } }")
    assert len(e.chamadas) == 1


def test_auth_error_e_deterministico():
    # Um no que trata `LinearDeterministicoError` tem que pegar auth tambem:
    # chave errada nao melhora com retry.
    assert issubclass(LinearAuthError, LinearDeterministicoError)


def test_chave_ausente_falha_com_mensagem_acionavel(monkeypatch):
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    with pytest.raises(LinearDeterministicoError) as info:
        LinearClient()
    mensagem = str(info.value)
    assert "LINEAR_API_KEY" in mensagem
    assert ".env" in mensagem
    assert "Traceback" not in mensagem


def test_chave_vem_do_ambiente_quando_nao_passada(monkeypatch):
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_DO_AMBIENTE")
    chamadas: list[str | None] = []

    def h(request: httpx.Request) -> httpx.Response:
        chamadas.append(request.headers.get("authorization"))
        return httpx.Response(200, json={"data": {}})

    with LinearClient(transport=httpx.MockTransport(h)) as c:
        c.executar("{ ok }")
    assert chamadas == ["lin_api_DO_AMBIENTE"]


def test_segredo_nao_aparece_no_repr(espiao):
    e = espiao(dados({}))
    c = e.cliente()
    assert CHAVE_FALSA not in repr(c)
    assert "***" in repr(c)
    c.close()


def test_segredo_nao_aparece_nas_mensagens_de_erro(espiao):
    e = espiao(*[httpx.Response(500, text=f"erro com {CHAVE_FALSA} no corpo") for _ in range(3)])
    with e.cliente() as c, pytest.raises(LinearTransienteError) as info:
        c.executar("{ ok }")
    assert CHAVE_FALSA not in str(info.value)


def test_segredo_nao_aparece_no_log(espiao, caplog):
    e = espiao(httpx.Response(500), dados({"ok": True}))
    with caplog.at_level("DEBUG"), e.cliente() as c:
        c.executar("{ ok }")
    assert CHAVE_FALSA not in caplog.text


def test_documento_e_variaveis_viajam_no_corpo(espiao):
    e = espiao(dados({"ok": True}))
    with e.cliente() as c:
        c.executar("query X($a: String!) { x(a: $a) }", {"a": "valor"})
    assert e.ultima.documento == "query X($a: String!) { x(a: $a) }"
    assert e.ultima.variaveis == {"a": "valor"}
