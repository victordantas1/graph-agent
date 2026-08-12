"""Decisao do agente `classify`: em que repositorio o trabalho acontece."""

from typing import Literal

from pydantic import BaseModel, Field

Rota = Literal["feature", "bug", "improvement"]
Forge = Literal["glab", "gh"]


class Routing(BaseModel):
    """Repositorio, diretorios e rota escolhidos, com a evidencia que sustenta."""

    repo: str = Field(min_length=1)
    base: str = Field(min_length=1)
    forge: Forge
    dirs: list[str] = Field(min_length=1)
    rota: Rota
    confianca: float = Field(ge=0.0, le=1.0)
    evidencia: str = Field(min_length=1)
