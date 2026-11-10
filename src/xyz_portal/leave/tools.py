"""Tool definitions and dispatch for the chat-based leave workflow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import auth
from .parsing import LEAVE_TYPE_LABELS
from .service import (
    LeaveError,
    decide_leave_request,
    get_hr_inbox,
    get_leave_request,
    list_leave_requests,
    submit_leave_request,
)

TOOL_LABELS = {
    "submit_leave_request": "Sending the leave request to HR",
    "list_my_leave_requests": "Checking your leave requests",
    "get_leave_request": "Loading the leave request",
    "get_hr_inbox": "Opening the HR leave inbox",
    "decide_leave_request": "Recording the HR decision",
}

_LEAVE_INTENT_WORDS = (
    "leave",
    "vacation",
    "time off",
    "day off",
    "sick",
    "absence",
    "approve",
    "reject",
    "inbox",
    "pending request",
)


def is_leave_intent(text: str) -> bool:
    """Return whether a chat message is likely about the leave workflow."""
    lowered = (text or "").lower()
    return any(word in lowered for word in _LEAVE_INTENT_WORDS)


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


def chat_tools(user: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the OpenAI-compatible tools available to a signed-in user."""
    tools: dict[str, dict[str, Any]] = {}

    if auth.has_permission(user, "leave:request"):
        tools["submit_leave_request"] = _tool(
            "submit_leave_request",
            (
                "Submit a leave request to the HR inbox. Only call this after the "
                "employee has confirmed the leave type, start date, end date, and "
                "reason. Returns the reference number and the formatted letter."
            ),
            {
                "leave_type": {
                    "type": "string",
                    "enum": list(LEAVE_TYPE_LABELS),
                    "description": "The leave type the employee confirmed.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in ISO format (YYYY-MM-DD).",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in ISO format (YYYY-MM-DD).",
                },
                "reason": {
                    "type": "string",
                    "description": "The reason the employee gave for the leave.",
                },
            },
            ["leave_type", "start_date", "end_date", "reason"],
        )

    if auth.has_permission(user, "leave:read:self"):
        tools["list_my_leave_requests"] = _tool(
            "list_my_leave_requests",
            "List the signed-in employee's own leave requests and their status.",
            {
                "status": {
                    "type": "string",
                    "enum": ["all", "pending", "approved", "rejected", "cancelled"],
                    "description": "Optional status filter; defaults to all.",
                }
            },
            [],
        )

    if auth.has_permission(user, "leave:read:self") or auth.has_permission(
        user, "leave:read:all"
    ):
        tools["get_leave_request"] = _tool(
            "get_leave_request",
            (
                "Read one leave request with its formatted letter. Employees can "
                "read their own requests; HR and the CEO can read any request."
            ),
            {
                "request_id": {
                    "type": "integer",
                    "description": "Numeric request id (LR-0001 has id 1).",
                }
            },
            ["request_id"],
        )

    if auth.has_permission(user, "leave:approve"):
        tools["get_hr_inbox"] = _tool(
            "get_hr_inbox",
            (
                "Return the HR leave inbox with formatted letters and status "
                "counts. Requires an approver role."
            ),
            {
                "status": {
                    "type": "string",
                    "enum": [
                        "pending",
                        "approved",
                        "rejected",
                        "cancelled",
                        "all",
                    ],
                    "description": "Status filter; defaults to pending.",
                }
            },
            [],
        )
        tools["decide_leave_request"] = _tool(
            "decide_leave_request",
            (
                "Approve or reject a pending leave request. Confirm the decision "
                "with the approver first. Self-approval is blocked."
            ),
            {
                "request_id": {
                    "type": "integer",
                    "description": "Numeric request id (LR-0001 has id 1).",
                },
                "decision": {
                    "type": "string",
                    "enum": ["approve", "reject"],
                    "description": "The confirmed decision.",
                },
                "note": {
                    "type": "string",
                    "description": "Optional note shown to the employee.",
                },
            },
            ["request_id", "decision"],
        )

    return list(tools.values())


def _load_arguments(arguments: dict[str, Any] | str | None) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if not arguments:
        return {}
    parsed = json.loads(arguments)
    if not isinstance(parsed, dict):
        raise ValueError("Tool arguments must be a JSON object.")
    return parsed


def execute_chat_tool(
    user: dict[str, Any],
    name: str,
    arguments: dict[str, Any] | str | None,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Execute one chat tool call and return a JSON-serializable result."""
    employee_id = user["employee_id"]

    try:
        values = _load_arguments(arguments)
        if name == "submit_leave_request":
            record = submit_leave_request(
                employee_id,
                str(values.get("leave_type", "")),
                str(values.get("start_date", "")),
                str(values.get("end_date", "")),
                str(values.get("reason", "")),
                db_path=db_path,
            )
            return {
                "ok": True,
                "message": (f"Request {record['reference']} was sent to the HR inbox."),
                "request": record,
            }

        if name == "list_my_leave_requests":
            status = str(values.get("status", "all") or "all")
            records = list_leave_requests(employee_id, status=status, db_path=db_path)
            return {
                "ok": True,
                "status": status,
                "count": len(records),
                "requests": records,
            }

        if name == "get_leave_request":
            request_id = int(values.get("request_id", 0))
            fetched = get_leave_request(employee_id, request_id, db_path=db_path)
            if fetched is None:
                return {
                    "ok": False,
                    "error": f"Leave request {request_id} was not found.",
                }
            return {"ok": True, "request": fetched}

        if name == "get_hr_inbox":
            status = str(values.get("status", "pending") or "pending")
            inbox = get_hr_inbox(employee_id, status=status, db_path=db_path)
            return {"ok": True, **inbox}

        if name == "decide_leave_request":
            record = decide_leave_request(
                employee_id,
                int(values.get("request_id", 0)),
                str(values.get("decision", "")),
                str(values.get("note", "")),
                db_path=db_path,
            )
            return {
                "ok": True,
                "message": (f"Request {record['reference']} was {record['status']}."),
                "request": record,
            }

        return {"ok": False, "error": f"Unknown leave tool: {name}"}
    except (LeaveError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc)}
