# E1 — Fundação do projeto e contratos de estado — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar o esqueleto do pacote `sentinela_graph` e os modelos Pydantic que todo nó do grafo consome, com o `GraphState` provadamente sobrevivendo a um round-trip pelo `SqliteSaver`.

**Architecture:** Um pacote `src/sentinela_graph/` com layout src instalável via hatchling. Os modelos ficam em `models/`, um arquivo por responsabilidade (issue congelada, roteamento, workspace, saídas de agente, resultados de execução), porque cada grupo muda junto com um épico diferente. `state.py` compõe todos eles no `GraphState` e declara o `Literal` de `outcome`. `checkpointer.py` isola a construção do `SqliteSaver` para que nenhum nó precise saber onde fica o `.state/graph.db`.

**Tech Stack:** Python 3.12, Pydantic 2.13, LangGraph 1.2, `langgraph-checkpoint-sqlite` 3.1, pytest 8, ruff, uv.

**Rastreabilidade:** épico [#1](https://github.com/victordantas1/graph-agent/issues/1); tasks [#12](https://github.com/victordantas1/graph-agent/issues/12), [#13](https://github.com/victordantas1/graph-agent/issues/13), [#14](https://github.com/victordantas1/graph-agent/issues/14), [#15](https://github.com/victordantas1/graph-agent/issues/15). Spec: `docs/superpowers/specs/2026-08-11-graph-of-agents-design.md`.

## Global Constraints

- **Python `>=3.12`.** O `.python-version` do repo é `3.12`.
- **Nenhuma chamada de rede em E1.** Nada de Linear, git, `glab`, Agent SDK. Só modelos e serialização.
- **Nenhum nó do grafo em E1.** Grafos aparecem nos testes apenas como fixture mínima para exercitar o checkpointer.
- **Campos em pt-BR onde a spec os nomeia em pt-BR** (`rota`, `confianca`, `evidencia`, `achados`, `suposicoes`, `arquivos`, `riscos`). Não traduzir para inglês: a spec, os prompts dos agentes e os comentários do Linear usam esses nomes.
- **Valores do `Literal` de `outcome`, exatos:** `mr_aberto`, `fila_vazia`, `ambiguo`, `subespecificado`, `reprovado_3x`, `erro`.
- **`MAX_ATTEMPTS = 3`**, conforme o ciclo de correção da spec.
- **Commits em Conventional Commits** (`<tipo>(<escopo>): <descrição>`), como os commits já existentes no repo.
- **Artefatos grandes ficam em disco; o estado guarda o caminho.** Nenhum modelo carrega conteúdo de plano, log ou diff — só ponteiro ou texto truncado.

## Decisões que estendem a spec

Três pontos onde as tasks do GitHub eram omissas e este plano fixa uma escolha. Estão aqui para não passarem despercebidos na revisão.

1. **`Verdict` ganha o campo `attempt`.** O `verdicts` do estado usa reducer `operator.add` — obrigatório, porque `review_adv` e `qa_func` escrevem no mesmo canal em paralelo e o LangGraph rejeita escrita concorrente sem reducer. Com `add`, os vereditos **acumulam entre tentativas**. Sem `attempt` no veredito, o `verdict_gate` da E7 leria a reprovação da tentativa 1 como se fosse da tentativa 2 e nunca aprovaria. `attempt` também preserva o histórico que o comentário de `reprovado_3x` precisa ("as 3 tentativas, laudo de cada uma").
2. **`GateReport.passou` é falso quando não há resultado nenhum.** `all([])` é `True` em Python; um relatório vazio significando "passou" faria um gate que nunca rodou virar sinal verde.
3. **`LANGGRAPH_STRICT_MSGPACK=true` é definido no `__init__.py` do pacote.** No modo permissivo (default hoje) o desserializador do LangGraph loga um `WARNING` por modelo Pydantic a cada leitura de checkpoint. No modo estrito nossos modelos passam normalmente e o log fica limpo. O flag é lido no import do `langgraph.checkpoint.serde._msgpack`, então precisa ser definido **antes** de qualquer import de langgraph — daí o `conftest.py` na raiz importar o pacote primeiro.

## File Structure

| arquivo | responsabilidade |
|---|---|
| `pyproject.toml` (modificar) | dependências, layout src, config de pytest e ruff |
| `conftest.py` (criar) | importa o pacote antes de qualquer langgraph, para o flag de msgpack valer |
| `src/sentinela_graph/__init__.py` (criar) | versão + `LANGGRAPH_STRICT_MSGPACK` |
| `src/sentinela_graph/models/__init__.py` (criar) | marcador de pacote, vazio |
| `src/sentinela_graph/models/issue.py` (criar) | `Comment`, `IssueRelation`, `IssueRef` — o que `load_issue` congela |
| `src/sentinela_graph/models/routing.py` (criar) | `Rota`, `Forge`, `Routing` — o que `classify` devolve |
| `src/sentinela_graph/models/workspace.py` (criar) | `Workspace` — o que `prepare_workspace` devolve |
| `src/sentinela_graph/models/agent_outputs.py` (criar) | `PlanSummary`, `Verdict`, `ImplementationSummary` — contratos dos agentes |
| `src/sentinela_graph/models/execution.py` (criar) | `GateResult`, `GateReport`, `MrRef` — saída dos nós determinísticos |
| `src/sentinela_graph/state.py` (criar) | `MAX_ATTEMPTS`, `Outcome`, `GraphState` |
| `src/sentinela_graph/checkpointer.py` (criar) | `build_checkpointer`, `config_da_issue` |
| `main.py` (apagar) | stub do template do `uv init`, substituído pelo pacote |

Testes espelham a estrutura: `tests/models/test_issue.py`, `test_routing.py`, `test_workspace.py`, `test_agent_outputs.py`, `test_execution.py`, `tests/test_state.py`, `tests/test_checkpointer.py`.

---

## Task 1: Esqueleto do pacote e gates de qualidade

Fecha a task [#12](https://github.com/victordantas1/graph-agent/issues/12).

**Files:**
- Modify: `pyproject.toml`
- Create: `src/sentinela_graph/__init__.py`
- Create: `src/sentinela_graph/models/__init__.py`
- Create: `conftest.py`
- Create: `tests/__init__.py` (vazio), `tests/models/__init__.py` (vazio)
- Create: `tests/test_pacote.py`
- Modify: `README.md`, `.gitignore`
- Delete: `main.py`

**Interfaces:**
- Consumes: nada.
- Produces: pacote importável `sentinela_graph` com `__version__: str`; comandos `uv run pytest` e `uv run ruff check` funcionando.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_pacote.py`:

```python
import os

import sentinela_graph


def test_pacote_expoe_versao():
    assert sentinela_graph.__version__ == "0.1.0"


def test_pacote_ativa_msgpack_estrito():
    # Precisa valer no import do pacote: o langgraph le esse flag no import
    # dele, e depois disso mudar a variavel nao tem efeito.
    assert os.environ["LANGGRAPH_STRICT_MSGPACK"] == "true"
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `uv run pytest tests/test_pacote.py -v`
Expected: erro de coleta, `ModuleNotFoundError: No module named 'sentinela_graph'`.

- [ ] **Step 3: Escrever o `pyproject.toml`**

Substituir o conteúdo inteiro de `pyproject.toml`:

```toml
[project]
name = "sentinela-graph-agent"
version = "0.1.0"
description = "Grafo de agentes que leva uma issue do Linear ate um MR aberto"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "langgraph>=1.2,<2",
    "langgraph-checkpoint-sqlite>=3.1,<4",
    "claude-agent-sdk>=0.2.136",
    "pydantic>=2.13,<3",
    "httpx>=0.28",
    "langfuse>=4.14,<5",
    "typer>=0.27",
]

[dependency-groups]
dev = [
    "pytest>=8.4",
    "ruff>=0.14",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/sentinela_graph"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

`packages` é obrigatório: o nome do projeto é `sentinela-graph-agent`, então o hatchling procuraria `src/sentinela_graph_agent`, que não existe.

- [ ] **Step 4: Criar o pacote**

`src/sentinela_graph/__init__.py`:

```python
"""Grafo de agentes que leva uma issue do Linear ate um MR aberto."""

import os

# Precisa vir antes de qualquer import de langgraph: o flag e lido uma unica
# vez, no import de langgraph.checkpoint.serde._msgpack. Sem ele, cada leitura
# de checkpoint loga um WARNING por modelo Pydantic do projeto.
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

__version__ = "0.1.0"
```

`src/sentinela_graph/models/__init__.py`, `tests/__init__.py` e `tests/models/__init__.py`: arquivos vazios.

`conftest.py` na raiz do repo:

```python
# Importado pelo pytest antes dos modulos de teste. Garante que o
# LANGGRAPH_STRICT_MSGPACK definido no pacote valha mesmo em testes que
# importam langgraph direto.
import sentinela_graph  # noqa: F401
```

- [ ] **Step 5: Apagar o stub do template**

`main.py` nunca foi rastreado (veio do `uv init` e está como untracked), então basta apagá-lo:

```bash
rm -f main.py
```

- [ ] **Step 6: Instalar e rodar os testes**

Run: `uv sync && uv run pytest -v`
Expected: `2 passed`.

- [ ] **Step 7: Ajustar o `.gitignore`**

Acrescentar ao final de `.gitignore`:

```gitignore
# Estado do grafo (checkpoints e ledger)
.state/

# IDE
.idea/
```

- [ ] **Step 8: Escrever o README**

Substituir o conteúdo de `README.md`:

````markdown
# sentinela-graph-agent

Grafo de agentes que leva uma issue do Linear — status `To Do` **e** label
`Ready` — ate um Merge Request aberto, sem intervencao humana durante a
execucao.

Design: [`docs/superpowers/specs/2026-08-11-graph-of-agents-design.md`](docs/superpowers/specs/2026-08-11-graph-of-agents-design.md)

## Desenvolvimento

```bash
uv sync                 # instala tudo, inclusive o grupo dev
uv run pytest           # testes
uv run ruff check       # lint
uv run ruff format      # formatacao
```

Gate completo antes de commitar:

```bash
uv run ruff check && uv run ruff format --check && uv run pytest
```

## Configuracao

Copie `.env.template` para `.env` e preencha. Nenhuma chave entra no
repositorio.
````

- [ ] **Step 9: Rodar o gate completo**

Run: `uv run ruff check && uv run ruff format --check && uv run pytest`
Expected: tudo verde. Se o `ruff format --check` reclamar, rodar `uv run ruff format` e repetir.

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml uv.lock conftest.py README.md .gitignore .python-version .env.template
git add src/sentinela_graph/__init__.py src/sentinela_graph/models/__init__.py
git add tests/__init__.py tests/models/__init__.py tests/test_pacote.py
git commit -m "chore: esqueleto do pacote e gates de qualidade

Layout src com hatchling, dependencias do grafo e config de pytest e ruff.
LANGGRAPH_STRICT_MSGPACK ativado no import do pacote para o desserializador
de checkpoint nao logar um aviso por modelo Pydantic.

Closes #12

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

Nunca use `git add -A`: há arquivos não rastreados fora do escopo circulando em `/home/victor/nomos/`.

---

## Task 2: Modelos de issue, roteamento e workspace

Fecha a task [#13](https://github.com/victordantas1/graph-agent/issues/13).

**Files:**
- Create: `src/sentinela_graph/models/issue.py`
- Create: `src/sentinela_graph/models/routing.py`
- Create: `src/sentinela_graph/models/workspace.py`
- Test: `tests/models/test_issue.py`, `tests/models/test_routing.py`, `tests/models/test_workspace.py`

**Interfaces:**
- Consumes: pacote `sentinela_graph` da Task 1.
- Produces:
  - `sentinela_graph.models.issue`: `Comment(id, author, body, created_at)`; `IssueRelation(identifier, title, state, url, tipo)`; `IssueRef(id, identifier, title, url, git_branch_name, spec, state, labels, priority, comments, relations)`; `TipoRelacao = Literal["parent","sub","blocks","blocked_by","related"]`.
  - `sentinela_graph.models.routing`: `Rota = Literal["feature","bug","improvement"]`; `Forge = Literal["glab","gh"]`; `Routing(repo, base, forge, dirs, rota, confianca, evidencia)`.
  - `sentinela_graph.models.workspace`: `Workspace(worktree_path, branch, app_root, install_ok, port)`.

- [ ] **Step 1: Escrever os testes que falham**

`tests/models/test_issue.py`:

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from sentinela_graph.models.issue import Comment, IssueRef, IssueRelation


def _issue(**overrides) -> IssueRef:
    campos = {
        "id": "e5a1-uuid",
        "identifier": "NOM-716",
        "title": "Instrumentar o tracing com Langfuse",
        "url": "https://linear.app/nomos/issue/NOM-716",
        "git_branch_name": "victor/nom-716-langfuse",
        "spec": "Adicionar tracing por requisicao.",
        "state": "To Do",
    }
    campos.update(overrides)
    return IssueRef(**campos)


def test_issue_minima_tem_colecoes_vazias():
    issue = _issue()
    assert issue.labels == []
    assert issue.comments == []
    assert issue.relations == []
    assert issue.priority == 0


def test_issue_sem_git_branch_name_e_rejeitada():
    with pytest.raises(ValidationError):
        IssueRef(
            id="e5a1-uuid",
            identifier="NOM-716",
            title="t",
            url="u",
            spec="s",
            state="To Do",
        )


def test_comentarios_preservam_a_ordem():
    # O contrato mora nos comentarios; a ordem cronologica e o que diz qual
    # instrucao vale.
    issue = _issue(
        comments=[
            Comment(
                id="c1",
                author="victor",
                body="primeiro",
                created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            ),
            Comment(
                id="c2",
                author="victor",
                body="segundo",
                created_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            ),
        ]
    )
    assert [c.body for c in issue.comments] == ["primeiro", "segundo"]


def test_relacao_com_tipo_invalido_e_rejeitada():
    with pytest.raises(ValidationError):
        IssueRelation(
            identifier="NOM-643",
            title="outra",
            state="Done",
            url="u",
            tipo="duplicada",
        )
```

`tests/models/test_routing.py`:

```python
import pytest
from pydantic import ValidationError

from sentinela_graph.models.routing import Routing


def _routing(**overrides) -> Routing:
    campos = {
        "repo": "nomos-api",
        "base": "develop",
        "forge": "glab",
        "dirs": ["app/src/modules/tracing"],
        "rota": "feature",
        "confianca": 0.87,
        "evidencia": "grep 'langfuse' encontrou app/src/modules/tracing",
    }
    campos.update(overrides)
    return Routing(**campos)


def test_routing_valido():
    assert _routing().repo == "nomos-api"


@pytest.mark.parametrize("valor", [-0.01, 1.01])
def test_confianca_fora_de_zero_a_um_e_rejeitada(valor):
    with pytest.raises(ValidationError):
        _routing(confianca=valor)


@pytest.mark.parametrize("valor", [0.0, 1.0])
def test_confianca_aceita_os_extremos(valor):
    assert _routing(confianca=valor).confianca == valor


def test_rota_fora_do_vocabulario_e_rejeitada():
    with pytest.raises(ValidationError):
        _routing(rota="epico")


def test_forge_fora_do_vocabulario_e_rejeitada():
    with pytest.raises(ValidationError):
        _routing(forge="hub")


def test_routing_sem_diretorio_e_rejeitado():
    # Roteamento sem diretorio nao diz onde o agente trabalha.
    with pytest.raises(ValidationError):
        _routing(dirs=[])


def test_routing_sem_evidencia_e_rejeitado():
    # A escolha de repo exige evidencia no codigo: repo errado e um MR
    # inteiro jogado fora.
    with pytest.raises(ValidationError):
        _routing(evidencia="")
```

`tests/models/test_workspace.py`:

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from sentinela_graph.models.workspace import Workspace


def _workspace(**overrides) -> Workspace:
    campos = {
        "worktree_path": "/home/victor/nomos/.worktrees/nomos-api/victor/nom-716",
        "branch": "victor/nom-716-langfuse",
        "app_root": "/home/victor/nomos/.worktrees/nomos-api/victor/nom-716/app",
    }
    campos.update(overrides)
    return Workspace(**campos)


def test_caminhos_viram_path():
    ws = _workspace()
    assert isinstance(ws.worktree_path, Path)
    assert isinstance(ws.app_root, Path)


def test_install_e_porta_comecam_indefinidos():
    ws = _workspace()
    assert ws.install_ok is False
    assert ws.port is None


def test_porta_privilegiada_e_rejeitada():
    # serve_app aloca porta dinamica; nada abaixo de 1024 e alocavel sem root.
    with pytest.raises(ValidationError):
        _workspace(port=80)


def test_workspace_sem_branch_e_rejeitado():
    with pytest.raises(ValidationError):
        Workspace(worktree_path="/tmp/wt", app_root="/tmp/wt/app")
```

- [ ] **Step 2: Rodar os testes e ver falhar**

Run: `uv run pytest tests/models -v`
Expected: erro de coleta, `ModuleNotFoundError: No module named 'sentinela_graph.models.issue'`.

- [ ] **Step 3: Implementar `models/issue.py`**

```python
"""Issue do Linear congelada por `load_issue`.

Congelar torna o run reproduzivel: `--resume` e o Langfuse mostram o que o
agente viu, nao o que a issue virou depois.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TipoRelacao = Literal["parent", "sub", "blocks", "blocked_by", "related"]


class Comment(BaseModel):
    """Comentario da issue. O contrato mora aqui, nao na descricao."""

    id: str
    author: str
    body: str
    created_at: datetime


class IssueRelation(BaseModel):
    """Issue vizinha: so titulo, estado e URL.

    O corpo nao entra no contexto por padrao — quem precisar dele chama a
    ferramenta `fetch_linear_issue`.
    """

    identifier: str
    title: str
    state: str
    url: str
    tipo: TipoRelacao


class IssueRef(BaseModel):
    """Tudo que o grafo sabe da issue no instante em que a reivindicou."""

    id: str
    identifier: str
    title: str
    url: str
    git_branch_name: str
    spec: str
    state: str
    labels: list[str] = Field(default_factory=list)
    priority: int = 0
    comments: list[Comment] = Field(default_factory=list)
    relations: list[IssueRelation] = Field(default_factory=list)
```

- [ ] **Step 4: Implementar `models/routing.py`**

```python
"""Decisao do agente `classify`: em que repositorio o trabalho acontece."""

from typing import Literal

from pydantic import BaseModel, Field

Rota = Literal["feature", "bug", "improvement"]
Forge = Literal["glab", "gh"]


class Routing(BaseModel):
    """Repositorio, diretorios e rota escolhidos, com a evidencia que sustenta."""

    repo: str = Field(min_length=1)
    base: str = Field(min_length=1)
    forge: Forge
    dirs: list[str] = Field(min_length=1)
    rota: Rota
    confianca: float = Field(ge=0.0, le=1.0)
    evidencia: str = Field(min_length=1)
```

- [ ] **Step 5: Implementar `models/workspace.py`**

```python
"""Worktree isolado onde a implementacao e a validacao acontecem."""

from pathlib import Path

from pydantic import BaseModel, Field


class Workspace(BaseModel):
    """Um `git worktree` por issue, em /home/victor/nomos/.worktrees/<repo>/<branch>."""

    worktree_path: Path
    branch: str = Field(min_length=1)
    app_root: Path
    install_ok: bool = False
    port: int | None = Field(default=None, ge=1024, le=65535)
```

- [ ] **Step 6: Rodar os testes e ver passar**

Run: `uv run pytest tests/models -v`
Expected: todos passam.

- [ ] **Step 7: Commit**

```bash
git add src/sentinela_graph/models/issue.py src/sentinela_graph/models/routing.py \
        src/sentinela_graph/models/workspace.py \
        tests/models/test_issue.py tests/models/test_routing.py tests/models/test_workspace.py
uv run ruff check && uv run ruff format --check && uv run pytest
git commit -m "feat(models): issue congelada, roteamento e workspace

IssueRef guarda a spec e os comentarios em ordem; relacoes so com titulo,
estado e URL. Routing exige diretorio e evidencia, e limita confianca a
0..1. Workspace rejeita porta privilegiada.

Closes #13

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: Contratos de saída dos agentes e dos nós determinísticos

Fecha a task [#14](https://github.com/victordantas1/graph-agent/issues/14).

**Files:**
- Create: `src/sentinela_graph/models/agent_outputs.py`
- Create: `src/sentinela_graph/models/execution.py`
- Test: `tests/models/test_agent_outputs.py`, `tests/models/test_execution.py`

**Interfaces:**
- Consumes: pacote `sentinela_graph` da Task 1.
- Produces:
  - `sentinela_graph.models.agent_outputs`: `TipoCommit = Literal["feat","fix","refactor","chore"]`; `NomeValidador = Literal["review_adv","qa_func"]`; `PlanSummary(bugs, features, arquivos, riscos, suposicoes)`; `Verdict(agente, attempt, aprovado, achados, evidencia)`; `ImplementationSummary(tipo, escopo, resumo, mudancas, arquivos_tocados, comandos_validacao)`.
  - `sentinela_graph.models.execution`: `LIMITE_SAIDA: int`; `GateResult(comando, passou, saida)`; `GateReport(resultados)` com as propriedades `passou` e `falhas`; `MrRef(url, numero, titulo, branch, base)`.

- [ ] **Step 1: Escrever os testes que falham**

`tests/models/test_agent_outputs.py`:

```python
import pytest
from pydantic import ValidationError

from sentinela_graph.models.agent_outputs import (
    ImplementationSummary,
    PlanSummary,
    Verdict,
)


def test_plan_summary_vazio_ainda_tem_suposicoes():
    # "Suposicoes" e a valvula que substitui a pergunta ao humano: a secao
    # existe sempre, ainda que vazia.
    plano = PlanSummary()
    assert plano.suposicoes == []
    assert plano.bugs == []


def test_plan_summary_round_trip():
    plano = PlanSummary(
        bugs=["tracing perde o span em erro 500"],
        features=["exportar custo por agente"],
        arquivos=["app/src/modules/tracing/tracing.service.ts"],
        riscos=["latencia adicional no hot path"],
        suposicoes=["a spec nao diz o sampling; assumido 100%"],
    )
    assert PlanSummary.model_validate_json(plano.model_dump_json()) == plano


def test_verdict_aprovado_dispensa_achado():
    veredito = Verdict(agente="review_adv", attempt=0, aprovado=True, evidencia="diff limpo")
    assert veredito.achados == []


def test_verdict_reprovado_sem_achado_e_rejeitado():
    # Reprovar sem dizer o que esta errado nao alimenta o findings_digest.
    with pytest.raises(ValidationError):
        Verdict(agente="qa_func", attempt=1, aprovado=False, evidencia="curl 500")


def test_verdict_reprovado_com_achado_e_valido():
    veredito = Verdict(
        agente="qa_func",
        attempt=1,
        aprovado=False,
        achados=["POST /traces devolve 500 sem body"],
        evidencia="curl -X POST localhost:3000/traces",
    )
    assert veredito.achados


def test_verdict_de_agente_desconhecido_e_rejeitado():
    with pytest.raises(ValidationError):
        Verdict(agente="implement", attempt=0, aprovado=True, evidencia="e")


def test_verdict_round_trip():
    veredito = Verdict(
        agente="review_adv",
        attempt=2,
        aprovado=False,
        achados=["teste nao cobre o caminho de erro"],
        evidencia="git diff origin/develop...HEAD",
    )
    assert Verdict.model_validate_json(veredito.model_dump_json()) == veredito


def _impl(**overrides) -> ImplementationSummary:
    campos = {
        "tipo": "feat",
        "escopo": "tracing",
        "resumo": "instrumenta o tracing das requisicoes com Langfuse",
        "mudancas": ["tracing.service.ts: cria o span por requisicao"],
        "arquivos_tocados": ["app/src/modules/tracing/tracing.service.ts"],
        "comandos_validacao": ["npx jest app/src/modules/tracing/tracing.service.spec.ts"],
    }
    campos.update(overrides)
    return ImplementationSummary(**campos)


def test_implementation_summary_round_trip():
    impl = _impl()
    assert ImplementationSummary.model_validate_json(impl.model_dump_json()) == impl


def test_implementation_summary_sem_comando_de_validacao_e_rejeitado():
    # A secao "Como validar" do MR nao pode sair vazia.
    with pytest.raises(ValidationError):
        _impl(comandos_validacao=[])


def test_tipo_de_commit_fora_do_vocabulario_e_rejeitado():
    with pytest.raises(ValidationError):
        _impl(tipo="feature")
```

`tests/models/test_execution.py`:

```python
import pytest
from pydantic import ValidationError

from sentinela_graph.models.execution import LIMITE_SAIDA, GateReport, GateResult, MrRef


def test_gate_result_round_trip():
    resultado = GateResult(comando="npm run lint", passou=True, saida="ok")
    assert GateResult.model_validate_json(resultado.model_dump_json()) == resultado


def test_saida_gigante_e_truncada():
    # A saida entra no checkpoint e volta para o implementador como contexto.
    resultado = GateResult(comando="npx jest", passou=False, saida="x" * (LIMITE_SAIDA + 500))
    assert len(resultado.saida) < LIMITE_SAIDA + 200
    assert "truncado" in resultado.saida


def test_relatorio_verde():
    relatorio = GateReport(
        resultados=[
            GateResult(comando="npm run build", passou=True),
            GateResult(comando="npm run lint", passou=True),
        ]
    )
    assert relatorio.passou is True
    assert relatorio.falhas == []


def test_relatorio_com_uma_falha_reprova():
    falha = GateResult(comando="npx jest a.spec.ts", passou=False, saida="1 failing")
    relatorio = GateReport(resultados=[GateResult(comando="npm run build", passou=True), falha])
    assert relatorio.passou is False
    assert relatorio.falhas == [falha]


def test_relatorio_vazio_nao_passa():
    # all([]) e True em Python. Um relatorio sem nenhum gate executado nao
    # pode virar sinal verde.
    assert GateReport().passou is False


def test_relatorio_round_trip():
    relatorio = GateReport(resultados=[GateResult(comando="npm run build", passou=True)])
    assert GateReport.model_validate_json(relatorio.model_dump_json()) == relatorio


def test_mr_ref_round_trip():
    mr = MrRef(
        url="https://gitlab.com/nomos/nomos-api/-/merge_requests/412",
        numero="!412",
        titulo="feat(tracing): instrumenta o tracing das requisicoes",
        branch="victor/nom-716-langfuse",
        base="develop",
    )
    assert MrRef.model_validate_json(mr.model_dump_json()) == mr


def test_mr_ref_sem_url_e_rejeitado():
    with pytest.raises(ValidationError):
        MrRef(url="", numero="!412", titulo="t", branch="b", base="develop")
```

- [ ] **Step 2: Rodar os testes e ver falhar**

Run: `uv run pytest tests/models/test_agent_outputs.py tests/models/test_execution.py -v`
Expected: erro de coleta, `ModuleNotFoundError: No module named 'sentinela_graph.models.agent_outputs'`.

- [ ] **Step 3: Implementar `models/agent_outputs.py`**

```python
"""Contratos de saida dos agentes do Agent SDK.

O grafo renderiza o MR e os comentarios do Linear a partir destes objetos.
Nenhum texto livre de LLM chega direto ao Linear ou ao GitLab.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

TipoCommit = Literal["feat", "fix", "refactor", "chore"]
NomeValidador = Literal["review_adv", "qa_func"]


class PlanSummary(BaseModel):
    """Resumo do plano. Vira o comentario que `post_plan` publica na issue."""

    bugs: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    arquivos: list[str] = Field(default_factory=list)
    riscos: list[str] = Field(default_factory=list)
    suposicoes: list[str] = Field(default_factory=list)


class Verdict(BaseModel):
    """Veredito de um validador sobre uma tentativa especifica.

    `attempt` e obrigatorio porque o canal `verdicts` do estado acumula entre
    tentativas: sem ele, o `verdict_gate` leria a reprovacao da tentativa
    anterior como se fosse da atual.
    """

    agente: NomeValidador
    attempt: int = Field(ge=0)
    aprovado: bool
    achados: list[str] = Field(default_factory=list)
    evidencia: str = Field(min_length=1)

    @model_validator(mode="after")
    def _reprovar_exige_achado(self) -> "Verdict":
        if not self.aprovado and not self.achados:
            raise ValueError("veredito reprovado precisa de pelo menos um achado")
        return self


class ImplementationSummary(BaseModel):
    """Saida do `implement`. Alimenta o titulo e o corpo do MR."""

    tipo: TipoCommit
    escopo: str = Field(min_length=1)
    resumo: str = Field(min_length=1)
    mudancas: list[str] = Field(min_length=1)
    arquivos_tocados: list[str] = Field(min_length=1)
    comandos_validacao: list[str] = Field(min_length=1)
```

- [ ] **Step 4: Implementar `models/execution.py`**

```python
"""Resultados dos nos deterministicos: gates do repo e MR aberto."""

from pydantic import BaseModel, Field, field_validator

LIMITE_SAIDA = 8000


class GateResult(BaseModel):
    """Um comando do registry executado no worktree."""

    comando: str = Field(min_length=1)
    passou: bool
    saida: str = ""

    @field_validator("saida")
    @classmethod
    def _truncar(cls, valor: str) -> str:
        # A saida entra no checkpoint e volta como contexto para o
        # implementador. Log de suite inteira estoura os dois.
        if len(valor) <= LIMITE_SAIDA:
            return valor
        cortado = len(valor) - LIMITE_SAIDA
        return f"{valor[:LIMITE_SAIDA]}\n[... truncado, {cortado} caracteres ...]"


class GateReport(BaseModel):
    """Relatorio de `repo_gates`: build, lint, format e testes dos arquivos tocados."""

    resultados: list[GateResult] = Field(default_factory=list)

    @property
    def passou(self) -> bool:
        # Relatorio vazio nao passa: gate que nao rodou nao e gate verde.
        return bool(self.resultados) and all(r.passou for r in self.resultados)

    @property
    def falhas(self) -> list[GateResult]:
        return [r for r in self.resultados if not r.passou]


class MrRef(BaseModel):
    """MR/PR aberto por `open_mr`, vinculado na issue por `report`."""

    url: str = Field(min_length=1)
    numero: str = Field(min_length=1)
    titulo: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    base: str = Field(min_length=1)
```

- [ ] **Step 5: Rodar os testes e ver passar**

Run: `uv run pytest tests/models -v`
Expected: todos passam, incluindo os da Task 2.

- [ ] **Step 6: Commit**

```bash
git add src/sentinela_graph/models/agent_outputs.py src/sentinela_graph/models/execution.py \
        tests/models/test_agent_outputs.py tests/models/test_execution.py
uv run ruff check && uv run ruff format --check && uv run pytest
git commit -m "feat(models): contratos de saida dos agentes e dos gates

Verdict reprovado exige achado e carrega a tentativa, porque o canal de
vereditos acumula entre tentativas. GateResult trunca a saida antes de ela
entrar no checkpoint, e GateReport vazio nao passa.

Closes #14

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: `GraphState` e checkpointer

Fecha a task [#15](https://github.com/victordantas1/graph-agent/issues/15).

**Files:**
- Create: `src/sentinela_graph/state.py`
- Create: `src/sentinela_graph/checkpointer.py`
- Test: `tests/test_state.py`, `tests/test_checkpointer.py`

**Interfaces:**
- Consumes: todos os modelos das Tasks 2 e 3.
- Produces:
  - `sentinela_graph.state`: `MAX_ATTEMPTS = 3`; `Outcome` (Literal de 6 valores); `GraphState` com o campo `verdicts: Annotated[list[Verdict], operator.add]` e o método `verdicts_da_tentativa(attempt) -> list[Verdict]`.
  - `sentinela_graph.checkpointer`: `CAMINHO_PADRAO: Path`; `build_checkpointer(caminho) -> context manager de SqliteSaver`; `config_da_issue(identifier) -> dict`.

- [ ] **Step 1: Escrever o teste de `GraphState`**

`tests/test_state.py`:

```python
import pytest
from pydantic import ValidationError

from sentinela_graph.models.agent_outputs import Verdict
from sentinela_graph.state import MAX_ATTEMPTS, GraphState


def test_estado_inicial_e_todo_vazio():
    estado = GraphState()
    assert estado.issue is None
    assert estado.routing is None
    assert estado.attempt == 0
    assert estado.verdicts == []
    assert estado.findings_digest == ""
    assert estado.outcome is None


@pytest.mark.parametrize(
    "outcome",
    ["mr_aberto", "fila_vazia", "ambiguo", "subespecificado", "reprovado_3x", "erro"],
)
def test_outcomes_do_vocabulario_sao_aceitos(outcome):
    assert GraphState(outcome=outcome).outcome == outcome


def test_outcome_fora_do_vocabulario_e_rejeitado():
    with pytest.raises(ValidationError):
        GraphState(outcome="sucesso")


def test_attempt_acima_do_limite_e_rejeitado():
    assert GraphState(attempt=MAX_ATTEMPTS).attempt == 3
    with pytest.raises(ValidationError):
        GraphState(attempt=MAX_ATTEMPTS + 1)


def test_attempt_negativo_e_rejeitado():
    with pytest.raises(ValidationError):
        GraphState(attempt=-1)


def test_verdicts_da_tentativa_filtra_o_historico():
    # O canal de vereditos acumula: o gate so pode olhar a tentativa corrente.
    estado = GraphState(
        attempt=1,
        verdicts=[
            Verdict(
                agente="review_adv",
                attempt=0,
                aprovado=False,
                achados=["sem teste de erro"],
                evidencia="diff",
            ),
            Verdict(agente="review_adv", attempt=1, aprovado=True, evidencia="diff"),
            Verdict(agente="qa_func", attempt=1, aprovado=True, evidencia="curl"),
        ],
    )
    atuais = estado.verdicts_da_tentativa(1)
    assert len(atuais) == 2
    assert all(v.aprovado for v in atuais)
    assert len(estado.verdicts_da_tentativa(0)) == 1
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_state.py -v`
Expected: erro de coleta, `ModuleNotFoundError: No module named 'sentinela_graph.state'`.

- [ ] **Step 3: Implementar `state.py`**

```python
"""Estado do grafo.

Artefatos volumosos ficam em disco no worktree; aqui mora o ponteiro, o
veredito e o contador.
"""

import operator
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from sentinela_graph.models.agent_outputs import (
    ImplementationSummary,
    PlanSummary,
    Verdict,
)
from sentinela_graph.models.execution import GateReport, MrRef
from sentinela_graph.models.issue import IssueRef
from sentinela_graph.models.routing import Routing
from sentinela_graph.models.workspace import Workspace

MAX_ATTEMPTS = 3

Outcome = Literal[
    "mr_aberto",
    "fila_vazia",
    "ambiguo",
    "subespecificado",
    "reprovado_3x",
    "erro",
]


class GraphState(BaseModel):
    """O que o checkpoint guarda entre um no e o proximo."""

    issue: IssueRef | None = None
    routing: Routing | None = None
    workspace: Workspace | None = None
    plan_path: str | None = None
    plan_summary: PlanSummary | None = None
    attempt: int = Field(default=0, ge=0, le=MAX_ATTEMPTS)
    gate_report: GateReport | None = None
    # `review_adv` e `qa_func` escrevem neste canal em paralelo: sem reducer,
    # o LangGraph rejeita a escrita concorrente. Com `add`, os vereditos
    # acumulam entre tentativas — filtre com `verdicts_da_tentativa`.
    verdicts: Annotated[list[Verdict], operator.add] = Field(default_factory=list)
    findings_digest: str = ""
    impl_summary: ImplementationSummary | None = None
    mr: MrRef | None = None
    outcome: Outcome | None = None

    def verdicts_da_tentativa(self, attempt: int) -> list[Verdict]:
        """Vereditos de uma tentativa. E sobre eles que o `verdict_gate` decide."""
        return [v for v in self.verdicts if v.attempt == attempt]
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/test_state.py -v`
Expected: todos passam.

- [ ] **Step 5: Escrever o teste do checkpointer**

`tests/test_checkpointer.py`:

```python
import logging

from langgraph.graph import END, START, StateGraph

from sentinela_graph.checkpointer import build_checkpointer, config_da_issue
from sentinela_graph.models.agent_outputs import Verdict
from sentinela_graph.models.issue import IssueRef
from sentinela_graph.models.routing import Routing
from sentinela_graph.models.workspace import Workspace
from sentinela_graph.state import GraphState

ISSUE = IssueRef(
    id="e5a1-uuid",
    identifier="NOM-716",
    title="Instrumentar o tracing com Langfuse",
    url="https://linear.app/nomos/issue/NOM-716",
    git_branch_name="victor/nom-716-langfuse",
    spec="Adicionar tracing por requisicao.",
    state="Doing",
)
ROUTING = Routing(
    repo="nomos-api",
    base="develop",
    forge="glab",
    dirs=["app/src/modules/tracing"],
    rota="feature",
    confianca=0.87,
    evidencia="grep langfuse",
)
WORKSPACE = Workspace(
    worktree_path="/home/victor/nomos/.worktrees/nomos-api/victor/nom-716",
    branch="victor/nom-716-langfuse",
    app_root="/home/victor/nomos/.worktrees/nomos-api/victor/nom-716/app",
    install_ok=True,
    port=4321,
)


def _carrega(state: GraphState) -> dict:
    return {"issue": ISSUE, "routing": ROUTING, "workspace": WORKSPACE}


def _review(state: GraphState) -> dict:
    return {
        "verdicts": [
            Verdict(agente="review_adv", attempt=0, aprovado=True, evidencia="diff limpo")
        ]
    }


def _qa(state: GraphState) -> dict:
    return {
        "verdicts": [Verdict(agente="qa_func", attempt=0, aprovado=True, evidencia="curl 200")]
    }


def _grafo() -> StateGraph:
    """Fan-out minimo que reproduz a topologia review_adv || qa_func."""
    g = StateGraph(GraphState)
    g.add_node("carrega", _carrega)
    g.add_node("review", _review)
    g.add_node("qa", _qa)
    g.add_edge(START, "carrega")
    g.add_edge("carrega", "review")
    g.add_edge("carrega", "qa")
    g.add_edge("review", END)
    g.add_edge("qa", END)
    return g


def test_estado_sobrevive_ao_round_trip_pelo_sqlite_saver(tmp_path, caplog):
    caplog.set_level(logging.WARNING)
    db = tmp_path / ".state" / "graph.db"
    config = config_da_issue("NOM-716")

    with build_checkpointer(db) as saver:
        _grafo().compile(checkpointer=saver).invoke(GraphState(), config)

    # Segunda conexao: e o que o `--resume` faz, num processo novo.
    with build_checkpointer(db) as saver:
        valores = _grafo().compile(checkpointer=saver).get_state(config).values
    restaurado = GraphState.model_validate(valores)

    assert restaurado.issue == ISSUE
    assert restaurado.routing == ROUTING
    assert restaurado.workspace == WORKSPACE
    assert restaurado.workspace.port == 4321
    assert {v.agente for v in restaurado.verdicts_da_tentativa(0)} == {"review_adv", "qa_func"}
    assert not [r for r in caplog.records if "unregistered type" in r.getMessage()]


def test_o_banco_e_criado_no_caminho_pedido(tmp_path):
    db = tmp_path / "fundo" / ".state" / "graph.db"
    with build_checkpointer(db) as saver:
        saver.setup()
    assert db.exists()


def test_thread_id_e_o_identifier_da_issue():
    assert config_da_issue("NOM-716") == {"configurable": {"thread_id": "NOM-716"}}


def test_threads_diferentes_nao_se_misturam(tmp_path):
    db = tmp_path / ".state" / "graph.db"
    with build_checkpointer(db) as saver:
        app = _grafo().compile(checkpointer=saver)
        app.invoke(GraphState(), config_da_issue("NOM-716"))
        assert app.get_state(config_da_issue("NOM-999")).values == {}
```

O teste do fan-out é o que prova o reducer: sem `operator.add` no canal `verdicts`, o LangGraph aborta a execução com erro de escrita concorrente. O `assert` do `caplog` é o que prova o `LANGGRAPH_STRICT_MSGPACK`: sem ele, cada modelo Pydantic gera um `WARNING` na leitura.

- [ ] **Step 6: Rodar e ver falhar**

Run: `uv run pytest tests/test_checkpointer.py -v`
Expected: erro de coleta, `ModuleNotFoundError: No module named 'sentinela_graph.checkpointer'`.

- [ ] **Step 7: Implementar `checkpointer.py`**

```python
"""Checkpointer do grafo.

`thread_id` e o identifier da issue: um run por issue, retomavel com
`--resume NOM-716`. Substitui o `.linear-loop-state.md`, que guardava o
"onde parei" em prosa.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

CAMINHO_PADRAO = Path(".state/graph.db")


@contextmanager
def build_checkpointer(caminho: Path = CAMINHO_PADRAO) -> Iterator[SqliteSaver]:
    """Abre o checkpointer, criando o diretorio se preciso."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(caminho)) as saver:
        yield saver


def config_da_issue(identifier: str) -> dict:
    """Config do LangGraph para o run de uma issue."""
    return {"configurable": {"thread_id": identifier}}
```

- [ ] **Step 8: Rodar e ver passar**

Run: `uv run pytest tests/test_checkpointer.py -v`
Expected: todos passam.

- [ ] **Step 9: Rodar a suíte inteira e o gate**

Run: `uv run ruff check && uv run ruff format --check && uv run pytest`
Expected: tudo verde.

- [ ] **Step 10: Commit**

```bash
git add src/sentinela_graph/state.py src/sentinela_graph/checkpointer.py \
        tests/test_state.py tests/test_checkpointer.py
git commit -m "feat(state): GraphState e checkpointer em sqlite

O canal de vereditos usa reducer add porque review_adv e qa_func escrevem
nele em paralelo. thread_id e o identifier da issue, o que sustenta o
--resume. Teste prova o round-trip completo por duas conexoes distintas.

Closes #15

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Verificação final do épico

Depois da Task 4, o critério de entrega do épico [#1](https://github.com/victordantas1/graph-agent/issues/1) — *"`pytest` verde com os modelos do `GraphState` cobertos, incluindo round-trip de serialização"* — se comprova com:

```bash
uv sync
uv run ruff check
uv run ruff format --check
uv run pytest -v
```

E fechando o épico:

```bash
gh issue close 1 --repo victordantas1/graph-agent \
  --comment "E1 entregue: pacote, modelos e round-trip do GraphState pelo SqliteSaver."
```

O que **não** existe ao final da E1, por decisão: nenhum nó do grafo, nenhum cliente Linear, nenhum registry de repos, nenhuma sessão do Agent SDK. Isso é E2 em diante.
