import pytest

from sentinela_graph.errors import RegistryError
from sentinela_graph.registry import load_registry

VALIDO = """
nomos_root: /home/victor/nomos
repos:
  nomos-tldr:
    root: .
    base: main
    forge: gh
    install: npm ci
    build: npm run build
    lint: npm run lint
    format_check: npx prettier --check .
    test: npx jest {arquivo}
    test_patterns: ["{dir}/{stem}.spec.ts"]
    copy_untracked: [.env]
    qa_mode: none
    notas: NAO VERIFICADO
"""


def escrever(tmp_path, texto):
    caminho = tmp_path / "repos.yaml"
    caminho.write_text(texto, encoding="utf-8")
    return caminho


def test_carrega_registry_valido(tmp_path):
    reg = load_registry(escrever(tmp_path, VALIDO))
    assert reg.repo("nomos-tldr").forge == "gh"
    assert reg.nomos_root.name == "nomos"


def test_arquivo_ausente_e_erro_de_boot(tmp_path):
    with pytest.raises(RegistryError, match="nao encontrado"):
        load_registry(tmp_path / "nao-existe.yaml")


def test_yaml_malformado_e_erro_de_boot(tmp_path):
    with pytest.raises(RegistryError, match="YAML invalido"):
        load_registry(escrever(tmp_path, "repos: [: :"))


def test_raiz_que_nao_e_mapa_e_erro_de_boot(tmp_path):
    with pytest.raises(RegistryError, match="mapa"):
        load_registry(escrever(tmp_path, "- nomos-api"))


def test_sem_secao_repos_e_erro_de_boot(tmp_path):
    with pytest.raises(RegistryError, match="repos"):
        load_registry(escrever(tmp_path, "nomos_root: /n\n"))


def test_entrada_que_nao_e_mapa_e_erro_de_boot(tmp_path):
    texto = "nomos_root: /n\nrepos:\n  nomos-api: npm ci\n"
    with pytest.raises(RegistryError):
        load_registry(escrever(tmp_path, texto))


def test_entrada_invalida_e_erro_de_boot_nomeando_o_arquivo(tmp_path):
    quebrado = VALIDO.replace("qa_mode: none", "qa_mode: curl")
    caminho = escrever(tmp_path, quebrado)
    with pytest.raises(RegistryError, match=str(caminho)):
        load_registry(caminho)
