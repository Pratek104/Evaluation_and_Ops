"""Render formal leave letters from structured request data."""

from __future__ import annotations

from datetime import date
from typing import Any

COMPANY_NAME = "XYZ Company"
HR_DEPARTMENT = "Human Resources Department"


def format_letter_date(value: date) -> str:
    """Format a date as it appears in the letter header."""
    return value.strftime("%d %B %Y")


def format_leave_date(value: date) -> str:
    """Format a date with its weekday for the request body."""
    return value.strftime("%A, %d %B %Y")


def render_leave_letter(
    *,
    reference: str,
    employee: dict[str, Any],
    leave_type: str,
    start_date: date,
    end_date: date,
    days: int,
    reason: str,
    hr_name: str,
    submitted_on: date | None = None,
) -> str:
    """Build the formatted letter that HR receives in the inbox."""
    submitted_on = submitted_on or date.today()
    reason_line = reason.strip() or "Not provided."
    day_label = "working day" if days == 1 else "working days"

    return "\n".join(
        [
            COMPANY_NAME,
            HR_DEPARTMENT,
            "",
            f"Ref: {reference}",
            f"Date: {format_letter_date(submitted_on)}",
            "",
            f"Subject: Leave Request — {leave_type}",
            "",
            f"Dear {hr_name},",
            "",
            (
                f"I am writing to formally request {leave_type} from "
                f"{format_leave_date(start_date)} to "
                f"{format_leave_date(end_date)}, inclusive "
                f"({days} {day_label})."
            ),
            "",
            f"Reason: {reason_line}",
            "",
            (
                "I request your approval for this leave. I will ensure that my "
                "responsibilities are handed over before my absence."
            ),
            "",
            "Yours sincerely,",
            "",
            str(employee["name"]),
            f"{employee['job_title']}, {employee['department']}",
            f"Employee ID: {employee['employee_id']}",
            str(employee["email"]),
        ]
    )
