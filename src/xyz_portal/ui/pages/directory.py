"""Role-scoped people directory page."""

from __future__ import annotations

import csv
import io
from typing import Any

import streamlit as st

from ... import auth
from ...formatting import format_date


def render(user: dict[str, Any]) -> None:
    """Render the employees visible to the signed-in user."""
    if not (
        auth.has_permission(user, "directory:read:all")
        or auth.has_permission(user, "directory:read:department")
    ):
        st.error("The people directory is not available for your role.")
        return

    employees = auth.visible_employees(user)
    if auth.has_permission(user, "directory:read:all"):
        st.title("People directory")
        st.caption("All active employees in the XYZ directory.")
    else:
        st.title(f"{user['department']} team")
        st.caption("The employees in your department.")

    if not employees:
        st.info("No employees are visible for your role.")
        return

    departments = sorted({employee["department"] for employee in employees})
    metric_cols = st.columns(3)
    metric_cols[0].metric("People visible", len(employees))
    metric_cols[1].metric("Departments", len(departments))
    metric_cols[2].metric("Your role", user["role_label"])

    filter_cols = st.columns([2, 1])
    search = filter_cols[0].text_input(
        "Search",
        placeholder="Name, employee ID, email, or job title",
        key="directory_search",
    )
    department = filter_cols[1].selectbox(
        "Department",
        options=["All departments", *departments],
        key="directory_department",
    )

    query = (search or "").strip().casefold()
    filtered = []
    for employee in employees:
        haystack = " ".join(
            str(employee[key])
            for key in ("employee_id", "name", "job_title", "department", "email")
        ).casefold()
        if query and query not in haystack:
            continue
        if department != "All departments" and employee["department"] != department:
            continue
        filtered.append(employee)

    rows = [
        {
            "ID": employee["employee_id"],
            "Name": employee["name"],
            "Job title": employee["job_title"],
            "Department": employee["department"],
            "Work email": employee["email"],
            "Joined": format_date(employee["joined_on"]),
            "Reports to": employee["reports_to"],
            "Access role": employee["role"],
        }
        for employee in filtered
    ]

    st.caption(f"Showing {len(rows)} of {len(employees)} visible employees.")
    st.dataframe(rows, hide_index=True, width="stretch")

    if rows:
        csv_buffer = io.StringIO()
        writer = csv.DictWriter(csv_buffer, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        st.download_button(
            "Download visible directory as CSV",
            data=csv_buffer.getvalue().encode("utf-8"),
            file_name="xyz_directory.csv",
            mime="text/csv",
            icon=":material/download:",
        )
