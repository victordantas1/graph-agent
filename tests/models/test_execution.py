import pytest
from pydantic import ValidationError

from sentinela_graph.models.execution import LIMITE_SAIDA, GateReport, GateResult, MrRef


def test_gate_result_round_trip():
    resultado = GateResult(comando="npm run lint", passou=True, saida="ok")
    assert GateResult.model_validate_json(resultado.model_dump_json()) == resultado


def test_saida_gigante_e_truncada():
    # A saida entra no checkpoint e volta para o implementador como contexto.
    resultado = GateResult(comando="npx jest", passou=False, saida="x" * (LIMITE_SAIDA + 500))
    assert len(resultado.saida) < LIMITE_SAIDA + 200
    assert "truncado" in resultado.saida


def test_relatorio_verde():
    relatorio = GateReport(
        resultados=[
            GateResult(comando="npm run build", passou=True),
            GateResult(comando="npm run lint", passou=True),
        ]
    )
    assert relatorio.passou is True
    assert relatorio.falhas == []


def test_relatorio_com_uma_falha_reprova():
    falha = GateResult(comando="npx jest a.spec.ts", passou=False, saida="1 failing")
    relatorio = GateReport(resultados=[GateResult(comando="npm run build", passou=True), falha])
    assert relatorio.passou is False
    assert relatorio.falhas == [falha]


def test_relatorio_vazio_nao_passa():
    # all([]) e True em Python. Um relatorio sem nenhum gate executado nao
    # pode virar sinal verde.
    assert GateReport().passou is False


def test_relatorio_round_trip():
    relatorio = GateReport(resultados=[GateResult(comando="npm run build", passou=True)])
    assert GateReport.model_validate_json(relatorio.model_dump_json()) == relatorio


def test_mr_ref_round_trip():
    mr = MrRef(
        url="https://gitlab.com/nomos/nomos-api/-/merge_requests/412",
        numero="!412",
        titulo="feat(tracing): instrumenta o tracing das requisicoes",
        branch="victor/nom-716-langfuse",
        base="develop",
    )
    assert MrRef.model_validate_json(mr.model_dump_json()) == mr


def test_mr_ref_sem_url_e_rejeitado():
    with pytest.raises(ValidationError):
        MrRef(url="", numero="!412", titulo="t", branch="b", base="develop")
