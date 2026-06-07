#!/usr/bin/env python3
"""
plex_db_migrate.py — Migrate a Plex Media Server database between platforms

Useful when moving PMS from one OS to another (e.g. Windows → Linux) where
file paths in the database need to be rewritten to match the new mount points.

This is more reliable than a metadata sync because it preserves every correct
match, split, sort title, watch history, poster lock, and collection that the
source server has accumulated.

Steps:
  1. Copy both Plex database files from the source location
  2. Translate all source path prefixes to destination path prefixes
  3. Stop Plex on the destination server
  4. Back up the destination's existing databases
  5. Deploy the translated databases
  6. Fix ownership and clean WAL files
  7. Start Plex on the destination server

Usage:
    python plex_db_migrate.py --help

    # Example: Windows → Linux migration
    python plex_db_migrate.py \\
        --source-dir "C:/Users/YourUser/AppData/Local/Plex Media Server/Plug-in Support/Databases" \\
        --dest-host 192.168.1.100 \\
        --dest-user plex \\
        --proxy-host 192.168.1.x \\
        --proxy-user username \\
        --path-map "\\\\nas\\Movies=/mnt/nas/Movies" \\
        --path-map "\\\\nas\\TVShows=/mnt/nas/TVShows"

    (no extra packages needed — uses only stdlib)
"""

import argparse
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

SSH_EXE = r"C:\Windows\System32\OpenSSH\ssh.exe"
SCP_EXE = r"C:\Windows\System32\OpenSSH\scp.exe"

DEST_PLEX_DB_DIR = (
    "/var/lib/plexmediaserver/Library/Application Support"
    "/Plex Media Server/Plug-in Support/Databases"
)

DB_FILES = [
    "com.plexapp.plugins.library.db",
    "com.plexapp.plugins.library.blobs.db",
]


def translate_path(path: str, path_map: list[tuple[str, str]]) -> str:
    """Translate a source path prefix to a destination path prefix."""
    if not path:
        return path
    result = path
    for src_prefix, dst_prefix in path_map:
        if result.lower().startswith(src_prefix.lower()):
            result = dst_prefix + result[len(src_prefix):]
            break
    result = result.replace("\\", "/")
    return result


def translate_database(source: Path, dest: Path, path_map: list[tuple[str, str]]) -> dict:
    """Copy and translate all file paths in the database. Returns stats."""
    print(f"  Copying: {source.name}")
    shutil.copy2(source, dest)

    for ext in ("-wal", "-shm"):
        extra = source.parent / (source.name + ext)
        if extra.exists():
            shutil.copy2(extra, dest.parent / (dest.name + ext))
            print(f"    + copied {ext}")

    conn = sqlite3.connect(str(dest))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        pass

    stats = {"media_parts": 0, "section_locations": 0, "untranslated": []}

    rows = conn.execute(
        "SELECT id, file FROM media_parts WHERE file IS NOT NULL"
    ).fetchall()
    for row_id, fp in rows:
        new_fp = translate_path(fp, path_map)
        if new_fp != fp:
            conn.execute("UPDATE media_parts SET file = ? WHERE id = ?", (new_fp, row_id))
            stats["media_parts"] += 1
        elif fp and not fp.startswith("/"):
            stats["untranslated"].append(fp)

    rows = conn.execute(
        "SELECT id, root_path FROM section_locations WHERE root_path IS NOT NULL"
    ).fetchall()
    for row_id, rp in rows:
        new_rp = translate_path(rp, path_map)
        if new_rp != rp:
            conn.execute(
                "UPDATE section_locations SET root_path = ? WHERE id = ?", (new_rp, row_id)
            )
            stats["section_locations"] += 1
            print(f"    section: {rp}")
            print(f"          → {new_rp}")

    conn.commit()
    conn.close()

    for ext in ("-wal", "-shm"):
        extra = dest.parent / (dest.name + ext)
        if extra.exists():
            extra.unlink()

    return stats


def ssh_run(command: str, dest_host: str, dest_user: str,
            proxy_host: str = None, proxy_user: str = None) -> tuple[int, str]:
    """Run a command on the destination host, optionally via a proxy."""
    if proxy_host and proxy_user:
        cmd = [
            SSH_EXE, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
            f"{proxy_user}@{proxy_host}",
            f"ssh -o StrictHostKeyChecking=no {dest_user}@{dest_host} {repr(command)}",
        ]
    else:
        cmd = [
            SSH_EXE, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
            f"{dest_user}@{dest_host}", command,
        ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, (result.stdout + result.stderr).strip()


def scp_to_dest(local: Path, remote: str, dest_host: str, dest_user: str,
                proxy_host: str = None, proxy_user: str = None):
    """Transfer a file to the destination, optionally via a proxy."""
    if proxy_host and proxy_user:
        vm_tmp = f"/tmp/{local.name}"
        subprocess.run(
            [SCP_EXE, "-o", "BatchMode=yes", str(local),
             f"{proxy_user}@{proxy_host}:{vm_tmp}"],
            check=True, capture_output=True,
        )
        result = subprocess.run(
            [SSH_EXE, "-o", "BatchMode=yes", f"{proxy_user}@{proxy_host}",
             f"scp -o StrictHostKeyChecking=no {vm_tmp} {dest_user}@{dest_host}:{repr(remote)}"],
            capture_output=True, text=True,
        )
        subprocess.run(
            [SSH_EXE, "-o", "BatchMode=yes", f"{proxy_user}@{proxy_host}",
             f"rm -f {vm_tmp}"], capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"SCP to destination failed: {result.stdout + result.stderr}")
    else:
        subprocess.run(
            [SCP_EXE, "-o", "BatchMode=yes", str(local),
             f"{dest_user}@{dest_host}:{remote}"],
            check=True,
        )


def main():
    parser = argparse.ArgumentParser(
        description="Migrate a Plex database between platforms, rewriting file paths."
    )
    parser.add_argument(
        "--source-dir", required=True,
        help="Path to the source Plex 'Databases' directory"
    )
    parser.add_argument(
        "--dest-host", required=True,
        help="IP or hostname of the destination Plex server"
    )
    parser.add_argument(
        "--dest-user", default="plex",
        help="SSH user on the destination server (default: plex)"
    )
    parser.add_argument(
        "--proxy-host", default=None,
        help="Optional SSH proxy host (if destination is not directly reachable)"
    )
    parser.add_argument(
        "--proxy-user", default=None,
        help="SSH user on the proxy host"
    )
    parser.add_argument(
        "--path-map", action="append", default=[], metavar="SRC=DST",
        help=(
            "Path prefix mapping SRC=DST (repeat for multiple). "
            "Example: '\\\\\\\\nas\\\\Movies=/mnt/nas/Movies'. "
            "Comparisons are case-insensitive; backslashes are normalised."
        )
    )
    args = parser.parse_args()

    source_dir = Path(args.source_dir)
    if not source_dir.exists():
        print(f"ERROR: Source directory not found: {source_dir}")
        return

    path_map = []
    for mapping in args.path_map:
        if "=" not in mapping:
            print(f"ERROR: Invalid --path-map '{mapping}' — expected SRC=DST")
            return
        src, dst = mapping.split("=", 1)
        path_map.append((src.strip(), dst.strip()))

    if not path_map:
        print("WARNING: No --path-map entries provided. File paths will not be translated.")

    for f in DB_FILES:
        if not (source_dir / f).exists():
            print(f"ERROR: Not found: {source_dir / f}")
            return

    work_dir = Path(tempfile.mkdtemp(prefix="plex_migrate_"))
    print(f"\n{'='*60}")
    print("  Plex Database Migration")
    print(f"{'='*60}")
    print(f"\n  Source : {source_dir}")
    print(f"  Dest   : {args.dest_user}@{args.dest_host}")
    if args.proxy_host:
        print(f"  Proxy  : {args.proxy_user}@{args.proxy_host}")
    print(f"  Paths  : {len(path_map)} mapping(s)")
    print(f"  Work   : {work_dir}\n")

    print("[1/4] Translating file paths...")
    total = 0
    for fname in DB_FILES:
        src = source_dir / fname
        dst = work_dir / fname
        print(f"\n  {fname}  ({src.stat().st_size // 1024 // 1024} MB)")
        stats = translate_database(src, dst, path_map)
        print(f"    media_parts translated : {stats['media_parts']}")
        print(f"    section_locations      : {stats['section_locations']}")
        if stats["untranslated"]:
            print(f"    ⚠ {len(stats['untranslated'])} paths had no matching rule:")
            for p in stats["untranslated"][:5]:
                print(f"      {p}")
        total += stats["media_parts"]
    print(f"\n  Total paths translated: {total}")

    print(f"\n[2/4] Ready to deploy to {args.dest_host}")
    input("  Press Enter to stop Plex and deploy, Ctrl+C to abort...\n")

    print("[3/4] Deploying...")
    rc, out = ssh_run("systemctl stop plexmediaserver && sleep 2",
                      args.dest_host, args.dest_user, args.proxy_host, args.proxy_user)
    print(f"  {'✓ Plex stopped' if rc == 0 else f'⚠ stop rc={rc}: {out}'}")

    ts = time.strftime("%Y%m%d_%H%M%S")
    for fname in DB_FILES:
        remote = f"{DEST_PLEX_DB_DIR}/{fname}"
        rc, _ = ssh_run(f"test -f {repr(remote)}",
                        args.dest_host, args.dest_user, args.proxy_host, args.proxy_user)
        if rc == 0:
            ssh_run(f"cp {repr(remote)} {repr(remote + f'.bak.{ts}')}",
                    args.dest_host, args.dest_user, args.proxy_host, args.proxy_user)
    print(f"  ✓ Existing databases backed up (.bak.{ts})")

    for fname in DB_FILES:
        remote = f"{DEST_PLEX_DB_DIR}/{fname}"
        print(f"  Uploading {fname}...")
        scp_to_dest(work_dir / fname, remote,
                    args.dest_host, args.dest_user, args.proxy_host, args.proxy_user)
        ssh_run(f"chown plex:plex {repr(remote)} && chmod 640 {repr(remote)}",
                args.dest_host, args.dest_user, args.proxy_host, args.proxy_user)
        ssh_run(f"rm -f {repr(remote + '-wal')} {repr(remote + '-shm')}",
                args.dest_host, args.dest_user, args.proxy_host, args.proxy_user)
    print("  ✓ Databases deployed")

    print("[4/4] Starting Plex...")
    rc, out = ssh_run("systemctl start plexmediaserver",
                      args.dest_host, args.dest_user, args.proxy_host, args.proxy_user)
    print(f"  {'✓ started' if rc == 0 else f'⚠ rc={rc}: {out}'}")
    time.sleep(5)
    _, status = ssh_run("systemctl is-active plexmediaserver",
                        args.dest_host, args.dest_user, args.proxy_host, args.proxy_user)
    print(f"  Status: {status}")

    shutil.rmtree(work_dir)
    print(f"\n✓ Migration complete!")
    print(f"  To roll back: ssh {args.dest_user}@{args.dest_host}")
    for fname in DB_FILES:
        remote = f"{DEST_PLEX_DB_DIR}/{fname}"
        print(f"  cp '{remote}.bak.{ts}' '{remote}'")


if __name__ == "__main__":
    main()
