"""Page registry and sidebar account controls."""

from __future__ import annotations

from typing import Any

import streamlit as st

from .. import auth
from ..config import PROJECT_ROOT
from ..constants import ROLE_COLORS, SCOPE_LABELS
from .session import sign_out

PAGES_DIR = PROJECT_ROOT / "app_pages"


def build_pages(user: dict[str, Any]) -> list[st.Page]:
    """Return the pages available to the signed-in user."""
    pages = [
        st.Page(
            PAGES_DIR / "handbook.py",
            title="Handbook assistant",
            icon=":material/menu_book:",
            url_path="handbook",
            default=True,
            help=(
                "Ask questions about company policy and get answers grounded in "
                "the handbook sections available to your role."
            ),
        ),
        st.Page(
            PAGES_DIR / "profile.py",
            title="My profile",
            icon=":material/person:",
            url_path="profile",
            help=(
                "View your employee record, reporting line, compensation, and the "
                "permissions granted to your role."
            ),
        ),
    ]
    if auth.has_permission(user, "directory:read:all") or auth.has_permission(
        user, "directory:read:department"
    ):
        pages.append(
            st.Page(
                PAGES_DIR / "directory.py",
                title="People directory",
                icon=":material/groups:",
                url_path="directory",
                help=(
                    "Browse the employees your role can see, search by name or "
                    "department, and download the visible rows as CSV."
                ),
            )
        )
    if auth.has_permission(user, "salary:read:all"):
        pages.append(
            st.Page(
                PAGES_DIR / "compensation.py",
                title="Compensation",
                icon=":material/payments:",
                url_path="compensation",
                help=(
                    "Review monthly and annual payroll totals and the salary "
                    "records visible to your role."
                ),
            )
        )
    if auth.has_permission(user, "roles:view"):
        pages.append(
            st.Page(
                PAGES_DIR / "access_control.py",
                title="Access control",
                icon=":material/shield:",
                url_path="access-control",
                help=(
                    "Inspect the role and permission matrix, handbook retrieval "
                    "scopes, and recent authentication activity."
                ),
            )
        )
    return pages


def render_account_sidebar(user: dict[str, Any]) -> None:
    """Render the signed-in employee card and sign-out control."""
    with st.sidebar:
        with st.container(border=True):
            st.markdown(f"**{user['name']}**")
            st.caption(f"{user['employee_id']} · {user['department']}")
            st.badge(
                user["role_label"],
                color=ROLE_COLORS.get(user["role"], "gray"),
            )

        if st.button(
            "Sign out",
            icon=":material/logout:",
            width="stretch",
        ):
            sign_out()

        with st.expander("My access", icon=":material/shield:"):
            st.caption(f"Handbook scope: **{SCOPE_LABELS[auth.handbook_scope(user)]}**")
            for permission in user["permissions"]:
                st.caption(f"• {auth.permission_description(permission)}")
