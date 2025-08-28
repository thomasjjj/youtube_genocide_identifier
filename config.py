# config.py – centralised settings & path management
# --------------------------------------------------

from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv  # lightweight runtime dependency
from pydantic import Field, validator
from pydantic_settings import BaseSettings  # <-- new home of BaseSettings


# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
BASE_DIR: Path = Path(__file__).resolve().parent
DATA_DIR: Path = BASE_DIR / "data"
TRANSCRIPTS_DIR: Path = DATA_DIR / "transcripts"
RESULTS_DIR: Path = DATA_DIR / "individual_results"
DB_PATH: Path = DATA_DIR / "youtube_transcripts.db"

# ---------------------------------------------------------------------------
# Pydantic settings model
# ---------------------------------------------------------------------------
class Settings(BaseSettings):
    """Load environment variables from .env or the OS environment.

    Mandatory secrets are declared without defaults to fail fast if missing.
    Optional settings have sane defaults.
    """

    # Secrets & API
    openai_api_key: str = Field(..., env="OPENAI_API_KEY")

    # Runtime configuration
    openai_model: str = Field("gpt-5", env="OPENAI_MODEL")
    db_path: Path = Field(DB_PATH, env="DB_PATH")
    transcripts_dir: Path = Field(TRANSCRIPTS_DIR, env="TRANSCRIPTS_DIR")
    results_dir: Path = Field(RESULTS_DIR, env="RESULTS_DIR")

    # YouTube transcript fetching tweaks
    # Optional path to a cookies.txt file exported from your browser (Netscape format).
    youtube_cookies_path: Path | None = Field(None, env="YOUTUBE_COOKIES")
    # Optional HTTPS proxy, e.g. "http://127.0.0.1:8888" or "http://user:pass@host:port"
    https_proxy: str | None = Field(None, env="HTTPS_PROXY")
    # Preferred language codes, comma-separated (fallbacks tried in order, then “any available”)
    youtube_langs_csv: str = Field("en,en-GB,en-US", env="YOUTUBE_LANGS")

    @property
    def youtube_languages(self) -> list[str]:
        return [x.strip() for x in self.youtube_langs_csv.split(",") if x.strip()]

    # Allow ${HOME}/… etc. in paths
    @validator("db_path", "transcripts_dir", "results_dir", pre=True)
    def _expanduser(cls, v: Path | str) -> Path:  # noqa: N805  (pydantic convention)
        return Path(v).expanduser() if isinstance(v, (str, Path)) else v

    class Config:
        env_file = BASE_DIR / ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Instantiate once so the whole app shares the same settings instance.
load_dotenv(BASE_DIR / ".env", override=False)  # .env is optional
settings = Settings()  # raises ValidationError if OPENAI_API_KEY missing

# ---------------------------------------------------------------------------
# Convenience exports for legacy code – will be removed in v1.0
# ---------------------------------------------------------------------------
OPENAI_API_KEY: str = settings.openai_api_key
MODEL: str = settings.openai_model
DB_PATH: Path = settings.db_path

# Keep path constants (immutable) for broader import compatibility
# *Do not mutate these* at runtime.

# Re‑export already declared constants so “from config import DATA_DIR …” works
__all__ = [
    "settings",
    "OPENAI_API_KEY",
    "MODEL",
    "DB_PATH",
    "BASE_DIR",
    "DATA_DIR",
    "TRANSCRIPTS_DIR",
    "RESULTS_DIR",
    "ensure_dirs_exist",
]


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)


def ensure_dirs_exist() -> None:
    """Create runtime directories declared in *settings* if they don’t exist."""

    for directory in (
        settings.db_path.parent,
        settings.transcripts_dir,
        settings.results_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    logger.debug(
        "Ensured project directories exist: %s, %s, %s",
        settings.db_path.parent,
        settings.transcripts_dir,
        settings.results_dir,
    )


# Create paths eagerly so that downstream imports can assume they exist
ensure_dirs_exist()
