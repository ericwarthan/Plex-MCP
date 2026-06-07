import asyncio
import json
import logging

from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

TOOLS = [
    Tool(
        name="watch_mark_watched",
        description=(
            "Mark a movie, episode, season, or entire show as watched. "
            "For bulk operations (season or show with 10+ episodes), requires confirmed=true."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "rating_key": {"type": "string", "description": "Rating key of the item"},
                "confirmed": {"type": "boolean", "description": "Required for bulk operations (10+ items)"},
            },
            "required": ["rating_key"],
        },
    ),
    Tool(
        name="watch_mark_unwatched",
        description=(
            "Mark a movie, episode, season, or entire show as unwatched. "
            "For bulk operations (10+ items), requires confirmed=true."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "rating_key": {"type": "string"},
                "confirmed": {"type": "boolean"},
            },
            "required": ["rating_key"],
        },
    ),
    Tool(
        name="watch_set_rating",
        description="Set a star rating on a media item (0.0 to 10.0)",
        inputSchema={
            "type": "object",
            "properties": {
                "rating_key": {"type": "string"},
                "rating": {"type": "number", "description": "Rating value from 0.0 to 10.0"},
            },
            "required": ["rating_key", "rating"],
        },
    ),
    Tool(
        name="watch_get_status",
        description="Get the current watch status and user rating for a media item",
        inputSchema={
            "type": "object",
            "properties": {
                "rating_key": {"type": "string"},
            },
            "required": ["rating_key"],
        },
    ),
    Tool(
        name="watch_bulk_mark_watched",
        description=(
            "Mark all items in a collection or library as watched. "
            "Always requires confirmed=true. Describe what will happen before confirming."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string", "description": "Library name (marks entire library)"},
                "collection_title": {"type": "string", "description": "Collection name (marks all items in collection)"},
                "collection_rating_key": {"type": "string"},
                "confirmed": {"type": "boolean"},
            },
            "required": ["confirmed"],
        },
    ),
    Tool(
        name="watch_bulk_mark_unwatched",
        description=(
            "Mark all items in a collection or library as unwatched. "
            "Always requires confirmed=true."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "collection_title": {"type": "string"},
                "collection_rating_key": {"type": "string"},
                "confirmed": {"type": "boolean"},
            },
            "required": ["confirmed"],
        },
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


def _text(data) -> list[TextContent]:
    if isinstance(data, str):
        return [TextContent(type="text", text=data)]
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _estimate_leaf_count(item) -> int:
    if hasattr(item, "leafCount"):
        return item.leafCount
    if item.type in ("movie", "episode", "track"):
        return 1
    return 0


async def handle_tool(name: str, args: dict, plex) -> list[TextContent]:
    try:
        if name == "watch_mark_watched":
            return await _mark_watched(plex, args)
        if name == "watch_mark_unwatched":
            return await _mark_unwatched(plex, args)
        if name == "watch_set_rating":
            return await _set_rating(plex, args)
        if name == "watch_get_status":
            return await _get_status(plex, args)
        if name == "watch_bulk_mark_watched":
            return await _bulk_mark(plex, args, watched=True)
        if name == "watch_bulk_mark_unwatched":
            return await _bulk_mark(plex, args, watched=False)
    except Exception as exc:
        logger.exception("Error in watch_state tool %s", name)
        return _text(f"Error: {exc}")
    return _text(f"Unknown tool: {name}")


async def _mark_watched(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    rating_key = args["rating_key"]

    def _do():
        item = plex.fetchItem(int(rating_key))
        count = _estimate_leaf_count(item)
        if count >= 10 and not args.get("confirmed"):
            return (
                f"Marking '{item.title}' as watched will affect {count} items. "
                "Set confirmed=true to proceed."
            )
        item.markWatched()
        return f"Marked '{item.title}' as watched"

    result = await asyncio.to_thread(_do)
    if "confirmed" in str(result) and "Set confirmed" in str(result):
        return _text(result)
    log_change("watch_mark_watched", rating_key, f"marked watched: {result}")
    return _text(result)


async def _mark_unwatched(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    rating_key = args["rating_key"]

    def _do():
        item = plex.fetchItem(int(rating_key))
        count = _estimate_leaf_count(item)
        if count >= 10 and not args.get("confirmed"):
            return (
                f"Marking '{item.title}' as unwatched will affect {count} items. "
                "Set confirmed=true to proceed."
            )
        item.markUnwatched()
        return f"Marked '{item.title}' as unwatched"

    result = await asyncio.to_thread(_do)
    if "Set confirmed" in str(result):
        return _text(result)
    log_change("watch_mark_unwatched", rating_key, f"marked unwatched: {result}")
    return _text(result)


async def _set_rating(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    rating_key = args["rating_key"]
    rating = float(args["rating"])

    def _do():
        item = plex.fetchItem(int(rating_key))
        item.rate(rating)
        return f"Rating set to {rating} on '{item.title}'"

    result = await asyncio.to_thread(_do)
    log_change("watch_set_rating", rating_key, f"rating={rating}")
    return _text(result)


async def _get_status(plex, args: dict) -> list[TextContent]:
    rating_key = args["rating_key"]

    def _get():
        item = plex.fetchItem(int(rating_key))
        item.reload()
        return {
            "title": item.title,
            "type": item.type,
            "rating_key": rating_key,
            "watched": getattr(item, "isWatched", None),
            "view_count": getattr(item, "viewCount", None),
            "view_offset_ms": getattr(item, "viewOffset", None),
            "last_viewed": str(item.lastViewedAt) if getattr(item, "lastViewedAt", None) else None,
            "user_rating": getattr(item, "userRating", None),
            "critic_rating": getattr(item, "rating", None),
            "audience_rating": getattr(item, "audienceRating", None),
        }

    return _text(await asyncio.to_thread(_get))


async def _bulk_mark(plex, args: dict, watched: bool) -> list[TextContent]:
    from changelog import log_change

    if not args.get("confirmed"):
        action = "watched" if watched else "unwatched"
        target = args.get("library_name") or args.get("collection_title") or "unknown"
        return _text(
            f"This will mark all items in '{target}' as {action}. "
            "Set confirmed=true to proceed with this bulk operation."
        )

    action = "watched" if watched else "unwatched"
    library_name = args.get("library_name")
    collection_title = args.get("collection_title")
    collection_key = args.get("collection_rating_key")

    def _do():
        items = []
        if library_name:
            section = plex.library.section(library_name)
            items = section.all()
            target = f"library '{library_name}'"
        elif collection_key:
            col = plex.fetchItem(int(collection_key))
            items = col.items()
            target = f"collection '{col.title}'"
        elif collection_title:
            for section in plex.library.sections():
                try:
                    col = next(
                        c for c in section.collections()
                        if c.title.lower() == collection_title.lower()
                    )
                    items = col.items()
                    target = f"collection '{col.title}'"
                    break
                except StopIteration:
                    continue
        else:
            return "No library or collection specified"

        count = 0
        for item in items:
            if watched:
                item.markWatched()
            else:
                item.markUnwatched()
            count += 1
        return f"Marked {count} items in {target} as {action}"

    result = await asyncio.to_thread(_do)
    log_change(
        f"watch_bulk_mark_{action}",
        library_name or collection_title or "",
        result,
    )
    return _text(result)
