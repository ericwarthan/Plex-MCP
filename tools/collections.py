import asyncio
import json
import logging

from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

TOOLS = [
    Tool(
        name="collection_list",
        description="List all collections in a library",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="collection_get",
        description="Get details and item list for a specific collection",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "collection_title": {"type": "string"},
                "rating_key": {"type": "string"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="collection_create",
        description=(
            "Create a new collection. Provide item titles or rating keys to populate it. "
            "Logs the creation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "title": {"type": "string", "description": "Collection name"},
                "item_titles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Titles of items to add",
                },
                "rating_keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Rating keys of items to add (alternative to item_titles)",
                },
            },
            "required": ["library_name", "title"],
        },
    ),
    Tool(
        name="collection_delete",
        description="Delete a collection. Requires confirmed=true. Does NOT delete the media items.",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "collection_title": {"type": "string"},
                "rating_key": {"type": "string"},
                "confirmed": {"type": "boolean"},
            },
            "required": ["library_name", "confirmed"],
        },
    ),
    Tool(
        name="collection_add_items",
        description=(
            "Add items to an existing collection. If adding 10 or more items, requires confirmed=true. "
            "Provide titles or rating keys."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "collection_title": {"type": "string"},
                "collection_rating_key": {"type": "string"},
                "item_titles": {"type": "array", "items": {"type": "string"}},
                "rating_keys": {"type": "array", "items": {"type": "string"}},
                "confirmed": {"type": "boolean", "description": "Required when adding 10+ items"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="collection_remove_items",
        description="Remove specific items from a collection. If removing 10+ items, requires confirmed=true.",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "collection_title": {"type": "string"},
                "collection_rating_key": {"type": "string"},
                "item_titles": {"type": "array", "items": {"type": "string"}},
                "rating_keys": {"type": "array", "items": {"type": "string"}},
                "confirmed": {"type": "boolean"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="collection_set_poster",
        description="Set a poster for a collection from a URL",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "collection_title": {"type": "string"},
                "rating_key": {"type": "string"},
                "url": {"type": "string", "description": "Poster image URL"},
            },
            "required": ["library_name", "url"],
        },
    ),
    Tool(
        name="collection_set_sort_order",
        description="Set the sort order for items in a collection",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "collection_title": {"type": "string"},
                "rating_key": {"type": "string"},
                "sort_order": {
                    "type": "string",
                    "description": "Sort order: 'release', 'alpha', 'custom'",
                },
            },
            "required": ["library_name", "sort_order"],
        },
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


def _text(data) -> list[TextContent]:
    if isinstance(data, str):
        return [TextContent(type="text", text=data)]
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _collection_summary(c) -> dict:
    return {
        "title": c.title,
        "rating_key": c.ratingKey,
        "child_count": c.childCount,
        "content_rating": getattr(c, "contentRating", None),
        "thumb": getattr(c, "thumbUrl", None),
        "added_at": str(c.addedAt) if c.addedAt else None,
    }


def _get_collection(plex, library_name: str, title: str | None, rating_key: str | None):
    if rating_key:
        col = plex.fetchItem(int(rating_key))
    elif title:
        section = plex.library.section(library_name)
        col = next(
            (c for c in section.collections() if c.title.lower() == title.lower()),
            None,
        )
        if col is None:
            raise ValueError(f"Collection '{title}' not found in '{library_name}'")
    else:
        raise ValueError("Provide collection_title or rating_key")
    return col


async def handle_tool(name: str, args: dict, plex) -> list[TextContent]:
    try:
        if name == "collection_list":
            return await _collection_list(plex, args)
        if name == "collection_get":
            return await _collection_get(plex, args)
        if name == "collection_create":
            return await _collection_create(plex, args)
        if name == "collection_delete":
            return await _collection_delete(plex, args)
        if name == "collection_add_items":
            return await _collection_add_items(plex, args)
        if name == "collection_remove_items":
            return await _collection_remove_items(plex, args)
        if name == "collection_set_poster":
            return await _collection_set_poster(plex, args)
        if name == "collection_set_sort_order":
            return await _collection_set_sort_order(plex, args)
    except Exception as exc:
        logger.exception("Error in collections tool %s", name)
        return _text(f"Error: {exc}")
    return _text(f"Unknown tool: {name}")


async def _collection_list(plex, args: dict) -> list[TextContent]:
    library_name = args["library_name"]

    def _get():
        section = plex.library.section(library_name)
        return [_collection_summary(c) for c in section.collections()]

    return _text(await asyncio.to_thread(_get))


async def _collection_get(plex, args: dict) -> list[TextContent]:
    def _get():
        col = _get_collection(
            plex,
            args["library_name"],
            args.get("collection_title"),
            args.get("rating_key"),
        )
        data = _collection_summary(col)
        data["items"] = [
            {"title": item.title, "year": getattr(item, "year", None), "rating_key": item.ratingKey}
            for item in col.items()
        ]
        return data

    return _text(await asyncio.to_thread(_get))


async def _collection_create(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    library_name = args["library_name"]
    title = args["title"]
    item_titles = args.get("item_titles", [])
    rating_keys = args.get("rating_keys", [])

    def _create():
        section = plex.library.section(library_name)
        items = []
        for t in item_titles:
            items.append(section.get(t))
        for rk in rating_keys:
            items.append(plex.fetchItem(int(rk)))
        col = section.createCollection(title, items=items)
        return f"Collection '{title}' created with {len(items)} items (key={col.ratingKey})"

    result = await asyncio.to_thread(_create)
    log_change("collection_create", title, f"library={library_name}, items={len(item_titles)+len(rating_keys)}")
    return _text(result)


async def _collection_delete(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    if not args.get("confirmed"):
        return _text("Collection deletion requires confirmed=true.")

    def _delete():
        col = _get_collection(
            plex,
            args["library_name"],
            args.get("collection_title"),
            args.get("rating_key"),
        )
        title = col.title
        col.delete()
        return f"Collection '{title}' deleted"

    result = await asyncio.to_thread(_delete)
    log_change("collection_delete", args.get("collection_title", ""), "Collection deleted")
    return _text(result)


async def _collection_add_items(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    library_name = args["library_name"]
    item_titles = args.get("item_titles", [])
    rating_keys = args.get("rating_keys", [])
    total = len(item_titles) + len(rating_keys)

    if total >= 10 and not args.get("confirmed"):
        return _text(
            f"Adding {total} items to the collection requires confirmed=true. "
            "Please confirm this bulk operation."
        )

    def _add():
        section = plex.library.section(library_name)
        col = _get_collection(
            plex,
            library_name,
            args.get("collection_title"),
            args.get("collection_rating_key"),
        )
        items = [section.get(t) for t in item_titles]
        items += [plex.fetchItem(int(rk)) for rk in rating_keys]
        col.addItems(items)
        return f"Added {len(items)} items to '{col.title}'"

    result = await asyncio.to_thread(_add)
    log_change("collection_add_items", args.get("collection_title", ""), f"added {total} items")
    return _text(result)


async def _collection_remove_items(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    library_name = args["library_name"]
    item_titles = args.get("item_titles", [])
    rating_keys = args.get("rating_keys", [])
    total = len(item_titles) + len(rating_keys)

    if total >= 10 and not args.get("confirmed"):
        return _text(
            f"Removing {total} items from the collection requires confirmed=true."
        )

    def _remove():
        section = plex.library.section(library_name)
        col = _get_collection(
            plex,
            library_name,
            args.get("collection_title"),
            args.get("collection_rating_key"),
        )
        items = [section.get(t) for t in item_titles]
        items += [plex.fetchItem(int(rk)) for rk in rating_keys]
        col.removeItems(items)
        return f"Removed {len(items)} items from '{col.title}'"

    result = await asyncio.to_thread(_remove)
    log_change("collection_remove_items", args.get("collection_title", ""), f"removed {total} items")
    return _text(result)


async def _collection_set_poster(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    def _set():
        col = _get_collection(
            plex,
            args["library_name"],
            args.get("collection_title"),
            args.get("rating_key"),
        )
        col.setPoster(url=args["url"])
        return f"Poster set on collection '{col.title}'"

    result = await asyncio.to_thread(_set)
    log_change("collection_set_poster", args.get("collection_title", ""), f"url={args['url']}")
    return _text(result)


async def _collection_set_sort_order(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    sort_map = {"release": 0, "alpha": 1, "custom": 2}
    sort_order = args["sort_order"].lower()
    sort_value = sort_map.get(sort_order, 0)

    def _set():
        col = _get_collection(
            plex,
            args["library_name"],
            args.get("collection_title"),
            args.get("rating_key"),
        )
        col.editSortType(sort_value)
        return f"Sort order set to '{sort_order}' on '{col.title}'"

    result = await asyncio.to_thread(_set)
    log_change("collection_set_sort_order", args.get("collection_title", ""), f"sort={sort_order}")
    return _text(result)
