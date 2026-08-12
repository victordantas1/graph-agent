"""Estado do grafo.

Artefatos volumosos ficam em disco no worktree; aqui mora o ponteiro, o
veredito e o contador.
"""

import operator
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from sentinela_graph.models.agent_outputs import (
    ImplementationSummary,
    PlanSummary,
    Verdict,
)
from sentinela_graph.models.execution import GateReport, MrRef
from sentinela_graph.models.issue import IssueRef
from sentinela_graph.models.routing import Routing
from sentinela_graph.models.workspace import Workspace

MAX_ATTEMPTS = 3

Outcome = Literal[
    "mr_aberto",
    "fila_vazia",
    "ambiguo",
    "subespecificado",
    "reprovado_3x",
    "erro",
]


class GraphState(BaseModel):
    """O que o checkpoint guarda entre um no e o proximo."""

    issue: IssueRef | None = None
    routing: Routing | None = None
    workspace: Workspace | None = None
    plan_path: str | None = None
    plan_summary: PlanSummary | None = None
    attempt: int = Field(default=0, ge=0, le=MAX_ATTEMPTS)
    gate_report: GateReport | None = None
    # `review_adv` e `qa_func` escrevem neste canal em paralelo: sem reducer,
    # o LangGraph rejeita a escrita concorrente. Com `add`, os vereditos
    # acumulam entre tentativas — filtre com `verdicts_da_tentativa`.
    verdicts: Annotated[list[Verdict], operator.add] = Field(default_factory=list)
    findings_digest: str = ""
    impl_summary: ImplementationSummary | None = None
    mr: MrRef | None = None
    outcome: Outcome | None = None

    def verdicts_da_tentativa(self, attempt: int) -> list[Verdict]:
        """Vereditos de uma tentativa. E sobre eles que o `verdict_gate` decide."""
        return [v for v in self.verdicts if v.attempt == attempt]
