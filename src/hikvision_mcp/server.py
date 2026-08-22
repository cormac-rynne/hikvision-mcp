from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from mcp.server import MCPServer

from .errors import HikvisionMCPError
from .models import DetectionKind, WarningLightConfig
from .service import CameraService


async def _safe(call: Callable[[], Awaitable[Any]]) -> Any:
    try:
        return await call()
    except HikvisionMCPError as exc:
        return exc.as_dict()


def create_mcp_server(service: CameraService) -> MCPServer[Any]:
    mcp = MCPServer(
        "hikvision-mcp",
        instructions=(
            "Safe semantic access to configured Hikvision cameras. Read capabilities before "
            "using feature tools. Never substitute an unsupported feature. All mutations use "
            "proposal then explicit apply approval."
        ),
    )

    @mcp.tool()
    async def list_cameras() -> Any:
        """List configured cameras. Read-only. Requires permission Level 0."""
        return await _safe(service.list_cameras)

    @mcp.tool()
    async def get_camera_identity(camera: str) -> Any:
        """Read camera model and firmware identity. Read-only. Requires Level 0."""
        return await _safe(lambda: service.get_camera_identity(camera))

    @mcp.tool()
    async def get_capabilities(camera: str) -> Any:
        """Probe semantic camera capabilities. Read-only. Requires Level 0."""
        return await _safe(lambda: service.get_capabilities(camera))

    @mcp.tool()
    async def get_warning_light(camera: str) -> Any:
        """Read native warning/strobe-light settings. Read-only. Requires Level 1."""
        return await _safe(lambda: service.get_warning_light(camera))

    @mcp.tool()
    async def get_intrusion_detection(camera: str) -> Any:
        """Read field/intrusion regions, arming schedule, targets, and linkage.

        Read-only. Requires Level 1. This does not alter detection or alarm behavior.
        """
        return await _safe(lambda: service.get_intrusion_detection(camera))

    @mcp.tool()
    async def get_detection_rules(camera: str, kinds: list[DetectionKind] | None = None) -> Any:
        """Read detection rules, zones, schedules, targets, and alarm linkage.

        Read-only. Requires Level 1. Kinds may include motion, tamper, line_crossing,
        intrusion, region_entrance, region_exit, and scene_change. Omit kinds to read features
        advertised by the camera. Each result states whether it is supported; unavailable
        schedule or linkage sub-resources do not discard a readable rule configuration.
        """
        return await _safe(lambda: service.get_detection_rules(camera, kinds))

    @mcp.tool()
    async def get_camera_health(camera: str) -> Any:
        """Read uptime, CPU, memory, reboot count, and clock status. Requires Level 1."""
        return await _safe(lambda: service.get_camera_health(camera))

    @mcp.tool()
    async def get_stream_profiles(camera: str) -> Any:
        """Read semantic video and audio encoding profiles. Requires Level 1."""
        return await _safe(lambda: service.get_stream_profiles(camera))

    @mcp.tool()
    async def get_image_settings(camera: str) -> Any:
        """Read day/night, exposure, colour, WDR, noise, and illumination settings."""
        return await _safe(lambda: service.get_image_settings(camera))

    @mcp.tool()
    async def get_storage_status(camera: str) -> Any:
        """Read camera storage mode, devices, capacity, and status. Requires Level 1."""
        return await _safe(lambda: service.get_storage_status(camera))

    @mcp.tool()
    async def get_audio_alarm(camera: str) -> Any:
        """Read audible-alarm sound, volume, repetitions, schedule, and options."""
        return await _safe(lambda: service.get_audio_alarm(camera))

    @mcp.tool()
    async def get_two_way_audio(camera: str) -> Any:
        """Read two-way-audio channels and supported audio properties. Requires Level 1."""
        return await _safe(lambda: service.get_two_way_audio(camera))

    @mcp.tool()
    async def monitor_events(
        camera: str,
        duration_seconds: int = 10,
        max_events: int = 20,
        event_types: list[str] | None = None,
    ) -> Any:
        """Monitor the camera alert stream for a bounded period.

        Read-only. Requires Level 1. Returns semantic event type, active/inactive state,
        timestamp, channel, and description. Duration is limited to 1-60 seconds and the
        result to 1-100 events. Optionally filter using exact camera event type names.
        """
        return await _safe(
            lambda: service.monitor_events(
                camera,
                duration_seconds=duration_seconds,
                max_events=max_events,
                event_types=event_types,
            )
        )

    @mcp.tool()
    async def configure_warning_light(
        camera: str,
        duration_seconds: int | None = None,
        frequency: Literal["high", "medium", "low", "normallyOn"] | None = None,
        schedule: dict[str, object] | None = None,
    ) -> Any:
        """Propose a persistent native warning/strobe-light change.

        Requires Level 3 and approval. This call never mutates the camera. Call
        get_capabilities first when support is unknown. Only supplied fields change.
        Do not use this for ordinary IR/night illumination. Unsupported features are
        never substituted. A successful result contains a proposal_id for apply_change.
        """
        supplied = {
            key: value
            for key, value in {
                "duration_seconds": duration_seconds,
                "frequency": frequency,
                "schedule": schedule,
            }.items()
            if value is not None
        }
        try:
            patch = WarningLightConfig.model_validate(supplied)
        except Exception as exc:
            return {"error": "invalid_configuration", "message": str(exc)}
        return await _safe(lambda: service.propose_warning_light(camera, patch))

    @mcp.tool()
    async def apply_change(proposal_id: str, approved: bool) -> Any:
        """Apply or reject a pending proposal after explicit user approval.

        Mutates state when approved=true, requires Level 3, verifies current state for
        conflicts, reads back the result, and audits it. Pass false when approval was denied.
        """
        return await _safe(lambda: service.apply_change(proposal_id, approved))

    @mcp.tool()
    async def get_change_history(camera: str | None = None, limit: int = 100) -> Any:
        """Read recent verified configuration changes. Read-only. Requires Level 1."""
        return await _safe(lambda: service.get_change_history(camera, limit))

    @mcp.tool()
    async def get_change(change_id: str) -> Any:
        """Read a change and its rollback metadata. Read-only. Requires Level 1."""
        return await _safe(lambda: service.get_change(change_id))

    @mcp.tool()
    async def rollback_change(change_id: str) -> Any:
        """Propose restoring a previous camera configuration snapshot.

        Requires Level 3 and approval. This call does not mutate the camera; pass its
        proposal_id to apply_change after explicit approval. Rollback is itself audited.
        """
        return await _safe(lambda: service.propose_rollback(change_id))

    return mcp
