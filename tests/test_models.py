import pytest
from pydantic import ValidationError

from hikvision_mcp.models import (
    AppConfig,
    CameraConfig,
    PermissionLevel,
    Schedule,
    SchedulePeriod,
    WarningLightConfig,
)


def test_alias_validation() -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate(
            {
                "cameras": {
                    "Front Door": {
                        "host": "192.0.2.1",
                        "username_env": "USER",
                        "password_env": "PASSWORD",
                    }
                }
            }
        )


def test_schedule_allows_cross_midnight() -> None:
    schedule = Schedule(periods=[SchedulePeriod(days=["mon", "tue"], start="23:00", end="06:00")])
    assert schedule.periods[0].end == "06:00"


def test_warning_duration_range() -> None:
    with pytest.raises(ValidationError):
        WarningLightConfig(duration_seconds=61)


def test_schedule_allows_camera_end_of_day() -> None:
    schedule = Schedule(periods=[SchedulePeriod(days=["sun"], start="00:00", end="24:00")])
    assert schedule.periods[0].end == "24:00"


def test_camera_defaults_are_read_only_with_automatic_channels() -> None:
    camera = CameraConfig(
        host="192.0.2.1",
        username_env="USER",
        password_env="PASSWORD",  # noqa: S106
    )
    assert camera.policy.max_level is PermissionLevel.READ
    assert camera.channels.video_input == "auto"
    assert camera.channels.image == "auto"
    assert camera.channels.smart_detection == "auto"


def test_camera_channel_overrides_are_validated() -> None:
    camera = CameraConfig(
        host="192.0.2.1",
        username_env="USER",
        password_env="PASSWORD",  # noqa: S106
        channels={"video_input": 4, "image": 7, "smart_detection": 9},
    )
    assert camera.channels.video_input == 4
    with pytest.raises(ValidationError):
        CameraConfig(
            host="192.0.2.1",
            username_env="USER",
            password_env="PASSWORD",  # noqa: S106
            channels={"video_input": 0},
        )
