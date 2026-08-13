"""Schema do registry de repos.

E o que faz 6 repos custarem configuracao e nao codigo: cada entrada diz
onde o repo mora, como se instala, como se valida e se da para exercitar o
app. Toda invariante daqui e checada no boot — nunca no meio do run.
"""

import re
from pathlib import Path
from string import Formatter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sentinela_graph.errors import RegistryError
from sentinela_graph.models.routing import Forge

QaMode = Literal["http", "playwright", "none"]

# `run_command` usa shlex.split, nunca shell=True: uma linha do YAML nao
# pode virar execucao arbitraria. Onde faria falta um `cd`, existe `root`.
OPERADORES_DE_SHELL = ("&&", "||", "|", ";", ">", "<", "`", "$(")

CAMPOS_DE_COMANDO = ("install", "build", "lint", "format_check", "test", "serve")

# Nomes de branch entram nos comandos de git como argv. Sem shell nao ha
# injecao de shell, mas o parser do proprio git e alcancavel: uma branch
# comecando com '-' vira flag (`-b --help origin/develop`) e um espaco vira
# argumento extra. Charset conservador, dentro do que refname aceita.
PADRAO_DE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def ref_valida(nome: str) -> bool:
    """Se `nome` pode virar argumento de git sem ser lido como flag."""
    return bool(PADRAO_DE_REF.fullmatch(nome))


def placeholders(template: str, campo: str) -> set[str]:
    """Nomes entre chaves de `template`, ou erro nomeando `campo`."""
    try:
        return {nome for _, nome, _, _ in Formatter().parse(template) if nome is not None}
    except ValueError as erro:
        raise ValueError(f"{campo}: {template!r} nao e um template valido: {erro}") from None


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
    serve: str | None = Field(default=None, min_length=1)
    health: str | None = Field(default=None, min_length=1)
    # Divergencias entre o CLAUDE.md e a realidade moram aqui (task #22).
    notas: str = Field(min_length=1)

    @model_validator(mode="after")
    def _comandos_sao_um_comando_so(self) -> "RepoConfig":
        for campo in CAMPOS_DE_COMANDO:
            valor = getattr(self, campo)
            if valor is None:
                continue
            # `min_length=1` nao remove espaco: " " passaria por comando e so
            # quebraria dentro do run_command, no meio do run.
            if not valor.strip():
                raise ValueError(f"{self.nome}.{campo}: comando em branco nao e um comando")
            for operador in OPERADORES_DE_SHELL:
                if operador in valor:
                    raise ValueError(
                        f"{self.nome}.{campo}: operador de shell {operador!r} nao e"
                        " suportado; use o campo 'root' no lugar de 'cd'"
                    )
        return self

    @model_validator(mode="after")
    def _base_e_um_nome_de_branch(self) -> "RepoConfig":
        # `base` vira argv de git (`origin/{base}`). Um espaco viraria
        # argumento extra e um '-' inicial viraria flag do proprio git.
        if not ref_valida(self.base):
            raise ValueError(
                f"{self.nome}.base: {self.base!r} nao e um nome de branch valido;"
                " use apenas letras, digitos e . _ / -, comecando por letra ou digito"
            )
        return self

    @model_validator(mode="after")
    def _test_recebe_um_arquivo(self) -> "RepoConfig":
        # Placeholder desconhecido e KeyError no meio do run, quando o gate
        # formata o template. Aqui vira erro de boot, como o resto.
        nomes = placeholders(self.test, f"{self.nome}.test")
        if "arquivo" not in nomes:
            raise ValueError(f"{self.nome}.test precisa do placeholder {{arquivo}}")
        if nomes != {"arquivo"}:
            desconhecidos = ", ".join(sorted(nomes - {"arquivo"}))
            raise ValueError(
                f"{self.nome}.test: {self.test!r} usa placeholder desconhecido"
                f" ({desconhecidos}); so existe {{arquivo}}"
            )

        for padrao in self.test_patterns:
            nomes = placeholders(padrao, f"{self.nome}.test_patterns")
            if "stem" not in nomes:
                raise ValueError(
                    f"{self.nome}.test_patterns: {padrao!r} precisa do placeholder {{stem}}"
                )
            # `{dir}` e opcional: "tests/test_{stem}.py" do official-diaries
            # nao tem diretorio de origem e esta correto.
            if not nomes <= {"dir", "stem"}:
                desconhecidos = ", ".join(sorted(nomes - {"dir", "stem"}))
                raise ValueError(
                    f"{self.nome}.test_patterns: {padrao!r} usa placeholder desconhecido"
                    f" ({desconhecidos}); so existem {{dir}} e {{stem}}"
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
