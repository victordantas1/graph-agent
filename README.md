# sentinela-graph-agent

Grafo de agentes que leva uma issue do Linear — status `To Do` **e** label
`Ready` — ate um Merge Request aberto, sem intervencao humana durante a
execucao.

Design: [`docs/superpowers/specs/2026-08-11-graph-of-agents-design.md`](docs/superpowers/specs/2026-08-11-graph-of-agents-design.md)

## Desenvolvimento

```bash
uv sync                 # instala tudo, inclusive o grupo dev
uv run pytest           # testes
uv run ruff check       # lint
uv run ruff format      # formatacao
```

Gate completo antes de commitar:

```bash
uv run ruff check && uv run ruff format --check && uv run pytest
```

## Configuracao

Copie `.env.template` para `.env` e preencha. Nenhuma chave entra no
repositorio.
