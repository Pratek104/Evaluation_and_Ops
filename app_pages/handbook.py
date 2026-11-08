"""Streamlit page: handbook assistant."""

from xyz_portal.ui.pages.handbook import render
from xyz_portal.ui.session import require_user

render(require_user())
