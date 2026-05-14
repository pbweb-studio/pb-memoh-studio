"""Studio Admin UI (phase 13a): read-only Jinja + Bootstrap skeleton."""

from pathlib import Path


def templates_dir() -> Path:
    return Path(__file__).resolve().parent / "templates"


def static_dir() -> Path:
    return Path(__file__).resolve().parent / "static"
