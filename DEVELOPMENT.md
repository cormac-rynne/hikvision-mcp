# Development

The layers are deliberately narrow:

`MCP tools -> CameraService -> policy/change manager -> CameraAdapter -> IsapiClient`

MCP handlers must use semantic Pydantic models. Endpoint names, XML shapes, and firmware
quirks belong only in adapters. Add sanitized real-device fixtures before changing XML, JSON,
or multipart codecs.

The test fake exercises proposal, rejection, conflict, verification, history, and rollback
without hardware. Real hardware tests must remain opt-in and separate read from write tests.
Firmware fixtures currently cover warning-light JSON, field detection, schedules, linkage,
and alert events for V5.7.14 and V5.7.19. V5.7.19 fixtures additionally cover general
detection-rule decoding, system health/time, stream profiles, image settings, storage,
audible-alarm JSON, and two-way audio.

`AdapterRegistry` is the extension point for model/firmware quirks. The default generic adapter
discovers video and image channels when list endpoints are available, accepts per-camera channel
overrides, and derives smart-event trigger identifiers from the selected detection channel.
