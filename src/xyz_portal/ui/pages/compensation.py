"""Company compensation page."""

from __future__ import annotations

from typing import Any

import streamlit as st

from ... import auth
from ...formatting import format_rupees


def render(user: dict[str, Any]) -> None:
    """Render compensation rows visible to the signed-in user."""
    if not auth.has_permission(user, "salary:read:all"):
        st.error("Compensation data is not available for your role.")
        return

    st.title("Compensation")
    st.caption("Monthly and annual gross salary for employees visible to your role.")

    employees = auth.compensation_employees(user)
    if not employees:
        st.warning("Compensation data is not available for your role.")
        return

    total_monthly = sum(employee["monthly_salary"] for employee in employees)
    total_annual = sum(employee["annual_salary"] for employee in employees)
    average_monthly = total_monthly / len(employees)

    metric_cols = st.columns(3)
    metric_cols[0].metric("Monthly payroll", format_rupees(total_monthly))
    metric_cols[1].metric("Annual payroll", format_rupees(total_annual))
    metric_cols[2].metric("Average monthly", format_rupees(average_monthly))

    rows = [
        {
            "ID": employee["employee_id"],
            "Name": employee["name"],
            "Department": employee["department"],
            "Monthly salary (Rs.)": employee["monthly_salary"],
            "Annual salary (Rs.)": employee["annual_salary"],
        }
        for employee in employees
    ]
    st.dataframe(
        rows,
        hide_index=True,
        width="stretch",
        column_config={
            "Monthly salary (Rs.)": st.column_config.NumberColumn(format="%d"),
            "Annual salary (Rs.)": st.column_config.NumberColumn(format="%d"),
        },
    )

    st.caption(
        "Salary figures are seeded from Appendix C of the handbook. Employees "
        "can see only their own compensation on their profile."
    )
