import asyncio
import json
import logging
from datetime import timedelta

from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

TOOLS = [
    Tool(
        name="music_list_artists",
        description="List music artists in a library",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "genre": {"type": "string"},
                "limit": {"type": "integer", "default": 100},
                "sort": {"type": "string", "default": "titleSort"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="music_list_albums",
        description="List albums, optionally filtered by artist",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "artist": {"type": "string", "description": "Filter by artist name"},
                "genre": {"type": "string"},
                "year": {"type": "integer"},
                "limit": {"type": "integer", "default": 100},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="music_list_tracks",
        description="List tracks, optionally filtered by album or artist",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "album_rating_key": {"type": "string"},
                "artist": {"type": "string"},
                "limit": {"type": "integer", "default": 200},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="music_get_artist",
        description="Get detailed info for a music artist including albums list. Refreshes metadata.",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "artist": {"type": "string"},
                "rating_key": {"type": "string"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="music_get_album",
        description="Get detailed info for an album including all tracks. Refreshes metadata.",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "album_title": {"type": "string"},
                "rating_key": {"type": "string"},
                "artist": {"type": "string", "description": "Artist name to narrow search"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="music_search",
        description="Search for music artists, albums, or tracks by title",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "query": {"type": "string"},
                "type": {
                    "type": "string",
                    "description": "What to search: 'artist', 'album', 'track' (default: all)",
                },
            },
            "required": ["library_name", "query"],
        },
    ),
    Tool(
        name="music_update_metadata",
        description="Update metadata fields on a music artist or album",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "rating_key": {"type": "string"},
                "title": {"type": "string"},
                "fields": {"type": "object", "description": "Fields to update"},
            },
            "required": ["library_name", "fields"],
        },
    ),
    Tool(
        name="music_fix_match",
        description="Find match candidates for a misidentified artist or album",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "rating_key": {"type": "string"},
                "title": {"type": "string"},
                "search_title": {"type": "string"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="music_apply_match",
        description="Apply a metadata match to a music artist or album",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "rating_key": {"type": "string"},
                "title": {"type": "string"},
                "guid": {"type": "string"},
                "match_title": {"type": "string"},
            },
            "required": ["library_name", "guid"],
        },
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


def _text(data) -> list[TextContent]:
    if isinstance(data, str):
        return [TextContent(type="text", text=data)]
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _artist_summary(a) -> dict:
    return {
        "title": a.title,
        "rating_key": a.ratingKey,
        "guid": a.guid,
        "guids": [g.id for g in getattr(a, "guids", [])],
        "genres": [g.tag for g in getattr(a, "genres", [])],
        "summary": getattr(a, "summary", None),
        "thumb": getattr(a, "thumbUrl", None),
    }


def _album_summary(al) -> dict:
    return {
        "title": al.title,
        "artist": getattr(al, "parentTitle", None),
        "year": al.year,
        "rating_key": al.ratingKey,
        "guid": al.guid,
        "guids": [g.id for g in getattr(al, "guids", [])],
        "genres": [g.tag for g in getattr(al, "genres", [])],
        "track_count": al.leafCount,
        "added_at": str(al.addedAt) if al.addedAt else None,
        "thumb": getattr(al, "thumbUrl", None),
    }


def _track_summary(t) -> dict:
    dur = getattr(t, "duration", None)
    return {
        "title": t.title,
        "artist": getattr(t, "grandparentTitle", None),
        "album": getattr(t, "parentTitle", None),
        "track_number": t.index,
        "disc": getattr(t, "parentIndex", None),
        "duration": str(timedelta(milliseconds=dur)).split(".")[0] if dur else None,
        "rating_key": t.ratingKey,
        "file": t.media[0].parts[0].file if t.media and t.media[0].parts else None,
    }


def _get_item(plex, args: dict):
    library_name = args.get("library_name", "")
    rating_key = args.get("rating_key")
    title = args.get("title") or args.get("artist") or args.get("album_title")
    section = plex.library.section(library_name)
    if rating_key:
        item = plex.fetchItem(int(rating_key))
    elif title:
        item = section.get(title)
    else:
        raise ValueError("Provide title or rating_key")
    item.reload()
    return item


async def handle_tool(name: str, args: dict, plex) -> list[TextContent]:
    try:
        if name == "music_list_artists":
            return await _list_artists(plex, args)
        if name == "music_list_albums":
            return await _list_albums(plex, args)
        if name == "music_list_tracks":
            return await _list_tracks(plex, args)
        if name == "music_get_artist":
            return await _get_artist(plex, args)
        if name == "music_get_album":
            return await _get_album(plex, args)
        if name == "music_search":
            return await _search(plex, args)
        if name == "music_update_metadata":
            return await _update_metadata(plex, args)
        if name == "music_fix_match":
            return await _fix_match(plex, args)
        if name == "music_apply_match":
            return await _apply_match(plex, args)
    except Exception as exc:
        logger.exception("Error in music tool %s", name)
        return _text(f"Error: {exc}")
    return _text(f"Unknown tool: {name}")


async def _list_artists(plex, args: dict) -> list[TextContent]:
    library_name = args["library_name"]
    limit = int(args.get("limit", 100))
    sort = args.get("sort", "titleSort")
    filters = {}
    if args.get("genre"):
        filters["genre"] = args["genre"]

    def _get():
        section = plex.library.section(library_name)
        items = section.search(libtype="artist", sort=sort, **filters) if filters else section.all(sort=sort)
        return [_artist_summary(a) for a in items[:limit]]

    return _text(await asyncio.to_thread(_get))


async def _list_albums(plex, args: dict) -> list[TextContent]:
    library_name = args["library_name"]
    limit = int(args.get("limit", 100))
    artist_filter = args.get("artist")
    filters = {"libtype": "album"}
    if args.get("genre"):
        filters["genre"] = args["genre"]
    if args.get("year"):
        filters["year"] = args["year"]

    def _get():
        section = plex.library.section(library_name)
        if artist_filter:
            artist = section.get(artist_filter)
            albums = artist.albums()
        else:
            albums = section.search(**filters)
        return [_album_summary(al) for al in albums[:limit]]

    return _text(await asyncio.to_thread(_get))


async def _list_tracks(plex, args: dict) -> list[TextContent]:
    library_name = args["library_name"]
    limit = int(args.get("limit", 200))
    album_key = args.get("album_rating_key")
    artist_name = args.get("artist")

    def _get():
        section = plex.library.section(library_name)
        if album_key:
            album = plex.fetchItem(int(album_key))
            tracks = album.tracks()
        elif artist_name:
            artist = section.get(artist_name)
            tracks = artist.tracks()
        else:
            tracks = section.search(libtype="track")
        return [_track_summary(t) for t in tracks[:limit]]

    return _text(await asyncio.to_thread(_get))


async def _get_artist(plex, args: dict) -> list[TextContent]:
    def _get():
        artist = _get_item(plex, args)
        data = _artist_summary(artist)
        data["albums"] = [_album_summary(al) for al in artist.albums()]
        return data

    return _text(await asyncio.to_thread(_get))


async def _get_album(plex, args: dict) -> list[TextContent]:
    def _get():
        if args.get("rating_key"):
            album = plex.fetchItem(int(args["rating_key"]))
            album.reload()
        else:
            section = plex.library.section(args["library_name"])
            artist_name = args.get("artist")
            album_title = args.get("album_title", "")
            if artist_name:
                artist = section.get(artist_name)
                album = next((al for al in artist.albums() if album_title.lower() in al.title.lower()), None)
                if not album:
                    raise ValueError(f"Album '{album_title}' not found for artist '{artist_name}'")
            else:
                album = section.get(album_title)
            album.reload()
        data = _album_summary(album)
        data["tracks"] = [_track_summary(t) for t in album.tracks()]
        return data

    return _text(await asyncio.to_thread(_get))


async def _search(plex, args: dict) -> list[TextContent]:
    library_name = args["library_name"]
    query = args["query"]
    search_type = args.get("type", "all")

    def _get():
        section = plex.library.section(library_name)
        results = []
        if search_type in ("all", "artist"):
            for a in section.search(title=query, libtype="artist"):
                results.append({"type": "artist", **_artist_summary(a)})
        if search_type in ("all", "album"):
            for al in section.search(title=query, libtype="album"):
                results.append({"type": "album", **_album_summary(al)})
        if search_type in ("all", "track"):
            for t in section.search(title=query, libtype="track"):
                results.append({"type": "track", **_track_summary(t)})
        return results

    return _text(await asyncio.to_thread(_get))


async def _update_metadata(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    fields: dict = args["fields"]

    def _update():
        item = _get_item(plex, args)
        item.edit(**fields)
        item.saveEdits()
        return f"Updated {list(fields.keys())} on '{item.title}'"

    result = await asyncio.to_thread(_update)
    log_change("music_update_metadata", args.get("title", ""), str(fields))
    return _text(result)


async def _fix_match(plex, args: dict) -> list[TextContent]:
    search_title = args.get("search_title") or args.get("title", "")

    def _get():
        item = _get_item(plex, args)
        matches = item.matches(title=search_title) if search_title else item.matches()
        return [
            {
                "name": m.name,
                "year": getattr(m, "year", None),
                "guid": m.guid,
                "score": getattr(m, "score", None),
            }
            for m in matches
        ]

    return _text(await asyncio.to_thread(_get))


async def _apply_match(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    guid = args["guid"]
    match_title = args.get("match_title", "")

    def _apply():
        item = _get_item(plex, args)
        old_title = item.title
        item.fixMatch(guid=guid, title=match_title)
        return f"Match applied to '{old_title}' → guid={guid}"

    result = await asyncio.to_thread(_apply)
    log_change("music_apply_match", args.get("title", ""), f"guid={guid}")
    return _text(result)
