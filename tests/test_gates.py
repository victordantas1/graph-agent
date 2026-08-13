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
    assert alvos_de_teste(repo_config(), wt, ["app/src/pedido.ts"]) == ["src/pedido.spec.ts"]


def test_alvo_e_relativo_ao_root_e_nao_a_raiz_do_repo(tmp_path):
    # `npx jest` roda dentro de app/; passar "app/src/..." nao acharia nada.
    wt = montar_worktree(tmp_path, "app/src/pedido.spec.ts")
    assert alvos_de_teste(repo_config(), wt, ["app/src/pedido.spec.ts"]) == ["src/pedido.spec.ts"]


def test_arquivo_de_teste_tocado_vira_alvo_de_si_mesmo(tmp_path):
    wt = montar_worktree(tmp_path, "app/src/pedido.spec.ts")
    assert alvos_de_teste(repo_config(), wt, ["app/src/pedido.spec.ts"]) == ["src/pedido.spec.ts"]


def test_padrao_em_subdiretorio_de_testes_e_considerado(tmp_path):
    wt = montar_worktree(tmp_path, "app/src/nota.ts", "app/src/__tests__/nota.spec.ts")
    assert alvos_de_teste(repo_config(), wt, ["app/src/nota.ts"]) == ["src/__tests__/nota.spec.ts"]


def test_fonte_sem_teste_correspondente_nao_gera_alvo(tmp_path):
    wt = montar_worktree(tmp_path, "app/src/sem-teste.ts")
    assert alvos_de_teste(repo_config(), wt, ["app/src/sem-teste.ts"]) == []


def test_arquivo_fora_do_root_e_ignorado(tmp_path):
    wt = montar_worktree(tmp_path, "README.md", "app/src/pedido.spec.ts")
    assert alvos_de_teste(repo_config(), wt, ["README.md"]) == []


def test_alvos_nao_repetem(tmp_path):
    wt = montar_worktree(tmp_path, "app/src/pedido.ts", "app/src/pedido.spec.ts")
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


def test_diff_real_contra_origin_encontra_o_arquivo_commitado(nomos):
    from sentinela_graph.shell import run_command
    from sentinela_graph.workspace import prepare_workspace
    from tests.conftest import git

    repo = nomos.registry.repo("nomos-api")
    ws = prepare_workspace(nomos.registry, repo, "victor/nom-716", espera=0)
    alvo = ws.worktree_path / "app" / "src" / "nota.ts"
    alvo.write_text("export const nota = 1;\n")
    (ws.worktree_path / "app" / "src" / "nota.spec.ts").write_text("it('n', () => {});\n")

    # `app/.env` esta presente e untracked por design (copy_untracked); `-A`
    # o varreria pra dentro do commit, exatamente o motivo pelo qual a spec
    # proibe `-A` no `open_mr` — add caminho a caminho.
    git("add", "--", "app/src/nota.ts", "app/src/nota.spec.ts", cwd=ws.worktree_path)
    git("commit", "-m", "feat: nota", cwd=ws.worktree_path)

    tocados = arquivos_tocados(repo, ws.worktree_path, run=run_command)

    assert sorted(tocados) == ["app/src/nota.spec.ts", "app/src/nota.ts"]
    assert alvos_de_teste(repo, ws.worktree_path, tocados) == ["src/nota.spec.ts"]
