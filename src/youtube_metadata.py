# youtube_metadata.py – lightweight metadata fetch & cache
# --------------------------------------------------------
# Provides helper(s) to retrieve YouTube video title + channel *without*
# Google API credentials.  Primary function `get_video_metadata()` already
# does a two-step lookup (yt-dlp → pytube).  Several legacy callers still
# import a now-removed helper `get_video_metadata_pytube`, so we re-add a
# *thin* wrapper for backward compatibility.

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import NamedTuple, Optional, Tuple
from urllib.parse import parse_qs, urlparse

# Local imports
from config import ensure_dirs_exist, settings

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------
class VideoMeta(NamedTuple):
    title: Optional[str]
    channel: Optional[str]


# ---------------------------------------------------------------------------
# SQLite helper (private)
# ---------------------------------------------------------------------------
@contextmanager
def _connect(db_path: Path):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS video_metadata (
            video_id TEXT PRIMARY KEY,
            video_title TEXT,
            channel_name TEXT,
            fetch_date TIMESTAMP NOT NULL
        );
        """
    )
    conn.commit()


def _from_cache(conn: sqlite3.Connection, vid: str) -> Optional[VideoMeta]:
    row = conn.execute(
        "SELECT video_title, channel_name FROM video_metadata WHERE video_id = ?",
        (vid,),
    ).fetchone()
    if row:
        return VideoMeta(row[0], row[1])
    return None


def _to_cache(conn: sqlite3.Connection, vid: str, meta: VideoMeta) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO video_metadata VALUES (?, ?, ?, ?)",
        (vid, meta.title, meta.channel, datetime.utcnow().isoformat()),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Public helpers (main + backward-compat)
# ---------------------------------------------------------------------------

def _metadata_via_yt_dlp(video_id: str) -> VideoMeta:
    """Try yt-dlp JSON dump; returns (None, None) on failure."""
    try:
        cmd = [
            "yt-dlp",
            "--dump-json",
            "--no-warnings",
            f"https://www.youtube.com/watch?v={video_id}",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(proc.stdout)
        return VideoMeta(data.get("title"), data.get("uploader") or data.get("channel"))
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return VideoMeta(None, None)


def _metadata_via_pytube(video_id: str) -> VideoMeta:
    """Always uses pytube directly (no cache)."""
    try:
        from pytube import YouTube  # type: ignore

        yt = YouTube(f"https://www.youtube.com/watch?v={video_id}")
        return VideoMeta(yt.title, yt.author)
    except Exception as exc:  # noqa: BLE001
        logger.debug("pytube failed for %s: %s", video_id, exc)
        return VideoMeta(None, None)


def get_video_metadata(video_id: str, *, use_cache: bool = True) -> VideoMeta:
    """Return `(title, channel)` for *video_id*.

    Order: SQLite cache → yt-dlp → pytube.  Stores result in cache even if
    incomplete to avoid repeat network calls.
    """

    ensure_dirs_exist()

    # 1) cache lookup
    with _connect(settings.db_path) as conn:
        _ensure_table(conn)
        if use_cache:
            cached = _from_cache(conn, video_id)
            if cached and all(cached):
                logger.debug("Cache hit for %s", video_id)
                return cached

    # 2) yt-dlp
    meta = VideoMeta(None, None)
    if shutil.which("yt-dlp"):
        meta = _metadata_via_yt_dlp(video_id)

    # 3) pytube fallback if we’re missing any field
    if not all(meta):
        meta = _metadata_via_pytube(video_id)

    # 4) persist to cache (even if None/None) so we don’t retry instantly
    with _connect(settings.db_path) as conn:
        _ensure_table(conn)
        _to_cache(conn, video_id, meta)

    return meta


# ---------------------------------------------------------------------------
# Backward compatibility shim
# ---------------------------------------------------------------------------

def get_video_metadata_pytube(video_id: str) -> VideoMeta:  # noqa: N802 (legacy name)
    """Legacy helper retained for older imports.

    Directly calls pytube **only**, bypassing yt-dlp and cache. Use the new
    `get_video_metadata` in fresh code where possible.
    """

    return _metadata_via_pytube(video_id)


# ---------------------------------------------------------------------------
# Convenience helper for full URLs (strips query / playlist params)
# ---------------------------------------------------------------------------

def get_video_metadata_from_url(url: str, *, use_cache: bool = True) -> VideoMeta:
    """Extract 11-char ID from an arbitrary YouTube URL then fetch metadata."""

    parsed = urlparse(url)
    if parsed.hostname in {"youtu.be"}:  # short URL
        vid = parsed.path.lstrip("/")
    else:  # youtube.com/watch?v=…
        vid = parse_qs(parsed.query).get("v", [""])[0]

    if not vid:
        raise ValueError("Could not extract video ID from URL")

    return get_video_metadata(vid, use_cache=use_cache)


# ---------------------------------------------------------------------------
# Interactive CLI – keeps `input()` UX for quick look-ups
# ---------------------------------------------------------------------------

def _interactive_flow() -> None:  # pragma: no cover
    url = input("Enter YouTube URL (or plain video ID): ").strip()
    meta = (
        get_video_metadata_from_url(url) if "http" in url else get_video_metadata(url)
    )

    print("\nMetadata:\n--------")
    print(f"Title  : {meta.title or '[not found]'}")
    print(f"Channel: {meta.channel or '[not found]'}")


if __name__ == "__main__":  # pragma: no cover
    if len(sys.argv) > 1:
        meta = (
            get_video_metadata_from_url(sys.argv[1])
            if "http" in sys.argv[1]
            else get_video_metadata(sys.argv[1])
        )
        print(meta)
    else:
        _interactive_flow()
