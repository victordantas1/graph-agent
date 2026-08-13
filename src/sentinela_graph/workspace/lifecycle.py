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


def worktrees_registrados(canonico: Path, *, run: Runner = run_command) -> list[WorktreeInfo]:
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
        if info.path != (ativo.resolve() if ativo else None) and _esta_sob(info.path, raiz)
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
