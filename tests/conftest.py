"""Shared pytest configuration and isolated runtime paths."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = Path(tempfile.mkdtemp(prefix="xyz_portal_tests_"))

# Set these before importing the package so config.py and dotenv see the test
# paths. The missing PDF also keeps UI tests from loading the embedding model.
os.environ["RBAC_DB_PATH"] = str(TEST_ROOT / "xyz_rbac.db")
os.environ["RAG_CACHE_DIR"] = str(TEST_ROOT / "rag_cache")
os.environ["PDF_PATH"] = str(TEST_ROOT / "missing.pdf")
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["LANGSMITH_API_KEY"] = ""
os.environ["LANGSMITH_TRACING"] = "false"

sys.path.insert(0, str(PROJECT_ROOT / "src"))

from xyz_portal import auth  # noqa: E402
from xyz_portal.auth.database import resolve_db_path  # noqa: E402


def pytest_sessionfinish(session, exitstatus) -> None:
    """Remove the temporary test database and caches."""
    del session, exitstatus
    shutil.rmtree(TEST_ROOT, ignore_errors=True)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Return a freshly seeded database for one test."""
    path = tmp_path / "xyz_rbac.db"
    auth.ensure_database(path)
    return path


@pytest.fixture
def app_db() -> Path:
    """Reset the database used by the Streamlit AppTest process."""
    path = resolve_db_path()
    path.unlink(missing_ok=True)
    auth.ensure_database()
    return path
