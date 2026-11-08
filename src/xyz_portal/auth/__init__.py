"""Authentication, authorization, and employee data access."""

from __future__ import annotations

from ..formatting import format_timestamp
from .constants import EMPLOYEES, PERMISSIONS, ROLE_PERMISSIONS, ROLES
from .database import ensure_database
from .passwords import hash_password, verify_password
from .service import (
    authenticate,
    compensation_employees,
    get_user,
    handbook_scope,
    has_permission,
    permission_description,
    recent_auth_events,
    record_logout,
    role_matrix,
    visible_employees,
)

__all__ = [
    "EMPLOYEES",
    "PERMISSIONS",
    "ROLES",
    "ROLE_PERMISSIONS",
    "authenticate",
    "compensation_employees",
    "ensure_database",
    "format_timestamp",
    "get_user",
    "handbook_scope",
    "has_permission",
    "hash_password",
    "permission_description",
    "recent_auth_events",
    "record_logout",
    "role_matrix",
    "verify_password",
    "visible_employees",
]
