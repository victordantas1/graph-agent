"""Contratos de saida dos agentes do Agent SDK.

O grafo renderiza o MR e os comentarios do Linear a partir destes objetos.
Nenhum texto livre de LLM chega direto ao Linear ou ao GitLab.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

TipoCommit = Literal["feat", "fix", "refactor", "chore"]
NomeValidador = Literal["review_adv", "qa_func"]


class PlanSummary(BaseModel):
    """Resumo do plano. Vira o comentario que `post_plan` publica na issue."""

    bugs: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    arquivos: list[str] = Field(default_factory=list)
    riscos: list[str] = Field(default_factory=list)
    suposicoes: list[str] = Field(default_factory=list)


class Verdict(BaseModel):
    """Veredito de um validador sobre uma tentativa especifica.

    `attempt` e obrigatorio porque o canal `verdicts` do estado acumula entre
    tentativas: sem ele, o `verdict_gate` leria a reprovacao da tentativa
    anterior como se fosse da atual.
    """

    agente: NomeValidador
    attempt: int = Field(ge=0)
    aprovado: bool
    achados: list[str] = Field(default_factory=list)
    evidencia: str = Field(min_length=1)

    @model_validator(mode="after")
    def _reprovar_exige_achado(self) -> "Verdict":
        if not self.aprovado and not self.achados:
            raise ValueError("veredito reprovado precisa de pelo menos um achado")
        return self


class ImplementationSummary(BaseModel):
    """Saida do `implement`. Alimenta o titulo e o corpo do MR."""

    tipo: TipoCommit
    escopo: str = Field(min_length=1)
    resumo: str = Field(min_length=1)
    mudancas: list[str] = Field(min_length=1)
    arquivos_tocados: list[str] = Field(min_length=1)
    comandos_validacao: list[str] = Field(min_length=1)
