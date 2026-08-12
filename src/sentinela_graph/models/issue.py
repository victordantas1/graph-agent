"""Issue do Linear congelada por `load_issue`.

Congelar torna o run reproduzivel: `--resume` e o Langfuse mostram o que o
agente viu, nao o que a issue virou depois.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TipoRelacao = Literal["parent", "sub", "blocks", "blocked_by", "related"]


class Comment(BaseModel):
    """Comentario da issue. O contrato mora aqui, nao na descricao."""

    id: str
    author: str
    body: str
    created_at: datetime


class IssueRelation(BaseModel):
    """Issue vizinha: so titulo, estado e URL.

    O corpo nao entra no contexto por padrao — quem precisar dele chama a
    ferramenta `fetch_linear_issue`.
    """

    identifier: str
    title: str
    state: str
    url: str
    tipo: TipoRelacao


class IssueRef(BaseModel):
    """Tudo que o grafo sabe da issue no instante em que a reivindicou."""

    id: str
    identifier: str
    title: str
    url: str
    git_branch_name: str
    spec: str
    state: str
    labels: list[str] = Field(default_factory=list)
    priority: int = 0
    comments: list[Comment] = Field(default_factory=list)
    relations: list[IssueRelation] = Field(default_factory=list)
