"""Registry declarativo dos repos da Nomos."""

from sentinela_graph.registry.loader import CAMINHO_PADRAO, load_registry
from sentinela_graph.registry.models import QaMode, Registry, RepoConfig

__all__ = ["CAMINHO_PADRAO", "QaMode", "Registry", "RepoConfig", "load_registry"]
