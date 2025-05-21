# genocide_detect.py — Typer CLI for "YouTube-rhetoric" pipeline
# ────────────────────────────────────────────────────────────────────────────
# • Step 1  Fetch/cache a YouTube transcript in SQLite + text file
# • Step 2  Send transcript to OpenAI, store + pretty-print the verdict
# ---------------------------------------------------------------------------
from __future__ import annotations
from datetime import datetime

import asyncio
import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from typer import Context

from config import RESULTS_DIR, ensure_dirs_exist
from src.gpt import TranscriptAnalyzer
from src.youtube_transcript import (
    extract_video_id,
    fetch_transcript,
    save_transcript,
)

# ── logging ————————————————————————————————————————————————————————————
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ── Typer app ————————————————————————————————————————————————————————————
app = typer.Typer(
    add_completion=False,
    rich_markup_mode="rich",
    help="""
CLI helper that **(1)** grabs a YouTube transcript and **(2)** runs the
OpenAI genocide-intent analysis. Simply provide a YouTube URL to run the
full pipeline automatically. If you launch it without arguments, it will
prompt you for a URL.
""",
)

# ── lazy singleton for the analyzer ————————————————————————————————
_analyzer: Optional[TranscriptAnalyzer] = None


def _get_analyzer() -> TranscriptAnalyzer:
    global _analyzer  # noqa: PLW0603
    if _analyzer is None:
        _analyzer = TranscriptAnalyzer()
    return _analyzer


# ── helpers ————————————————————————————————————————————————————————


def _pretty_json(data: dict) -> str:
    """Pretty-print dicts that may contain datetime objects."""
    return json.dumps(
        data,
        indent=2,
        ensure_ascii=False,
        default=lambda o: o.isoformat() if isinstance(o, datetime) else str(o),
    )


def _save_json_to_file(data: dict, path: Path) -> None:
    path.write_text(_pretty_json(data), encoding="utf-8")


def _acquire_transcript(video_id: str, *, overwrite: bool = False):
    """
    Return a SQLite row for `transcripts` (fetch and/or insert as needed).

    Handles first-run DBs that might still miss the table.
    """
    analyzer = _get_analyzer()

    # Existing transcript in DB? (handle ancient DBs missing table)
    try:
        rec = analyzer.get_transcript_by_video_id(video_id)
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            rec = None  # first run on old DB — we'll create it below
        else:
            raise

    if rec and not overwrite:
        return rec  # ✅ cache hit

    # Otherwise download (or overwrite) transcript
    rprint("[cyan]\nFetching transcript – this may take a few seconds…")

    try:
        # Fetch transcript data and language
        transcript_data, transcript_lang = fetch_transcript(video_id)

        # Make sure transcript_data is a list we can work with
        if not isinstance(transcript_data, list):
            rprint("[yellow]Warning: Transcript data is not a list, attempting to convert...")
            try:
                # Try to convert to a list if it's iterable
                transcript_data = list(transcript_data)
            except Exception as e:
                rprint(f"[red]Failed to convert transcript data to list: {e}")
                # Create a simple list with just the string representation
                transcript_data = [{'text': str(transcript_data), 'start': 0.0, 'duration': 0.0}]

        # Verify we have something to work with
        if not transcript_data:
            rprint("[red]Empty transcript data received")
            raise ValueError("Empty transcript data")

        # Save the transcript
        file_path, saved_to_db = save_transcript(
            transcript_data,
            video_id,
            transcript_language=transcript_lang,
            overwrite=overwrite
        )

        tag = "saved" if saved_to_db else "updated" if overwrite else "skipped"
        rprint(f"[green]Transcript {tag} → {file_path}")

        # Get the updated record
        return analyzer.get_transcript_by_video_id(video_id)

    except Exception as exc:
        rprint(f"[red]Error in _acquire_transcript: {exc}")
        raise


def process_video(video_id: str, force_extract: bool = False, force_analysis: bool = False):
    """Process a video through the entire pipeline: extraction + analysis."""
    # 1️⃣ transcript
    try:
        # Use _acquire_transcript which properly handles the transcript fetching and saving
        transcript_rec = _acquire_transcript(video_id, overwrite=force_extract)

        if transcript_rec is None:
            rprint("[red]Could not acquire transcript; aborting.")
            raise typer.Exit(1)

        # Display language information if available
        # sqlite3.Row objects support dictionary-style access but not .get() method
        # So we need to check if the key exists first
        if "transcript_language" in transcript_rec.keys():
            transcript_lang = transcript_rec["transcript_language"]
            if transcript_lang and transcript_lang.lower() != 'en':
                rprint(f"[yellow]Note: Using transcript in language: {transcript_lang}")
                rprint("[yellow]Analysis may be less accurate for non-English content.")

    except Exception as exc:  # noqa: BLE001
        rprint(f"[red]Transcript step failed: {exc}")
        raise typer.Exit(1)

    # 2️⃣ analysis
    analyzer = _get_analyzer()

    # Check for cached analysis if not forcing
    if not force_analysis:
        # Only check cache if analyzer has the method
        if hasattr(analyzer, 'last_verdict_for_video'):
            cached = analyzer.last_verdict_for_video(video_id)
            if cached:
                rprint("[green]Using cached analysis (use --force-analysis to override):")
                rprint(_pretty_json(cached.model_dump()))
                return cached

    rprint("[cyan]\nRunning OpenAI analysis ... this might take a while.")
    try:
        verdict = asyncio.run(analyzer.analyze(transcript_rec))
    except Exception as exc:  # noqa: BLE001
        rprint(f"[red]OpenAI call failed: {exc}")
        raise typer.Exit(1)

    # ── output ────────────────────────────────────────────────
    rprint("\n[bold magenta]— Analysis Result —")
    pretty = _pretty_json(verdict.model_dump())
    rprint(pretty)

    results_dir = Path(RESULTS_DIR)
    results_dir.mkdir(parents=True, exist_ok=True)
    out = results_dir / f"analysis_{video_id}_{verdict.timestamp:%Y%m%d_%H%M%S}.json"
    _save_json_to_file(verdict.model_dump(), out)

    rprint(f"[green]\nResult saved to: {out}")
    return verdict


# ── default (no sub-command) ————————————————————————————————————————


@app.callback(invoke_without_command=True)
def _default(
        ctx: Context,
        url: str = typer.Argument(None, help="YouTube URL or 11-char ID"),
        force_extract: bool = typer.Option(
            False, "--force-extract", "-E", help="Re-download transcript"
        ),
        force_analysis: bool = typer.Option(
            False, "--force-analysis", "-A", help="Ignore cached verdict"
        ),
):
    """Run the full pipeline: extract transcript and analyze content."""
    if ctx.invoked_subcommand:
        return  # a real sub-command was chosen

    ensure_dirs_exist()

    # If URL was provided as argument, use it directly
    if url:
        video_id = extract_video_id(url) if "http" in url else url
        process_video(video_id, force_extract, force_analysis)
        raise typer.Exit()

    # Interactive prompt — user preference
    url = input("Enter the YouTube video URL (or ID): ").strip()
    if not url:
        rprint("[red]No URL provided. Exiting.")
        raise typer.Exit(1)

    video_id = extract_video_id(url) if "http" in url else url
    process_video(video_id, force_extract, force_analysis)
    raise typer.Exit()


# ── sub-commands ——————————————————————————————————————————————————————


@app.command()
def extract(
        url: str = typer.Argument(..., help="YouTube URL or 11-char ID"),
        overwrite: bool = typer.Option(
            False, "--overwrite", "-o", help="Force re-download if present"
        ),
):
    """Only fetch & store the transcript (skip analysis)."""
    ensure_dirs_exist()
    video_id = extract_video_id(url) if "http" in url else url
    _acquire_transcript(video_id, overwrite=overwrite)
    rprint("[bold green]\nDone!")


@app.command()
def analyze(
        url: str = typer.Argument(..., help="YouTube URL or 11-char ID"),
        force_extract: bool = typer.Option(
            False, "--force-extract", "-E", help="Re-download transcript"
        ),
        force_analysis: bool = typer.Option(
            False, "--force-analysis", "-A", help="Ignore cached verdict"
        ),
):
    """End-to-end pipeline (transcript + analysis) with cache controls."""
    ensure_dirs_exist()
    video_id = extract_video_id(url) if "http" in url else url
    process_video(video_id, force_extract, force_analysis)


@app.command(name="list")
def _list(
        limit: int = typer.Option(10, "--limit", "-n", help="Rows to show"),
):
    """Show the latest transcripts already in the DB."""
    rows = _get_analyzer().list_available_transcripts(limit)
    if not rows:
        rprint("[yellow]No transcripts found. Run the extractor first.")
        raise typer.Exit(1)

    for r in rows:
        dt = r["extraction_date"].split("T")[0]
        rprint(f"[cyan]{r['id']:>4}[/] | {dt} | {r['video_title']}")


# ── entry-point ——————————————————————————————————————————————————————
if __name__ == "__main__":
    app()