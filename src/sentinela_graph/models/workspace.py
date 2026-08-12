"""Worktree isolado onde a implementacao e a validacao acontecem."""

from pathlib import Path

from pydantic import BaseModel, Field


class Workspace(BaseModel):
    """Um `git worktree` por issue, em /home/victor/nomos/.worktrees/<repo>/<branch>."""

    worktree_path: Path
    branch: str = Field(min_length=1)
    app_root: Path
    install_ok: bool = False
    port: int | None = Field(default=None, ge=1024, le=65535)
