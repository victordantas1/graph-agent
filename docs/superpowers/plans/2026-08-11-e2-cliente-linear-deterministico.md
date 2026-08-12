# E2 — Cliente Linear determinístico (leitura e escrita) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir a camada de acesso ao Linear — leitura da fila, congelamento da issue, transições de status, comentários, vínculo do MR e labels de outcome — inteiramente determinística, testada com dublê HTTP, e verificável contra o workspace real por um comando.

**Arquitetura:** Um `LinearClient` sobre `httpx` concentra autenticação, retry com backoff e a classificação transiente × determinístico. Acima dele, quatro módulos finos e sem estado — `fila`, `carga`, `escrita`, `labels` — traduzem GraphQL para os modelos Pydantic da E1 e de volta. Nenhum agente LLM toca este pacote: a E4 vai expor só uma função de *leitura* (`fetch_linear_issue`) sobre o mesmo cliente, e a escrita fica estruturalmente inalcançável.

**Tech Stack:** Python 3.12, `httpx` (síncrono, com `httpx.MockTransport` como dublê), Pydantic 2, `python-dotenv`, `typer`, pytest, ruff.

**Épico:** [#2](https://github.com/victordantas1/graph-agent/issues/2) · **Tasks:** [#16](https://github.com/victordantas1/graph-agent/issues/16) [#17](https://github.com/victordantas1/graph-agent/issues/17) [#18](https://github.com/victordantas1/graph-agent/issues/18) [#19](https://github.com/victordantas1/graph-agent/issues/19) [#20](https://github.com/victordantas1/graph-agent/issues/20)
**Spec:** [`docs/superpowers/specs/2026-08-11-graph-of-agents-design.md`](../specs/2026-08-11-graph-of-agents-design.md)
**Depende de:** E1, já em `master` (commit de merge `3518641`).

## Global Constraints

Valem para **todas** as tasks. Copiadas da spec e das regras de operação do usuário.

- **Nenhum segredo entra em log, exceção, `repr`, commit ou mensagem de erro.** `LINEAR_API_KEY` só existe em memória e no header `Authorization`.
- **Nunca mover uma issue para `Done`.** Quem fecha é o merge.
- Status reais do time Nomos: `Backlog`, `Prioritized`, `Design`, `To Do`, `Doing`, `Review`, `Bugs`, `Done`, `Canceled`, `Duplicate`. **Não existe "In Progress" nem "In Review".**
- Time `Nomos`, prefixo/`key` `NOM`. Fila = `state.name == "To Do"` **e** label `Ready` **e** `assignee == viewer`. **Nunca relaxar o filtro.**
- Nome de branch vem do campo `branchName` da issue, nunca inventado.
- Transiente (5xx, rede, rate limit) → retry com backoff exponencial, máximo 3. Determinístico (chave ausente, chave rejeitada, entidade inexistente, argumento inválido) → falha imediata, sem retry.
- `git add` **caminho a caminho**, nunca `-A`. Há service accounts `.json` untracked em `nomos-api/app/` e em `/home/victor/nomos/`.
- Nunca usar `--no-verify` no commit.
- Comentários de código e nomes em português sem acento, como na E1. Docstrings explicam **por quê**, não o quê.
- Gate completo antes de cada commit: `uv run ruff check && uv run ruff format --check && uv run pytest`.
- `line-length = 100`, ruff `select = ["E","F","I","UP","B"]`.
- Testes com dublê HTTP via `httpx.MockTransport`. **Nenhum teste toca a rede.**

---

## Decisões que estendem ou corrigem as issues

Tudo abaixo foi verificado contra o schema GraphQL real do Linear (`linear/linear@master:packages/sdk/src/schema.graphql`, 50.383 linhas, baixado e validado com `graphql-core`) e contra a documentação de rate limiting. Os dez documentos GraphQL deste plano passam por `graphql.validate` contra esse schema. Onde este plano diverge do texto de uma issue, a divergência está aqui.

**1. O campo é `branchName`, não `gitBranchName`.**
A skill `linear-ready-loop` e o MCP do Linear chamam de `gitBranchName`; o schema GraphQL cru chama de `branchName: String!`. A E1 modelou `IssueRef.git_branch_name`. O mapeamento acontece em `carga.py`. Pedir `gitBranchName` na query devolve erro de campo desconhecido.

**2. Rate limit do Linear chega como HTTP 400, não 429.**
A issue #16 diz "5xx → retry e 4xx → falha imediata". A documentação do Linear diz que o limite de requisições devolve **HTTP 400** com `errors[].extensions.code == "RATELIMITED"`. A regra literal de 4xx faria o grafo desistir de uma condição recuperável que a própria spec classifica como transiente. A classificação implementada é: 5xx → transiente; 429 → transiente; **400 com `code == "RATELIMITED"` → transiente**; 401/403 → erro de autenticação (determinístico); demais 4xx → determinístico; HTTP 200 com `errors` → determinístico.

**3. Ordenar por prioridade é trabalho do cliente, e prioridade 0 é a menor.**
`PaginationOrderBy` só aceita `createdAt` e `updatedAt` — não dá para ordenar por prioridade no servidor. E a escala do Linear é `0 = sem prioridade, 1 = Urgent, 2 = High, 3 = Medium, 4 = Low`: ordenar por `priority` ascendente jogaria as issues **sem prioridade** para a frente de todas as urgentes. A ordenação é local, com chave `(priority == 0, priority, created_at)` e desempate pela mais antiga.

**4. Aplicar label usa `addedLabelIds`/`removedLabelIds`, nunca `labelIds`.**
`IssueUpdateInput.labelIds` **substitui o conjunto inteiro**: usá-lo para pôr `agent:blocked` arrancaria a label `Ready` da issue, e a issue sumiria da própria fila que o grafo lê. `addedLabelIds` e `removedLabelIds` existem no schema exatamente para isso.

**5. O bloqueio de status terminal é por `type`, não por nome.**
A spec proíbe `Done`. `WorkflowState.type` assume `triage|backlog|unstarted|started|completed|canceled|duplicate`; barrar os tipos `completed`, `canceled` e `duplicate` cobre `Done` por construção e continua valendo se alguém renomear o status na UI do Linear. O critério de aceite de #19 ("`Done` nunca é um destino possível") é provado por teste direto sobre o nome, além do bloqueio por tipo.

**6. `IssueRef` ganha `links` — a dívida registrada da E1.**
A spec manda `load_issue` congelar "links e anexos". No modelo do Linear os dois são a mesma entidade (`Issue.attachments`), então vira um campo só: `IssueRef.links: list[IssueLink]`. Isso paga a dívida anotada em [#2](https://github.com/victordantas1/graph-agent/issues/2#issuecomment) e no comentário de dívidas da [#1](https://github.com/victordantas1/graph-agent/issues/1).

**7. Os três critérios de "NÃO é elegível" de #17 são provados sobre o filtro enviado.**
Um dublê HTTP não pode reimplementar o motor de filtro do Linear: se o teste devolvesse issues em `Doing` e o código as descartasse localmente, estaríamos testando um filtro que o servidor já deveria ter aplicado — e mascarando a falha real, que é enviar um filtro frouxo. O filtro é construído por uma função pura, `filtro_da_fila()`, e cada critério de aceite vira um teste sobre a cláusula correspondente do dicionário. Relaxar qualquer condição quebra um teste nomeado por aquele critério.

**8. `fetch_queue` devolve `list[ItemDaFila]`; o outcome `fila_vazia` é da E5.**
A issue #17 fala em "devolve outcome `fila_vazia`", mas o épico #2 declara "fora de escopo: qualquer nó do grafo". A camada de acesso devolve lista vazia; o nó da E5 traduz `if not fila` para `outcome = "fila_vazia"`. Lista, e não uma issue só, porque o diagnóstico da Task 6 precisa imprimir a fila inteira — o nó pega `[0]`.

**9. Task 6 existe além das cinco issues.**
A "Entrega verificável" do épico #2 é "um comando que imprime a fila real do Linear (…) e transições de status/comentários funcionando contra o workspace de verdade". Nenhuma das issues #16–#20 entrega esse comando. A Task 6 entrega um **diagnóstico**, explicitamente temporário: o CLI de produto é a [#55](https://github.com/victordantas1/graph-agent/issues/55) da E10, que o substitui.

**10. Suposição não verificada: `issue(id:)` aceita o identificador humano.**
Não há `LINEAR_API_KEY` nesta máquina, então isto não pôde ser testado contra a API. A descrição do schema diz apenas "unique identifier"; a documentação do SDK e a mutação `attachmentLinkURL` (que documenta "Can be a UUID or issue identifier (e.g., 'LIN-123')") indicam que o Linear resolve as duas formas. **Nada no caminho do grafo depende disso**: `fetch_queue` já devolve o `id` UUID e é ele que `load_issue` recebe. Só o `carregar NOM-716` do diagnóstico exercita a forma humana — e o smoke da Task 6 revela na hora se a suposição for falsa.

---

## File Structure

| Arquivo | Responsabilidade | Task |
|---|---|---|
| `src/sentinela_graph/linear/__init__.py` | Reexporta a superfície pública do pacote | 1 |
| `src/sentinela_graph/linear/errors.py` | Hierarquia de exceções: transiente × determinístico | 1 |
| `src/sentinela_graph/linear/client.py` | Transporte: auth, timeout, retry/backoff, classificação de erro, `executar()` | 1 |
| `src/sentinela_graph/linear/constantes.py` | Time, status e labels que a spec fixa | 2 |
| `src/sentinela_graph/linear/queries.py` | Documentos GraphQL, um por operação | 2, 3, 4, 5 |
| `src/sentinela_graph/linear/fila.py` | `filtro_da_fila()`, `ItemDaFila`, `fetch_queue()` | 2 |
| `src/sentinela_graph/linear/carga.py` | `load_issue()` — GraphQL → `IssueRef` congelada | 3 |
| `src/sentinela_graph/linear/escrita.py` | `mover_status()`, `comentar()`, `vincular_mr()` | 4 |
| `src/sentinela_graph/linear/labels.py` | Labels de outcome: criação idempotente, aplicação, remoção | 5 |
| `src/sentinela_graph/linear/__main__.py` | Diagnóstico contra o workspace real (temporário, ver decisão 9) | 6 |
| `src/sentinela_graph/models/issue.py` | **Modificar:** acrescentar `IssueLink` e `IssueRef.links` | 3 |
| `pyproject.toml` | **Modificar:** dependência `python-dotenv` | 1 |
| `.env.template` | **Modificar:** documentar `LINEAR_API_KEY` (append, ver Task 1 Passo 2) | 1 |
| `tests/linear/conftest.py` | `Espiao`: dublê do endpoint que grava chamadas e esperas | 1 |
| `tests/linear/test_client.py` | Retry, classificação, higiene do segredo | 1 |
| `tests/linear/test_fila.py` | O filtro estrito e a ordenação | 2 |
| `tests/linear/test_carga.py` | Mapeamento, ordem dos comentários, relações sem corpo, round-trip | 3 |
| `tests/linear/test_escrita.py` | Resolução de status, bloqueio terminal, markdown intacto | 4 |
| `tests/linear/test_labels.py` | Idempotência, matriz outcome→label, remoção | 5 |
| `tests/linear/test_diagnostico.py` | Formatação da fila e a trava do smoke de escrita | 6 |

---

### Task 1: Cliente GraphQL com autenticação, retry e classificação de erro

Fecha [#16](https://github.com/victordantas1/graph-agent/issues/16).

**Files:**
- Create: `src/sentinela_graph/linear/__init__.py`
- Create: `src/sentinela_graph/linear/errors.py`
- Create: `src/sentinela_graph/linear/client.py`
- Create: `tests/linear/__init__.py` (vazio)
- Create: `tests/linear/conftest.py`
- Create: `tests/linear/test_client.py`
- Modify: `pyproject.toml`
- Modify: `.env.template`

**Interfaces:**
- Consumes: nada da E1.
- Produces:
  - `LinearError`, `LinearTransienteError`, `LinearDeterministicoError`, `LinearAuthError` (subclasse de `LinearDeterministicoError`) — de `sentinela_graph.linear.errors`
  - `LinearClient(api_key: str | None = None, *, transport: httpx.BaseTransport | None = None, dormir: Callable[[float], None] = time.sleep)`
  - `LinearClient.executar(documento: str, variaveis: dict[str, Any] | None = None) -> dict[str, Any]` — devolve o conteúdo de `data`, já validado; levanta em qualquer erro
  - `LinearClient.close()`, e uso como context manager
  - Constantes `ENDPOINT`, `MAX_TENTATIVAS = 3`, `BACKOFF_BASE_S = 0.5`, `TIMEOUT_S = 30.0`
  - Fixture de teste `Espiao` em `tests/linear/conftest.py`, usada por todas as tasks seguintes

- [ ] **Passo 1: Acrescentar `python-dotenv` às dependências**

Em `pyproject.toml`, dentro de `[project].dependencies`, acrescente uma linha após `"typer>=0.27",`:

```toml
    "python-dotenv>=1.1",
```

Depois rode `uv sync` para atualizar `uv.lock`.

O cliente **não** lê `.env` — quem lê é o entrypoint da Task 6. Manter o cliente puro é o que permite que os testes o instanciem sem tocar no ambiente do desenvolvedor.

- [ ] **Passo 2: Documentar `LINEAR_API_KEY` no `.env.template`**

`.env.template` hoje tem exatamente três linhas e **não termina em quebra de linha**. **Acrescente** a quarta linha; **não reescreva nem reformate as três existentes** (o `https:/` com uma barra só é texto do usuário e fica como está). O arquivo inteiro deve ficar assim:

```
LANGFUSE_SECRET_KEY="sk-lf-"
LANGFUSE_PUBLIC_KEY="pk-lf-"
LANGFUSE_BASE_URL="https:/localhost:5000"
LINEAR_API_KEY="lin_api_"
```

Confira com `git diff .env.template`: o diff tem que ser de **uma** linha adicionada e nenhuma removida. Se aparecer linha removida, você reescreveu o arquivo — desfaça com `git checkout .env.template` e refaça acrescentando.

- [ ] **Passo 3: Escrever o dublê do endpoint**

Crie `tests/linear/__init__.py` vazio e `tests/linear/conftest.py`:

```python
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
```

- [ ] **Passo 4: Escrever os testes que falham**

Crie `tests/linear/test_client.py`:

```python
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
```

- [ ] **Passo 5: Rodar os testes e ver falhar**

```bash
uv run pytest tests/linear/test_client.py -q
```

Esperado: erro de coleta, `ModuleNotFoundError: No module named 'sentinela_graph.linear'`.

- [ ] **Passo 6: Escrever as exceções**

Crie `src/sentinela_graph/linear/__init__.py`:

```python
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
```

Crie `src/sentinela_graph/linear/errors.py`:

```python
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
```

- [ ] **Passo 7: Escrever o cliente**

Crie `src/sentinela_graph/linear/client.py`:

```python
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
```

- [ ] **Passo 8: Rodar os testes e ver passar**

```bash
uv run pytest tests/linear/test_client.py -q
```

Esperado: todos passam.

- [ ] **Passo 9: Gate completo**

```bash
uv run ruff check && uv run ruff format --check && uv run pytest
```

Esperado: sem achado, 56 testes da E1 + os novos, todos verdes.

- [ ] **Passo 10: Commit**

```bash
git add pyproject.toml uv.lock .env.template
git add src/sentinela_graph/linear/__init__.py src/sentinela_graph/linear/errors.py src/sentinela_graph/linear/client.py
git add tests/linear/__init__.py tests/linear/conftest.py tests/linear/test_client.py
git commit -m "feat(linear): cliente graphql com retry e classificacao de erro

Closes #16"
```

---

### Task 2: `fetch_queue` com o filtro estrito da fila

Fecha [#17](https://github.com/victordantas1/graph-agent/issues/17).

**Files:**
- Create: `src/sentinela_graph/linear/constantes.py`
- Create: `src/sentinela_graph/linear/queries.py`
- Create: `src/sentinela_graph/linear/fila.py`
- Create: `tests/linear/test_fila.py`

**Interfaces:**
- Consumes: `LinearClient.executar(documento, variaveis)` da Task 1; `Espiao`/`dados` de `tests/linear/conftest.py`.
- Produces:
  - `constantes.EQUIPE = "NOM"`, `STATUS_FILA = "To Do"`, `LABEL_FILA = "Ready"`, `STATUS_CLAIM = "Doing"`, `TIPOS_TERMINAIS`, `LIMITE_FILA = 50`
  - `queries.FILA` (documento GraphQL)
  - `fila.filtro_da_fila() -> dict[str, Any]`
  - `fila.ItemDaFila` (Pydantic: `id, identifier, title, url, priority, state, created_at`)
  - `fila.chave_de_ordenacao(item) -> tuple`
  - `fila.fetch_queue(client: LinearClient) -> list[ItemDaFila]` — já ordenada

- [ ] **Passo 1: Escrever os testes que falham**

Crie `tests/linear/test_fila.py`:

```python
"""A fila e o unico ponto onde o grafo escolhe trabalho. Filtro frouxo aqui
significa roubar issue de outra pessoa ou atropelar trabalho manual."""

from datetime import datetime, timedelta, timezone

from sentinela_graph.linear.constantes import EQUIPE, LABEL_FILA, LIMITE_FILA, STATUS_FILA
from sentinela_graph.linear.fila import ItemDaFila, fetch_queue, filtro_da_fila

from .conftest import dados

AGORA = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def no(identificador: str, prioridade: float, minutos: int = 0) -> dict:
    return {
        "id": f"uuid-{identificador}",
        "identifier": identificador,
        "title": f"titulo de {identificador}",
        "url": f"https://linear.app/nomos-tech/issue/{identificador}",
        "priority": prioridade,
        "createdAt": (AGORA + timedelta(minutes=minutos)).isoformat(),
        "state": {"name": STATUS_FILA},
    }


def fila_com(*nos: dict) -> dict:
    return {"issues": {"nodes": list(nos)}}


# --- criterios de aceite da #17, provados sobre o filtro que sai daqui ---
# Um duble nao pode reimplementar o motor de filtro do Linear. O que se
# pode provar — e o que de fato falha na producao — e o filtro ficar frouxo.


def test_filtro_exige_status_to_do():
    # Issue em `Doing` com label `Ready` NAO e elegivel.
    assert filtro_da_fila()["state"] == {"name": {"eq": "To Do"}}


def test_filtro_exige_label_ready():
    # Issue em `To Do` sem label `Ready` NAO e elegivel.
    assert filtro_da_fila()["labels"] == {"some": {"name": {"eq": "Ready"}}}


def test_filtro_exige_assignee_igual_ao_viewer():
    # Issue de outro assignee NAO e elegivel.
    assert filtro_da_fila()["assignee"] == {"isMe": {"eq": True}}


def test_filtro_exige_o_time_nomos():
    assert filtro_da_fila()["team"] == {"key": {"eq": "NOM"}}


def test_filtro_nao_tem_mais_nada():
    # Guarda contra alguem acrescentar um `or` que relaxe o conjunto.
    assert set(filtro_da_fila()) == {"team", "state", "labels", "assignee"}


def test_constantes_batem_com_a_spec():
    assert (EQUIPE, STATUS_FILA, LABEL_FILA) == ("NOM", "To Do", "Ready")


# --- a chamada ---


def test_envia_o_filtro_e_o_limite(espiao):
    e = espiao(dados(fila_com()))
    with e.cliente() as c:
        fetch_queue(c)
    assert e.ultima.variaveis == {"filtro": filtro_da_fila(), "limite": LIMITE_FILA}


def test_fila_vazia_devolve_lista_vazia(espiao):
    # Fila vazia e resposta final: quem traduz para o outcome `fila_vazia`
    # e o no da E5. Aqui nao ha relaxamento nem segunda chamada.
    e = espiao(dados(fila_com()))
    with e.cliente() as c:
        assert fetch_queue(c) == []
    assert len(e.chamadas) == 1


def test_congela_os_campos_do_item(espiao):
    e = espiao(dados(fila_com(no("NOM-716", 2))))
    with e.cliente() as c:
        (item,) = fetch_queue(c)
    assert item == ItemDaFila(
        id="uuid-NOM-716",
        identifier="NOM-716",
        title="titulo de NOM-716",
        url="https://linear.app/nomos-tech/issue/NOM-716",
        priority=2,
        state="To Do",
        created_at=AGORA,
    )


# --- ordenacao ---


def test_urgente_vem_antes_de_alta(espiao):
    e = espiao(dados(fila_com(no("NOM-2", 2), no("NOM-1", 1))))
    with e.cliente() as c:
        assert [i.identifier for i in fetch_queue(c)] == ["NOM-1", "NOM-2"]


def test_sem_prioridade_vai_para_o_fim(espiao):
    # Prioridade 0 no Linear e "sem prioridade", nao "a mais alta".
    # Ordenar por `priority` ascendente colocaria NOM-0 na frente da urgente.
    e = espiao(dados(fila_com(no("NOM-0", 0), no("NOM-4", 4), no("NOM-1", 1))))
    with e.cliente() as c:
        assert [i.identifier for i in fetch_queue(c)] == ["NOM-1", "NOM-4", "NOM-0"]


def test_empate_desempata_pela_mais_antiga(espiao):
    e = espiao(dados(fila_com(no("NOM-novo", 2, minutos=30), no("NOM-velho", 2, minutos=0))))
    with e.cliente() as c:
        assert [i.identifier for i in fetch_queue(c)] == ["NOM-velho", "NOM-novo"]


def test_ordem_e_estavel_entre_chamadas(espiao):
    # O grafo pega `[0]`: duas leituras da mesma fila tem que escolher a
    # mesma issue, senao `--resume` pode trocar de trabalho no meio.
    nos = [no("NOM-a", 0), no("NOM-b", 3, minutos=5), no("NOM-c", 3, minutos=1)]
    e = espiao(dados(fila_com(*nos)), dados(fila_com(*reversed(nos))))
    with e.cliente() as c:
        primeira = [i.identifier for i in fetch_queue(c)]
        segunda = [i.identifier for i in fetch_queue(c)]
    assert primeira == segunda == ["NOM-c", "NOM-b", "NOM-a"]
```

- [ ] **Passo 2: Rodar e ver falhar**

```bash
uv run pytest tests/linear/test_fila.py -q
```

Esperado: `ModuleNotFoundError: No module named 'sentinela_graph.linear.constantes'`.

- [ ] **Passo 3: Escrever as constantes**

Crie `src/sentinela_graph/linear/constantes.py`:

```python
"""O que a spec fixa sobre o workspace da Nomos.

Nada aqui e configuravel: sao os nomes reais do time no Linear. Errar um
faz a chamada falhar, nao produzir resultado parcial.
"""

EQUIPE = "NOM"
"""`Team.key` do time Nomos. As issues sao `NOM-<n>`."""

STATUS_FILA = "To Do"
LABEL_FILA = "Ready"
STATUS_CLAIM = "Doing"

LIMITE_FILA = 50
"""Teto da leitura da fila.

Uma fila de `To Do` + `Ready` + minhas com mais de 50 itens e um problema
de processo, nao de paginacao — e o grafo pega uma issue por run.
"""

TIPOS_TERMINAIS = frozenset({"completed", "canceled", "duplicate"})
"""`WorkflowState.type` para onde o agente nunca move uma issue.

Cobre `Done` por construcao, e continua valendo se o status for renomeado
na UI. Quem fecha a issue e o merge.
"""
```

`STATUS_MR` não entra agora: quem move a issue para `Review` é o nó `report` da E9, e constante sem consumidor é dívida. `STATUS_CLAIM` entra porque o smoke da Task 6 a usa.

- [ ] **Passo 4: Escrever o documento GraphQL**

Crie `src/sentinela_graph/linear/queries.py`:

```python
"""Documentos GraphQL, um por operacao.

Todos validados contra o schema publicado do Linear
(`linear/linear@master:packages/sdk/src/schema.graphql`). Valores de
usuario entram sempre por variavel, nunca por interpolacao: markdown com
aspas ou chaves quebraria o documento, e interpolar e como se injeta.
"""

FILA = """
query Fila($filtro: IssueFilter!, $limite: Int!) {
  issues(first: $limite, filter: $filtro) {
    nodes {
      id
      identifier
      title
      url
      priority
      createdAt
      state { name }
    }
  }
}
"""
```

- [ ] **Passo 5: Escrever a fila**

Crie `src/sentinela_graph/linear/fila.py`:

```python
"""Leitura da fila: o unico ponto onde o grafo escolhe trabalho."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from sentinela_graph.linear import queries
from sentinela_graph.linear.client import LinearClient
from sentinela_graph.linear.constantes import EQUIPE, LABEL_FILA, LIMITE_FILA, STATUS_FILA


class ItemDaFila(BaseModel):
    """Uma issue elegivel, com o minimo para ordenar e escolher.

    O corpo nao vem aqui: quem congela a issue inteira e `load_issue`,
    depois que uma foi escolhida.
    """

    id: str
    identifier: str
    title: str
    url: str
    priority: int
    state: str
    created_at: datetime


def filtro_da_fila() -> dict[str, Any]:
    """As quatro condicoes da fila, todas obrigatorias.

    Funcao pura de proposito: e sobre ela que os testes provam que o filtro
    nao afrouxou. Um duble HTTP nao consegue provar isso pelo retorno.
    """
    return {
        "team": {"key": {"eq": EQUIPE}},
        "state": {"name": {"eq": STATUS_FILA}},
        "labels": {"some": {"name": {"eq": LABEL_FILA}}},
        "assignee": {"isMe": {"eq": True}},
    }


def chave_de_ordenacao(item: ItemDaFila) -> tuple[int, int, datetime]:
    """Urgente primeiro, sem prioridade por ultimo, mais antiga desempata.

    No Linear `priority` e `0 = sem prioridade, 1 = Urgent, ..., 4 = Low`,
    entao ordenar por `priority` cru poria as sem prioridade na frente das
    urgentes. E `PaginationOrderBy` so aceita `createdAt`/`updatedAt`: nao
    da para delegar essa ordenacao ao servidor.
    """
    return (1 if item.priority == 0 else 0, item.priority, item.created_at)


def fetch_queue(client: LinearClient) -> list[ItemDaFila]:
    """Issues elegiveis, em ordem de atendimento. Lista vazia e resposta final."""
    dados = client.executar(
        queries.FILA, {"filtro": filtro_da_fila(), "limite": LIMITE_FILA}
    )
    itens = [
        ItemDaFila(
            id=no["id"],
            identifier=no["identifier"],
            title=no["title"],
            url=no["url"],
            priority=int(no["priority"]),
            state=no["state"]["name"],
            created_at=no["createdAt"],
        )
        for no in dados["issues"]["nodes"]
    ]
    return sorted(itens, key=chave_de_ordenacao)
```

- [ ] **Passo 6: Rodar e ver passar**

```bash
uv run pytest tests/linear/test_fila.py -q
```

Esperado: todos passam.

- [ ] **Passo 7: Gate completo e commit**

```bash
uv run ruff check && uv run ruff format --check && uv run pytest
git add src/sentinela_graph/linear/constantes.py src/sentinela_graph/linear/queries.py src/sentinela_graph/linear/fila.py
git add tests/linear/test_fila.py
git commit -m "feat(linear): fetch_queue com o filtro estrito da fila

Closes #17"
```

---

### Task 3: `load_issue` — congelar issue, comentários, links e relações

Fecha [#18](https://github.com/victordantas1/graph-agent/issues/18). Paga a dívida de E1 sobre `links`.

**Files:**
- Create: `src/sentinela_graph/linear/carga.py`
- Create: `tests/linear/test_carga.py`
- Modify: `src/sentinela_graph/models/issue.py`
- Modify: `src/sentinela_graph/linear/queries.py` (acrescentar `ISSUE`)
- Modify: `tests/models/test_issue.py` (cobrir `IssueLink`)

**Interfaces:**
- Consumes: `LinearClient.executar`; `IssueRef`, `Comment`, `IssueRelation`, `TipoRelacao` de `sentinela_graph.models.issue`.
- Produces:
  - `models.issue.IssueLink(title: str, url: str)`
  - `models.issue.IssueRef.links: list[IssueLink]` (default `[]`)
  - `carga.load_issue(client: LinearClient, id_da_issue: str) -> IssueRef`

- [ ] **Passo 1: Escrever os testes que falham**

Crie `tests/linear/test_carga.py`:

```python
"""`load_issue` congela o que o agente vai ver. Um campo perdido aqui vira
um agente decidindo com contexto incompleto, sem sinal nenhum."""

import json
from datetime import datetime, timezone

import pytest

from sentinela_graph.linear.carga import load_issue
from sentinela_graph.linear.errors import LinearDeterministicoError
from sentinela_graph.models.issue import IssueRef

from .conftest import dados, erro_graphql


def vizinha(identificador: str, estado: str = "To Do") -> dict:
    return {
        "identifier": identificador,
        "title": f"titulo de {identificador}",
        "url": f"https://linear.app/nomos-tech/issue/{identificador}",
        "state": {"name": estado},
    }


PAYLOAD = {
    "issue": {
        "id": "uuid-716",
        "identifier": "NOM-716",
        "title": "Clipping duplica materia",
        "url": "https://linear.app/nomos-tech/issue/NOM-716",
        "branchName": "bug/nom-716-clipping-duplica",
        "description": "## Contexto\n\nO clipping repete a mesma materia.",
        "priority": 1.0,
        "state": {"name": "To Do"},
        "labels": {"nodes": [{"name": "Ready"}, {"name": "Bug"}]},
        "comments": {
            "nodes": [
                {
                    "id": "c1",
                    "body": "Primeiro: o contrato.",
                    "createdAt": "2026-08-01T10:00:00.000Z",
                    "user": {"name": "Victor Dantas"},
                    "botActor": None,
                },
                {
                    "id": "c2",
                    "body": "Segundo: uma ressalva.",
                    "createdAt": "2026-08-02T10:00:00.000Z",
                    "user": {"name": "Maria Silva"},
                    "botActor": None,
                },
            ]
        },
        "attachments": {
            "nodes": [
                {"title": "Log do Sentry", "url": "https://sentry.io/issues/1"},
                {"title": "MR !7", "url": "https://gitlab.sing1.nomos.pro/x/-/merge_requests/7"},
            ]
        },
        "parent": vizinha("NOM-700", "Doing"),
        "children": {"nodes": [vizinha("NOM-717"), vizinha("NOM-718")]},
        "relations": {
            "nodes": [
                {"type": "blocks", "relatedIssue": vizinha("NOM-720")},
                {"type": "related", "relatedIssue": vizinha("NOM-721")},
            ]
        },
        "inverseRelations": {
            "nodes": [{"type": "blocks", "issue": vizinha("NOM-690", "Review")}],
        },
    }
}


@pytest.fixture
def issue(espiao):
    e = espiao(dados(PAYLOAD))
    with e.cliente() as c:
        return load_issue(c, "uuid-716")


def test_branch_name_vira_git_branch_name(issue):
    # O campo GraphQL cru e `branchName`; o MCP do Linear e a skill chamam
    # de `gitBranchName` e a E1 modelou `git_branch_name`. Pedir
    # `gitBranchName` na query devolve erro de campo desconhecido.
    assert issue.git_branch_name == "bug/nom-716-clipping-duplica"


def test_descricao_vira_spec(issue):
    # A descricao da issue e a spec escrita pelo humano.
    assert issue.spec.startswith("## Contexto")


def test_campos_diretos(issue):
    assert (issue.id, issue.identifier, issue.state, issue.priority) == (
        "uuid-716",
        "NOM-716",
        "To Do",
        1,
    )
    assert issue.labels == ["Ready", "Bug"]


def test_comentarios_preservam_ordem_autor_e_data(issue):
    assert [c.id for c in issue.comments] == ["c1", "c2"]
    assert [c.author for c in issue.comments] == ["Victor Dantas", "Maria Silva"]
    assert issue.comments[0].created_at == datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    assert issue.comments[0].created_at < issue.comments[1].created_at


def test_comentario_fora_de_ordem_e_reordenado(espiao):
    # O contrato mora nos comentarios e e cronologico: um comentario que
    # chegue fora de ordem inverteria o sentido do que o agente le.
    payload = json.loads(json.dumps(PAYLOAD))
    payload["issue"]["comments"]["nodes"].reverse()
    e = espiao(dados(payload))
    with e.cliente() as c:
        recarregada = load_issue(c, "uuid-716")
    assert [x.id for x in recarregada.comments] == ["c1", "c2"]


def test_comentario_de_bot_nao_perde_autoria(espiao):
    # `Comment.user` e anulavel: comentario de integracao vem com `botActor`.
    payload = json.loads(json.dumps(PAYLOAD))
    payload["issue"]["comments"]["nodes"][0]["user"] = None
    payload["issue"]["comments"]["nodes"][0]["botActor"] = {"name": "GitLab"}
    e = espiao(dados(payload))
    with e.cliente() as c:
        recarregada = load_issue(c, "uuid-716")
    assert recarregada.comments[0].author == "GitLab"


def test_comentario_sem_autor_nenhum_nao_quebra(espiao):
    payload = json.loads(json.dumps(PAYLOAD))
    payload["issue"]["comments"]["nodes"][0]["user"] = None
    payload["issue"]["comments"]["nodes"][0]["botActor"] = None
    e = espiao(dados(payload))
    with e.cliente() as c:
        recarregada = load_issue(c, "uuid-716")
    assert recarregada.comments[0].author == "desconhecido"


def test_links_congelam_titulo_e_url(issue):
    assert [(x.title, x.url) for x in issue.links] == [
        ("Log do Sentry", "https://sentry.io/issues/1"),
        ("MR !7", "https://gitlab.sing1.nomos.pro/x/-/merge_requests/7"),
    ]


def test_relacoes_cobrem_os_cinco_tipos(issue):
    assert {(r.identifier, r.tipo) for r in issue.relations} == {
        ("NOM-700", "parent"),
        ("NOM-717", "sub"),
        ("NOM-718", "sub"),
        ("NOM-720", "blocks"),
        ("NOM-721", "related"),
        ("NOM-690", "blocked_by"),
    }


def test_blocked_by_vem_de_inverse_relations(issue):
    # O enum `IssueRelationType` do Linear nao tem `blocked_by`: quem me
    # bloqueia aparece em `inverseRelations` com type `blocks`.
    (bloqueadora,) = [r for r in issue.relations if r.tipo == "blocked_by"]
    assert (bloqueadora.identifier, bloqueadora.state) == ("NOM-690", "Review")


def test_relacoes_nao_trazem_o_corpo(issue):
    # O corpo da vizinha nao entra no contexto por padrao — quem precisar
    # chama `fetch_linear_issue`. O unico `description` do documento e o da
    # propria issue: qualquer outro seria corpo de vizinha vazando.
    from sentinela_graph.linear import queries

    assert queries.ISSUE.count("description") == 1
    assert all(not hasattr(r, "body") for r in issue.relations)


def test_relacao_de_tipo_desconhecido_e_ignorada(espiao):
    # `duplicate` e `similar` existem no enum e nao tem lugar em
    # `TipoRelacao`. Ignorar e melhor que estourar no meio de um run.
    payload = json.loads(json.dumps(PAYLOAD))
    payload["issue"]["relations"]["nodes"].append(
        {"type": "duplicate", "relatedIssue": vizinha("NOM-999")}
    )
    e = espiao(dados(payload))
    with e.cliente() as c:
        recarregada = load_issue(c, "uuid-716")
    assert "NOM-999" not in {r.identifier for r in recarregada.relations}


def test_issue_sem_vizinhas_nao_quebra(espiao):
    e = espiao(
        dados(
            {
                "issue": {
                    **PAYLOAD["issue"],
                    "parent": None,
                    "children": {"nodes": []},
                    "relations": {"nodes": []},
                    "inverseRelations": {"nodes": []},
                    "attachments": {"nodes": []},
                    "comments": {"nodes": []},
                    "description": None,
                }
            }
        )
    )
    with e.cliente() as c:
        magra = load_issue(c, "uuid-716")
    assert (magra.relations, magra.links, magra.comments, magra.spec) == ([], [], [], "")


def test_resultado_sobrevive_ao_checkpoint(issue):
    # O run precisa ser reproduzivel: o que `--resume` le tem que ser
    # identico ao que o agente viu.
    volta = IssueRef.model_validate(json.loads(issue.model_dump_json()))
    assert volta == issue


def test_issue_inexistente_falha_deterministicamente(espiao):
    e = espiao(erro_graphql("Entity not found: Issue"))
    with e.cliente() as c, pytest.raises(LinearDeterministicoError, match="Entity not found"):
        load_issue(c, "uuid-inexistente")
    assert len(e.chamadas) == 1


def test_envia_o_identificador_por_variavel(espiao):
    e = espiao(dados(PAYLOAD))
    with e.cliente() as c:
        load_issue(c, "NOM-716")
    assert e.ultima.variaveis == {"id": "NOM-716"}
```

Acrescente ao fim de `tests/models/test_issue.py`:

```python
def test_issue_link_exige_titulo_e_url():
    from sentinela_graph.models.issue import IssueLink

    link = IssueLink(title="MR !7", url="https://gitlab.exemplo/-/merge_requests/7")
    assert (link.title, link.url) == ("MR !7", "https://gitlab.exemplo/-/merge_requests/7")


def test_issue_ref_sem_links_continua_valida():
    # Retrocompatibilidade: checkpoints da E1 nao tem o campo.
    from sentinela_graph.models.issue import IssueRef

    ref = IssueRef(
        id="1",
        identifier="NOM-1",
        title="t",
        url="u",
        git_branch_name="b",
        spec="s",
        state="To Do",
    )
    assert ref.links == []
```

- [ ] **Passo 2: Rodar e ver falhar**

```bash
uv run pytest tests/linear/test_carga.py tests/models/test_issue.py -q
```

Esperado: `ModuleNotFoundError: No module named 'sentinela_graph.linear.carga'` e `ImportError: cannot import name 'IssueLink'`.

- [ ] **Passo 3: Acrescentar `IssueLink` e `IssueRef.links`**

Em `src/sentinela_graph/models/issue.py`, insira a classe `IssueLink` **entre** `IssueRelation` e `IssueRef`:

```python
class IssueLink(BaseModel):
    """Link ou anexo da issue.

    No Linear os dois sao a mesma entidade (`Issue.attachments`), entao
    viram um campo so. E por aqui que o MR e vinculado a issue: nao ha
    integracao automatica entre as forjas e o Linear.
    """

    title: str
    url: str
```

E acrescente o campo em `IssueRef`, **depois** de `labels` e **antes** de `priority`:

```python
    links: list[IssueLink] = Field(default_factory=list)
```

- [ ] **Passo 4: Acrescentar o documento `ISSUE`**

Acrescente ao fim de `src/sentinela_graph/linear/queries.py`:

```python
ISSUE = """
query Issue($id: String!) {
  issue(id: $id) {
    id
    identifier
    title
    url
    branchName
    description
    priority
    state { name }
    labels { nodes { name } }
    comments(first: 100, orderBy: createdAt) {
      nodes {
        id
        body
        createdAt
        user { name }
        botActor { name }
      }
    }
    attachments(first: 50) { nodes { title url } }
    parent { identifier title url state { name } }
    children(first: 50) { nodes { identifier title url state { name } } }
    relations(first: 50) {
      nodes { type relatedIssue { identifier title url state { name } } }
    }
    inverseRelations(first: 50) {
      nodes { type issue { identifier title url state { name } } }
    }
  }
}
"""
```

- [ ] **Passo 5: Escrever `load_issue`**

Crie `src/sentinela_graph/linear/carga.py`:

```python
"""Congela a issue no estado antes de qualquer agente rodar.

Congelar torna o run reproduzivel: `--resume` e a investigacao no Langfuse
mostram o que o agente viu, nao o que a issue virou depois.
"""

from typing import Any

from sentinela_graph.linear import queries
from sentinela_graph.linear.client import LinearClient
from sentinela_graph.models.issue import Comment, IssueLink, IssueRef, IssueRelation

AUTOR_DESCONHECIDO = "desconhecido"

# `IssueRelationType` do Linear e `blocks | duplicate | related | similar`.
# `duplicate` e `similar` nao tem lugar em `TipoRelacao` e sao ignorados:
# derrubar um run por causa de uma relacao decorativa seria pior.
TIPO_DIRETO = {"blocks": "blocks", "related": "related"}
TIPO_INVERSO = {"blocks": "blocked_by", "related": "related"}


def _autor(no: dict[str, Any]) -> str:
    """`Comment.user` e anulavel: comentario de integracao vem com `botActor`."""
    for ator in (no.get("user"), no.get("botActor")):
        if ator and ator.get("name"):
            return str(ator["name"])
    return AUTOR_DESCONHECIDO


def _vizinha(no: dict[str, Any], tipo: str) -> IssueRelation:
    return IssueRelation(
        identifier=no["identifier"],
        title=no["title"],
        state=no["state"]["name"],
        url=no["url"],
        tipo=tipo,
    )


def _relacoes(issue: dict[str, Any]) -> list[IssueRelation]:
    relacoes: list[IssueRelation] = []

    if issue.get("parent"):
        relacoes.append(_vizinha(issue["parent"], "parent"))

    for filha in (issue.get("children") or {}).get("nodes", []):
        relacoes.append(_vizinha(filha, "sub"))

    for no in (issue.get("relations") or {}).get("nodes", []):
        tipo = TIPO_DIRETO.get(no["type"])
        if tipo:
            relacoes.append(_vizinha(no["relatedIssue"], tipo))

    # Quem me bloqueia nao aparece em `relations`: o enum do Linear so tem
    # `blocks`, e a direcao inversa vive em `inverseRelations`.
    for no in (issue.get("inverseRelations") or {}).get("nodes", []):
        tipo = TIPO_INVERSO.get(no["type"])
        if tipo:
            relacoes.append(_vizinha(no["issue"], tipo))

    return relacoes


def load_issue(client: LinearClient, id_da_issue: str) -> IssueRef:
    """Busca a issue inteira e devolve o contexto congelado.

    `id_da_issue` e o UUID que `fetch_queue` devolve. O Linear tambem
    resolve o identificador humano (`NOM-716`), o que o diagnostico usa.
    """
    issue = client.executar(queries.ISSUE, {"id": id_da_issue})["issue"]

    comentarios = [
        Comment(
            id=no["id"],
            author=_autor(no),
            body=no["body"],
            created_at=no["createdAt"],
        )
        for no in (issue.get("comments") or {}).get("nodes", [])
    ]

    return IssueRef(
        id=issue["id"],
        identifier=issue["identifier"],
        title=issue["title"],
        url=issue["url"],
        git_branch_name=issue["branchName"],
        # A descricao da issue e a spec escrita pelo humano. Issue sem
        # descricao vira spec vazia, e quem reclama e o agente de plano.
        spec=issue.get("description") or "",
        state=issue["state"]["name"],
        labels=[no["name"] for no in (issue.get("labels") or {}).get("nodes", [])],
        links=[
            IssueLink(title=no["title"], url=no["url"])
            for no in (issue.get("attachments") or {}).get("nodes", [])
        ],
        priority=int(issue["priority"]),
        # O contrato mora nos comentarios e e cronologico. O `orderBy` da
        # query ja pede ordem, mas ordenar aqui torna a garantia local.
        comments=sorted(comentarios, key=lambda c: c.created_at),
        relations=_relacoes(issue),
    )
```

- [ ] **Passo 6: Rodar e ver passar**

```bash
uv run pytest tests/linear/test_carga.py tests/models/test_issue.py -q
```

Esperado: todos passam.

- [ ] **Passo 7: Gate completo e commit**

```bash
uv run ruff check && uv run ruff format --check && uv run pytest
git add src/sentinela_graph/models/issue.py src/sentinela_graph/linear/queries.py src/sentinela_graph/linear/carga.py
git add tests/linear/test_carga.py tests/models/test_issue.py
git commit -m "feat(linear): load_issue congela issue, comentarios, links e relacoes

Acrescenta IssueRef.links, a divida registrada da E1.

Closes #18"
```

---

### Task 4: Escritas no Linear — status, comentário e link de MR

Fecha [#19](https://github.com/victordantas1/graph-agent/issues/19).

**Files:**
- Create: `src/sentinela_graph/linear/escrita.py`
- Create: `tests/linear/test_escrita.py`
- Modify: `src/sentinela_graph/linear/queries.py` (acrescentar `ESTADOS`, `MOVER`, `COMENTAR`, `VINCULAR`)

**Interfaces:**
- Consumes: `LinearClient.executar`; `constantes.EQUIPE`, `constantes.TIPOS_TERMINAIS`.
- Produces:
  - `escrita.EstadoDoTime(id: str, name: str, type: str)`; `EstadoDoTime.terminal -> bool`
  - `escrita.estados_do_time(client) -> list[EstadoDoTime]`
  - `escrita.mover_status(client, issue_id: str, nome_status: str) -> None`
  - `escrita.comentar(client, issue_id: str, corpo: str) -> str` (devolve a URL do comentário)
  - `escrita.vincular_mr(client, issue_id: str, url: str, titulo: str) -> None`

- [ ] **Passo 1: Escrever os testes que falham**

Crie `tests/linear/test_escrita.py`. A listagem está entre cercas de **quatro** crases porque a constante `CORPO` contém um bloco de código markdown — as cercas de três crases fazem parte do arquivo:

````python
"""As escritas sao o unico caminho do grafo para o mundo. Nenhum agente LLM
chega aqui: a E4 so expoe leitura."""

import pytest

from sentinela_graph.linear.errors import LinearDeterministicoError
from sentinela_graph.linear.escrita import comentar, estados_do_time, mover_status, vincular_mr

from .conftest import dados

ESTADOS_REAIS = [
    {"id": "s-backlog", "name": "Backlog", "type": "backlog"},
    {"id": "s-todo", "name": "To Do", "type": "unstarted"},
    {"id": "s-doing", "name": "Doing", "type": "started"},
    {"id": "s-review", "name": "Review", "type": "started"},
    {"id": "s-done", "name": "Done", "type": "completed"},
    {"id": "s-canceled", "name": "Canceled", "type": "canceled"},
    {"id": "s-dup", "name": "Duplicate", "type": "duplicate"},
]


def resposta_estados() -> dict:
    return {"teams": {"nodes": [{"id": "t-nom", "key": "NOM", "states": {"nodes": ESTADOS_REAIS}}]}}


def ok_mover() -> dict:
    return {"issueUpdate": {"success": True, "issue": {"identifier": "NOM-716", "state": {"name": "Doing"}}}}


# --- status ---


def test_estados_do_time_marca_os_terminais(espiao):
    e = espiao(dados(resposta_estados()))
    with e.cliente() as c:
        estados = estados_do_time(c)
    assert {x.name for x in estados if x.terminal} == {"Done", "Canceled", "Duplicate"}


def test_mover_resolve_o_id_do_estado_pelo_nome(espiao):
    e = espiao(dados(resposta_estados()), dados(ok_mover()))
    with e.cliente() as c:
        mover_status(c, "uuid-716", "Doing")
    assert e.ultima.variaveis == {"id": "uuid-716", "stateId": "s-doing"}


def test_done_nunca_e_destino(espiao):
    # Criterio de aceite da #19. Quem fecha a issue e o merge.
    e = espiao(dados(resposta_estados()))
    with e.cliente() as c, pytest.raises(LinearDeterministicoError, match="Done"):
        mover_status(c, "uuid-716", "Done")
    # Uma chamada apenas: a leitura dos estados. A mutation nunca sai.
    assert len(e.chamadas) == 1


@pytest.mark.parametrize("terminal", ["Done", "Canceled", "Duplicate"])
def test_todo_status_terminal_e_barrado(espiao, terminal):
    e = espiao(dados(resposta_estados()))
    with e.cliente() as c, pytest.raises(LinearDeterministicoError):
        mover_status(c, "uuid-716", terminal)
    assert len(e.chamadas) == 1


def test_status_renomeado_continua_barrado_pelo_tipo(espiao):
    # O bloqueio e por `WorkflowState.type`, nao pelo nome: renomear
    # "Done" para "Concluido" na UI nao abre a porta.
    estados = [dict(x) for x in ESTADOS_REAIS]
    estados[4]["name"] = "Concluido"
    e = espiao(dados({"teams": {"nodes": [{"id": "t", "key": "NOM", "states": {"nodes": estados}}]}}))
    with e.cliente() as c, pytest.raises(LinearDeterministicoError):
        mover_status(c, "uuid-716", "Concluido")


def test_status_inexistente_lista_os_status_reais(espiao):
    e = espiao(dados(resposta_estados()))
    with e.cliente() as c, pytest.raises(LinearDeterministicoError) as info:
        mover_status(c, "uuid-716", "In Progress")
    mensagem = str(info.value)
    assert "In Progress" in mensagem
    for esperado in ("Backlog", "To Do", "Doing", "Review"):
        assert esperado in mensagem


def test_status_terminal_nao_aparece_na_lista_sugerida(espiao):
    # Sugerir `Done` seria ensinar o proximo mantenedor a violar a regra.
    e = espiao(dados(resposta_estados()))
    with e.cliente() as c, pytest.raises(LinearDeterministicoError) as info:
        mover_status(c, "uuid-716", "In Progress")
    for proibido in ("Done", "Canceled", "Duplicate"):
        assert proibido not in str(info.value)


def test_mutation_sem_success_falha(espiao):
    e = espiao(dados(resposta_estados()), dados({"issueUpdate": {"success": False, "issue": None}}))
    with e.cliente() as c, pytest.raises(LinearDeterministicoError, match="nao confirmou"):
        mover_status(c, "uuid-716", "Doing")


def test_time_inexistente_falha_com_a_chave_procurada(espiao):
    e = espiao(dados({"teams": {"nodes": []}}))
    with e.cliente() as c, pytest.raises(LinearDeterministicoError, match="NOM"):
        estados_do_time(c)


# --- comentario ---


CORPO = """## Plano

- **Bug:** o clipping repete a materia
- Arquivos: `app/src/clipping/`

```bash
npx jest app/src/clipping/dedupe.spec.ts
```
"""


def test_comentario_preserva_quebras_de_linha_e_markdown(espiao):
    e = espiao(dados({"commentCreate": {"success": True, "comment": {"id": "c9", "url": "u"}}}))
    with e.cliente() as c:
        comentar(c, "uuid-716", CORPO)
    assert e.ultima.variaveis["body"] == CORPO
    assert "\n\n" in e.ultima.variaveis["body"]


def test_corpo_nunca_e_interpolado_no_documento(espiao):
    # Interpolar markdown no documento GraphQL quebraria com aspas ou
    # chaves — e e assim que se injeta uma operacao inteira.
    e = espiao(dados({"commentCreate": {"success": True, "comment": {"id": "c9", "url": "u"}}}))
    with e.cliente() as c:
        comentar(c, "uuid-716", CORPO)
    assert CORPO not in e.ultima.documento
    assert "$body" in e.ultima.documento


def test_comentario_devolve_a_url(espiao):
    e = espiao(
        dados({"commentCreate": {"success": True, "comment": {"id": "c9", "url": "https://l/c9"}}})
    )
    with e.cliente() as c:
        assert comentar(c, "uuid-716", "oi") == "https://l/c9"


def test_comentario_vazio_e_recusado_antes_da_chamada(espiao):
    # Comentario vazio na issue e ruido puro e apaga o rastro do que o
    # grafo decidiu.
    e = espiao()
    with e.cliente() as c, pytest.raises(LinearDeterministicoError, match="vazio"):
        comentar(c, "uuid-716", "   \n  ")
    assert e.chamadas == []


# --- vinculo do MR ---


def test_vincular_mr_usa_attachment_create(espiao):
    e = espiao(
        dados(
            {
                "attachmentCreate": {
                    "success": True,
                    "attachment": {"id": "a1", "url": "https://gl/-/merge_requests/7", "title": "MR !7"},
                }
            }
        )
    )
    with e.cliente() as c:
        vincular_mr(c, "uuid-716", "https://gl/-/merge_requests/7", "MR !7")
    assert e.ultima.variaveis == {
        "issueId": "uuid-716",
        "url": "https://gl/-/merge_requests/7",
        "title": "MR !7",
    }


def test_vincular_o_mesmo_mr_duas_vezes_nao_quebra(espiao):
    # `attachmentCreate` atualiza quando `url` + `issueId` se repetem, o
    # que faz `--resume` depois do `report` ser seguro.
    resposta = dados(
        {"attachmentCreate": {"success": True, "attachment": {"id": "a1", "url": "u", "title": "MR !7"}}}
    )
    e = espiao(resposta, resposta)
    with e.cliente() as c:
        vincular_mr(c, "uuid-716", "u", "MR !7")
        vincular_mr(c, "uuid-716", "u", "MR !7")
    assert len(e.chamadas) == 2
````

- [ ] **Passo 2: Rodar e ver falhar**

```bash
uv run pytest tests/linear/test_escrita.py -q
```

Esperado: `ModuleNotFoundError: No module named 'sentinela_graph.linear.escrita'`.

- [ ] **Passo 3: Acrescentar os documentos**

Acrescente ao fim de `src/sentinela_graph/linear/queries.py`:

```python
ESTADOS = """
query Estados($equipe: String!) {
  teams(first: 1, filter: { key: { eq: $equipe } }) {
    nodes {
      id
      key
      states(first: 50) { nodes { id name type } }
    }
  }
}
"""

MOVER = """
mutation Mover($id: String!, $stateId: String!) {
  issueUpdate(id: $id, input: { stateId: $stateId }) {
    success
    issue { identifier state { name } }
  }
}
"""

COMENTAR = """
mutation Comentar($issueId: String!, $body: String!) {
  commentCreate(input: { issueId: $issueId, body: $body }) {
    success
    comment { id url }
  }
}
"""

VINCULAR = """
mutation Vincular($issueId: String!, $url: String!, $title: String!) {
  attachmentCreate(input: { issueId: $issueId, url: $url, title: $title }) {
    success
    attachment { id url title }
  }
}
"""
```

- [ ] **Passo 4: Escrever as escritas**

Crie `src/sentinela_graph/linear/escrita.py`:

```python
"""Escritas deterministicas no Linear: status, comentario e vinculo do MR.

Nenhum agente LLM recebe ferramenta deste modulo. O LLM decide *conteudo*;
o grafo executa a escrita.
"""

from pydantic import BaseModel

from sentinela_graph.linear import queries
from sentinela_graph.linear.client import LinearClient
from sentinela_graph.linear.constantes import EQUIPE, TIPOS_TERMINAIS
from sentinela_graph.linear.errors import LinearDeterministicoError


class EstadoDoTime(BaseModel):
    """Um status do workflow do time."""

    id: str
    name: str
    type: str

    @property
    def terminal(self) -> bool:
        """Status de onde o agente nunca pode ser a causa da chegada.

        Por `type`, nao por nome: cobre `Done` por construcao e sobrevive a
        um rename na UI do Linear.
        """
        return self.type in TIPOS_TERMINAIS


def _time(client: LinearClient) -> dict:
    nos = client.executar(queries.ESTADOS, {"equipe": EQUIPE})["teams"]["nodes"]
    if not nos:
        raise LinearDeterministicoError(
            f"nenhum time com key {EQUIPE!r} visivel para esta LINEAR_API_KEY"
        )
    return nos[0]


def estados_do_time(client: LinearClient) -> list[EstadoDoTime]:
    return [EstadoDoTime(**no) for no in _time(client)["states"]["nodes"]]


def mover_status(client: LinearClient, issue_id: str, nome_status: str) -> None:
    """Move a issue para o status de nome exato. Nunca para um status terminal."""
    estados = estados_do_time(client)
    por_nome = {e.name: e for e in estados}
    alvo = por_nome.get(nome_status)

    if alvo is not None and alvo.terminal:
        raise LinearDeterministicoError(
            f"o agente nunca move uma issue para {nome_status!r}: quem fecha e o merge"
        )
    if alvo is None:
        # Listar os terminais aqui ensinaria o proximo mantenedor a violar
        # a regra, entao a sugestao so tem destinos legitimos.
        validos = ", ".join(e.name for e in estados if not e.terminal)
        raise LinearDeterministicoError(
            f"status {nome_status!r} nao existe no time {EQUIPE}. Destinos validos: {validos}"
        )

    dados = client.executar(queries.MOVER, {"id": issue_id, "stateId": alvo.id})
    _confirmar(dados, "issueUpdate", f"mover {issue_id} para {nome_status!r}")


def comentar(client: LinearClient, issue_id: str, corpo: str) -> str:
    """Cria um comentario markdown e devolve a URL dele."""
    if not corpo.strip():
        raise LinearDeterministicoError("comentario vazio: nada a publicar na issue")

    # O corpo viaja como variavel, nunca interpolado no documento: markdown
    # com aspas, chaves ou crase quebraria a operacao.
    dados = client.executar(queries.COMENTAR, {"issueId": issue_id, "body": corpo})
    _confirmar(dados, "commentCreate", f"comentar em {issue_id}")
    return str(dados["commentCreate"]["comment"]["url"])


def vincular_mr(client: LinearClient, issue_id: str, url: str, titulo: str) -> None:
    """Anexa o MR a issue.

    Nao ha integracao automatica entre as forjas e o Linear: os dois lados
    sao vinculados explicitamente. `attachmentCreate` atualiza quando
    `url` + `issueId` se repetem, entao repetir e seguro no `--resume`.
    """
    dados = client.executar(
        queries.VINCULAR, {"issueId": issue_id, "url": url, "title": titulo}
    )
    _confirmar(dados, "attachmentCreate", f"vincular {url} a {issue_id}")


def _confirmar(dados: dict, campo: str, acao: str) -> None:
    """O Linear responde 200 com `success: false` em recusa de regra de negocio."""
    if not (dados.get(campo) or {}).get("success"):
        raise LinearDeterministicoError(f"o Linear nao confirmou a operacao: {acao}")
```

- [ ] **Passo 5: Rodar e ver passar**

```bash
uv run pytest tests/linear/test_escrita.py -q
```

Esperado: todos passam.

- [ ] **Passo 6: Gate completo e commit**

```bash
uv run ruff check && uv run ruff format --check && uv run pytest
git add src/sentinela_graph/linear/queries.py src/sentinela_graph/linear/escrita.py
git add tests/linear/test_escrita.py
git commit -m "feat(linear): escritas de status, comentario e link de MR

Closes #19"
```

---

### Task 5: Labels de outcome — criação idempotente, aplicação e remoção

Fecha [#20](https://github.com/victordantas1/graph-agent/issues/20).

**Files:**
- Create: `src/sentinela_graph/linear/labels.py`
- Create: `tests/linear/test_labels.py`
- Modify: `src/sentinela_graph/linear/queries.py` (acrescentar `LABELS`, `CRIAR_LABEL`, `AJUSTAR_LABELS`)

**Interfaces:**
- Consumes: `LinearClient.executar`; `constantes.EQUIPE`. `labels.py` resolve o time por conta própria pelo documento `LABELS` — não reaproveita `escrita._time`, que pede os *estados* e traria um payload maior sem necessidade.
- Produces:
  - `labels.LABEL_POR_OUTCOME: dict[str, str | None]`
  - `labels.COR_LABEL = "#EB5757"`
  - `labels.garantir_labels_de_outcome(client) -> dict[str, str]` (nome → id, idempotente)
  - `labels.aplicar_label_de_outcome(client, issue_id: str, outcome: str) -> None`

- [ ] **Passo 1: Escrever os testes que falham**

Crie `tests/linear/test_labels.py`:

```python
"""As labels sao como um humano descobre por que o run parou. Errar aqui
faz a issue voltar para a fila com o motivo apagado — ou sumir dela."""

import pytest

from sentinela_graph.linear.labels import (
    LABEL_POR_OUTCOME,
    aplicar_label_de_outcome,
    garantir_labels_de_outcome,
)
from sentinela_graph.state import Outcome

from .conftest import dados

TODAS = ["agent:blocked", "agent:needs-spec", "agent:failed", "agent:error"]


def resposta_time(*nomes: str) -> dict:
    labels = [{"id": f"id-{n}", "name": n} for n in nomes]
    return {"teams": {"nodes": [{"id": "t-nom", "labels": {"nodes": labels}}]}}


def resposta_criacao(nome: str) -> dict:
    return {"issueLabelCreate": {"success": True, "issueLabel": {"id": f"id-{nome}", "name": nome}}}


def resposta_ajuste() -> dict:
    return {"issueUpdate": {"success": True, "issue": {"identifier": "NOM-716", "labels": {"nodes": []}}}}


# --- matriz outcome -> label ---


def test_a_matriz_cobre_todos_os_outcomes():
    # Um outcome novo sem entrada aqui viraria um run que termina sem
    # deixar rastro nenhum na issue.
    assert set(LABEL_POR_OUTCOME) == set(Outcome.__args__)


@pytest.mark.parametrize(
    ("outcome", "esperado"),
    [
        ("mr_aberto", None),
        ("fila_vazia", None),
        ("ambiguo", "agent:blocked"),
        ("subespecificado", "agent:needs-spec"),
        ("reprovado_3x", "agent:failed"),
        ("erro", "agent:error"),
    ],
)
def test_matriz_outcome_para_label(outcome, esperado):
    assert LABEL_POR_OUTCOME[outcome] == esperado


# --- criacao idempotente ---


def test_cria_apenas_as_labels_ausentes(espiao):
    e = espiao(
        dados(resposta_time("Ready", "agent:blocked")),
        dados(resposta_criacao("agent:needs-spec")),
        dados(resposta_criacao("agent:failed")),
        dados(resposta_criacao("agent:error")),
    )
    with e.cliente() as c:
        por_nome = garantir_labels_de_outcome(c)
    criadas = [ch.variaveis["nome"] for ch in e.chamadas if "nome" in ch.variaveis]
    assert criadas == ["agent:needs-spec", "agent:failed", "agent:error"]
    assert set(por_nome) == set(TODAS)
    assert por_nome["agent:blocked"] == "id-agent:blocked"


def test_segunda_execucao_nao_cria_nada(espiao):
    e = espiao(dados(resposta_time("Ready", *TODAS)))
    with e.cliente() as c:
        por_nome = garantir_labels_de_outcome(c)
    assert len(e.chamadas) == 1
    assert set(por_nome) == set(TODAS)


def test_labels_sao_criadas_no_time(espiao):
    e = espiao(dados(resposta_time()), *[dados(resposta_criacao(n)) for n in TODAS])
    with e.cliente() as c:
        garantir_labels_de_outcome(c)
    criacoes = [ch for ch in e.chamadas if "nome" in ch.variaveis]
    assert all(ch.variaveis["teamId"] == "t-nom" for ch in criacoes)


# --- aplicacao ---


def test_aplica_a_label_do_outcome(espiao):
    e = espiao(dados(resposta_time("Ready", *TODAS)), dados(resposta_ajuste()))
    with e.cliente() as c:
        aplicar_label_de_outcome(c, "uuid-716", "ambiguo")
    assert e.ultima.variaveis["add"] == ["id-agent:blocked"]


def test_nunca_usa_label_ids_que_substituiria_ready(espiao):
    # `IssueUpdateInput.labelIds` troca o conjunto inteiro: usa-lo aqui
    # arrancaria a label `Ready` e a issue sumiria da propria fila.
    e = espiao(dados(resposta_time("Ready", *TODAS)), dados(resposta_ajuste()))
    with e.cliente() as c:
        aplicar_label_de_outcome(c, "uuid-716", "erro")
    assert "labelIds" not in e.ultima.documento
    assert set(e.ultima.variaveis) == {"id", "add", "rem"}


def test_troca_de_outcome_remove_a_label_anterior(espiao):
    e = espiao(dados(resposta_time("Ready", *TODAS)), dados(resposta_ajuste()))
    with e.cliente() as c:
        aplicar_label_de_outcome(c, "uuid-716", "erro")
    assert e.ultima.variaveis["add"] == ["id-agent:error"]
    assert sorted(e.ultima.variaveis["rem"]) == sorted(
        f"id-{n}" for n in TODAS if n != "agent:error"
    )


def test_sucesso_remove_todas_as_labels_agent(espiao):
    # "As 4 labels sao removidas quando um run posterior tem sucesso."
    e = espiao(dados(resposta_time("Ready", *TODAS)), dados(resposta_ajuste()))
    with e.cliente() as c:
        aplicar_label_de_outcome(c, "uuid-716", "mr_aberto")
    assert e.ultima.variaveis["add"] == []
    assert sorted(e.ultima.variaveis["rem"]) == sorted(f"id-{n}" for n in TODAS)


def test_rodar_duas_vezes_seguidas_e_idempotente(espiao):
    # Criterio de aceite: rodar duas vezes nao duplica label nem falha.
    e = espiao(
        dados(resposta_time("Ready", *TODAS)),
        dados(resposta_ajuste()),
        dados(resposta_time("Ready", *TODAS)),
        dados(resposta_ajuste()),
    )
    with e.cliente() as c:
        aplicar_label_de_outcome(c, "uuid-716", "ambiguo")
        primeira = e.ultima.variaveis
        aplicar_label_de_outcome(c, "uuid-716", "ambiguo")
    assert e.ultima.variaveis == primeira


def test_fila_vazia_nao_toca_em_issue_nenhuma(espiao):
    # `fila_vazia` acontece quando nao ha issue: chamar isto com um id
    # seria um bug de chamador, e falhar alto e melhor que escrever errado.
    e = espiao()
    with e.cliente() as c, pytest.raises(ValueError, match="fila_vazia"):
        aplicar_label_de_outcome(c, "uuid-716", "fila_vazia")
    assert e.chamadas == []


def test_outcome_desconhecido_falha(espiao):
    e = espiao()
    with e.cliente() as c, pytest.raises(ValueError, match="inventado"):
        aplicar_label_de_outcome(c, "uuid-716", "inventado")
    assert e.chamadas == []
```

- [ ] **Passo 2: Rodar e ver falhar**

```bash
uv run pytest tests/linear/test_labels.py -q
```

Esperado: `ModuleNotFoundError: No module named 'sentinela_graph.linear.labels'`.

- [ ] **Passo 3: Acrescentar os documentos**

Acrescente ao fim de `src/sentinela_graph/linear/queries.py`:

```python
LABELS = """
query Labels($equipe: String!) {
  teams(first: 1, filter: { key: { eq: $equipe } }) {
    nodes {
      id
      labels(first: 250) { nodes { id name } }
    }
  }
}
"""

CRIAR_LABEL = """
mutation CriarLabel($nome: String!, $teamId: String!, $cor: String!) {
  issueLabelCreate(input: { name: $nome, teamId: $teamId, color: $cor }) {
    success
    issueLabel { id name }
  }
}
"""

# `addedLabelIds`/`removedLabelIds`, nunca `labelIds`: este ultimo
# substitui o conjunto inteiro e arrancaria a label `Ready` da issue.
AJUSTAR_LABELS = """
mutation AjustarLabels($id: String!, $add: [String!]!, $rem: [String!]!) {
  issueUpdate(id: $id, input: { addedLabelIds: $add, removedLabelIds: $rem }) {
    success
    issue { identifier labels { nodes { name } } }
  }
}
"""
```

- [ ] **Passo 4: Escrever as labels**

Crie `src/sentinela_graph/linear/labels.py`:

```python
"""Labels de outcome: como um humano descobre por que o run parou.

Todo fracasso deixa a issue onde um humano a encontra, com label
explicando por que. Sucesso limpa o rastro do run anterior.
"""

from sentinela_graph.linear import queries
from sentinela_graph.linear.client import LinearClient
from sentinela_graph.linear.constantes import EQUIPE
from sentinela_graph.linear.errors import LinearDeterministicoError

COR_LABEL = "#EB5757"

LABEL_POR_OUTCOME: dict[str, str | None] = {
    "mr_aberto": None,
    "fila_vazia": None,
    "ambiguo": "agent:blocked",
    "subespecificado": "agent:needs-spec",
    "reprovado_3x": "agent:failed",
    "erro": "agent:error",
}

LABELS_DE_AGENTE = tuple(nome for nome in LABEL_POR_OUTCOME.values() if nome)


def garantir_labels_de_outcome(client: LinearClient) -> dict[str, str]:
    """Devolve nome -> id das quatro labels, criando as que faltarem.

    Idempotente: le o que ja existe antes de criar. Rodar duas vezes nao
    duplica nem falha.
    """
    time = _time(client)
    por_nome = {
        no["name"]: no["id"]
        for no in time["labels"]["nodes"]
        if no["name"] in LABELS_DE_AGENTE
    }

    for nome in LABELS_DE_AGENTE:
        if nome in por_nome:
            continue
        dados = client.executar(
            queries.CRIAR_LABEL,
            {"nome": nome, "teamId": time["id"], "cor": COR_LABEL},
        )
        if not (dados.get("issueLabelCreate") or {}).get("success"):
            raise LinearDeterministicoError(f"o Linear nao confirmou a criacao da label {nome!r}")
        por_nome[nome] = dados["issueLabelCreate"]["issueLabel"]["id"]

    return por_nome


def aplicar_label_de_outcome(client: LinearClient, issue_id: str, outcome: str) -> None:
    """Deixa exatamente a label do outcome na issue, e nenhuma outra `agent:*`.

    Uma escrita so: aplicar a nova e remover as anteriores no mesmo
    `issueUpdate` evita um estado intermediario visivel com duas labels.
    """
    if outcome not in LABEL_POR_OUTCOME:
        raise ValueError(f"outcome {outcome!r} nao esta na matriz — outcome inventado?")
    if outcome == "fila_vazia":
        raise ValueError("fila_vazia acontece sem issue: nao ha o que rotular")

    por_nome = garantir_labels_de_outcome(client)
    alvo = LABEL_POR_OUTCOME[outcome]

    adicionar = [por_nome[alvo]] if alvo else []
    remover = [id_ for nome, id_ in por_nome.items() if nome != alvo]

    dados = client.executar(
        queries.AJUSTAR_LABELS,
        {"id": issue_id, "add": adicionar, "rem": sorted(remover)},
    )
    if not (dados.get("issueUpdate") or {}).get("success"):
        raise LinearDeterministicoError(
            f"o Linear nao confirmou o ajuste de labels de {issue_id}"
        )


def _time(client: LinearClient) -> dict:
    nos = client.executar(queries.LABELS, {"equipe": EQUIPE})["teams"]["nodes"]
    if not nos:
        raise LinearDeterministicoError(
            f"nenhum time com key {EQUIPE!r} visivel para esta LINEAR_API_KEY"
        )
    return nos[0]
```

`labels.py` **não** importa `Outcome` de `state.py`: a chave do dicionário é `str` e quem confronta a matriz com o `Literal` é o teste. Importar o tipo aqui criaria uma dependência da camada de acesso no estado do grafo — e é justamente o estado do grafo que o épico #2 declara fora de escopo.

- [ ] **Passo 5: Rodar e ver passar**

```bash
uv run pytest tests/linear/test_labels.py -q
```

Esperado: todos passam.

- [ ] **Passo 6: Gate completo e commit**

```bash
uv run ruff check && uv run ruff format --check && uv run pytest
git add src/sentinela_graph/linear/queries.py src/sentinela_graph/linear/labels.py
git add tests/linear/test_labels.py
git commit -m "feat(linear): labels de outcome idempotentes

Closes #20"
```

---

### Task 6: Diagnóstico contra o workspace real

Entrega verificável do épico [#2](https://github.com/victordantas1/graph-agent/issues/2). Ver decisão 9: é temporário, e a [#55](https://github.com/victordantas1/graph-agent/issues/55) da E10 o substitui.

**Files:**
- Create: `src/sentinela_graph/linear/__main__.py`
- Create: `tests/linear/test_diagnostico.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: tudo das tasks 1–5.
- Produces: `__main__.formatar_fila(itens: list[ItemDaFila]) -> str`; três comandos typer — `fila`, `carregar`, `smoke-escrita`.

- [ ] **Passo 1: Escrever os testes que falham**

Crie `tests/linear/test_diagnostico.py`:

```python
"""O diagnostico e o unico codigo deste epico que escreve no Linear de
verdade. A trava do smoke e a parte que precisa de teste."""

from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from sentinela_graph.linear.__main__ import app, formatar_fila
from sentinela_graph.linear.fila import ItemDaFila


def item(identificador: str, prioridade: int) -> ItemDaFila:
    return ItemDaFila(
        id=f"uuid-{identificador}",
        identifier=identificador,
        title=f"titulo de {identificador}",
        url=f"https://linear.app/nomos-tech/issue/{identificador}",
        priority=prioridade,
        state="To Do",
        created_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
    )


def test_fila_vazia_diz_isso_em_voz_alta():
    saida = formatar_fila([])
    assert "nada em Ready" in saida


def test_fila_mostra_posicao_prioridade_e_identificador():
    saida = formatar_fila([item("NOM-1", 1), item("NOM-9", 0)])
    assert "NOM-1" in saida and "NOM-9" in saida
    assert "Urgent" in saida
    assert "sem prioridade" in saida
    # A primeira linha de issue e a que o grafo pegaria.
    assert saida.index("NOM-1") < saida.index("NOM-9")


def test_smoke_de_escrita_exige_confirmacao():
    # Sem a trava, um `--help` distraido escreveria no workspace real.
    resultado = CliRunner().invoke(app, ["smoke-escrita", "NOM-716"])
    assert resultado.exit_code != 0
    assert "--confirmar" in resultado.output
```

- [ ] **Passo 2: Rodar e ver falhar**

```bash
uv run pytest tests/linear/test_diagnostico.py -q
```

Esperado: `ModuleNotFoundError: No module named 'sentinela_graph.linear.__main__'`.

- [ ] **Passo 3: Escrever o diagnóstico**

Crie `src/sentinela_graph/linear/__main__.py`:

```python
"""Diagnostico do cliente Linear contra o workspace real.

Temporario: e a entrega verificavel da E2. O CLI de produto e a #55 da
E10, e substitui isto.

    uv run python -m sentinela_graph.linear fila
    uv run python -m sentinela_graph.linear carregar NOM-716
    uv run python -m sentinela_graph.linear smoke-escrita NOM-716 --confirmar
"""

import typer
from dotenv import load_dotenv

from sentinela_graph.linear.carga import load_issue
from sentinela_graph.linear.client import LinearClient
from sentinela_graph.linear.constantes import STATUS_CLAIM, STATUS_FILA
from sentinela_graph.linear.escrita import comentar, mover_status, vincular_mr
from sentinela_graph.linear.fila import ItemDaFila, fetch_queue
from sentinela_graph.linear.labels import aplicar_label_de_outcome

app = typer.Typer(add_completion=False, help="Diagnostico do cliente Linear.")

NOME_DA_PRIORIDADE = {0: "sem prioridade", 1: "Urgent", 2: "High", 3: "Medium", 4: "Low"}


def formatar_fila(itens: list[ItemDaFila]) -> str:
    if not itens:
        return "nada em Ready atribuido a voce. Fila vazia e resposta final."
    linhas = [f"{len(itens)} issue(s) na fila, na ordem em que o grafo pegaria:", ""]
    for posicao, item in enumerate(itens, start=1):
        prioridade = NOME_DA_PRIORIDADE.get(item.priority, str(item.priority))
        linhas.append(f"{posicao}. {item.identifier}  [{prioridade}]  {item.title}")
        linhas.append(f"   {item.url}")
    return "\n".join(linhas)


def _cliente() -> LinearClient:
    load_dotenv()
    return LinearClient()


@app.command()
def fila() -> None:
    """Imprime a fila real aplicando o filtro estrito."""
    with _cliente() as c:
        typer.echo(formatar_fila(fetch_queue(c)))


@app.command()
def carregar(identificador: str) -> None:
    """Congela uma issue e imprime o que o agente veria."""
    with _cliente() as c:
        issue = load_issue(c, identificador)
    typer.echo(f"{issue.identifier}  {issue.title}")
    typer.echo(f"branch: {issue.git_branch_name}")
    typer.echo(f"estado: {issue.state}   labels: {', '.join(issue.labels) or '-'}")
    typer.echo(f"spec: {len(issue.spec)} caracteres")
    typer.echo(f"comentarios: {len(issue.comments)}")
    for comentario in issue.comments:
        typer.echo(f"  - {comentario.created_at:%Y-%m-%d} {comentario.author}")
    typer.echo(f"links: {len(issue.links)}")
    for link in issue.links:
        typer.echo(f"  - {link.title}: {link.url}")
    typer.echo(f"relacoes: {len(issue.relations)}")
    for relacao in issue.relations:
        typer.echo(f"  - {relacao.tipo}: {relacao.identifier} [{relacao.state}] {relacao.title}")


@app.command("smoke-escrita")
def smoke_escrita(
    identificador: str,
    confirmar: bool = typer.Option(False, "--confirmar", help="Autoriza escrever no Linear."),
) -> None:
    """Round-trip de escrita numa issue de rascunho. ESCREVE NO LINEAR REAL.

    Move para Doing, comenta, aplica e remove label, vincula um link e
    volta para To Do. Use numa issue descartavel, nunca numa issue de
    trabalho de verdade.
    """
    if not confirmar:
        raise typer.BadParameter(
            "este comando escreve no Linear real. Repita com --confirmar "
            "e aponte para uma issue de rascunho."
        )

    with _cliente() as c:
        issue = load_issue(c, identificador)
        typer.echo(f"alvo: {issue.identifier} (estado atual: {issue.state})")

        mover_status(c, issue.id, STATUS_CLAIM)
        typer.echo(f"-> {STATUS_CLAIM}")

        url = comentar(c, issue.id, "## Smoke da E2\n\n- markdown\n- com **quebras** reais\n")
        typer.echo(f"comentario: {url}")

        vincular_mr(c, issue.id, "https://example.invalid/-/merge_requests/1", "MR !1 (smoke)")
        typer.echo("link anexado")

        aplicar_label_de_outcome(c, issue.id, "erro")
        typer.echo("label agent:error aplicada")

        aplicar_label_de_outcome(c, issue.id, "mr_aberto")
        typer.echo("labels agent:* removidas")

        mover_status(c, issue.id, STATUS_FILA)
        typer.echo(f"-> {STATUS_FILA} (estado restaurado)")


if __name__ == "__main__":
    app()
```

- [ ] **Passo 4: Rodar e ver passar**

```bash
uv run pytest tests/linear/test_diagnostico.py -q
```

Esperado: todos passam.

- [ ] **Passo 5: Documentar no README**

Acrescente ao fim de `README.md` exatamente o conteúdo entre as cercas de quatro crases (as cercas de três crases fazem parte do texto do README):

````markdown
## Diagnostico do cliente Linear

Exige `LINEAR_API_KEY` no `.env`. Os dois primeiros comandos so leem:

```bash
uv run python -m sentinela_graph.linear fila
uv run python -m sentinela_graph.linear carregar NOM-716
```

O terceiro **escreve no workspace real** e existe para provar o
round-trip de escrita. Aponte para uma issue de rascunho:

```bash
uv run python -m sentinela_graph.linear smoke-escrita NOM-716 --confirmar
```

Temporario: o CLI de produto e a E10.
````

- [ ] **Passo 6: Verificação manual contra o workspace real**

Esta é a aceitação do épico. Com `LINEAR_API_KEY` preenchida no `.env`:

```bash
uv run python -m sentinela_graph.linear fila
```

Confira que a saída bate com o que o Linear mostra filtrando `To Do` + `Ready` + assignee você. Depois:

```bash
uv run python -m sentinela_graph.linear carregar <um identificador da fila>
```

Confira que `branch:` traz o `gitBranchName` real e que os comentários aparecem em ordem com os autores certos.

**Se não houver `LINEAR_API_KEY` disponível**, não invente uma e não pule silenciosamente: registre no relatório da task que a verificação contra o workspace real ficou pendente e por quê. É o único critério deste plano que os testes não cobrem.

O `smoke-escrita` fica a critério do usuário — ele escreve numa issue real e a escolha da issue de rascunho é dele.

- [ ] **Passo 7: Gate completo e commit**

```bash
uv run ruff check && uv run ruff format --check && uv run pytest
git add src/sentinela_graph/linear/__main__.py tests/linear/test_diagnostico.py README.md
git commit -m "feat(linear): diagnostico de fila e de escrita contra o workspace real"
```

---

## Verificação final da branch

```bash
uv run ruff check && uv run ruff format --check && uv run pytest
git log --oneline master..HEAD
git diff --stat master..HEAD
```

Esperado: seis commits, gate verde, e `git diff master..HEAD -- .env.template` mostrando **uma** linha adicionada e nenhuma removida.

## O que este épico deliberadamente não entrega

- **Nenhum nó do grafo.** `claim`, `report` e os outros consomem `escrita.py` na E5 e na E9; aqui só existe a camada de acesso.
- **A ferramenta `fetch_linear_issue` dos agentes.** É da E4: um servidor MCP in-process sobre este mesmo cliente, expondo **só leitura**.
- **Carregamento de `.env` no caminho do grafo.** Só o diagnóstico chama `load_dotenv()`. A E10 resolve isso no CLI de produto.
- **Paginação.** `LIMITE_FILA = 50` e `first: 100` nos comentários. Uma issue com mais de 100 comentários existe, e nesse caso o contrato mais antigo é o que se perde — se aparecer na prática, vira issue da E5.
