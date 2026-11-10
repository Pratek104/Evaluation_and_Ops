# Leave workflow MCP server

`src/xyz_portal/mcp_server.py` exposes the leave request workflow as a **Model
Context Protocol** server over stdio. It uses the same authentication, RBAC, and
service layer as the Streamlit assistant, so a request submitted from an external
MCP client appears immediately in the HR inbox and vice versa.

## What the workflow does

```text
sign_in
   │
   ▼
format_leave_letter / request_leave_from_chat
   │  regex + date parser extracts leave type, dates, and reason
   ▼
render_leave_letter
   │  fixed formal template
   ▼
leave_requests (pending)
   │
   ▼
get_hr_inbox (HR or CEO)
   │
   ▼
decide_leave_request
   │
   ▼
approved / rejected + decision note + leave_events audit row
```

The chat-to-letter translation is deterministic at the service boundary. The
`request_leave_from_chat` tool parses the message without an LLM; the Streamlit
assistant uses model tool calls and then the same service validates the fields and
renders the letter. Both work offline once the request reaches the service.

## Start the server

The package must be importable. From the project root, either install it in
editable mode:

```bash
python -m pip install -e .
```

or set `PYTHONPATH` to the `src` directory.

Then run one of:

```bash
make mcp
python -m xyz_portal.mcp_server
xyz-leave-mcp
```

The process speaks MCP over stdin/stdout and writes logs to stderr. It creates
and seeds the SQLite database on startup if needed.

## Client configuration

Most MCP clients accept a JSON server definition. Use **absolute paths** for
`cwd` and `PYTHONPATH`, especially on Windows.

### Generic stdio configuration

```json
{
  "mcpServers": {
    "xyz-leave": {
      "command": "python",
      "args": ["-m", "xyz_portal.mcp_server"],
      "cwd": "D:\\DESKTOP\\AiOnly\\evalvs",
      "env": {
        "PYTHONPATH": "D:\\DESKTOP\\AiOnly\\evalvs\\src",
        "RBAC_DB_PATH": "D:\\DESKTOP\\AiOnly\\evalvs\\data\\runtime\\xyz_rbac.db"
      }
    }
  }
}
```

### macOS / Linux

```json
{
  "mcpServers": {
    "xyz-leave": {
      "command": "python3",
      "args": ["-m", "xyz_portal.mcp_server"],
      "cwd": "/absolute/path/to/evalvs",
      "env": {
        "PYTHONPATH": "/absolute/path/to/evalvs/src",
        "RBAC_DB_PATH": "/absolute/path/to/evalvs/data/runtime/xyz_rbac.db"
      }
    }
  }
}
```

If the package is installed in editable mode, `PYTHONPATH` can be omitted. Use
the same `RBAC_DB_PATH` as the Streamlit app if the two surfaces should share
requests.

## Authentication model

Tools do not accept an employee ID as identity. The client first calls
`sign_in` with a work email and password. The server validates the password with
the same PBKDF2 verifier as the UI and returns an opaque token:

```json
{
  "token": "t2gB0O4Q...",
  "employee": {
    "employee_id": "XYZ011",
    "name": "Karan Joshi",
    "email": "karan.joshi@xyzcompany.example",
    "role": "EMPLOYEE",
    "role_label": "Employee",
    "department": "Technology"
  },
  "permissions": [
    "directory:read:self",
    "handbook:read",
    "leave:read:self",
    "leave:request",
    "profile:read:self",
    "salary:read:self"
  ]
}
```

Pass that token to every other tool. Tokens are held in server memory only; a
server restart invalidates them. Call `sign_out` to invalidate a token
explicitly.

> **Security note:** stdio MCP servers run as a local subprocess under the
> client's account. The token prevents accidental impersonation inside the
> protocol, but it is not a substitute for OS-level isolation. Do not expose this
> server to untrusted clients, and do not log tool arguments containing
> passwords.

## Tool reference

### `sign_in`

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `email` | string | yes | Work email |
| `password` | string | yes | Account password |

Returns a session token, employee summary, and permission list.

### `sign_out`

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `token` | string | yes | Session token |

Returns `{"signed_out": true}`.

### `whoami`

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `token` | string | yes | Session token |

Returns the employee and permissions stored for the session.

### `format_leave_letter`

Translates raw chat into a formatted letter **without saving a request**. Use
this first when details may be missing.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `token` | string | yes | Session token |
| `message` | string | yes | Raw chat message |

When parsing succeeds:

```json
{
  "ok": true,
  "status": "preview",
  "parsed": {
    "leave_type": "Sick Leave",
    "start_date": "2026-11-10",
    "end_date": "2026-11-12",
    "days": 3,
    "reason": "I have a fever"
  },
  "assumptions": [],
  "letter": "XYZ Company\nHuman Resources Department\n..."
}
```

When a date is missing:

```json
{
  "ok": false,
  "status": "needs_clarification",
  "missing": ["start_date", "end_date"],
  "assumptions": ["No leave type was stated, so Casual Leave was assumed."],
  "message": "I need a start and end date to format the letter. Try: ..."
}
```

### `request_leave`

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `token` | string | yes | Session token |
| `leave_type` | string | yes | One of the supported leave types |
| `start_date` | string | yes | ISO or natural date |
| `end_date` | string | yes | ISO or natural date |
| `reason` | string | no | Reason included in the letter |

Supported types: `Casual Leave`, `Sick Leave`, `Privileged Leave`, `Unpaid
Leave`, `Maternity Leave`, `Paternity Leave`, `Bereavement Leave`,
`Compensatory Leave`.

### `request_leave_from_chat`

Parses a chat message and submits it immediately.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `token` | string | yes | Session token |
| `message` | string | yes | Raw leave request |

Example message:

```text
I need sick leave from 10 Nov 2026 to 12 Nov 2026 because I have a fever.
```

Response (trimmed):

```json
{
  "request": {
    "id": 1,
    "reference": "LR-0001",
    "leave_type": "Sick Leave",
    "start_date": "2026-11-10",
    "end_date": "2026-11-12",
    "days": 3,
    "reason": "I have a fever",
    "status": "pending",
    "letter_text": "XYZ Company\nHuman Resources Department\n..."
  },
  "message": "Request LR-0001 was sent to the HR inbox."
}
```

### `list_my_leave_requests`

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `token` | string | yes | Session token |
| `status` | string | no | `all`, `pending`, `approved`, `rejected`, or `cancelled` |

Returns `{"status": "...", "requests": [...]}`.

### `get_leave_request`

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `token` | string | yes | Session token |
| `request_id` | integer | yes | Numeric id (`LR-0001` has id `1`) |

Employees can read only their own requests. HR and the CEO can read any request.

### `get_hr_inbox`

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `token` | string | yes | Session token |
| `status` | string | no | `pending` (default), `approved`, `rejected`, `cancelled`, or `all` |

Response (trimmed):

```json
{
  "status": "pending",
  "count": 1,
  "counts": {
    "pending": 1,
    "approved": 0,
    "rejected": 0,
    "cancelled": 0
  },
  "total": 1,
  "requests": [
    {
      "reference": "LR-0001",
      "employee_name": "Karan Joshi",
      "leave_type": "Sick Leave",
      "days": 3,
      "letter_text": "XYZ Company\n..."
    }
  ]
}
```

### `decide_leave_request`

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `token` | string | yes | Session token |
| `request_id` | integer | yes | Numeric request id |
| `decision` | string | yes | `approve` or `reject` |
| `note` | string | no | Note shown to the employee |

Only `leave:approve` roles can call this tool. HR's own request must be decided
by the CEO (or another approver), because self-approval is blocked.

## Date and working-day rules

The parser accepts:

- ISO dates: `2026-11-10`
- Numeric dates: `10/11/2026` or `10-11-2026`
- Month names: `10 Nov 2026`, `10 November 2026`, `November 10, 2026`
- Weekdays: `Monday`, `next Monday`
- Relative words: `today`, `tomorrow`, `day after tomorrow`
- A duration such as `for 3 days` when only a start date is present

Working days follow the handbook's Monday–Saturday week. Sundays and the first
and third Saturday of each month are excluded. For example, 1–30 November 2026
contains **23 working days**.

If the parser cannot find both dates, `format_leave_letter` returns
`needs_clarification`; `request_leave_from_chat` raises an error asking for the
missing dates.

## Errors

Tool failures are returned as MCP tool errors with a readable message. Common
cases:

| Message | Cause |
| --- | --- |
| `Invalid work email or password.` | Failed `sign_in` |
| `Invalid or expired session token.` | Missing token or server restart |
| `Your role cannot access the HR leave inbox.` | Employee called `get_hr_inbox` |
| `Your role cannot approve or reject leave requests.` | Missing `leave:approve` |
| `You cannot approve or reject your own leave request.` | Self-approval attempt |
| `Leave request N is already approved.` | Duplicate decision |
| `The end date cannot be before the start date.` | Invalid range |
| `The selected range contains no working days.` | Only Sundays / off Saturdays |

## Data model

| Table | Purpose |
| --- | --- |
| `leave_requests` | Employee, type, dates, days, reason, raw chat, letter, status, decision |
| `leave_events` | Append-only audit of submissions and decisions |

Indexes cover employee, status, creation time, and event lookup. The Streamlit
assistant and the MCP server read and write the same rows.

## Tests

The workflow is covered by `tests/test_leave.py`:

```bash
python -m pytest tests/test_leave.py -q
```

Coverage includes date parsing, first/third Saturday rules, letter rendering,
submission, HR inbox visibility, approve/reject decisions, duplicate decisions,
self-approval blocking, CEO break-glass approval, role-filtered chat tools, chat
tool submission and decisions, tool error handling, MCP tool registration, MCP
authentication, and an end-to-end employee-to-HR flow. Prompt tests in
`tests/test_chat.py` cover the leave tool instructions and streamed tool-call
accumulation.
