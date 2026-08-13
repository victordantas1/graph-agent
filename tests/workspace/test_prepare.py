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


@pytest.mark.parametrize(
    "branch",
    [
        "--help",  # vira flag do proprio git, nao nome de branch
        "-b",
        "com espaco",  # vira argumento extra no argv
        "",
        "/absoluta",
        ".oculta",
    ],
)
def test_branch_invalida_e_barrada_na_fronteira(nomos, branch):
    # Nao ha shell, mas o parser do git le argv: `git worktree add <path> -b
    # --help origin/develop` executa `--help`, nao cria branch nenhuma.
    with pytest.raises(WorkspaceError, match="nome de branch valido"):
        preparar(nomos, branch=branch)


def test_branch_com_barra_ponto_e_traco_continua_valida(nomos):
    ws = preparar(nomos, branch="victor/nom-716.2_final")
    assert ws.branch == "victor/nom-716.2_final"


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
