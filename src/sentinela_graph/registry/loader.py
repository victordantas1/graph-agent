"""Carregamento do registry.

Registry invalido para o boot, nao o meio do run: descobrir que o
`format_check` do nomos-api nao existe depois de 40 minutos de implement e
tempo jogado fora.
"""

from pathlib import Path

import yaml
from pydantic import ValidationError

from sentinela_graph.errors import RegistryError
from sentinela_graph.registry.models import Registry, RepoConfig

CAMINHO_PADRAO = Path("config/repos.yaml")


def load_registry(caminho: Path = CAMINHO_PADRAO) -> Registry:
    """Le e valida o YAML. Qualquer problema vira `RegistryError`."""
    caminho = Path(caminho)
    if not caminho.is_file():
        raise RegistryError(f"registry nao encontrado em {caminho}")

    try:
        cru = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    except yaml.YAMLError as erro:
        raise RegistryError(f"{caminho}: YAML invalido: {erro}") from erro

    if not isinstance(cru, dict):
        raise RegistryError(f"{caminho}: a raiz do registry precisa ser um mapa")

    repos_crus = cru.get("repos")
    if not isinstance(repos_crus, dict) or not repos_crus:
        raise RegistryError(f"{caminho}: registry sem a secao 'repos'")

    try:
        repos = {
            nome: RepoConfig(nome=nome, **_corpo(caminho, nome, corpo))
            for nome, corpo in repos_crus.items()
        }
        return Registry(**{**cru, "repos": repos})
    except ValidationError as erro:
        raise RegistryError(f"{caminho}: {erro}") from erro


def _corpo(caminho: Path, nome: str, corpo: object) -> dict:
    if not isinstance(corpo, dict):
        raise RegistryError(f"{caminho}: a entrada {nome!r} precisa ser um mapa")
    if "nome" in corpo:
        raise RegistryError(f"{caminho}: a entrada {nome!r} nao declara 'nome'; a chave e o nome")
    return corpo
