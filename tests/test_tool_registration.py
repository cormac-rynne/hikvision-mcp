from typing import cast

from hikvision_mcp.server import create_mcp_server
from hikvision_mcp.service import CameraService


async def test_expanded_tools_are_registered() -> None:
    server = create_mcp_server(cast(CameraService, object()))
    tools = await server.list_tools()
    by_name = {tool.name: tool for tool in tools}
    expected = {
        "get_detection_rules",
        "get_camera_health",
        "get_stream_profiles",
        "get_image_settings",
        "get_storage_status",
        "get_audio_alarm",
        "get_two_way_audio",
    }
    assert expected <= by_name.keys()
    schema = by_name["get_detection_rules"].input_schema
    kinds = schema["$defs"]["DetectionKind"]["enum"]
    assert "motion" in kinds
    assert "scene_change" in kinds
