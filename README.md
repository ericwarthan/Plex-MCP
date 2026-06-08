# Plex MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io) server that gives Claude full management access to a Plex Media Server — browsing libraries, fixing metadata, syncing between servers, managing collections, and more.

Works with **Claude Desktop** (Windows/macOS) and **Claude Code** via an SSH connection to the Ubuntu host running this server.

---

## Prerequisites

- **Python 3.11+** on the host machine
- **Plex Media Server** accessible on your LAN
- A **Plex authentication token** (see [Finding your token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/))
- **Claude Desktop** or **Claude Code**

---

## Installation

```bash
git clone https://github.com/ericwarthan/Plex-MCP
cd Plex-MCP
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

---

## Configuration

Copy the example config and fill in your details:

```bash
cp config/config.example.json ~/.config/plex-mcp/config.json
```

Edit `~/.config/plex-mcp/config.json`:

```json
{
  "plex_name": "My Plex Server",
  "plex_host": "192.168.1.x",
  "plex_port": 32400,
  "token": "YOUR_PLEX_TOKEN_HERE",
  "plex_url": "http://192.168.1.x:32400"
}
```

The config file is stored in your home directory (not the repo) so credentials are never accidentally committed.

---

## Connecting to Claude Desktop (Windows)

Claude Desktop connects to the MCP server over SSH. Add this to your
`%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "plex": {
      "command": "C:\\Program Files\\Git\\usr\\bin\\ssh.exe",
      "args": [
        "username@YOUR_SERVER_IP",
        "cd /home/username/Plex-MCP && source venv/bin/activate && python3 server.py --stdio"
      ]
    }
  }
}
```

**Important — use Git's `ssh.exe`, not Windows OpenSSH.**
Claude Desktop launches `ssh.exe` as a subprocess and reads its stdout as the MCP stream. Windows' built-in OpenSSH (`C:\Windows\System32\OpenSSH\ssh.exe`) sometimes uses a different key format or agent that fails silently. The SSH binary bundled with [Git for Windows](https://git-scm.com/download/win) (`C:\Program Files\Git\usr\bin\ssh.exe`) is more reliable for this use case.

Your SSH public key must be in `~/.ssh/authorized_keys` on the server host.

---

## Connecting to Claude Code

Claude Code can use the MCP server directly (no SSH wrapper needed if running on the same machine) or via SSH. In your project's `.claude/settings.json`:

```json
{
  "mcpServers": {
    "plex": {
      "command": "python3",
      "args": ["/home/username/Plex-MCP/server.py", "--stdio"]
    }
  }
}
```

Or via SSH from a remote machine (same pattern as Claude Desktop above).

---

## Tool Reference

The server exposes **125+ tools** across 15 categories. Destructive operations (delete, bulk-mark) require `confirmed=true`.

### Libraries
| Tool | Description |
|---|---|
| `library_list` | List all libraries with type, item count, and last scan time |
| `library_scan` | Trigger a full or partial path scan |
| `library_refresh_metadata` | Refresh metadata from agents for all items |
| `library_cancel_scan` | Cancel an in-progress scan |
| `library_get_genres` | List all genres present in a library |
| `library_get_years` | List all release years present |
| `library_get_studios` | List all studios present |
| `library_get_directors` | List all directors present |
| `library_empty_trash` | Permanently remove deleted items from trash |
| `library_create` | Create a new library section |
| `library_delete` | Permanently delete a library *(confirmed=true)* |
| `library_update` | Rename, change agent/language, or add/remove folder locations |
| `library_settings_get` | Read advanced settings (thumbnail gen, intro detection, etc.) |
| `library_settings_set` | Update advanced library settings |

### Movies
| Tool | Description |
|---|---|
| `movie_list` | List movies with filtering by genre, year, resolution, watched status |
| `movie_recently_added` | Movies added most recently |
| `movie_recently_viewed` | Recently played movies |
| `movie_on_deck` | In-progress / resume-watching movies |
| `movie_get` | Full details including cast, GUIDs, media info |
| `movie_search` | Search by title |
| `movie_find_candidates` | Find correct metadata match candidates |
| `movie_apply_match` | Apply a metadata match by GUID |
| `movie_update_metadata` | Edit title, sort title, year, summary, studio, rating, etc. |
| `movie_delete` | Delete a movie *(confirmed=true)* |
| `movie_missing_posters` | Find all movies without poster artwork |
| `movie_optimize` | Queue a pre-transcoded optimized version for a device target |
| `movie_merge` | Merge two separate items into one multi-version item |
| `movie_split_media` | Split a multi-version item back into separate items |
| `movie_list_merged` | List all items with more than one media file attached |
| `movie_list_unmatched` | List items with no external metadata agent match |

### TV Shows
| Tool | Description |
|---|---|
| `show_list` | List shows with metadata summary |
| `show_get` | Full details including season/episode counts, cast |
| `show_seasons` | List seasons with episode counts and watch status |
| `show_episodes` | List episodes for a season |
| `show_recently_added` | Recently added episodes |
| `show_on_deck` | Next episodes to watch |
| `show_find_candidates` | Find correct metadata match candidates for a show |
| `show_apply_match` | Apply a metadata match by GUID |
| `show_update_metadata` | Edit metadata on a show, season, or episode |
| `show_delete` | Delete a show, season, or episode *(confirmed=true)* |

### Artwork
| Tool | Description |
|---|---|
| `artwork_get_posters` | List all poster options (online + local) with selection state |
| `artwork_get_available` | Same as above but also shows provider info for browsing |
| `artwork_set_poster_url` | Set poster by downloading from a URL |
| `artwork_set_poster_plex` | Select a poster from available options by index |
| `artwork_upload_poster` | Upload a poster from a local file path on the server |
| `artwork_lock_poster` | Lock poster so metadata refreshes cannot override it |
| `artwork_get_backgrounds` | List available background/art images |
| `artwork_set_background_url` | Set background art from a URL |
| `artwork_set_background_plex` | Select a background by index |
| `artwork_get_banners` | List available banner images (TV shows) |
| `artwork_set_banner_url` | Set a banner from a URL |
| `artwork_get_themes` | List available theme music (TV shows) |

### Collections
| Tool | Description |
|---|---|
| `collection_list` | List all collections in a library |
| `collection_get` | Get collection details and item list |
| `collection_create` | Create a new collection |
| `collection_delete` | Delete a collection *(confirmed=true)* |
| `collection_add_items` | Add items to an existing collection *(confirmed=true for 10+)* |
| `collection_remove_items` | Remove items from a collection *(confirmed=true for 10+)* |
| `collection_set_poster` | Set a collection poster from a URL |
| `collection_set_sort_order` | Set sort order: release, alpha, or custom |

### Playlists
| Tool | Description |
|---|---|
| `playlist_list` | List all playlists |
| `playlist_get` | Get playlist details and items |
| `playlist_create` | Create a playlist from titles or rating keys |
| `playlist_delete` | Delete a playlist *(confirmed=true)* |
| `playlist_add_items` | Add items to a playlist |
| `playlist_remove_items` | Remove items from a playlist |

### Sessions & Playback
| Tool | Description |
|---|---|
| `session_list` | List active playback sessions |
| `session_transcode_list` | List active transcoding sessions |
| `session_terminate` | Stop a playback session |
| `session_terminate_transcode` | Stop a transcode job |
| `session_history` | Recent play history |
| `playback_clients` | List available Plex clients |
| `playback_play` | Resume playback on a client |
| `playback_pause` | Pause playback |
| `playback_stop` | Stop playback |
| `playback_seek` | Seek to a position |
| `playback_start_media` | Start playing a specific item on a client |
| `playback_skip_next` | Skip to next item |
| `playback_skip_prev` | Skip to previous item |
| `playback_set_volume` | Set volume on a client |

### Watch State
| Tool | Description |
|---|---|
| `watch_mark_watched` | Mark an item as watched *(confirmed=true for 10+ episodes)* |
| `watch_mark_unwatched` | Mark an item as unwatched *(confirmed=true for 10+)* |
| `watch_set_rating` | Set a star rating (0–10) |
| `watch_get_status` | Get watch status, view count, and ratings |
| `watch_bulk_mark_watched` | Mark entire library or collection as watched *(confirmed=true)* |
| `watch_bulk_mark_unwatched` | Mark entire library or collection as unwatched *(confirmed=true)* |

### Users & Sharing
| Tool | Description |
|---|---|
| `user_list` | List all managed users and home users |
| `user_get` | Get details for a specific user |
| `user_watch_history` | Get a user's watch history |
| `user_statistics` | Playback statistics for a user |
| `user_share_library` | Share a library with a Plex user |
| `user_unshare_library` | Remove a user's access to a library |

### Discovery
| Tool | Description |
|---|---|
| `discovery_hubs` | Get the home screen hubs (On Deck, Recently Added, etc.) |
| `discovery_on_deck` | On Deck items across all libraries |
| `discovery_recently_added` | Recently added content across all libraries |
| `discovery_continue_watching` | Items with a resume position |
| `discovery_search` | Full-text search across all libraries |

### Music
| Tool | Description |
|---|---|
| `music_list_artists` | List artists in a music library |
| `music_list_albums` | List albums for an artist |
| `music_list_tracks` | List tracks for an album |
| `music_get_artist` | Full artist details |
| `music_get_album` | Full album details including tracks |
| `music_search` | Search within a music library |
| `music_update_metadata` | Edit artist or album metadata |
| `music_fix_match` | Find correct metadata match for an artist or album |
| `music_apply_match` | Apply a metadata match by GUID |

### Server Admin
| Tool | Description |
|---|---|
| `server_identity` | Server name, version, machine ID |
| `server_capabilities` | Feature flags and enabled capabilities |
| `server_preferences` | Read all server preferences |
| `server_set_preference` | Update a server preference |
| `server_check_updates` | Check for available Plex updates |
| `server_apply_update` | Apply a pending update |
| `server_activity_log` | Recent server activity |
| `server_transient_token` | Generate a short-lived access token |
| `server_statistics` | Bandwidth and media statistics |

### Maintenance
| Tool | Description |
|---|---|
| `maintenance_empty_all_trash` | Empty trash on all libraries *(confirmed=true)* |
| `maintenance_optimize_database` | Run database VACUUM and ANALYZE |
| `maintenance_clean_bundles` | Remove orphaned metadata bundle files |
| `maintenance_empty_codecs` | Clear the codec cache *(confirmed=true)* |
| `maintenance_download_logs` | Download diagnostics log archive to disk |
| `maintenance_check_orphaned` | Find items whose files no longer exist on disk |
| `maintenance_library_info` | Storage and metadata statistics for a library |
| `maintenance_server_logs_tail` | Recent log lines filtered by level and component |
| `maintenance_library_health` | Combined unmatched / merged / orphaned check |

### Sync
| Tool | Description |
|---|---|
| `plex_sync` | Copy sort titles, posters, watch state, and collections from a source Plex server to the connected one. Matches items by GUID across both legacy and modern agent formats. Supports `dry_run=true` to preview changes. |

---

## Known Quirks

**Git `ssh.exe` vs Windows OpenSSH**
Claude Desktop on Windows must use the SSH binary from Git for Windows, not the built-in Windows OpenSSH. Point `command` to `C:\Program Files\Git\usr\bin\ssh.exe`. The built-in version at `C:\Windows\System32\OpenSSH\ssh.exe` often fails silently when Claude Desktop reads the MCP stream from its stdout.

**`confirmed=true` on destructive tools**
Any tool that deletes items, empties trash, or bulk-modifies many records requires the `confirmed` parameter set to `true`. This prevents accidental bulk operations when Claude is exploring or describing what it would do. Always ask Claude to preview first, then confirm.

**Poster lock behavior**
When you upload a custom poster or select a specific one via the artwork tools, the server locks the `thumb` field so scheduled metadata refreshes cannot overwrite it. To allow Plex to choose the poster again, use `movie_update_metadata` or the Plex web UI to unlock the field.

**`plex_sync` dry run**
Always run `plex_sync` with `dry_run=true` first. The summary shows every item that would be changed and every GUID that didn't match. Unmatched items usually indicate the source has legacy agent GUIDs that need the mapping table extended — open an issue with the unmatched GUID strings.

---

## License

MIT
