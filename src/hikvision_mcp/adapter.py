from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast
from xml.etree import ElementTree as StdET

from defusedxml import ElementTree as SafeET

from .errors import HikvisionMCPError, error
from .isapi import IsapiClient
from .models import (
    AudioAlarmConfig,
    AudioOption,
    CameraCapabilities,
    CameraEvent,
    CameraHealth,
    CameraIdentity,
    CapabilitySupport,
    DetectionGrid,
    DetectionKind,
    DetectionRuleConfig,
    DetectionRuleRead,
    DetectionZone,
    ImageCoordinate,
    ImageSettings,
    IntrusionDetectionConfig,
    IntrusionRegion,
    Schedule,
    SchedulePeriod,
    StorageStatus,
    StorageVolume,
    StreamProfile,
    TwoWayAudioChannel,
    WarningLightConfig,
)

DEVICE_INFO_PATH = "/ISAPI/System/deviceInfo"
SYSTEM_CAPABILITIES_PATH = "/ISAPI/System/capabilities"
WARNING_LIGHT_PATH = "/ISAPI/Event/triggers/notifications/whiteLightAlarm?format=json"
ALERT_STREAM_PATH = "/ISAPI/Event/notification/alertStream"
type DayName = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_NAMES: tuple[DayName, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


SYSTEM_STATUS_PATH = "/ISAPI/System/status"
SYSTEM_TIME_PATH = "/ISAPI/System/time"
VIDEO_INPUT_CHANNELS_PATH = "/ISAPI/System/Video/inputs/channels"
STREAMING_CHANNELS_PATH = "/ISAPI/Streaming/channels"
IMAGE_CHANNELS_PATH = "/ISAPI/Image/channels"
IMAGE_CHANNEL_PATH = f"{IMAGE_CHANNELS_PATH}/1"
STORAGE_PATH = "/ISAPI/ContentMgmt/Storage"
AUDIO_ALARM_PATH = "/ISAPI/Event/triggers/notifications/AudioAlarm?format=json"
AUDIO_ALARM_CAPABILITIES_PATH = (
    "/ISAPI/Event/triggers/notifications/AudioAlarm/capabilities?format=json"
)
TWO_WAY_AUDIO_PATH = "/ISAPI/System/TwoWayAudio/channels"
TWO_WAY_AUDIO_CAPABILITIES_PATH = f"{TWO_WAY_AUDIO_PATH}/1/capabilities"


@dataclass(frozen=True)
class AdapterState:
    semantic: WarningLightConfig
    raw: str


@dataclass(frozen=True)
class DetectionEndpoint:
    config: str
    schedule: str
    notifications: str
    zone_tag: str | None


def detection_endpoints(channel_id: int) -> dict[DetectionKind, DetectionEndpoint]:
    """Build channel-specific endpoint mappings without leaking paths into MCP handlers."""

    return {
        DetectionKind.MOTION: DetectionEndpoint(
            f"/ISAPI/System/Video/inputs/channels/{channel_id}/motionDetection",
            f"/ISAPI/Event/schedules/motionDetections/VMD-{channel_id}",
            f"/ISAPI/Event/triggers/VMD-{channel_id}/notifications",
            "Region",
        ),
        DetectionKind.TAMPER: DetectionEndpoint(
            f"/ISAPI/System/Video/inputs/channels/{channel_id}/tamperDetection",
            f"/ISAPI/Event/schedules/tamperDetections/tamper-{channel_id}",
            f"/ISAPI/Event/triggers/tamper-{channel_id}/notifications",
            "TamperDetectionRegion",
        ),
        DetectionKind.LINE_CROSSING: DetectionEndpoint(
            f"/ISAPI/Smart/LineDetection/{channel_id}",
            f"/ISAPI/Event/schedules/lineDetections/linedetection-{channel_id}",
            f"/ISAPI/Event/triggers/linedetection-{channel_id}/notifications",
            "LineItem",
        ),
        DetectionKind.INTRUSION: DetectionEndpoint(
            f"/ISAPI/Smart/FieldDetection/{channel_id}",
            f"/ISAPI/Event/schedules/fieldDetections/fielddetection-{channel_id}",
            f"/ISAPI/Event/triggers/fielddetection-{channel_id}/notifications",
            "FieldDetectionRegion",
        ),
        DetectionKind.REGION_ENTRANCE: DetectionEndpoint(
            f"/ISAPI/Smart/RegionEntrance/{channel_id}",
            f"/ISAPI/Event/schedules/regionEntrances/regionEntrance-{channel_id}",
            f"/ISAPI/Event/triggers/regionEntrance-{channel_id}/notifications",
            "RegionEntranceRegion",
        ),
        DetectionKind.REGION_EXIT: DetectionEndpoint(
            f"/ISAPI/Smart/RegionExiting/{channel_id}",
            f"/ISAPI/Event/schedules/regionExitings/regionExiting-{channel_id}",
            f"/ISAPI/Event/triggers/regionExiting-{channel_id}/notifications",
            "RegionExitingRegion",
        ),
        DetectionKind.SCENE_CHANGE: DetectionEndpoint(
            f"/ISAPI/Smart/SceneChangeDetection/{channel_id}",
            f"/ISAPI/Event/schedules/sceneChangeDetections/scenechangedetection-{channel_id}",
            f"/ISAPI/Event/triggers/scenechangedetection-{channel_id}/notifications",
            None,
        ),
    }


# Channel-1 aliases retained for fixture compatibility; runtime code uses discovery/overrides.
DETECTION_ENDPOINTS = detection_endpoints(1)
FIELD_DETECTION_PATH = DETECTION_ENDPOINTS[DetectionKind.INTRUSION].config
FIELD_DETECTION_SCHEDULE_PATH = DETECTION_ENDPOINTS[DetectionKind.INTRUSION].schedule
FIELD_DETECTION_NOTIFICATIONS_PATH = DETECTION_ENDPOINTS[DetectionKind.INTRUSION].notifications


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_text(root: StdET.Element, *names: str) -> str | None:
    expected = set(names)
    for element in root.iter():
        if _local_name(element.tag) in expected and element.text:
            return element.text.strip()
    return None


def _find_element(root: StdET.Element, *names: str) -> StdET.Element | None:
    expected = set(names)
    for element in root.iter():
        if _local_name(element.tag) in expected:
            return element
    return None


def _as_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.lower() == "true"


class CameraAdapter(ABC):
    _client: IsapiClient
    _channel_cache: dict[str, int]

    @staticmethod
    def _parse(content: bytes) -> StdET.Element:
        try:
            return SafeET.fromstring(content)
        except StdET.ParseError as exc:
            raise error("isapi_error", "Camera returned malformed XML") from exc

    @staticmethod
    def _optional_int(value: str | None) -> int | None:
        return int(value) if value is not None else None

    async def _discover_channel(
        self,
        name: Literal["video_input", "image", "smart_detection"],
    ) -> int:
        configured = getattr(self._client.camera.channels, name)
        if isinstance(configured, int):
            return configured
        if name in self._channel_cache:
            return self._channel_cache[name]
        if name == "smart_detection":
            channel_id = await self._discover_channel("video_input")
        else:
            path, element_name, fallback = {
                "video_input": (VIDEO_INPUT_CHANNELS_PATH, "VideoInputChannel", 1),
                "image": (IMAGE_CHANNELS_PATH, "ImageChannel", 1),
            }[name]
            channel_id = fallback
            try:
                response = await self._client.get(path)
                root = self._parse(response.content)
                for element in root.iter():
                    if _local_name(element.tag) != element_name:
                        continue
                    discovered = self._optional_int(_find_text(element, "id"))
                    if discovered is not None and discovered >= 1:
                        channel_id = discovered
                        break
            except HikvisionMCPError as exc:
                if exc.code != "unsupported_capability":
                    raise
        self._channel_cache[name] = channel_id
        return channel_id

    async def _advertised_detection_kinds(self) -> list[DetectionKind] | None:
        try:
            response = await self._client.get(SYSTEM_CAPABILITIES_PATH)
        except HikvisionMCPError as exc:
            if exc.code == "unsupported_capability":
                return None
            raise
        root = self._parse(response.content)
        flags = {
            DetectionKind.MOTION: "isSupportMotionDetection",
            DetectionKind.TAMPER: "isSupportTamperDetection",
            DetectionKind.LINE_CROSSING: "isSupportLineDetection",
            DetectionKind.INTRUSION: "isSupportFieldDetection",
            DetectionKind.REGION_ENTRANCE: "isSupportRegionEntrance",
            DetectionKind.REGION_EXIT: "isSupportRegionExiting",
            DetectionKind.SCENE_CHANGE: "isSupportSceneChangeDetection",
        }
        advertised = [kind for kind, tag in flags.items() if _find_text(root, tag) == "true"]
        return advertised or None

    @abstractmethod
    async def identity(self, alias: str) -> CameraIdentity: ...

    @abstractmethod
    async def capabilities(self, alias: str) -> CameraCapabilities: ...

    @abstractmethod
    async def get_warning_light(self) -> AdapterState: ...

    @abstractmethod
    async def get_intrusion_detection(self) -> IntrusionDetectionConfig: ...

    async def get_detection_rules(
        self, kinds: list[DetectionKind] | None = None
    ) -> list[DetectionRuleRead]:
        selected = list(
            dict.fromkeys(kinds or await self._advertised_detection_kinds() or list(DetectionKind))
        )
        channel_id = await self._discover_channel("smart_detection")
        endpoints = detection_endpoints(channel_id)
        results: list[DetectionRuleRead] = []
        for kind in selected:
            endpoint = endpoints[kind]
            try:
                config_response = await self._client.get(endpoint.config)
            except HikvisionMCPError as exc:
                if exc.code == "unsupported_capability":
                    results.append(
                        DetectionRuleRead(
                            kind=kind,
                            supported=False,
                            unavailable_parts=["configuration", "schedule", "linkage"],
                        )
                    )
                    continue
                raise
            unavailable: list[Literal["configuration", "schedule", "linkage"]] = []
            try:
                schedule_response = await self._client.get(endpoint.schedule)
                schedule_content = schedule_response.content
            except HikvisionMCPError as exc:
                if exc.code != "unsupported_capability":
                    raise
                schedule_content = b"<Schedule/>"
                unavailable.append("schedule")
            try:
                notifications_response = await self._client.get(endpoint.notifications)
                notifications_content = notifications_response.content
            except HikvisionMCPError as exc:
                if exc.code != "unsupported_capability":
                    raise
                notifications_content = b"<EventTriggerNotificationList/>"
                unavailable.append("linkage")
            results.append(
                DetectionRuleRead(
                    kind=kind,
                    supported=True,
                    rule=self._decode_detection_rule(
                        kind,
                        endpoint,
                        channel_id,
                        config_response.content,
                        schedule_content,
                        notifications_content,
                    ),
                    unavailable_parts=unavailable,
                )
            )
        return results

    def _decode_detection_rule(
        self,
        kind: DetectionKind,
        endpoint: DetectionEndpoint,
        channel_id: int,
        config: bytes,
        schedule: bytes,
        notifications: bytes,
    ) -> DetectionRuleConfig:
        root = self._parse(config)
        schedule_root = self._parse(schedule)
        notifications_root = self._parse(notifications)
        zones: list[DetectionZone] = []
        valid_targets = {"all", "human", "vehicle", "others"}
        valid_confidence = {"low", "mediumLow", "mediumHigh", "high"}
        if endpoint.zone_tag is not None:
            for zone in root.iter():
                if _local_name(zone.tag) != endpoint.zone_tag:
                    continue
                target_text = _find_text(zone, "detectionTarget", "targetType") or ""
                targets = cast(
                    list[Literal["all", "human", "vehicle", "others"]],
                    [item for item in target_text.split(",") if item in valid_targets],
                )
                confidence_text = _find_text(zone, "alarmConfidence")
                confidence = cast(
                    Literal["low", "mediumLow", "mediumHigh", "high"] | None,
                    confidence_text if confidence_text in valid_confidence else None,
                )
                polygon: list[ImageCoordinate] = []
                for coordinate in zone.iter():
                    if _local_name(coordinate.tag) not in {
                        "RegionCoordinates",
                        "Coordinates",
                    }:
                        continue
                    x = _find_text(coordinate, "positionX")
                    y = _find_text(coordinate, "positionY")
                    if x is not None and y is not None:
                        polygon.append(ImageCoordinate(x=int(x), y=int(y)))
                enabled_text = _find_text(zone, "enabled")
                sensitivity = _find_text(zone, "sensitivityLevel", "tampersensitivityLevel")
                zone_id = self._optional_int(_find_text(zone, "id"))
                if zone_id is None:
                    continue
                zones.append(
                    DetectionZone(
                        id=zone_id,
                        enabled=_as_bool(enabled_text),
                        sensitivity=self._optional_int(sensitivity),
                        time_threshold_seconds=self._optional_int(
                            _find_text(zone, "timeThreshold")
                        ),
                        direction=_find_text(zone, "directionSensitivity", "direction"),
                        targets=targets,
                        alarm_confidence=confidence,
                        polygon=polygon,
                    )
                )

        periods = self._decode_xml_schedule(schedule_root)
        linkage_methods: list[str] = []
        for notification in notifications_root.iter():
            if _local_name(notification.tag) == "EventTriggerNotification":
                method = _find_text(notification, "notificationMethod")
                if method is not None:
                    linkage_methods.append(method)

        grid = None
        rows = self._optional_int(_find_text(root, "rowGranularity"))
        columns = self._optional_int(_find_text(root, "columnGranularity"))
        grid_map = _find_text(root, "gridMap")
        if rows and columns and grid_map is not None:
            grid = DetectionGrid(rows=rows, columns=columns, map=grid_map)
        return DetectionRuleConfig(
            kind=kind,
            channel_id=channel_id,
            enabled=bool(_as_bool(_find_text(root, "enabled"))),
            start_trigger_milliseconds=self._optional_int(_find_text(root, "startTriggerTime")),
            end_trigger_milliseconds=self._optional_int(_find_text(root, "endTriggerTime")),
            normalized_width=self._optional_int(_find_text(root, "normalizedScreenWidth")),
            normalized_height=self._optional_int(_find_text(root, "normalizedScreenHeight")),
            zones=zones,
            grid=grid,
            arming_schedule=Schedule(periods=periods),
            linkage_methods=linkage_methods,
            warning_light_duration_seconds=self._optional_int(
                _find_text(notifications_root, "whiteLightDurationTime")
            ),
        )

    @staticmethod
    def _decode_xml_schedule(root: StdET.Element) -> list[SchedulePeriod]:
        periods: list[SchedulePeriod] = []
        for block in root.iter():
            if _local_name(block.tag) != "TimeBlock":
                continue
            day_number = int(_find_text(block, "dayOfWeek") or "0")
            start = _find_text(block, "beginTime")
            end = _find_text(block, "endTime")
            if 1 <= day_number <= 7 and start is not None and end is not None:
                periods.append(
                    SchedulePeriod(days=[DAY_NAMES[day_number - 1]], start=start, end=end)
                )
        return periods

    async def get_camera_health(self) -> CameraHealth:
        status_response = await self._client.get(SYSTEM_STATUS_PATH)
        time_response = await self._client.get(SYSTEM_TIME_PATH)
        status = self._parse(status_response.content)
        time_root = self._parse(time_response.content)
        reported_text = _find_text(status, "currentDeviceTime")
        return CameraHealth(
            reported_at=datetime.fromisoformat(reported_text) if reported_text else None,
            uptime_seconds=self._optional_int(_find_text(status, "deviceUpTime")),
            cpu_percent=self._optional_int(_find_text(status, "cpuUtilization")),
            memory_percent=self._optional_int(_find_text(status, "memoryUsage")),
            memory_available_kb=self._optional_int(_find_text(status, "memoryAvailable")),
            total_reboots=self._optional_int(_find_text(status, "totalRebootCount")),
            time_mode=_find_text(time_root, "timeMode"),
            time_zone=_find_text(time_root, "timeZone"),
        )

    async def get_stream_profiles(self) -> list[StreamProfile]:
        response = await self._client.get(STREAMING_CHANNELS_PATH)
        root = self._parse(response.content)
        profiles: list[StreamProfile] = []
        for channel in root.iter():
            if _local_name(channel.tag) != "StreamingChannel":
                continue
            channel_id = self._optional_int(_find_text(channel, "id"))
            if channel_id is None:
                continue
            video = _find_element(channel, "Video")
            audio = _find_element(channel, "Audio")
            frame_rate = (
                self._optional_int(_find_text(video, "maxFrameRate")) if video is not None else None
            )
            profiles.append(
                StreamProfile(
                    id=channel_id,
                    enabled=bool(_as_bool(_find_text(channel, "enabled"))),
                    video_enabled=_as_bool(_find_text(video, "enabled"))
                    if video is not None
                    else None,
                    codec=_find_text(video, "videoCodecType") if video is not None else None,
                    width=self._optional_int(_find_text(video, "videoResolutionWidth"))
                    if video is not None
                    else None,
                    height=self._optional_int(_find_text(video, "videoResolutionHeight"))
                    if video is not None
                    else None,
                    rate_control=_find_text(video, "videoQualityControlType")
                    if video is not None
                    else None,
                    bitrate_kbps=self._optional_int(
                        _find_text(video, "constantBitRate", "vbrUpperCap")
                    )
                    if video is not None
                    else None,
                    frame_rate_fps=frame_rate / 100 if frame_rate is not None else None,
                    gov_length=self._optional_int(
                        _find_text(video, "GovLength", "keyFrameInterval")
                    )
                    if video is not None
                    else None,
                    audio_enabled=_as_bool(_find_text(audio, "enabled"))
                    if audio is not None
                    else None,
                    audio_codec=_find_text(audio, "audioCompressionType")
                    if audio is not None
                    else None,
                )
            )
        return profiles

    async def get_image_settings(self) -> ImageSettings:
        channel_id = await self._discover_channel("image")
        response = await self._client.get(f"/ISAPI/Image/channels/{channel_id}")
        root = self._parse(response.content)
        ircut = _find_element(root, "IrcutFilter")
        exposure = _find_element(root, "Exposure")
        color = _find_element(root, "Color")
        wdr = _find_element(root, "WDR")
        noise = _find_element(root, "NoiseReduce")
        general_noise = _find_element(noise, "GeneralMode") if noise is not None else None
        white_balance = _find_element(root, "WhiteBalance")
        dehaze = _find_element(root, "Dehaze")
        supplement = _find_element(root, "SupplementLight")
        ir_light = _find_element(supplement, "IRLight") if supplement is not None else None
        return ImageSettings(
            channel_id=int(_find_text(root, "id") or str(channel_id)),
            enabled=bool(_as_bool(_find_text(root, "enabled"))),
            ir_cut_mode=_find_text(ircut, "IrcutFilterType") if ircut is not None else None,
            night_to_day_level=self._optional_int(_find_text(ircut, "nightToDayLevel"))
            if ircut is not None
            else None,
            exposure_mode=_find_text(exposure, "ExposureType") if exposure is not None else None,
            shutter=_find_text(exposure, "ShutterLevel") if exposure is not None else None,
            gain=self._optional_int(_find_text(exposure, "GainLevel"))
            if exposure is not None
            else None,
            power_line_frequency=_find_text(root, "powerLineFrequencyMode"),
            brightness=self._optional_int(_find_text(color, "brightnessLevel"))
            if color is not None
            else None,
            contrast=self._optional_int(_find_text(color, "contrastLevel"))
            if color is not None
            else None,
            saturation=self._optional_int(_find_text(color, "saturationLevel"))
            if color is not None
            else None,
            sharpness=self._optional_int(_find_text(root, "SharpnessLevel")),
            white_balance_mode=_find_text(white_balance, "WhiteBalanceStyle")
            if white_balance is not None
            else None,
            wdr_mode=_find_text(wdr, "mode") if wdr is not None else None,
            wdr_level=self._optional_int(_find_text(wdr, "WDRLevel")) if wdr is not None else None,
            noise_reduction_mode=_find_text(noise, "mode") if noise is not None else None,
            noise_reduction_level=self._optional_int(_find_text(general_noise, "generalLevel"))
            if general_noise is not None
            else None,
            dehaze_mode=_find_text(dehaze, "mode") if dehaze is not None else None,
            dehaze_level=self._optional_int(_find_text(dehaze, "dehazeLevel"))
            if dehaze is not None
            else None,
            supplement_light_mode=_find_text(supplement, "supplementLightMode")
            if supplement is not None
            else None,
            ir_light_brightness=self._optional_int(_find_text(ir_light, "brightnessLevel"))
            if ir_light is not None
            else None,
        )

    async def get_storage_status(self) -> StorageStatus:
        response = await self._client.get(STORAGE_PATH)
        root = self._parse(response.content)
        volumes: list[StorageVolume] = []
        for node in root.iter():
            if _local_name(node.tag) not in {"hdd", "nas", "sdCard", "storageDevice"}:
                continue
            volumes.append(
                StorageVolume(
                    id=_find_text(node, "id"),
                    type=_local_name(node.tag),
                    status=_find_text(node, "status"),
                    capacity_bytes=self._optional_int(_find_text(node, "capacity")),
                    free_bytes=self._optional_int(_find_text(node, "freeSpace")),
                )
            )
        return StorageStatus(work_mode=_find_text(root, "workMode"), volumes=volumes)

    async def get_audio_alarm(self) -> AudioAlarmConfig:
        response = await self._client.get(AUDIO_ALARM_PATH)
        capabilities_response = await self._client.get(AUDIO_ALARM_CAPABILITIES_PATH)
        try:
            node = json.loads(response.text)["AudioAlarm"]
            capabilities = json.loads(capabilities_response.text).get("AudioAlarm", {})
            capability_document = json.loads(capabilities_response.text)
            capabilities = capability_document.get("AudioAlarmCap", capabilities)
            periods: list[SchedulePeriod] = []
            for day_entry in node.get("TimeRangeList", []):
                day_number = int(day_entry["week"])
                for item in day_entry.get("TimeRange", []):
                    periods.append(
                        SchedulePeriod(
                            days=[DAY_NAMES[day_number - 1]],
                            start=str(item["beginTime"]),
                            end=str(item["endTime"]),
                        )
                    )
            options_node = capabilities.get("audioID", capabilities.get("AudioID", {}))
            option_values = options_node.get("opt", []) if isinstance(options_node, dict) else []
            live_options = capabilities.get("audioTypeListCap", [])
            if isinstance(live_options, list):
                option_values = live_options
            options = [
                AudioOption(id=int(item["audioID"]), description=item.get("audioDescription"))
                for item in option_values
                if isinstance(item, dict) and "audioID" in item
            ]
            return AudioAlarmConfig(
                audio_id=int(node["audioID"]),
                volume=int(node["audioVolume"]),
                repetitions=int(node["alarmTimes"]),
                schedule=Schedule(periods=periods),
                audio_class=node.get("audioClass"),
                alert_audio_id=self._optional_int_value(node.get("alertAudioID")),
                custom_audio_id=self._optional_int_value(node.get("customAudioID")),
                available_sounds=options,
                custom_audio_supported=self._json_flag(capabilities, "isSupportCustomAudio"),
                test_supported=self._json_flag(capabilities, "isSupportAudioTest"),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, IndexError) as exc:
            raise error("isapi_error", "Camera returned malformed audio-alarm JSON") from exc

    async def get_two_way_audio(self) -> list[TwoWayAudioChannel]:
        response = await self._client.get(TWO_WAY_AUDIO_PATH)
        root = self._parse(response.content)
        channels: list[TwoWayAudioChannel] = []
        for node in root.iter():
            if _local_name(node.tag) not in {"TwoWayAudioChannel", "AudioChannel"}:
                continue
            channel_id = self._optional_int(_find_text(node, "id"))
            if channel_id is None:
                continue
            echo = None
            try:
                capabilities_response = await self._client.get(
                    f"/ISAPI/System/TwoWayAudio/channels/{channel_id}/capabilities"
                )
                capabilities = self._parse(capabilities_response.content)
                echo = _as_bool(_find_text(capabilities, "isSupportEchoCancellation"))
            except HikvisionMCPError as exc:
                if exc.code != "unsupported_capability":
                    raise
            channels.append(
                TwoWayAudioChannel(
                    id=channel_id,
                    enabled=bool(_as_bool(_find_text(node, "enabled"))),
                    codec=_find_text(node, "audioCompressionType", "codec"),
                    speaker_volume=self._optional_int(_find_text(node, "speakerVolume")),
                    noise_reduction=_as_bool(_find_text(node, "noisereduce", "noiseReduce")),
                    input_type=_find_text(node, "audioInputType"),
                    echo_cancellation_supported=echo,
                )
            )
        return channels

    @staticmethod
    def _optional_int_value(value: object) -> int | None:
        return int(str(value)) if value is not None else None

    @staticmethod
    def _json_flag(node: dict[str, object], name: str) -> bool:
        value = node.get(name, False)
        if isinstance(value, dict):
            value = value.get("value", value.get("default", False))
        return value is True or str(value).lower() == "true"

    @abstractmethod
    async def monitor_events(
        self,
        duration_seconds: float,
        max_events: int,
        event_types: set[str] | None = None,
    ) -> list[CameraEvent]: ...

    @abstractmethod
    async def set_warning_light(self, config: WarningLightConfig) -> AdapterState: ...

    @abstractmethod
    async def restore_warning_light(self, raw: str) -> AdapterState: ...


class GenericHikvisionAdapter(CameraAdapter):
    """Generic ISAPI adapter; model quirks belong in subclasses/registry entries."""

    def __init__(self, client: IsapiClient) -> None:
        self._client = client
        self._channel_cache = {}

    async def identity(self, alias: str) -> CameraIdentity:
        response = await self._client.get(DEVICE_INFO_PATH)
        root = self._parse(response.content)
        return CameraIdentity(
            alias=alias,
            manufacturer=_find_text(root, "manufacturer"),
            model=_find_text(root, "model"),
            firmware_version=_find_text(root, "firmwareVersion", "firmwareReleasedDate"),
            serial_number=_find_text(root, "serialNumber"),
        )

    async def capabilities(self, alias: str) -> CameraCapabilities:
        warning = CapabilitySupport(supported=False)
        intrusion = CapabilitySupport(supported=False)
        event_stream = CapabilitySupport(supported=False)
        detection_rules = CapabilitySupport(supported=False)
        detector_flags: dict[str, bool | int | str] = {}
        try:
            await self.get_warning_light()
            warning = CapabilitySupport(
                supported=True,
                readable=True,
                writable=True,
                details={
                    "schedule": True,
                    "frequency": True,
                    "duration_seconds": True,
                    "brightness": False,
                    "enabled": False,
                },
            )
        except HikvisionMCPError as exc:
            if exc.code != "unsupported_capability":
                raise
        try:
            current_intrusion = await self.get_intrusion_detection()
            intrusion = CapabilitySupport(
                supported=True,
                readable=True,
                writable=False,
                details={
                    "regions": len(current_intrusion.regions),
                    "arming_schedule": True,
                    "linkage": True,
                },
            )
        except HikvisionMCPError as exc:
            if exc.code != "unsupported_capability":
                raise
        try:
            response = await self._client.get(SYSTEM_CAPABILITIES_PATH)
            root = self._parse(response.content)
            detector_flags = {
                "motion": _find_text(root, "isSupportMotionDetection") == "true",
                "tamper": _find_text(root, "isSupportTamperDetection") == "true",
                "line_crossing": _find_text(root, "isSupportLineDetection") == "true",
                "intrusion": _find_text(root, "isSupportFieldDetection") == "true",
                "region_entrance": _find_text(root, "isSupportRegionEntrance") == "true",
                "region_exit": _find_text(root, "isSupportRegionExiting") == "true",
                "scene_change": _find_text(root, "isSupportSceneChangeDetection") == "true",
            }
            supported = _find_text(root, "isSupportSubscribeEvent") == "true"
            event_stream = CapabilitySupport(
                supported=supported,
                readable=supported,
                writable=False,
                details={"bounded_monitoring": supported},
            )
        except HikvisionMCPError as exc:
            if exc.code != "unsupported_capability":
                raise
        if any(detector_flags.values()):
            detection_rules = CapabilitySupport(
                supported=True,
                readable=True,
                writable=False,
                details=detector_flags,
            )
        if intrusion.supported and not detection_rules.supported:
            detection_rules = CapabilitySupport(
                supported=True,
                readable=True,
                writable=False,
                details={"general_rule_reader": True},
            )
        image_channel = await self._discover_channel("image")
        smart_channel = await self._discover_channel("smart_detection")
        if detection_rules.supported:
            detection_rules.details["channel_id"] = smart_channel
        return CameraCapabilities(
            camera=alias,
            warning_light=warning,
            intrusion_detection=intrusion,
            event_stream=event_stream,
            detection_rules=detection_rules,
            health=await self._probe_readable(SYSTEM_STATUS_PATH),
            stream_profiles=await self._probe_readable(STREAMING_CHANNELS_PATH),
            image_settings=await self._probe_readable(f"/ISAPI/Image/channels/{image_channel}"),
            storage=await self._probe_readable(STORAGE_PATH),
            audio_alarm=await self._probe_readable(AUDIO_ALARM_PATH),
            two_way_audio=await self._probe_readable(TWO_WAY_AUDIO_PATH),
        )

    async def _probe_readable(self, path: str) -> CapabilitySupport:
        try:
            await self._client.get(path)
            return CapabilitySupport(supported=True, readable=True, writable=False)
        except HikvisionMCPError as exc:
            if exc.code == "unsupported_capability":
                return CapabilitySupport(supported=False)
            raise

    async def get_warning_light(self) -> AdapterState:
        response = await self._client.get(WARNING_LIGHT_PATH)
        raw = response.text
        return AdapterState(semantic=self._decode_warning_light(raw), raw=raw)

    async def set_warning_light(self, config: WarningLightConfig) -> AdapterState:
        payload = self._encode_warning_light(config)
        await self._client.request(
            "PUT", WARNING_LIGHT_PATH, content=payload, content_type="application/json"
        )
        return await self.get_warning_light()

    async def restore_warning_light(self, raw: str) -> AdapterState:
        # Semantic parsing prevents arbitrary raw payload restore.
        self._decode_warning_light(raw)
        await self._client.request(
            "PUT",
            WARNING_LIGHT_PATH,
            content=raw.encode(),
            content_type="application/json",
        )
        return await self.get_warning_light()

    @staticmethod
    def _parse(content: bytes) -> StdET.Element:
        try:
            return SafeET.fromstring(content)
        except StdET.ParseError as exc:
            raise error("isapi_error", "Camera returned malformed XML") from exc

    def _decode_warning_light(self, raw: str) -> WarningLightConfig:
        try:
            document = json.loads(raw)
            node = document["WhiteLightAlarm"]
            periods: list[SchedulePeriod] = []
            for day_entry in node.get("TimeRangeList", []):
                day_number = int(day_entry["week"])
                day = DAY_NAMES[day_number - 1]
                for time_range in day_entry.get("TimeRange", []):
                    periods.append(
                        SchedulePeriod(
                            days=[day],
                            start=str(time_range["beginTime"]),
                            end=str(time_range["endTime"]),
                        )
                    )
            return WarningLightConfig(
                duration_seconds=int(node["durationTime"]),
                frequency=node["frequency"],
                schedule=Schedule(periods=periods),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, IndexError) as exc:
            raise error("isapi_error", "Camera returned malformed warning-light JSON") from exc

    @staticmethod
    def _encode_warning_light(config: WarningLightConfig) -> bytes:
        node: dict[str, object] = {}
        if config.duration_seconds is not None:
            node["durationTime"] = config.duration_seconds
        if config.frequency is not None:
            node["frequency"] = config.frequency
        if config.schedule is not None:
            day_numbers = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 7}
            ranges: dict[int, list[dict[str, object]]] = {
                day_number: [] for day_number in day_numbers.values()
            }
            for period in config.schedule.periods:
                for day in period.days:
                    day_ranges = ranges[day_numbers[day]]
                    day_ranges.append(
                        {
                            "id": len(day_ranges) + 1,
                            "beginTime": period.start,
                            "endTime": period.end,
                        }
                    )
            node["TimeRangeList"] = [
                {"week": day_number, "TimeRange": day_ranges}
                for day_number, day_ranges in ranges.items()
                if day_ranges
            ]
        return json.dumps({"WhiteLightAlarm": node}, separators=(",", ":")).encode()

    async def get_intrusion_detection(self) -> IntrusionDetectionConfig:
        channel_id = await self._discover_channel("smart_detection")
        endpoint = detection_endpoints(channel_id)[DetectionKind.INTRUSION]
        config_response = await self._client.get(endpoint.config)
        schedule_response = await self._client.get(endpoint.schedule)
        notifications_response = await self._client.get(endpoint.notifications)
        config_root = self._parse(config_response.content)
        schedule_root = self._parse(schedule_response.content)
        notifications_root = self._parse(notifications_response.content)

        regions: list[IntrusionRegion] = []
        valid_targets = {"all", "human", "vehicle", "others"}
        valid_confidence = {"low", "mediumLow", "mediumHigh", "high"}
        for region in config_root.iter():
            if _local_name(region.tag) != "FieldDetectionRegion":
                continue
            targets_text = _find_text(region, "detectionTarget") or ""
            targets = cast(
                list[Literal["all", "human", "vehicle", "others"]],
                [target for target in targets_text.split(",") if target in valid_targets],
            )
            confidence_text = _find_text(region, "alarmConfidence")
            confidence = cast(
                Literal["low", "mediumLow", "mediumHigh", "high"] | None,
                confidence_text if confidence_text in valid_confidence else None,
            )
            polygon: list[ImageCoordinate] = []
            for coordinate in region.iter():
                if _local_name(coordinate.tag) not in {"RegionCoordinates", "Coordinates"}:
                    continue
                x = _find_text(coordinate, "positionX")
                y = _find_text(coordinate, "positionY")
                if x is not None and y is not None:
                    polygon.append(ImageCoordinate(x=int(x), y=int(y)))
            regions.append(
                IntrusionRegion(
                    id=int(_find_text(region, "id") or "0"),
                    enabled=(_find_text(region, "enabled") or "false").lower() == "true",
                    sensitivity=int(_find_text(region, "sensitivityLevel") or "0"),
                    time_threshold_seconds=int(_find_text(region, "timeThreshold") or "0"),
                    targets=targets,
                    alarm_confidence=confidence,
                    polygon=polygon,
                )
            )

        periods: list[SchedulePeriod] = []
        for block in schedule_root.iter():
            if _local_name(block.tag) != "TimeBlock":
                continue
            day_number = int(_find_text(block, "dayOfWeek") or "0")
            start = _find_text(block, "beginTime")
            end = _find_text(block, "endTime")
            if 1 <= day_number <= 7 and start is not None and end is not None:
                periods.append(
                    SchedulePeriod(days=[DAY_NAMES[day_number - 1]], start=start, end=end)
                )

        linkage_methods: list[str] = []
        for notification in notifications_root.iter():
            if _local_name(notification.tag) != "EventTriggerNotification":
                continue
            method = _find_text(notification, "notificationMethod")
            if method is not None:
                linkage_methods.append(method)

        duration_text = _find_text(notifications_root, "whiteLightDurationTime")
        return IntrusionDetectionConfig(
            enabled=(_find_text(config_root, "enabled") or "false").lower() == "true",
            start_trigger_milliseconds=self._optional_int(
                _find_text(config_root, "startTriggerTime")
            ),
            end_trigger_milliseconds=self._optional_int(_find_text(config_root, "endTriggerTime")),
            regions=regions,
            arming_schedule=Schedule(periods=periods),
            linkage_methods=linkage_methods,
            warning_light_duration_seconds=self._optional_int(duration_text),
        )

    async def monitor_events(
        self,
        duration_seconds: float,
        max_events: int,
        event_types: set[str] | None = None,
    ) -> list[CameraEvent]:
        events: list[CameraEvent] = []
        buffer = b""
        start_token = b"<EventNotificationAlert"
        end_token = b"</EventNotificationAlert>"
        async for chunk in self._client.stream_bytes(ALERT_STREAM_PATH, duration_seconds):
            buffer += chunk
            while True:
                start = buffer.find(start_token)
                if start < 0:
                    buffer = buffer[-len(start_token) :]
                    break
                end = buffer.find(end_token, start)
                if end < 0:
                    buffer = buffer[start:]
                    break
                end += len(end_token)
                event = self._decode_event(buffer[start:end])
                buffer = buffer[end:]
                if event_types is None or event.event_type in event_types:
                    events.append(event)
                    if len(events) >= max_events:
                        return events
            if len(buffer) > 262_144:
                raise error("isapi_error", "Camera event frame exceeded the configured limit")
        return events

    def _decode_event(self, payload: bytes) -> CameraEvent:
        root = self._parse(payload)
        event_type = _find_text(root, "eventType")
        state = _find_text(root, "eventState")
        occurred_at = _find_text(root, "dateTime")
        if event_type is None or state not in {"active", "inactive"} or occurred_at is None:
            raise error("isapi_error", "Camera returned an incomplete event notification")
        try:
            timestamp = datetime.fromisoformat(occurred_at)
        except ValueError as exc:
            raise error("isapi_error", "Camera returned an invalid event timestamp") from exc
        channel_text = _find_text(root, "channelID")
        count_text = _find_text(root, "activePostCount")
        return CameraEvent(
            event_type=event_type,
            state=cast(Literal["active", "inactive"], state),
            occurred_at=timestamp,
            channel_id=self._optional_int(channel_text),
            description=_find_text(root, "eventDescription"),
            active_post_count=self._optional_int(count_text),
        )

    @staticmethod
    def _optional_int(value: str | None) -> int | None:
        return int(value) if value is not None else None
