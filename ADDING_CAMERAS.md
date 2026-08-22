# Adding cameras

Add a `[cameras.alias]` table to TOML and set the two referenced credential environment
variables. Run `hikvision-mcp camera test ALIAS`, then `camera capabilities ALIAS`.
Do not attempt a write until identity and read-only results have been checked on that firmware.
Leave channel selectors on `"auto"` for ordinary cameras. For an NVR or multi-sensor device,
set explicit positive `video_input`, `image`, or `smart_detection` channel numbers when the
discovered primary channel is not the intended source.
