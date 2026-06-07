import asyncio
import json
import logging
from datetime import timedelta

from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

TOOLS = [
    Tool(
        name="show_list",
        description="List TV shows in a library with metadata summary",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "genre": {"type": "string"},
                "year": {"type": "integer"},
                "unwatched": {"type": "boolean"},
                "limit": {"type": "integer", "default": 100},
                "sort": {"type": "string", "default": "titleSort"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="show_get",
        description="Get full details for a specific TV show including seasons count, episode count, genres, cast. Refreshes metadata.",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "title": {"type": "string"},
                "rating_key": {"type": "string"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="show_seasons",
        description="Get seasons for a TV show with episode counts and watch status",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "show_title": {"type": "string"},
                "show_rating_key": {"type": "string"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="show_episodes",
        description="Get episodes for a specific season of a TV show",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "show_title": {"type": "string"},
                "show_rating_key": {"type": "string"},
                "season_number": {"type": "integer", "description": "Season number (0 = Specials)"},
            },
            "required": ["library_name", "season_number"],
        },
    ),
    Tool(
        name="show_recently_added",
        description="Get recently added episodes across the TV library",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "limit": {"type": "integer", "default": 25},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="show_on_deck",
        description="Get TV shows on deck (next episodes to watch)",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="show_find_candidates",
        description="Find correct metadata match candidates for a misidentified TV show",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "title": {"type": "string"},
                "rating_key": {"type": "string"},
                "search_title": {"type": "string"},
                "search_year": {"type": "integer"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="show_apply_match",
        description="Apply a metadata match to fix a misidentified TV show. Provide guid from show_find_candidates.",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "title": {"type": "string"},
                "rating_key": {"type": "string"},
                "guid": {"type": "string"},
                "match_title": {"type": "string"},
            },
            "required": ["library_name", "guid"],
        },
    ),
    Tool(
        name="show_update_metadata",
        description="Update metadata fields on a show, season, or episode",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "title": {"type": "string"},
                "rating_key": {"type": "string"},
                "fields": {"type": "object", "description": "Fields to update: title, summary, studio, contentRating, etc."},
            },
            "required": ["library_name", "fields"],
        },
    ),
    Tool(
        name="show_delete",
        description="Delete a show, season, or episode. Requires confirmed=true.",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "title": {"type": "string"},
                "rating_key": {"type": "string"},
                "confirmed": {"type": "boolean"},
            },
            "required": ["library_name", "confirmed"],
        },
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


def _text(data) -> list[TextContent]:
    if isinstance(data, str):
        return [TextContent(type="text", text=data)]
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _fmt_dur(ms: int | None) -> str | None:
    if not ms:
        return None
    return str(timedelta(milliseconds=ms)).split(".")[0]


def _show_summary(s) -> dict:
    return {
        "title": s.title,
        "year": s.year,
        "rating_key": s.ratingKey,
        "guid": s.guid,
        "guids": [g.id for g in getattr(s, "guids", [])],
        "rating": s.rating,
        "content_rating": s.contentRating,
        "genres": [g.tag for g in getattr(s, "genres", [])],
        "seasons": s.childCount,
        "episodes": s.leafCount,
        "unwatched": s.leafCount - s.viewedLeafCount,
        "watched": s.isWatched,
        "studio": getattr(s, "studio", None),
        "added_at": str(s.addedAt) if s.addedAt else None,
        "last_viewed": str(s.lastViewedAt) if s.lastViewedAt else None,
        "poster": getattr(s, "thumbUrl", None),
    }


def _episode_summary(ep) -> dict:
    media_info = []
    for media in getattr(ep, "media", []):
        media_info.append({
            "resolution": media.videoResolution,
            "video_codec": media.videoCodec,
            "audio_codec": media.audioCodec,
            "container": media.container,
            "bitrate_kbps": media.bitrate,
        })
    return {
        "title": ep.title,
        "show": getattr(ep, "grandparentTitle", None),
        "season": ep.seasonNumber,
        "episode": ep.index,
        "rating_key": ep.ratingKey,
        "duration": _fmt_dur(ep.duration),
        "watched": ep.isWatched,
        "view_count": ep.viewCount,
        "air_date": str(ep.originallyAvailableAt) if ep.originallyAvailableAt else None,
        "summary": ep.summary,
        "media": media_info,
    }


def _get_show(plex, args: dict):
    library_name = args.get("library_name", "")
    rating_key = args.get("rating_key") or args.get("show_rating_key")
    title = args.get("title") or args.get("show_title")
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
        if name == "show_list":
            return await _show_list(plex, args)
        if name == "show_get":
            return await _show_get(plex, args)
        if name == "show_seasons":
            return await _show_seasons(plex, args)
        if name == "show_episodes":
            return await _show_episodes(plex, args)
        if name == "show_recently_added":
            return await _show_recently_added(plex, args)
        if name == "show_on_deck":
            return await _show_on_deck(plex, args)
        if name == "show_find_candidates":
            return await _show_find_candidates(plex, args)
        if name == "show_apply_match":
            return await _show_apply_match(plex, args)
        if name == "show_update_metadata":
            return await _show_update_metadata(plex, args)
        if name == "show_delete":
            return await _show_delete(plex, args)
    except Exception as exc:
        logger.exception("Error in tv tool %s", name)
        return _text(f"Error: {exc}")
    return _text(f"Unknown tool: {name}")


async def _show_list(plex, args: dict) -> list[TextContent]:
    library_name = args["library_name"]
    limit = int(args.get("limit", 100))
    sort = args.get("sort", "titleSort")
    filters = {}
    if args.get("genre"):
        filters["genre"] = args["genre"]
    if args.get("year"):
        filters["year"] = args["year"]
    if args.get("unwatched"):
        filters["unwatched"] = True

    def _get():
        section = plex.library.section(library_name)
        items = section.search(sort=sort, **filters) if filters else section.all(sort=sort)
        return [_show_summary(s) for s in items[:limit]]

    return _text(await asyncio.to_thread(_get))


async def _show_get(plex, args: dict) -> list[TextContent]:
    def _get():
        show = _get_show(plex, args)
        data = _show_summary(show)
        data.update({
            "summary": show.summary,
            "cast": [a.tag for a in getattr(show, "roles", [])],
            "directors": [d.tag for d in getattr(show, "directors", [])],
            "art": getattr(show, "artUrl", None),
        })
        return data

    return _text(await asyncio.to_thread(_get))


async def _show_seasons(plex, args: dict) -> list[TextContent]:
    def _get():
        show = _get_show(plex, args)
        seasons = show.seasons()
        return [
            {
                "title": s.title,
                "season_number": s.seasonNumber,
                "rating_key": s.ratingKey,
                "episode_count": s.leafCount,
                "unwatched": s.leafCount - s.viewedLeafCount,
                "watched": s.isWatched,
                "added_at": str(s.addedAt) if s.addedAt else None,
                "poster": getattr(s, "thumbUrl", None),
            }
            for s in seasons
        ]

    return _text(await asyncio.to_thread(_get))


async def _show_episodes(plex, args: dict) -> list[TextContent]:
    season_number = int(args["season_number"])

    def _get():
        show = _get_show(plex, args)
        season = show.season(season_number)
        episodes = season.episodes()
        return [_episode_summary(ep) for ep in episodes]

    return _text(await asyncio.to_thread(_get))


async def _show_recently_added(plex, args: dict) -> list[TextContent]:
    library_name = args["library_name"]
    limit = int(args.get("limit", 25))

    def _get():
        section = plex.library.section(library_name)
        return [_episode_summary(ep) for ep in section.recentlyAdded(maxresults=limit)]

    return _text(await asyncio.to_thread(_get))


async def _show_on_deck(plex, args: dict) -> list[TextContent]:
    library_name = args["library_name"]

    def _get():
        section = plex.library.section(library_name)
        return [_episode_summary(ep) for ep in section.onDeck()]

    return _text(await asyncio.to_thread(_get))


async def _show_find_candidates(plex, args: dict) -> list[TextContent]:
    search_title = args.get("search_title") or args.get("title", "")
    search_year = args.get("search_year")

    def _get():
        show = _get_show(plex, args)
        kwargs = {}
        if search_title:
            kwargs["title"] = search_title
        if search_year:
            kwargs["year"] = search_year
        matches = show.matches(**kwargs)
        return [
            {
                "name": m.name,
                "year": m.year,
                "guid": m.guid,
                "score": getattr(m, "score", None),
            }
            for m in matches
        ]

    return _text(await asyncio.to_thread(_get))


async def _show_apply_match(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    guid = args["guid"]
    match_title = args.get("match_title", "")

    def _apply():
        show = _get_show(plex, args)
        old_title = show.title
        show.fixMatch(guid=guid, title=match_title)
        return f"Match applied to '{old_title}' → guid={guid}"

    result = await asyncio.to_thread(_apply)
    log_change("show_apply_match", args.get("title", ""), f"guid={guid}")
    return _text(result)


async def _show_update_metadata(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    fields: dict = args["fields"]

    def _update():
        item = _get_show(plex, args)
        item.edit(**fields)
        item.saveEdits()
        return f"Updated {list(fields.keys())} on '{item.title}'"

    result = await asyncio.to_thread(_update)
    log_change("show_update_metadata", args.get("title", ""), str(fields))
    return _text(result)


async def _show_delete(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    if not args.get("confirmed"):
        return _text("Deletion requires confirmed=true. This action is irreversible.")

    def _delete():
        item = _get_show(plex, args)
        title = item.title
        item.delete()
        return f"Deleted: '{title}'"

    result = await asyncio.to_thread(_delete)
    log_change("show_delete", args.get("title", ""), "Deleted show/season/episode")
    return _text(result)
