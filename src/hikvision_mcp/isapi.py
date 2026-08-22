from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Final

import httpx

from .errors import HikvisionMCPError, error
from .models import CameraConfig, CameraCredentials

ISAPI_PATH: Final = re.compile(
    r"^/ISAPI/[A-Za-z0-9._~!$&'()*+,;=:@%/-]+(?:\?[A-Za-z0-9._~!$&'()*+,;=:@%/?-]*)?$"
)


@dataclass(frozen=True)
class IsapiResponse:
    status_code: int
    content: bytes
    content_type: str

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


class IsapiClient:
    """Bound-host async ISAPI client with digest auth and bounded responses."""

    def __init__(
        self,
        camera: CameraConfig,
        credentials: CameraCredentials,
        *,
        timeout_seconds: float = 8.0,
        max_response_bytes: int = 2_000_000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._camera = camera
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._client = httpx.AsyncClient(
            base_url=camera.base_url,
            auth=httpx.DigestAuth(credentials.username, credentials.password.get_secret_value()),
            verify=camera.verify_tls,
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            follow_redirects=False,
        )

    async def __aenter__(self) -> IsapiClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def camera(self) -> CameraConfig:
        return self._camera

    async def get(self, path: str) -> IsapiResponse:
        return await self.request("GET", path)

    async def request(
        self,
        method: str,
        path: str,
        *,
        content: bytes | None = None,
        content_type: str = "application/xml",
    ) -> IsapiResponse:
        method = method.upper()
        self._validate_path(path)
        try:
            async with self._client.stream(
                method,
                path,
                content=content,
                headers={"Content-Type": content_type} if content is not None else None,
            ) as response:
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self._max_response_bytes:
                        raise error("isapi_error", "Camera response exceeded the configured limit")
                    chunks.append(chunk)
                body = b"".join(chunks)
        except HikvisionMCPError:
            raise
        except httpx.TimeoutException as exc:
            raise error("timeout", "Camera request timed out") from exc
        except httpx.ConnectError as exc:
            raise error("camera_offline", "Camera could not be reached") from exc
        except httpx.HTTPError as exc:
            raise error("isapi_error", f"Camera request failed: {type(exc).__name__}") from exc

        self._raise_for_status(response, method, path)
        return IsapiResponse(
            status_code=response.status_code,
            content=body,
            content_type=response.headers.get("content-type", "application/octet-stream"),
        )

    async def stream_bytes(self, path: str, duration_seconds: float) -> AsyncIterator[bytes]:
        """Yield a bounded GET response without buffering an indefinite alert stream."""
        self._validate_path(path)
        size = 0
        try:
            async with asyncio.timeout(duration_seconds):
                async with self._client.stream(
                    "GET",
                    path,
                    timeout=httpx.Timeout(
                        connect=self._timeout_seconds,
                        read=None,
                        write=self._timeout_seconds,
                        pool=self._timeout_seconds,
                    ),
                ) as response:
                    self._raise_for_status(response, "GET", path)
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self._max_response_bytes:
                            raise error(
                                "isapi_error", "Camera response exceeded the configured limit"
                            )
                        yield chunk
        except TimeoutError:
            return
        except HikvisionMCPError:
            raise
        except httpx.TimeoutException as exc:
            raise error("timeout", "Camera request timed out") from exc
        except httpx.ConnectError as exc:
            raise error("camera_offline", "Camera could not be reached") from exc
        except httpx.HTTPError as exc:
            raise error("isapi_error", f"Camera request failed: {type(exc).__name__}") from exc

    @staticmethod
    def _validate_path(path: str) -> None:
        if not ISAPI_PATH.fullmatch(path):
            raise error("prohibited_operation", "ISAPI path must be a local /ISAPI/ path")

    @staticmethod
    def _raise_for_status(response: httpx.Response, method: str, path: str) -> None:
        if response.status_code in {401, 403}:
            raise error("authentication_failed", "Camera rejected the configured credentials")
        if response.status_code == 404:
            raise error("unsupported_capability", f"Camera does not expose {path}", path=path)
        if response.is_error:
            raise error(
                "camera_rejected_configuration" if method != "GET" else "isapi_error",
                f"Camera returned HTTP {response.status_code}",
                status_code=response.status_code,
            )
