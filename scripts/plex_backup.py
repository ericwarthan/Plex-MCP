#!/usr/bin/env python3
"""
plex_backup.py — Full Plex Media Server backup utility

Backs up:
  - Server preferences
  - Library configurations
  - Movie metadata (sort titles, watch status, user ratings)
  - TV show metadata + per-episode watch status
  - Custom/locked posters (downloaded as image files)
  - Collections and their members
  - Playlists

Usage:
    pip install plexapi requests
    python plex_backup.py

Output: ./plex_backup/ directory
"""

import os
import json
import time
import hashlib
import requests
from pathlib import Path
from plexapi.server import PlexServer

# ── Configuration ─────────────────────────────────────────────────────────────
PLEX_URL   = "http://YOUR_PLEX_IP:32400"   # e.g. http://192.168.1.100:32400
PLEX_TOKEN = "YOUR_PLEX_TOKEN_HERE"          # Plex Web → Settings → Account → Auth Token
BACKUP_DIR = Path("plex_backup")

# Preferences to skip (identity / read-only / machine-specific)
SKIP_PREFS = {
    "MachineIdentifier", "CertificateUUID", "CertificateVersion",
    "LocalAppDataPath", "ButlerDatabaseBackupPath", "AcceptedEULA",
    "PlexOnlineMail", "PublishServerOnPlexOnlineKey", "FriendlyName",
    "LastAutomaticMappedPort", "TranscoderTempDirectory",
    "ButlerTaskUpdateVersionSkipped",
}
# ──────────────────────────────────────────────────────────────────────────────


def get_guids(item):
    """Return a dict of {provider: id} and a canonical primary GUID string."""
    guids = {}
    for g in getattr(item, "guids", []):
        if "://" in g.id:
            provider, uid = g.id.split("://", 1)
            guids[provider] = uid
    primary = (
        f"imdb://{guids['imdb']}" if "imdb" in guids else
        f"tmdb://{guids['tmdb']}" if "tmdb" in guids else
        f"tvdb://{guids['tvdb']}" if "tvdb" in guids else
        item.guid
    )
    return guids, primary


def is_poster_locked(item):
    """Return True if the thumb/poster field is locked on this item."""
    try:
        for field in item.fields:
            if field.name == "thumb" and field.locked:
                return True
    except Exception:
        pass
    return False


def download_poster(item, poster_dir):
    """
    Download the currently-selected poster.
    Returns the relative path string, or None on failure.
    """
    if not getattr(item, "thumb", None):
        return None

    _, primary = get_guids(item)
    filename = hashlib.md5(primary.encode()).hexdigest() + ".jpg"
    dest = poster_dir / filename

    if dest.exists():
        return str(dest)

    url = f"{PLEX_URL}{item.thumb}?X-Plex-Token={PLEX_TOKEN}"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            dest.write_bytes(r.content)
            return str(dest)
        else:
            print(f"    ✗ HTTP {r.status_code} downloading poster for: {item.title}")
    except Exception as e:
        print(f"    ✗ Poster download error for {item.title}: {e}")
    return None


# ── Phase 1: Preferences ──────────────────────────────────────────────────────

def backup_preferences(plex, out_dir):
    data = {}
    for s in plex.settings.all():
        data[s.id] = {
            "value":   s.value,
            "default": s.default,
            "type":    s.type,
            "label":   s.label,
            "group":   s.group,
        }
    (out_dir / "preferences.json").write_text(json.dumps(data, indent=2, default=str))
    print(f"  ✓ {len(data)} preferences")


# ── Phase 2: Library configs ──────────────────────────────────────────────────

def backup_libraries(plex, out_dir):
    libs = []
    for lib in plex.library.sections():
        libs.append({
            "key":       lib.key,
            "title":     lib.title,
            "type":      lib.type,
            "agent":     lib.agent,
            "scanner":   lib.scanner,
            "language":  lib.language,
            "locations": lib.locations,
        })
    (out_dir / "libraries.json").write_text(json.dumps(libs, indent=2))
    print(f"  ✓ {len(libs)} libraries")


# ── Phase 3: Movies ───────────────────────────────────────────────────────────

def backup_movies(plex, out_dir):
    poster_dir = out_dir / "posters" / "movies"
    poster_dir.mkdir(parents=True, exist_ok=True)

    all_movies = []
    for lib in plex.library.sections():
        if lib.type != "movie":
            continue
        print(f"    → {lib.title}")
        for movie in lib.all():
            guids, primary = get_guids(movie)
            poster_path = download_poster(movie, poster_dir)
            locked = is_poster_locked(movie)

            all_movies.append({
                "guid":        primary,
                "all_guids":   [g.id for g in getattr(movie, "guids", [])],
                "title":       movie.title,
                "year":        movie.year,
                "sort_title":  movie.titleSort,
                "library":     lib.title,
                "poster_file": poster_path,
                "poster_locked": locked,
                "watched":     movie.isWatched,
                "view_count":  movie.viewCount,
                "user_rating": movie.userRating,
                "media_files": [
                    (p.file if p else None)
                    for m in movie.media for p in m.parts
                ],
            })

    (out_dir / "movies.json").write_text(json.dumps(all_movies, indent=2, default=str))
    print(f"  ✓ {len(all_movies)} movies")


# ── Phase 4: TV Shows ─────────────────────────────────────────────────────────

def backup_shows(plex, out_dir):
    poster_dir = out_dir / "posters" / "shows"
    poster_dir.mkdir(parents=True, exist_ok=True)

    all_shows = []
    for lib in plex.library.sections():
        if lib.type != "show":
            continue
        print(f"    → {lib.title}")
        for show in lib.all():
            guids, primary = get_guids(show)
            poster_path = download_poster(show, poster_dir)
            locked = is_poster_locked(show)

            episodes = []
            for season in show.seasons():
                for ep in season.episodes():
                    episodes.append({
                        "season":      season.seasonNumber,
                        "episode":     ep.index,
                        "watched":     ep.isWatched,
                        "view_count":  ep.viewCount,
                        "view_offset": ep.viewOffset,
                    })

            all_shows.append({
                "guid":          primary,
                "all_guids":     [g.id for g in getattr(show, "guids", [])],
                "title":         show.title,
                "year":          show.year,
                "sort_title":    show.titleSort,
                "library":       lib.title,
                "poster_file":   poster_path,
                "poster_locked": locked,
                "watched":       show.isWatched,
                "episodes":      episodes,
            })

    (out_dir / "shows.json").write_text(json.dumps(all_shows, indent=2, default=str))
    print(f"  ✓ {len(all_shows)} shows")


# ── Phase 5: Collections ──────────────────────────────────────────────────────

def backup_collections(plex, out_dir):
    all_collections = []
    for lib in plex.library.sections():
        if lib.type not in ("movie", "show"):
            continue
        try:
            for coll in lib.collections():
                members = []
                for item in coll.items():
                    _, primary = get_guids(item)
                    members.append({
                        "guid":  primary,
                        "title": item.title,
                        "year":  item.year,
                    })
                all_collections.append({
                    "title":   coll.title,
                    "library": lib.title,
                    "items":   members,
                })
        except Exception as e:
            print(f"    ✗ Could not read collections from {lib.title}: {e}")

    (out_dir / "collections.json").write_text(json.dumps(all_collections, indent=2))
    print(f"  ✓ {len(all_collections)} collections")


# ── Phase 6: Playlists ────────────────────────────────────────────────────────

def backup_playlists(plex, out_dir):
    all_playlists = []
    for pl in plex.playlists():
        items = []
        try:
            for item in pl.items():
                _, primary = get_guids(item)
                items.append({
                    "guid":  primary,
                    "title": item.title,
                    "type":  item.type,
                })
        except Exception:
            pass
        all_playlists.append({
            "title":       pl.title,
            "playlist_type": pl.playlistType,
            "items":       items,
        })

    (out_dir / "playlists.json").write_text(json.dumps(all_playlists, indent=2))
    print(f"  ✓ {len(all_playlists)} playlists")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"Connecting to {PLEX_URL} ...")
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)
    print(f"Connected: {plex.friendlyName}  (PMS {plex.version})\n")

    BACKUP_DIR.mkdir(exist_ok=True)

    (BACKUP_DIR / "meta.json").write_text(json.dumps({
        "server":     plex.friendlyName,
        "version":    plex.version,
        "machine_id": plex.machineIdentifier,
        "timestamp":  time.strftime("%Y-%m-%d %H:%M:%S"),
        "plex_url":   PLEX_URL,
    }, indent=2))

    print("[1/6] Preferences...")
    backup_preferences(plex, BACKUP_DIR)

    print("[2/6] Library configurations...")
    backup_libraries(plex, BACKUP_DIR)

    print("[3/6] Movies (metadata + posters)...")
    backup_movies(plex, BACKUP_DIR)

    print("[4/6] TV shows (metadata + posters + episode history)...")
    backup_shows(plex, BACKUP_DIR)

    print("[5/6] Collections...")
    backup_collections(plex, BACKUP_DIR)

    print("[6/6] Playlists...")
    backup_playlists(plex, BACKUP_DIR)

    print(f"\n✓ Backup complete → {BACKUP_DIR.resolve()}")
    print(f"  Poster images are in {(BACKUP_DIR / 'posters').resolve()}")


if __name__ == "__main__":
    main()
