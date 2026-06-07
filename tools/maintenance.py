import asyncio
import io
import json
import logging
import os
import tempfile
import zipfile
from pathlib import Path

from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

TOOLS = [
    Tool(
        name="maintenance_empty_all_trash",
        description="Empty trash on ALL libraries simultaneously. Requires confirmed=true.",
        inputSchema={
            "type": "object",
            "properties": {
                "confirmed": {"type": "boolean"},
            },
            "required": ["confirmed"],
        },
    ),
    Tool(
        name="maintenance_optimize_database",
        description="Run Plex database optimization (VACUUM and ANALYZE)",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="maintenance_clean_bundles",
        description="Clean up Plex bundle files (removes orphaned metadata bundles)",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="maintenance_empty_codecs",
        description="Clean the Plex codecs cache (forces re-download on next use)",
        inputSchema={
            "type": "object",
            "properties": {
                "confirmed": {"type": "boolean"},
            },
            "required": ["confirmed"],
        },
    ),
    Tool(
        name="maintenance_download_logs",
        description=(
            "Download Plex server diagnostics log archive to ~/.config/plex-mcp/logs/. "
            "Warning: the archive can be very large and may time out (up to 3 min). "
            "For quick log access use the Plex web UI Settings > Troubleshooting > Logs."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="maintenance_check_orphaned",
        description=(
            "Scan a library for items whose files no longer exist on disk "
            "(orphaned database entries)"
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
        name="maintenance_library_info",
        description="Get storage and metadata statistics for a library",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="maintenance_server_logs_tail",
        description=(
            "Return recent Plex server log lines. "
            "Reads the log file directly when the MCP server runs on the same host as Plex; "
            "otherwise streams the diagnostics archive (may take 15-30 s on large installs). "
            "Filter by minimum severity (info/warn/error) and optional source component."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "limit":     {"type": "integer", "default": 100, "description": "Number of log lines to return (newest first)"},
                "min_level": {"type": "string", "enum": ["debug", "info", "warn", "error"], "default": "info"},
                "source":    {"type": "string", "description": "Optional component filter, e.g. 'Scanner', 'Transcode', 'Library'"},
            },
        },
    ),
    Tool(
        name="maintenance_library_health",
        description=(
            "Run a combined health check across all libraries (or a single named library). "
            "Reports: unmatched items, merged/multi-version items, and items with missing files."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string", "description": "Specific library to check (omit to check all)"},
            },
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
        if name == "maintenance_empty_all_trash":
            return await _empty_all_trash(plex, args)
        if name == "maintenance_optimize_database":
            return await _optimize_db(plex)
        if name == "maintenance_clean_bundles":
            return await _clean_bundles(plex)
        if name == "maintenance_empty_codecs":
            return await _empty_codecs(plex, args)
        if name == "maintenance_download_logs":
            return await _download_logs(plex)
        if name == "maintenance_check_orphaned":
            return await _check_orphaned(plex, args)
        if name == "maintenance_library_info":
            return await _library_info(plex, args)
        if name == "maintenance_server_logs_tail":
            return await _server_logs_tail(plex, args)
        if name == "maintenance_library_health":
            return await _library_health(plex, args)
    except Exception as exc:
        logger.exception("Error in maintenance tool %s", name)
        return _text(f"Error: {exc}")
    return _text(f"Unknown tool: {name}")


async def _empty_all_trash(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    if not args.get("confirmed"):
        return _text(
            "This will permanently empty trash on ALL libraries. Set confirmed=true to proceed."
        )

    def _do():
        sections = plex.library.sections()
        emptied = []
        for section in sections:
            section.emptyTrash()
            emptied.append(section.title)
        return f"Trash emptied for libraries: {', '.join(emptied)}"

    result = await asyncio.to_thread(_do)
    log_change("maintenance_empty_all_trash", "all-libraries", result)
    return _text(result)


async def _optimize_db(plex) -> list[TextContent]:
    from changelog import log_change

    def _do():
        plex.library.optimize()
        return "Database optimization started"

    result = await asyncio.to_thread(_do)
    log_change("maintenance_optimize_database", "plex-db", "Started database optimization")
    return _text(result)


async def _clean_bundles(plex) -> list[TextContent]:
    from changelog import log_change

    def _do():
        plex.library.cleanBundles()
        return "Bundle cleanup started"

    result = await asyncio.to_thread(_do)
    log_change("maintenance_clean_bundles", "plex-bundles", "Started bundle cleanup")
    return _text(result)


async def _empty_codecs(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    if not args.get("confirmed"):
        return _text(
            "Emptying the codec cache will cause a brief delay on next playback while codecs re-download. "
            "Set confirmed=true to proceed."
        )

    def _do():
        plex.emptyCodecs()
        return "Codec cache emptied"

    result = await asyncio.to_thread(_do)
    log_change("maintenance_empty_codecs", "codec-cache", "Emptied codec cache")
    return _text(result)


def _stream_log_zip(plex, dest_path: Path) -> list[str]:
    """Stream /diagnostics/logs to dest_path and return the zip's file list."""
    import requests as req
    url = plex.url("/diagnostics/logs")
    with req.get(url, headers={"X-Plex-Token": plex._token}, stream=True,
                 timeout=(10, 180), verify=False) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)
    with zipfile.ZipFile(dest_path) as zf:
        return zf.namelist()


async def _download_logs(plex) -> list[TextContent]:
    from config import CONFIG_DIR

    def _do():
        logs_dir = CONFIG_DIR / "logs"
        logs_dir.mkdir(exist_ok=True)
        zip_path = logs_dir / "plex-logs.zip"
        file_list = _stream_log_zip(plex, zip_path)
        return {"saved_to": str(zip_path), "files": file_list}

    return _text(await asyncio.to_thread(_do))


async def _check_orphaned(plex, args: dict) -> list[TextContent]:
    library_name = args["library_name"]

    def _do():
        section = plex.library.section(library_name)
        orphaned = []
        for item in section.all():
            for media in getattr(item, "media", []):
                for part in getattr(media, "parts", []):
                    if part.file and not os.path.exists(part.file):
                        orphaned.append({
                            "title": item.title,
                            "rating_key": item.ratingKey,
                            "missing_file": part.file,
                        })
        return {
            "library": library_name,
            "orphaned_count": len(orphaned),
            "orphaned": orphaned,
        }

    return _text(await asyncio.to_thread(_do))


async def _library_info(plex, args: dict) -> list[TextContent]:
    library_name = args["library_name"]

    def _get():
        section = plex.library.section(library_name)
        return {
            "name": section.title,
            "type": section.type,
            "total_items": section.totalSize,
            "locations": section.locations,
            "agent": section.agent,
            "language": section.language,
            "refreshing": section.refreshing,
            "created_at": str(section.createdAt),
            "updated_at": str(section.updatedAt),
        }

    return _text(await asyncio.to_thread(_get))


async def _server_logs_tail(plex, args: dict) -> list[TextContent]:
    limit     = int(args.get("limit", 100))
    min_level = args.get("min_level", "info").upper()
    source    = args.get("source", None)

    # Plex log format: "Jun 06, 2026 22:23:01.709 [tid] LEVEL - message"
    # Levels in log file: DEBUG, INFO, WARN, ERROR
    _LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARN": 2, "WARNING": 2, "ERROR": 3}
    _MIN = _LEVEL_ORDER.get(min_level, 1)

    import re
    _LINE_RE = re.compile(
        r"^(\w{3}\s+\d+,\s+\d{4}\s+[\d:.]+)"   # timestamp
        r"\s+\[\d+\]\s+"                           # thread id
        r"(\w+)"                                   # level
        r"\s+-\s+(.*)",                            # message
        re.DOTALL,
    )

    def _parse_lines(text: str) -> list[dict]:
        entries = []
        for line in text.splitlines():
            m = _LINE_RE.match(line.strip())
            if not m:
                continue
            ts, level, msg = m.group(1), m.group(2).upper(), m.group(3).strip()
            if _LEVEL_ORDER.get(level, 0) < _MIN:
                continue
            if source and source.lower() not in msg.lower():
                continue
            entries.append({"timestamp": ts, "level": level, "message": msg})
        return entries

    def _get():
        # ── Strategy 1: read log file directly (same-host deployment) ─────────
        log_path = None
        try:
            prefs_xml = plex.query("/:/prefs")
            for el in prefs_xml.iter():
                val = el.get("value") or el.get("default", "")
                # LocalAppDataPath holds the Plex application data root
                if el.get("id") == "LocalAppDataPath" and val:
                    from pathlib import Path
                    log_path = (
                        Path(val) / "Plex Media Server" / "Logs" / "Plex Media Server.log"
                    )
                    break
        except Exception:
            pass

        if log_path and log_path.exists():
            # Read last ~500 KB — enough for several hundred log lines
            with open(log_path, "rb") as fh:
                fh.seek(0, 2)
                size = fh.tell()
                fh.seek(max(0, size - 524288))
                raw = fh.read().decode("utf-8", errors="replace")
            entries = _parse_lines(raw)[-limit:]
            entries.reverse()
            return {
                "source": "log_file",
                "log_path": str(log_path),
                "returned": len(entries),
                "entries": entries,
            }

        # ── Strategy 2: stream diagnostics ZIP, extract main log ──────────────
        import io, requests as req, zipfile
        url = plex.url("/diagnostics/logs")
        result_entries: list[dict] = []
        try:
            with req.get(
                url,
                headers={"X-Plex-Token": plex._token},
                stream=True,
                timeout=(10, 60),
                verify=False,
            ) as r:
                r.raise_for_status()
                buf = io.BytesIO(r.content)  # read full response (may be large)

            with zipfile.ZipFile(buf) as zf:
                # Find the main server log (not plugin/transcoder logs)
                candidates = [
                    n for n in zf.namelist()
                    if "Plex Media Server.log" in n and "crash" not in n.lower()
                ]
                if candidates:
                    raw = zf.read(candidates[0]).decode("utf-8", errors="replace")
                    result_entries = _parse_lines(raw)[-limit:]
                    result_entries.reverse()
                    return {
                        "source": "diagnostics_zip",
                        "log_file": candidates[0],
                        "returned": len(result_entries),
                        "entries": result_entries,
                    }
        except Exception as exc:
            return {
                "source": "unavailable",
                "error": str(exc),
                "note": (
                    "Log file is not directly readable (MCP running on a different host than Plex) "
                    "and the diagnostics download failed or timed out. "
                    "View logs in the Plex web UI under Settings → Troubleshooting → Logs."
                ),
            }

        return {"source": "unavailable", "entries": []}

    return _text(await asyncio.to_thread(_get))


async def _library_health(plex, args: dict) -> list[TextContent]:
    """Combined unmatched / merged / orphaned check across one or all libraries."""
    target_name = args.get("library_name")

    _KNOWN_PROVIDERS = (
        "imdb", "tmdb", "tvdb", "thetvdb", "themoviedb", "plex://",
        "com.plexapp.agents.imdb", "com.plexapp.agents.themoviedb",
        "com.plexapp.agents.thetvdb",
    )

    def _is_unmatched(item) -> bool:
        guid = item.guid or ""
        if "agents.none" in guid or guid.startswith("local://"):
            return True
        return not any(p in guid for p in _KNOWN_PROVIDERS)

    def _check_section(section) -> dict:
        unmatched, merged, orphaned = [], [], []
        for item in section.all():
            # Unmatched (no external metadata)
            if _is_unmatched(item):
                unmatched.append({"title": item.title, "rating_key": item.ratingKey, "guid": item.guid})
            # Merged (multiple media files on one item)
            if len(item.media) > 1:
                merged.append({
                    "title": item.title,
                    "rating_key": item.ratingKey,
                    "media_count": len(item.media),
                })
            # Orphaned (file missing from disk)
            for m in getattr(item, "media", []):
                for p in getattr(m, "parts", []):
                    if p.file and not os.path.exists(p.file):
                        orphaned.append({
                            "title": item.title,
                            "rating_key": item.ratingKey,
                            "missing_file": p.file,
                        })
                        break  # one entry per item is enough
        return {
            "library":         section.title,
            "type":            section.type,
            "total_items":     section.totalSize,
            "unmatched_count": len(unmatched),
            "merged_count":    len(merged),
            "orphaned_count":  len(orphaned),
            "unmatched":       unmatched,
            "merged":          merged,
            "orphaned":        orphaned,
        }

    def _run():
        if target_name:
            return {target_name: _check_section(plex.library.section(target_name))}
        return {s.title: _check_section(s) for s in plex.library.sections()}

    return _text(await asyncio.to_thread(_run))
