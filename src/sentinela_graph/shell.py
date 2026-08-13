"""Execucao de comando externo, com saida capturada e timeout.

Todo comando do registry passa por aqui. E o ponto onde o timeout vira erro
deterministico e onde o retry transiente da spec acontece.
"""

import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

TIMEOUT_PADRAO = 900


@dataclass(frozen=True)
class CommandResult:
    """O que sobrou de um comando: codigo, saida unificada e se estourou."""

    comando: str
    exit_code: int
    saida: str = ""
    timed_out: bool = False

    @property
    def passou(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class Runner(Protocol):
    """Assinatura que todo no injeta nos testes no lugar do subprocess."""

    def __call__(
        self, comando: str, cwd: Path | None, timeout: int = TIMEOUT_PADRAO
    ) -> CommandResult: ...


def run_command(comando: str, cwd: Path | None, timeout: int = TIMEOUT_PADRAO) -> CommandResult:
    """Roda `comando` em `cwd`, com stdout e stderr unificados.

    Sem `shell=True`: o registry e configuracao, nao script. O carregador ja
    recusou qualquer operador de shell.
    """
    try:
        proc = subprocess.run(
            shlex.split(comando),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as erro:
        # Comando inexistente e deterministico: retry so gastaria tempo.
        return CommandResult(comando, exit_code=127, saida=str(erro))
    except subprocess.TimeoutExpired as erro:
        return CommandResult(comando, exit_code=124, saida=_texto(erro.output), timed_out=True)
    return CommandResult(comando, proc.returncode, proc.stdout + proc.stderr)


def run_com_retry(
    comando: str,
    cwd: Path | None,
    *,
    tentativas: int = 3,
    espera: float = 2.0,
    run: Runner = run_command,
    timeout: int = TIMEOUT_PADRAO,
) -> CommandResult:
    """Retry com backoff exponencial, para falha transiente (rede, install).

    Nao consome tentativa do ciclo de correcao: o implementador nao errou.
    """
    resultado = run(comando, cwd, timeout)
    for n in range(1, tentativas):
        if resultado.passou:
            return resultado
        if espera:
            time.sleep(espera * 2 ** (n - 1))
        resultado = run(comando, cwd, timeout)
    return resultado


def _texto(saida: str | bytes | None) -> str:
    if saida is None:
        return ""
    return saida.decode(errors="replace") if isinstance(saida, bytes) else saida
