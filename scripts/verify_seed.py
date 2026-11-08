"""Verify the seeded employee directory and payroll totals."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from xyz_portal import auth  # noqa: E402
from xyz_portal.auth.database import connection  # noqa: E402

EXPECTED_EMPLOYEES = 15
EXPECTED_MONTHLY_PAYROLL = 1_850_000
EXPECTED_ANNUAL_PAYROLL = 22_200_000


def main() -> int:
    auth.ensure_database()
    with connection() as database:
        count = database.execute(
            "SELECT COUNT(*) FROM employees WHERE is_active = 1"
        ).fetchone()[0]
        monthly, annual = database.execute(
            "SELECT SUM(monthly_salary), SUM(annual_salary) FROM employees "
            "WHERE is_active = 1"
        ).fetchone()
        roles = {
            row["name"]: row["count"]
            for row in database.execute(
                "SELECT role AS name, COUNT(*) AS count FROM employees "
                "GROUP BY role ORDER BY role"
            )
        }

    checks = {
        "active employees": (count, EXPECTED_EMPLOYEES),
        "monthly payroll": (monthly, EXPECTED_MONTHLY_PAYROLL),
        "annual payroll": (annual, EXPECTED_ANNUAL_PAYROLL),
    }
    failed = False
    for label, (actual, expected) in checks.items():
        status = "ok" if actual == expected else "FAILED"
        print(f"{label}: {actual} (expected {expected}) [{status}]")
        failed = failed or actual != expected

    print(f"role counts: {roles}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
