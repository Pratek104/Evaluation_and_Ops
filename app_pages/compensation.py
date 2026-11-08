"""Streamlit page: compensation."""

from xyz_portal.ui.pages.compensation import render
from xyz_portal.ui.session import require_user

render(require_user())
