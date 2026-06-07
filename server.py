"""Plex MCP Server — SSE and stdio transport entry point."""

import argparse
import asyncio
import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool
from plexapi.server import PlexServer
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount, Route

from auth import do_oauth_flow, ensure_token
from changelog import log_change
from config import get_plex_url, load_config

from tools import (
    artwork,
    collections,
    discovery,
    libraries,
    maintenance,
    movies,
    music,
    playback,
    playlists,
    server_admin,
    sessions,
    sync,
    shows,
    users,
    watch_state,
)

# ---------------------------------------------------------------------------
# Logging — never log the token
# ---------------------------------------------------------------------------

class _TokenFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = str(record.getMessage())
        if record.args:
            try:
                msg = msg % record.args
            except Exception:
                pass
        # Redact anything that looks like a Plex token (20-char alphanumeric)
        import re
        record.msg = re.sub(r'[A-Za-z0-9]{20,}', '[REDACTED]', str(record.msg))
        record.args = ()
        return True


def _setup_logging(stderr: bool = False) -> None:
    handler = logging.StreamHandler(sys.stderr if stderr else sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    handler.addFilter(_TokenFilter())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


# ---------------------------------------------------------------------------
# Plex manager
# ---------------------------------------------------------------------------

class PlexManager:
    plex: PlexServer | None = None
    config: dict = {}

    @classmethod
    def initialize(cls, config: dict, token: str) -> None:
        url = get_plex_url(config)
        cls.config = config
        cls.plex = PlexServer(url, token)

    @classmethod
    def get(cls) -> PlexServer:
        if cls.plex is None:
            raise RuntimeError("Plex server not initialized")
        return cls.plex

    @classmethod
    def reauthenticate(cls) -> str:
        new_token = do_oauth_flow(cls.config)
        cls.initialize(cls.config, new_token)
        return "Reauthentication complete — new token stored"


# ---------------------------------------------------------------------------
# MCP tool registry
# ---------------------------------------------------------------------------

_MODULES = [
    server_admin,
    libraries,
    movies,
    shows,
    music,
    artwork,
    collections,
    playlists,
    sessions,
    playback,
    users,
    discovery,
    watch_state,
    maintenance,
    sync,
]

_REAUTHENTICATE_TOOL = Tool(
    name="reauthenticate",
    description=(
        "Trigger a fresh Plex OAuth login. Use when the Plex token has expired or "
        "you get authentication errors. Opens a browser to Plex.tv to log in again."
    ),
    inputSchema={"type": "object", "properties": {}},
)

_CHANGELOG_TOOL = Tool(
    name="get_changelog",
    description="Retrieve recent entries from the write-operation change log",
    inputSchema={
        "type": "object",
        "properties": {
            "lines": {"type": "integer", "description": "Last N entries to return (default 50)", "default": 50},
        },
    },
)

_DISPATCH: dict = {}


def _build_registry() -> list[Tool]:
    all_tools: list[Tool] = [_REAUTHENTICATE_TOOL, _CHANGELOG_TOOL]
    for module in _MODULES:
        for tool in module.TOOLS:
            all_tools.append(tool)
            _DISPATCH[tool.name] = module.handle_tool
    return all_tools


ALL_TOOLS = _build_registry()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp_server = Server("plex-mcp")


@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    return ALL_TOOLS


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[TextContent]:
    args = arguments or {}
    plex = PlexManager.get()

    # Special built-in tools
    if name == "reauthenticate":
        try:
            result = await asyncio.to_thread(PlexManager.reauthenticate)
            log_change("reauthenticate", "plex-server", "OAuth flow completed")
            return [TextContent(type="text", text=result)]
        except Exception as exc:
            logger.error("Reauthentication failed: %s", exc)
            return [TextContent(type="text", text=f"Reauthentication failed: {exc}")]

    if name == "get_changelog":
        from config import CHANGES_LOG
        n = int(args.get("lines", 50))

        def _read():
            if not CHANGES_LOG.exists():
                return "No changelog entries yet"
            lines = CHANGES_LOG.read_text().splitlines()
            return "\n".join(lines[-n:])

        result = await asyncio.to_thread(_read)
        return [TextContent(type="text", text=result)]

    # Route to module handler
    handler = _DISPATCH.get(name)
    if handler is None:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    try:
        return await handler(name, args, plex)
    except Exception as exc:
        logger.exception("Unhandled error in tool %s", name)
        return [TextContent(type="text", text=f"Error executing {name}: {exc}")]


# ---------------------------------------------------------------------------
# SSE transport / Starlette app
# ---------------------------------------------------------------------------

sse_transport = SseServerTransport("/messages/")


async def _sse_endpoint(request: Request) -> None:
    async with sse_transport.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await mcp_server.run(
            streams[0],
            streams[1],
            mcp_server.create_initialization_options(),
        )


async def _handle_post_message(request: Request) -> None:
    await sse_transport.handle_post_message(
        request.scope, request.receive, request._send
    )


starlette_app = Starlette(
    debug=False,
    routes=[
        Route("/sse", endpoint=_sse_endpoint),
        Route("/messages/", endpoint=_handle_post_message, methods=["POST"]),
        Mount("/messages", app=sse_transport.handle_post_message),
    ],
)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _run_stdio() -> None:
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read_stream, write_stream):
        await mcp_server.run(
            read_stream,
            write_stream,
            mcp_server.create_initialization_options(),
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdio", action="store_true", help="Run in stdio mode for SSH/Claude Desktop")
    args = parser.parse_args()

    _setup_logging(stderr=args.stdio)
    logger.info("Plex MCP Server starting")

    config = load_config()
    logger.info("Config loaded from ~/.config/plex-mcp/config.json")

    logger.info("Validating Plex token...")
    token = ensure_token(config)

    logger.info("Connecting to Plex at %s", get_plex_url(config))
    PlexManager.initialize(config, token)

    plex = PlexManager.get()
    logger.info(
        "Connected to Plex: %s v%s (machine=%s)",
        plex.friendlyName,
        plex.version,
        plex.machineIdentifier,
    )

    if args.stdio:
        logger.info("Plex MCP Server ready — stdio mode")
        asyncio.run(_run_stdio())
    else:
        logger.info("Plex MCP Server ready — listening on 0.0.0.0:8000 (SSE)")
        logger.info("Claude Desktop endpoint: http://YOUR_SERVER_IP:8000/sse")
        logger.info("Total tools registered: %d", len(ALL_TOOLS))
        uvicorn.run(
            starlette_app,
            host="0.0.0.0",
            port=8000,
            log_level="info",
            access_log=False,
        )


if __name__ == "__main__":
    main()
