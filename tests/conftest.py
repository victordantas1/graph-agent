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
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
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
    subprocess.run(["git", "clone", str(remoto), str(canonico)], check=True, capture_output=True)
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
