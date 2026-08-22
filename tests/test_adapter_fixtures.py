from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from hikvision_mcp.adapter import (
    ALERT_STREAM_PATH,
    AUDIO_ALARM_CAPABILITIES_PATH,
    AUDIO_ALARM_PATH,
    DETECTION_ENDPOINTS,
    FIELD_DETECTION_NOTIFICATIONS_PATH,
    FIELD_DETECTION_PATH,
    FIELD_DETECTION_SCHEDULE_PATH,
    IMAGE_CHANNEL_PATH,
    IMAGE_CHANNELS_PATH,
    STORAGE_PATH,
    STREAMING_CHANNELS_PATH,
    SYSTEM_STATUS_PATH,
    SYSTEM_TIME_PATH,
    TWO_WAY_AUDIO_CAPABILITIES_PATH,
    TWO_WAY_AUDIO_PATH,
    VIDEO_INPUT_CHANNELS_PATH,
    GenericHikvisionAdapter,
)
from hikvision_mcp.isapi import IsapiClient
from hikvision_mcp.models import CameraConfig, CameraCredentials, DetectionKind

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(version: str, name: str) -> bytes:
    return (FIXTURES / version / name).read_bytes()


def make_adapter(
    version: str, unavailable_paths: set[str] | None = None
) -> tuple[GenericHikvisionAdapter, IsapiClient]:
    responses = {
        VIDEO_INPUT_CHANNELS_PATH: (
            "application/xml",
            fixture(version, "video_input_channels.xml"),
        ),
        FIELD_DETECTION_PATH: ("application/xml", fixture(version, "field_detection.xml")),
        FIELD_DETECTION_SCHEDULE_PATH: (
            "application/xml",
            fixture(version, "field_detection_schedule.xml"),
        ),
        FIELD_DETECTION_NOTIFICATIONS_PATH: (
            "application/xml",
            fixture(version, "field_detection_notifications.xml"),
        ),
        ALERT_STREAM_PATH: (
            "multipart/mixed; boundary=boundary",
            fixture(version, "alert_stream.multipart"),
        ),
    }
    if version == "v5_7_19":
        motion = DETECTION_ENDPOINTS[DetectionKind.MOTION]
        responses.update(
            {
                SYSTEM_STATUS_PATH: ("application/xml", fixture(version, "system_status.xml")),
                SYSTEM_TIME_PATH: ("application/xml", fixture(version, "system_time.xml")),
                STREAMING_CHANNELS_PATH: (
                    "application/xml",
                    fixture(version, "streaming_channels.xml"),
                ),
                IMAGE_CHANNEL_PATH: ("application/xml", fixture(version, "image_channel.xml")),
                IMAGE_CHANNELS_PATH: ("application/xml", fixture(version, "image_channel.xml")),
                STORAGE_PATH: ("application/xml", fixture(version, "storage.xml")),
                TWO_WAY_AUDIO_PATH: ("application/xml", fixture(version, "two_way_audio.xml")),
                TWO_WAY_AUDIO_CAPABILITIES_PATH: (
                    "application/xml",
                    fixture(version, "two_way_audio_capabilities.xml"),
                ),
                AUDIO_ALARM_PATH.split("?", 1)[0]: (
                    "application/json",
                    fixture(version, "audio_alarm.json"),
                ),
                AUDIO_ALARM_CAPABILITIES_PATH.split("?", 1)[0]: (
                    "application/json",
                    fixture(version, "audio_alarm_capabilities_live.json"),
                ),
                motion.config: ("application/xml", fixture(version, "motion_detection.xml")),
                motion.schedule: (
                    "application/xml",
                    fixture(version, "field_detection_schedule.xml"),
                ),
                motion.notifications: (
                    "application/xml",
                    fixture(version, "field_detection_notifications.xml"),
                ),
            }
        )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in (unavailable_paths or set()) or request.url.path not in responses:
            return httpx.Response(404)
        content_type, body = responses[request.url.path]
        return httpx.Response(200, content=body, headers={"Content-Type": content_type})

    camera = CameraConfig(
        host="192.0.2.10",
        username_env="TEST_USER",
        password_env="TEST_PASSWORD",  # noqa: S106
    )
    credentials = CameraCredentials(
        username="fixture-user",
        password=SecretStr("fixture-password"),  # noqa: S106
    )
    client = IsapiClient(camera, credentials, transport=httpx.MockTransport(handler))
    return GenericHikvisionAdapter(client), client


@pytest.mark.parametrize(
    ("version", "frequency", "period_count"),
    [("v5_7_19", "high", 2), ("v5_7_14", "medium", 1)],
)
async def test_warning_light_json_round_trip(
    version: str, frequency: str, period_count: int
) -> None:
    adapter, client = make_adapter(version)
    try:
        config = adapter._decode_warning_light(  # noqa: SLF001
            fixture(version, "warning_light.json").decode()
        )
        assert config.frequency == frequency
        assert config.duration_seconds == 15
        assert config.schedule is not None
        assert len(config.schedule.periods) == period_count
        assert (
            adapter._decode_warning_light(  # noqa: SLF001
                adapter._encode_warning_light(config).decode()  # noqa: SLF001
            )
            == config
        )
    finally:
        await client.close()


@pytest.mark.parametrize(
    ("version", "enabled", "targets", "linkage"),
    [
        ("v5_7_19", True, ["human", "vehicle"], ["record", "center", "whiteLight"]),
        ("v5_7_14", False, ["human"], ["record", "center"]),
    ],
)
async def test_intrusion_detection_firmware_fixtures(
    version: str,
    enabled: bool,
    targets: list[str],
    linkage: list[str],
) -> None:
    adapter, client = make_adapter(version)
    try:
        config = await adapter.get_intrusion_detection()
        assert config.enabled is enabled
        assert config.regions[0].targets == targets
        assert config.linkage_methods == linkage
        assert config.arming_schedule.periods[0].end == "24:00"
    finally:
        await client.close()


@pytest.mark.parametrize(
    ("version", "event_type", "state"),
    [
        ("v5_7_19", "fielddetection", "active"),
        ("v5_7_14", "videoloss", "inactive"),
    ],
)
async def test_alert_stream_firmware_fixtures(version: str, event_type: str, state: str) -> None:
    adapter, client = make_adapter(version)
    try:
        events = await adapter.monitor_events(duration_seconds=1, max_events=5)
        assert len(events) == 1
        assert events[0].event_type == event_type
        assert events[0].state == state
    finally:
        await client.close()


async def test_expanded_read_fixtures() -> None:
    adapter, client = make_adapter("v5_7_19")
    try:
        health = await adapter.get_camera_health()
        assert health.uptime_seconds == 7712
        assert health.cpu_percent == 80

        streams = await adapter.get_stream_profiles()
        assert [(item.id, item.codec, item.frame_rate_fps) for item in streams] == [
            (101, "H.265", 25.0),
            (102, "H.264", 6.0),
        ]

        image = await adapter.get_image_settings()
        assert image.ir_cut_mode == "auto"
        assert image.ir_light_brightness == 100

        storage = await adapter.get_storage_status()
        assert storage.work_mode == "quota"
        assert storage.volumes == []

        audio_alarm = await adapter.get_audio_alarm()
        assert audio_alarm.available_sounds[0].description == "Siren"
        assert audio_alarm.custom_audio_supported is True

        two_way = await adapter.get_two_way_audio()
        assert two_way[0].codec == "G.711ulaw"
        assert two_way[0].echo_cancellation_supported is True

        reads = await adapter.get_detection_rules([DetectionKind.MOTION])
        assert reads[0].supported is True
        assert reads[0].rule is not None
        assert reads[0].rule.zones[0].targets == ["human", "vehicle"]
        assert reads[0].rule.grid is not None
        assert reads[0].rule.grid.rows == 18
    finally:
        await client.close()


async def test_detection_rule_keeps_config_when_optional_parts_are_unavailable() -> None:
    motion = DETECTION_ENDPOINTS[DetectionKind.MOTION]
    adapter, client = make_adapter(
        "v5_7_19", unavailable_paths={motion.schedule, motion.notifications}
    )
    try:
        reads = await adapter.get_detection_rules([DetectionKind.MOTION])
        assert reads[0].supported is True
        assert reads[0].rule is not None
        assert reads[0].unavailable_parts == ["schedule", "linkage"]

        unsupported = await adapter.get_detection_rules([DetectionKind.SCENE_CHANGE])
        assert unsupported[0].supported is False
        assert unsupported[0].rule is None
    finally:
        await client.close()
