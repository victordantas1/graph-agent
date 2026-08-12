from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from sentinela_graph.models.issue import Comment, IssueRef, IssueRelation


def _issue(**overrides) -> IssueRef:
    campos = {
        "id": "e5a1-uuid",
        "identifier": "NOM-716",
        "title": "Instrumentar o tracing com Langfuse",
        "url": "https://linear.app/nomos/issue/NOM-716",
        "git_branch_name": "victor/nom-716-langfuse",
        "spec": "Adicionar tracing por requisicao.",
        "state": "To Do",
    }
    campos.update(overrides)
    return IssueRef(**campos)


def test_issue_minima_tem_colecoes_vazias():
    issue = _issue()
    assert issue.labels == []
    assert issue.comments == []
    assert issue.relations == []
    assert issue.priority == 0


def test_issue_sem_git_branch_name_e_rejeitada():
    with pytest.raises(ValidationError):
        IssueRef(
            id="e5a1-uuid",
            identifier="NOM-716",
            title="t",
            url="u",
            spec="s",
            state="To Do",
        )


def test_comentarios_preservam_a_ordem():
    # O contrato mora nos comentarios; a ordem cronologica e o que diz qual
    # instrucao vale.
    issue = _issue(
        comments=[
            Comment(
                id="c1",
                author="victor",
                body="primeiro",
                created_at=datetime(2026, 8, 1, tzinfo=UTC),
            ),
            Comment(
                id="c2",
                author="victor",
                body="segundo",
                created_at=datetime(2026, 8, 2, tzinfo=UTC),
            ),
        ]
    )
    assert [c.body for c in issue.comments] == ["primeiro", "segundo"]


def test_relacao_com_tipo_invalido_e_rejeitada():
    with pytest.raises(ValidationError):
        IssueRelation(
            identifier="NOM-643",
            title="outra",
            state="Done",
            url="u",
            tipo="duplicada",
        )


def test_issue_ref_com_comentarios_e_relacoes_round_trip():
    # comments e relations sao os campos com datetime aware; e o round-trip
    # via JSON que o checkpointer depende de preservar.
    issue = _issue(
        comments=[
            Comment(
                id="c1",
                author="victor",
                body="primeiro",
                created_at=datetime(2026, 8, 1, tzinfo=UTC),
            ),
            Comment(
                id="c2",
                author="victor",
                body="segundo",
                created_at=datetime(2026, 8, 2, tzinfo=UTC),
            ),
        ],
        relations=[
            IssueRelation(
                identifier="NOM-643",
                title="Adicionar Langfuse ao pacote base",
                state="Done",
                url="https://linear.app/nomos/issue/NOM-643",
                tipo="parent",
            )
        ],
    )
    restaurada = IssueRef.model_validate_json(issue.model_dump_json())
    assert restaurada == issue
    assert restaurada.comments[0].created_at.tzinfo is not None
