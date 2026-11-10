"""Leave requests, formatted letters, and the HR approval workflow."""

from __future__ import annotations

from .letters import render_leave_letter
from .parsing import (
    LEAVE_TYPE_LABELS,
    LEAVE_TYPES,
    ParsedLeave,
    count_working_days,
    parse_leave_chat,
    parse_single_date,
)
from .service import (
    LEAVE_STATUSES,
    LeaveError,
    decide_leave_request,
    format_leave_letter,
    get_hr_inbox,
    get_leave_request,
    leave_summary,
    list_leave_requests,
    submit_leave_from_chat,
    submit_leave_request,
)
from .tools import (
    TOOL_LABELS,
    chat_tools,
    execute_chat_tool,
    is_leave_intent,
)

__all__ = [
    "LEAVE_STATUSES",
    "LEAVE_TYPES",
    "LEAVE_TYPE_LABELS",
    "TOOL_LABELS",
    "LeaveError",
    "ParsedLeave",
    "chat_tools",
    "count_working_days",
    "decide_leave_request",
    "execute_chat_tool",
    "format_leave_letter",
    "get_hr_inbox",
    "get_leave_request",
    "is_leave_intent",
    "leave_summary",
    "list_leave_requests",
    "parse_leave_chat",
    "parse_single_date",
    "render_leave_letter",
    "submit_leave_from_chat",
    "submit_leave_request",
]
