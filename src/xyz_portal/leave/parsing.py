"""Parse natural-language leave messages into structured request fields."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

LEAVE_TYPES: dict[str, str] = {
    "casual": "Casual Leave",
    "sick": "Sick Leave",
    "privileged": "Privileged Leave",
    "earned": "Privileged Leave",
    "unpaid": "Unpaid Leave",
    "maternity": "Maternity Leave",
    "paternity": "Paternity Leave",
    "bereavement": "Bereavement Leave",
    "compensatory": "Compensatory Leave",
}

LEAVE_TYPE_LABELS: tuple[str, ...] = (
    "Casual Leave",
    "Sick Leave",
    "Privileged Leave",
    "Unpaid Leave",
    "Maternity Leave",
    "Paternity Leave",
    "Bereavement Leave",
    "Compensatory Leave",
)

DEFAULT_LEAVE_TYPE = "Casual Leave"

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

_MONTH_PATTERN = "|".join(sorted(_MONTHS, key=len, reverse=True))
_WEEKDAY_PATTERN = "|".join(_WEEKDAYS)


@dataclass(frozen=True)
class ParsedLeave:
    """Structured fields extracted from a raw chat message."""

    leave_type: str
    start_date: date | None
    end_date: date | None
    reason: str
    missing: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()

    @property
    def days(self) -> int | None:
        """Return the working-day count when both dates are known."""
        if self.start_date is None or self.end_date is None:
            return None
        return count_working_days(self.start_date, self.end_date)


def is_first_or_third_saturday(value: date) -> bool:
    """Return whether a date is the first or third Saturday of its month."""
    return value.weekday() == 5 and ((value.day - 1) // 7 + 1) in (1, 3)


def count_working_days(start: date, end: date) -> int:
    """Count working days, skipping Sundays and first/third Saturdays."""
    if end < start:
        raise ValueError("The end date cannot be before the start date.")
    total = 0
    current = start
    while current <= end:
        if current.weekday() != 6 and not is_first_or_third_saturday(current):
            total += 1
        current += timedelta(days=1)
    return total


def _month_number(name: str) -> int | None:
    return _MONTHS.get(name.lower().strip("."))


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _weekday_date(name: str, *, next_week: bool, today: date) -> date:
    target = _WEEKDAYS[name.lower()]
    delta = (target - today.weekday()) % 7
    if next_week or delta == 0:
        delta = delta or 7
    return today + timedelta(days=delta)


def _date_mentions(text: str, today: date) -> list[tuple[int, date, str]]:
    """Return (position, date, source) for each date-like phrase in text."""
    mentions: list[tuple[int, date, str]] = []

    for match in re.finditer(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)", text):
        parsed = _safe_date(int(match[1]), int(match[2]), int(match[3]))
        if parsed is not None:
            mentions.append((match.start(), parsed, "explicit"))

    for match in re.finditer(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{2,4})(?!\d)", text):
        year = int(match[3])
        year = year + 2000 if year < 100 else year
        parsed = _safe_date(year, int(match[2]), int(match[1]))
        if parsed is not None:
            mentions.append((match.start(), parsed, "explicit"))

    for match in re.finditer(r"(?<!\d)(\d{1,2})-(\d{1,2})-(\d{2,4})(?!\d)", text):
        year = int(match[3])
        year = year + 2000 if year < 100 else year
        parsed = _safe_date(year, int(match[2]), int(match[1]))
        if parsed is not None:
            mentions.append((match.start(), parsed, "explicit"))

    for match in re.finditer(
        rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?\s+"
        rf"({_MONTH_PATTERN})\.?,?\s+(\d{{4}})(?!\d)",
        text,
        re.IGNORECASE,
    ):
        month = _month_number(match[2])
        parsed = _safe_date(int(match[3]), month, int(match[1])) if month else None
        if parsed is not None:
            mentions.append((match.start(), parsed, "explicit"))

    for match in re.finditer(
        rf"\b({_MONTH_PATTERN})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+"
        rf"(\d{{4}})(?!\d)",
        text,
        re.IGNORECASE,
    ):
        month = _month_number(match[1])
        parsed = _safe_date(int(match[3]), month, int(match[2])) if month else None
        if parsed is not None:
            mentions.append((match.start(), parsed, "explicit"))

    for match in re.finditer(
        rf"\b(?:(next)\s+)?({_WEEKDAY_PATTERN})\b", text, re.IGNORECASE
    ):
        parsed = _weekday_date(match[2], next_week=bool(match[1]), today=today)
        mentions.append((match.start(), parsed, "weekday"))

    for match in re.finditer(
        r"\b(today|tomorrow|day after tomorrow)\b", text, re.IGNORECASE
    ):
        word = match[1].lower()
        offset = {"today": 0, "tomorrow": 1, "day after tomorrow": 2}[word]
        mentions.append((match.start(), today + timedelta(days=offset), "relative"))

    seen: set[tuple[int, date]] = set()
    unique: list[tuple[int, date, str]] = []
    for mention in sorted(mentions, key=lambda item: item[0]):
        key = (mention[0], mention[1])
        if key in seen:
            continue
        seen.add(key)
        unique.append(mention)
    return unique


def parse_single_date(value: str | date, *, today: date | None = None) -> date:
    """Parse one date from ISO, numeric, month-name, weekday, or relative text."""
    if isinstance(value, date):
        return value
    text = (value or "").strip()
    if not text:
        raise ValueError("A date is required.")
    mentions = _date_mentions(text, today or date.today())
    if not mentions:
        raise ValueError(f"Could not parse a date from {value!r}.")
    return mentions[0][1]


def _extract_reason(text: str) -> str:
    patterns = (
        r"\bbecause\s+(.+)",
        r"\bdue to\s+(.+)",
        r"\bsince\s+(.+)",
        r"\breason\s*[:\-]\s*(.+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return match[1].strip().strip(" .,;")[:500]
    return ""


def parse_leave_chat(raw_chat: str, *, today: date | None = None) -> ParsedLeave:
    """Extract leave type, dates, and reason from a free-form chat message."""
    text = re.sub(r"\s+", " ", raw_chat or "").strip()
    today = today or date.today()
    assumptions: list[str] = []
    lowered = text.lower()

    leave_type = DEFAULT_LEAVE_TYPE
    for keyword, label in LEAVE_TYPES.items():
        if re.search(rf"\b{re.escape(keyword)}\b", lowered):
            leave_type = label
            break
    else:
        if text:
            assumptions.append("No leave type was stated, so Casual Leave was assumed.")

    mentions = _date_mentions(text, today)
    start: date | None = None
    end: date | None = None

    if mentions:
        start = mentions[0][1]
        if len(mentions) >= 2:
            end = mentions[1][1]
            if end < start:
                if mentions[0][2] == "weekday" and mentions[1][2] == "weekday":
                    end += timedelta(days=7)
                    assumptions.append(
                        "The weekday range wrapped to the following week."
                    )
                else:
                    end = None
                    assumptions.append("The end date was before the start date.")
        else:
            end = start
    else:
        start = None
        end = None

    duration_match = re.search(r"\bfor\s+(\d+)\s+(?:working\s+)?days?\b", lowered)
    if start is not None and end == start and duration_match:
        extra = max(1, int(duration_match[1])) - 1
        end = start + timedelta(days=extra)
        assumptions.append(
            "The end date was derived from the stated "
            f"{duration_match[1]}-day duration."
        )

    missing: list[str] = []
    if start is None:
        missing.append("start_date")
    if end is None:
        missing.append("end_date")
    if start is not None and end is not None and end < start:
        missing.append("end_date")

    return ParsedLeave(
        leave_type=leave_type,
        start_date=start,
        end_date=end,
        reason=_extract_reason(text),
        missing=tuple(missing),
        assumptions=tuple(assumptions),
    )
