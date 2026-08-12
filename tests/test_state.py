import pytest
from pydantic import ValidationError

from sentinela_graph.models.agent_outputs import Verdict
from sentinela_graph.state import MAX_ATTEMPTS, GraphState


def test_estado_inicial_e_todo_vazio():
    estado = GraphState()
    assert estado.issue is None
    assert estado.routing is None
    assert estado.attempt == 0
    assert estado.verdicts == []
    assert estado.findings_digest == ""
    assert estado.outcome is None


@pytest.mark.parametrize(
    "outcome",
    ["mr_aberto", "fila_vazia", "ambiguo", "subespecificado", "reprovado_3x", "erro"],
)
def test_outcomes_do_vocabulario_sao_aceitos(outcome):
    assert GraphState(outcome=outcome).outcome == outcome


def test_outcome_fora_do_vocabulario_e_rejeitado():
    with pytest.raises(ValidationError):
        GraphState(outcome="sucesso")


def test_attempt_acima_do_limite_e_rejeitado():
    assert GraphState(attempt=MAX_ATTEMPTS).attempt == 3
    with pytest.raises(ValidationError):
        GraphState(attempt=MAX_ATTEMPTS + 1)


def test_attempt_negativo_e_rejeitado():
    with pytest.raises(ValidationError):
        GraphState(attempt=-1)


def test_verdicts_da_tentativa_filtra_o_historico():
    # O canal de vereditos acumula: o gate so pode olhar a tentativa corrente.
    estado = GraphState(
        attempt=1,
        verdicts=[
            Verdict(
                agente="review_adv",
                attempt=0,
                aprovado=False,
                achados=["sem teste de erro"],
                evidencia="diff",
            ),
            Verdict(agente="review_adv", attempt=1, aprovado=True, evidencia="diff"),
            Verdict(agente="qa_func", attempt=1, aprovado=True, evidencia="curl"),
        ],
    )
    atuais = estado.verdicts_da_tentativa(1)
    assert len(atuais) == 2
    assert all(v.aprovado for v in atuais)
    assert len(estado.verdicts_da_tentativa(0)) == 1
