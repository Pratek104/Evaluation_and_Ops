"""Streamlit session lifecycle and authentication helpers."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

import streamlit as st

from .. import auth

LOGGER = logging.getLogger(__name__)

_SESSION_KEYS = (
    "auth_user",
    "messages",
    "messages_access",
    "page",
    "login_email",
    "login_password",
)


def get_session_user() -> dict[str, Any] | None:
    """Reload the signed-in user so role/permission changes take effect."""
    stored = st.session_state.get("auth_user")
    if not stored:
        return None

    user = auth.get_user(stored["employee_id"])
    if user is None:
        st.session_state.auth_user = None
        st.session_state.messages = []
        st.session_state.pop("messages_access", None)
        return None

    st.session_state.auth_user = user
    st.session_state.setdefault("messages", [])
    access_signature = (user["role"], user["permissions"])
    if st.session_state.get("messages_access") != access_signature:
        st.session_state.messages = []
        st.session_state.messages_access = access_signature
    return user


def require_user() -> dict[str, Any]:
    """Return the signed-in user or stop the current page safely."""
    user = get_session_user()
    if user is None:
        st.warning("Your session has ended. Please sign in again.")
        st.stop()
    return user


def sign_out() -> None:
    """Record the logout, clear the session, and return to the login screen."""
    user = st.session_state.get("auth_user")
    if user:
        try:
            auth.record_logout(user)
        except sqlite3.Error as exc:
            # Logging out must still work if the audit write fails.
            LOGGER.warning("Could not record logout for %s: %s", user["email"], exc)
    for key in _SESSION_KEYS:
        st.session_state.pop(key, None)
    st.query_params.clear()
    st.rerun()
