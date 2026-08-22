# Configuration

Copy `config.example.toml` to `config.toml`. Camera aliases must start with a lowercase
letter and contain only lowercase letters, digits, and underscores. Credentials are named
by `username_env` and `password_env`; their values are never stored in TOML or SQLite.
The environment-variable names are arbitrary and may be different for every camera.

`policy.default_level` is the server/client permission ceiling for this local v1 deployment.
Each camera's `policy.max_level` can only reduce that level. `policy.tools` overrides the
required level for known tools but cannot bypass a camera ceiling.

All semantic read tools require Level 1 except identity/capability discovery. This includes
warning light, detection rules, intrusion, health, streams, image settings, storage, audible
alarm, two-way audio, change history, and event monitoring. `monitor_events` is bounded to
1-60 seconds and 1-100 returned events. Warning-light configuration requires Level 3 and
always uses proposal plus explicit apply approval.

Streamable HTTP binds to `127.0.0.1` by default. Do not change this to a remote interface
without adding authentication, TLS, and a reviewed host allowlist.

## Channel selection

Camera channel selectors default to `"auto"`:

```toml
[cameras.example_camera.channels]
video_input = "auto"
image = "auto"
smart_detection = "auto"
```

Automatic selection reads the camera's channel lists and chooses the first available channel.
If an older camera does not expose a list endpoint, the adapter safely falls back to channel 1.
Set a positive integer to override discovery for an NVR, multi-sensor camera, or unusual mapping.

The example policy is deliberately read-only. To enable a Level 3 mutation, both the server
ceiling and that camera's ceiling must be raised explicitly; approval is still mandatory.
