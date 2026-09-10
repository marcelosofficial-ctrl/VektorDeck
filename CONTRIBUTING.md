# Contributing to VektorDeck

Thanks for taking the time to improve VektorDeck.

## Before opening a change

VektorDeck is intentionally local-first and conservative about runtime control. Changes should preserve these invariants:

- no cloud account requirement
- no silent launch, replacement, promotion, or process termination
- loopback-only local runtime control where VektorDeck owns the listener
- clear distinction between observed evidence and inferred recommendations
- no fabricated benchmark confidence when the workstation baseline is contaminated
- predictable failure states instead of hidden fallback behavior

For larger changes, open an issue first so architecture and scope can be discussed before implementation.

## Development checks

Backend:

```bash
python -m pip install -e '.[dev]'
ruff check src tests
pytest -q
```

Frontend:

```bash
cd web
npm ci
npm run build
```

A pull request should leave both backend and frontend CI green.

## Pull requests

Keep changes focused and explain:

1. what problem the change solves
2. why the chosen approach fits the existing architecture
3. how it was tested
4. any user-visible failure modes or compatibility risks

Include or update tests when behavior changes. Avoid unrelated formatting or refactors in the same pull request.

## Security

Potential vulnerabilities should follow [SECURITY.md](SECURITY.md) rather than being disclosed in a public issue.