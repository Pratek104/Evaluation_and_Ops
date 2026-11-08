"""Streamlit page: employee profile."""

from xyz_portal.ui.pages.profile import render
from xyz_portal.ui.session import require_user

render(require_user())
