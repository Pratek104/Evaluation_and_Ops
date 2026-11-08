"""Application configuration loaded from environment variables."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
RUNTIME_DATA_DIR = DATA_DIR / "runtime"


def _path_from_env(name: str, default: Path) -> Path:
    value = os.getenv(name, "").strip()
    path = Path(value) if value else default
    return path if path.is_absolute() else PROJECT_ROOT / path


PDF_PATH = _path_from_env("PDF_PATH", RAW_DATA_DIR / "xyz_company.pdf")
DB_PATH = _path_from_env("RBAC_DB_PATH", RUNTIME_DATA_DIR / "xyz_rbac.db")
RAG_CACHE_DIR = _path_from_env("RAG_CACHE_DIR", RUNTIME_DATA_DIR / "rag_cache")

DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-4-26b-a4b-it:free").strip()
API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()


def configure_logging() -> None:
    """Configure a consistent application log format."""
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
