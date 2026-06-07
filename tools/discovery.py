import asyncio
import json
import logging
from datetime import timedelta

from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

TOOLS = [
    Tool(
        name="discovery_hubs",
        description=(
            "Get Plex recommendation hubs across all libraries or a specific library. "
            "Returns categorized content recommendations like 'Continue Watching', "
            "'Recently Added', 'Top Movies', 'Staff Picks', etc."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string", "description": "Optional: get hubs for a specific library"},
            },
        },
    ),
    Tool(
        name="discovery_on_deck",
        description="Get On Deck content (in-progress items) across all libraries",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 25},
            },
        },
    ),
    Tool(
        name="discovery_recently_added",
        description="Get recently added content across all libraries",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 25},
                "library_type": {
                    "type": "string",
                    "description": "Filter by type: 'movie', 'show', 'music'. Omit for all.",
                },
            },
        },
    ),
    Tool(
        name="discovery_continue_watching",
        description="Get in-progress movies and shows to continue watching",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 25},
            },
        },
    ),
    Tool(
        name="discovery_search",
        description="Search for content across all Plex libraries at once",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


def _text(data) -> list[TextContent]:
    if isinstance(data, str):
        return [TextContent(type="text", text=data)]
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _item_brief(item) -> dict:
    return {
        "title": item.title,
        "type": item.type,
        "year": getattr(item, "year", None),
        "rating_key": item.ratingKey,
        "library": getattr(item, "librarySectionTitle", None),
        "thumb": getattr(item, "thumbUrl", None),
    }


async def handle_tool(name: str, args: dict, plex) -> list[TextContent]:
    try:
        if name == "discovery_hubs":
            return await _hubs(plex, args)
        if name == "discovery_on_deck":
            return await _on_deck(plex, args)
        if name == "discovery_recently_added":
            return await _recently_added(plex, args)
        if name == "discovery_continue_watching":
            return await _continue_watching(plex, args)
        if name == "discovery_search":
            return await _search(plex, args)
    except Exception as exc:
        logger.exception("Error in discovery tool %s", name)
        return _text(f"Error: {exc}")
    return _text(f"Unknown tool: {name}")


async def _hubs(plex, args: dict) -> list[TextContent]:
    library_name = args.get("library_name")

    def _get():
        if library_name:
            section = plex.library.section(library_name)
            hubs = section.hubs()
        else:
            hubs = plex.library.hubs()
        result = []
        for hub in hubs:
            items = []
            try:
                for item in hub.items:
                    items.append(_item_brief(item))
            except Exception:
                pass
            result.append({
                "title": hub.title,
                "type": hub.type,
                "hub_identifier": hub.hubIdentifier,
                "context": getattr(hub, "context", None),
                "size": hub.size,
                "more": hub.more,
                "items": items,
            })
        return result

    return _text(await asyncio.to_thread(_get))


async def _on_deck(plex, args: dict) -> list[TextContent]:
    limit = int(args.get("limit", 25))

    def _get():
        items = plex.library.onDeck()
        return [_item_brief(item) for item in items[:limit]]

    return _text(await asyncio.to_thread(_get))


async def _recently_added(plex, args: dict) -> list[TextContent]:
    limit = int(args.get("limit", 25))
    library_type = args.get("library_type")

    def _get():
        items = plex.library.recentlyAdded()
        if library_type:
            type_map = {"movie": "movie", "show": "episode", "music": "track"}
            filter_type = type_map.get(library_type, library_type)
            items = [i for i in items if i.type == filter_type]
        return [_item_brief(item) for item in items[:limit]]

    return _text(await asyncio.to_thread(_get))


async def _continue_watching(plex, args: dict) -> list[TextContent]:
    limit = int(args.get("limit", 25))

    def _get():
        items = plex.library.onDeck()
        return [_item_brief(item) for item in items[:limit]]

    return _text(await asyncio.to_thread(_get))


async def _search(plex, args: dict) -> list[TextContent]:
    query = args["query"]
    limit = int(args.get("limit", 20))

    def _get():
        results = plex.library.search(query)
        return [_item_brief(item) for item in results[:limit]]

    return _text(await asyncio.to_thread(_get))
