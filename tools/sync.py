"""
plex_sync — copy metadata from a source Plex server to the connected destination server.

Matches items by GUID (with legacy-agent translation), then applies:
  • sort-title overrides (locked so refreshes don't overwrite them)
  • current poster (downloaded from source, uploaded to destination)
  • watch state (watched / unwatched)
  • collections (recreated on destination by GUID-matched members)
"""

import asyncio
import json
import logging
import os
import tempfile

import requests as req
from mcp.types import TextContent, Tool
from plexapi.server import PlexServer

logger = logging.getLogger(__name__)

TOOLS = [
    Tool(
        name="plex_sync",
        description=(
            "Sync metadata from a source Plex server to the currently connected destination server. "
            "Matches items by GUID (handles both modern and legacy agent formats). "
            "Syncs sort titles, posters, watch state, and collections. "
            "Use dry_run=true first to preview what would change."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "source_url": {
                    "type": "string",
                    "description": "Base URL of the source server e.g. http://192.168.1.109:32400",
                },
                "source_token": {
                    "type": "string",
                    "description": "Plex auth token for the source server",
                },
                "library_name": {
                    "type": "string",
                    "description": "Sync only this library (omit to sync all libraries)",
                },
                "sync_posters": {
                    "type": "boolean",
                    "default": True,
                    "description": "Download selected poster from source and upload to destination",
                },
                "sync_sort_titles": {
                    "type": "boolean",
                    "default": True,
                    "description": "Copy titleSort overrides (locked to survive metadata refreshes)",
                },
                "sync_watched": {
                    "type": "boolean",
                    "default": True,
                    "description": "Copy watch state and view counts",
                },
                "sync_collections": {
                    "type": "boolean",
                    "default": True,
                    "description": "Recreate source collections on destination by matching members via GUID",
                },
                "dry_run": {
                    "type": "boolean",
                    "default": False,
                    "description": "Report what would be synced without making any changes",
                },
            },
            "required": ["source_url", "source_token"],
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
        if name == "plex_sync":
            return await _plex_sync(plex, args)
    except Exception as exc:
        logger.exception("Error in sync tool %s", name)
        return _text(f"Error: {exc}")
    return _text(f"Unknown tool: {name}")


# ── GUID normalisation ────────────────────────────────────────────────────────

# Maps legacy com.plexapp.agents.* prefixes to canonical provider names
_LEGACY_AGENT = {
    "com.plexapp.agents.imdb":            "imdb",
    "com.plexapp.agents.themoviedb":      "tmdb",
    "com.plexapp.agents.thetvdb":         "tvdb",
    "com.plexapp.agents.thetvdbdvdorder": "tvdb",
    "com.plexapp.agents.hama":            "tvdb",   # HAMA stores tvdb IDs
    "com.plexapp.agents.musicbrainz":     "mbid",
}


def normalize_guids(item) -> set[str]:
    """Return a set of canonical 'provider://id' strings for cross-server matching.

    Handles both:
      • Modern:  item.guids → [Guid(id='imdb://tt1234567'), ...]
      • Legacy:  item.guid  → 'com.plexapp.agents.imdb://tt1234567?lang=en'
    """
    result: set[str] = set()

    # Modern multi-GUID list
    for g in getattr(item, "guids", []):
        raw = g.id if hasattr(g, "id") else str(g)
        result.add(raw.split("?")[0])  # strip ?lang= suffix

    # Legacy single-GUID string
    guid = (getattr(item, "guid", None) or "").split("?")[0]
    if not guid or "agents.none" in guid or "local://" in guid:
        pass
    elif guid.startswith("plex://") or "://" in guid and not guid.startswith("com.plexapp"):
        # Already in canonical form (plex://movie/…, imdb://tt…, tmdb://…)
        result.add(guid)
    else:
        # Legacy form: com.plexapp.agents.PROVIDER://RAW_ID[/season/ep]
        for prefix, provider in _LEGACY_AGENT.items():
            if guid.startswith(prefix + "://"):
                raw_id = guid[len(prefix) + 3:].lstrip("/").split("/")[0]
                result.add(f"{provider}://{raw_id}")
                break

    return result


# ── Destination GUID index ────────────────────────────────────────────────────

def _build_guid_index(section) -> dict[str, object]:
    """Map every normalised GUID → destination item for fast lookup."""
    index: dict[str, object] = {}
    for item in section.all():
        for guid in normalize_guids(item):
            index[guid] = item
    return index


def _find_dest(src_item, guid_index: dict) -> object | None:
    for guid in normalize_guids(src_item):
        if guid in guid_index:
            return guid_index[guid]
    return None


# ── Per-field sync helpers ────────────────────────────────────────────────────

def _sync_sort_title(src_item, dst_item, dry_run: bool, log: list) -> None:
    src_sort = getattr(src_item, "titleSort", None) or ""
    src_title = getattr(src_item, "title", "")
    # Only bother if titleSort differs from the plain title (i.e. it's a real override)
    if not src_sort or src_sort == src_title:
        return
    dst_sort = getattr(dst_item, "titleSort", None) or ""
    if dst_sort == src_sort:
        return
    label = f"sort_title '{src_title}' → '{src_sort}'"
    if not dry_run:
        dst_item.edit(**{"titleSort.value": src_sort, "titleSort.locked": 1})
    log.append({"action": "sort_title", "title": src_title, "value": src_sort, "dry_run": dry_run})


def _sync_poster(src_item, dst_item, src_baseurl: str, src_token: str,
                 dry_run: bool, log: list, errors: list) -> None:
    thumb = getattr(src_item, "thumb", None)
    if not thumb:
        return
    if dry_run:
        log.append({"action": "poster", "title": src_item.title, "dry_run": True})
        return
    try:
        url = f"{src_baseurl.rstrip('/')}{thumb}?X-Plex-Token={src_token}"
        resp = req.get(url, timeout=30, verify=False)
        resp.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(resp.content)
            tmp = f.name
        try:
            dst_item.uploadPoster(filepath=tmp)
            dst_item.edit(**{"thumb.locked": 1})
            log.append({"action": "poster", "title": src_item.title})
        finally:
            os.unlink(tmp)
    except Exception as exc:
        errors.append({"title": src_item.title, "error": f"poster: {exc}"})


def _sync_watched_movie(src_item, dst_item, dry_run: bool, log: list) -> None:
    src_watched = bool(getattr(src_item, "isWatched", False))
    src_count   = int(getattr(src_item, "viewCount", 0) or 0)
    dst_watched = bool(getattr(dst_item, "isWatched", False))
    effectively_watched = src_watched or src_count > 0
    if effectively_watched == dst_watched:
        return
    action = "mark_watched" if effectively_watched else "mark_unwatched"
    if not dry_run:
        if effectively_watched:
            dst_item.markWatched()
        else:
            dst_item.markUnwatched()
    log.append({"action": action, "title": src_item.title, "dry_run": dry_run})


# ── TV-show episode watched sync ──────────────────────────────────────────────

def _sync_show_episodes(src_show, dst_show, dry_run: bool, log: list) -> None:
    """Match episodes by (season, episode number) and copy watch state."""
    # Build a (season, ep) → dst_episode map
    dst_ep_map: dict[tuple[int, int], object] = {}
    for ep in dst_show.episodes():
        key = (ep.seasonNumber, ep.index)
        dst_ep_map[key] = ep

    for src_ep in src_show.episodes():
        key = (src_ep.seasonNumber, src_ep.index)
        dst_ep = dst_ep_map.get(key)
        if dst_ep is None:
            continue
        _sync_watched_movie(src_ep, dst_ep, dry_run, log)


# ── Collection sync ───────────────────────────────────────────────────────────

def _sync_collections(src_section, dst_section, dst_guid_index: dict,
                      dry_run: bool, log: list) -> list[dict]:
    results: list[dict] = []
    try:
        src_collections = src_section.collections()
    except Exception:
        return results

    # Build existing-collection map for destination (case-insensitive)
    dst_col_map: dict[str, object] = {}
    for c in dst_section.collections():
        dst_col_map[c.title.lower()] = c

    for src_col in src_collections:
        dst_members = []
        not_found   = []
        try:
            src_members = src_col.items()
        except Exception as exc:
            results.append({"collection": src_col.title, "error": str(exc)})
            continue

        for src_item in src_members:
            dst_item = _find_dest(src_item, dst_guid_index)
            if dst_item:
                dst_members.append(dst_item)
            else:
                not_found.append(f"{src_item.title} ({getattr(src_item, 'year', '?')})")

        entry: dict = {
            "collection": src_col.title,
            "matched":    len(dst_members),
            "not_found":  not_found,
            "dry_run":    dry_run,
        }

        if not dst_members:
            entry["action"] = "skipped_no_members"
            results.append(entry)
            continue

        if dry_run:
            entry["action"] = "would_create_or_update"
            results.append(entry)
            continue

        existing = dst_col_map.get(src_col.title.lower())
        if existing:
            # Add any new members (items already in collection are silently ignored by Plex)
            existing.addItems(dst_members)
            entry["action"] = "updated"
        else:
            dst_section.createCollection(src_col.title, items=dst_members)
            entry["action"] = "created"
        results.append(entry)

    return results


# ── Main sync entrypoint ──────────────────────────────────────────────────────

async def _plex_sync(dst_plex, args: dict) -> list[TextContent]:
    source_url      = args["source_url"].rstrip("/")
    source_token    = args["source_token"]
    target_library  = args.get("library_name")
    do_posters      = args.get("sync_posters",      True)
    do_sort         = args.get("sync_sort_titles",   True)
    do_watched      = args.get("sync_watched",       True)
    do_collections  = args.get("sync_collections",   True)
    dry_run         = args.get("dry_run",            False)

    def _run() -> dict:
        # ── Connect to source ─────────────────────────────────────────────
        try:
            src_plex = PlexServer(source_url, source_token)
            src_name = src_plex.friendlyName
        except Exception as exc:
            return {"error": f"Cannot connect to source server: {exc}"}

        dst_name = dst_plex.friendlyName
        summary: dict = {
            "source":      src_name,
            "destination": dst_name,
            "dry_run":     dry_run,
            "libraries":   {},
        }

        # ── Enumerate source libraries to process ─────────────────────────
        src_sections = src_plex.library.sections()
        if target_library:
            src_sections = [s for s in src_sections if s.title == target_library]
            if not src_sections:
                return {"error": f"Library '{target_library}' not found on source server"}

        for src_section in src_sections:
            lib_result: dict = {
                "type":                src_section.type,
                "matched":             0,
                "not_found":           [],
                "sort_title_applied":  0,
                "poster_applied":      0,
                "watched_applied":     0,
                "poster_errors":       [],
                "collections":         [],
                "actions":             [],
            }

            # Find the same-named library on destination
            try:
                dst_section = dst_plex.library.section(src_section.title)
            except Exception:
                lib_result["error"] = f"Library '{src_section.title}' not found on destination"
                summary["libraries"][src_section.title] = lib_result
                continue

            # ── Build GUID index for destination section ──────────────────
            logger.info("Building GUID index for '%s'…", src_section.title)
            dst_guid_index = _build_guid_index(dst_section)

            # ── Sync items ────────────────────────────────────────────────
            for src_item in src_section.all():
                dst_item = _find_dest(src_item, dst_guid_index)

                if dst_item is None:
                    src_guids = normalize_guids(src_item)
                    lib_result["not_found"].append(
                        f"✗ Not found: {src_item.title}"
                        f" ({getattr(src_item, 'year', '?')})"
                        f" — source GUIDs: {sorted(src_guids)}"
                    )
                    continue

                lib_result["matched"] += 1
                item_log:   list = []
                item_errors: list = []

                if do_sort:
                    _sync_sort_title(src_item, dst_item, dry_run, item_log)

                if do_posters:
                    _sync_poster(src_item, dst_item, source_url, source_token,
                                 dry_run, item_log, item_errors)

                if do_watched:
                    if src_section.type == "show":
                        # Show-level: poster + sort title already handled above.
                        # Episode watched state: match by season+episode number.
                        _sync_show_episodes(src_item, dst_item, dry_run, item_log)
                    else:
                        _sync_watched_movie(src_item, dst_item, dry_run, item_log)

                # Tally
                for entry in item_log:
                    action = entry.get("action", "")
                    if "sort_title" in action:
                        lib_result["sort_title_applied"] += 1
                    elif "poster" in action:
                        lib_result["poster_applied"] += 1
                    elif "watched" in action or "mark_" in action:
                        lib_result["watched_applied"] += 1

                if item_errors:
                    lib_result["poster_errors"].extend(item_errors)

                if item_log:
                    lib_result["actions"].append({
                        "title":   src_item.title,
                        "changes": item_log,
                    })

            # ── Sync collections ──────────────────────────────────────────
            if do_collections and src_section.type in ("movie", "show"):
                logger.info("Syncing collections for '%s'…", src_section.title)
                col_results = _sync_collections(
                    src_section, dst_section, dst_guid_index, dry_run, []
                )
                lib_result["collections"] = col_results

            summary["libraries"][src_section.title] = lib_result

        # ── Top-level totals ──────────────────────────────────────────────
        total_matched    = sum(v.get("matched",   0)         for v in summary["libraries"].values())
        total_not_found  = sum(len(v.get("not_found", []))   for v in summary["libraries"].values())
        total_col_created = sum(
            1
            for v in summary["libraries"].values()
            for c in v.get("collections", [])
            if c.get("action") in ("created", "would_create_or_update")
        )
        summary["totals"] = {
            "items_matched":       total_matched,
            "items_not_found":     total_not_found,
            "collections_created": total_col_created,
        }
        return summary

    result = await asyncio.to_thread(_run)
    return _text(result)
