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

    return Workspace(worktree_path=worktree, branch=branch, app_root=app_root, install_ok=True)


def _garantir_worktree(canonico: Path, worktree: Path, branch: str, base: str, run: Runner) -> None:
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
