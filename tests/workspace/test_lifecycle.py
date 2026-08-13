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
    return prepare_workspace(nomos.registry, nomos.registry.repo("nomos-api"), branch, espera=0)


def caminhos(infos):
    """`git worktree list` devolve caminho resolvido; o registry, nao."""
    return [i.path for i in infos]


@pytest.mark.parametrize("outcome", FRACASSOS)
def test_worktree_e_preservado_em_todo_outcome_de_fracasso(nomos, outcome):
    # Depurar um reprovado_3x sem o worktree e impossivel.
    ws = preparar(nomos)
    removeu = finalizar_workspace(nomos.registry, nomos.registry.repo("nomos-api"), ws, outcome)
    assert removeu is False
    assert ws.worktree_path.is_dir()


def test_worktree_e_removido_em_mr_aberto(nomos):
    ws = preparar(nomos)
    removeu = finalizar_workspace(nomos.registry, nomos.registry.repo("nomos-api"), ws, "mr_aberto")
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

    assert finalizar_workspace(nomos.registry, nomos.registry.repo("nomos-api"), ws, "mr_aberto")
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


def test_aviso_no_stderr_nao_vira_worktree_registrado(nomos, tmp_path):
    # O --porcelain e dado; o stderr do git, nao. Um aviso lido junto viraria
    # um bloco sem `worktree ` — ou, pior, um caminho inventado.
    porcelain = f"worktree {tmp_path / 'wt'}\nbranch refs/heads/victor/nom-716\n"

    def com_aviso(comando, cwd, timeout=None):
        return CommandResult(comando, 0, stdout=porcelain, stderr="warning: algo estranho\n")

    registrados = worktrees_registrados(nomos.canonico(), run=com_aviso)

    assert caminhos(registrados) == [(tmp_path / "wt").resolve()]


def test_orfao_de_run_anterior_e_detectado(nomos):
    antigo = preparar(nomos, branch="victor/nom-700-antiga")
    preparar(nomos, branch=BRANCH)

    orfaos = detectar_orfaos(nomos.registry, nomos.registry.repo("nomos-api"), branch_ativa=BRANCH)

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
