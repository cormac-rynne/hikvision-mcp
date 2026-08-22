# Contributing

Thanks for helping improve `hikvision-mcp`. The project favors small, typed,
safety-preserving changes over broad endpoint exposure.

## Before opening an issue

- Search existing issues and confirm the behavior on a current checkout.
- Use a minimal reproduction and state the camera model and firmware when relevant.
- Remove credentials, tokens, addresses, MAC addresses, serial numbers, hostnames, names,
  and other identifying data from logs and camera responses.
- Report security problems privately as described in [SECURITY.md](SECURITY.md).

## Development

1. Install Python 3.12 or newer and `uv`.
2. Run `uv sync --extra dev`.
3. Create a focused branch and add tests for the behavior being changed.
4. Run `uv run ruff check .`, `uv run mypy`, and `uv run pytest`.
5. Update documentation when behavior, configuration, permissions, or security changes.

Hardware tests must be opt-in. Never make a persistent camera write from an ordinary unit or
CI test. New capabilities start read-only and require sanitized fixtures from the relevant
firmware. Mutations must retain proposal, approval, conflict detection, rollback snapshot,
single-write, read-back verification, and audit behavior.

## Pull requests

Keep pull requests focused and explain the user-visible behavior, safety implications, test
coverage, and firmware evidence. By contributing, you agree that your contribution is
licensed under this repository's MIT License.
