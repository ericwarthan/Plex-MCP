import asyncio
import json
import logging

from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

TOOLS = [
    Tool(
        name="server_identity",
        description="Get Plex server identity: name, version, platform, machine identifier",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="server_capabilities",
        description="Get Plex server feature capabilities and enabled flags",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="server_preferences",
        description=(
            "Get Plex server preferences and settings. Supports optional group filter "
            "(e.g. 'transcoder', 'network', 'library', 'dlna'). Returns id, label, "
            "current value, default, and summary for each preference."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "group": {
                    "type": "string",
                    "description": "Optional group name to filter (case-insensitive substring match)",
                }
            },
        },
    ),
    Tool(
        name="server_set_preference",
        description="Set a Plex server preference by its ID (e.g. 'TranscoderQuality', 'HardwareAcceleratedCodecs')",
        inputSchema={
            "type": "object",
            "properties": {
                "preference_id": {"type": "string", "description": "Preference ID as returned by server_preferences"},
                "value": {"description": "New value for the preference"},
            },
            "required": ["preference_id", "value"],
        },
    ),
    Tool(
        name="server_check_updates",
        description="Check if a Plex Media Server software update is available",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="server_apply_update",
        description="Apply a pending Plex Media Server update",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="server_activity_log",
        description="Get current server activity log (background tasks, scans, etc.)",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max entries to return (default 50)"},
            },
        },
    ),
    Tool(
        name="server_transient_token",
        description="Get a short-lived transient Plex token for resource access (token value is [REDACTED] in logs)",
        inputSchema={
            "type": "object",
            "properties": {
                "token_type": {
                    "type": "string",
                    "description": "Token type: 'delegation' (default) or 'managed'",
                    "default": "delegation",
                }
            },
        },
    ),
    Tool(
        name="server_statistics",
        description="Get Plex server resource and media statistics",
        inputSchema={"type": "object", "properties": {}},
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


def _text(data) -> list[TextContent]:
    if isinstance(data, str):
        return [TextContent(type="text", text=data)]
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


async def handle_tool(name: str, args: dict, plex) -> list[TextContent]:
    try:
        if name == "server_identity":
            return await _server_identity(plex)
        if name == "server_capabilities":
            return await _server_capabilities(plex)
        if name == "server_preferences":
            return await _server_preferences(plex, args)
        if name == "server_set_preference":
            return await _server_set_preference(plex, args)
        if name == "server_check_updates":
            return await _server_check_updates(plex)
        if name == "server_apply_update":
            return await _server_apply_update(plex)
        if name == "server_activity_log":
            return await _server_activity_log(plex, args)
        if name == "server_transient_token":
            return await _server_transient_token(plex, args)
        if name == "server_statistics":
            return await _server_statistics(plex)
    except Exception as exc:
        logger.exception("Error in server_admin tool %s", name)
        return _text(f"Error: {exc}")
    return _text(f"Unknown tool: {name}")


async def _server_identity(plex) -> list[TextContent]:
    def _get():
        return {
            "name": plex.friendlyName,
            "version": plex.version,
            "platform": plex.platform,
            "platform_version": plex.platformVersion,
            "machine_identifier": plex.machineIdentifier,
            "my_plex_username": getattr(plex, "myPlexUsername", None),
            "my_plex_subscription": getattr(plex, "myPlexSubscription", None),
            "transcoder_active_video_sessions": plex.transcoderActiveVideoSessions,
        }
    return _text(await asyncio.to_thread(_get))


async def _server_capabilities(plex) -> list[TextContent]:
    def _get():
        attrs = [
            "livetv", "sync", "hubSearch", "mediaProviders",
            "allowMediaDeletion", "allowCameraUpload", "allowChannelAccess",
            "allowSharing", "allowSync", "allowTuners",
        ]
        return {a: getattr(plex, a, None) for a in attrs}
    return _text(await asyncio.to_thread(_get))


async def _server_preferences(plex, args: dict) -> list[TextContent]:
    group_filter = args.get("group", "").lower()

    def _get():
        result = []
        for p in plex.settings.all():
            grp = getattr(p, "group", "") or ""
            if group_filter and group_filter not in grp.lower():
                continue
            result.append({
                "id": p.id,
                "label": p.label,
                "summary": p.summary,
                "type": p.type,
                "value": p.value,
                "default": p.default,
                "group": grp,
            })
        return result

    return _text(await asyncio.to_thread(_get))


async def _server_set_preference(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    pref_id = args["preference_id"]
    value = args["value"]

    def _coerce(pref, raw):
        ptype = getattr(pref, "type", None)
        if ptype == "bool":
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in ("true", "1", "yes")
        if ptype == "int":
            return int(raw)
        if ptype == "double":
            return float(raw)
        return raw

    def _set():
        pref = plex.settings.get(pref_id)
        coerced = _coerce(pref, value)
        pref.set(coerced)
        plex.settings.save()
        return f"Preference '{pref_id}' set to {coerced!r} (type={getattr(pref, 'type', 'unknown')})"

    result = await asyncio.to_thread(_set)
    log_change("server_set_preference", pref_id, f"set to {value!r}")
    return _text(result)


async def _server_check_updates(plex) -> list[TextContent]:
    def _check():
        try:
            result = plex.checkForUpdate()
            if result is None:
                return "No updates available — server is up to date"
            return str(result)
        except Exception as exc:
            return f"Update check failed: {exc}"

    return _text(await asyncio.to_thread(_check))


async def _server_apply_update(plex) -> list[TextContent]:
    from changelog import log_change

    def _apply():
        plex.applySettingsUpdate()
        return "Update applied — server may restart shortly"

    result = await asyncio.to_thread(_apply)
    log_change("server_apply_update", "plex-server", "Applied pending server update")
    return _text(result)


async def _server_activity_log(plex, args: dict) -> list[TextContent]:
    limit = int(args.get("limit", 50))

    def _get():
        try:
            activities = plex.activities()
            return [
                {
                    "type": a.type,
                    "title": getattr(a, "title", ""),
                    "subtitle": getattr(a, "subtitle", ""),
                    "progress": getattr(a, "progress", None),
                    "cancellable": getattr(a, "cancellable", False),
                    "uuid": getattr(a, "uuid", None),
                }
                for a in activities[:limit]
            ]
        except Exception as exc:
            return {"error": str(exc)}

    return _text(await asyncio.to_thread(_get))


async def _server_transient_token(plex, args: dict) -> list[TextContent]:
    token_type = args.get("token_type", "delegation")

    def _get():
        try:
            token = plex.transientToken(type=token_type, scope="all")
            return {
                "status": "ok",
                "token": "[REDACTED]",
                "type": token_type,
                "note": "Token obtained — value masked in output per security policy",
            }
        except Exception as exc:
            return {"error": str(exc)}

    return _text(await asyncio.to_thread(_get))


async def _server_statistics(plex) -> list[TextContent]:
    def _get():
        # Library item counts
        libraries = [
            {"name": s.title, "type": s.type, "items": s.totalSize}
            for s in plex.library.sections()
        ]

        # Active transcoder sessions
        try:
            sessions = plex.sessions()
            active_sessions = len(sessions)
        except Exception:
            active_sessions = None

        # Recent bandwidth samples (last 20, newest first)
        bandwidth = []
        try:
            root = plex.query("/statistics/bandwidth")
            children = list(root)
            for child in children[-20:]:
                a = child.attrib
                bandwidth.append({
                    "client": a.get("name"),
                    "platform": a.get("platform"),
                    "at": a.get("createdAt"),
                })
            bandwidth.reverse()
        except Exception as exc:
            bandwidth = {"error": str(exc)}

        # Play history count
        try:
            media_root = plex.query("/statistics/media")
            play_history_count = int(media_root.attrib.get("size", 0))
        except Exception:
            play_history_count = None

        return {
            "libraries": libraries,
            "active_sessions": active_sessions,
            "play_history_total": play_history_count,
            "recent_bandwidth_clients": bandwidth,
        }

    return _text(await asyncio.to_thread(_get))
