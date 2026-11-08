"""Authentication, seeding, and authorization tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from xyz_portal import auth
from xyz_portal.auth.database import connection
from xyz_portal.auth.passwords import hash_password, verify_password


def _login(email: str, db_path: Path) -> dict:
    user = auth.authenticate(email, "admin1234", db_path=db_path)
    assert user is not None
    return user


def test_seed_counts_and_payroll(db_path: Path) -> None:
    with connection(db_path) as database:
        count = database.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    assert count == 15
    assert sum(employee["monthly_salary"] for employee in auth.EMPLOYEES) == 1_850_000
    assert sum(employee["annual_salary"] for employee in auth.EMPLOYEES) == 22_200_000


def test_every_seeded_account_can_sign_in(db_path: Path) -> None:
    for employee in auth.EMPLOYEES:
        user = _login(employee["email"], db_path)
        assert user["employee_id"] == employee["employee_id"]
        assert user["role"] == employee["role"]


def test_bad_password_is_rejected_and_audited(db_path: Path) -> None:
    assert (
        auth.authenticate(
            "karan.joshi@xyzcompany.example", "not-the-password", db_path=db_path
        )
        is None
    )
    events = auth.recent_auth_events(db_path=db_path)
    assert events[0]["event"] == "login_failure"
    assert events[0]["email"] == "karan.joshi@xyzcompany.example"


def test_password_hashing_roundtrip() -> None:
    encoded = hash_password("secret", iterations=1_000)
    assert encoded.startswith("pbkdf2_sha256$1000$")
    assert verify_password("secret", encoded)
    assert not verify_password("wrong", encoded)
    assert not verify_password("secret", "invalid")


@pytest.mark.parametrize(
    ("email", "scope", "directory_rows", "salary_rows"),
    [
        ("ceo@xyzcompany.example", "full", 15, 15),
        ("cto@xyzcompany.example", "directory", 4, 1),
        ("hr@xyzcompany.example", "full", 15, 15),
        ("karan.joshi@xyzcompany.example", "public", 1, 1),
    ],
)
def test_role_scopes(
    db_path: Path,
    email: str,
    scope: str,
    directory_rows: int,
    salary_rows: int,
) -> None:
    user = _login(email, db_path)
    assert auth.handbook_scope(user) == scope
    assert len(auth.visible_employees(user, db_path=db_path)) == directory_rows
    assert len(auth.compensation_employees(user, db_path=db_path)) == salary_rows


def test_role_matrix_is_seeded(db_path: Path) -> None:
    roles, permissions, mapping = auth.role_matrix(db_path=db_path)
    assert [role["name"] for role in roles] == ["CEO", "CTO", "HR", "EMPLOYEE"]
    assert len(permissions) == len(auth.PERMISSIONS)
    assert "salary:read:all" in mapping["CEO"]
    assert "salary:read:all" not in mapping["CTO"]
    assert "handbook:read:directory" in mapping["CTO"]
    assert "handbook:read:directory" not in mapping["EMPLOYEE"]


def test_permission_helpers(db_path: Path) -> None:
    cto = _login("cto@xyzcompany.example", db_path)
    assert auth.has_permission(cto, "directory:read:department")
    assert not auth.has_permission(cto, "salary:read:all")
    assert (
        auth.permission_description("salary:read:all")
        == "View all employee compensation"
    )
