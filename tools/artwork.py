import asyncio
import json
import logging

from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

TOOLS = [
    Tool(
        name="artwork_get_posters",
        description=(
            "Get all available posters for a media item (movie, show, season, album). "
            "Returns list of poster options with their URLs and whether each is currently selected."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "rating_key": {"type": "string", "description": "Plex rating key of the item"},
            },
            "required": ["rating_key"],
        },
    ),
    Tool(
        name="artwork_set_poster_url",
        description="Set a poster for a media item by downloading from a URL",
        inputSchema={
            "type": "object",
            "properties": {
                "rating_key": {"type": "string"},
                "url": {"type": "string", "description": "URL to poster image"},
            },
            "required": ["rating_key", "url"],
        },
    ),
    Tool(
        name="artwork_set_poster_plex",
        description="Select a poster from Plex's existing options by index (from artwork_get_posters output)",
        inputSchema={
            "type": "object",
            "properties": {
                "rating_key": {"type": "string"},
                "poster_index": {"type": "integer", "description": "0-based index from artwork_get_posters"},
            },
            "required": ["rating_key", "poster_index"],
        },
    ),
    Tool(
        name="artwork_upload_poster",
        description="Upload a poster from a local file path on the server",
        inputSchema={
            "type": "object",
            "properties": {
                "rating_key": {"type": "string"},
                "file_path": {"type": "string", "description": "Absolute path to image file on the server"},
            },
            "required": ["rating_key", "file_path"],
        },
    ),
    Tool(
        name="artwork_get_backgrounds",
        description="Get all available background/art images for a media item",
        inputSchema={
            "type": "object",
            "properties": {
                "rating_key": {"type": "string"},
            },
            "required": ["rating_key"],
        },
    ),
    Tool(
        name="artwork_set_background_url",
        description="Set background/art for a media item from a URL",
        inputSchema={
            "type": "object",
            "properties": {
                "rating_key": {"type": "string"},
                "url": {"type": "string"},
            },
            "required": ["rating_key", "url"],
        },
    ),
    Tool(
        name="artwork_set_background_plex",
        description="Select a background from Plex's existing options by index",
        inputSchema={
            "type": "object",
            "properties": {
                "rating_key": {"type": "string"},
                "background_index": {"type": "integer"},
            },
            "required": ["rating_key", "background_index"],
        },
    ),
    Tool(
        name="artwork_get_banners",
        description="Get available banner images for a TV show",
        inputSchema={
            "type": "object",
            "properties": {
                "rating_key": {"type": "string"},
            },
            "required": ["rating_key"],
        },
    ),
    Tool(
        name="artwork_set_banner_url",
        description="Set a banner for a TV show from a URL",
        inputSchema={
            "type": "object",
            "properties": {
                "rating_key": {"type": "string"},
                "url": {"type": "string"},
            },
            "required": ["rating_key", "url"],
        },
    ),
    Tool(
        name="artwork_lock_poster",
        description=(
            "Lock the poster field on one or more items so Plex's scheduled metadata refresh "
            "cannot override a custom poster. Accepts a single rating_key or a list of "
            "rating_keys for bulk locking."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "rating_key": {"type": "string", "description": "Single item rating key"},
                "rating_keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Multiple rating keys for bulk locking",
                },
            },
        },
    ),
    Tool(
        name="artwork_get_available",
        description=(
            "Return all available poster options for a movie or TV show — both online candidates "
            "from the metadata agent and any locally uploaded ones — so you can browse before "
            "committing. Use artwork_set_poster_plex to select one by index."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "rating_key":   {"type": "string", "description": "Plex rating key of the item"},
                "library_name": {"type": "string", "description": "Library containing the item (for context)"},
            },
            "required": ["rating_key"],
        },
    ),
    Tool(
        name="artwork_get_themes",
        description="Get available theme music for a TV show",
        inputSchema={
            "type": "object",
            "properties": {
                "rating_key": {"type": "string"},
            },
            "required": ["rating_key"],
        },
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


def _text(data) -> list[TextContent]:
    if isinstance(data, str):
        return [TextContent(type="text", text=data)]
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


async def handle_tool(name: str, args: dict, plex) -> list[TextContent]:
    try:
        if name == "artwork_get_posters":
            return await _get_posters(plex, args)
        if name == "artwork_set_poster_url":
            return await _set_poster_url(plex, args)
        if name == "artwork_set_poster_plex":
            return await _set_poster_plex(plex, args)
        if name == "artwork_upload_poster":
            return await _upload_poster(plex, args)
        if name == "artwork_get_backgrounds":
            return await _get_backgrounds(plex, args)
        if name == "artwork_set_background_url":
            return await _set_background_url(plex, args)
        if name == "artwork_set_background_plex":
            return await _set_background_plex(plex, args)
        if name == "artwork_get_banners":
            return await _get_banners(plex, args)
        if name == "artwork_set_banner_url":
            return await _set_banner_url(plex, args)
        if name == "artwork_lock_poster":
            return await _lock_poster_tool(plex, args)
        if name == "artwork_get_available":
            return await _get_available_posters(plex, args)
        if name == "artwork_get_themes":
            return await _get_themes(plex, args)
    except Exception as exc:
        logger.exception("Error in artwork tool %s", name)
        return _text(f"Error: {exc}")
    return _text(f"Unknown tool: {name}")


def _get_item(plex, rating_key: str):
    item = plex.fetchItem(int(rating_key))
    item.reload()
    return item


def _lock_poster(item) -> None:
    item.edit(**{"thumb.locked": 1})


async def _get_posters(plex, args: dict) -> list[TextContent]:
    def _get():
        item = _get_item(plex, args["rating_key"])
        posters = item.posters()
        return [
            {
                "index": i,
                "selected": p.selected,
                "provider": getattr(p, "provider", None),
                "thumb_url": p.thumb if hasattr(p, "thumb") else str(p),
                "key": p.key,
            }
            for i, p in enumerate(posters)
        ]

    return _text(await asyncio.to_thread(_get))


async def _set_poster_url(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    def _set():
        item = _get_item(plex, args["rating_key"])
        item.setPoster(url=args["url"])
        return f"Poster set from URL on '{item.title}'"

    result = await asyncio.to_thread(_set)
    log_change("artwork_set_poster_url", args["rating_key"], f"url={args['url']}")
    return _text(result)


async def _set_poster_plex(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    idx = int(args["poster_index"])

    def _set():
        item = _get_item(plex, args["rating_key"])
        posters = item.posters()
        if idx >= len(posters):
            raise ValueError(f"Poster index {idx} out of range (0-{len(posters)-1})")
        item.setPoster(posters[idx])
        return f"Poster {idx} selected on '{item.title}'"

    result = await asyncio.to_thread(_set)
    log_change("artwork_set_poster_plex", args["rating_key"], f"index={idx}")
    return _text(result)


async def _upload_poster(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    def _set():
        item = _get_item(plex, args["rating_key"])
        item.uploadPoster(filepath=args["file_path"])
        _lock_poster(item)
        return f"Poster uploaded and locked on '{item.title}'"

    result = await asyncio.to_thread(_set)
    log_change("artwork_upload_poster", args["rating_key"], f"file={args['file_path']}")
    return _text(result)


async def _lock_poster_tool(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    keys = args.get("rating_keys") or ([args["rating_key"]] if args.get("rating_key") else [])
    if not keys:
        return _text("Provide rating_key or rating_keys.")

    def _lock():
        results = []
        for rk in keys:
            item = _get_item(plex, str(rk))
            _lock_poster(item)
            results.append({"rating_key": rk, "title": item.title, "locked": True})
        return results

    result = await asyncio.to_thread(_lock)
    log_change("artwork_lock_poster", str(keys), "poster locked")
    return _text(result)


async def _get_backgrounds(plex, args: dict) -> list[TextContent]:
    def _get():
        item = _get_item(plex, args["rating_key"])
        arts = item.arts()
        return [
            {
                "index": i,
                "selected": a.selected,
                "provider": getattr(a, "provider", None),
                "key": a.key,
            }
            for i, a in enumerate(arts)
        ]

    return _text(await asyncio.to_thread(_get))


async def _set_background_url(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    def _set():
        item = _get_item(plex, args["rating_key"])
        item.setArt(url=args["url"])
        return f"Background set from URL on '{item.title}'"

    result = await asyncio.to_thread(_set)
    log_change("artwork_set_background_url", args["rating_key"], f"url={args['url']}")
    return _text(result)


async def _set_background_plex(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    idx = int(args["background_index"])

    def _set():
        item = _get_item(plex, args["rating_key"])
        arts = item.arts()
        if idx >= len(arts):
            raise ValueError(f"Background index {idx} out of range")
        item.setArt(arts[idx])
        return f"Background {idx} selected on '{item.title}'"

    result = await asyncio.to_thread(_set)
    log_change("artwork_set_background_plex", args["rating_key"], f"index={idx}")
    return _text(result)


async def _get_banners(plex, args: dict) -> list[TextContent]:
    def _get():
        item = _get_item(plex, args["rating_key"])
        banners = item.banners() if hasattr(item, "banners") else []
        return [
            {
                "index": i,
                "selected": b.selected,
                "key": b.key,
            }
            for i, b in enumerate(banners)
        ]

    return _text(await asyncio.to_thread(_get))


async def _set_banner_url(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    def _set():
        item = _get_item(plex, args["rating_key"])
        if hasattr(item, "setBanner"):
            item.setBanner(url=args["url"])
            return f"Banner set from URL on '{item.title}'"
        return "Banner setting not supported for this item type"

    result = await asyncio.to_thread(_set)
    log_change("artwork_set_banner_url", args["rating_key"], f"url={args['url']}")
    return _text(result)


async def _get_themes(plex, args: dict) -> list[TextContent]:
    def _get():
        item = _get_item(plex, args["rating_key"])
        themes = item.themes() if hasattr(item, "themes") else []
        return [
            {
                "index": i,
                "selected": t.selected,
                "key": t.key,
                "provider": getattr(t, "provider", None),
            }
            for i, t in enumerate(themes)
        ]

    return _text(await asyncio.to_thread(_get))


async def _get_available_posters(plex, args: dict) -> list[TextContent]:
    """All available poster choices — online + local — with selection state and provider."""
    def _get():
        item = _get_item(plex, args["rating_key"])
        # GET /library/metadata/{ratingKey}/posters returns all candidates
        posters = item.posters()
        return {
            "rating_key": args["rating_key"],
            "title":      item.title,
            "count":      len(posters),
            "posters": [
                {
                    "index":    i,
                    "selected": p.selected,
                    "provider": getattr(p, "provider", None),
                    "key":      p.key,
                    "thumb":    getattr(p, "thumb", None) or p.key,
                    "rating_key": getattr(p, "ratingKey", None),
                }
                for i, p in enumerate(posters)
            ],
        }

    return _text(await asyncio.to_thread(_get))
