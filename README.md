# hikvision-mcp

> [!IMPORTANT]
> Alpha software for local, trusted deployments. Test against your exact camera model and
> firmware before enabling writes.

A local, capability-aware MCP server for safely inspecting and configuring Hikvision
cameras. The current release implements the PRD's first end-to-end vertical slice:

- TOML configuration and environment-variable secrets;
- per-camera and per-tool permission enforcement;
- async ISAPI with digest authentication, safe XML parsing, and bounded event streaming;
- camera identity and capability probing;
- warning-light read and partial configuration updates using the camera's JSON schema;
- read-only intrusion regions, targets, arming schedules, and event linkage;
- read-only motion, tamper, line-crossing, intrusion, region entrance/exit, and
  scene-change rules with zones, schedules, targets, and linkage;
- camera health, stream profiles, image/day-night settings, storage status, audible-alarm
  configuration, and two-way-audio capability reads;
- bounded live alert monitoring with semantic event type and active/inactive state;
- mandatory proposal/apply approval fallback;
- conflict detection, verified read-back, SQLite audit/change history, and rollback;
- stdio and localhost Streamable HTTP MCP transports.

The warning-light, field-detection, and alert-stream adapters have sanitized fixture coverage
for DS-2CD2346G2-ISU/SL firmware V5.7.14 and V5.7.19. The expanded read surface has sanitized
V5.7.19 fixture coverage. Hardware writes still require explicit approval and should be opt-in
until a PUT/read-back cycle has been validated on the target. Firmware differences belong in
adapter subclasses, never MCP handlers.

## Compatibility

| Surface | V5.7.14 fixtures | V5.7.19 fixtures | V5.7.19 reference hardware |
| --- | --- | --- | --- |
| Warning light, intrusion, alert stream | Yes | Yes | Read-only verified |
| Health, streams, image, storage, audio | — | Yes | Read-only verified |
| General detection rules | — | Yes | Seven advertised rule types read |

The reference hardware is a DS-2CD2346G2-ISU/SL. Other Hikvision devices are handled through
capability probing, automatic or configured channel selection, and model/firmware adapter
registration; they are not claimed as tested until sanitized fixtures or hardware evidence are
added.

## Install

```powershell
uv sync --extra dev
Copy-Item config.example.toml config.toml
$env:HIKVISION_CAMERA_USERNAME = "service-account"
$env:HIKVISION_CAMERA_PASSWORD = "..."
```

On Linux or macOS, use `cp` and `export` for the equivalent file copy and environment values.

Keep `config.toml` local and never commit credentials. Validate and run:

```powershell
uv run hikvision-mcp config validate --config config.toml
uv run hikvision-mcp serve --transport stdio --config config.toml
uv run hikvision-mcp serve --transport streamable-http --config config.toml
```

The HTTP MCP endpoint is `http://127.0.0.1:8000/mcp` by default.

## Safe mutation flow

The example configuration is read-only. Deliberately raise both the server and camera policy
ceilings to Level 3 before using this flow.

1. Call `get_capabilities(camera="example_camera")`.
2. Call `get_warning_light`.
3. Call `configure_warning_light`; this only creates a proposal.
4. Obtain explicit human approval.
5. Call `apply_change(proposal_id=..., approved=true)`.
6. The server checks for conflicts, writes once, reads back, verifies, and audits.
7. Use `rollback_change` to create a separately approved rollback proposal.

## Read-only diagnostics

- `get_detection_rules(camera="example_camera")` reads detector types advertised by the
  camera. Pass `kinds` to probe specific types. Each result reports support independently and
  preserves readable configuration if schedule or linkage sub-resources are unavailable.
- `get_camera_health`, `get_stream_profiles`, `get_image_settings`, and `get_storage_status`
  expose operational state without allowing networking, accounts, firmware, or reset actions.
- `get_audio_alarm` and `get_two_way_audio` describe audible deterrence and talk-channel
  configuration. They do not play audio, open a talk session, or change camera state.

- `get_intrusion_detection(camera="example_camera")` returns field-detection enablement,
  regions, polygons, targets, sensitivity, arming schedule, and linkage methods.
- `monitor_events(camera="example_camera", duration_seconds=15)` watches the alert stream for
  a bounded period. Use `event_types=["fielddetection"]` to filter exact camera event names.
- `get_warning_light(camera="example_camera")` returns duration, frequency, and schedule. The
  reference V5.7.19 firmware does not advertise brightness or a standalone enabled flag.

## Quality checks

```powershell
uv run ruff check .
uv run mypy
uv run pytest
```

See [CONFIGURATION.md](CONFIGURATION.md), [SECURITY.md](SECURITY.md), and
[DEVELOPMENT.md](DEVELOPMENT.md).

## Project status and support

This project is not affiliated with or endorsed by Hikvision. Hikvision and ISAPI are used
only to identify compatible products and protocols. Hardware and firmware behavior varies;
unsupported or unknown features return `unsupported_capability` rather than being guessed.

Bug reports and contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before
submitting camera payloads or changes, and use [SECURITY.md](SECURITY.md) for vulnerabilities.

Licensed under the [MIT License](LICENSE).
