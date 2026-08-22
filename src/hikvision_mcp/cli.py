from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Annotated, Literal

import typer

from .config import load_config
from .server import create_mcp_server
from .service import CameraService
from .storage import Store

app = typer.Typer(no_args_is_help=True, help="Safe Hikvision Camera MCP server")
config_app = typer.Typer(no_args_is_help=True)
camera_app = typer.Typer(no_args_is_help=True)
app.add_typer(config_app, name="config")
app.add_typer(camera_app, name="camera")


def _service(config_path: Path) -> CameraService:
    config = load_config(config_path)
    store = Store(config.database_path)
    asyncio.run(store.initialize())
    return CameraService(config, store)


@app.command()
def serve(
    transport: Annotated[Literal["stdio", "streamable-http"], typer.Option()] = "stdio",
    config: Annotated[Path, typer.Option(exists=True, dir_okay=False)] = Path("config.toml"),
    log_level: Annotated[str, typer.Option()] = "INFO",
) -> None:
    """Start the MCP server over stdio or local Streamable HTTP."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    service = _service(config)
    mcp = create_mcp_server(service)
    if transport == "stdio":
        mcp.run("stdio")
    else:
        mcp.run(
            "streamable-http",
            host=service.config.http.host,
            port=service.config.http.port,
            stateless_http=True,
            json_response=True,
        )


@config_app.command("validate")
def validate_config(
    config: Annotated[Path, typer.Option(exists=True, dir_okay=False)] = Path("config.toml"),
) -> None:
    """Validate configuration without contacting cameras."""
    loaded = load_config(config)
    typer.echo(f"Valid configuration: {len(loaded.cameras)} camera(s)")


@camera_app.command("test")
def test_camera(
    alias: str,
    config: Annotated[Path, typer.Option(exists=True, dir_okay=False)] = Path("config.toml"),
) -> None:
    """Test camera authentication and print non-secret identity."""
    result = asyncio.run(_service(config).get_camera_identity(alias))
    typer.echo(result)


@camera_app.command("capabilities")
def camera_capabilities(
    alias: str,
    config: Annotated[Path, typer.Option(exists=True, dir_okay=False)] = Path("config.toml"),
) -> None:
    """Probe semantic camera capabilities."""
    result = asyncio.run(_service(config).get_capabilities(alias))
    typer.echo(result)


if __name__ == "__main__":
    app()
