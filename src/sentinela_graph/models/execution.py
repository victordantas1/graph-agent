"""Resultados dos nos deterministicos: gates do repo e MR aberto."""

from pydantic import BaseModel, Field, field_validator

LIMITE_SAIDA = 8000


class GateResult(BaseModel):
    """Um comando do registry executado no worktree."""

    comando: str = Field(min_length=1)
    passou: bool
    saida: str = ""

    @field_validator("saida")
    @classmethod
    def _truncar(cls, valor: str) -> str:
        # A saida entra no checkpoint e volta como contexto para o
        # implementador. Log de suite inteira estoura os dois.
        if len(valor) <= LIMITE_SAIDA:
            return valor
        cortado = len(valor) - LIMITE_SAIDA
        return f"{valor[:LIMITE_SAIDA]}\n[... truncado, {cortado} caracteres ...]"


class GateReport(BaseModel):
    """Relatorio de `repo_gates`: build, lint, format e testes dos arquivos tocados."""

    resultados: list[GateResult] = Field(default_factory=list)

    @property
    def passou(self) -> bool:
        # Relatorio vazio nao passa: gate que nao rodou nao e gate verde.
        return bool(self.resultados) and all(r.passou for r in self.resultados)

    @property
    def falhas(self) -> list[GateResult]:
        return [r for r in self.resultados if not r.passou]


class MrRef(BaseModel):
    """MR/PR aberto por `open_mr`, vinculado na issue por `report`."""

    url: str = Field(min_length=1)
    numero: str = Field(min_length=1)
    titulo: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    base: str = Field(min_length=1)
