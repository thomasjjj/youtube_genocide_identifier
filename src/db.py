# db.py – connect_db function and database operations
# -------------------------------------------------------------------------
from __future__ import annotations

import json
import logging
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from youtube_transcript_api import YouTubeTranscriptApi, YouTubeTranscriptApiError  # type: ignore

# Local imports
from config import settings, ensure_dirs_exist

from src.youtube_metadata import get_video_metadata, get_video_metadata_pytube
from pydantic import Field, validator
from pydantic_settings import BaseSettings  # <-- new home of BaseSettings

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

@contextmanager
def connect_db():
    """Context-managed SQLite connection with row factory."""
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def extract_video_id(youtube_url: str) -> str:
    parsed = urlparse(youtube_url)
    host = parsed.hostname or ""
    if host in {"www.youtube.com", "youtube.com"}:
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [""])[0]
        if parsed.path.startswith("/embed/"):
            return parsed.path.split("/")[2]
        if parsed.path.startswith("/v/"):
            return parsed.path.split("/")[2]
    elif host == "youtu.be":
        return parsed.path.lstrip("/")
    raise ValueError("Could not extract video ID from URL – unsupported format.")


# ---------------------------------------------------------------------------
# Transcript fetching
# ---------------------------------------------------------------------------

def fetch_transcript(video_id: str, languages: Optional[List[str]] = None) -> List[Dict]:
    languages = languages or ["en"]
    try:
        return YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
    except YouTubeTranscriptApiError as exc:
        logger.error("Transcript API error for %s: %s", video_id, exc)
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected error fetching transcript for %s: %s", video_id, exc)
        raise


def _format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def format_transcript(transcript: List[Dict]) -> str:
    if not transcript:
        return "<no transcript available>"
    return "\n".join(f"[{_format_time(e['start'])}] {e['text']}" for e in transcript)


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _ensure_transcripts_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS transcripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT NOT NULL,
            video_title TEXT,
            channel_name TEXT,
            transcript_text TEXT NOT NULL,
            transcript_language TEXT,
            extraction_date TIMESTAMP NOT NULL
        );
        """
    )
    conn.commit()

    # Check if transcript_language column exists, add it if not
    try:
        conn.execute("SELECT transcript_language FROM transcripts LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE transcripts ADD COLUMN transcript_language TEXT;")
        conn.commit()


def _transcript_exists(conn: sqlite3.Connection, video_id: str) -> bool:
    return conn.execute("SELECT 1 FROM transcripts WHERE video_id = ? LIMIT 1", (video_id,)).fetchone() is not None


def save_transcript(
    transcript: List[Dict],
    video_id: str,
    video_title: Optional[str] = None,
    channel_name: Optional[str] = None,
    transcript_language: Optional[str] = None,
    overwrite: bool = False,
) -> Tuple[Path, bool]:
    ensure_dirs_exist()

    if not (video_title and channel_name):
        auto_title, auto_channel = get_video_metadata(video_id)
        if not auto_title or not auto_channel:
            auto_title, auto_channel = get_video_metadata_pytube(video_id)
        video_title = video_title or auto_title or f"Unknown Title – {video_id}"
        channel_name = channel_name or auto_channel or "Unknown Channel"

    safe_id = video_id.replace("/", "_").replace("\\", "_")
    safe_title = re.sub(r"[^\w\s-]", "", video_title).replace(" ", "_")[:60]
    file_path = settings.transcripts_dir / f"transcript_{safe_id}_{safe_title}.txt"
    file_path.write_text(format_transcript(transcript), encoding="utf-8")
    logger.info("Transcript written to %s", file_path)

    saved = False
    with connect_db() as conn:
        _ensure_transcripts_table(conn)
        if _transcript_exists(conn, video_id):
            if overwrite:
                conn.execute("DELETE FROM transcripts WHERE video_id = ?", (video_id,))
            else:
                logger.info("Transcript for %s already in DB; skipping insert.", video_id)
                return file_path, False
        conn.execute(
            """
            INSERT INTO transcripts (video_id, video_title, channel_name, 
                                     transcript_text, transcript_language, extraction_date) 
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                video_id,
                video_title,
                channel_name,
                "\n".join(e["text"] for e in transcript),
                transcript_language,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
        saved = True
        logger.info("Transcript stored in DB (video_id=%s, language=%s)", video_id, transcript_language or "unknown")
    return file_path, saved


# ---------------------------------------------------------------------------
# Interactive flow
# ---------------------------------------------------------------------------

def _interactive_flow() -> None:
    ensure_dirs_exist()
    url = input("Enter the YouTube video URL: ").strip()
    try:
        vid = extract_video_id(url)
    except ValueError as exc:
        logger.error("%s", exc)
        print(f"Error: {exc}")
        return

    try:
        print("Fetching transcript… (this might take a few seconds)")
        transcript_data = fetch_transcript(vid)
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to fetch transcript: {exc}")
        return

    preview = "\n".join(entry["text"] for entry in transcript_data)[:500]
    print("\nTranscript preview:\n", preview, "…\n", sep="")

    title_override = input("Video title (press Enter to auto / keep): ").strip()
    channel_override = input("Channel name (press Enter to auto / keep): ").strip()

    fp, saved_flag = save_transcript(
        transcript_data,
        video_id=vid,
        video_title=title_override or None,
        channel_name=channel_override or None,
    )
    print(f"Transcript saved to file: {fp}")
    print("Transcript also saved to database." if saved_flag else "Transcript already existed in database.")


if __name__ == "__main__":
    _interactive_flow()