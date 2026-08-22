from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

ALIAS_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class PermissionLevel(IntEnum):
    DISCOVERY = 0
    READ = 1
    OPERATE = 2
    CONFIGURE = 3
    DEVELOPER = 4


class CameraPolicy(BaseModel):
    max_level: PermissionLevel = PermissionLevel.READ


type ChannelSelector = Annotated[int, Field(ge=1)] | Literal["auto"]


class CameraChannels(BaseModel):
    """Channel selection overrides; auto discovers a channel and safely falls back to 1."""

    model_config = ConfigDict(extra="forbid")
    video_input: ChannelSelector = "auto"
    image: ChannelSelector = "auto"
    smart_detection: ChannelSelector = "auto"


class CameraConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str
    port: int = Field(default=80, ge=1, le=65535)
    scheme: Literal["http", "https"] = "http"
    username_env: str
    password_env: str
    verify_tls: bool = True
    channels: CameraChannels = Field(default_factory=CameraChannels)
    policy: CameraPolicy = Field(default_factory=CameraPolicy)

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"


class ServerPolicy(BaseModel):
    default_level: PermissionLevel = PermissionLevel.READ
    enable_raw_get: bool = False
    enable_raw_writes: bool = False
    proposal_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    tools: dict[str, PermissionLevel] = Field(default_factory=dict)


class HttpConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)


class AppConfig(BaseModel):
    database_path: str = "hikvision-mcp.sqlite3"
    policy: ServerPolicy = Field(default_factory=ServerPolicy)
    http: HttpConfig = Field(default_factory=HttpConfig)
    cameras: dict[str, CameraConfig] = Field(default_factory=dict)

    @field_validator("cameras")
    @classmethod
    def validate_aliases(cls, value: dict[str, CameraConfig]) -> dict[str, CameraConfig]:
        invalid = [alias for alias in value if not ALIAS_RE.fullmatch(alias)]
        if invalid:
            raise ValueError(f"Invalid camera aliases: {', '.join(invalid)}")
        return value


class CameraCredentials(BaseModel):
    username: str
    password: SecretStr


class CameraIdentity(BaseModel):
    alias: str
    manufacturer: str | None = None
    model: str | None = None
    firmware_version: str | None = None
    serial_number: str | None = None


class CapabilitySupport(BaseModel):
    supported: bool
    readable: bool = False
    writable: bool = False
    details: dict[str, bool | int | str] = Field(default_factory=dict)


class CameraCapabilities(BaseModel):
    camera: str
    identity: CapabilitySupport = Field(
        default_factory=lambda: CapabilitySupport(supported=True, readable=True)
    )
    warning_light: CapabilitySupport = Field(
        default_factory=lambda: CapabilitySupport(supported=False)
    )
    intrusion_detection: CapabilitySupport = Field(
        default_factory=lambda: CapabilitySupport(supported=False)
    )
    event_stream: CapabilitySupport = Field(
        default_factory=lambda: CapabilitySupport(supported=False)
    )
    detection_rules: CapabilitySupport = Field(
        default_factory=lambda: CapabilitySupport(supported=False)
    )
    health: CapabilitySupport = Field(default_factory=lambda: CapabilitySupport(supported=False))
    stream_profiles: CapabilitySupport = Field(
        default_factory=lambda: CapabilitySupport(supported=False)
    )
    image_settings: CapabilitySupport = Field(
        default_factory=lambda: CapabilitySupport(supported=False)
    )
    storage: CapabilitySupport = Field(default_factory=lambda: CapabilitySupport(supported=False))
    audio_alarm: CapabilitySupport = Field(
        default_factory=lambda: CapabilitySupport(supported=False)
    )
    two_way_audio: CapabilitySupport = Field(
        default_factory=lambda: CapabilitySupport(supported=False)
    )
    ptz: CapabilitySupport = Field(default_factory=lambda: CapabilitySupport(supported=False))
    probed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SchedulePeriod(BaseModel):
    days: list[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]]
    start: str
    end: str

    @field_validator("days")
    @classmethod
    def unique_days(cls, value: list[str]) -> list[str]:
        if not value or len(value) != len(set(value)):
            raise ValueError("days must be non-empty and unique")
        return value

    @field_validator("start", "end")
    @classmethod
    def validate_time(cls, value: str) -> str:
        if value == "24:00":
            return value
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError as exc:
            raise ValueError("time must use HH:MM in 24-hour format") from exc
        return value


class Schedule(BaseModel):
    periods: list[SchedulePeriod] = Field(default_factory=list)

    @model_validator(mode="after")
    def no_exact_duplicates(self) -> Schedule:
        keys = [(tuple(period.days), period.start, period.end) for period in self.periods]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate schedule periods are not allowed")
        return self


class WarningLightConfig(BaseModel):
    duration_seconds: Annotated[int | None, Field(ge=1, le=60)] = None
    frequency: Literal["high", "medium", "low", "normallyOn"] | None = None
    schedule: Schedule | None = None

    def merge(self, patch: WarningLightConfig) -> WarningLightConfig:
        return self.model_copy(update=patch.model_dump(exclude_unset=True))


class ImageCoordinate(BaseModel):
    x: Annotated[int, Field(ge=0, le=1000)]
    y: Annotated[int, Field(ge=0, le=1000)]


class IntrusionRegion(BaseModel):
    id: Annotated[int, Field(ge=1)]
    enabled: bool
    sensitivity: Annotated[int, Field(ge=1, le=100)]
    time_threshold_seconds: Annotated[int, Field(ge=0, le=10)]
    targets: list[Literal["all", "human", "vehicle", "others"]] = Field(default_factory=list)
    alarm_confidence: Literal["low", "mediumLow", "mediumHigh", "high"] | None = None
    polygon: list[ImageCoordinate] = Field(default_factory=list)


class IntrusionDetectionConfig(BaseModel):
    enabled: bool
    start_trigger_milliseconds: Annotated[int | None, Field(ge=0)] = None
    end_trigger_milliseconds: Annotated[int | None, Field(ge=0)] = None
    regions: list[IntrusionRegion] = Field(default_factory=list)
    arming_schedule: Schedule = Field(default_factory=Schedule)
    linkage_methods: list[str] = Field(default_factory=list)
    warning_light_duration_seconds: Annotated[int | None, Field(ge=0)] = None


class DetectionKind(StrEnum):
    MOTION = "motion"
    TAMPER = "tamper"
    LINE_CROSSING = "line_crossing"
    INTRUSION = "intrusion"
    REGION_ENTRANCE = "region_entrance"
    REGION_EXIT = "region_exit"
    SCENE_CHANGE = "scene_change"


class DetectionGrid(BaseModel):
    rows: Annotated[int, Field(ge=1)]
    columns: Annotated[int, Field(ge=1)]
    map: str


class DetectionZone(BaseModel):
    id: Annotated[int, Field(ge=1)]
    enabled: bool | None = None
    sensitivity: Annotated[int | None, Field(ge=0, le=100)] = None
    time_threshold_seconds: Annotated[int | None, Field(ge=0)] = None
    direction: str | None = None
    targets: list[Literal["all", "human", "vehicle", "others"]] = Field(default_factory=list)
    alarm_confidence: Literal["low", "mediumLow", "mediumHigh", "high"] | None = None
    polygon: list[ImageCoordinate] = Field(default_factory=list)


class DetectionRuleConfig(BaseModel):
    kind: DetectionKind
    channel_id: Annotated[int, Field(ge=1)] = 1
    enabled: bool
    start_trigger_milliseconds: Annotated[int | None, Field(ge=0)] = None
    end_trigger_milliseconds: Annotated[int | None, Field(ge=0)] = None
    normalized_width: Annotated[int | None, Field(ge=1)] = None
    normalized_height: Annotated[int | None, Field(ge=1)] = None
    zones: list[DetectionZone] = Field(default_factory=list)
    grid: DetectionGrid | None = None
    arming_schedule: Schedule = Field(default_factory=Schedule)
    linkage_methods: list[str] = Field(default_factory=list)
    warning_light_duration_seconds: Annotated[int | None, Field(ge=0)] = None


class DetectionRuleRead(BaseModel):
    kind: DetectionKind
    supported: bool
    rule: DetectionRuleConfig | None = None
    unavailable_parts: list[Literal["configuration", "schedule", "linkage"]] = Field(
        default_factory=list
    )


class CameraHealth(BaseModel):
    reported_at: datetime | None = None
    uptime_seconds: Annotated[int | None, Field(ge=0)] = None
    cpu_percent: Annotated[int | None, Field(ge=0, le=100)] = None
    memory_percent: Annotated[int | None, Field(ge=0, le=100)] = None
    memory_available_kb: Annotated[int | None, Field(ge=0)] = None
    total_reboots: Annotated[int | None, Field(ge=0)] = None
    time_mode: str | None = None
    time_zone: str | None = None


class StreamProfile(BaseModel):
    id: Annotated[int, Field(ge=1)]
    enabled: bool
    video_enabled: bool | None = None
    codec: str | None = None
    width: Annotated[int | None, Field(ge=1)] = None
    height: Annotated[int | None, Field(ge=1)] = None
    rate_control: str | None = None
    bitrate_kbps: Annotated[int | None, Field(ge=0)] = None
    frame_rate_fps: Annotated[float | None, Field(ge=0)] = None
    gov_length: Annotated[int | None, Field(ge=0)] = None
    audio_enabled: bool | None = None
    audio_codec: str | None = None


class ImageSettings(BaseModel):
    channel_id: Annotated[int, Field(ge=1)]
    enabled: bool
    ir_cut_mode: str | None = None
    night_to_day_level: int | None = None
    exposure_mode: str | None = None
    shutter: str | None = None
    gain: int | None = None
    power_line_frequency: str | None = None
    brightness: int | None = None
    contrast: int | None = None
    saturation: int | None = None
    sharpness: int | None = None
    white_balance_mode: str | None = None
    wdr_mode: str | None = None
    wdr_level: int | None = None
    noise_reduction_mode: str | None = None
    noise_reduction_level: int | None = None
    dehaze_mode: str | None = None
    dehaze_level: int | None = None
    supplement_light_mode: str | None = None
    ir_light_brightness: int | None = None


class StorageVolume(BaseModel):
    id: str | None = None
    type: str | None = None
    status: str | None = None
    capacity_bytes: Annotated[int | None, Field(ge=0)] = None
    free_bytes: Annotated[int | None, Field(ge=0)] = None


class StorageStatus(BaseModel):
    work_mode: str | None = None
    volumes: list[StorageVolume] = Field(default_factory=list)


class AudioOption(BaseModel):
    id: int
    description: str | None = None


class AudioAlarmConfig(BaseModel):
    audio_id: int
    volume: Annotated[int, Field(ge=1, le=100)]
    repetitions: Annotated[int, Field(ge=1)]
    schedule: Schedule = Field(default_factory=Schedule)
    audio_class: str | None = None
    alert_audio_id: int | None = None
    custom_audio_id: int | None = None
    available_sounds: list[AudioOption] = Field(default_factory=list)
    custom_audio_supported: bool = False
    test_supported: bool = False


class TwoWayAudioChannel(BaseModel):
    id: Annotated[int, Field(ge=1)]
    enabled: bool
    codec: str | None = None
    speaker_volume: Annotated[int | None, Field(ge=0, le=100)] = None
    noise_reduction: bool | None = None
    input_type: str | None = None
    echo_cancellation_supported: bool | None = None


class CameraEvent(BaseModel):
    event_type: str
    state: Literal["active", "inactive"]
    occurred_at: datetime
    channel_id: int | None = None
    description: str | None = None
    active_post_count: Annotated[int | None, Field(ge=0)] = None


class ChangeProposal(BaseModel):
    id: str
    camera_alias: str
    operation: str
    request: dict[str, object]
    current_semantic: dict[str, object]
    current_raw: str | None = None
    created_at: datetime
    expires_at: datetime
    status: Literal["pending", "approved", "rejected", "expired", "applied", "failed", "cancelled"]


class ChangeResult(BaseModel):
    status: Literal["applied"] = "applied"
    change_id: str
    camera: str
    verified: bool
