"""Streamlit page: access control."""

from xyz_portal.ui.pages.access_control import render
from xyz_portal.ui.session import require_user

render(require_user())
