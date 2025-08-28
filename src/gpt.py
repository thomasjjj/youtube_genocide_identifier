# gpt.py – TranscriptAnalyzer (Pydantic v2-ready)
# ------------------------------------------------
# • Cleaned imports
# • Bootstraps reproducible SQLite schema
# • Pydantic model with relaxed evidence list
# • Minimal Typer CLI (list transcripts)
# ------------------------------------------------

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

import typer
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError
from rich import print as rprint
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from config import ensure_dirs_exist, settings
from .system_prompt import construct_genocide_analysis_prompt

# Logging setup
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


class GenocideVerdict(BaseModel):
    """Schema for the genocide-incitement analysis response."""

    answer: Literal["Yes", "No", "Cannot determine"]
    reasoning: str
    evidence: List[str] = Field(default_factory=list)

    # Locally-attached metadata (populated post-parse)
    model: Optional[str] = None
    tokens_used: Optional[int] = None
    video_title: Optional[str] = None
    timestamp: Optional[datetime] = None


@contextmanager
def _connect(db_path: Path):
    """Context-managed SQLite connection with row factory."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


class TranscriptAnalyzer:
    """High-level API: *transcript row* → structured GenocideVerdict."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.openai_model
        self.client = OpenAI(api_key=self.api_key)

        ensure_dirs_exist()
        self.db_path = settings.db_path
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Create SQLite tables (transcripts + analysis_results) and migrate schema."""
        with _connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transcripts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT NOT NULL,
                    video_title TEXT,
                    channel_name TEXT,
                    transcript_text TEXT NOT NULL,
                    extraction_date TIMESTAMP NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS analysis_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transcript_id INTEGER NOT NULL,
                    answer TEXT,
                    reasoning TEXT,
                    evidence TEXT,
                    model TEXT,
                    tokens_used INTEGER,
                    analysis_date TIMESTAMP,
                    FOREIGN KEY (transcript_id) REFERENCES transcripts(id)
                );
            """)
            # Lightweight migration for analysis_results
            want = {
                "answer": "TEXT",
                "reasoning": "TEXT",
                "evidence": "TEXT",
                "model": "TEXT",
                "tokens_used": "INTEGER",
                "analysis_date": "TIMESTAMP",
            }
            have = {row["name"]: row["type"] for row in conn.execute("PRAGMA table_info(analysis_results);")}
            for col, sqltype in want.items():
                if col not in have:
                    conn.execute(f"ALTER TABLE analysis_results ADD COLUMN {col} {sqltype};")
            conn.commit()

    def _fetchone(self, query: str, params: Tuple[Any, ...]) -> Optional[sqlite3.Row]:
        with _connect(self.db_path) as conn:
            cur = conn.execute(query, params)
            return cur.fetchone()

    def list_available_transcripts(self, limit: int = 15) -> List[sqlite3.Row]:
        """Return recent transcript records, up to `limit`."""
        sql = """
            SELECT id, video_id, video_title, channel_name, extraction_date
            FROM transcripts
            ORDER BY extraction_date DESC
            LIMIT ?
        """
        with _connect(self.db_path) as conn:
            return conn.execute(sql, (limit,)).fetchall()

    def get_transcript_by_id(self, tid: int) -> Optional[sqlite3.Row]:
        return self._fetchone("SELECT * FROM transcripts WHERE id = ?", (tid,))

    def get_transcript_by_video_id(self, video_id: str) -> Optional[sqlite3.Row]:
        return self._fetchone(
            "SELECT * FROM transcripts WHERE video_id = ? ORDER BY extraction_date DESC LIMIT 1", (video_id,),
        )

    def _save_result(self, transcript_id: int, verdict: GenocideVerdict) -> None:
        with _connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO analysis_results (
                    transcript_id, answer, reasoning, evidence, model, tokens_used, analysis_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                transcript_id,
                verdict.answer,
                verdict.reasoning,
                json.dumps(verdict.evidence, ensure_ascii=False),
                verdict.model,
                verdict.tokens_used,
                (verdict.timestamp or datetime.utcnow()).isoformat(),
            ))
            conn.commit()

    async def analyze(self, transcript_rec: sqlite3.Row) -> GenocideVerdict:
        """Run the OpenAI genocide-incitement analysis and return a verdict."""
        transcript_text = transcript_rec["transcript_text"] or ""
        if len(transcript_text) > 90_000:
            transcript_text = transcript_text[:90_000] + "… [truncated]"

        user_content = (
            f"Video: {transcript_rec['video_title']}\n"
            f"Channel: {transcript_rec['channel_name']}\n\n"
            f"Transcript:\n{transcript_text}"
        )
        system_prompt = construct_genocide_analysis_prompt()

        progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(),
            transient=True,
        )
        task_id = progress.add_task("[bold green]Querying OpenAI…", total=None)
        progress.start()
        try:
            response = await asyncio.to_thread(
                self.client.responses.create,
                model=self.model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
            )
        finally:
            progress.stop()

        raw = response.output_text
        try:
            parsed = json.loads(raw)
            verdict = GenocideVerdict(**parsed)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.error("OpenAI output parse failed: %s", exc, exc_info=True)
            raise RuntimeError("Model returned invalid JSON – see logs.") from exc

        verdict.model = getattr(response, "model", None)
        verdict.tokens_used = getattr(response.usage, "total_tokens", None)
        verdict.video_title = transcript_rec['video_title']
        verdict.timestamp = datetime.utcnow()

        self._save_result(transcript_rec['id'], verdict)
        return verdict


# Minimal Typer CLI – list transcripts
app = typer.Typer(add_completion=False, help="Minimal CLI to list stored transcripts.")
_analyzer: Optional[TranscriptAnalyzer] = None

def _get_analyzer() -> TranscriptAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = TranscriptAnalyzer()
    return _analyzer

@app.command(name="list")
def list_transcripts(
    limit: int = typer.Option(10, "--limit", "-n", help="Number of transcripts to list")
):
    """Show the most recent transcripts in the local DB."""
    rows = _get_analyzer().list_available_transcripts(limit)
    if not rows:
        rprint("[yellow]No transcripts found. Run the extractor first.")
        raise typer.Exit()
    for r in rows:
        date = r['extraction_date'].split("T")[0]
        rprint(f"[cyan]{r['id']:>4}[/] | {date} | {r['video_title']}")

if __name__ == "__main__":
    app()