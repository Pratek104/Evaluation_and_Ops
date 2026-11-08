"""Employee profile page."""

from __future__ import annotations

from typing import Any

import streamlit as st

from ... import auth
from ...constants import ROLE_COLORS, SCOPE_LABELS
from ...formatting import format_date, format_rupees


def render(user: dict[str, Any]) -> None:
    """Render the signed-in employee's profile and access summary."""
    st.title("My profile")
    st.caption("Your employee record from the XYZ directory.")

    with st.container(border=True):
        name_col, detail_col = st.columns([1.3, 1])
        with name_col:
            st.markdown(f"## {user['name']}")
            st.caption(user["job_title"])
            st.badge(
                user["role_label"],
                color=ROLE_COLORS.get(user["role"], "gray"),
            )
            st.markdown(f"**Work email:** {user['email']}")
        with detail_col:
            st.metric("Employee ID", user["employee_id"])
            st.metric("Department", user["department"])

    metric_cols = st.columns(4)
    metric_cols[0].metric("Joined", format_date(user["joined_on"]))
    metric_cols[1].metric("Reports to", user["reports_to"])
    metric_cols[2].metric("Monthly salary", format_rupees(user["monthly_salary"]))
    metric_cols[3].metric("Annual salary", format_rupees(user["annual_salary"]))

    st.subheader("My access")
    with st.container(border=True):
        st.markdown(f"**Handbook scope:** {SCOPE_LABELS[auth.handbook_scope(user)]}")
        for permission in user["permissions"]:
            st.caption(f"• {auth.permission_description(permission)}")
