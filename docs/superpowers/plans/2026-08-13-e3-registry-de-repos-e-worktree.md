# E3 — Registry de repos e workspace isolado por worktree — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer os 6 repos da Nomos custarem configuração e não código, e dar a cada issue um `git worktree` isolado do working tree sujo do humano — criado a partir de `origin/`, abastecido com os arquivos não versionados, instalado, validado pelos gates do próprio repo e preservado em qualquer fracasso.

**Architecture:** Um YAML declarativo (`config/repos.yaml`) validado por Pydantic no boot é a única fonte de verdade sobre os 6 repos. Sobre ele, três funções determinísticas puras — `prepare_workspace`, `run_repo_gates` e `finalizar_workspace` — que a E5/E6/E9 vão embrulhar como nós do grafo. Todas recebem um `Runner` injetável (`run_command` por padrão), que é o que permite testar a ordem e o conteúdo exato dos comandos sem subprocess, e testar o comportamento de git de verdade contra um repositório de fixture com remoto local.

**Tech Stack:** Python 3.12, Pydantic 2.13, PyYAML 6, pytest 8, ruff, uv, `git` ≥ 2.43.

**Spec:** `docs/superpowers/specs/2026-08-11-graph-of-agents-design.md` — seções *Registry de repos*, *`prepare_workspace`*, *`repo_gates`* e *Tratamento de erros*.

**Rastreabilidade:** épico [#3](https://github.com/victordantas1/graph-agent/issues/3); tasks [#21](https://github.com/victordantas1/graph-agent/issues/21), [#22](https://github.com/victordantas1/graph-agent/issues/22), [#23](https://github.com/victordantas1/graph-agent/issues/23), [#24](https://github.com/victordantas1/graph-agent/issues/24), [#25](https://github.com/victordantas1/graph-agent/issues/25). Depende da E1 ([#1](https://github.com/victordantas1/graph-agent/issues/1)), já entregue.

## Global Constraints

- **Python `>=3.12`**, `line-length = 100`, ruff com `select = ["E", "F", "I", "UP", "B"]`.
- **Nenhuma chamada de rede a serviço externo em E3.** Nada de Linear, Agent SDK, `glab`, `gh`. O único processo externo é `git`, e nos testes ele só toca repositórios criados em `tmp_path`.
- **Nenhum nó do grafo em E3.** A E3 entrega funções; a E5 (#31) as registra como nós. Nada aqui importa `langgraph`.
- **Nenhum estado global.** Toda função recebe o `Registry` e o `Runner` por parâmetro. Não existe singleton de registry.
- **Campos em pt-BR onde a spec os nomeia em pt-BR** (`rota`, `confianca`, `evidencia`, `achados`, `suposicoes`, `notas`). As chaves do registry vêm da spec em inglês (`install`, `build`, `lint`, `format_check`, `test`, `copy_untracked`, `qa_mode`, `serve`, `health`) e ficam como estão.
- **Valores da tabela do registry, exatos, conforme a spec:**

  | repo | root | base | forge | test | qa_mode |
  |---|---|---|---|---|---|
  | `nomos-api` | `app` | `develop` | `glab` | `npx jest {arquivo}` | `http` |
  | `nomos.pro` | `.` | `develop` | `glab` | `yarn test {arquivo}` | `playwright` |
  | `monitor-search` | `app` | `develop` | `glab` | `npm test {arquivo}` | `none` |
  | `gov-open-data` | `app` | `develop` | `glab` | `npm test {arquivo}` | `none` |
  | `official-diaries` | `.` | `develop` | `glab` | `pytest {arquivo}` | `none` |
  | `nomos-tldr` | `.` | `main` | `gh` | `npx jest {arquivo}` | `none` |

- **`qa_mode` restrito a `http | playwright | none`.** `serve` e `health` obrigatórios se e somente se `qa_mode != none`.
- **A suíte de testes inteira do repo-alvo nunca é invocada.** Os testes rodam um alvo por vez, derivados do diff. Estourar memória nos repos de backend é a falha que essa regra existe para impedir.
- **O worktree só é removido no outcome `mr_aberto`.** Qualquer outro outcome preserva.
- **A branch vem do `gitBranchName` da issue, nunca inventada.** Nenhuma função em E3 deriva nome de branch de título, id ou data.
- **Commits em Conventional Commits** (`<tipo>(<escopo>): <descrição>`), como os já existentes no repo.
- **`uv run pytest` fica verde numa máquina sem `/home/victor/nomos`.** Tudo que exige os repos reais é marcado `requires_nomos` e pulado.

## Decisões que estendem a spec

Sete pontos onde as tasks do GitHub eram omissas e este plano fixa uma escolha. Estão aqui para não passarem despercebidos na revisão.

1. **`nomos_root` é campo do registry, não constante.** A spec fixa `/home/victor/nomos/<repo>`. Hardcodar isso torna `prepare_workspace` e o ciclo de vida do worktree intestáveis sem a máquina do Victor. Com `nomos_root` no YAML, o teste aponta para `tmp_path` e exercita git de verdade. `worktrees_root` é opcional e cai em `<nomos_root>/.worktrees`, exatamente o caminho da spec.

2. **Comandos do registry são um comando só, sem operador de shell.** `run_command` usa `shlex.split`, não `shell=True`: um registry é dado de configuração, e `shell=True` transformaria uma linha de YAML em execução arbitrária no mesmo processo que roda com `bypassPermissions`. O carregador rejeita `&&`, `||`, `|`, `;`, `>`, `<`, `` ` `` e `$(` **no boot**. Onde um repo precisaria de `cd app && npm ci`, quem resolve é o campo `root`.

3. **`test_patterns` entra no schema.** A task #24 pede o mapeamento arquivo-fonte → arquivo-de-teste coberto por teste, mas o mapeamento é diferente em cada repo (`.spec.ts` do Nest, `.test.tsx` do CRA, `test_*.py` do pytest). Deixá-lo em código faria o sexto repo custar código, que é justamente o que o épico existe para evitar. Fica no YAML, com os placeholders `{dir}` e `{stem}`.

4. **`health` precisa conter `{port}`.** A porta é alocada dinamicamente (invariante 2 da spec). Um `health` com porta fixa passaria na validação e falharia no run. `serve` pode conter `{port}` e não é obrigado a — alguns servidores leem a porta do ambiente.

5. **`git worktree remove` usa `--force`.** Sem `--force`, o git recusa remover um worktree com arquivos não rastreados, e todo worktree nosso tem `node_modules/` e o `.env` copiado. A remoção só acontece em `mr_aberto`, quando tudo já foi commitado e empurrado — é o único outcome em que não há nada a perder. Em qualquer outro outcome não se remove nada, então `--force` nunca alcança trabalho não salvo.

6. **`git fetch` e `install` têm retry com backoff; o resto não.** A spec classifica rede e `install` instável como transiente com no máximo 3 tentativas dentro do nó. Os demais passos (worktree em branch errada, `copy_untracked` ausente, comando inexistente) são determinísticos e falham de primeira.

7. **`run_repo_gates` para no primeiro comando que falha.** A spec manda executar "na ordem"; rodar `lint` depois de o `build` quebrar produz ruído que vai virar contexto do implementador na próxima tentativa. O `GateReport` carrega os resultados até a falha, inclusive a saída de quem falhou.

## Bloqueio conhecido: a Task 2 exige a máquina do operador

A task [#22](https://github.com/victordantas1/graph-agent/issues/22) é investigação sobre os 6 repositórios em `/home/victor/nomos`. **Nenhum deles está acessível no container desta sessão** (`/home/victor` não existe) e nenhum está no escopo de repositórios do GitHub desta sessão.

O plano trata isso de frente, sem fingir que verificou:

- A Task 2 preenche `config/repos.yaml` com **os valores que a spec autoriza** (root, base, forge, template de teste, `qa_mode` — a tabela acima é normativa) e com valores **inferidos** para `install`, `build`, `lint`, `format_check`, `copy_untracked`, `serve` e `health`.
- Todo repo cujos comandos não foram executados carrega `notas` começando por `NAO VERIFICADO`. É o campo que o critério de aceite pede ("divergências registradas no próprio YAML") e é o que impede o valor inferido de passar por verificado.
- Os testes que só a máquina do operador pode rodar ficam sob a marca `requires_nomos` e são pulados em qualquer outro lugar. Rodá-los em `/home/victor/nomos` é o passo final da Task 2 e o único que troca `NAO VERIFICADO` por `verificado em AAAA-MM-DD`.

A Task 2 fica, portanto, **parcialmente entregue** ao fim deste plano em qualquer ambiente que não seja a máquina do Victor. As Tasks 1, 3, 4 e 5 fecham por completo, porque todas são testadas contra fixtures de git em `tmp_path`.

## File Structure

| arquivo | responsabilidade |
|---|---|
| `pyproject.toml` (modificar) | `pyyaml`, marca `requires_nomos` |
| `src/sentinela_graph/errors.py` (criar) | `SentinelaError`, `RegistryError`, `WorkspaceError`, `GateError` |
| `src/sentinela_graph/registry/__init__.py` (criar) | reexporta `Registry`, `RepoConfig`, `QaMode`, `load_registry` |
| `src/sentinela_graph/registry/models.py` (criar) | `RepoConfig`, `Registry` — schema e invariantes do YAML |
| `src/sentinela_graph/registry/loader.py` (criar) | `load_registry` — YAML → `Registry`, falhando no boot |
| `config/repos.yaml` (criar) | as 6 entradas |
| `src/sentinela_graph/shell.py` (criar) | `CommandResult`, `Runner`, `run_command`, `run_com_retry` |
| `src/sentinela_graph/workspace/__init__.py` (criar) | reexporta `prepare_workspace`, `finalizar_workspace`, `detectar_orfaos` |
| `src/sentinela_graph/workspace/prepare.py` (criar) | `prepare_workspace` idempotente |
| `src/sentinela_graph/workspace/lifecycle.py` (criar) | `finalizar_workspace`, `detectar_orfaos`, `WorktreeInfo` |
| `src/sentinela_graph/gates.py` (criar) | `arquivos_tocados`, `alvos_de_teste`, `run_repo_gates` |
| `tests/conftest.py` (criar) | fixture `nomos` (repo canônico + remoto local), `Gravador`, skip de `requires_nomos` |
| `tests/registry/test_models.py` (criar) | invariantes do schema |
| `tests/registry/test_loader.py` (criar) | erro de boot em registry inválido |
| `tests/registry/test_repos_reais.py` (criar) | as 6 entradas contra a tabela da spec + checagens `requires_nomos` |
| `tests/test_shell.py` (criar) | captura de saída, timeout, comando inexistente, retry |
| `tests/workspace/test_prepare.py` (criar) | idempotência, branch divergente, `copy_untracked`, install |
| `tests/workspace/test_lifecycle.py` (criar) | preservação por outcome, remoção, órfãos |
| `tests/test_gates.py` (criar) | ordem, fail-fast, mapeamento, suíte inteira nunca invocada |

`tests/registry/__init__.py` e `tests/workspace/__init__.py` (vazios) acompanham, como já fazem `tests/models/__init__.py`.

---

## Task 1: Schema e carregador do registry

Fecha a task [#21](https://github.com/victordantas1/graph-agent/issues/21).

**Files:**
- Modify: `pyproject.toml`
- Create: `src/sentinela_graph/errors.py`
- Create: `src/sentinela_graph/registry/__init__.py`, `models.py`, `loader.py`
- Create: `tests/registry/__init__.py` (vazio)
- Test: `tests/registry/test_models.py`, `tests/registry/test_loader.py`

**Interfaces:**
- Consumes: `sentinela_graph.models.routing.Forge` (`Literal["glab", "gh"]`), da E1.
- Produces:
  - `RegistryError(SentinelaError)`, `SentinelaError(Exception)` em `sentinela_graph.errors`
  - `QaMode = Literal["http", "playwright", "none"]`
  - `RepoConfig` com os campos `nome, root, base, forge, install, build, lint, format_check, test, test_patterns, copy_untracked, qa_mode, serve, health, notas`
  - `Registry` com `nomos_root: Path`, `worktrees_root: Path`, `repos: dict[str, RepoConfig]` e os métodos `repo(nome) -> RepoConfig`, `caminho_canonico(nome) -> Path`, `caminho_worktree(nome, branch) -> Path`
  - `load_registry(caminho: Path = Path("config/repos.yaml")) -> Registry`

- [ ] **Step 1: Escrever os testes do schema que falham**

Criar `tests/registry/__init__.py` vazio e `tests/registry/test_models.py`:

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from sentinela_graph.registry import Registry, RepoConfig

BASE = {
    "nome": "nomos-api",
    "root": "app",
    "base": "develop",
    "forge": "glab",
    "install": "npm ci",
    "build": "npm run build",
    "lint": "npm run lint",
    "format_check": "npx prettier --check .",
    "test": "npx jest {arquivo}",
    "test_patterns": ["{dir}/{stem}.spec.ts"],
    "copy_untracked": ["app/.env"],
    "qa_mode": "http",
    "serve": "npm run start:dev",
    "health": "http://127.0.0.1:{port}/health",
    "notas": "NAO VERIFICADO",
}


def repo_config(**over) -> RepoConfig:
    return RepoConfig(**{**BASE, **over})


def test_entrada_valida_carrega():
    cfg = repo_config()
    assert cfg.nome == "nomos-api"
    assert cfg.qa_mode == "http"


def test_qa_mode_fora_do_literal_e_rejeitado():
    with pytest.raises(ValidationError):
        repo_config(qa_mode="curl")


@pytest.mark.parametrize("faltando", ["serve", "health"])
def test_qa_mode_diferente_de_none_exige_serve_e_health(faltando):
    with pytest.raises(ValidationError, match="qa_mode"):
        repo_config(**{faltando: None})


def test_qa_mode_none_proibe_serve_e_health():
    # "sse" na task #21: a implicacao vale nos dois sentidos. Um `serve`
    # orfao e uma promessa que o grafo nunca vai cumprir.
    with pytest.raises(ValidationError, match="qa_mode"):
        repo_config(qa_mode="none")


def test_qa_mode_none_sem_serve_nem_health_carrega():
    cfg = repo_config(qa_mode="none", serve=None, health=None)
    assert cfg.serve is None


def test_health_sem_placeholder_de_porta_e_rejeitado():
    # A porta e alocada dinamicamente; porta fixa passaria aqui e
    # quebraria no serve_app.
    with pytest.raises(ValidationError, match="port"):
        repo_config(health="http://127.0.0.1:3000/health")


def test_test_sem_placeholder_de_arquivo_e_rejeitado():
    with pytest.raises(ValidationError, match="arquivo"):
        repo_config(test="npx jest")


def test_test_pattern_sem_stem_e_rejeitado():
    with pytest.raises(ValidationError, match="stem"):
        repo_config(test_patterns=["{dir}/tudo.spec.ts"])


@pytest.mark.parametrize(
    "comando",
    ["cd app && npm ci", "npm ci; npm run build", "npm ci | tee log", "echo $(whoami)"],
)
def test_comando_com_operador_de_shell_e_rejeitado(comando):
    with pytest.raises(ValidationError, match="operador de shell"):
        repo_config(install=comando)


def test_campo_desconhecido_e_rejeitado():
    # Chave escrita errada no YAML tem que estourar, nao virar default.
    with pytest.raises(ValidationError):
        repo_config(formatcheck="npx prettier --check .")


def test_registry_deriva_worktrees_root_de_nomos_root():
    reg = Registry(nomos_root=Path("/home/victor/nomos"), repos={"nomos-api": repo_config()})
    assert reg.worktrees_root == Path("/home/victor/nomos/.worktrees")


def test_registry_respeita_worktrees_root_explicito():
    reg = Registry(
        nomos_root=Path("/home/victor/nomos"),
        worktrees_root=Path("/scratch/wt"),
        repos={"nomos-api": repo_config()},
    )
    assert reg.worktrees_root == Path("/scratch/wt")


def test_registry_rejeita_chave_diferente_do_nome():
    with pytest.raises(ValidationError, match="nome"):
        Registry(nomos_root=Path("/n"), repos={"nomos-app": repo_config()})


def test_caminhos_derivados():
    reg = Registry(nomos_root=Path("/home/victor/nomos"), repos={"nomos-api": repo_config()})
    assert reg.caminho_canonico("nomos-api") == Path("/home/victor/nomos/nomos-api")
    assert reg.caminho_worktree("nomos-api", "victor/nom-716") == Path(
        "/home/victor/nomos/.worktrees/nomos-api/victor/nom-716"
    )


def test_repo_desconhecido_e_erro_com_a_lista_de_conhecidos():
    from sentinela_graph.errors import RegistryError

    reg = Registry(nomos_root=Path("/n"), repos={"nomos-api": repo_config()})
    with pytest.raises(RegistryError, match="nomos-api"):
        reg.repo("nomos-web")
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/registry/test_models.py -v`
Expected: erro de coleta, `ModuleNotFoundError: No module named 'sentinela_graph.registry'`.

- [ ] **Step 3: Criar `errors.py`**

`src/sentinela_graph/errors.py`:

```python
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
```

`GateError` e `WorkspaceError` só ganham uso nas Tasks 3–5; ficam aqui para o módulo nascer completo.

- [ ] **Step 4: Escrever `registry/models.py`**

```python
"""Schema do registry de repos.

E o que faz 6 repos custarem configuracao e nao codigo: cada entrada diz
onde o repo mora, como se instala, como se valida e se da para exercitar o
app. Toda invariante daqui e checada no boot — nunca no meio do run.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sentinela_graph.errors import RegistryError
from sentinela_graph.models.routing import Forge

QaMode = Literal["http", "playwright", "none"]

# `run_command` usa shlex.split, nunca shell=True: uma linha do YAML nao
# pode virar execucao arbitraria. Onde faria falta um `cd`, existe `root`.
OPERADORES_DE_SHELL = ("&&", "||", "|", ";", ">", "<", "`", "$(")

CAMPOS_DE_COMANDO = ("install", "build", "lint", "format_check", "test", "serve")


class RepoConfig(BaseModel):
    """Uma entrada do registry: um repositorio da Nomos."""

    model_config = ConfigDict(extra="forbid")

    nome: str = Field(min_length=1)
    # Subdiretorio do repo onde os comandos rodam ("app" no nomos-api).
    # Nao confundir com o caminho do repo, que sai de `Registry.nomos_root`.
    root: str = "."
    base: str = Field(min_length=1)
    forge: Forge
    install: str = Field(min_length=1)
    build: str = Field(min_length=1)
    lint: str = Field(min_length=1)
    format_check: str = Field(min_length=1)
    # Template por arquivo: a suite inteira estoura memoria nos backends.
    test: str = Field(min_length=1)
    # Mapeamento arquivo-fonte -> arquivo-de-teste, com {dir} e {stem}.
    test_patterns: list[str] = Field(min_length=1)
    # Relativos a raiz do repo. Sem eles o install nao roda.
    copy_untracked: list[str] = Field(default_factory=list)
    qa_mode: QaMode
    serve: str | None = None
    health: str | None = None
    # Divergencias entre o CLAUDE.md e a realidade moram aqui (task #22).
    notas: str = Field(min_length=1)

    @model_validator(mode="after")
    def _comandos_sao_um_comando_so(self) -> "RepoConfig":
        for campo in CAMPOS_DE_COMANDO:
            valor = getattr(self, campo)
            if valor is None:
                continue
            for operador in OPERADORES_DE_SHELL:
                if operador in valor:
                    raise ValueError(
                        f"{self.nome}.{campo}: operador de shell {operador!r} nao e"
                        " suportado; use o campo 'root' no lugar de 'cd'"
                    )
        return self

    @model_validator(mode="after")
    def _test_recebe_um_arquivo(self) -> "RepoConfig":
        if "{arquivo}" not in self.test:
            raise ValueError(f"{self.nome}.test precisa do placeholder {{arquivo}}")
        for padrao in self.test_patterns:
            if "{stem}" not in padrao:
                raise ValueError(
                    f"{self.nome}.test_patterns: {padrao!r} precisa do placeholder {{stem}}"
                )
        return self

    @model_validator(mode="after")
    def _qa_mode_manda_em_serve_e_health(self) -> "RepoConfig":
        executavel = self.qa_mode != "none"
        tem = self.serve is not None and self.health is not None
        if executavel and not tem:
            raise ValueError(
                f"{self.nome}: qa_mode={self.qa_mode} exige 'serve' e 'health'"
            )
        if not executavel and (self.serve is not None or self.health is not None):
            raise ValueError(
                f"{self.nome}: qa_mode=none nao pode declarar 'serve' nem 'health'"
            )
        if self.health is not None and "{port}" not in self.health:
            raise ValueError(
                f"{self.nome}.health precisa do placeholder {{port}}:"
                " a porta e alocada dinamicamente"
            )
        return self


class Registry(BaseModel):
    """O registry inteiro: onde os repos moram e o que cada um sabe fazer."""

    model_config = ConfigDict(extra="forbid")

    nomos_root: Path
    worktrees_root: Path | None = None
    repos: dict[str, RepoConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def _consolidar(self) -> "Registry":
        if self.worktrees_root is None:
            self.worktrees_root = self.nomos_root / ".worktrees"
        for chave, cfg in self.repos.items():
            if chave != cfg.nome:
                raise ValueError(f"chave {chave!r} nao bate com o nome {cfg.nome!r}")
        return self

    def repo(self, nome: str) -> RepoConfig:
        """Entrada do repo, ou erro nomeando os conhecidos."""
        try:
            return self.repos[nome]
        except KeyError:
            conhecidos = ", ".join(sorted(self.repos))
            raise RegistryError(
                f"repo {nome!r} nao esta no registry; conhecidos: {conhecidos}"
            ) from None

    def caminho_canonico(self, nome: str) -> Path:
        """O clone do humano, de onde saem o fetch e os arquivos nao versionados."""
        return self.nomos_root / nome

    def caminho_worktree(self, nome: str, branch: str) -> Path:
        """`<worktrees_root>/<repo>/<branch>`. Branch com '/' vira subdiretorio."""
        return self.worktrees_root / nome / branch
```

`worktrees_root` é `Path | None` no schema e nunca `None` depois do validador; `caminho_worktree` conta com isso.

- [ ] **Step 5: Criar o `__init__.py` do pacote `registry`**

`src/sentinela_graph/registry/__init__.py`:

```python
"""Registry declarativo dos repos da Nomos."""

from sentinela_graph.registry.loader import CAMINHO_PADRAO, load_registry
from sentinela_graph.registry.models import QaMode, Registry, RepoConfig

__all__ = ["CAMINHO_PADRAO", "QaMode", "Registry", "RepoConfig", "load_registry"]
```

Isso importa `loader`, que só nasce no Step 8. Até lá `tests/registry/test_models.py` continua vermelho por `ModuleNotFoundError` — é esperado, e é o Step 10 que fecha os dois arquivos de teste de uma vez.

- [ ] **Step 6: Escrever os testes do carregador que falham**

`tests/registry/test_loader.py`:

```python
import pytest

from sentinela_graph.errors import RegistryError
from sentinela_graph.registry import load_registry

VALIDO = """
nomos_root: /home/victor/nomos
repos:
  nomos-tldr:
    root: .
    base: main
    forge: gh
    install: npm ci
    build: npm run build
    lint: npm run lint
    format_check: npx prettier --check .
    test: npx jest {arquivo}
    test_patterns: ["{dir}/{stem}.spec.ts"]
    copy_untracked: [.env]
    qa_mode: none
    notas: NAO VERIFICADO
"""


def escrever(tmp_path, texto):
    caminho = tmp_path / "repos.yaml"
    caminho.write_text(texto, encoding="utf-8")
    return caminho


def test_carrega_registry_valido(tmp_path):
    reg = load_registry(escrever(tmp_path, VALIDO))
    assert reg.repo("nomos-tldr").forge == "gh"
    assert reg.nomos_root.name == "nomos"


def test_arquivo_ausente_e_erro_de_boot(tmp_path):
    with pytest.raises(RegistryError, match="nao encontrado"):
        load_registry(tmp_path / "nao-existe.yaml")


def test_yaml_malformado_e_erro_de_boot(tmp_path):
    with pytest.raises(RegistryError, match="YAML invalido"):
        load_registry(escrever(tmp_path, "repos: [: :"))


def test_raiz_que_nao_e_mapa_e_erro_de_boot(tmp_path):
    with pytest.raises(RegistryError, match="mapa"):
        load_registry(escrever(tmp_path, "- nomos-api"))


def test_sem_secao_repos_e_erro_de_boot(tmp_path):
    with pytest.raises(RegistryError, match="repos"):
        load_registry(escrever(tmp_path, "nomos_root: /n\n"))


def test_entrada_que_nao_e_mapa_e_erro_de_boot(tmp_path):
    texto = "nomos_root: /n\nrepos:\n  nomos-api: npm ci\n"
    with pytest.raises(RegistryError):
        load_registry(escrever(tmp_path, texto))


def test_entrada_invalida_e_erro_de_boot_nomeando_o_arquivo(tmp_path):
    quebrado = VALIDO.replace("qa_mode: none", "qa_mode: curl")
    caminho = escrever(tmp_path, quebrado)
    with pytest.raises(RegistryError, match=str(caminho)):
        load_registry(caminho)
```

- [ ] **Step 7: Rodar e ver falhar**

Run: `uv run pytest tests/registry -v`
Expected: `ModuleNotFoundError: No module named 'sentinela_graph.registry.loader'`.

- [ ] **Step 8: Escrever `registry/loader.py`**

```python
"""Carregamento do registry.

Registry invalido para o boot, nao o meio do run: descobrir que o
`format_check` do nomos-api nao existe depois de 40 minutos de implement e
tempo jogado fora.
"""

from pathlib import Path

import yaml
from pydantic import ValidationError

from sentinela_graph.errors import RegistryError
from sentinela_graph.registry.models import Registry, RepoConfig

CAMINHO_PADRAO = Path("config/repos.yaml")


def load_registry(caminho: Path = CAMINHO_PADRAO) -> Registry:
    """Le e valida o YAML. Qualquer problema vira `RegistryError`."""
    caminho = Path(caminho)
    if not caminho.is_file():
        raise RegistryError(f"registry nao encontrado em {caminho}")

    try:
        cru = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    except yaml.YAMLError as erro:
        raise RegistryError(f"{caminho}: YAML invalido: {erro}") from erro

    if not isinstance(cru, dict):
        raise RegistryError(f"{caminho}: a raiz do registry precisa ser um mapa")

    repos_crus = cru.get("repos")
    if not isinstance(repos_crus, dict) or not repos_crus:
        raise RegistryError(f"{caminho}: registry sem a secao 'repos'")

    try:
        repos = {
            nome: RepoConfig(nome=nome, **_corpo(caminho, nome, corpo))
            for nome, corpo in repos_crus.items()
        }
        return Registry(**{**cru, "repos": repos})
    except ValidationError as erro:
        raise RegistryError(f"{caminho}: {erro}") from erro


def _corpo(caminho: Path, nome: str, corpo: object) -> dict:
    if not isinstance(corpo, dict):
        raise RegistryError(f"{caminho}: a entrada {nome!r} precisa ser um mapa")
    if "nome" in corpo:
        raise RegistryError(f"{caminho}: a entrada {nome!r} nao declara 'nome'; a chave e o nome")
    return corpo
```

- [ ] **Step 9: Adicionar `pyyaml` e a marca `requires_nomos` ao `pyproject.toml`**

Em `[project].dependencies`, acrescentar depois de `"pydantic>=2.13,<3",`:

```toml
    "pyyaml>=6.0",
```

E substituir o bloco `[tool.pytest.ini_options]` por:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
markers = [
    "requires_nomos: exige os repos reais em nomos_root; pulado em qualquer outra maquina",
]
```

Depois: `uv sync`

- [ ] **Step 10: Rodar e ver passar**

Run: `uv run pytest tests/registry -v`
Expected: todos passam.

- [ ] **Step 11: Gate e commit**

Run: `uv run ruff check && uv run ruff format --check && uv run pytest`

```bash
git add pyproject.toml uv.lock src/sentinela_graph/errors.py \
        src/sentinela_graph/registry tests/registry
git commit -m "feat(registry): schema e carregador do registry de repos

qa_mode restrito a http|playwright|none, com serve e health obrigatorios se
e somente se qa_mode != none. Comando com operador de shell e recusado no
boot porque run_command usa shlex.split, nao shell=True. Registry invalido
para o boot, nunca o meio do run.

Closes #21"
```

---

## Task 2: As 6 entradas do registry

Fecha a task [#22](https://github.com/victordantas1/graph-agent/issues/22) — **parcialmente fora da máquina do operador**, ver *Bloqueio conhecido*.

**Files:**
- Create: `config/repos.yaml`
- Modify: `tests/conftest.py` (criado aqui; a Task 3 acrescenta a fixture `nomos`)
- Test: `tests/registry/test_repos_reais.py`

**Interfaces:**
- Consumes: `load_registry`, `Registry`, `RepoConfig` da Task 1.
- Produces: `config/repos.yaml` com as 6 entradas; a marca `requires_nomos` operando (pulando quando `nomos_root` não existe).

- [ ] **Step 1: Escrever o teste que falha**

`tests/registry/test_repos_reais.py`:

```python
"""O registry real, checado contra a tabela normativa da spec.

Os testes sem marca rodam em qualquer maquina: so leem o YAML. Os marcados
`requires_nomos` exigem /home/victor/nomos e sao pulados fora dela.
"""

import shlex
import shutil

import pytest

from sentinela_graph.registry import load_registry

REGISTRY = load_registry()

# Spec, secao "Registry de repos". Estes valores sao normativos.
TABELA = {
    "nomos-api": ("app", "develop", "glab", "npx jest {arquivo}", "http"),
    "nomos.pro": (".", "develop", "glab", "yarn test {arquivo}", "playwright"),
    "monitor-search": ("app", "develop", "glab", "npm test {arquivo}", "none"),
    "gov-open-data": ("app", "develop", "glab", "npm test {arquivo}", "none"),
    "official-diaries": (".", "develop", "glab", "pytest {arquivo}", "none"),
    "nomos-tldr": (".", "main", "gh", "npx jest {arquivo}", "none"),
}


def test_os_seis_repos_estao_no_registry():
    assert set(REGISTRY.repos) == set(TABELA)


@pytest.mark.parametrize("nome", sorted(TABELA))
def test_entrada_bate_com_a_tabela_da_spec(nome):
    root, base, forge, teste, qa_mode = TABELA[nome]
    cfg = REGISTRY.repo(nome)
    assert (cfg.root, cfg.base, cfg.forge, cfg.qa_mode) == (root, base, forge, qa_mode)
    # A spec e normativa sobre QUAL runner roda, nao sobre o wrapper
    # (`uv run`) nem sobre flags obrigatorias (--watchAll=false, sem a qual
    # o CRA fica em watch e o gate nunca termina). Entao os tokens da spec
    # tem que aparecer em ordem dentro do template, nao serem iguais a ele.
    assert _e_subsequencia(teste.split(), cfg.test.split()), cfg.test
    assert "{arquivo}" in cfg.test


def _e_subsequencia(esperados: list[str], tokens: list[str]) -> bool:
    restante = iter(tokens)
    return all(token in restante for token in esperados)


@pytest.mark.parametrize("nome", sorted(TABELA))
def test_toda_entrada_declara_o_estado_da_verificacao(nome):
    # Criterio de aceite da #22: divergencias registradas no proprio YAML.
    notas = REGISTRY.repo(nome).notas
    assert notas.startswith("NAO VERIFICADO") or notas.startswith("verificado em ")


def test_so_nomos_api_e_nomos_pro_tem_qa_funcional():
    executaveis = {n for n, c in REGISTRY.repos.items() if c.qa_mode != "none"}
    assert executaveis == {"nomos-api", "nomos.pro"}


@pytest.mark.parametrize("nome", sorted(TABELA))
@pytest.mark.requires_nomos
def test_repo_canonico_existe(nome):
    canonico = REGISTRY.caminho_canonico(nome)
    assert (canonico / ".git").exists(), f"{canonico} nao e um clone git"


@pytest.mark.parametrize("nome", sorted(TABELA))
@pytest.mark.requires_nomos
def test_copy_untracked_existe_de_verdade_no_repo_canonico(nome):
    # Criterio de aceite da #22. Sem esses arquivos o install morre.
    canonico = REGISTRY.caminho_canonico(nome)
    ausentes = [alvo for alvo in REGISTRY.repo(nome).copy_untracked
                if not (canonico / alvo).exists()]
    assert not ausentes, f"{nome}: copy_untracked inexistente: {ausentes}"


@pytest.mark.parametrize("nome", sorted(TABELA))
@pytest.mark.requires_nomos
def test_o_binario_de_cada_comando_existe_no_path(nome):
    cfg = REGISTRY.repo(nome)
    comandos = [cfg.install, cfg.build, cfg.lint, cfg.format_check, cfg.test, cfg.serve]
    faltando = [
        c for c in comandos if c and shutil.which(shlex.split(c)[0]) is None
    ]
    assert not faltando, f"{nome}: binario ausente em {faltando}"
```

E criar `tests/conftest.py` com o skip da marca:

```python
"""Fixtures compartilhadas dos testes.

A marca `requires_nomos` isola tudo que so roda na maquina que tem os 6
repos da Nomos clonados. Em qualquer outro lugar, pula — a suite tem que
ficar verde num container limpo.
"""

import pytest

from sentinela_graph.registry import load_registry


def pytest_runtest_setup(item: pytest.Item) -> None:
    if "requires_nomos" not in item.keywords:
        return
    raiz = load_registry().nomos_root
    if not raiz.is_dir():
        pytest.skip(f"exige os repos reais em {raiz}")
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/registry/test_repos_reais.py -v`
Expected: erro de coleta, `RegistryError: registry nao encontrado em config/repos.yaml`.

- [ ] **Step 3: Escrever `config/repos.yaml`**

Os campos `root`, `base`, `forge`, `test` e `qa_mode` vêm da tabela normativa da spec. Os demais são **inferidos** e ficam marcados como tal em `notas` até o Step 6 rodar na máquina do operador.

```yaml
# Registry dos repos da Nomos.
#
# root/base/forge/test/qa_mode vem da spec
# (docs/superpowers/specs/2026-08-11-graph-of-agents-design.md, secao
# "Registry de repos") e sao normativos.
#
# install/build/lint/format_check/copy_untracked/serve/health so valem
# depois de executados no repo canonico. Ate la, `notas` comeca com
# "NAO VERIFICADO". Ver docs/superpowers/plans/2026-08-13-e3-registry-de-repos-e-worktree.md
# Task 2, Step 6.

nomos_root: /home/victor/nomos

repos:
  nomos-api:
    root: app
    base: develop
    forge: glab
    install: npm ci
    build: npm run build
    lint: npm run lint
    format_check: npx prettier --check .
    test: npx jest {arquivo}
    test_patterns:
      - "{dir}/{stem}.spec.ts"
      - "{dir}/__tests__/{stem}.spec.ts"
      - "{dir}/{stem}.spec.js"
    copy_untracked:
      - app/.env
    qa_mode: http
    serve: npm run start:dev
    health: http://127.0.0.1:{port}/health
    notas: >-
      NAO VERIFICADO. Comandos inferidos do CLAUDE.md, sem execucao.
      Pendente: o nome real do service account JSON em app/ (a spec cita
      service accounts untracked circulando em nomos-api/app/) e a rota
      real de healthcheck.

  nomos.pro:
    root: .
    base: develop
    forge: glab
    install: yarn install --frozen-lockfile
    build: yarn build
    lint: yarn lint
    format_check: npx prettier --check src
    # CRA roda em watch por padrao; sem --watchAll=false o gate nunca termina.
    test: yarn test --watchAll=false {arquivo}
    test_patterns:
      - "{dir}/{stem}.test.tsx"
      - "{dir}/{stem}.test.ts"
      - "{dir}/{stem}.spec.tsx"
      - "{dir}/__tests__/{stem}.test.tsx"
    copy_untracked:
      - .env
    qa_mode: playwright
    serve: yarn start
    health: http://127.0.0.1:{port}/
    notas: >-
      NAO VERIFICADO. CRA com react-app-rewired; confirmar se `yarn start`
      respeita PORT e se existe script `lint`.

  monitor-search:
    root: app
    base: develop
    forge: glab
    install: npm ci
    build: npm run build
    lint: npm run lint
    format_check: npx prettier --check .
    test: npm test {arquivo}
    test_patterns:
      - "{dir}/{stem}.test.js"
      - "{dir}/__tests__/{stem}.test.js"
      - "{dir}/{stem}.spec.js"
    copy_untracked:
      - app/.env
    qa_mode: none
    notas: >-
      NAO VERIFICADO. Cloud Function com handler CloudEvent
      (exports.entrypoint); sem endpoint, qa_mode=none por decisao da spec.
      Confirmar se existe script `build`.

  gov-open-data:
    root: app
    base: develop
    forge: glab
    install: npm ci
    build: npm run build
    lint: npm run lint
    format_check: npx prettier --check .
    test: npm test {arquivo}
    test_patterns:
      - "{dir}/{stem}.test.js"
      - "{dir}/__tests__/{stem}.test.js"
      - "{dir}/{stem}.spec.js"
    copy_untracked:
      - app/.env
    qa_mode: none
    notas: >-
      NAO VERIFICADO. Mesma forma do monitor-search. Confirmar service
      account JSON usado pelas credenciais do GCP.

  official-diaries:
    root: .
    base: develop
    forge: glab
    install: uv sync
    build: uv run python -c pass
    lint: uv run ruff check
    format_check: uv run ruff format --check .
    test: uv run pytest {arquivo}
    test_patterns:
      - "{dir}/test_{stem}.py"
      - "tests/test_{stem}.py"
    copy_untracked:
      - .env
    qa_mode: none
    notas: >-
      NAO VERIFICADO. Python functions_framework.http, mas o CLAUDE.md do
      repo declara "desenvolvimento: nao existe - e fica assim, por decisao
      do time", entao qa_mode=none. `build` e um no-op porque nao ha etapa
      de build; confirmar se o repo usa uv ou requirements.txt.

  nomos-tldr:
    root: .
    base: main
    forge: gh
    install: npm ci
    build: npm run build
    lint: npm run lint
    format_check: npx prettier --check .
    test: npx jest {arquivo}
    test_patterns:
      - "{dir}/{stem}.spec.ts"
      - "{dir}/{stem}.test.ts"
      - "{dir}/__tests__/{stem}.spec.ts"
    copy_untracked:
      - .env
    qa_mode: none
    notas: >-
      NAO VERIFICADO. Unico repo em main e na forja gh. Tem
      docker-compose.yml, mas entra na v1 sem QA funcional por decisao da
      spec.
```

Atenção ao `official-diaries.build`: `uv run python -c pass` é um no-op deliberado. O schema exige `build` não vazio, e um repo sem etapa de build precisa de algo que saia com 0 sem efeito colateral.

- [ ] **Step 4: Rodar e ver passar (fora da máquina do operador)**

Run: `uv run pytest tests/registry/test_repos_reais.py -v`
Expected: os quatro primeiros testes passam; os `requires_nomos` aparecem como `SKIPPED (exige os repos reais em /home/victor/nomos)`.

- [ ] **Step 5: Gate e commit**

Run: `uv run ruff check && uv run ruff format --check && uv run pytest`

```bash
git add config/repos.yaml tests/conftest.py tests/registry/test_repos_reais.py
git commit -m "feat(registry): as 6 entradas do registry da Nomos

root, base, forge, test e qa_mode vem da tabela normativa da spec e estao
cobertos por teste. Os comandos de install/build/lint/format e o
copy_untracked ainda nao foram executados no repo canonico: cada entrada
declara isso em notas, e as checagens que exigem /home/victor/nomos ficam
sob a marca requires_nomos.

Refs #22"
```

- [ ] **Step 6: Verificação na máquina do operador (`/home/victor/nomos` presente)**

Este step **não roda no container**. Executá-lo é o que fecha a #22.

Para cada um dos 6 repos:

```bash
cd /home/victor/nomos/<repo>
cat CLAUDE.md
cat package.json | head -40        # ou pyproject.toml no official-diaries
git status --porcelain --ignored=no --untracked-files=all | grep '^??'
```

O `git status` é o que revela o `copy_untracked` real: todo arquivo não rastreado e não ignorado que o install ou o runtime precisa (`.env`, service accounts `.json`). Registrar cada um no YAML com o caminho relativo à raiz do repo.

Depois, confirmar que cada comando realmente existe e sai com 0:

```bash
cd /home/victor/nomos/<repo>/<root>
npm run build && npm run lint && npx prettier --check .
```

Então, no `config/repos.yaml`:

- corrigir todo comando que divergiu;
- **registrar a divergência em `notas`** — é o critério de aceite, e é a informação que vale mais que o comando corrigido ("o CLAUDE.md manda `npm run test:unit`, mas o script não existe; o real é `npx jest`");
- trocar o prefixo `NAO VERIFICADO.` por `verificado em AAAA-MM-DD.` em cada repo cujos comandos foram executados.

Finalmente:

```bash
uv run pytest tests/registry -v -m requires_nomos
uv run pytest
git add config/repos.yaml
git commit -m "fix(registry): comandos reais dos 6 repos, verificados no canonico

Closes #22"
```

---

## Task 3: `prepare_workspace` idempotente

Fecha a task [#23](https://github.com/victordantas1/graph-agent/issues/23).

**Files:**
- Create: `src/sentinela_graph/shell.py`
- Create: `src/sentinela_graph/workspace/__init__.py`, `prepare.py`
- Create: `tests/workspace/__init__.py` (vazio)
- Modify: `tests/conftest.py` (acrescenta a fixture `nomos` e o `Gravador`)
- Test: `tests/test_shell.py`, `tests/workspace/test_prepare.py`

**Interfaces:**
- Consumes: `Registry`, `RepoConfig` (Task 1); `Workspace` (E1, `sentinela_graph.models.workspace`); `WorkspaceError` (Task 1).
- Produces:
  - `CommandResult(comando: str, exit_code: int, saida: str, timed_out: bool)` com `.passou: bool`
  - `Runner` (Protocol), `run_command(comando, cwd, timeout=TIMEOUT_PADRAO) -> CommandResult`, `TIMEOUT_PADRAO = 900`
  - `run_com_retry(comando, cwd, *, tentativas=3, espera=2.0, run=run_command) -> CommandResult`
  - `prepare_workspace(registry, repo: RepoConfig, branch: str, *, run=run_command, espera=2.0) -> Workspace`

- [ ] **Step 1: Escrever os testes do shell que falham**

`tests/test_shell.py`:

```python
import pytest

from sentinela_graph.shell import CommandResult, run_com_retry, run_command


def test_captura_stdout_e_stderr_juntos(tmp_path):
    r = run_command("python -c import sys;sys.stderr.write('erro');print('ok')", tmp_path)
    assert r.passou
    assert "ok" in r.saida and "erro" in r.saida


def test_exit_code_nao_zero_nao_passa(tmp_path):
    r = run_command("python -c raise SystemExit(3)", tmp_path)
    assert not r.passou
    assert r.exit_code == 3


def test_comando_inexistente_nao_levanta(tmp_path):
    # Erro deterministico: vira resultado, e quem decide o que fazer e o no.
    r = run_command("comando-que-nao-existe-1234", tmp_path)
    assert not r.passou
    assert r.exit_code == 127


def test_timeout_marca_timed_out(tmp_path):
    r = run_command("python -c import time;time.sleep(5)", tmp_path, timeout=1)
    assert r.timed_out
    assert not r.passou


def test_roda_no_cwd_pedido(tmp_path):
    (tmp_path / "marcador.txt").write_text("x")
    r = run_command("python -c import os;print(os.listdir())", tmp_path)
    assert "marcador.txt" in r.saida


def test_retry_desiste_depois_das_tentativas():
    chamadas = []

    def falha(comando, cwd, timeout=None):
        chamadas.append(comando)
        return CommandResult(comando, 1, "rede caiu")

    r = run_com_retry("git fetch origin", None, tentativas=3, espera=0, run=falha)
    assert not r.passou
    assert len(chamadas) == 3


def test_retry_para_no_primeiro_sucesso():
    respostas = [CommandResult("x", 1, "rede"), CommandResult("x", 0, "ok")]

    def instavel(comando, cwd, timeout=None):
        return respostas.pop(0)

    r = run_com_retry("x", None, tentativas=3, espera=0, run=instavel)
    assert r.passou
    assert respostas == []
```

O `python -c import sys;...` sem aspas é intencional: `shlex.split` entrega `import sys;sys.stderr.write('erro');print('ok')` como um único argumento porque não há espaço depois dos `;`. Mantenha os comandos sem espaços dentro do `-c`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_shell.py -v`
Expected: `ModuleNotFoundError: No module named 'sentinela_graph.shell'`.

- [ ] **Step 3: Escrever `shell.py`**

```python
"""Execucao de comando externo, com saida capturada e timeout.

Todo comando do registry passa por aqui. E o ponto onde o timeout vira erro
deterministico e onde o retry transiente da spec acontece.
"""

import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

TIMEOUT_PADRAO = 900


@dataclass(frozen=True)
class CommandResult:
    """O que sobrou de um comando: codigo, saida unificada e se estourou."""

    comando: str
    exit_code: int
    saida: str = ""
    timed_out: bool = False

    @property
    def passou(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class Runner(Protocol):
    """Assinatura que todo no injeta nos testes no lugar do subprocess."""

    def __call__(
        self, comando: str, cwd: Path | None, timeout: int = TIMEOUT_PADRAO
    ) -> CommandResult: ...


def run_command(
    comando: str, cwd: Path | None, timeout: int = TIMEOUT_PADRAO
) -> CommandResult:
    """Roda `comando` em `cwd`, com stdout e stderr unificados.

    Sem `shell=True`: o registry e configuracao, nao script. O carregador ja
    recusou qualquer operador de shell.
    """
    try:
        proc = subprocess.run(
            shlex.split(comando),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as erro:
        # Comando inexistente e deterministico: retry so gastaria tempo.
        return CommandResult(comando, exit_code=127, saida=str(erro))
    except subprocess.TimeoutExpired as erro:
        return CommandResult(
            comando, exit_code=124, saida=_texto(erro.output), timed_out=True
        )
    return CommandResult(comando, proc.returncode, proc.stdout + proc.stderr)


def run_com_retry(
    comando: str,
    cwd: Path | None,
    *,
    tentativas: int = 3,
    espera: float = 2.0,
    run: Runner = run_command,
    timeout: int = TIMEOUT_PADRAO,
) -> CommandResult:
    """Retry com backoff exponencial, para falha transiente (rede, install).

    Nao consome tentativa do ciclo de correcao: o implementador nao errou.
    """
    resultado = run(comando, cwd, timeout)
    for n in range(1, tentativas):
        if resultado.passou:
            return resultado
        if espera:
            time.sleep(espera * 2 ** (n - 1))
        resultado = run(comando, cwd, timeout)
    return resultado


def _texto(saida: str | bytes | None) -> str:
    if saida is None:
        return ""
    return saida.decode(errors="replace") if isinstance(saida, bytes) else saida
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/test_shell.py -v`
Expected: todos passam.

- [ ] **Step 5: Acrescentar a fixture `nomos` ao `tests/conftest.py`**

Substituir `tests/conftest.py` inteiro — os imports precisam ficar no topo, senão o ruff acusa `E402`. O `pytest_runtest_setup` da Task 2 continua igual, no fim do arquivo:

```python
"""Fixtures compartilhadas dos testes.

A marca `requires_nomos` isola tudo que so roda na maquina que tem os 6
repos da Nomos clonados. Em qualquer outro lugar, pula — a suite tem que
ficar verde num container limpo.
"""

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from sentinela_graph.registry import Registry, RepoConfig, load_registry
from sentinela_graph.shell import TIMEOUT_PADRAO, CommandResult

REPO_BASE = {
    "root": "app",
    "base": "develop",
    "forge": "glab",
    "install": "python -c pass",
    "build": "python -c pass",
    "lint": "python -c pass",
    "format_check": "python -c pass",
    "test": "python -c pass {arquivo}",
    "test_patterns": ["{dir}/{stem}.spec.ts", "{dir}/__tests__/{stem}.spec.ts"],
    "copy_untracked": ["app/.env"],
    "qa_mode": "none",
    "notas": "fixture",
}


def repo_config(nome: str = "nomos-api", **over) -> RepoConfig:
    """RepoConfig de teste, com comandos que sempre saem com 0."""
    return RepoConfig(nome=nome, **{**REPO_BASE, **over})


class Gravador:
    """Runner falso que grava a ordem exata dos comandos.

    E como se prova que a suite inteira nunca e invocada e que os gates
    rodam na ordem da spec.
    """

    def __init__(self, respostas: dict[str, tuple[int, str]] | None = None) -> None:
        self.comandos: list[str] = []
        self.cwds: list[Path | None] = []
        self.respostas = respostas or {}

    def __call__(
        self, comando: str, cwd: Path | None, timeout: int = TIMEOUT_PADRAO
    ) -> CommandResult:
        self.comandos.append(comando)
        self.cwds.append(cwd)
        exit_code, saida = self.respostas.get(comando, (0, ""))
        return CommandResult(comando, exit_code, saida)


def git(*args: str, cwd: Path) -> str:
    """git de verdade nos testes: o comportamento de worktree nao se dubla."""
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return proc.stdout


@dataclass
class FakeNomos:
    """Um /home/victor/nomos falso: remoto local + clone canonico."""

    raiz: Path
    registry: Registry
    repos: list[str] = field(default_factory=list)

    def canonico(self, nome: str = "nomos-api") -> Path:
        return self.registry.caminho_canonico(nome)


@pytest.fixture
def nomos(tmp_path: Path) -> FakeNomos:
    """Repo `nomos-api` com remoto local, branch develop e um .env untracked."""
    nome = "nomos-api"
    raiz = tmp_path / "nomos"
    raiz.mkdir()
    remoto = tmp_path / "remoto" / f"{nome}.git"
    remoto.parent.mkdir()
    subprocess.run(
        ["git", "init", "--bare", "-b", "develop", str(remoto)],
        check=True,
        capture_output=True,
    )

    canonico = raiz / nome
    subprocess.run(
        ["git", "clone", str(remoto), str(canonico)], check=True, capture_output=True
    )
    git("config", "user.email", "grafo@nomos.test", cwd=canonico)
    git("config", "user.name", "Grafo", cwd=canonico)
    git("symbolic-ref", "HEAD", "refs/heads/develop", cwd=canonico)

    (canonico / "app").mkdir()
    (canonico / "app" / "src").mkdir()
    (canonico / "app" / "src" / "pedido.ts").write_text("export const pedido = 1;\n")
    (canonico / "app" / "src" / "pedido.spec.ts").write_text("it('x', () => {});\n")
    git("add", "-A", cwd=canonico)
    git("commit", "-m", "chore: base", cwd=canonico)
    git("push", "-u", "origin", "develop", cwd=canonico)

    # Nao versionado: e exatamente o que copy_untracked existe para levar.
    (canonico / "app" / ".env").write_text("SEGREDO=1\n", encoding="utf-8")

    registry = Registry(nomos_root=raiz, repos={nome: repo_config(nome)})
    return FakeNomos(raiz=raiz, registry=registry, repos=[nome])


def pytest_runtest_setup(item: pytest.Item) -> None:
    if "requires_nomos" not in item.keywords:
        return
    raiz = load_registry().nomos_root
    if not raiz.is_dir():
        pytest.skip(f"exige os repos reais em {raiz}")
```

O `git symbolic-ref HEAD` é necessário porque um clone de repositório vazio deixa o `HEAD` apontando para a branch default da configuração local, que pode não ser `develop`.

- [ ] **Step 6: Escrever os testes de `prepare_workspace` que falham**

`tests/workspace/__init__.py` vazio e `tests/workspace/test_prepare.py`:

```python
import pytest

from sentinela_graph.errors import WorkspaceError
from sentinela_graph.shell import CommandResult
from sentinela_graph.workspace import prepare_workspace

BRANCH = "victor/nom-716-corrige-pedido"


def preparar(nomos, branch=BRANCH, **kw):
    return prepare_workspace(
        nomos.registry, nomos.registry.repo("nomos-api"), branch, espera=0, **kw
    )


def test_cria_worktree_na_branch_pedida(nomos):
    ws = preparar(nomos)
    assert ws.worktree_path.is_dir()
    assert ws.branch == BRANCH
    assert (ws.worktree_path / "app" / "src" / "pedido.ts").exists()


def test_worktree_fica_no_caminho_da_spec(nomos):
    ws = preparar(nomos)
    assert ws.worktree_path == nomos.raiz / ".worktrees" / "nomos-api" / BRANCH


def test_app_root_aponta_para_o_root_do_registry(nomos):
    ws = preparar(nomos)
    assert ws.app_root == ws.worktree_path / "app"


def test_a_branch_sai_do_gitBranchName_e_nao_e_inventada(nomos):
    ws = preparar(nomos, branch="victor/nom-999-outra")
    cabeca = (ws.worktree_path / ".git").read_text()
    assert cabeca  # o worktree existe
    assert ws.branch == "victor/nom-999-outra"


def test_copia_os_arquivos_nao_versionados(nomos):
    ws = preparar(nomos)
    assert (ws.worktree_path / "app" / ".env").read_text() == "SEGREDO=1\n"


def test_copy_untracked_ausente_e_erro_deterministico(nomos):
    (nomos.canonico() / "app" / ".env").unlink()
    with pytest.raises(WorkspaceError, match="app/.env"):
        preparar(nomos)


def test_roda_o_install_no_app_root(nomos):
    from tests.conftest import Gravador

    gravador = Gravador()
    ws = preparar(nomos, run=_git_de_verdade_menos(gravador, "python -c pass"))
    assert "python -c pass" in gravador.comandos
    assert gravador.cwds[gravador.comandos.index("python -c pass")] == ws.app_root
    assert ws.install_ok


def test_install_que_falha_e_erro_com_a_saida(nomos):
    def falhando(comando, cwd, timeout=None):
        from sentinela_graph.shell import run_command

        if comando == "python -c pass":
            return CommandResult(comando, 1, "npm ERR! ENOENT")
        return run_command(comando, cwd, timeout or 900)

    with pytest.raises(WorkspaceError, match="npm ERR"):
        preparar(nomos, run=falhando)


def test_rodar_duas_vezes_reaproveita_e_nao_falha(nomos):
    primeira = preparar(nomos)
    marcador = primeira.worktree_path / "app" / "nao-apague.txt"
    marcador.write_text("sobrevivi")

    segunda = preparar(nomos)

    assert segunda.worktree_path == primeira.worktree_path
    assert marcador.read_text() == "sobrevivi"


def test_worktree_em_branch_diferente_e_erro_deterministico(nomos):
    ws = preparar(nomos)
    from tests.conftest import git

    git("checkout", "-b", "outra-branch", cwd=ws.worktree_path)

    with pytest.raises(WorkspaceError, match="outra-branch"):
        preparar(nomos)


def test_worktree_registrado_mas_com_diretorio_sumido_e_recriado(nomos):
    import shutil

    ws = preparar(nomos)
    shutil.rmtree(ws.worktree_path)

    de_novo = preparar(nomos)

    assert de_novo.worktree_path.is_dir()


def test_branch_ja_existente_sem_worktree_e_reaproveitada(nomos):
    from tests.conftest import git

    git("branch", BRANCH, "origin/develop", cwd=nomos.canonico())
    ws = preparar(nomos)
    assert ws.branch == BRANCH


def test_repo_canonico_ausente_e_erro_deterministico(nomos):
    import shutil

    shutil.rmtree(nomos.canonico())
    with pytest.raises(WorkspaceError, match="nao e um repositorio git"):
        preparar(nomos)


def _git_de_verdade_menos(gravador, comando_falso):
    """Grava `comando_falso` e delega o resto ao git real."""
    from sentinela_graph.shell import run_command

    def runner(comando, cwd, timeout=None):
        if comando == comando_falso:
            return gravador(comando, cwd)
        return run_command(comando, cwd, timeout or 900)

    return runner
```

`tests/conftest.py` é importável como `tests.conftest` porque `tests/__init__.py` já existe.

- [ ] **Step 7: Rodar e ver falhar**

Run: `uv run pytest tests/workspace/test_prepare.py -v`
Expected: `ModuleNotFoundError: No module named 'sentinela_graph.workspace'`.

- [ ] **Step 8: Escrever `workspace/prepare.py`**

```python
"""Preparo do worktree isolado de uma issue.

Idempotente por obrigacao: sem isso o `--resume` quebraria no primeiro no.
Worktree existente na branch esperada e reaproveitado; em branch diferente,
e erro deterministico — nunca se adivinha qual das duas o humano queria.
"""

import shutil
from pathlib import Path

from sentinela_graph.errors import WorkspaceError
from sentinela_graph.models.workspace import Workspace
from sentinela_graph.registry import Registry, RepoConfig
from sentinela_graph.shell import Runner, run_com_retry, run_command


def prepare_workspace(
    registry: Registry,
    repo: RepoConfig,
    branch: str,
    *,
    run: Runner = run_command,
    espera: float = 2.0,
) -> Workspace:
    """Cria (ou reaproveita) o worktree de `branch`, abastece e instala.

    `branch` e o `gitBranchName` da issue. Nunca derivado de titulo ou id.
    """
    canonico = registry.caminho_canonico(repo.nome)
    if not (canonico / ".git").exists():
        raise WorkspaceError(f"{canonico} nao e um repositorio git")

    worktree = registry.caminho_worktree(repo.nome, branch)

    fetch = run_com_retry("git fetch origin --prune", canonico, espera=espera, run=run)
    if not fetch.passou:
        raise WorkspaceError(f"git fetch origin falhou em {canonico}:\n{fetch.saida}")

    _garantir_worktree(canonico, worktree, branch, repo.base, run)
    _copiar_nao_versionados(canonico, worktree, repo)

    app_root = worktree / repo.root
    if not app_root.is_dir():
        raise WorkspaceError(f"root {repo.root!r} nao existe em {worktree}")

    install = run_com_retry(repo.install, app_root, espera=espera, run=run)
    if not install.passou:
        raise WorkspaceError(f"install falhou em {app_root}:\n{install.saida}")

    return Workspace(
        worktree_path=worktree, branch=branch, app_root=app_root, install_ok=True
    )


def _garantir_worktree(
    canonico: Path, worktree: Path, branch: str, base: str, run: Runner
) -> None:
    if worktree.is_dir():
        atual = _branch_do_worktree(worktree, run)
        if atual == branch:
            return  # reaproveita: e o que sustenta o --resume
        raise WorkspaceError(
            f"worktree {worktree} esta na branch {atual!r}, esperada {branch!r};"
            " resolva a mao antes de rodar de novo"
        )

    # Diretorio sumiu mas o registro ficou: sem prune, o `add` recusa.
    run("git worktree prune", canonico)

    worktree.parent.mkdir(parents=True, exist_ok=True)
    if _branch_existe(canonico, branch, run):
        comando = f"git worktree add {worktree} {branch}"
    else:
        comando = f"git worktree add {worktree} -b {branch} origin/{base}"

    resultado = run(comando, canonico)
    if not resultado.passou:
        raise WorkspaceError(f"nao foi possivel criar o worktree:\n{resultado.saida}")


def _branch_do_worktree(worktree: Path, run: Runner) -> str:
    resultado = run("git symbolic-ref --short HEAD", worktree)
    if not resultado.passou:
        raise WorkspaceError(
            f"worktree {worktree} nao esta numa branch (HEAD destacado):\n{resultado.saida}"
        )
    return resultado.saida.strip()


def _branch_existe(canonico: Path, branch: str, run: Runner) -> bool:
    return run(f"git show-ref --verify --quiet refs/heads/{branch}", canonico).passou


def _copiar_nao_versionados(canonico: Path, worktree: Path, repo: RepoConfig) -> None:
    """Leva `.env` e service accounts do clone do humano para o worktree.

    Ausencia e erro deterministico: sem esses arquivos nada roda, e
    descobrir isso no meio do install so custa tempo.
    """
    for relativo in repo.copy_untracked:
        origem = canonico / relativo
        if not origem.is_file():
            raise WorkspaceError(
                f"{repo.nome}: copy_untracked {relativo!r} nao existe em {canonico}"
            )
        destino = worktree / relativo
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origem, destino)
```

`src/sentinela_graph/workspace/__init__.py`:

```python
"""Ciclo de vida do worktree isolado de cada issue."""

from sentinela_graph.workspace.prepare import prepare_workspace

__all__ = ["prepare_workspace"]
```

Caminhos com espaço quebrariam o `shlex.split` do `git worktree add {worktree}`. Não é caso real (`nomos_root` e nomes de branch do Linear não têm espaço) e um `shlex.quote` aqui esconderia o problema em vez de resolvê-lo; se um dia aparecer, o comando falha alto.

- [ ] **Step 9: Rodar e ver passar**

Run: `uv run pytest tests/workspace/test_prepare.py -v`
Expected: todos passam.

- [ ] **Step 10: Gate e commit**

Run: `uv run ruff check && uv run ruff format --check && uv run pytest`

```bash
git add src/sentinela_graph/shell.py src/sentinela_graph/workspace \
        tests/conftest.py tests/test_shell.py tests/workspace
git commit -m "feat(workspace): prepare_workspace idempotente

Worktree existente na branch esperada e reaproveitado, o que e o que
sustenta o --resume; em branch diferente e erro deterministico. A branch
vem do gitBranchName da issue. fetch e install tem retry transiente;
copy_untracked ausente falha de primeira.

Closes #23"
```

---

## Task 4: `repo_gates` sobre os arquivos tocados

Fecha a task [#24](https://github.com/victordantas1/graph-agent/issues/24).

**Files:**
- Create: `src/sentinela_graph/gates.py`
- Test: `tests/test_gates.py`

**Interfaces:**
- Consumes: `RepoConfig` (Task 1), `Workspace` (E1), `GateReport`/`GateResult` (E1, `sentinela_graph.models.execution`), `Runner`/`run_command` (Task 3), `GateError` (Task 1).
- Produces:
  - `arquivos_tocados(repo, worktree: Path, *, run=run_command) -> list[str]`
  - `alvos_de_teste(repo, worktree: Path, tocados: list[str]) -> list[str]`
  - `run_repo_gates(repo, workspace: Workspace, *, run=run_command) -> GateReport`

- [ ] **Step 1: Escrever os testes que falham**

`tests/test_gates.py`:

```python
from pathlib import Path

import pytest

from sentinela_graph.errors import GateError
from sentinela_graph.gates import alvos_de_teste, arquivos_tocados, run_repo_gates
from sentinela_graph.models.workspace import Workspace
from tests.conftest import Gravador, repo_config

DIFF = "git diff --name-only --diff-filter=d origin/develop...HEAD"


def montar_worktree(tmp_path: Path, *arquivos: str) -> Path:
    for arquivo in arquivos:
        alvo = tmp_path / arquivo
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text("x")
    return tmp_path


def workspace_de(worktree: Path, root: str = "app") -> Workspace:
    return Workspace(
        worktree_path=worktree,
        branch="victor/nom-716",
        app_root=worktree / root,
        install_ok=True,
    )


# --- derivacao do diff -------------------------------------------------


def test_arquivos_tocados_sai_do_diff_contra_a_base(tmp_path):
    gravador = Gravador({DIFF: (0, "app/src/pedido.ts\napp/src/nota.ts\n")})
    tocados = arquivos_tocados(repo_config(), tmp_path, run=gravador)
    assert tocados == ["app/src/pedido.ts", "app/src/nota.ts"]
    assert gravador.comandos == [DIFF]


def test_diff_impossivel_e_gate_error(tmp_path):
    gravador = Gravador({DIFF: (128, "fatal: bad revision")})
    with pytest.raises(GateError, match="bad revision"):
        arquivos_tocados(repo_config(), tmp_path, run=gravador)


# --- mapeamento fonte -> teste ----------------------------------------


def test_fonte_mapeia_para_o_teste_irmao(tmp_path):
    wt = montar_worktree(tmp_path, "app/src/pedido.ts", "app/src/pedido.spec.ts")
    assert alvos_de_teste(repo_config(), wt, ["app/src/pedido.ts"]) == [
        "src/pedido.spec.ts"
    ]


def test_alvo_e_relativo_ao_root_e_nao_a_raiz_do_repo(tmp_path):
    # `npx jest` roda dentro de app/; passar "app/src/..." nao acharia nada.
    wt = montar_worktree(tmp_path, "app/src/pedido.spec.ts")
    assert alvos_de_teste(repo_config(), wt, ["app/src/pedido.spec.ts"]) == [
        "src/pedido.spec.ts"
    ]


def test_arquivo_de_teste_tocado_vira_alvo_de_si_mesmo(tmp_path):
    wt = montar_worktree(tmp_path, "app/src/pedido.spec.ts")
    assert alvos_de_teste(repo_config(), wt, ["app/src/pedido.spec.ts"]) == [
        "src/pedido.spec.ts"
    ]


def test_padrao_em_subdiretorio_de_testes_e_considerado(tmp_path):
    wt = montar_worktree(
        tmp_path, "app/src/nota.ts", "app/src/__tests__/nota.spec.ts"
    )
    assert alvos_de_teste(repo_config(), wt, ["app/src/nota.ts"]) == [
        "src/__tests__/nota.spec.ts"
    ]


def test_fonte_sem_teste_correspondente_nao_gera_alvo(tmp_path):
    wt = montar_worktree(tmp_path, "app/src/sem-teste.ts")
    assert alvos_de_teste(repo_config(), wt, ["app/src/sem-teste.ts"]) == []


def test_arquivo_fora_do_root_e_ignorado(tmp_path):
    wt = montar_worktree(tmp_path, "README.md", "app/src/pedido.spec.ts")
    assert alvos_de_teste(repo_config(), wt, ["README.md"]) == []


def test_alvos_nao_repetem(tmp_path):
    wt = montar_worktree(
        tmp_path, "app/src/pedido.ts", "app/src/pedido.spec.ts"
    )
    tocados = ["app/src/pedido.ts", "app/src/pedido.spec.ts"]
    assert alvos_de_teste(repo_config(), wt, tocados) == ["src/pedido.spec.ts"]


def test_padrao_de_python_tambem_funciona(tmp_path):
    repo = repo_config(
        root=".",
        test="pytest {arquivo}",
        test_patterns=["{dir}/test_{stem}.py", "tests/test_{stem}.py"],
    )
    wt = montar_worktree(tmp_path, "diarios/parser.py", "tests/test_parser.py")
    assert alvos_de_teste(repo, wt, ["diarios/parser.py"]) == ["tests/test_parser.py"]


# --- execucao dos gates ------------------------------------------------


def test_gates_rodam_na_ordem_da_spec(tmp_path):
    wt = montar_worktree(tmp_path, "app/src/pedido.ts", "app/src/pedido.spec.ts")
    repo = repo_config(
        build="npm run build",
        lint="npm run lint",
        format_check="npx prettier --check .",
        test="npx jest {arquivo}",
    )
    gravador = Gravador({DIFF: (0, "app/src/pedido.ts\n")})

    relatorio = run_repo_gates(repo, workspace_de(wt), run=gravador)

    assert [c for c in gravador.comandos if c != DIFF] == [
        "npm run build",
        "npm run lint",
        "npx prettier --check .",
        "npx jest src/pedido.spec.ts",
    ]
    assert relatorio.passou


def test_a_suite_inteira_nunca_e_invocada(tmp_path):
    # O criterio de aceite da #24: rodar `npx jest` pelado estoura memoria
    # nos repos de backend.
    wt = montar_worktree(tmp_path, "app/src/a.ts", "app/src/a.spec.ts", "app/src/b.spec.ts")
    repo = repo_config(test="npx jest {arquivo}")
    gravador = Gravador({DIFF: (0, "app/src/a.ts\n")})

    run_repo_gates(repo, workspace_de(wt), run=gravador)

    assert "npx jest" not in gravador.comandos
    assert "npx jest src/b.spec.ts" not in gravador.comandos
    assert "npx jest src/a.spec.ts" in gravador.comandos


def test_sem_arquivo_tocado_nenhum_teste_roda(tmp_path):
    wt = montar_worktree(tmp_path, "app/src/pedido.spec.ts")
    repo = repo_config(test="npx jest {arquivo}")
    gravador = Gravador({DIFF: (0, "")})

    relatorio = run_repo_gates(repo, workspace_de(wt), run=gravador)

    assert not [c for c in gravador.comandos if c.startswith("npx jest")]
    assert relatorio.passou  # build, lint e format rodaram e passaram


def test_um_alvo_por_comando(tmp_path):
    wt = montar_worktree(
        tmp_path, "app/src/a.ts", "app/src/a.spec.ts", "app/src/b.ts", "app/src/b.spec.ts"
    )
    repo = repo_config(test="npx jest {arquivo}")
    gravador = Gravador({DIFF: (0, "app/src/a.ts\napp/src/b.ts\n")})

    run_repo_gates(repo, workspace_de(wt), run=gravador)

    testes = [c for c in gravador.comandos if c.startswith("npx jest")]
    assert testes == ["npx jest src/a.spec.ts", "npx jest src/b.spec.ts"]


def test_gates_rodam_no_app_root(tmp_path):
    wt = montar_worktree(tmp_path, "app/src/pedido.spec.ts")
    gravador = Gravador({DIFF: (0, "")})
    ws = workspace_de(wt)

    run_repo_gates(repo_config(), ws, run=gravador)

    assert gravador.cwds[0] == wt  # o diff sai da raiz do worktree
    assert set(gravador.cwds[1:]) == {ws.app_root}


def test_para_no_primeiro_comando_que_falha(tmp_path):
    wt = montar_worktree(tmp_path, "app/src/pedido.spec.ts")
    repo = repo_config(build="npm run build", lint="npm run lint")
    gravador = Gravador({DIFF: (0, ""), "npm run build": (1, "TS2304: nome nao encontrado")})

    relatorio = run_repo_gates(repo, workspace_de(wt), run=gravador)

    assert "npm run lint" not in gravador.comandos
    assert not relatorio.passou


def test_relatorio_traz_a_saida_de_quem_falhou(tmp_path):
    # Criterio de aceite da #24: nao basta o codigo de saida — o
    # implementador precisa do texto do erro na proxima tentativa.
    wt = montar_worktree(tmp_path, "app/src/pedido.spec.ts")
    repo = repo_config(build="npm run build")
    gravador = Gravador({DIFF: (0, ""), "npm run build": (1, "TS2304: nome nao encontrado")})

    relatorio = run_repo_gates(repo, workspace_de(wt), run=gravador)

    assert [f.comando for f in relatorio.falhas] == ["npm run build"]
    assert "TS2304" in relatorio.falhas[0].saida


def test_teste_que_falha_para_o_relatorio(tmp_path):
    wt = montar_worktree(
        tmp_path, "app/src/a.ts", "app/src/a.spec.ts", "app/src/b.ts", "app/src/b.spec.ts"
    )
    repo = repo_config(test="npx jest {arquivo}")
    gravador = Gravador(
        {DIFF: (0, "app/src/a.ts\napp/src/b.ts\n"), "npx jest src/a.spec.ts": (1, "1 failed")}
    )

    relatorio = run_repo_gates(repo, workspace_de(wt), run=gravador)

    assert "npx jest src/b.spec.ts" not in gravador.comandos
    assert not relatorio.passou
    assert "1 failed" in relatorio.falhas[0].saida
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_gates.py -v`
Expected: `ModuleNotFoundError: No module named 'sentinela_graph.gates'`.

- [ ] **Step 3: Escrever `gates.py`**

```python
"""Gates do repo-alvo: build, lint, format e os testes dos arquivos tocados.

A regra que sustenta tudo aqui: a suite inteira nunca e invocada. Nos repos
de backend ela estoura memoria, e o gate viraria um falso vermelho
permanente. Os alvos saem do diff contra a base, um comando por alvo.
"""

from collections.abc import Iterator
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from sentinela_graph.errors import GateError
from sentinela_graph.models.execution import GateReport, GateResult
from sentinela_graph.models.workspace import Workspace
from sentinela_graph.registry import RepoConfig
from sentinela_graph.shell import Runner, run_command


def arquivos_tocados(
    repo: RepoConfig, worktree: Path, *, run: Runner = run_command
) -> list[str]:
    """Arquivos do diff contra `origin/<base>`, relativos a raiz do worktree.

    `--diff-filter=d` tira os apagados: nao ha o que testar num arquivo que
    nao existe mais.
    """
    comando = f"git diff --name-only --diff-filter=d origin/{repo.base}...HEAD"
    resultado = run(comando, worktree)
    if not resultado.passou:
        raise GateError(f"nao foi possivel derivar o diff em {worktree}:\n{resultado.saida}")
    return [linha.strip() for linha in resultado.saida.splitlines() if linha.strip()]


def alvos_de_teste(repo: RepoConfig, worktree: Path, tocados: list[str]) -> list[str]:
    """Arquivos de teste a rodar, relativos a `root` — que e o cwd do comando.

    Um arquivo tocado que ja e teste vira alvo de si mesmo; um fonte vira os
    testes que `test_patterns` aponta e que existem em disco. Fonte sem teste
    nao gera alvo: e achado do revisor adversarial, nao falha de gate.
    """
    raiz = (worktree / repo.root).resolve()
    alvos: list[str] = []
    for tocado in tocados:
        try:
            relativo = PurePosixPath((worktree / tocado).resolve().relative_to(raiz).as_posix())
        except ValueError:
            continue  # fora do root: nenhum comando de teste alcanca
        for candidato in _candidatos(repo, relativo):
            if (raiz / candidato).is_file() and candidato not in alvos:
                alvos.append(candidato)
    return alvos


def run_repo_gates(
    repo: RepoConfig, workspace: Workspace, *, run: Runner = run_command
) -> GateReport:
    """Build, lint, format e um comando de teste por arquivo tocado.

    Para no primeiro vermelho: rodar lint depois de o build quebrar so
    produz ruido, e esse ruido vira contexto do implementador.
    """
    resultados: list[GateResult] = []
    tocados = arquivos_tocados(repo, workspace.worktree_path, run=run)
    alvos = alvos_de_teste(repo, workspace.worktree_path, tocados)

    comandos = [repo.build, repo.lint, repo.format_check]
    comandos += [repo.test.format(arquivo=alvo) for alvo in alvos]

    for comando in comandos:
        resultado = run(comando, workspace.app_root)
        resultados.append(
            GateResult(comando=comando, passou=resultado.passou, saida=resultado.saida)
        )
        if not resultado.passou:
            break

    return GateReport(resultados=resultados)


def _candidatos(repo: RepoConfig, relativo: PurePosixPath) -> Iterator[str]:
    if _e_arquivo_de_teste(repo, relativo):
        yield relativo.as_posix()
        return
    contexto = {"dir": relativo.parent.as_posix(), "stem": relativo.stem}
    for padrao in repo.test_patterns:
        yield PurePosixPath(padrao.format(**contexto)).as_posix()


def _e_arquivo_de_teste(repo: RepoConfig, relativo: PurePosixPath) -> bool:
    """Um tocado ja e teste se casa com algum padrao com `{stem}` curinga."""
    contexto = {"dir": relativo.parent.as_posix(), "stem": "*"}
    return any(
        fnmatch(relativo.as_posix(), PurePosixPath(padrao.format(**contexto)).as_posix())
        for padrao in repo.test_patterns
    )
```

`PurePosixPath("./pedido.spec.ts")` normaliza para `pedido.spec.ts`, o que é o que faz `{dir}` funcionar quando o arquivo está na raiz do `root`.

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/test_gates.py -v`
Expected: todos passam.

- [ ] **Step 5: Teste de integração com git de verdade**

Acrescentar ao final de `tests/test_gates.py`:

```python
def test_diff_real_contra_origin_encontra_o_arquivo_commitado(nomos):
    from sentinela_graph.shell import run_command
    from sentinela_graph.workspace import prepare_workspace
    from tests.conftest import git

    repo = nomos.registry.repo("nomos-api")
    ws = prepare_workspace(nomos.registry, repo, "victor/nom-716", espera=0)
    alvo = ws.worktree_path / "app" / "src" / "nota.ts"
    alvo.write_text("export const nota = 1;\n")
    (ws.worktree_path / "app" / "src" / "nota.spec.ts").write_text("it('n', () => {});\n")

    git("add", "-A", cwd=ws.worktree_path)
    git("commit", "-m", "feat: nota", cwd=ws.worktree_path)

    tocados = arquivos_tocados(repo, ws.worktree_path, run=run_command)

    assert sorted(tocados) == ["app/src/nota.spec.ts", "app/src/nota.ts"]
    assert alvos_de_teste(repo, ws.worktree_path, tocados) == ["src/nota.spec.ts"]
```

Run: `uv run pytest tests/test_gates.py -v`
Expected: todos passam. Esse teste é o que prova que a string do `git diff` está certa — o `Gravador` acredita em qualquer coisa.

- [ ] **Step 6: Gate e commit**

Run: `uv run ruff check && uv run ruff format --check && uv run pytest`

```bash
git add src/sentinela_graph/gates.py tests/test_gates.py
git commit -m "feat(gates): build, lint, format e testes dos arquivos tocados

Os alvos saem de git diff --name-only contra origin/<base>, um comando por
alvo: a suite inteira estoura memoria nos repos de backend, e teste prova
que ela nunca e invocada. O mapeamento fonte -> teste vem de test_patterns
no registry, porque cada repo usa uma convencao diferente. O GateReport
carrega a saida do comando que falhou, nao so o codigo.

Closes #24"
```

---

## Task 5: Ciclo de vida do worktree

Fecha a task [#25](https://github.com/victordantas1/graph-agent/issues/25).

**Files:**
- Create: `src/sentinela_graph/workspace/lifecycle.py`
- Modify: `src/sentinela_graph/workspace/__init__.py`
- Test: `tests/workspace/test_lifecycle.py`

**Interfaces:**
- Consumes: `Registry`, `RepoConfig` (Task 1); `Workspace` (E1); `Outcome` (E1, `sentinela_graph.state`); `Runner`/`run_command` (Task 3); `WorkspaceError` (Task 1).
- Produces:
  - `WorktreeInfo(path: Path, branch: str | None, prunable: bool)` (dataclass congelada)
  - `finalizar_workspace(registry, repo, workspace, outcome, *, run=run_command) -> bool`
  - `worktrees_registrados(canonico: Path, *, run=run_command) -> list[WorktreeInfo]`
  - `detectar_orfaos(registry, repo, *, branch_ativa: str | None = None, run=run_command) -> list[WorktreeInfo]`

- [ ] **Step 1: Escrever os testes que falham**

`tests/workspace/test_lifecycle.py`:

```python
import pytest

from sentinela_graph.errors import WorkspaceError
from sentinela_graph.shell import CommandResult
from sentinela_graph.state import Outcome
from sentinela_graph.workspace import (
    detectar_orfaos,
    finalizar_workspace,
    prepare_workspace,
    worktrees_registrados,
)

BRANCH = "victor/nom-716-corrige-pedido"

FRACASSOS: list[Outcome] = ["ambiguo", "subespecificado", "reprovado_3x", "erro", "fila_vazia"]


def preparar(nomos, branch=BRANCH):
    return prepare_workspace(
        nomos.registry, nomos.registry.repo("nomos-api"), branch, espera=0
    )


def caminhos(infos):
    """`git worktree list` devolve caminho resolvido; o registry, nao."""
    return [i.path for i in infos]


@pytest.mark.parametrize("outcome", FRACASSOS)
def test_worktree_e_preservado_em_todo_outcome_de_fracasso(nomos, outcome):
    # Depurar um reprovado_3x sem o worktree e impossivel.
    ws = preparar(nomos)
    removeu = finalizar_workspace(
        nomos.registry, nomos.registry.repo("nomos-api"), ws, outcome
    )
    assert removeu is False
    assert ws.worktree_path.is_dir()


def test_worktree_e_removido_em_mr_aberto(nomos):
    ws = preparar(nomos)
    removeu = finalizar_workspace(
        nomos.registry, nomos.registry.repo("nomos-api"), ws, "mr_aberto"
    )
    assert removeu is True
    assert not ws.worktree_path.exists()


def test_remocao_limpa_a_referencia_no_repo_canonico(nomos):
    ws = preparar(nomos)
    finalizar_workspace(nomos.registry, nomos.registry.repo("nomos-api"), ws, "mr_aberto")

    registrados = worktrees_registrados(nomos.canonico())

    assert ws.worktree_path.resolve() not in caminhos(registrados)


def test_remocao_funciona_com_arquivo_nao_versionado_no_worktree(nomos):
    # node_modules/ e o .env copiado tornam todo worktree "sujo" para o git.
    ws = preparar(nomos)
    (ws.worktree_path / "node_modules").mkdir()
    (ws.worktree_path / "node_modules" / "x.js").write_text("1")

    assert finalizar_workspace(
        nomos.registry, nomos.registry.repo("nomos-api"), ws, "mr_aberto"
    )
    assert not ws.worktree_path.exists()


def test_falha_na_remocao_e_erro_com_a_saida(nomos):
    ws = preparar(nomos)

    def recusando(comando, cwd, timeout=None):
        return CommandResult(comando, 1, "fatal: working trees containing submodules")

    with pytest.raises(WorkspaceError, match="submodules"):
        finalizar_workspace(
            nomos.registry,
            nomos.registry.repo("nomos-api"),
            ws,
            "mr_aberto",
            run=recusando,
        )


# --- orfaos ------------------------------------------------------------


def test_worktrees_registrados_ignora_o_repo_canonico(nomos):
    ws = preparar(nomos)
    registrados = worktrees_registrados(nomos.canonico())
    assert caminhos(registrados) == [ws.worktree_path.resolve()]
    assert registrados[0].branch == BRANCH


def test_orfao_de_run_anterior_e_detectado(nomos):
    antigo = preparar(nomos, branch="victor/nom-700-antiga")
    preparar(nomos, branch=BRANCH)

    orfaos = detectar_orfaos(
        nomos.registry, nomos.registry.repo("nomos-api"), branch_ativa=BRANCH
    )

    assert caminhos(orfaos) == [antigo.worktree_path.resolve()]


def test_sem_branch_ativa_todo_worktree_e_orfao(nomos):
    ws = preparar(nomos)
    orfaos = detectar_orfaos(nomos.registry, nomos.registry.repo("nomos-api"))
    assert caminhos(orfaos) == [ws.worktree_path.resolve()]


def test_worktree_com_diretorio_sumido_e_reportado_como_prunable(nomos):
    import shutil

    ws = preparar(nomos)
    shutil.rmtree(ws.worktree_path)

    orfaos = detectar_orfaos(nomos.registry, nomos.registry.repo("nomos-api"))

    assert [(o.path, o.prunable) for o in orfaos] == [(ws.worktree_path.resolve(), True)]


def test_sem_worktree_nenhum_nao_ha_orfao(nomos):
    assert detectar_orfaos(nomos.registry, nomos.registry.repo("nomos-api")) == []
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/workspace/test_lifecycle.py -v`
Expected: `ImportError: cannot import name 'detectar_orfaos' from 'sentinela_graph.workspace'`.

- [ ] **Step 3: Escrever `workspace/lifecycle.py`**

```python
"""Fim de vida do worktree.

Regra unica: so `mr_aberto` remove. Qualquer fracasso preserva, porque
depurar um `reprovado_3x` sem o worktree e impossivel — a branch existe,
mas o node_modules, o .env e o estado do disco que produziram a falha, nao.
"""

from dataclasses import dataclass
from pathlib import Path

from sentinela_graph.errors import WorkspaceError
from sentinela_graph.models.workspace import Workspace
from sentinela_graph.registry import Registry, RepoConfig
from sentinela_graph.shell import Runner, run_command
from sentinela_graph.state import Outcome

OUTCOME_QUE_REMOVE: Outcome = "mr_aberto"


@dataclass(frozen=True)
class WorktreeInfo:
    """Uma linha do `git worktree list --porcelain`."""

    path: Path
    branch: str | None
    prunable: bool


def finalizar_workspace(
    registry: Registry,
    repo: RepoConfig,
    workspace: Workspace,
    outcome: Outcome,
    *,
    run: Runner = run_command,
) -> bool:
    """Remove o worktree se e so se o outcome for `mr_aberto`.

    Devolve se removeu. `--force` e obrigatorio: todo worktree nosso tem
    node_modules e o .env copiado, e o git recusa remover worktree com
    arquivo nao rastreado. Em `mr_aberto` o codigo ja foi commitado e
    empurrado, entao nao ha o que perder; nos demais outcomes nada e
    removido, entao o --force nunca alcanca trabalho nao salvo.
    """
    if outcome != OUTCOME_QUE_REMOVE:
        return False

    canonico = registry.caminho_canonico(repo.nome)
    resultado = run(f"git worktree remove --force {workspace.worktree_path}", canonico)
    if not resultado.passou:
        raise WorkspaceError(
            f"nao foi possivel remover o worktree {workspace.worktree_path}:\n{resultado.saida}"
        )
    run("git worktree prune", canonico)
    return True


def worktrees_registrados(
    canonico: Path, *, run: Runner = run_command
) -> list[WorktreeInfo]:
    """Worktrees que o repo canonico conhece, sem contar ele mesmo."""
    resultado = run("git worktree list --porcelain", canonico)
    if not resultado.passou:
        raise WorkspaceError(f"git worktree list falhou em {canonico}:\n{resultado.saida}")

    infos: list[WorktreeInfo] = []
    for bloco in resultado.saida.strip().split("\n\n"):
        info = _parse_bloco(bloco)
        # O primeiro bloco e sempre o proprio repo canonico.
        if info is not None and info.path != canonico.resolve():
            infos.append(info)
    return infos


def detectar_orfaos(
    registry: Registry,
    repo: RepoConfig,
    *,
    branch_ativa: str | None = None,
    run: Runner = run_command,
) -> list[WorktreeInfo]:
    """Worktrees de runs anteriores que ninguem limpou.

    Nao remove nada: reportar e o trabalho: um orfao ou e um fracasso ainda
    por depurar, ou um run que morreu duro. Ambos merecem um humano.
    """
    canonico = registry.caminho_canonico(repo.nome)
    raiz = registry.worktrees_root / repo.nome
    ativo = registry.caminho_worktree(repo.nome, branch_ativa) if branch_ativa else None
    return [
        info
        for info in worktrees_registrados(canonico, run=run)
        if info.path != (ativo.resolve() if ativo else None)
        and _esta_sob(info.path, raiz)
    ]


def _parse_bloco(bloco: str) -> WorktreeInfo | None:
    caminho: Path | None = None
    branch: str | None = None
    prunable = False
    for linha in bloco.splitlines():
        if linha.startswith("worktree "):
            caminho = Path(linha.removeprefix("worktree ")).resolve()
        elif linha.startswith("branch "):
            branch = linha.removeprefix("branch ").removeprefix("refs/heads/")
        elif linha.startswith("prunable"):
            prunable = True
    return None if caminho is None else WorktreeInfo(caminho, branch, prunable)


def _esta_sob(caminho: Path, raiz: Path) -> bool:
    try:
        caminho.relative_to(raiz.resolve())
    except ValueError:
        return False
    return True
```

`git worktree list --porcelain` resolve os caminhos, e num macOS `/tmp` é link simbólico para `/private/tmp` — daí todo `Path` aqui passar por `.resolve()` antes de comparar.

- [ ] **Step 4: Atualizar `workspace/__init__.py`**

```python
"""Ciclo de vida do worktree isolado de cada issue."""

from sentinela_graph.workspace.lifecycle import (
    WorktreeInfo,
    detectar_orfaos,
    finalizar_workspace,
    worktrees_registrados,
)
from sentinela_graph.workspace.prepare import prepare_workspace

__all__ = [
    "WorktreeInfo",
    "detectar_orfaos",
    "finalizar_workspace",
    "prepare_workspace",
    "worktrees_registrados",
]
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/workspace/test_lifecycle.py -v`
Expected: todos passam.

- [ ] **Step 6: Gate e commit**

Run: `uv run ruff check && uv run ruff format --check && uv run pytest`

```bash
git add src/sentinela_graph/workspace tests/workspace/test_lifecycle.py
git commit -m "feat(workspace): remover so em mr_aberto, preservar em todo fracasso

Teste cobre a preservacao em cada outcome de fracasso. A remocao usa
git worktree remove --force, obrigatorio porque node_modules e o .env
copiado tornam todo worktree sujo aos olhos do git, seguido de prune para
limpar a referencia no canonico. detectar_orfaos reporta worktree de run
anterior sem remover: um orfao merece um humano.

Closes #25"
```

---

## Verificação final do épico

Depois da Task 5, o critério de entrega do épico [#3](https://github.com/victordantas1/graph-agent/issues/3) — *"Dado repo + branch, o sistema cria o worktree a partir de `origin/`, aplica `copy_untracked`, instala e roda os gates do repo"* — se comprova com:

```bash
uv sync
uv run ruff check
uv run ruff format --check
uv run pytest -v
```

O teste que sustenta o critério de ponta a ponta é `test_diff_real_contra_origin_encontra_o_arquivo_commitado` (Task 4, Step 5): ele parte da fixture `nomos`, chama `prepare_workspace` de verdade, commita no worktree e deriva os alvos do diff real.

Na máquina do operador, com os 6 repos presentes, o épico só fecha depois do Step 6 da Task 2:

```bash
uv run pytest -m requires_nomos -v
```

Fechando o épico:

```bash
gh issue close 3 --repo victordantas1/graph-agent \
  --comment "E3 entregue: registry validado no boot, worktree idempotente, gates por arquivo tocado e worktree preservado em todo fracasso."
```

O que **não** existe ao final da E3, por decisão: nenhum nó do grafo (as funções existem, quem as registra é a E5), nenhum `serve_app` (E7 consome `serve`/`health` do registry, que a E3 só valida), nenhum `git add`/`push`/`mr create` (E9), nenhuma sessão do Agent SDK (E4).
