import asyncio
import json
import logging
from datetime import timedelta

from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

TOOLS = [
    Tool(
        name="movie_list",
        description=(
            "List movies in a library. Supports filtering by genre, year, studio, director, "
            "unwatched status. Returns title, year, resolution, HDR, codec, rating, watch status."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string", "description": "Movie library name"},
                "genre": {"type": "string"},
                "year": {"type": "integer"},
                "unwatched": {"type": "boolean", "description": "Filter to unwatched only"},
                "resolution": {"type": "string", "description": "e.g. '4k', '1080', '720'"},
                "limit": {"type": "integer", "description": "Max results (default 100)", "default": 100},
                "sort": {
                    "type": "string",
                    "description": "Sort field: 'titleSort', 'year', 'addedAt', 'lastViewedAt', 'rating'",
                    "default": "titleSort",
                },
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="movie_recently_added",
        description="Get recently added movies across a library",
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
        name="movie_recently_viewed",
        description="Get recently viewed/played movies",
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
        name="movie_on_deck",
        description="Get movies on deck (in-progress / resume watching)",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="movie_get",
        description=(
            "Get full details for a specific movie including cast, crew, metadata, media info, "
            "and all available GUIDs (TMDB, IMDB). Refreshes metadata before returning."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "title": {"type": "string", "description": "Movie title (exact or partial)"},
                "rating_key": {"type": "string", "description": "Plex rating key (alternative to title)"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="movie_search",
        description="Search for movies by title across a library",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["library_name", "query"],
        },
    ),
    Tool(
        name="movie_find_candidates",
        description=(
            "Search for correct metadata match candidates for a misidentified movie. "
            "Returns a list of candidates with name, year, and ID. "
            "Always call this before movie_apply_match."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "title": {"type": "string", "description": "Current movie title in Plex"},
                "rating_key": {"type": "string", "description": "Plex rating key (alternative)"},
                "search_title": {"type": "string", "description": "Title to search for (if different)"},
                "search_year": {"type": "integer", "description": "Year to narrow down results"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="movie_apply_match",
        description=(
            "Apply a specific metadata match to fix a misidentified movie. "
            "Provide a GUID from movie_find_candidates output. Logs the change."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "title": {"type": "string", "description": "Current movie title in Plex"},
                "rating_key": {"type": "string", "description": "Plex rating key (alternative)"},
                "guid": {"type": "string", "description": "Match GUID (e.g. 'tmdb://12345')"},
                "match_title": {"type": "string", "description": "Title of the correct match"},
            },
            "required": ["library_name", "guid"],
        },
    ),
    Tool(
        name="movie_update_metadata",
        description="Update editable metadata fields on a movie (title, year, summary, tagline, studio, content_rating, etc.)",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "title": {"type": "string"},
                "rating_key": {"type": "string"},
                "fields": {
                    "type": "object",
                    "description": "Dict of field names to new values. Supported: title, titleSort, originalTitle, year, summary, tagline, studio, contentRating",
                },
            },
            "required": ["library_name", "fields"],
        },
    ),
    Tool(
        name="movie_delete",
        description="Delete a movie from the library. Requires confirmed=true.",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "title": {"type": "string"},
                "rating_key": {"type": "string"},
                "confirmed": {"type": "boolean", "description": "Must be true to proceed"},
            },
            "required": ["library_name", "confirmed"],
        },
    ),
    Tool(
        name="movie_missing_posters",
        description="Find all movies in a library that are missing poster artwork",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="movie_optimize",
        description=(
            "Queue a Plex Media Optimizer job for a movie, creating a pre-transcoded version "
            "optimized for a specific device profile and quality level. "
            "Preset targets: 'mobile','tv','original' (no quality needed). "
            "Device targets: 'android','ios','apple_tv','chromecast','universal','universal_tv','windows','xbox'. "
            "Quality presets: '720p'(4Mbps),'1080p'(8Mbps),'1080p_10m','1080p_high'(12Mbps),'1080p_20m','4k'(original res). "
            "Or pass a raw VIDEO_QUALITY integer."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "rating_key": {"type": "string", "description": "Plex rating key of the movie to optimize"},
                "target": {"type": "string", "description": "Device profile tag (e.g. 'android', 'apple_tv', 'universal')"},
                "quality": {"description": "Quality preset string or raw integer videoQuality value"},
                "title": {"type": "string", "description": "Optional label for this optimized version"},
            },
            "required": ["rating_key", "target", "quality"],
        },
    ),
    Tool(
        name="movie_merge",
        description=(
            "Merge one or more standalone movie entries into a primary item, creating a "
            "multi-version item. The primary item keeps its metadata; merged items contribute "
            "their media files as additional versions. Use this to group alternate cuts, "
            "editions, or releases of the same film under one entry."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "primary_rating_key": {"type": "string", "description": "Rating key of the item to merge INTO (keeps its metadata)"},
                "merge_rating_keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Rating keys of items to merge into the primary",
                },
            },
            "required": ["library_name", "primary_rating_key", "merge_rating_keys"],
        },
    ),
    Tool(
        name="movie_list_merged",
        description=(
            "List all movies in a library that have more than one media file attached "
            "(merged / multi-version items). These are candidates for movie_split_media."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="movie_list_unmatched",
        description=(
            "List all items in a library that have no metadata agent match "
            "(guid indicates no external match). Useful for finding items that need "
            "manual matching via movie_find_candidates / movie_apply_match."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="movie_split_media",
        description=(
            "Split a merged/multi-version movie item into separate entries without deleting files. "
            "Use this to fix items where two different movies were incorrectly grouped together. "
            "Does NOT auto-scan after splitting — apply correct matches with movie_apply_match first, "
            "then run library_scan to avoid Plex re-merging items before matches are fixed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "rating_key": {"type": "string", "description": "Plex rating key of the merged item to split"},
                "library_name": {"type": "string", "description": "Library name to scan after split"},
                "confirmed": {"type": "boolean", "description": "Must be true to execute the split; omit to preview affected files without splitting"},
            },
            "required": ["rating_key", "library_name"],
        },
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


def _text(data) -> list[TextContent]:
    if isinstance(data, str):
        return [TextContent(type="text", text=data)]
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _format_duration(ms: int | None) -> str | None:
    if ms is None:
        return None
    return str(timedelta(milliseconds=ms)).split(".")[0]


def _movie_summary(m) -> dict:
    media_info = []
    for media in getattr(m, "media", []):
        media_info.append({
            "media_id": media.id,
            "resolution": media.videoResolution,
            "bitrate_kbps": media.bitrate,
            "container": media.container,
            "video_codec": media.videoCodec,
            "audio_codec": media.audioCodec,
            "audio_channels": media.audioChannels,
            "file": media.parts[0].file if media.parts else None,
        })
    return {
        "title": m.title,
        "year": m.year,
        "rating_key": m.ratingKey,
        "guid": m.guid,
        "guids": [g.id for g in getattr(m, "guids", [])],
        "rating": m.rating,
        "audience_rating": getattr(m, "audienceRating", None),
        "duration": _format_duration(m.duration),
        "studio": m.studio,
        "content_rating": m.contentRating,
        "genres": [g.tag for g in getattr(m, "genres", [])],
        "watched": m.isWatched,
        "view_count": m.viewCount,
        "last_viewed": str(m.lastViewedAt) if m.lastViewedAt else None,
        "added_at": str(m.addedAt) if m.addedAt else None,
        "media": media_info,
        "poster": getattr(m, "thumbUrl", None),
    }


def _movie_full(m) -> dict:
    base = _movie_summary(m)
    base.update({
        "tagline": m.tagline,
        "summary": m.summary,
        "directors": [d.tag for d in getattr(m, "directors", [])],
        "writers": [w.tag for w in getattr(m, "writers", [])],
        "cast": [a.tag for a in getattr(m, "roles", [])],
        "countries": [c.tag for c in getattr(m, "countries", [])],
        "art": getattr(m, "artUrl", None),
    })
    return base


async def handle_tool(name: str, args: dict, plex) -> list[TextContent]:
    try:
        if name == "movie_list":
            return await _movie_list(plex, args)
        if name == "movie_recently_added":
            return await _movie_recently_added(plex, args)
        if name == "movie_recently_viewed":
            return await _movie_recently_viewed(plex, args)
        if name == "movie_on_deck":
            return await _movie_on_deck(plex, args)
        if name == "movie_get":
            return await _movie_get(plex, args)
        if name == "movie_search":
            return await _movie_search(plex, args)
        if name == "movie_find_candidates":
            return await _movie_find_candidates(plex, args)
        if name == "movie_apply_match":
            return await _movie_apply_match(plex, args)
        if name == "movie_update_metadata":
            return await _movie_update_metadata(plex, args)
        if name == "movie_delete":
            return await _movie_delete(plex, args)
        if name == "movie_missing_posters":
            return await _movie_missing_posters(plex, args)
        if name == "movie_optimize":
            return await _movie_optimize(plex, args)
        if name == "movie_merge":
            return await _movie_merge(plex, args)
        if name == "movie_list_merged":
            return await _movie_list_merged(plex, args)
        if name == "movie_list_unmatched":
            return await _movie_list_unmatched(plex, args)
        if name == "movie_split_media":
            return await _movie_split_media(plex, args)
    except Exception as exc:
        logger.exception("Error in movies tool %s", name)
        return _text(f"Error: {exc}")
    return _text(f"Unknown tool: {name}")


def _get_movie(plex, args: dict):
    library_name = args.get("library_name", "")
    rating_key = args.get("rating_key")
    title = args.get("title")
    section = plex.library.section(library_name)
    if rating_key:
        item = plex.fetchItem(int(rating_key))
    elif title:
        item = section.get(title)
    else:
        raise ValueError("Provide title or rating_key")
    item.reload()
    return item


async def _movie_list(plex, args: dict) -> list[TextContent]:
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
    if args.get("resolution"):
        filters["mediaVideoResolution"] = args["resolution"]

    def _get():
        section = plex.library.section(library_name)
        if filters:
            items = section.search(sort=sort, **filters)
        else:
            items = section.all(sort=sort)
        return [_movie_summary(m) for m in items[:limit]]

    return _text(await asyncio.to_thread(_get))


async def _movie_recently_added(plex, args: dict) -> list[TextContent]:
    library_name = args["library_name"]
    limit = int(args.get("limit", 25))

    def _get():
        section = plex.library.section(library_name)
        return [_movie_summary(m) for m in section.recentlyAdded(maxresults=limit)]

    return _text(await asyncio.to_thread(_get))


async def _movie_recently_viewed(plex, args: dict) -> list[TextContent]:
    library_name = args["library_name"]
    limit = int(args.get("limit", 25))

    def _get():
        section = plex.library.section(library_name)
        items = section.search(sort="lastViewedAt:desc", unwatched=False)
        return [_movie_summary(m) for m in items[:limit]]

    return _text(await asyncio.to_thread(_get))


async def _movie_on_deck(plex, args: dict) -> list[TextContent]:
    library_name = args["library_name"]

    def _get():
        section = plex.library.section(library_name)
        return [_movie_summary(m) for m in section.onDeck()]

    return _text(await asyncio.to_thread(_get))


async def _movie_get(plex, args: dict) -> list[TextContent]:
    def _get():
        return _movie_full(_get_movie(plex, args))

    return _text(await asyncio.to_thread(_get))


async def _movie_search(plex, args: dict) -> list[TextContent]:
    library_name = args["library_name"]
    query = args["query"]

    def _get():
        section = plex.library.section(library_name)
        return [_movie_summary(m) for m in section.search(title=query)]

    return _text(await asyncio.to_thread(_get))


async def _movie_find_candidates(plex, args: dict) -> list[TextContent]:
    search_title = args.get("search_title") or args.get("title", "")
    search_year = args.get("search_year")

    def _get():
        movie = _get_movie(plex, args)
        kwargs = {}
        if search_title:
            kwargs["title"] = search_title
        if search_year:
            kwargs["year"] = search_year
        matches = movie.matches(**kwargs)
        return [
            {
                "name": m.name,
                "year": m.year,
                "guid": m.guid,
                "score": getattr(m, "score", None),
                "thumb": getattr(m, "thumb", None),
            }
            for m in matches
        ]

    return _text(await asyncio.to_thread(_get))


async def _movie_apply_match(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    guid = args["guid"]
    match_title = args.get("match_title", "")

    def _apply():
        movie = _get_movie(plex, args)
        old_title = movie.title
        # When a guid is explicitly provided, apply it directly via the Plex API
        # rather than re-validating against search results, which may not return
        # the correct candidate when the item title doesn't match the target film.
        plex.query(
            f"/library/metadata/{movie.ratingKey}/match",
            method=plex._session.put,
            params={"guid": guid, "name": match_title or old_title},
        )
        return f"Match applied to '{old_title}' → {guid}"

    result = await asyncio.to_thread(_apply)
    log_change("movie_apply_match", args.get("title", args.get("rating_key", "")), f"guid={guid}")
    return _text(result)


_FIELD_MAP = {
    "title": "title",
    "titleSort": "titleSort",
    "originalTitle": "originalTitle",
    "year": "year",
    "summary": "summary",
    "tagline": "tagline",
    "studio": "studio",
    "contentRating": "contentRating",
}


async def _movie_update_metadata(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    fields: dict = args["fields"]

    def _update():
        movie = _get_movie(plex, args)
        updates = {_FIELD_MAP[k]: v for k, v in fields.items() if k in _FIELD_MAP}
        if updates:
            params = {}
            for field, val in updates.items():
                params[f"{field}.value"] = val
                params[f"{field}.locked"] = 1
            movie.edit(**params)
        return f"Updated {list(updates.keys())} on '{movie.title}'"

    result = await asyncio.to_thread(_update)
    log_change("movie_update_metadata", args.get("title", ""), str(fields))
    return _text(result)


async def _movie_delete(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    if not args.get("confirmed"):
        return _text("Deletion requires confirmed=true. This action is irreversible.")

    def _delete():
        movie = _get_movie(plex, args)
        title = movie.title
        movie.delete()
        return f"Deleted movie: '{title}'"

    result = await asyncio.to_thread(_delete)
    log_change("movie_delete", args.get("title", ""), "Movie deleted")
    return _text(result)


async def _movie_missing_posters(plex, args: dict) -> list[TextContent]:
    library_name = args["library_name"]

    def _get():
        section = plex.library.section(library_name)
        missing = []
        for movie in section.all():
            if not movie.thumb:
                missing.append({
                    "title": movie.title,
                    "year": movie.year,
                    "rating_key": movie.ratingKey,
                })
        return {"count": len(missing), "movies": missing}

    return _text(await asyncio.to_thread(_get))


# Preset targets handled by plexapi's tag lookup; everything else is a deviceProfile.
_TARGET_PRESETS = {"mobile", "tv", "original"}

# Maps user-friendly quality strings to plexapi sync VIDEO_QUALITY_* constants.
# "4k" has no explicit constant — VIDEO_QUALITY_ORIGINAL (-1) preserves source resolution.
_QUALITY_MAP = {
    "0.2m": 2, "0.3m": 3, "0.7m": 4,
    "480p": 5, "1.5m": 5,
    "720p": 8, "2m": 6, "3m": 7, "4m": 8,
    "1080p": 9, "8m": 9,
    "1080p_10m": 10, "10m": 10,
    "1080p_high": 11, "12m": 11,
    "1080p_20m": 12, "20m": 12,
    "4k": -1, "original": -1,
}

# Maps shorthand target strings to plexapi deviceProfile names.
_DEVICE_PROFILE_MAP = {
    "android": "Android",
    "ios": "iOS",
    "apple_tv": "Apple TV",
    "chromecast": "Chromecast",
    "universal": "Universal Mobile",
    "universal_mobile": "Universal Mobile",
    "universal_tv": "Universal TV",
    "windows": "Windows",
    "xbox": "Xbox One",
    "windows_phone": "Windows Phone",
}


async def _movie_optimize(plex, args: dict) -> list[TextContent]:
    from plexapi.sync import VIDEO_QUALITY_ORIGINAL
    from changelog import log_change

    rating_key = args["rating_key"]
    target_raw = args["target"].lower().strip()
    quality_raw = str(args["quality"]).lower().strip()
    label = args.get("title") or f"{args['target']} {args['quality']}"

    # Resolve quality to int constant
    video_quality = _QUALITY_MAP.get(quality_raw)
    if video_quality is None:
        try:
            video_quality = int(args["quality"])
        except (TypeError, ValueError):
            return _text(
                f"Unknown quality {args['quality']!r}. "
                f"Use: {', '.join(_QUALITY_MAP)} or a raw integer."
            )

    def _optimize():
        item = plex.fetchItem(int(rating_key))
        if target_raw in _TARGET_PRESETS:
            item.optimize(title=label, target=target_raw)
        else:
            device_profile = _DEVICE_PROFILE_MAP.get(target_raw, args["target"])
            item.optimize(
                title=label,
                deviceProfile=device_profile,
                videoQuality=video_quality,
            )
        quality_label = next(
            (k for k, v in _QUALITY_MAP.items() if v == video_quality and k not in ("original",)),
            str(video_quality),
        )
        return {
            "status": "queued",
            "title": item.title,
            "rating_key": rating_key,
            "target": target_raw,
            "device_profile": _DEVICE_PROFILE_MAP.get(target_raw, args["target"]) if target_raw not in _TARGET_PRESETS else None,
            "video_quality": video_quality,
            "quality_label": quality_label,
            "label": label,
        }

    result = await asyncio.to_thread(_optimize)
    log_change("movie_optimize", f"ratingKey={rating_key}", f"target={target_raw} quality={video_quality} label={label}")
    return _text(result)


async def _movie_merge(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    primary_key = args["primary_rating_key"]
    merge_keys = args["merge_rating_keys"]

    def _merge():
        primary = plex.fetchItem(int(primary_key))
        ids = ",".join(str(k) for k in merge_keys)
        plex.query(
            f"/library/metadata/{primary_key}/merge",
            method=plex._session.put,
            params={"ids": ids},
        )
        merged_titles = []
        for k in merge_keys:
            try:
                merged_titles.append(plex.fetchItem(int(k)).title)
            except Exception:
                merged_titles.append(str(k))
        return {
            "status": "ok",
            "primary": {"title": primary.title, "rating_key": primary_key},
            "merged": merged_titles,
            "action": f"merged {len(merge_keys)} item(s) into '{primary.title}'",
        }

    result = await asyncio.to_thread(_merge)
    log_change(
        "movie_merge",
        f"primary={primary_key}",
        f"merged keys={merge_keys}",
    )
    return _text(result)


async def _movie_split_media(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    rating_key = args["rating_key"]
    library_name = args["library_name"]
    confirmed = args.get("confirmed", False)

    def _preview_or_split():
        item = plex.fetchItem(int(rating_key))
        item.reload()
        files = [m.parts[0].file for m in item.media if m.parts]
        media_count = len(item.media)

        if not confirmed:
            return {
                "status": "preview",
                "item": item.title,
                "rating_key": rating_key,
                "media_versions": media_count,
                "files": files,
                "action_required": "Pass confirmed=true to execute the split",
            }

        # Split all merged versions into separate items — does NOT delete files
        plex.query(
            f"/library/metadata/{rating_key}/split",
            method=plex._session.put,
        )

        # Do NOT auto-scan: scanning immediately after split lets Plex re-merge
        # files whose metadata overlaps. Apply correct matches first, then library_scan.
        return {
            "status": "ok",
            "split_item": item.title,
            "rating_key": rating_key,
            "files": files,
            "next_steps": (
                "1. Run movie_find_candidates / movie_apply_match on each split item "
                "to apply the correct metadata before Plex rescans. "
                "2. Then run library_scan to pick up any remaining unmatched files."
            ),
        }

    result = await asyncio.to_thread(_preview_or_split)
    if confirmed:
        log_change(
            "movie_split_media",
            f"ratingKey={rating_key}",
            f"split files={result.get('files')}",
        )
    return _text(result)


# ── New implementations ────────────────────────────────────────────────────────

async def _movie_list_merged(plex, args: dict) -> list[TextContent]:
    """Items with more than one Media object — merged / multi-version."""
    library_name = args["library_name"]

    def _get():
        section = plex.library.section(library_name)
        results = []
        for item in section.all():
            if len(item.media) > 1:
                media_files = []
                for m in item.media:
                    for p in m.parts:
                        media_files.append({
                            "media_id":   m.id,
                            "file":       p.file,
                            "resolution": getattr(m, "videoResolution", None)
                                          or (f"{m.width}x{m.height}" if m.width and m.height else "?"),
                            "codec":      m.videoCodec,
                            "bitrate":    m.bitrate,
                            "duration_ms": m.duration,
                        })
                results.append({
                    "title":       item.title,
                    "year":        item.year,
                    "rating_key":  item.ratingKey,
                    "media_count": len(item.media),
                    "media_files": media_files,
                })
        return {"library": library_name, "merged_count": len(results), "items": results}

    return _text(await asyncio.to_thread(_get))


async def _movie_list_unmatched(plex, args: dict) -> list[TextContent]:
    """Items whose guid shows no external metadata agent match."""
    library_name = args["library_name"]

    # Known provider tokens that appear in a matched guid
    _KNOWN = ("imdb", "tmdb", "tvdb", "thetvdb", "themoviedb", "plex://", "com.plexapp.agents.imdb",
              "com.plexapp.agents.themoviedb", "com.plexapp.agents.thetvdb")

    def _is_unmatched(item) -> bool:
        guid = item.guid or ""
        # Explicit "none" agent or local path
        if "agents.none" in guid or guid.startswith("local://"):
            return True
        # If no known provider appears in the guid it's also considered unmatched
        return not any(p in guid for p in _KNOWN)

    def _get():
        section = plex.library.section(library_name)
        results = []
        for item in section.all():
            if _is_unmatched(item):
                media_files = [
                    p.file
                    for m in getattr(item, "media", [])
                    for p in getattr(m, "parts", [])
                ]
                results.append({
                    "title":       item.title,
                    "year":        getattr(item, "year", None),
                    "rating_key":  item.ratingKey,
                    "guid":        item.guid,
                    "media_files": media_files,
                })
        return {"library": library_name, "unmatched_count": len(results), "items": results}

    return _text(await asyncio.to_thread(_get))
