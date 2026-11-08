"""Application bootstrap shared by the Streamlit entrypoints."""

from __future__ import annotations

import sqlite3

import streamlit as st

from .. import auth
from ..config import configure_logging
from .login import render_login
from .navigation import build_pages, render_account_sidebar
from .session import get_session_user


def run() -> None:
    """Configure and run one Streamlit application render."""
    st.set_page_config(
        page_title="XYZ employee portal",
        page_icon=":material/menu_book:",
        layout="centered",
    )
    configure_logging()

    try:
        auth.ensure_database()
    except (OSError, sqlite3.Error) as exc:
        st.error(f"Could not initialize the employee database: {exc}")
        st.stop()

    user = get_session_user()
    if user is None:
        render_login()
        return

    navigation = st.navigation(build_pages(user), expanded=True)
    render_account_sidebar(user)
    navigation.run()
