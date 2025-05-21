# youtube_transcript.py – download & persist captions
# ---------------------------------------------------
# Goals
#  • Centralise settings via `config.settings`
#  • Use pathlib + context-managed SQLite (helper duplicated here)
#  • Add duplicate check so we don’t insert identical transcripts
#  • Reusable API functions *and* interactive __main__ flow (input-driven)
#  • Clean return types + detailed logging

from __future__ import annotations

import json
import logging
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse
from xml.etree.ElementTree import ParseError

# ── third-party ───────────────────────────────────────────────────────────
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    VideoUnavailable,
    NoTranscriptFound,
)

# ── local imports ─────────────────────────────────────────────────────────
from config import settings, ensure_dirs_exist

# If this file lives inside the same `src` package as youtube_metadata.py
# a relative import is safest.  Fall back to absolute if you prefer.
try:
    from .youtube_metadata import (
        get_video_metadata,
        get_video_metadata_pytube,
    )
except ImportError:  # running as a script, not a module
    from src.youtube_metadata import (
        get_video_metadata,
        get_video_metadata_pytube,
    )

# ── logging setup ─────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------


@contextmanager
def _connect(db_path: Path):
    """Context-managed connection with row dicts."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def extract_video_id(youtube_url: str) -> str:
    """Return the 11-char YouTube video ID or raise ValueError."""
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


def fetch_transcript(
    video_id: str, languages: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Download the transcript for *video_id*.

    Parameters
    ----------
    video_id : str
        11-character YouTube ID.
    languages : list[str] | None
        Preferred language codes (defaults to ``["en"]``).

    Returns
    -------
    list[dict[str, Any]]
        Raw segments as returned by *youtube-transcript-api*.

    Raises
    ------
    TranscriptsDisabled
    VideoUnavailable
    NoTranscriptFound
    """
    languages = languages or ["en"]
    try:
        return YouTubeTranscriptApi.get_transcript(video_id, languages=languages)

    # Known library exceptions
    except (TranscriptsDisabled, VideoUnavailable, NoTranscriptFound) as exc:
        logger.error("Transcript API error for %s – %s", video_id, exc)
        raise

    # Broken captions sometimes surface as XML parse failures
    except ParseError as exc:
        msg = (
            f"No transcript available or parse failure for video {video_id}"
        )
        logger.error("%s – %s", msg, exc)
        raise NoTranscriptFound(msg) from exc

    # Anything we didn’t anticipate
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error fetching transcript for %s", video_id)
        raise


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def format_transcript(transcript: List[Dict[str, Any]]) -> str:
    """Human-readable transcript with [MM:SS] prefixes."""
    if not transcript:
        return "<no transcript available>"

    return "\n".join(
        f"[{_format_time(seg['start'])}] {seg['text']}" for seg in transcript
    )


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
            extraction_date TIMESTAMP NOT NULL
        );
        """
    )
    conn.commit()


def _transcript_exists(conn: sqlite3.Connection, video_id: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM transcripts WHERE video_id = ? LIMIT 1", (video_id,)
    )
    return cur.fetchone() is not None


def save_transcript(
    transcript: List[Dict[str, Any]],
    video_id: str,
    video_title: Optional[str] = None,
    channel_name: Optional[str] = None,
    overwrite: bool = False,
) -> Tuple[Path, bool]:
    """
    Persist transcript to a nicely-named text file **and** SQLite.

    Returns
    -------
    (Path, bool)
        Path to file and a flag indicating whether a DB insert occurred.
    """
    ensure_dirs_exist()

    # Auto-fetch metadata if caller didn’t supply
    if not (video_title and channel_name):
        auto_title, auto_channel = get_video_metadata(video_id)
        if not auto_title or not auto_channel:
            auto_title, auto_channel = get_video_metadata_pytube(video_id)
        video_title = video_title or auto_title or f"Unknown Title – {video_id}"
        channel_name = channel_name or auto_channel or "Unknown Channel"

    # ---------- write text file ------------------------------------------------
    safe_id = video_id.replace("/", "_").replace("\\", "_")
    safe_title = re.sub(r"[^\w\s-]", "", video_title).replace(" ", "_")[:60]
    out_file = settings.transcripts_dir / f"transcript_{safe_id}_{safe_title}.txt"
    out_file.write_text(format_transcript(transcript), encoding="utf-8")
    logger.info("Transcript written to %s", out_file)

    # ---------- upsert into DB -------------------------------------------------
    saved = False
    with _connect(settings.db_path) as conn:
        _ensure_transcripts_table(conn)

        if _transcript_exists(conn, video_id):
            if overwrite:
                logger.info("Overwriting existing DB transcript for %s", video_id)
                conn.execute("DELETE FROM transcripts WHERE video_id = ?", (video_id,))
            else:
                logger.info(
                    "Transcript for %s already in DB; skipping insert.", video_id
                )
                return out_file, False

        conn.execute(
            """
            INSERT INTO transcripts (
                video_id, video_title, channel_name,
                transcript_text, extraction_date
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                video_id,
                video_title,
                channel_name,
                "\n".join(seg["text"] for seg in transcript),
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
        saved = True
        logger.info("Transcript stored in DB (video_id=%s)", video_id)

    return out_file, saved


# ---------------------------------------------------------------------------
# Interactive script entry-point
# ---------------------------------------------------------------------------


def _interactive_flow() -> None:
    """Simple CLI driven by `input()` prompts."""
    ensure_dirs_exist()

    url = input("Enter the YouTube video URL: ").strip()
    try:
        vid = extract_video_id(url)
    except ValueError as exc:
        logger.error("%s", exc)
        print(f"Error: {exc}")
        return

    print("Fetching transcript… (this might take a few seconds)")
    try:
        transcript = fetch_transcript(vid)
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to fetch transcript: {exc}")
        return

    # Preview first ~500 characters
    preview = "\n".join(seg["text"] for seg in transcript)[:500]
    print("\nTranscript preview:\n", preview, "…\n", sep="")

    # Optional metadata overrides
    title_override = input("Video title (press ¶ to auto/keep): ").strip()
    channel_override = input("Channel name (press ¶ to auto/keep): ").strip()

    out, inserted = save_transcript(
        transcript,
        video_id=vid,
        video_title=title_override or None,
        channel_name=channel_override or None,
    )

    print(f"Transcript saved to file: {out}")
    print("Transcript also saved to database." if inserted else "Already existed in DB.")


if __name__ == "__main__":
    _interactive_flow()
