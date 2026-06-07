import asyncio
import json
import logging

from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

TOOLS = [
    Tool(
        name="playback_clients",
        description="List all available Plex client devices (active and recently connected)",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="playback_play",
        description="Resume/unpause playback on a Plex client",
        inputSchema={
            "type": "object",
            "properties": {
                "client_name": {"type": "string", "description": "Client name from playback_clients"},
            },
            "required": ["client_name"],
        },
    ),
    Tool(
        name="playback_pause",
        description="Pause playback on a Plex client",
        inputSchema={
            "type": "object",
            "properties": {
                "client_name": {"type": "string"},
            },
            "required": ["client_name"],
        },
    ),
    Tool(
        name="playback_stop",
        description="Stop playback on a Plex client",
        inputSchema={
            "type": "object",
            "properties": {
                "client_name": {"type": "string"},
            },
            "required": ["client_name"],
        },
    ),
    Tool(
        name="playback_seek",
        description="Seek to a position during playback",
        inputSchema={
            "type": "object",
            "properties": {
                "client_name": {"type": "string"},
                "offset_ms": {
                    "type": "integer",
                    "description": "Position to seek to in milliseconds",
                },
                "offset_seconds": {
                    "type": "integer",
                    "description": "Position to seek to in seconds (alternative to offset_ms)",
                },
            },
            "required": ["client_name"],
        },
    ),
    Tool(
        name="playback_start_media",
        description=(
            "Start playing a specific media item on a Plex client. "
            "Provide the rating_key of the item and the client name."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "client_name": {"type": "string"},
                "rating_key": {"type": "string", "description": "Rating key of the item to play"},
                "offset_ms": {
                    "type": "integer",
                    "description": "Start position in milliseconds (default 0)",
                    "default": 0,
                },
            },
            "required": ["client_name", "rating_key"],
        },
    ),
    Tool(
        name="playback_skip_next",
        description="Skip to next item in a Plex client queue",
        inputSchema={
            "type": "object",
            "properties": {
                "client_name": {"type": "string"},
            },
            "required": ["client_name"],
        },
    ),
    Tool(
        name="playback_skip_prev",
        description="Skip to previous item in a Plex client queue",
        inputSchema={
            "type": "object",
            "properties": {
                "client_name": {"type": "string"},
            },
            "required": ["client_name"],
        },
    ),
    Tool(
        name="playback_set_volume",
        description="Set the volume level on a Plex client (0-100)",
        inputSchema={
            "type": "object",
            "properties": {
                "client_name": {"type": "string"},
                "volume": {"type": "integer", "description": "Volume level 0-100"},
            },
            "required": ["client_name", "volume"],
        },
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


def _text(data) -> list[TextContent]:
    if isinstance(data, str):
        return [TextContent(type="text", text=data)]
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _get_client(plex, name: str):
    client = plex.client(name)
    client.connect()
    return client


async def handle_tool(name: str, args: dict, plex) -> list[TextContent]:
    try:
        if name == "playback_clients":
            return await _list_clients(plex)
        if name == "playback_play":
            return await _play(plex, args)
        if name == "playback_pause":
            return await _pause(plex, args)
        if name == "playback_stop":
            return await _stop(plex, args)
        if name == "playback_seek":
            return await _seek(plex, args)
        if name == "playback_start_media":
            return await _start_media(plex, args)
        if name == "playback_skip_next":
            return await _skip_next(plex, args)
        if name == "playback_skip_prev":
            return await _skip_prev(plex, args)
        if name == "playback_set_volume":
            return await _set_volume(plex, args)
    except Exception as exc:
        logger.exception("Error in playback tool %s", name)
        return _text(f"Error: {exc}")
    return _text(f"Unknown tool: {name}")


async def _list_clients(plex) -> list[TextContent]:
    def _get():
        clients = plex.clients()
        return [
            {
                "name": c.title,
                "product": c.product,
                "platform": c.platform,
                "device": c.device,
                "address": c.address,
                "port": c.port,
                "version": c.version,
                "state": getattr(c, "state", None),
                "machine_identifier": c.machineIdentifier,
            }
            for c in clients
        ]

    return _text(await asyncio.to_thread(_get))


async def _play(plex, args: dict) -> list[TextContent]:
    def _do():
        client = _get_client(plex, args["client_name"])
        client.play()
        return f"Play command sent to '{args['client_name']}'"

    return _text(await asyncio.to_thread(_do))


async def _pause(plex, args: dict) -> list[TextContent]:
    def _do():
        client = _get_client(plex, args["client_name"])
        client.pause()
        return f"Pause command sent to '{args['client_name']}'"

    return _text(await asyncio.to_thread(_do))


async def _stop(plex, args: dict) -> list[TextContent]:
    def _do():
        client = _get_client(plex, args["client_name"])
        client.stop()
        return f"Stop command sent to '{args['client_name']}'"

    return _text(await asyncio.to_thread(_do))


async def _seek(plex, args: dict) -> list[TextContent]:
    offset_ms = args.get("offset_ms")
    if offset_ms is None:
        offset_ms = int(args.get("offset_seconds", 0)) * 1000

    def _do():
        client = _get_client(plex, args["client_name"])
        client.seekTo(offset_ms)
        return f"Seeked to {offset_ms}ms on '{args['client_name']}'"

    return _text(await asyncio.to_thread(_do))


async def _start_media(plex, args: dict) -> list[TextContent]:
    rating_key = args["rating_key"]
    offset_ms = int(args.get("offset_ms", 0))

    def _do():
        client = _get_client(plex, args["client_name"])
        media = plex.fetchItem(int(rating_key))
        client.playMedia(media, offset=offset_ms)
        return f"Playing '{media.title}' on '{args['client_name']}'"

    return _text(await asyncio.to_thread(_do))


async def _skip_next(plex, args: dict) -> list[TextContent]:
    def _do():
        client = _get_client(plex, args["client_name"])
        client.skipNext()
        return f"Skip next sent to '{args['client_name']}'"

    return _text(await asyncio.to_thread(_do))


async def _skip_prev(plex, args: dict) -> list[TextContent]:
    def _do():
        client = _get_client(plex, args["client_name"])
        client.skipPrevious()
        return f"Skip previous sent to '{args['client_name']}'"

    return _text(await asyncio.to_thread(_do))


async def _set_volume(plex, args: dict) -> list[TextContent]:
    volume = int(args["volume"])

    def _do():
        client = _get_client(plex, args["client_name"])
        client.setVolume(volume)
        return f"Volume set to {volume} on '{args['client_name']}'"

    return _text(await asyncio.to_thread(_do))
