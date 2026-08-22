from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, Protocol

from .adapter import CameraAdapter
from .config import resolve_credentials
from .errors import error
from .isapi import IsapiClient
from .models import AppConfig, ChangeResult, DetectionKind, WarningLightConfig
from .policy import PolicyEngine
from .registry import DEFAULT_ADAPTER_REGISTRY
from .storage import Store


class AdapterContext(Protocol):
    async def __aenter__(self) -> CameraAdapter: ...
    async def __aexit__(self, *args: object) -> None: ...


AdapterFactory = Callable[[str], AdapterContext]


class CameraService:
    def __init__(
        self,
        config: AppConfig,
        store: Store,
        adapter_factory: AdapterFactory | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.policy = PolicyEngine(config)
        self._adapter_factory = adapter_factory or self._default_adapter
        self._locks = {alias: asyncio.Lock() for alias in config.cameras}

    @asynccontextmanager
    async def _default_adapter(self, alias: str) -> AsyncIterator[CameraAdapter]:
        camera = self.config.cameras.get(alias)
        if camera is None:
            raise error("camera_not_found", f"Camera '{alias}' is not configured", camera=alias)
        client = IsapiClient(camera, resolve_credentials(camera))
        try:
            yield await DEFAULT_ADAPTER_REGISTRY.create(client, alias)
        finally:
            await client.close()

    async def list_cameras(self) -> list[dict[str, object]]:
        self.policy.authorize("list_cameras")
        return [
            {
                "alias": alias,
                "configured": True,
                "host": camera.host,
                "max_permission_level": int(camera.policy.max_level),
            }
            for alias, camera in sorted(self.config.cameras.items())
        ]

    async def get_camera_identity(self, camera: str) -> dict[str, object]:
        level = self.policy.authorize("get_camera_identity", camera)
        async with self._adapter_factory(camera) as adapter:
            result = (await adapter.identity(camera)).model_dump(mode="json")
        await self.store.audit(
            camera=camera,
            tool="get_camera_identity",
            permission_level=int(level),
            action="read",
            approval_required=False,
            approval_result=None,
            result="success",
        )
        return result

    async def get_capabilities(self, camera: str) -> dict[str, object]:
        level = self.policy.authorize("get_capabilities", camera)
        async with self._adapter_factory(camera) as adapter:
            result = (await adapter.capabilities(camera)).model_dump(mode="json")
        await self.store.audit(
            camera=camera,
            tool="get_capabilities",
            permission_level=int(level),
            action="read",
            approval_required=False,
            approval_result=None,
            result="success",
        )
        return result

    async def get_warning_light(self, camera: str) -> dict[str, object]:
        level = self.policy.authorize("get_warning_light", camera)
        async with self._adapter_factory(camera) as adapter:
            result = (await adapter.get_warning_light()).semantic.model_dump(mode="json")
        await self.store.audit(
            camera=camera,
            tool="get_warning_light",
            permission_level=int(level),
            action="read",
            approval_required=False,
            approval_result=None,
            result="success",
        )
        return result

    async def get_intrusion_detection(self, camera: str) -> dict[str, object]:
        level = self.policy.authorize("get_intrusion_detection", camera)
        async with self._adapter_factory(camera) as adapter:
            result = (await adapter.get_intrusion_detection()).model_dump(mode="json")
        await self.store.audit(
            camera=camera,
            tool="get_intrusion_detection",
            permission_level=int(level),
            action="read",
            approval_required=False,
            approval_result=None,
            result="success",
        )
        return result

    async def _read_adapter_result(
        self, camera: str, tool: str, reader: str
    ) -> dict[str, object] | list[dict[str, object]]:
        level = self.policy.authorize(tool, camera)
        async with self._adapter_factory(camera) as adapter:
            value = await getattr(adapter, reader)()
            if isinstance(value, list):
                result: dict[str, object] | list[dict[str, object]] = [
                    item.model_dump(mode="json") for item in value
                ]
            else:
                result = value.model_dump(mode="json")
        await self.store.audit(
            camera=camera,
            tool=tool,
            permission_level=int(level),
            action="read",
            approval_required=False,
            approval_result=None,
            result="success",
        )
        return result

    async def get_detection_rules(
        self, camera: str, kinds: list[DetectionKind] | None = None
    ) -> dict[str, object]:
        level = self.policy.authorize("get_detection_rules", camera)
        async with self._adapter_factory(camera) as adapter:
            reads = await adapter.get_detection_rules(kinds)
        await self.store.audit(
            camera=camera,
            tool="get_detection_rules",
            permission_level=int(level),
            action="read",
            approval_required=False,
            approval_result=None,
            result="success",
            metadata={
                "requested_count": len(reads),
                "supported_count": sum(read.supported for read in reads),
            },
        )
        return {
            "camera": camera,
            "requested_count": len(reads),
            "supported_count": sum(read.supported for read in reads),
            "rules": [read.model_dump(mode="json") for read in reads],
        }

    async def get_camera_health(self, camera: str) -> dict[str, object]:
        result = await self._read_adapter_result(camera, "get_camera_health", "get_camera_health")
        assert isinstance(result, dict)
        return result

    async def get_stream_profiles(self, camera: str) -> list[dict[str, object]]:
        result = await self._read_adapter_result(
            camera, "get_stream_profiles", "get_stream_profiles"
        )
        assert isinstance(result, list)
        return result

    async def get_image_settings(self, camera: str) -> dict[str, object]:
        result = await self._read_adapter_result(camera, "get_image_settings", "get_image_settings")
        assert isinstance(result, dict)
        return result

    async def get_storage_status(self, camera: str) -> dict[str, object]:
        result = await self._read_adapter_result(camera, "get_storage_status", "get_storage_status")
        assert isinstance(result, dict)
        return result

    async def get_audio_alarm(self, camera: str) -> dict[str, object]:
        result = await self._read_adapter_result(camera, "get_audio_alarm", "get_audio_alarm")
        assert isinstance(result, dict)
        return result

    async def get_two_way_audio(self, camera: str) -> list[dict[str, object]]:
        result = await self._read_adapter_result(camera, "get_two_way_audio", "get_two_way_audio")
        assert isinstance(result, list)
        return result

    async def monitor_events(
        self,
        camera: str,
        duration_seconds: float = 10,
        max_events: int = 20,
        event_types: list[str] | None = None,
    ) -> dict[str, object]:
        level = self.policy.authorize("monitor_events", camera)
        if not 1 <= duration_seconds <= 60:
            raise error("invalid_configuration", "duration_seconds must be between 1 and 60")
        if not 1 <= max_events <= 100:
            raise error("invalid_configuration", "max_events must be between 1 and 100")
        normalized_types = (
            {event_type.strip() for event_type in event_types if event_type.strip()}
            if event_types is not None
            else None
        )
        async with self._adapter_factory(camera) as adapter:
            events = await adapter.monitor_events(
                duration_seconds=duration_seconds,
                max_events=max_events,
                event_types=normalized_types,
            )
        await self.store.audit(
            camera=camera,
            tool="monitor_events",
            permission_level=int(level),
            action="read",
            approval_required=False,
            approval_result=None,
            result="success",
            metadata={"event_count": len(events), "duration_seconds": duration_seconds},
        )
        return {
            "camera": camera,
            "duration_seconds": duration_seconds,
            "event_count": len(events),
            "events": [event.model_dump(mode="json") for event in events],
        }

    async def propose_warning_light(
        self, camera: str, patch: WarningLightConfig
    ) -> dict[str, object]:
        level = self.policy.authorize("configure_warning_light", camera)
        if not patch.model_fields_set:
            raise error("invalid_configuration", "At least one warning-light field is required")
        async with self._adapter_factory(camera) as adapter:
            capabilities = await adapter.capabilities(camera)
            if not capabilities.warning_light.supported or not capabilities.warning_light.writable:
                raise error(
                    "unsupported_capability",
                    f"Camera '{camera}' does not support writable warning-light configuration",
                    camera=camera,
                    capability="warning_light",
                )
            current = await adapter.get_warning_light()
            requested = current.semantic.merge(patch)
        proposal = await self.store.create_proposal(
            camera=camera,
            operation="configure_warning_light",
            request=requested.model_dump(mode="json"),
            current_semantic=current.semantic.model_dump(mode="json"),
            current_raw=current.raw,
            ttl_seconds=self.config.policy.proposal_ttl_seconds,
        )
        await self.store.audit(
            camera=camera,
            tool="configure_warning_light",
            permission_level=int(level),
            action="proposal",
            approval_required=True,
            approval_result="pending",
            result="success",
            metadata={"proposal_id": proposal.id},
        )
        return {
            "status": "approval_required",
            "proposal_id": proposal.id,
            "camera": camera,
            "operation": proposal.operation,
            "current_state": proposal.current_semantic,
            "requested_state": proposal.request,
            "summary": f"Change {camera} warning-light configuration",
            "expires_at": proposal.expires_at.isoformat(),
        }

    async def apply_change(self, proposal_id: str, approved: bool) -> dict[str, object]:
        proposal = await self.store.get_proposal(proposal_id)
        level = self.policy.authorize("apply_change", proposal.camera_alias)
        if proposal.status != "pending":
            raise error(
                "approval_rejected",
                f"Proposal cannot be applied from status '{proposal.status}'",
                proposal_id=proposal_id,
            )
        if not approved:
            await self.store.set_proposal_status(proposal_id, "rejected")
            await self.store.audit(
                camera=proposal.camera_alias,
                tool="apply_change",
                permission_level=int(level),
                action="apply",
                approval_required=True,
                approval_result="rejected",
                result="cancelled",
                metadata={"proposal_id": proposal_id},
            )
            return {"status": "rejected", "proposal_id": proposal_id}
        await self.store.set_proposal_status(proposal_id, "approved")
        try:
            async with self._locks[proposal.camera_alias]:
                if proposal.operation == "configure_warning_light":
                    result = await self._apply_warning_light(proposal)
                elif proposal.operation == "rollback_change":
                    result = await self._apply_rollback(proposal)
                else:
                    raise error("invalid_configuration", "Unknown proposal operation")
        except Exception:
            await self.store.set_proposal_status(proposal_id, "failed")
            raise
        await self.store.audit(
            camera=proposal.camera_alias,
            tool="apply_change",
            permission_level=int(level),
            action="apply",
            approval_required=True,
            approval_result="approved",
            result="success",
            metadata={"proposal_id": proposal_id, "change_id": result.change_id},
        )
        return result.model_dump(mode="json")

    async def _apply_warning_light(self, proposal: Any) -> ChangeResult:
        async with self._adapter_factory(proposal.camera_alias) as adapter:
            current = await adapter.get_warning_light()
            if current.semantic.model_dump(mode="json") != proposal.current_semantic:
                raise error(
                    "camera_state_conflict",
                    "Camera configuration changed after the proposal was created",
                    proposal_id=proposal.id,
                )
            requested = WarningLightConfig.model_validate(proposal.request)
            after = await adapter.set_warning_light(requested)
            if after.semantic != requested:
                raise error(
                    "verification_failed",
                    "Camera read-back did not match the requested warning-light configuration",
                )
        change_id = await self.store.record_change(
            proposal=proposal,
            before_semantic=current.semantic.model_dump(mode="json"),
            after_semantic=after.semantic.model_dump(mode="json"),
            before_raw=current.raw,
            after_raw=after.raw,
            rollback_supported=True,
        )
        return ChangeResult(change_id=change_id, camera=proposal.camera_alias, verified=True)

    async def get_change_history(
        self, camera: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        self.policy.authorize("get_change_history", camera)
        return await self.store.history(camera=camera, limit=max(1, min(limit, 500)))

    async def get_change(self, change_id: str) -> dict[str, Any]:
        change = await self.store.get_change(change_id)
        self.policy.authorize("get_change", change["camera"])
        return change

    async def propose_rollback(self, change_id: str) -> dict[str, object]:
        change = await self.store.get_change(change_id)
        camera = str(change["camera"])
        self.policy.authorize("rollback_change", camera)
        if not change["rollback_supported"] or not change["before_raw"]:
            raise error("rollback_unavailable", "This change has no safe rollback snapshot")
        if change["operation"] not in {"configure_warning_light", "rollback_change"}:
            raise error("rollback_unavailable", "This operation has no rollback adapter")
        async with self._adapter_factory(camera) as adapter:
            current = await adapter.get_warning_light()
        proposal = await self.store.create_proposal(
            camera=camera,
            operation="rollback_change",
            request={"change_id": change_id, "target_raw": change["before_raw"]},
            current_semantic=current.semantic.model_dump(mode="json"),
            current_raw=current.raw,
            ttl_seconds=self.config.policy.proposal_ttl_seconds,
        )
        return {
            "status": "approval_required",
            "proposal_id": proposal.id,
            "camera": camera,
            "operation": "rollback_change",
            "summary": f"Restore state from before change {change_id}",
            "current_state": proposal.current_semantic,
            "requested_state": change["before"],
            "expires_at": proposal.expires_at.isoformat(),
        }

    async def _apply_rollback(self, proposal: Any) -> ChangeResult:
        target_raw = proposal.request.get("target_raw")
        if not isinstance(target_raw, str):
            raise error("rollback_unavailable", "Rollback snapshot is missing")
        async with self._adapter_factory(proposal.camera_alias) as adapter:
            current = await adapter.get_warning_light()
            if current.semantic.model_dump(mode="json") != proposal.current_semantic:
                raise error("camera_state_conflict", "Camera changed after rollback was proposed")
            after = await adapter.restore_warning_light(target_raw)
        change_id = await self.store.record_change(
            proposal=proposal,
            before_semantic=current.semantic.model_dump(mode="json"),
            after_semantic=after.semantic.model_dump(mode="json"),
            before_raw=current.raw,
            after_raw=after.raw,
            rollback_supported=True,
        )
        return ChangeResult(change_id=change_id, camera=proposal.camera_alias, verified=True)
