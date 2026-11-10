"""Model Context Protocol server for the leave request workflow.

The server exposes the same service layer as the Streamlit pages over stdio.
Every tool except ``sign_in`` requires a session token returned by
``sign_in``; the token resolves to an employee whose role permissions are
checked by :mod:`xyz_portal.leave.service`.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import sys
from typing import Any

import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

from . import auth
from .config import configure_logging
from .leave import LeaveError
from .leave import service as leave_service

SERVER_NAME = "xyz-leave-workflow"
SERVER_VERSION = "1.0.0"

_SESSIONS: dict[str, dict[str, Any]] = {}


def _schema(
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


_TOKEN_PROPERTY = {
    "type": "string",
    "description": "Session token returned by sign_in.",
}

TOOLS: list[types.Tool] = [
    types.Tool(
        name="sign_in",
        description=(
            "Sign in with a work email and password. Returns a session token "
            "that the other leave tools require."
        ),
        inputSchema=_schema(
            {
                "email": {
                    "type": "string",
                    "description": "Work email, for example hr@xyzcompany.example.",
                },
                "password": {"type": "string", "description": "Account password."},
            },
            ["email", "password"],
        ),
    ),
    types.Tool(
        name="sign_out",
        description="Invalidate a leave session token.",
        inputSchema=_schema({"token": _TOKEN_PROPERTY}, ["token"]),
    ),
    types.Tool(
        name="whoami",
        description="Return the employee and permissions for a session token.",
        inputSchema=_schema({"token": _TOKEN_PROPERTY}, ["token"]),
    ),
    types.Tool(
        name="format_leave_letter",
        description=(
            "Translate a raw chat message into a formatted leave letter without "
            "saving a request. Use this to preview or clarify missing details."
        ),
        inputSchema=_schema(
            {
                "token": _TOKEN_PROPERTY,
                "message": {
                    "type": "string",
                    "description": (
                        "Raw chat, for example: 'I need casual leave from "
                        "10 Nov 2026 to 12 Nov 2026 because of a family function.'"
                    ),
                },
            },
            ["token", "message"],
        ),
    ),
    types.Tool(
        name="request_leave",
        description=(
            "Submit a structured leave request to the HR inbox. The service "
            "formats the letter and stores it for approval."
        ),
        inputSchema=_schema(
            {
                "token": _TOKEN_PROPERTY,
                "leave_type": {
                    "type": "string",
                    "description": (
                        "Casual Leave, Sick Leave, Privileged Leave, Unpaid Leave, "
                        "Maternity Leave, Paternity Leave, Bereavement Leave, or "
                        "Compensatory Leave."
                    ),
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date as ISO (YYYY-MM-DD) or natural text.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date as ISO (YYYY-MM-DD) or natural text.",
                },
                "reason": {
                    "type": "string",
                    "description": "Optional reason included in the letter.",
                },
            },
            ["token", "leave_type", "start_date", "end_date"],
        ),
    ),
    types.Tool(
        name="request_leave_from_chat",
        description=(
            "Parse a raw chat message and immediately submit the resulting leave "
            "request to the HR inbox."
        ),
        inputSchema=_schema(
            {
                "token": _TOKEN_PROPERTY,
                "message": {
                    "type": "string",
                    "description": "Free-form leave request chat message.",
                },
            },
            ["token", "message"],
        ),
    ),
    types.Tool(
        name="list_my_leave_requests",
        description="List the signed-in employee's leave requests.",
        inputSchema=_schema(
            {
                "token": _TOKEN_PROPERTY,
                "status": {
                    "type": "string",
                    "enum": ["all", "pending", "approved", "rejected", "cancelled"],
                    "description": "Optional status filter; defaults to all.",
                },
            },
            ["token"],
        ),
    ),
    types.Tool(
        name="get_leave_request",
        description=(
            "Return one leave request with its formatted letter. Employees can "
            "read their own requests; HR and the CEO can read any request."
        ),
        inputSchema=_schema(
            {
                "token": _TOKEN_PROPERTY,
                "request_id": {
                    "type": "integer",
                    "description": "Numeric request id (LR-0001 has id 1).",
                },
            },
            ["token", "request_id"],
        ),
    ),
    types.Tool(
        name="get_hr_inbox",
        description=(
            "Return the HR leave inbox with formatted letters and status counts. "
            "Requires the leave:approve permission."
        ),
        inputSchema=_schema(
            {
                "token": _TOKEN_PROPERTY,
                "status": {
                    "type": "string",
                    "enum": ["pending", "approved", "rejected", "cancelled", "all"],
                    "description": "Status filter; defaults to pending.",
                },
            },
            ["token"],
        ),
    ),
    types.Tool(
        name="decide_leave_request",
        description=(
            "Approve or reject a pending leave request. Requires leave:approve; "
            "self-approval is blocked."
        ),
        inputSchema=_schema(
            {
                "token": _TOKEN_PROPERTY,
                "request_id": {
                    "type": "integer",
                    "description": "Numeric request id (LR-0001 has id 1).",
                },
                "decision": {
                    "type": "string",
                    "enum": ["approve", "reject"],
                    "description": "Approval decision.",
                },
                "note": {
                    "type": "string",
                    "description": "Optional note shown to the employee.",
                },
            },
            ["token", "request_id", "decision"],
        ),
    ),
]


def _session(token: str) -> dict[str, Any]:
    session = _SESSIONS.get((token or "").strip())
    if session is None:
        raise LeaveError("Invalid or expired session token. Call sign_in first.")
    return session


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def sign_in(email: str, password: str) -> dict[str, Any]:
    """Authenticate an employee and return a new session token."""
    user = auth.authenticate(email, password)
    if user is None:
        raise LeaveError("Invalid work email or password.")
    token = secrets.token_urlsafe(24)
    _SESSIONS[token] = {
        "employee_id": user["employee_id"],
        "name": user["name"],
        "email": user["email"],
        "role": user["role"],
        "role_label": user["role_label"],
        "permissions": list(user["permissions"]),
    }
    return {
        "token": token,
        "employee": {
            "employee_id": user["employee_id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
            "role_label": user["role_label"],
            "department": user["department"],
        },
        "permissions": list(user["permissions"]),
    }


def dispatch(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute one tool call and return a JSON-serializable payload."""
    arguments = arguments or {}

    if name == "sign_in":
        return sign_in(
            str(arguments.get("email", "")),
            str(arguments.get("password", "")),
        )

    if name == "sign_out":
        token = str(arguments.get("token", "")).strip()
        if not _SESSIONS.pop(token, None):
            raise LeaveError("Invalid or expired session token.")
        return {"signed_out": True}

    token = str(arguments.get("token", ""))
    session = _session(token)
    employee_id = session["employee_id"]

    if name == "whoami":
        return {
            "employee": session,
        }

    if name == "format_leave_letter":
        return leave_service.format_leave_letter(
            employee_id, str(arguments.get("message", ""))
        )

    if name == "request_leave":
        record = leave_service.submit_leave_request(
            employee_id,
            str(arguments.get("leave_type", "")),
            str(arguments.get("start_date", "")),
            str(arguments.get("end_date", "")),
            str(arguments.get("reason", "")),
        )
        return {
            "request": record,
            "message": f"Request {record['reference']} was sent to the HR inbox.",
        }

    if name == "request_leave_from_chat":
        record = leave_service.submit_leave_from_chat(
            employee_id, str(arguments.get("message", ""))
        )
        return {
            "request": record,
            "message": f"Request {record['reference']} was sent to the HR inbox.",
        }

    if name == "list_my_leave_requests":
        status = str(arguments.get("status", "all") or "all")
        return {
            "status": status,
            "requests": leave_service.list_leave_requests(employee_id, status=status),
        }

    if name == "get_leave_request":
        request_id = int(arguments.get("request_id", 0))
        fetched = leave_service.get_leave_request(employee_id, request_id)
        if fetched is None:
            raise LeaveError(f"Leave request {request_id} was not found.")
        return {"request": fetched}

    if name == "get_hr_inbox":
        status = str(arguments.get("status", "pending") or "pending")
        return leave_service.get_hr_inbox(employee_id, status=status)

    if name == "decide_leave_request":
        record = leave_service.decide_leave_request(
            employee_id,
            int(arguments.get("request_id", 0)),
            str(arguments.get("decision", "")),
            str(arguments.get("note", "")),
        )
        return {
            "request": record,
            "message": (f"Request {record['reference']} was {record['status']}."),
        }

    raise LeaveError(f"Unknown tool: {name}")


def build_server() -> Server:
    """Create an MCP server with the leave workflow tools registered."""
    server = Server(SERVER_NAME)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, Any]
    ) -> list[types.TextContent]:
        return [types.TextContent(type="text", text=_json(dispatch(name, arguments)))]

    return server


async def serve() -> None:
    """Run the MCP server over stdio until the client disconnects."""
    auth.ensure_database()
    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name=SERVER_NAME,
                server_version=SERVER_VERSION,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def _configure_stdio() -> None:
    """Force UTF-8 on stdio so non-ASCII letters survive on Windows."""
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def main() -> None:
    """Console entry point for the leave workflow MCP server."""
    _configure_stdio()
    configure_logging()
    asyncio.run(serve())


if __name__ == "__main__":
    main()
