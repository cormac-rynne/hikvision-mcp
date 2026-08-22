from __future__ import annotations

from .errors import error
from .models import AppConfig, PermissionLevel

DEFAULT_TOOL_LEVELS: dict[str, PermissionLevel] = {
    "get_detection_rules": PermissionLevel.READ,
    "get_camera_health": PermissionLevel.READ,
    "get_stream_profiles": PermissionLevel.READ,
    "get_image_settings": PermissionLevel.READ,
    "get_storage_status": PermissionLevel.READ,
    "get_audio_alarm": PermissionLevel.READ,
    "get_two_way_audio": PermissionLevel.READ,
    "list_cameras": PermissionLevel.DISCOVERY,
    "get_camera_status": PermissionLevel.DISCOVERY,
    "get_camera_identity": PermissionLevel.DISCOVERY,
    "get_capabilities": PermissionLevel.DISCOVERY,
    "get_warning_light": PermissionLevel.READ,
    "get_intrusion_detection": PermissionLevel.READ,
    "monitor_events": PermissionLevel.READ,
    "configure_warning_light": PermissionLevel.CONFIGURE,
    "apply_change": PermissionLevel.CONFIGURE,
    "get_change_history": PermissionLevel.READ,
    "get_change": PermissionLevel.READ,
    "rollback_change": PermissionLevel.CONFIGURE,
}


class PolicyEngine:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def required_level(self, tool: str) -> PermissionLevel:
        return self._config.policy.tools.get(tool, DEFAULT_TOOL_LEVELS[tool])

    def authorize(self, tool: str, camera: str | None = None) -> PermissionLevel:
        required = self.required_level(tool)
        effective = self._config.policy.default_level
        if camera is not None:
            camera_config = self._config.cameras.get(camera)
            if camera_config is None:
                raise error(
                    "camera_not_found", f"Camera '{camera}' is not configured", camera=camera
                )
            effective = min(effective, camera_config.policy.max_level)
        if effective < required:
            raise error(
                "permission_denied",
                f"Tool '{tool}' requires permission level {int(required)}",
                required_level=int(required),
                effective_level=int(effective),
            )
        return required
