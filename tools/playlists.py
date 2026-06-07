import asyncio
import json
import logging

from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

TOOLS = [
    Tool(
        name="playlist_list",
        description="List all Plex playlists with type and item count",
        inputSchema={
            "type": "object",
            "properties": {
                "playlist_type": {
                    "type": "string",
                    "description": "Filter by type: 'video', 'audio', 'photo'. Omit for all.",
                }
            },
        },
    ),
    Tool(
        name="playlist_get",
        description="Get detailed contents of a playlist including all items",
        inputSchema={
            "type": "object",
            "properties": {
                "playlist_title": {"type": "string"},
                "rating_key": {"type": "string"},
            },
        },
    ),
    Tool(
        name="playlist_create",
        description="Create a new playlist. Provide item rating keys to populate it.",
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Playlist name"},
                "playlist_type": {
                    "type": "string",
                    "description": "Type: 'video' (default), 'audio', 'photo'",
                    "default": "video",
                },
                "rating_keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Rating keys of items to add",
                },
                "library_name": {"type": "string", "description": "Library to resolve item titles from"},
                "item_titles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Item titles (requires library_name)",
                },
            },
            "required": ["title"],
        },
    ),
    Tool(
        name="playlist_delete",
        description="Delete a playlist. Requires confirmed=true.",
        inputSchema={
            "type": "object",
            "properties": {
                "playlist_title": {"type": "string"},
                "rating_key": {"type": "string"},
                "confirmed": {"type": "boolean"},
            },
            "required": ["confirmed"],
        },
    ),
    Tool(
        name="playlist_add_items",
        description="Add items to a playlist by rating keys. Requires confirmed=true for 10+ items.",
        inputSchema={
            "type": "object",
            "properties": {
                "playlist_title": {"type": "string"},
                "playlist_rating_key": {"type": "string"},
                "rating_keys": {"type": "array", "items": {"type": "string"}},
                "confirmed": {"type": "boolean"},
            },
        },
    ),
    Tool(
        name="playlist_remove_items",
        description="Remove items from a playlist by rating keys. Requires confirmed=true for 10+ items.",
        inputSchema={
            "type": "object",
            "properties": {
                "playlist_title": {"type": "string"},
                "playlist_rating_key": {"type": "string"},
                "rating_keys": {"type": "array", "items": {"type": "string"}},
                "confirmed": {"type": "boolean"},
            },
        },
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


def _text(data) -> list[TextContent]:
    if isinstance(data, str):
        return [TextContent(type="text", text=data)]
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _playlist_summary(p) -> dict:
    return {
        "title": p.title,
        "rating_key": p.ratingKey,
        "type": p.playlistType,
        "item_count": p.leafCount,
        "duration_ms": getattr(p, "duration", None),
        "thumb": getattr(p, "thumbUrl", None),
        "created_at": str(p.addedAt) if p.addedAt else None,
    }


def _get_playlist(plex, title: str | None, rating_key: str | None):
    if rating_key:
        return plex.fetchItem(int(rating_key))
    if title:
        return plex.playlist(title)
    raise ValueError("Provide playlist_title or rating_key")


async def handle_tool(name: str, args: dict, plex) -> list[TextContent]:
    try:
        if name == "playlist_list":
            return await _playlist_list(plex, args)
        if name == "playlist_get":
            return await _playlist_get(plex, args)
        if name == "playlist_create":
            return await _playlist_create(plex, args)
        if name == "playlist_delete":
            return await _playlist_delete(plex, args)
        if name == "playlist_add_items":
            return await _playlist_add_items(plex, args)
        if name == "playlist_remove_items":
            return await _playlist_remove_items(plex, args)
    except Exception as exc:
        logger.exception("Error in playlists tool %s", name)
        return _text(f"Error: {exc}")
    return _text(f"Unknown tool: {name}")


async def _playlist_list(plex, args: dict) -> list[TextContent]:
    playlist_type = args.get("playlist_type")

    def _get():
        playlists = plex.playlists()
        if playlist_type:
            playlists = [p for p in playlists if p.playlistType == playlist_type]
        return [_playlist_summary(p) for p in playlists]

    return _text(await asyncio.to_thread(_get))


async def _playlist_get(plex, args: dict) -> list[TextContent]:
    def _get():
        pl = _get_playlist(plex, args.get("playlist_title"), args.get("rating_key"))
        data = _playlist_summary(pl)
        data["items"] = [
            {
                "title": item.title,
                "year": getattr(item, "year", None),
                "type": item.type,
                "rating_key": item.ratingKey,
            }
            for item in pl.items()
        ]
        return data

    return _text(await asyncio.to_thread(_get))


async def _playlist_create(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    title = args["title"]
    rating_keys = args.get("rating_keys", [])
    item_titles = args.get("item_titles", [])
    library_name = args.get("library_name")

    def _create():
        items = [plex.fetchItem(int(rk)) for rk in rating_keys]
        if item_titles and library_name:
            section = plex.library.section(library_name)
            items += [section.get(t) for t in item_titles]
        pl = plex.createPlaylist(title, items=items)
        return f"Playlist '{title}' created with {len(items)} items (key={pl.ratingKey})"

    result = await asyncio.to_thread(_create)
    log_change("playlist_create", title, f"items={len(rating_keys)+len(item_titles)}")
    return _text(result)


async def _playlist_delete(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    if not args.get("confirmed"):
        return _text("Playlist deletion requires confirmed=true.")

    def _delete():
        pl = _get_playlist(plex, args.get("playlist_title"), args.get("rating_key"))
        title = pl.title
        pl.delete()
        return f"Playlist '{title}' deleted"

    result = await asyncio.to_thread(_delete)
    log_change("playlist_delete", args.get("playlist_title", ""), "Playlist deleted")
    return _text(result)


async def _playlist_add_items(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    rating_keys = args.get("rating_keys", [])
    if len(rating_keys) >= 10 and not args.get("confirmed"):
        return _text(f"Adding {len(rating_keys)} items requires confirmed=true.")

    def _add():
        pl = _get_playlist(plex, args.get("playlist_title"), args.get("playlist_rating_key"))
        items = [plex.fetchItem(int(rk)) for rk in rating_keys]
        pl.addItems(items)
        return f"Added {len(items)} items to '{pl.title}'"

    result = await asyncio.to_thread(_add)
    log_change("playlist_add_items", args.get("playlist_title", ""), f"added {len(rating_keys)} items")
    return _text(result)


async def _playlist_remove_items(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    rating_keys = args.get("rating_keys", [])
    if len(rating_keys) >= 10 and not args.get("confirmed"):
        return _text(f"Removing {len(rating_keys)} items requires confirmed=true.")

    def _remove():
        pl = _get_playlist(plex, args.get("playlist_title"), args.get("playlist_rating_key"))
        items = [plex.fetchItem(int(rk)) for rk in rating_keys]
        pl.removeItems(items)
        return f"Removed {len(items)} items from '{pl.title}'"

    result = await asyncio.to_thread(_remove)
    log_change("playlist_remove_items", args.get("playlist_title", ""), f"removed {len(rating_keys)} items")
    return _text(result)
