from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest

from hikvision_mcp.adapter import AdapterState, CameraAdapter
from hikvision_mcp.errors import HikvisionMCPError
from hikvision_mcp.models import (
    AppConfig,
    CameraCapabilities,
    CameraConfig,
    CameraEvent,
    CameraIdentity,
    CapabilitySupport,
    IntrusionDetectionConfig,
    PermissionLevel,
    ServerPolicy,
    WarningLightConfig,
)
from hikvision_mcp.service import CameraService
from hikvision_mcp.storage import Store


class FakeCameraAdapter(CameraAdapter):
    def __init__(self) -> None:
        self.state = WarningLightConfig(duration_seconds=10, frequency="low")
        self.raw = json.dumps({"WhiteLightAlarm": {"durationTime": 10, "frequency": "low"}})

    async def identity(self, alias: str) -> CameraIdentity:
        return CameraIdentity(alias=alias, manufacturer="Hikvision", model="MockCam")

    async def capabilities(self, alias: str) -> CameraCapabilities:
        return CameraCapabilities(
            camera=alias,
            warning_light=CapabilitySupport(supported=True, readable=True, writable=True),
        )

    async def get_warning_light(self) -> AdapterState:
        return AdapterState(self.state.model_copy(deep=True), self.raw)

    async def get_intrusion_detection(self) -> IntrusionDetectionConfig:
        return IntrusionDetectionConfig(enabled=False)

    async def monitor_events(
        self,
        duration_seconds: float,
        max_events: int,
        event_types: set[str] | None = None,
    ) -> list[CameraEvent]:
        event = CameraEvent(
            event_type="fielddetection",
            state="active",
            occurred_at=datetime(2026, 8, 21, 22, 35, tzinfo=UTC),
            channel_id=1,
        )
        if event_types is not None and event.event_type not in event_types:
            return []
        return [event][:max_events]

    async def set_warning_light(self, config: WarningLightConfig) -> AdapterState:
        self.state = config.model_copy(deep=True)
        self.raw = json.dumps(
            {
                "WhiteLightAlarm": {
                    "durationTime": config.duration_seconds,
                    "frequency": config.frequency,
                }
            }
        )
        return await self.get_warning_light()

    async def restore_warning_light(self, raw: str) -> AdapterState:
        document = json.loads(raw)
        node = document["WhiteLightAlarm"]
        self.state = WarningLightConfig(
            duration_seconds=node["durationTime"], frequency=node["frequency"]
        )
        self.raw = raw
        return await self.get_warning_light()


def make_config(level: PermissionLevel = PermissionLevel.CONFIGURE) -> AppConfig:
    return AppConfig(
        database_path=":memory:",
        policy=ServerPolicy(default_level=level, proposal_ttl_seconds=300),
        cameras={
            "test_camera": CameraConfig(
                host="192.0.2.10",
                username_env="TEST_CAMERA_USER",
                password_env="TEST_CAMERA_PASSWORD",  # noqa: S106
                policy={"max_level": PermissionLevel.CONFIGURE},
            )
        },
    )


@pytest.fixture
async def service(tmp_path):
    adapter = FakeCameraAdapter()

    @asynccontextmanager
    async def factory(alias: str) -> AsyncIterator[CameraAdapter]:
        assert alias == "test_camera"
        yield adapter

    config = make_config()
    config.database_path = str(tmp_path / "state.sqlite3")
    store = Store(config.database_path)
    await store.initialize()
    yield CameraService(config, store, factory), adapter


async def test_warning_light_full_propose_apply_audit_rollback(service) -> None:
    camera_service, adapter = service
    proposal = await camera_service.propose_warning_light(
        "test_camera", WarningLightConfig(frequency="high")
    )
    assert proposal["status"] == "approval_required"
    assert adapter.state.frequency == "low"

    applied = await camera_service.apply_change(str(proposal["proposal_id"]), approved=True)
    assert applied["verified"] is True
    assert adapter.state.frequency == "high"

    history = await camera_service.get_change_history("test_camera")
    assert len(history) == 1
    assert history[0]["before"]["frequency"] == "low"
    assert history[0]["after"]["frequency"] == "high"

    rollback = await camera_service.propose_rollback(history[0]["id"])
    assert adapter.state.frequency == "high"
    await camera_service.apply_change(str(rollback["proposal_id"]), approved=True)
    assert adapter.state.frequency == "low"


async def test_rejected_proposal_never_mutates(service) -> None:
    camera_service, adapter = service
    proposal = await camera_service.propose_warning_light(
        "test_camera", WarningLightConfig(frequency="high")
    )
    result = await camera_service.apply_change(str(proposal["proposal_id"]), approved=False)
    assert result["status"] == "rejected"
    assert adapter.state.frequency == "low"


async def test_conflict_prevents_overwrite(service) -> None:
    camera_service, adapter = service
    proposal = await camera_service.propose_warning_light(
        "test_camera", WarningLightConfig(duration_seconds=20)
    )
    adapter.state.duration_seconds = 30
    with pytest.raises(HikvisionMCPError, match="changed after") as caught:
        await camera_service.apply_change(str(proposal["proposal_id"]), approved=True)
    assert caught.value.code == "camera_state_conflict"
    assert adapter.state.duration_seconds == 30


async def test_read_policy_cannot_propose(tmp_path) -> None:
    adapter = FakeCameraAdapter()

    @asynccontextmanager
    async def factory(_: str) -> AsyncIterator[CameraAdapter]:
        yield adapter

    config = make_config(PermissionLevel.READ)
    config.database_path = str(tmp_path / "state.sqlite3")
    store = Store(config.database_path)
    await store.initialize()
    camera_service = CameraService(config, store, factory)
    with pytest.raises(HikvisionMCPError) as caught:
        await camera_service.propose_warning_light(
            "test_camera", WarningLightConfig(duration_seconds=20)
        )
    assert caught.value.code == "permission_denied"


async def test_read_intrusion_and_monitor_events(service) -> None:
    camera_service, _ = service
    intrusion = await camera_service.get_intrusion_detection("test_camera")
    assert intrusion["enabled"] is False

    monitored = await camera_service.monitor_events(
        "test_camera", duration_seconds=1, event_types=["fielddetection"]
    )
    assert monitored["event_count"] == 1
    assert monitored["events"][0]["state"] == "active"
