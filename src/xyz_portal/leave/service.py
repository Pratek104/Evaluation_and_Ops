"""Leave requests, formatted letters, and the HR approval workflow."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from .. import auth
from ..auth.database import connection
from .letters import render_leave_letter
from .parsing import (
    LEAVE_TYPE_LABELS,
    LEAVE_TYPES,
    count_working_days,
    parse_leave_chat,
    parse_single_date,
)

LEAVE_STATUSES = ("pending", "approved", "rejected", "cancelled")
_DECISION_MAP = {
    "approve": "approved",
    "approved": "approved",
    "accept": "approved",
    "accepted": "approved",
    "reject": "rejected",
    "rejected": "rejected",
    "deny": "rejected",
    "denied": "rejected",
}

_REQUEST_SELECT = """
    SELECT lr.id, lr.employee_id, lr.leave_type, lr.start_date, lr.end_date,
           lr.days, lr.reason, lr.raw_chat, lr.letter_text, lr.status,
           lr.created_at, lr.decided_by, lr.decided_at, lr.decision_note,
           e.name AS employee_name, e.job_title, e.department, e.email,
           d.name AS decided_by_name
    FROM leave_requests lr
    JOIN employees e ON e.employee_id = lr.employee_id
    LEFT JOIN employees d ON d.employee_id = lr.decided_by
"""


class LeaveError(ValueError):
    """A user-facing leave workflow error."""


def _require_user(employee_id: str, db_path: str | Path | None) -> dict[str, Any]:
    user = auth.get_user(employee_id, db_path=db_path)
    if user is None:
        raise LeaveError(f"Unknown or inactive employee: {employee_id}")
    return user


def _canonical_leave_type(value: str) -> str:
    normalized = " ".join((value or "").strip().lower().split())
    if normalized in LEAVE_TYPES:
        return LEAVE_TYPES[normalized]
    for label in LEAVE_TYPE_LABELS:
        if normalized == label.lower():
            return label
    raise LeaveError("Unknown leave type. Use one of: " + ", ".join(LEAVE_TYPE_LABELS))


def _hr_contact(database: Any) -> str:
    row = database.execute(
        "SELECT name FROM employees WHERE role = 'HR' AND is_active = 1 "
        "ORDER BY employee_id LIMIT 1"
    ).fetchone()
    return str(row["name"]) if row else "Human Resources Manager"


def _record_event(
    database: Any,
    request_id: int,
    actor_id: str,
    event: str,
    detail: str = "",
) -> None:
    database.execute(
        "INSERT INTO leave_events (request_id, actor_id, event, detail) "
        "VALUES (?, ?, ?, ?)",
        (request_id, actor_id, event, detail),
    )


def _row_to_dict(row: Any) -> dict[str, Any]:
    record = dict(row)
    record["reference"] = f"LR-{int(record['id']):04d}"
    return record


def submit_leave_request(
    employee_id: str,
    leave_type: str,
    start_date: str | date,
    end_date: str | date,
    reason: str = "",
    raw_chat: str = "",
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Create a pending leave request and store its formatted letter."""
    user = _require_user(employee_id, db_path)
    if not auth.has_permission(user, "leave:request"):
        raise LeaveError("Your role cannot submit leave requests.")

    label = _canonical_leave_type(leave_type)
    try:
        start = parse_single_date(start_date)
        end = parse_single_date(end_date)
    except ValueError as exc:
        raise LeaveError(str(exc)) from exc
    if end < start:
        raise LeaveError("The end date cannot be before the start date.")
    days = count_working_days(start, end)
    if days <= 0:
        raise LeaveError("The selected range contains no working days.")
    reason = (reason or "").strip()[:1000]

    with connection(db_path) as database:
        hr_name = _hr_contact(database)
        cursor = database.execute(
            """
            INSERT INTO leave_requests (
                employee_id, leave_type, start_date, end_date, days, reason,
                raw_chat, letter_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                employee_id,
                label,
                start.isoformat(),
                end.isoformat(),
                days,
                reason,
                (raw_chat or "").strip(),
                "",
            ),
        )
        request_id = int(cursor.lastrowid or 0)
        if request_id <= 0:  # pragma: no cover - SQLite always returns a row id
            raise LeaveError("The leave request could not be created.")
        reference = f"LR-{request_id:04d}"
        letter = render_leave_letter(
            reference=reference,
            employee=user,
            leave_type=label,
            start_date=start,
            end_date=end,
            days=days,
            reason=reason,
            hr_name=hr_name,
        )
        database.execute(
            "UPDATE leave_requests SET letter_text = ? WHERE id = ?",
            (letter, request_id),
        )
        _record_event(
            database,
            request_id,
            employee_id,
            "submitted",
            f"{label} {start.isoformat()} to {end.isoformat()} ({days} days)",
        )

    record = get_leave_request(employee_id, request_id, db_path=db_path)
    if record is None:  # pragma: no cover - the insert above guarantees a row
        raise LeaveError("The leave request could not be reloaded.")
    return record


def submit_leave_from_chat(
    employee_id: str,
    raw_chat: str,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Parse a free-form chat message, then submit the resulting request."""
    _require_user(employee_id, db_path)
    parsed = parse_leave_chat(raw_chat)
    if parsed.missing:
        raise LeaveError(
            "Could not determine "
            + ", ".join(parsed.missing)
            + ". Include a start and end date, for example: "
            "'I need casual leave from 10 Nov 2026 to 12 Nov 2026 because ...'."
        )
    if parsed.start_date is None or parsed.end_date is None:
        raise LeaveError("Both a start date and an end date are required.")
    return submit_leave_request(
        employee_id,
        parsed.leave_type,
        parsed.start_date,
        parsed.end_date,
        parsed.reason,
        raw_chat,
        db_path=db_path,
    )


def format_leave_letter(
    employee_id: str,
    raw_chat: str,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Turn a raw chat message into a letter without saving a request."""
    user = _require_user(employee_id, db_path)
    if not auth.has_permission(user, "leave:request"):
        raise LeaveError("Your role cannot submit leave requests.")

    parsed = parse_leave_chat(raw_chat)
    if parsed.missing or parsed.start_date is None or parsed.end_date is None:
        return {
            "ok": False,
            "status": "needs_clarification",
            "missing": list(parsed.missing),
            "assumptions": list(parsed.assumptions),
            "message": (
                "I need a start and end date to format the letter. Try: "
                "'I need casual leave from 10 Nov 2026 to 12 Nov 2026 "
                "because of a family function.'"
            ),
        }

    days = count_working_days(parsed.start_date, parsed.end_date)
    with connection(db_path) as database:
        hr_name = _hr_contact(database)

    letter = render_leave_letter(
        reference="PREVIEW",
        employee=user,
        leave_type=parsed.leave_type,
        start_date=parsed.start_date,
        end_date=parsed.end_date,
        days=days,
        reason=parsed.reason,
        hr_name=hr_name,
    )
    return {
        "ok": True,
        "status": "preview",
        "parsed": {
            "leave_type": parsed.leave_type,
            "start_date": parsed.start_date.isoformat(),
            "end_date": parsed.end_date.isoformat(),
            "days": days,
            "reason": parsed.reason,
        },
        "assumptions": list(parsed.assumptions),
        "letter": letter,
    }


def get_leave_request(
    employee_id: str,
    request_id: int,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Return one request if the caller owns it or can read all requests."""
    user = _require_user(employee_id, db_path)
    with connection(db_path) as database:
        row = database.execute(
            _REQUEST_SELECT + " WHERE lr.id = ?", (int(request_id),)
        ).fetchone()
        if row is None:
            return None
        record = _row_to_dict(row)

    if record["employee_id"] != employee_id and not auth.has_permission(
        user, "leave:read:all"
    ):
        raise LeaveError("You can only view your own leave requests.")
    return record


def list_leave_requests(
    employee_id: str,
    status: str | None = "all",
    *,
    all_requests: bool = False,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """List leave requests visible to the caller."""
    user = _require_user(employee_id, db_path)
    clauses: list[str] = []
    parameters: list[Any] = []

    if all_requests:
        if not auth.has_permission(user, "leave:read:all"):
            raise LeaveError("Your role cannot view all leave requests.")
    else:
        if not auth.has_permission(user, "leave:read:self"):
            raise LeaveError("Your role cannot view leave requests.")
        clauses.append("lr.employee_id = ?")
        parameters.append(employee_id)

    if status and status != "all":
        if status not in LEAVE_STATUSES:
            raise LeaveError(f"Unknown leave status: {status}")
        clauses.append("lr.status = ?")
        parameters.append(status)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with connection(db_path) as database:
        rows = database.execute(
            _REQUEST_SELECT + where + " ORDER BY lr.created_at DESC, lr.id DESC",
            parameters,
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_hr_inbox(
    approver_id: str,
    status: str = "pending",
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return the leave inbox and status counts for an approver."""
    user = _require_user(approver_id, db_path)
    if not auth.has_permission(user, "leave:approve"):
        raise LeaveError("Your role cannot access the HR leave inbox.")

    records = list_leave_requests(
        approver_id, status=status, all_requests=True, db_path=db_path
    )
    all_records = list_leave_requests(
        approver_id, status="all", all_requests=True, db_path=db_path
    )
    counts = dict.fromkeys(LEAVE_STATUSES, 0)
    for record in all_records:
        counts[record["status"]] = counts.get(record["status"], 0) + 1

    return {
        "status": status,
        "count": len(records),
        "counts": counts,
        "total": len(all_records),
        "requests": records,
    }


def decide_leave_request(
    approver_id: str,
    request_id: int,
    decision: str,
    note: str = "",
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Approve or reject a pending request, with self-approval blocked."""
    approver = _require_user(approver_id, db_path)
    if not auth.has_permission(approver, "leave:approve"):
        raise LeaveError("Your role cannot approve or reject leave requests.")

    status = _DECISION_MAP.get((decision or "").strip().lower())
    if status is None:
        raise LeaveError("Decision must be 'approve' or 'reject'.")

    with connection(db_path) as database:
        row = database.execute(
            "SELECT id, employee_id, status FROM leave_requests WHERE id = ?",
            (int(request_id),),
        ).fetchone()
        if row is None:
            raise LeaveError(f"Leave request {request_id} was not found.")
        if row["employee_id"] == approver_id:
            raise LeaveError("You cannot approve or reject your own leave request.")
        if row["status"] != "pending":
            raise LeaveError(f"Leave request {request_id} is already {row['status']}.")

        database.execute(
            """
            UPDATE leave_requests
            SET status = ?, decided_by = ?, decided_at = CURRENT_TIMESTAMP,
                decision_note = ?
            WHERE id = ?
            """,
            (
                status,
                approver_id,
                (note or "").strip()[:1000],
                int(request_id),
            ),
        )
        _record_event(
            database,
            int(request_id),
            approver_id,
            status,
            (note or "").strip(),
        )

    record = get_leave_request(approver_id, request_id, db_path=db_path)
    if record is None:  # pragma: no cover - the update above guarantees a row
        raise LeaveError("The leave request could not be reloaded.")
    return record


def leave_summary(
    employee_id: str,
    *,
    db_path: str | Path | None = None,
) -> dict[str, int]:
    """Return status counts for the caller's own requests."""
    records = list_leave_requests(employee_id, status="all", db_path=db_path)
    counts = dict.fromkeys(LEAVE_STATUSES, 0)
    for record in records:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    counts["total"] = len(records)
    return counts
