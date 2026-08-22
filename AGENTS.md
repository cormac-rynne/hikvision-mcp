# AGENTS.md

## Project purpose

`hikvision-mcp` is a local, capability-aware MCP server for safely discovering,
inspecting, configuring, operating, and monitoring Hikvision cameras.

The Product Requirements Document supplied for this repository is the source of
truth. Build incrementally and prefer a small, strongly typed core over broad,
loosely defined camera support.

## Current implementation scope

The implemented vertical slice covers:

- TOML configuration and environment-variable secrets;
- SQLite persistence;
- MCP stdio and local Streamable HTTP transports;
- async ISAPI access with digest authentication;
- identity and capability probing;
- semantic warning-light configuration using the validated JSON shape;
- read-only intrusion/field-detection configuration and event linkage;
- read-only general detection rules, health, stream profiles, image settings, storage,
  audible-alarm configuration, and two-way-audio configuration;
- automatic or configured channel selection, per-detector support results, and a
  model/firmware adapter registry;
- bounded read-only live event monitoring;
- proposal, approval, conflict detection, verified apply, audit, and rollback.

Do not describe unimplemented PRD phases as complete. Real hardware XML mappings
must be validated against sanitized fixtures from the target firmware before
hardware writes are considered production-ready.

## Architecture boundaries

Preserve this dependency direction:

```text
MCP tools
  -> CameraService
  -> policy / approval / change storage
  -> semantic CameraAdapter
  -> IsapiClient
  -> camera
```

- MCP handlers expose semantic camera concepts, never Hikvision endpoints or XML.
- Model- and firmware-specific behavior belongs in adapters or a quirk registry.
- Policy, storage, and MCP modules must not branch on camera model numbers.
- Use Pydantic models for public semantic inputs and outputs.
- Return `unsupported_capability` when support is absent or unknown. Never silently
  substitute another feature.
- Partial configuration tools behave like patches: read, merge supplied fields,
  validate the complete result, then write.

## Safety and security rules

- Reads may be directly available when policy permits.
- Every Level 2 or Level 3 mutation requires explicit approval.
- A proposal call must never mutate a camera.
- Before applying a proposal, re-read state and reject conflicts.
- Save rollback state before persistent writes.
- Do not report success from HTTP status alone; read back and verify.
- Do not blindly retry writes after timeouts or ambiguous failures.
- Keep Streamable HTTP bound to `127.0.0.1` by default.
- Camera hosts must come from configured camera records.
- Credentials must remain outside TOML, logs, SQLite audit metadata, fixtures, and
  MCP responses.
- Parse untrusted XML with external entities disabled.
- Never expose camera user/password administration, writable networking, firmware
  updates, factory reset, or certificate/private-key replacement in V1.
- Raw ISAPI access must not bypass permissions, approval, host restrictions, or the
  global prohibited-operation policy.

## Adding a capability

1. Add strongly typed semantic models.
2. Add model-independent methods to `CameraAdapter`.
3. Implement endpoint/XML handling inside the adapter layer.
4. Add capability probing and exact unsupported behavior.
5. Add read-only service and MCP interfaces first.
6. For mutations, implement proposal, approval, re-read/conflict detection,
   snapshot, one write, read-back verification, audit, and rollback metadata.
7. Add sanitized ISAPI fixtures and tests.

Do not add feature breadth before the current vertical slice remains green against
both mocks and, where explicitly enabled, the reference hardware.

## Development conventions

- Python baseline: 3.12 or newer.
- Package and lock dependencies with `uv`; commit `uv.lock`.
- Use async I/O for camera communication.
- Keep application logs on stderr in stdio mode. Never print diagnostic output to
  stdout from the MCP server.
- Use structured, actionable errors without raw stack traces in agent responses.
- Preserve user changes and avoid unrelated rewrites.
- Sanitized fixtures must contain no credentials, real serial numbers, tokens, or
  sensitive network information.
- Hardware tests must be opt-in. Separate read-only and write tests, and require an
  explicit environment flag for hardware writes.

## Required verification

Before considering a change complete, run:

```powershell
uv run ruff check .
uv run mypy
uv run pytest
```

When changing MCP registration or packaging, also validate the CLI and inspect the
registered tool list. When changing an adapter, add or update a sanitized fixture
and test the semantic transformation in both directions where applicable.

## Documentation

Update the relevant documentation when behavior, configuration, permissions,
security posture, or extension procedures change:

- `README.md`
- `INSTALL.md`
- `CONFIGURATION.md`
- `SECURITY.md`
- `ADDING_CAMERAS.md`
- `ADDING_CAPABILITIES.md`
- `DEVELOPMENT.md`
