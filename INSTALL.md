# Installation

Install Python 3.12+ and `uv`, then run `uv sync --extra dev`. Copy `config.example.toml`
to `config.toml`, configure environment-variable secrets, and validate with
`uv run hikvision-mcp config validate --config config.toml`.

For the supplied `example_camera`, set `HIKVISION_CAMERA_USERNAME` and
`HIKVISION_CAMERA_PASSWORD` in the same terminal before starting the server. Each camera can
reference different environment-variable names; these names are not fixed by the application.
