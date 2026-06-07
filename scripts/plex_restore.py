#!/usr/bin/env python3
"""
plex_restore.py — Restore Plex Media Server configuration from backup

Restores (in order):
  1. Server preferences  (skips identity/machine-specific ones)
  2. Movie metadata      (sort titles, watch status, custom locked posters)
  3. TV show metadata    (sort titles, per-episode watch status, locked posters)
  4. Collections         (creates if missing, adds members by GUID)
  5. Playlists           (creates if missing)

Prerequisites on the NEW server before running:
  - PMS installed and signed in to your Plex account
  - All libraries created with the same names, pointing to the same \\zoe shares
  - Libraries fully scanned so all items are indexed
  - plex_backup/ directory present (output of plex_backup.py)

Usage:
    pip install plexapi requests
    python plex_restore.py
"""

import json
import re
import time
import requests
from pathlib import Path
from plexapi.server import PlexServer
from plexapi.exceptions import NotFound

# ── Configuration ─────────────────────────────────────────────────────────────
PLEX_URL   = "http://YOUR_PLEX_IP:32400"   # e.g. http://192.168.1.100:32400
PLEX_TOKEN = "REPLACE_WITH_NEW_SERVER_TOKEN" # Plex Web → Settings → Account → Auth Token
BACKUP_DIR = Path("plex_backup")             # directory created by plex_backup.py

# Preferences to never restore (identity / path / machine-specific)
SKIP_PREFS = {
    "MachineIdentifier", "CertificateUUID", "CertificateVersion",
    "LocalAppDataPath", "ButlerDatabaseBackupPath", "AcceptedEULA",
    "PlexOnlineMail", "PublishServerOnPlexOnlineKey", "FriendlyName",
    "LastAutomaticMappedPort", "TranscoderTempDirectory",
    "ButlerTaskUpdateVersionSkipped", "HardwareDevicePath",
    "PreferredNetworkInterface",
}
# ──────────────────────────────────────────────────────────────────────────────


LEGACY_MAP = {
    "thetvdb":    "tvdb",
    "themoviedb": "tmdb",
    "imdb":       "imdb",
}

def normalize_guids(guid_iterable, primary=None):
    """
    Return a set of all GUIDs including legacy-translated equivalents.
    Converts e.g. "com.plexapp.agents.thetvdb://70726?lang=en" → "tvdb://70726"
    """
    result = set(guid_iterable)
    if primary:
        result.add(primary)
    for g in list(result):
        m = re.match(r'com\.plexapp\.agents\.(\w+)://(\d+)', g)
        if m:
            provider = LEGACY_MAP.get(m.group(1))
            if provider:
                result.add(f"{provider}://{m.group(2)}")
    return result


# Global GUID index: built once per library, reused for all lookups
# Structure: { library_title: { guid_string: PlexItem } }
_GUID_INDEX = {}

def build_guid_index(plex):
    """Pre-index every item in every library by all its GUIDs. Call once at startup."""
    print("  Building GUID index (this may take a moment)...")
    for lib in plex.library.sections():
        if lib.type not in ("movie", "show", "artist"):
            continue
        index = {}
        try:
            for item in lib.all():
                all_g = normalize_guids(
                    [g.id for g in getattr(item, "guids", [])],
                    primary=item.guid
                )
                for g in all_g:
                    index[g] = item
        except Exception as e:
            print(f"    ✗ Could not index {lib.title}: {e}")
        _GUID_INDEX[lib.title] = index
        print(f"    ✓ {lib.title}: {len(index)} GUID entries ({lib.totalSize} items)")


def find_by_guid(plex, primary_guid, all_guids, library_name=None):
    """
    Fast O(1) GUID lookup using the pre-built index.
    Falls back to a full scan if the index isn't available.
    """
    guid_set = normalize_guids(all_guids, primary=primary_guid)

    if _GUID_INDEX:
        # Fast path: use the pre-built index
        if library_name and library_name in _GUID_INDEX:
            for g in guid_set:
                if g in _GUID_INDEX[library_name]:
                    return _GUID_INDEX[library_name][g]
        # Search all libraries
        for lib_index in _GUID_INDEX.values():
            for g in guid_set:
                if g in lib_index:
                    return lib_index[g]
        return None

    # Slow fallback (no index built)
    search_libs = plex.library.sections()
    if library_name:
        try:
            search_libs = [plex.library.section(library_name)]
        except Exception:
            pass
    for lib in search_libs:
        if lib.type not in ("movie", "show", "artist"):
            continue
        try:
            for item in lib.all():
                item_guids = normalize_guids(
                    [g.id for g in getattr(item, "guids", [])],
                    primary=item.guid
                )
                if item_guids & guid_set:
                    return item
        except Exception:
            pass
    return None


def coerce(value, type_str):
    """Coerce a JSON-decoded value to the correct Python type for plexapi."""
    if type_str == "bool":
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("true", "1", "yes")
    if type_str == "int":
        return int(value)
    if type_str == "double":
        return float(value)
    return value  # text / enum


# ── Phase 1: Preferences ──────────────────────────────────────────────────────

def restore_preferences(plex, backup_dir):
    prefs_data = json.loads((backup_dir / "preferences.json").read_text())
    restored = skipped = errors = 0

    for pref_id, data in prefs_data.items():
        if pref_id in SKIP_PREFS:
            skipped += 1
            continue
        # Skip if value matches the backed-up default (no point setting it)
        if data["value"] == data.get("default"):
            skipped += 1
            continue
        try:
            setting = plex.settings.get(pref_id)
            if setting is None:
                skipped += 1
                continue
            new_val = coerce(data["value"], data.get("type", "text"))
            if setting.value != new_val:
                setting.set(new_val)
                restored += 1
        except Exception as e:
            errors += 1

    try:
        plex.settings.save()
    except Exception:
        pass

    print(f"  ✓ {restored} preferences restored  ({skipped} skipped, {errors} errors)")


# ── Phase 2: Movies ───────────────────────────────────────────────────────────

def restore_movies(plex, backup_dir):
    movies_data = json.loads((backup_dir / "movies.json").read_text())
    restored = not_found = poster_errors = 0

    for md in movies_data:
        item = find_by_guid(plex, md["guid"], md.get("all_guids", []), md.get("library"))

        if item is None:
            print(f"    ✗ Not found: {md['title']} ({md.get('year')})")
            not_found += 1
            continue

        # Restore sort title if it differs from the display title
        sort = md.get("sort_title", "")
        if sort and sort != md.get("title", ""):
            try:
                item.edit(**{"titleSort.value": sort, "titleSort.locked": 1})
            except Exception:
                pass

        # Upload + lock poster if it was locked in the backup
        if md.get("poster_locked") and md.get("poster_file"):
            poster_path = Path(md["poster_file"])
            if poster_path.exists():
                try:
                    item.uploadPoster(filepath=str(poster_path))
                    item.lockPoster()
                except Exception as e:
                    print(f"    ✗ Poster error for {md['title']}: {e}")
                    poster_errors += 1

        # Restore watched status
        if md.get("watched") and not item.isWatched:
            try:
                item.markWatched()
            except Exception:
                pass

        # Restore user rating
        if md.get("user_rating") is not None:
            try:
                item.rate(md["user_rating"])
            except Exception:
                pass

        restored += 1

    print(f"  ✓ {restored} movies restored  ({not_found} not found, {poster_errors} poster errors)")


# ── Phase 3: TV Shows ─────────────────────────────────────────────────────────

def restore_shows(plex, backup_dir):
    shows_data = json.loads((backup_dir / "shows.json").read_text())
    restored = not_found = poster_errors = 0

    for sd in shows_data:
        item = find_by_guid(plex, sd["guid"], sd.get("all_guids", []), sd.get("library"))

        if item is None:
            print(f"    ✗ Not found: {sd['title']} ({sd.get('year')})")
            not_found += 1
            continue

        # Sort title
        sort = sd.get("sort_title", "")
        if sort and sort != sd.get("title", ""):
            try:
                item.edit(**{"titleSort.value": sort, "titleSort.locked": 1})
            except Exception:
                pass

        # Poster
        if sd.get("poster_locked") and sd.get("poster_file"):
            poster_path = Path(sd["poster_file"])
            if poster_path.exists():
                try:
                    item.uploadPoster(filepath=str(poster_path))
                    item.lockPoster()
                except Exception as e:
                    print(f"    ✗ Poster error for {sd['title']}: {e}")
                    poster_errors += 1

        # Per-episode watch status
        watched_set = {
            (e["season"], e["episode"])
            for e in sd.get("episodes", [])
            if e.get("watched")
        }
        if watched_set:
            try:
                for season in item.seasons():
                    for ep in season.episodes():
                        if (season.seasonNumber, ep.index) in watched_set:
                            if not ep.isWatched:
                                ep.markWatched()
            except Exception:
                pass

        restored += 1

    print(f"  ✓ {restored} shows restored  ({not_found} not found, {poster_errors} poster errors)")


# ── Phase 4: Collections ──────────────────────────────────────────────────────

def restore_collections(plex, backup_dir):
    coll_data = json.loads((backup_dir / "collections.json").read_text())
    restored = skipped = 0

    for cd in coll_data:
        try:
            lib = plex.library.section(cd["library"])
        except Exception:
            print(f"    ✗ Library not found: {cd['library']}")
            skipped += 1
            continue

        # Resolve member items
        members = []
        for item_data in cd.get("items", []):
            item = find_by_guid(
                plex, item_data["guid"],
                [item_data["guid"]], cd["library"]
            )
            if item:
                members.append(item)

        if not members:
            print(f"    ✗ No members resolved for collection: {cd['title']}")
            skipped += 1
            continue

        try:
            coll = lib.collection(cd["title"])
            # Add any items not already in it
            existing_keys = {i.ratingKey for i in coll.items()}
            new_items = [i for i in members if i.ratingKey not in existing_keys]
            if new_items:
                coll.addItems(new_items)
        except NotFound:
            lib.createCollection(cd["title"], items=members)

        restored += 1

    print(f"  ✓ {restored} collections restored  ({skipped} skipped)")


# ── Phase 5: Playlists ────────────────────────────────────────────────────────

def restore_playlists(plex, backup_dir):
    pl_data = json.loads((backup_dir / "playlists.json").read_text())
    restored = skipped = 0

    for pd in pl_data:
        members = []
        for item_data in pd.get("items", []):
            item = find_by_guid(plex, item_data["guid"], [item_data["guid"]])
            if item:
                members.append(item)

        if not members:
            skipped += 1
            continue

        # Check if playlist already exists
        existing = {pl.title: pl for pl in plex.playlists()}
        if pd["title"] in existing:
            skipped += 1
            continue

        try:
            plex.createPlaylist(pd["title"], items=members)
            restored += 1
        except Exception as e:
            print(f"    ✗ Playlist error for '{pd['title']}': {e}")
            skipped += 1

    print(f"  ✓ {restored} playlists restored  ({skipped} skipped/already exist)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not BACKUP_DIR.exists():
        print(f"ERROR: Backup directory '{BACKUP_DIR}' not found.")
        print("       Run plex_backup.py first, or copy the backup folder here.")
        return

    if PLEX_TOKEN == "REPLACE_WITH_NEW_SERVER_TOKEN":
        print("ERROR: Update PLEX_TOKEN at the top of this script with the new server's token.")
        print("       Find it in Plex Web → Settings → Account → Authentication Token")
        return

    meta = json.loads((BACKUP_DIR / "meta.json").read_text())
    print(f"Backup source : {meta['server']}  (PMS {meta['version']})")
    print(f"Backup taken  : {meta['timestamp']}\n")

    print(f"Connecting to {PLEX_URL} ...")
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)
    print(f"Connected     : {plex.friendlyName}  (PMS {plex.version})\n")

    print("IMPORTANT: All libraries must be created and fully scanned before continuing.")
    print("           Items not yet indexed will be silently skipped.\n")
    input("Press Enter to begin restore, Ctrl+C to abort...\n")

    print("[0/5] Building GUID index...")
    build_guid_index(plex)

    print("[1/5] Restoring server preferences...")
    restore_preferences(plex, BACKUP_DIR)

    print("[2/5] Restoring movie metadata + posters...")
    restore_movies(plex, BACKUP_DIR)

    print("[3/5] Restoring TV show metadata + posters + watch history...")
    restore_shows(plex, BACKUP_DIR)

    print("[4/5] Restoring collections...")
    restore_collections(plex, BACKUP_DIR)

    print("[5/5] Restoring playlists...")
    restore_playlists(plex, BACKUP_DIR)

    print("\n✓ Restore complete.")
    print("  Recommended next steps:")
    print("  1. Verify a few items in Plex Web to confirm metadata looks correct")
    print("  2. Confirm any custom collections were restored")
    print("  3. Confirm poster locks are in place (Settings won't override them)")
    print("  4. Run a library scan to pick up any new content added since backup")


if __name__ == "__main__":
    main()
