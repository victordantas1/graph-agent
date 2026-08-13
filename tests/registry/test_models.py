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


def test_serve_vazio_e_rejeitado():
    # Uma string vazia nao e um comando: shlex.split("") vira argv vazio e
    # so quebra dentro do run_command, no meio do run (task #21).
    with pytest.raises(ValidationError):
        repo_config(serve="")


def test_health_vazio_e_rejeitado():
    with pytest.raises(ValidationError):
        repo_config(health="")


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
