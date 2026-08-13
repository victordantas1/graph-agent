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


def arquivos_tocados(repo: RepoConfig, worktree: Path, *, run: Runner = run_command) -> list[str]:
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
