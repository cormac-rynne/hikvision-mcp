import httpx
from pydantic import SecretStr

from hikvision_mcp.adapter import GenericHikvisionAdapter
from hikvision_mcp.isapi import IsapiClient
from hikvision_mcp.models import CameraConfig, CameraCredentials
from hikvision_mcp.registry import AdapterRegistration, AdapterRegistry


async def test_registry_selects_adapter_from_semantic_identity() -> None:
    body = (
        b"<DeviceInfo><model>ReferenceCam</model>"
        b"<firmwareVersion>V1.2.3</firmwareVersion></DeviceInfo>"
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"Content-Type": "application/xml"})

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
    selected = False

    def factory(value: IsapiClient) -> GenericHikvisionAdapter:
        nonlocal selected
        selected = True
        return GenericHikvisionAdapter(value)

    registry = AdapterRegistry()
    registry.register(
        AdapterRegistration(
            name="reference-v1",
            matches=lambda identity: (
                identity.model == "ReferenceCam"
                and (identity.firmware_version or "").startswith("V1.")
            ),
            factory=factory,
        )
    )
    try:
        adapter = await registry.create(client, "test_camera")
        assert selected is True
        assert isinstance(adapter, GenericHikvisionAdapter)
    finally:
        await client.close()
