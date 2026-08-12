from pathlib import Path

import pytest
from pydantic import ValidationError

from sentinela_graph.models.workspace import Workspace


def _workspace(**overrides) -> Workspace:
    campos = {
        "worktree_path": "/home/victor/nomos/.worktrees/nomos-api/victor/nom-716",
        "branch": "victor/nom-716-langfuse",
        "app_root": "/home/victor/nomos/.worktrees/nomos-api/victor/nom-716/app",
    }
    campos.update(overrides)
    return Workspace(**campos)


def test_caminhos_viram_path():
    ws = _workspace()
    assert isinstance(ws.worktree_path, Path)
    assert isinstance(ws.app_root, Path)


def test_install_e_porta_comecam_indefinidos():
    ws = _workspace()
    assert ws.install_ok is False
    assert ws.port is None


def test_porta_privilegiada_e_rejeitada():
    # serve_app aloca porta dinamica; nada abaixo de 1024 e alocavel sem root.
    with pytest.raises(ValidationError):
        _workspace(port=80)


def test_workspace_sem_branch_e_rejeitado():
    with pytest.raises(ValidationError):
        Workspace(worktree_path="/tmp/wt", app_root="/tmp/wt/app")
