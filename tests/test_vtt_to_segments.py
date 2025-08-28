import logging
import sys
from pathlib import Path
import types

import pytest

# Stub external dependency to avoid requiring actual package during tests
yt_api = types.ModuleType("youtube_transcript_api")
yt_api.YouTubeTranscriptApi = object
sys.modules["youtube_transcript_api"] = yt_api
errors_mod = types.ModuleType("youtube_transcript_api._errors")
for name in ["TranscriptsDisabled", "VideoUnavailable", "NoTranscriptFound"]:
    setattr(errors_mod, name, type(name, (Exception,), {}))
sys.modules["youtube_transcript_api._errors"] = errors_mod

# Stub minimal config module to satisfy youtube_transcript imports
config_stub = types.ModuleType("config")


class DummySettings:
    youtube_languages = ["en"]
    youtube_cookies_path = None
    https_proxy = None
    transcripts_dir = Path("./")
    db_path = Path("./dummy.db")


def ensure_dirs_exist() -> None:  # pragma: no cover - no-op for tests
    pass


config_stub.settings = DummySettings()
config_stub.ensure_dirs_exist = ensure_dirs_exist
sys.modules["config"] = config_stub

# Ensure repository root and src directory are on the path
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.extend([str(BASE_DIR / "src"), str(BASE_DIR)])

from youtube_transcript import _vtt_to_segments


def test_vtt_to_segments_parses_valid_input():
    vtt = """WEBVTT

00:00:01.000 --> 00:00:04.000
Hello world

00:00:05.000 --> 00:00:07.000
Another line
"""
    segments = _vtt_to_segments(vtt)
    assert len(segments) == 2
    assert segments[0]["text"] == "Hello world"
    assert segments[0]["start"] == 1.0
    assert segments[0]["duration"] == 3.0


def test_vtt_to_segments_logs_invalid_block(caplog):
    vtt = """WEBVTT

00:00:01.000 --> 00:00:02.000
Valid line

Bad block without timing
Just text
"""
    with caplog.at_level(logging.DEBUG):
        segments = _vtt_to_segments(vtt)
    assert len(segments) == 1
    assert any("without timing" in rec.getMessage() for rec in caplog.records)
