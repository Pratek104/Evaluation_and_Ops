"""SQLite schema, connection handling, and demo-data seeding."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .. import config
from .constants import (
    EMPLOYEES,
    PERMISSIONS,
    ROLE_PERMISSIONS,
    ROLES,
    SEED_PASSWORD,
)
from .passwords import hash_password

SCHEMA = """
CREATE TABLE IF NOT EXISTS roles (
    name TEXT PRIMARY KEY,
    label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS permissions (
    code TEXT PRIMARY KEY,
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS role_permissions (
    role TEXT NOT NULL REFERENCES roles(name) ON DELETE CASCADE,
    permission TEXT NOT NULL REFERENCES permissions(code) ON DELETE CASCADE,
    PRIMARY KEY (role, permission)
);

CREATE TABLE IF NOT EXISTS employees (
    employee_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    job_title TEXT NOT NULL,
    department TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    joined_on TEXT NOT NULL,
    reports_to TEXT NOT NULL,
    monthly_salary INTEGER NOT NULL CHECK (monthly_salary >= 0),
    annual_salary INTEGER NOT NULL CHECK (annual_salary >= 0),
    role TEXT NOT NULL REFERENCES roles(name),
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS auth_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT,
    email TEXT NOT NULL,
    event TEXT NOT NULL CHECK (event IN ('login_success', 'login_failure', 'logout')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_employees_department ON employees(department);
CREATE INDEX IF NOT EXISTS idx_auth_audit_created_at ON auth_audit(created_at);
"""


def resolve_db_path(db_path: str | Path | None = None) -> Path:
    """Resolve a database path against the project root."""
    path = Path(db_path) if db_path is not None else config.DB_PATH
    return path if path.is_absolute() else config.PROJECT_ROOT / path


@contextmanager
def connection(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Open a transaction-safe SQLite connection."""
    path = resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(path, timeout=10)
    database.row_factory = sqlite3.Row
    database.execute("PRAGMA foreign_keys = ON")
    try:
        yield database
        database.commit()
    except Exception:
        database.rollback()
        raise
    finally:
        database.close()


def _seed_reference_data(database: sqlite3.Connection) -> None:
    database.executemany(
        "INSERT OR IGNORE INTO roles (name, label) VALUES (?, ?)",
        [(name, label) for name, label in ROLES.items()],
    )
    database.executemany(
        "INSERT OR IGNORE INTO permissions (code, description) VALUES (?, ?)",
        [(code, description) for code, description in PERMISSIONS.items()],
    )
    database.executemany(
        "INSERT OR IGNORE INTO role_permissions (role, permission) VALUES (?, ?)",
        [
            (role, permission)
            for role, permissions in ROLE_PERMISSIONS.items()
            for permission in permissions
        ],
    )


def _seed_employees(database: sqlite3.Connection) -> None:
    existing = {
        row["employee_id"]
        for row in database.execute("SELECT employee_id FROM employees")
    }
    for employee in EMPLOYEES:
        if employee["employee_id"] in existing:
            continue
        database.execute(
            """
            INSERT INTO employees (
                employee_id, name, job_title, department, email, joined_on,
                reports_to, monthly_salary, annual_salary, role, password_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                employee["employee_id"],
                employee["name"],
                employee["job_title"],
                employee["department"],
                employee["email"],
                employee["joined_on"],
                employee["reports_to"],
                employee["monthly_salary"],
                employee["annual_salary"],
                employee["role"],
                hash_password(SEED_PASSWORD),
            ),
        )


def ensure_database(db_path: str | Path | None = None) -> Path:
    """Create and seed the SQLite database if needed, then return its path."""
    path = resolve_db_path(db_path)
    with connection(path) as database:
        database.executescript(SCHEMA)
        _seed_reference_data(database)
        _seed_employees(database)
    return path


def user_from_row(database: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    """Build the session-safe user record for an employee row."""
    permissions = tuple(
        permission_row["permission"]
        for permission_row in database.execute(
            "SELECT permission FROM role_permissions WHERE role = ? ORDER BY permission",
            (row["role"],),
        )
    )
    role_label = database.execute(
        "SELECT label FROM roles WHERE name = ?", (row["role"],)
    ).fetchone()
    return {
        "employee_id": row["employee_id"],
        "name": row["name"],
        "job_title": row["job_title"],
        "department": row["department"],
        "email": row["email"],
        "joined_on": row["joined_on"],
        "reports_to": row["reports_to"],
        "monthly_salary": row["monthly_salary"],
        "annual_salary": row["annual_salary"],
        "role": row["role"],
        "role_label": role_label["label"] if role_label else row["role"],
        "permissions": permissions,
    }


def record_event(
    database: sqlite3.Connection,
    employee_id: str | None,
    email: str,
    event: str,
) -> None:
    """Append one authentication audit event."""
    database.execute(
        "INSERT INTO auth_audit (employee_id, email, event) VALUES (?, ?, ?)",
        (employee_id, email, event),
    )
