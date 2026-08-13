"""Fixtures compartilhadas dos testes.

A marca `requires_nomos` isola tudo que so roda na maquina que tem os 6
repos da Nomos clonados. Em qualquer outro lugar, pula — a suite tem que
ficar verde num container limpo.
"""

import pytest

from sentinela_graph.registry import load_registry


def pytest_runtest_setup(item: pytest.Item) -> None:
    if "requires_nomos" not in item.keywords:
        return
    raiz = load_registry().nomos_root
    if not raiz.is_dir():
        pytest.skip(f"exige os repos reais em {raiz}")
