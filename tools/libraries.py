import asyncio
import json
import logging

from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

TOOLS = [
    Tool(
        name="library_list",
        description="List all Plex libraries with type, item count, and last scan time",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="library_scan",
        description=(
            "Trigger a library scan. Optionally scan a specific sub-path within the library "
            "for partial scans. Omit path to scan the entire library."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string", "description": "Name of the library to scan"},
                "path": {"type": "string", "description": "Optional sub-path for partial scan"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="library_refresh_metadata",
        description="Refresh metadata for all items in a library from the metadata agents",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "force": {
                    "type": "boolean",
                    "description": "Force refresh even for items with locked metadata (default false)",
                    "default": False,
                },
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="library_cancel_scan",
        description="Cancel an in-progress library scan",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="library_get_genres",
        description="Get all genres present in a library",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="library_get_years",
        description="Get all release years present in a library",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="library_get_studios",
        description="Get all studios present in a library",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="library_get_directors",
        description="Get all directors present in a library",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="library_empty_trash",
        description="Empty the trash for a specific library, permanently removing deleted items",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
            },
            "required": ["library_name"],
        },
    ),
    # ── New tools ─────────────────────────────────────────────────────────────
    Tool(
        name="library_create",
        description=(
            "Create a new Plex library section. "
            "Agent and scanner strings must exactly match Plex's internal identifiers "
            "(e.g. tv.plex.agents.movie / Plex Movie for modern movie libraries)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name":      {"type": "string", "description": "Display name for the new library"},
                "type":      {"type": "string", "enum": ["movie", "show", "artist"], "description": "Library type"},
                "agent":     {"type": "string", "description": "Metadata agent identifier (e.g. tv.plex.agents.movie)"},
                "scanner":   {"type": "string", "description": "Scanner name (e.g. Plex Movie)"},
                "language":  {"type": "string", "default": "en-US", "description": "Language code (default en-US)"},
                "locations": {"type": "array", "items": {"type": "string"}, "description": "Folder paths on the Plex server"},
            },
            "required": ["name", "type", "agent", "scanner", "locations"],
        },
    ),
    Tool(
        name="library_delete",
        description="Permanently delete a Plex library section and all its metadata. Requires confirmed=true.",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "confirmed":    {"type": "boolean", "description": "Must be true to execute"},
            },
            "required": ["library_name", "confirmed"],
        },
    ),
    Tool(
        name="library_update",
        description=(
            "Update an existing library's name, agent, language, or folder locations. "
            "All fields are optional — only supplied fields are changed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "library_name":      {"type": "string"},
                "new_name":          {"type": "string", "description": "Rename the library"},
                "agent":             {"type": "string", "description": "New metadata agent"},
                "language":          {"type": "string", "description": "New language code"},
                "add_locations":     {"type": "array", "items": {"type": "string"}, "description": "Paths to add"},
                "remove_locations":  {"type": "array", "items": {"type": "string"}, "description": "Paths to remove"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="library_settings_get",
        description="Get the advanced settings for a library (thumbnail generation, intro detection, chapter images, etc.)",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
            },
            "required": ["library_name"],
        },
    ),
    Tool(
        name="library_settings_set",
        description="Update one or more advanced settings on a library. Setting IDs come from library_settings_get.",
        inputSchema={
            "type": "object",
            "properties": {
                "library_name": {"type": "string"},
                "settings": {
                    "type": "object",
                    "description": "Dict of setting_id → value pairs to apply",
                    "additionalProperties": True,
                },
            },
            "required": ["library_name", "settings"],
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
        if name == "library_list":
            return await _library_list(plex)
        if name == "library_scan":
            return await _library_scan(plex, args)
        if name == "library_refresh_metadata":
            return await _library_refresh_metadata(plex, args)
        if name == "library_cancel_scan":
            return await _library_cancel_scan(plex, args)
        if name == "library_get_genres":
            return await _library_get_filter(plex, args, "genre")
        if name == "library_get_years":
            return await _library_get_filter(plex, args, "year")
        if name == "library_get_studios":
            return await _library_get_filter(plex, args, "studio")
        if name == "library_get_directors":
            return await _library_get_filter(plex, args, "director")
        if name == "library_empty_trash":
            return await _library_empty_trash(plex, args)
        if name == "library_create":
            return await _library_create(plex, args)
        if name == "library_delete":
            return await _library_delete(plex, args)
        if name == "library_update":
            return await _library_update(plex, args)
        if name == "library_settings_get":
            return await _library_settings_get(plex, args)
        if name == "library_settings_set":
            return await _library_settings_set(plex, args)
    except Exception as exc:
        logger.exception("Error in libraries tool %s", name)
        return _text(f"Error: {exc}")
    return _text(f"Unknown tool: {name}")


# ── Original implementations ───────────────────────────────────────────────────

async def _library_list(plex) -> list[TextContent]:
    def _get():
        sections = plex.library.sections()
        return [
            {
                "name": s.title,
                "type": s.type,
                "key": s.key,
                "agent": s.agent,
                "language": s.language,
                "locations": s.locations,
                "total_size": s.totalSize,
                "refreshing": s.refreshing,
                "created_at": str(s.createdAt),
                "updated_at": str(s.updatedAt),
                "scanned_at": str(getattr(s, "scannedAt", "")),
            }
            for s in sections
        ]
    return _text(await asyncio.to_thread(_get))


async def _library_scan(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    library_name = args["library_name"]
    path = args.get("path")

    def _scan():
        section = plex.library.section(library_name)
        if path:
            section.update(path=path)
            return f"Scan started for '{library_name}' at path: {path}"
        else:
            section.update()
            return f"Full scan started for '{library_name}'"

    result = await asyncio.to_thread(_scan)
    log_change("library_scan", library_name, f"path={path or 'all'}")
    return _text(result)


async def _library_refresh_metadata(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    library_name = args["library_name"]
    force = args.get("force", False)

    def _refresh():
        section = plex.library.section(library_name)
        section.refresh()
        return f"Metadata refresh started for '{library_name}' (force={force})"

    result = await asyncio.to_thread(_refresh)
    log_change("library_refresh_metadata", library_name, f"force={force}")
    return _text(result)


async def _library_cancel_scan(plex, args: dict) -> list[TextContent]:
    library_name = args["library_name"]

    def _cancel():
        section = plex.library.section(library_name)
        section.cancelUpdate()
        return f"Scan cancelled for '{library_name}'"

    return _text(await asyncio.to_thread(_cancel))


async def _library_get_filter(plex, args: dict, field: str) -> list[TextContent]:
    library_name = args["library_name"]

    def _get():
        section = plex.library.section(library_name)
        choices = section.listChoices(field)
        return sorted([c.title for c in choices])

    return _text(await asyncio.to_thread(_get))


async def _library_empty_trash(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    library_name = args["library_name"]

    def _empty():
        section = plex.library.section(library_name)
        section.emptyTrash()
        return f"Trash emptied for library '{library_name}'"

    result = await asyncio.to_thread(_empty)
    log_change("library_empty_trash", library_name, "Emptied library trash")
    return _text(result)


# ── New implementations ────────────────────────────────────────────────────────

async def _library_create(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    name      = args["name"]
    lib_type  = args["type"]
    agent     = args["agent"]
    scanner   = args["scanner"]
    language  = args.get("language", "en-US")
    locations = args["locations"]

    def _create():
        # Library.add() validates paths via isBrowsable() then POSTs to
        # /library/sections with location[] repeated for multiple paths.
        plex.library.add(
            name=name,
            type=lib_type,
            agent=agent,
            scanner=scanner,
            language=language,
            location=locations,
        )
        section = plex.library.section(name)
        return {
            "key":       section.key,
            "title":     section.title,
            "type":      section.type,
            "agent":     section.agent,
            "scanner":   getattr(section, "scanner", ""),
            "language":  section.language,
            "locations": section.locations,
        }

    result = await asyncio.to_thread(_create)
    log_change("library_create", name, f"Created {lib_type} library with {len(locations)} location(s)")
    return _text(result)


async def _library_delete(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    if not args.get("confirmed"):
        return _text(
            "Library deletion is permanent and removes all metadata. Set confirmed=true to proceed."
        )

    library_name = args["library_name"]

    def _delete():
        section = plex.library.section(library_name)
        key = section.key
        section.delete()  # DELETE /library/sections/{key}
        return {"deleted": library_name, "key": key}

    result = await asyncio.to_thread(_delete)
    log_change("library_delete", library_name, "Library permanently deleted")
    return _text(result)


async def _library_update(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    library_name     = args["library_name"]
    new_name         = args.get("new_name")
    new_agent        = args.get("agent")
    new_language     = args.get("language")
    add_locations    = args.get("add_locations") or []
    remove_locations = args.get("remove_locations") or []

    def _update():
        section = plex.library.section(library_name)

        # Location helpers call edit() internally and POST the full location list.
        if remove_locations:
            section.removeLocations(remove_locations)
            section._reload()
        if add_locations:
            section.addLocations(add_locations)
            section._reload()

        # Name / agent / language go through PUT /library/sections/{key}?...
        edit_kwargs = {}
        if new_name:
            edit_kwargs["name"] = new_name
        if new_language:
            edit_kwargs["language"] = new_language

        if edit_kwargs or new_agent:
            section.edit(agent=new_agent or section.agent, **edit_kwargs)
            section._reload()

        return {
            "title":     section.title,
            "type":      section.type,
            "key":       section.key,
            "agent":     section.agent,
            "language":  section.language,
            "locations": section.locations,
        }

    changes = {k: v for k, v in {
        "new_name": new_name, "agent": new_agent, "language": new_language,
        "add_locations": add_locations or None,
        "remove_locations": remove_locations or None,
    }.items() if v}
    result = await asyncio.to_thread(_update)
    log_change("library_update", library_name, f"Updated: {list(changes.keys())}")
    return _text(result)


async def _library_settings_get(plex, args: dict) -> list[TextContent]:
    library_name = args["library_name"]

    def _get():
        section = plex.library.section(library_name)
        # GET /library/sections/{key}/prefs → list of Setting objects
        return {
            s.id: {
                "value":   s.value,
                "default": s.default,
                "type":    s.type,
                "label":   getattr(s, "label", s.id),
            }
            for s in section.settings()
        }

    return _text(await asyncio.to_thread(_get))


async def _library_settings_set(plex, args: dict) -> list[TextContent]:
    from changelog import log_change

    library_name = args["library_name"]
    settings     = args["settings"]

    def _set():
        section = plex.library.section(library_name)
        # editAdvanced() validates IDs against section.settings() then calls
        # edit(prefs[id]=value, ...) → PUT /library/sections/{key}
        section.editAdvanced(**settings)
        return {"library": library_name, "applied_settings": settings}

    result = await asyncio.to_thread(_set)
    log_change("library_settings_set", library_name, f"Applied settings: {list(settings.keys())}")
    return _text(result)
