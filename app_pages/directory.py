"""Streamlit page: people directory."""

from xyz_portal.ui.pages.directory import render
from xyz_portal.ui.session import require_user

render(require_user())
