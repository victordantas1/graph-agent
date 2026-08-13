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
            raise ValueError(f"{self.nome}: qa_mode={self.qa_mode} exige 'serve' e 'health'")
        if not executavel and (self.serve is not None or self.health is not None):
            raise ValueError(f"{self.nome}: qa_mode=none nao pode declarar 'serve' nem 'health'")
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
