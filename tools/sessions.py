import asyncio
import json
import logging
from datetime import timedelta

from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

TOOLS = [
    Tool(
        name="session_list",
        description=(
            "Get all active Now Playing sessions with full detail: codec, video resolution, "
            "HDR type (Dolby Vision/HDR10/HLG/SDR), audio format (TrueHD Atmos, DTS:X, etc.), "
            "transcode vs direct play, bitrate, user, client, player state, and progress."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="session_transcode_list",
        description=(
            "Get active transcode sessions with resource usage: speed, progress, "
            "video/audio decision (transcode/copy/directplay), throttle status, codec details."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="session_terminate",
        description="Terminate an active session by session key",
        inputSchema={
            "type": "object",
            "properties": {
                "session_key": {"type": "string", "description": "Session key from session_list"},
                "reason": {"type": "string", "description": "Reason message shown to user", "default": ""},
            },
            "required": ["session_key"],
        },
    ),
    Tool(
        name="session_terminate_transcode",
        description="Terminate an active transcode session by its key",
        inputSchema={
            "type": "object",
            "properties": {
                "transcode_key": {"type": "string", "description": "Transcode key from session_transcode_list"},
            },
            "required": ["transcode_key"],
        },
    ),
    Tool(
        name="session_history",
        description="Get recent session/play history, optionally filtered by username",
        inputSchema={
            "type": "object",
            "properties": {
                "username": {"type": "string", "description": "Filter to a specific user"},
                "limit": {"type": "integer", "default": 50},
            },
        },
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


def _text(data) -> list[TextContent]:
    if isinstance(data, str):
        return [TextContent(type="text", text=data)]
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _detect_hdr(video_stream) -> str:
    if video_stream is None:
        return "Unknown"
    if getattr(video_stream, "DOVIPresent", False):
        return "Dolby Vision"
    ct = getattr(video_stream, "colorTrc", "") or getattr(video_stream, "colorTransfer", "") or ""
    cs = getattr(video_stream, "colorSpace", "") or ""
    if "smpte2084" in ct and "bt2020" in cs:
        return "HDR10"
    if "arib-std-b67" in ct:
        return "HLG"
    hdr_attr = str(getattr(video_stream, "hdr", "") or "")
    if hdr_attr and hdr_attr != "0":
        return "HDR"
    return "SDR"


def _format_session(session) -> dict:
    player = session.player
    media_list = getattr(session, "media", [])
    media = media_list[0] if media_list else None
    part = media.parts[0] if media and media.parts else None
    streams = part.streams if part else []

    video_stream = next((s for s in streams if s.streamType == 1), None)
    audio_stream = next((s for s in streams if s.streamType == 2), None)
    sub_stream = next((s for s in streams if s.streamType == 3 and getattr(s, "selected", False)), None)

    transcode_sessions = getattr(session, "transcodeSessions", [])
    ts = transcode_sessions[0] if transcode_sessions else None

    if ts:
        video_decision = getattr(ts, "videoDecision", "unknown")
        audio_decision = getattr(ts, "audioDecision", "unknown")
        transcode_speed = getattr(ts, "speed", None)
        transcode_progress = getattr(ts, "progress", None)
        throttled = getattr(ts, "throttled", False)
    else:
        video_decision = "directplay"
        audio_decision = "directplay"
        transcode_speed = None
        transcode_progress = None
        throttled = False

    view_offset = getattr(session, "viewOffset", 0) or 0
    duration = getattr(session, "duration", 0) or 0

    def _fmt_ms(ms: int) -> str:
        return str(timedelta(milliseconds=ms)).split(".")[0] if ms else "0:00:00"

    return {
        "session_key": session.sessionKey,
        "title": session.title,
        "type": session.type,
        "grandparent_title": getattr(session, "grandparentTitle", None),
        "parent_title": getattr(session, "parentTitle", None),
        "year": getattr(session, "year", None),
        "user": session.usernames[0] if getattr(session, "usernames", None) else "unknown",
        "progress": {
            "current": _fmt_ms(view_offset),
            "total": _fmt_ms(duration),
            "percent": round(view_offset / duration * 100, 1) if duration else 0,
        },
        "player": {
            "device": player.device,
            "platform": player.platform,
            "product": player.product,
            "state": player.state,
            "address": player.address,
            "title": player.title,
        },
        "video": {
            "codec": getattr(video_stream, "codec", None),
            "display_title": getattr(video_stream, "displayTitle", None),
            "resolution": getattr(media, "videoResolution", None) if media else None,
            "width": getattr(video_stream, "width", None),
            "height": getattr(video_stream, "height", None),
            "bit_depth": getattr(video_stream, "bitDepth", None),
            "hdr": _detect_hdr(video_stream),
            "frame_rate": getattr(media, "videoFrameRate", None) if media else None,
            "decision": video_decision,
        },
        "audio": {
            "codec": getattr(audio_stream, "codec", None),
            "display_title": getattr(audio_stream, "displayTitle", None),
            "channels": getattr(audio_stream, "channels", None),
            "channel_layout": getattr(audio_stream, "audioChannelLayout", None),
            "decision": audio_decision,
        },
        "subtitles": {
            "codec": getattr(sub_stream, "codec", None),
            "language": getattr(sub_stream, "language", None),
        } if sub_stream else None,
        "media": {
            "container": getattr(media, "container", None) if media else None,
            "bitrate_kbps": getattr(media, "bitrate", None) if media else None,
        },
        "transcode": {
            "active": ts is not None,
            "speed": transcode_speed,
            "progress_pct": transcode_progress,
            "throttled": throttled,
        } if ts else {"active": False},
    }


async def handle_tool(name: str, args: dict, plex) -> list[TextContent]:
    try:
        if name == "session_list":
            return await _session_list(plex)
        if name == "session_transcode_list":
            return await _transcode_list(plex)
        if name == "session_terminate":
            return await _terminate_session(plex, args)
        if name == "session_terminate_transcode":
            return await _terminate_transcode(plex, args)
        if name == "session_history":
            return await _session_history(plex, args)
    except Exception as exc:
        logger.exception("Error in sessions tool %s", name)
        return _text(f"Error: {exc}")
    return _text(f"Unknown tool: {name}")


async def _session_list(plex) -> list[TextContent]:
    def _get():
        sessions = plex.sessions()
        if not sessions:
            return "No active sessions"
        return [_format_session(s) for s in sessions]

    return _text(await asyncio.to_thread(_get))


async def _transcode_list(plex) -> list[TextContent]:
    def _get():
        sessions = plex.transcodeSessions()
        if not sessions:
            return "No active transcode sessions"
        result = []
        for ts in sessions:
            result.append({
                "key": ts.key,
                "session_key": getattr(ts, "sessionKey", None),
                "video_decision": ts.videoDecision,
                "audio_decision": ts.audioDecision,
                "subtitle_decision": getattr(ts, "subtitleDecision", None),
                "container": ts.container,
                "video_codec": ts.videoCodec,
                "audio_codec": ts.audioCodec,
                "width": ts.width,
                "height": ts.height,
                "speed": ts.speed,
                "progress": ts.progress,
                "throttled": ts.throttled,
                "complete": ts.complete,
                "duration_ms": getattr(ts, "duration", None),
                "remaining_ms": getattr(ts, "remaining", None),
                "context": getattr(ts, "context", None),
                "protocol": getattr(ts, "protocol", None),
            })
        return result

    return _text(await asyncio.to_thread(_get))


async def _terminate_session(plex, args: dict) -> list[TextContent]:
    session_key = args["session_key"]
    reason = args.get("reason", "")

    def _terminate():
        sessions = plex.sessions()
        session = next((s for s in sessions if str(s.sessionKey) == str(session_key)), None)
        if session is None:
            return f"Session {session_key} not found"
        session.stop(reason=reason)
        return f"Session {session_key} terminated"

    return _text(await asyncio.to_thread(_terminate))


async def _terminate_transcode(plex, args: dict) -> list[TextContent]:
    transcode_key = args["transcode_key"]

    def _terminate():
        sessions = plex.transcodeSessions()
        ts = next((s for s in sessions if s.key == transcode_key), None)
        if ts is None:
            return f"Transcode session {transcode_key} not found"
        ts.stop()
        return f"Transcode session {transcode_key} terminated"

    return _text(await asyncio.to_thread(_terminate))


async def _session_history(plex, args: dict) -> list[TextContent]:
    username_filter = args.get("username")
    limit = int(args.get("limit", 50))

    def _get():
        try:
            history = plex.history(maxresults=limit)
            result = []
            for h in history:
                user = getattr(h, "username", None) or getattr(h, "accountID", None)
                if username_filter and str(user) != str(username_filter):
                    continue
                result.append({
                    "title": h.title,
                    "type": h.type,
                    "grandparent_title": getattr(h, "grandparentTitle", None),
                    "parent_title": getattr(h, "parentTitle", None),
                    "user": user,
                    "viewed_at": str(h.viewedAt) if h.viewedAt else None,
                    "duration_ms": getattr(h, "duration", None),
                    "rating_key": h.ratingKey,
                })
            return result
        except Exception as exc:
            return {"error": str(exc)}

    return _text(await asyncio.to_thread(_get))
