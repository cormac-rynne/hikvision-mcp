from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import SecretStr, ValidationError

from .errors import error
from .models import AppConfig, CameraConfig, CameraCredentials


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    try:
        with config_path.open("rb") as stream:
            raw = tomllib.load(stream)
        return AppConfig.model_validate(raw)
    except FileNotFoundError as exc:
        raise error("invalid_configuration", f"Config file not found: {config_path}") from exc
    except (tomllib.TOMLDecodeError, ValidationError) as exc:
        raise error("invalid_configuration", f"Invalid config: {exc}") from exc


def resolve_credentials(camera: CameraConfig) -> CameraCredentials:
    username = os.environ.get(camera.username_env)
    password = os.environ.get(camera.password_env)
    if not username or not password:
        missing = [
            name
            for name, value in ((camera.username_env, username), (camera.password_env, password))
            if not value
        ]
        raise error(
            "invalid_configuration",
            f"Missing camera credential environment variable(s): {', '.join(missing)}",
        )
    return CameraCredentials(username=username, password=SecretStr(password))
