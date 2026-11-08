"""Authentication and permission-aware data access."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .constants import PERMISSIONS
from .database import connection, record_event, user_from_row
from .passwords import verify_password


def authenticate(
    email: str,
    password: str,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Authenticate by work email and password; return the user or None."""
    normalized_email = (email or "").strip().lower()
    password = password or ""
    if not normalized_email or not password:
        return None

    with connection(db_path) as database:
        row = database.execute(
            "SELECT * FROM employees WHERE email = ? COLLATE NOCASE",
            (normalized_email,),
        ).fetchone()
        valid = bool(
            row and row["is_active"] and verify_password(password, row["password_hash"])
        )
        if not valid:
            record_event(
                database,
                row["employee_id"] if row else None,
                normalized_email,
                "login_failure",
            )
            return None
        record_event(database, row["employee_id"], normalized_email, "login_success")
        return user_from_row(database, row)


def get_user(
    employee_id: str,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Reload an active user and their current permissions."""
    with connection(db_path) as database:
        row = database.execute(
            "SELECT * FROM employees WHERE employee_id = ? AND is_active = 1",
            (employee_id,),
        ).fetchone()
        return user_from_row(database, row) if row else None


def record_logout(
    user: dict[str, Any],
    *,
    db_path: str | Path | None = None,
) -> None:
    """Record a successful sign-out."""
    with connection(db_path) as database:
        record_event(
            database,
            user["employee_id"],
            user["email"],
            "logout",
        )


def has_permission(user: dict[str, Any], permission: str) -> bool:
    """Return whether the user's current role grants a permission."""
    return permission in user.get("permissions", ())


def handbook_scope(user: dict[str, Any]) -> str:
    """Map a user's permissions to the handbook retrieval scope."""
    if has_permission(user, "handbook:read:salary"):
        return "full"
    if has_permission(user, "handbook:read:directory"):
        return "directory"
    return "public"


def visible_employees(
    user: dict[str, Any],
    *,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return directory rows allowed by the user's directory permission."""
    where: str
    parameters: tuple[Any, ...]
    if has_permission(user, "directory:read:all"):
        where, parameters = "1 = 1", ()
    elif has_permission(user, "directory:read:department"):
        where, parameters = "department = ?", (user["department"],)
    elif has_permission(user, "directory:read:self"):
        where, parameters = "employee_id = ?", (user["employee_id"],)
    else:
        return []

    with connection(db_path) as database:
        rows = database.execute(
            f"""
            SELECT employee_id, name, job_title, department, email, joined_on,
                   reports_to, role
            FROM employees
            WHERE is_active = 1 AND {where}
            ORDER BY employee_id
            """,
            parameters,
        ).fetchall()
    return [dict(row) for row in rows]


def compensation_employees(
    user: dict[str, Any],
    *,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return compensation rows allowed by the user's salary permission."""
    where: str
    parameters: tuple[Any, ...]
    if has_permission(user, "salary:read:all"):
        where, parameters = "1 = 1", ()
    elif has_permission(user, "salary:read:self"):
        where, parameters = "employee_id = ?", (user["employee_id"],)
    else:
        return []

    with connection(db_path) as database:
        rows = database.execute(
            f"""
            SELECT employee_id, name, department, monthly_salary, annual_salary
            FROM employees
            WHERE is_active = 1 AND {where}
            ORDER BY employee_id
            """,
            parameters,
        ).fetchall()
    return [dict(row) for row in rows]


def role_matrix(
    *,
    db_path: str | Path | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, set[str]]]:
    """Return roles, permissions, and the role-to-permission mapping."""
    with connection(db_path) as database:
        roles = [
            dict(row)
            for row in database.execute(
                """
                SELECT name, label FROM roles
                ORDER BY CASE name
                    WHEN 'CEO' THEN 1 WHEN 'CTO' THEN 2
                    WHEN 'HR' THEN 3 ELSE 4 END
                """
            )
        ]
        permissions = [
            dict(row)
            for row in database.execute(
                "SELECT code, description FROM permissions ORDER BY code"
            )
        ]
        mapping: dict[str, set[str]] = {role["name"]: set() for role in roles}
        for row in database.execute("SELECT role, permission FROM role_permissions"):
            mapping[row["role"]].add(row["permission"])
    return roles, permissions, mapping


def recent_auth_events(
    limit: int = 25,
    *,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return recent sign-in events for the access-control page."""
    with connection(db_path) as database:
        rows = database.execute(
            """
            SELECT a.id, a.employee_id, a.email, a.event, a.created_at,
                   e.name
            FROM auth_audit AS a
            LEFT JOIN employees AS e ON e.employee_id = a.employee_id
            ORDER BY a.id DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 100)),),
        ).fetchall()
    return [dict(row) for row in rows]


def permission_description(code: str) -> str:
    """Return a human-readable permission description."""
    return PERMISSIONS.get(code, code)


__all__ = [
    "authenticate",
    "compensation_employees",
    "get_user",
    "handbook_scope",
    "has_permission",
    "permission_description",
    "recent_auth_events",
    "record_logout",
    "role_matrix",
    "visible_employees",
]
