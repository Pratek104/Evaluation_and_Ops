"""Delete and reseed the local demo SQLite database."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from xyz_portal import auth  # noqa: E402
from xyz_portal.auth.database import resolve_db_path  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation prompt.",
    )
    args = parser.parse_args()

    database_path = resolve_db_path()
    if not args.yes:
        answer = input(
            f"This deletes {database_path} and reseeds the demo employees. "
            "Continue? [y/N] "
        )
        if answer.strip().lower() not in {"y", "yes"}:
            print("Cancelled.")
            return 1

    database_path.unlink(missing_ok=True)
    auth.ensure_database()
    print(f"Reseeded demo database at {database_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
