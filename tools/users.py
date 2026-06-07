import asyncio
import json
import logging

from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

TOOLS = [
    Tool(
        name="user_list",
        description="List all users and home accounts associated with the Plex account",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="user_get",
        description="Get detailed info for a specific user including their server access and permissions",
        inputSchema={
            "type": "object",
            "properties": {
                "username": {"type": "string", "description": "Username or email"},
            },
            "required": ["username"],
        },
    ),
    Tool(
        name="user_watch_history",
        description="Get watch history for a specific user across all libraries",
        inputSchema={
            "type": "object",
            "properties": {
                "username": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
                "library_name": {"type": "string", "description": "Optional: filter to a specific library"},
            },
            "required": ["username"],
        },
    ),
    Tool(
        name="user_statistics",
        description="Get watch statistics for all users (total plays, duration, activity)",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string", "description": "Optional: filter to a specific library"},
            },
        },
    ),
    Tool(
        name="user_share_library",
        description="Share one or more libraries with a user",
        inputSchema={
            "type": "object",
            "properties": {
                "username": {"type": "string", "description": "Username or email to share with"},
                "library_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Library names to share",
                },
                "allow_sync": {"type": "boolean", "default": False},
                "allow_camera_upload": {"type": "boolean", "default": False},
            },
            "required": ["username", "library_names"],
        },
    ),
    Tool(
        name="user_unshare_library",
        description="Stop sharing libraries with a user",
        inputSchema={
            "type": "object",
            "properties": {
                "username": {"type": "string"},
                "library_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Library names to unshare, or omit to unshare all",
                },
            },
            "required": ["username"],
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
        if name == "user_list":
            return await _user_list(plex)
        if name == "user_get":
            return await _user_get(plex, args)
        if name == "user_watch_history":
            return await _user_watch_history(plex, args)
        if name == "user_statistics":
            return await _user_statistics(plex, args)
        if name == "user_share_library":
            return await _user_share_library(plex, args)
        if name == "user_unshare_library":
            return await _user_unshare_library(plex, args)
    except Exception as exc:
        logger.exception("Error in users tool %s", name)
        return _text(f"Error: {exc}")
    return _text(f"Unknown tool: {name}")


async def _user_list(plex) -> list[TextContent]:
    def _get():
        try:
            account = plex.myPlexAccount()
            users = account.users()
            result = {
                "owner": {
                    "username": account.username,
                    "email": account.email,
                    "subscription": getattr(account, "subscriptionActive", None),
                },
                "users": [],
            }
            for u in users:
                result["users"].append({
                    "username": u.username,
                    "email": u.email,
                    "title": u.title,
                    "restricted": u.restricted,
                    "allow_sync": getattr(u, "allowSync", None),
                    "home": getattr(u, "home", None),
                    "thumb": u.thumb,
                })
            return result
        except Exception as exc:
            return {"error": str(exc)}

    return _text(await asyncio.to_thread(_get))


async def _user_get(plex, args: dict) -> list[TextContent]:
    username = args["username"]

    def _get():
        account = plex.myPlexAccount()
        user = account.user(username)
        servers = user.servers if hasattr(user, "servers") else []
        return {
            "username": user.username,
            "email": user.email,
            "title": user.title,
            "restricted": user.restricted,
            "allow_sync": getattr(user, "allowSync", None),
            "home": getattr(user, "home", None),
            "servers": [
                {
                    "name": s.name,
                    "owned": s.owned,
                    "sections": [sec.title for sec in getattr(s, "sections", [])],
                }
                for s in servers
            ],
        }

    return _text(await asyncio.to_thread(_get))


async def _user_watch_history(plex, args: dict) -> list[TextContent]:
    username = args["username"]
    limit = int(args.get("limit", 50))
    library_name = args.get("library_name")

    def _get():
        try:
            history = plex.history(maxresults=limit, accountID=None)
            result = []
            for h in history:
                h_user = getattr(h, "username", None) or str(getattr(h, "accountID", ""))
                if h_user.lower() != username.lower():
                    continue
                lib_title = getattr(h, "librarySectionTitle", None)
                if library_name and lib_title != library_name:
                    continue
                result.append({
                    "title": h.title,
                    "type": h.type,
                    "show": getattr(h, "grandparentTitle", None),
                    "season": getattr(h, "parentTitle", None),
                    "viewed_at": str(h.viewedAt) if h.viewedAt else None,
                    "library": lib_title,
                    "rating_key": h.ratingKey,
                })
            return result
        except Exception as exc:
            return {"error": str(exc)}

    return _text(await asyncio.to_thread(_get))


async def _user_statistics(plex, args: dict) -> list[TextContent]:
    library_name = args.get("library_name")

    def _get():
        try:
            stats = plex.statistics()
            by_user: dict = {}
            for s in getattr(stats, "media", []):
                account_id = str(getattr(s, "accountID", "unknown"))
                if account_id not in by_user:
                    by_user[account_id] = {"plays": 0, "duration_ms": 0}
                by_user[account_id]["plays"] += getattr(s, "plays", 0) or 0
                by_user[account_id]["duration_ms"] += getattr(s, "duration", 0) or 0
            return by_user
        except Exception as exc:
            return {"error": str(exc)}

    return _text(await asyncio.to_thread(_get))


async def _user_share_library(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    username = args["username"]
    library_names = args["library_names"]
    allow_sync = args.get("allow_sync", False)

    def _share():
        account = plex.myPlexAccount()
        sections = [plex.library.section(name) for name in library_names]
        account.inviteFriend(
            username,
            plex,
            sections,
            allowSync=allow_sync,
            allowCameraUpload=args.get("allow_camera_upload", False),
        )
        return f"Shared {library_names} with '{username}'"

    result = await asyncio.to_thread(_share)
    log_change("user_share_library", username, f"shared: {library_names}")
    return _text(result)


async def _user_unshare_library(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    username = args["username"]
    library_names = args.get("library_names", [])

    def _unshare():
        account = plex.myPlexAccount()
        user = account.user(username)
        if library_names:
            sections = [plex.library.section(name) for name in library_names]
            account.updateFriend(username, plex, sections, removeSections=True)
            return f"Unshared {library_names} from '{username}'"
        else:
            account.removeFriend(username)
            return f"Removed all access for '{username}'"

    result = await asyncio.to_thread(_unshare)
    log_change("user_unshare_library", username, f"unshared: {library_names or 'all'}")
    return _text(result)
