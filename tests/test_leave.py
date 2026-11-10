"""Leave parsing, letter formatting, approval workflow, and MCP tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from xyz_portal import auth, mcp_server
from xyz_portal.leave import LeaveError, parsing
from xyz_portal.leave import service as leave_service
from xyz_portal.leave.tools import (
    chat_tools,
    execute_chat_tool,
    is_leave_intent,
)

EMPLOYEE = "XYZ011"
HR = "XYZ004"
CEO = "XYZ001"


def _submit(
    db_path: Path,
    employee_id: str = EMPLOYEE,
    leave_type: str = "Sick Leave",
    start: str = "2026-11-10",
    end: str = "2026-11-12",
    reason: str = "Fever",
) -> dict:
    return leave_service.submit_leave_request(
        employee_id, leave_type, start, end, reason, db_path=db_path
    )


def test_parse_chat_extracts_type_dates_and_reason() -> None:
    parsed = parsing.parse_leave_chat(
        "I need sick leave from 10 Nov 2026 to 12 Nov 2026 because I have a fever."
    )
    assert parsed.leave_type == "Sick Leave"
    assert parsed.start_date == date(2026, 11, 10)
    assert parsed.end_date == date(2026, 11, 12)
    assert parsed.days == 3
    assert parsed.reason == "I have a fever"
    assert parsed.missing == ()


def test_parse_chat_supports_iso_and_defaults_leave_type() -> None:
    parsed = parsing.parse_leave_chat(
        "Please approve leave from 2026-12-24 to 2026-12-26 due to travel."
    )
    assert parsed.leave_type == "Casual Leave"
    assert parsed.start_date == date(2026, 12, 24)
    assert parsed.end_date == date(2026, 12, 26)
    assert parsed.reason == "travel"
    assert parsed.assumptions


def test_parse_chat_reports_missing_dates() -> None:
    parsed = parsing.parse_leave_chat("I need some time off next week.")
    assert parsed.start_date is None
    assert parsed.end_date is None
    assert "start_date" in parsed.missing
    assert "end_date" in parsed.missing


def test_working_days_skip_sundays_and_first_third_saturdays() -> None:
    # November 2026 has five Sundays and first/third Saturdays on the 7th and 21st.
    assert parsing.count_working_days(date(2026, 11, 1), date(2026, 11, 30)) == 23
    assert parsing.count_working_days(date(2026, 11, 7), date(2026, 11, 7)) == 0
    assert parsing.count_working_days(date(2026, 11, 14), date(2026, 11, 14)) == 1
    with pytest.raises(ValueError):
        parsing.count_working_days(date(2026, 11, 12), date(2026, 11, 10))


def test_format_letter_preview_does_not_save(db_path: Path) -> None:
    preview = leave_service.format_leave_letter(
        EMPLOYEE,
        "I need casual leave from 10 Nov 2026 to 12 Nov 2026 because of a "
        "family function.",
        db_path=db_path,
    )
    assert preview["ok"] is True
    assert preview["parsed"]["days"] == 3
    assert "Ref: PREVIEW" in preview["letter"]
    assert "Karan Joshi" in preview["letter"]
    assert "Casual Leave" in preview["letter"]
    assert leave_service.list_leave_requests(EMPLOYEE, db_path=db_path) == []


def test_format_letter_needs_clarification(db_path: Path) -> None:
    preview = leave_service.format_leave_letter(
        EMPLOYEE, "I need leave soon.", db_path=db_path
    )
    assert preview["ok"] is False
    assert preview["status"] == "needs_clarification"
    assert "start_date" in preview["missing"]


def test_submit_creates_pending_request_and_hr_inbox_entry(db_path: Path) -> None:
    record = _submit(db_path)
    assert record["reference"] == "LR-0001"
    assert record["status"] == "pending"
    assert record["days"] == 3
    assert "Sick Leave" in record["letter_text"]
    assert "Karan Joshi" in record["letter_text"]
    assert "3 working days" in record["letter_text"]

    inbox = leave_service.get_hr_inbox(HR, db_path=db_path)
    assert inbox["count"] == 1
    assert inbox["counts"]["pending"] == 1
    assert inbox["requests"][0]["reference"] == "LR-0001"


def test_submit_from_chat_uses_parsed_fields(db_path: Path) -> None:
    record = leave_service.submit_leave_from_chat(
        EMPLOYEE,
        "I need sick leave from 10 Nov 2026 to 12 Nov 2026 because I have a fever.",
        db_path=db_path,
    )
    assert record["leave_type"] == "Sick Leave"
    assert record["reason"] == "I have a fever"
    assert record["raw_chat"].startswith("I need sick leave")


def test_invalid_dates_and_types_are_rejected(db_path: Path) -> None:
    with pytest.raises(LeaveError):
        _submit(db_path, start="2026-11-12", end="2026-11-10")
    with pytest.raises(LeaveError):
        _submit(db_path, leave_type="Holiday")
    with pytest.raises(LeaveError):
        _submit(db_path, start="not a date")


def test_hr_approves_and_duplicate_decision_is_blocked(db_path: Path) -> None:
    record = _submit(db_path)
    decided = leave_service.decide_leave_request(
        HR, record["id"], "approve", "Get well soon", db_path=db_path
    )
    assert decided["status"] == "approved"
    assert decided["decided_by_name"] == "Kavya Sharma"
    assert decided["decision_note"] == "Get well soon"

    with pytest.raises(LeaveError, match="already approved"):
        leave_service.decide_leave_request(HR, record["id"], "reject", db_path=db_path)


def test_hr_rejects_request(db_path: Path) -> None:
    record = _submit(db_path)
    decided = leave_service.decide_leave_request(
        HR, record["id"], "reject", "Coverage required", db_path=db_path
    )
    assert decided["status"] == "rejected"
    assert decided["decision_note"] == "Coverage required"
    assert leave_service.get_hr_inbox(HR, db_path=db_path)["count"] == 0


def test_employee_cannot_use_hr_inbox_or_decide(db_path: Path) -> None:
    record = _submit(db_path)
    with pytest.raises(LeaveError, match="HR leave inbox"):
        leave_service.get_hr_inbox(EMPLOYEE, db_path=db_path)
    with pytest.raises(LeaveError, match="approve or reject"):
        leave_service.decide_leave_request(
            EMPLOYEE, record["id"], "approve", db_path=db_path
        )


def test_employee_cannot_read_another_employees_request(db_path: Path) -> None:
    record = _submit(db_path)
    with pytest.raises(LeaveError, match="own leave requests"):
        leave_service.get_leave_request("XYZ012", record["id"], db_path=db_path)


def test_self_approval_is_blocked_and_ceo_can_break_glass(db_path: Path) -> None:
    record = _submit(db_path, employee_id=HR, reason="Personal work")
    with pytest.raises(LeaveError, match="own leave request"):
        leave_service.decide_leave_request(HR, record["id"], "approve", db_path=db_path)

    decided = leave_service.decide_leave_request(
        CEO, record["id"], "approve", "Approved by CEO", db_path=db_path
    )
    assert decided["status"] == "approved"
    assert decided["decided_by_name"] == "Arjun Mehta"


def test_leave_summary_counts_own_requests(db_path: Path) -> None:
    _submit(db_path)
    second = _submit(db_path)
    leave_service.decide_leave_request(HR, second["id"], "reject", db_path=db_path)
    summary = leave_service.leave_summary(EMPLOYEE, db_path=db_path)
    assert summary == {
        "pending": 1,
        "approved": 0,
        "rejected": 1,
        "cancelled": 0,
        "total": 2,
    }


def test_leave_permissions_are_seeded(db_path: Path) -> None:
    hr = auth.get_user(HR, db_path=db_path)
    employee = auth.get_user(EMPLOYEE, db_path=db_path)
    assert hr is not None and employee is not None
    assert auth.has_permission(hr, "leave:approve")
    assert auth.has_permission(hr, "leave:read:all")
    assert auth.has_permission(employee, "leave:request")
    assert not auth.has_permission(employee, "leave:approve")
    assert not auth.has_permission(employee, "leave:read:all")


def test_chat_tools_are_filtered_by_permission(db_path: Path) -> None:
    employee = auth.get_user(EMPLOYEE, db_path=db_path)
    hr = auth.get_user(HR, db_path=db_path)
    assert employee is not None and hr is not None

    employee_tools = {tool["function"]["name"] for tool in chat_tools(employee)}
    assert "submit_leave_request" in employee_tools
    assert "list_my_leave_requests" in employee_tools
    assert "get_hr_inbox" not in employee_tools
    assert "decide_leave_request" not in employee_tools

    hr_tools = {tool["function"]["name"] for tool in chat_tools(hr)}
    assert {
        "submit_leave_request",
        "get_hr_inbox",
        "decide_leave_request",
    } <= hr_tools


def test_chat_tools_submit_and_decide(db_path: Path) -> None:
    employee = auth.get_user(EMPLOYEE, db_path=db_path)
    hr = auth.get_user(HR, db_path=db_path)
    assert employee is not None and hr is not None

    submitted = execute_chat_tool(
        employee,
        "submit_leave_request",
        {
            "leave_type": "Sick Leave",
            "start_date": "2026-11-10",
            "end_date": "2026-11-12",
            "reason": "Fever",
        },
        db_path=db_path,
    )
    assert submitted["ok"] is True
    request_id = submitted["request"]["id"]
    assert "Karan Joshi" in submitted["request"]["letter_text"]

    inbox = execute_chat_tool(
        hr, "get_hr_inbox", {"status": "pending"}, db_path=db_path
    )
    assert inbox["ok"] is True
    assert inbox["count"] == 1

    decided = execute_chat_tool(
        hr,
        "decide_leave_request",
        {"request_id": request_id, "decision": "approve", "note": "Get well soon"},
        db_path=db_path,
    )
    assert decided["ok"] is True
    assert decided["request"]["status"] == "approved"


def test_chat_tool_errors_are_returned_to_the_model(db_path: Path) -> None:
    employee = auth.get_user(EMPLOYEE, db_path=db_path)
    assert employee is not None

    denied = execute_chat_tool(
        employee, "get_hr_inbox", {"status": "pending"}, db_path=db_path
    )
    assert denied["ok"] is False
    assert "HR leave inbox" in denied["error"]

    missing_dates = execute_chat_tool(
        employee,
        "submit_leave_request",
        {
            "leave_type": "Casual Leave",
            "start_date": "",
            "end_date": "",
            "reason": "Family function",
        },
        db_path=db_path,
    )
    assert missing_dates["ok"] is False
    assert "date" in missing_dates["error"].lower()

    bad_json = execute_chat_tool(
        employee, "submit_leave_request", "{not json", db_path=db_path
    )
    assert bad_json["ok"] is False

    unknown = execute_chat_tool(employee, "delete_everything", {}, db_path=db_path)
    assert unknown["ok"] is False
    assert "Unknown leave tool" in unknown["error"]


def test_leave_intent_detection() -> None:
    assert is_leave_intent("I want to apply for sick leave")
    assert is_leave_intent("Show me the pending leave requests")
    assert not is_leave_intent("What is the notice period after confirmation?")
    assert not is_leave_intent("Can you write Python code to sort a list?")


def test_mcp_tool_registry_covers_the_workflow() -> None:
    names = {tool.name for tool in mcp_server.TOOLS}
    assert {
        "sign_in",
        "sign_out",
        "whoami",
        "format_leave_letter",
        "request_leave",
        "request_leave_from_chat",
        "list_my_leave_requests",
        "get_leave_request",
        "get_hr_inbox",
        "decide_leave_request",
    } <= names
    for tool in mcp_server.TOOLS:
        assert tool.inputSchema["type"] == "object"


def test_mcp_end_to_end_employee_to_hr_decision(app_db: Path) -> None:
    del app_db
    mcp_server._SESSIONS.clear()

    with pytest.raises(LeaveError, match="Invalid work email or password"):
        mcp_server.dispatch("sign_in", {"email": EMPLOYEE, "password": "wrong"})

    employee = mcp_server.dispatch(
        "sign_in",
        {"email": "karan.joshi@xyzcompany.example", "password": "admin1234"},
    )
    token = employee["token"]
    assert employee["employee"]["employee_id"] == EMPLOYEE
    assert "leave:request" in employee["permissions"]

    preview = mcp_server.dispatch(
        "format_leave_letter",
        {
            "token": token,
            "message": (
                "I need sick leave from 10 Nov 2026 to 12 Nov 2026 because "
                "I have a fever."
            ),
        },
    )
    assert preview["ok"] is True
    assert "Sick Leave" in preview["letter"]

    submitted = mcp_server.dispatch(
        "request_leave_from_chat",
        {
            "token": token,
            "message": (
                "I need sick leave from 10 Nov 2026 to 12 Nov 2026 because "
                "I have a fever."
            ),
        },
    )
    request_id = submitted["request"]["id"]
    assert submitted["request"]["status"] == "pending"

    own = mcp_server.dispatch(
        "list_my_leave_requests", {"token": token, "status": "pending"}
    )
    assert [item["id"] for item in own["requests"]] == [request_id]

    hr = mcp_server.dispatch(
        "sign_in",
        {"email": "hr@xyzcompany.example", "password": "admin1234"},
    )
    hr_token = hr["token"]
    inbox = mcp_server.dispatch(
        "get_hr_inbox", {"token": hr_token, "status": "pending"}
    )
    assert inbox["count"] == 1
    assert inbox["requests"][0]["id"] == request_id

    decided = mcp_server.dispatch(
        "decide_leave_request",
        {
            "token": hr_token,
            "request_id": request_id,
            "decision": "approve",
            "note": "Get well soon",
        },
    )
    assert decided["request"]["status"] == "approved"
    assert decided["request"]["decided_by_name"] == "Kavya Sharma"

    fetched = mcp_server.dispatch(
        "get_leave_request", {"token": token, "request_id": request_id}
    )
    assert fetched["request"]["decision_note"] == "Get well soon"

    assert mcp_server.dispatch("sign_out", {"token": token}) == {"signed_out": True}
    with pytest.raises(LeaveError, match="Invalid or expired"):
        mcp_server.dispatch("whoami", {"token": token})


def test_mcp_rejects_unknown_tools_and_employee_inbox_access(app_db: Path) -> None:
    del app_db
    mcp_server._SESSIONS.clear()
    employee = mcp_server.dispatch(
        "sign_in",
        {"email": "karan.joshi@xyzcompany.example", "password": "admin1234"},
    )
    with pytest.raises(LeaveError, match="Unknown tool"):
        mcp_server.dispatch("delete_everything", {"token": employee["token"]})
    with pytest.raises(LeaveError, match="HR leave inbox"):
        mcp_server.dispatch("get_hr_inbox", {"token": employee["token"]})
