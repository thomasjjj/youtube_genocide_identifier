# youtube_transcript.py – download & persist captions
# ---------------------------------------------------
# Goals
#  • Centralise settings via `config.settings`
#  • Use pathlib + context-managed SQLite (helper duplicated here)
#  • Add duplicate check so we don’t insert identical transcripts
#  • Reusable API functions *and* interactive __main__ flow (input-driven)
#  • Clean return types + detailed logging

from __future__ import annotations

import logging
import re as _re
import sqlite3
import urllib.request
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

try:
    from yt_dlp import YoutubeDL  # optional fallback
except Exception:  # pragma: no cover
    YoutubeDL = None  # type: ignore

# ── local imports ─────────────────────────────────────────────────────────
from config import settings, ensure_dirs_exist

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
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Download the transcript for *video_id*, using whatever language is available if preferred
    languages aren't found.

    Parameters
    ----------
    video_id : str
        11-character YouTube ID.
    languages : list[str] | None
        Preferred language codes. If not available, will attempt to use any available transcript.

    Returns
    -------
    tuple[list[dict[str, Any]], str]
        Raw segments as returned by *youtube-transcript-api* and language code.
    """

    # 1) preferred languages (from config) → then try "any available"
    languages = languages or settings.youtube_languages or ["en", "en-GB", "en-US"]
    transcript_language = "unknown"

    try:
        # Build proxies/cookies args if provided
        proxies = {"https": settings.https_proxy} if settings.https_proxy else None
        cookies = (
            str(settings.youtube_cookies_path)
            if settings.youtube_cookies_path
            else None
        )

        # First: try to get transcript in preferred languages (manual or generated)
        transcript = YouTubeTranscriptApi.get_transcript(
            video_id,
            languages=languages,
            proxies=proxies,
            cookies=cookies,
        )
        transcript_language = languages[
            0
        ]  # Use the first requested language if successful
        return transcript, transcript_language

    except (TranscriptsDisabled, VideoUnavailable) as exc:
        logger.error("Transcript API error for %s – %s", video_id, exc)
        raise

    except NoTranscriptFound:
        # If preferred languages aren't available, try to get a list of available languages
        try:
            proxies = {"https": settings.https_proxy} if settings.https_proxy else None
            cookies = (
                str(settings.youtube_cookies_path)
                if settings.youtube_cookies_path
                else None
            )
            transcript_list = YouTubeTranscriptApi.list_transcripts(
                video_id,
                proxies=proxies,
                cookies=cookies,
            )

            # Log available languages for debug purposes
            available_langs = [
                f"{t.language_code} ({t.language})" for t in transcript_list
            ]
            logger.info("Available transcripts for %s: %s", video_id, available_langs)

            # Prefer manual, then generated, then "first available"
            try:
                manual = transcript_list.find_manually_created_transcript(
                    settings.youtube_languages
                )
                return manual.fetch(), manual.language_code
            except Exception:
                pass
            try:
                auto = transcript_list.find_generated_transcript(
                    settings.youtube_languages
                )
                return auto.fetch(), auto.language_code
            except Exception:
                pass

            # Otherwise iterate all and take the first one we can parse
            for transcript_obj in transcript_list:
                logger.info(
                    "Using transcript in %s (%s)",
                    transcript_obj.language,
                    transcript_obj.language_code,
                )
                fetched_transcript = transcript_obj.fetch()

                # Normal path: `fetch()` returns a list[dict]
                transcript_data = (
                    list(fetched_transcript)
                    if not isinstance(fetched_transcript, list)
                    else fetched_transcript
                )

                # If we successfully parsed any transcript data, return it
                if transcript_data:
                    return transcript_data, transcript_obj.language_code
                else:
                    logger.warning(
                        f"Could not extract transcript data from {transcript_obj.language_code}"
                    )
                    continue

            # If we get here, there were no transcripts in the list or none could be parsed
            raise NoTranscriptFound(
                video_id,
                languages,
                f"No transcripts found in list for video {video_id}",
            )

        except Exception as exc:
            logger.error(
                "Failed to fetch any transcript for %s via API list: %s", video_id, exc
            )
            # ↓ Fall through to yt-dlp fallback before giving up
            return _fallback_with_ytdlp(video_id)

    # Broken captions sometimes surface as XML parse failures
    except ParseError as exc:
        msg = f"No transcript available or parse failure for video {video_id}"
        logger.error("%s – %s", msg, exc)
        # Try yt-dlp last
        return _fallback_with_ytdlp(video_id)

    # Anything we didn't anticipate
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error fetching transcript for %s", video_id)
        return _fallback_with_ytdlp(video_id)


# ---------------------- yt-dlp fallback ------------------------------------


def _fallback_with_ytdlp(video_id: str) -> Tuple[List[Dict[str, Any]], str]:
    """
    Last-resort: use yt-dlp to obtain subtitles (manual or automatic) and
    convert VTT → segment list. Requires yt-dlp to be installed.
    """
    if YoutubeDL is None:
        raise NoTranscriptFound(video_id, [], "yt-dlp not available and API failed")

    url = f"https://www.youtube.com/watch?v={video_id}"
    langs = settings.youtube_languages
    ydl_opts = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitlesformat": "vtt",
        "subtitleslangs": langs,
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise NoTranscriptFound(
            video_id, langs, f"yt-dlp extraction failed: {exc}"
        ) from exc

    subs = info.get("subtitles") or {}
    autos = info.get("automatic_captions") or {}

    # Pick the first language that exists in subs or autos
    chosen_lang = None
    tracks = None
    for code in langs:
        if code in subs:
            chosen_lang, tracks = code, subs[code]
            break
        if code in autos:
            chosen_lang, tracks = code, autos[code]
            break
    if not tracks:  # nothing in preferred langs; try any
        sources = subs or autos
        if sources:
            chosen_lang, tracks = next(iter(sources.items()))
    if not tracks:
        raise NoTranscriptFound(video_id, langs, "yt-dlp found no captions")

    # Grab first VTT URL and fetch it
    vtt_url = None
    for t in tracks:
        if t.get("ext") == "vtt" and t.get("url"):
            vtt_url = t["url"]
            break
    if not vtt_url:
        vtt_url = tracks[0].get("url")
    if not vtt_url:
        raise NoTranscriptFound(video_id, langs, "yt-dlp captions had no URL")

    try:
        with urllib.request.urlopen(vtt_url) as resp:
            vtt_text = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise NoTranscriptFound(
            video_id, langs, f"Failed to download VTT: {exc}"
        ) from exc

    segments = _vtt_to_segments(vtt_text)
    if not segments:
        raise NoTranscriptFound(video_id, langs, "VTT parsed to zero segments")
    logger.info("yt-dlp fallback succeeded for %s (%s)", video_id, chosen_lang)
    return segments, chosen_lang or "unknown"


def _vtt_to_segments(vtt_text: str) -> List[Dict[str, Any]]:
    """
    Very small VTT → segments converter: returns [{'text','start','duration'}, ...]
    Assumes well-formed cue timings like '00:01.234 --> 00:03.000'
    """

    def _ts_to_seconds(ts: str) -> float:
        # hh:mm:ss.mmm or mm:ss.mmm
        parts = ts.split(":")
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s.replace(",", "."))
        m, s = parts
        return int(m) * 60 + float(s.replace(",", "."))

    segments: List[Dict[str, Any]] = []
    # split on blank lines to get cues
    for block in _re.split(r"\n\s*\n", vtt_text.strip()):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            logger.debug("Skipping VTT block with insufficient lines: %r", block)
            continue
        # optional cue id at lines[0]; timings line contains '-->'
        timing_idx = 0 if "-->" in lines[0] else 1
        if "-->" not in lines[timing_idx]:
            logger.debug("Skipping VTT block without timing: %r", block)
            continue
        start_s, end_s = [x.strip() for x in lines[timing_idx].split("-->")[:2]]
        text = " ".join(lines[timing_idx + 1 :])
        try:
            start = _ts_to_seconds(start_s)
            end = _ts_to_seconds(end_s)
            segments.append(
                {"text": text, "start": start, "duration": max(0.0, end - start)}
            )
        except Exception as exc:
            logger.debug(
                "Failed to parse VTT timing %s --> %s: %s", start_s, end_s, exc
            )
            continue
    return segments


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
        CREATE TABLE IF NOT EXISTS transcripts
        (
            id
            INTEGER
            PRIMARY
            KEY
            AUTOINCREMENT,
            video_id
            TEXT
            NOT
            NULL,
            video_title
            TEXT,
            channel_name
            TEXT,
            transcript_text
            TEXT
            NOT
            NULL,
            transcript_language
            TEXT,
            extraction_date
            TIMESTAMP
            NOT
            NULL
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
    cur = conn.execute(
        "SELECT 1 FROM transcripts WHERE video_id = ? LIMIT 1", (video_id,)
    )
    return cur.fetchone() is not None


def save_transcript(
    transcript: List[Dict[str, Any]],
    video_id: str,
    video_title: Optional[str] = None,
    channel_name: Optional[str] = None,
    transcript_language: Optional[str] = None,
    overwrite: bool = False,
) -> Tuple[Path, bool]:
    """
    Persist transcript to a nicely-named text file **and** SQLite.

    Parameters
    ----------
    transcript : List[Dict[str, Any]]
        Transcript segments.
    video_id : str
        11-character YouTube ID.
    video_title : Optional[str]
        Video title (auto-fetched if None).
    channel_name : Optional[str]
        Channel name (auto-fetched if None).
    transcript_language : Optional[str]
        Language of the transcript (should be provided by fetch_transcript).
    overwrite : bool
        Whether to overwrite existing transcripts.

    Returns
    -------
    (Path, bool)
        Path to file and a flag indicating whether a DB insert occurred.
    """
    ensure_dirs_exist()

    # Auto-fetch metadata if caller didn't supply
    if not (video_title and channel_name):
        auto_title, auto_channel = get_video_metadata(video_id)
        if not auto_title or not auto_channel:
            auto_title, auto_channel = get_video_metadata_pytube(video_id)
        video_title = video_title or auto_title or f"Unknown Title – {video_id}"
        channel_name = channel_name or auto_channel or "Unknown Channel"

    # Verify we have a valid transcript list to work with
    if not isinstance(transcript, list):
        logger.warning(
            f"Transcript is not a list but a {type(transcript)}, attempting to convert..."
        )
        try:
            # Try to convert to a list if it's iterable
            transcript_list = list(transcript)
            transcript = transcript_list
        except Exception as e:
            logger.error(f"Failed to convert transcript to list: {e}")
            # Create a simple list with just the string representation
            transcript = [{"text": str(transcript), "start": 0.0, "duration": 0.0}]

    if not transcript:
        logger.warning("Empty transcript received, creating placeholder")
        transcript = [
            {"text": "[No transcript content available]", "start": 0.0, "duration": 0.0}
        ]

    # Ensure all transcript items are dictionaries with the required keys
    for i, item in enumerate(transcript):
        if not isinstance(item, dict):
            logger.warning(f"Transcript item {i} is not a dict: {item}")
            try:
                # Try to convert to dict if it has the necessary attributes
                transcript[i] = {
                    "text": str(getattr(item, "text", str(item))),
                    "start": float(getattr(item, "start", 0.0)),
                    "duration": float(getattr(item, "duration", 0.0)),
                }
            except Exception as e:
                logger.error(f"Failed to convert transcript item to dict: {e}")
                transcript[i] = {"text": str(item), "start": 0.0, "duration": 0.0}
        elif "text" not in item:
            logger.warning(f"Transcript item {i} missing 'text' key: {item}")
            transcript[i]["text"] = str(item)

    # ---------- write text file ------------------------------------------------
    safe_id = video_id.replace("/", "_").replace("\\", "_")
    safe_title = _re.sub(r"[^\w\s-]", "", video_title).replace(" ", "_")[:60]
    out_file = settings.transcripts_dir / f"transcript_{safe_id}_{safe_title}.txt"

    try:
        out_file.write_text(format_transcript(transcript), encoding="utf-8")
        logger.info("Transcript written to %s", out_file)
    except Exception as e:
        logger.error(f"Failed to write transcript to file: {e}")
        # Create a fallback file with a simple error message
        error_text = f"Error processing transcript: {e}"
        out_file.write_text(error_text, encoding="utf-8")

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

        # Extract transcript text safely
        try:
            transcript_text = "\n".join(
                segment.get("text", "") for segment in transcript
            )
        except Exception as e:
            logger.error(f"Error extracting transcript text: {e}")
            transcript_text = "[Error extracting transcript text]"

        # Update SQL query to include transcript_language
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
                transcript_text,
                transcript_language,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
        saved = True
        logger.info(
            "Transcript stored in DB (video_id=%s, language=%s)",
            video_id,
            transcript_language,
        )

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
        transcript, transcript_language = fetch_transcript(vid)
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
        transcript_language=transcript_language,
    )

    print(f"Transcript saved to file: {out}")
    print(
        "Transcript also saved to database." if inserted else "Already existed in DB."
    )


if __name__ == "__main__":
    _interactive_flow()
