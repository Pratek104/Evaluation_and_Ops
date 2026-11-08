"""Display formatting helpers shared by the UI pages."""

from __future__ import annotations

from datetime import date, datetime, timezone


def format_pages(pages: list[int]) -> str:
    """Format a list of page numbers for the source expander."""
    unique = sorted(set(pages))
    return ", ".join(f"p. {page}" for page in unique)


def format_date(value: str) -> str:
    """Format an ISO date for display."""
    try:
        return date.fromisoformat(value).strftime("%d %b %Y")
    except (TypeError, ValueError):
        return value


def format_rupees(amount: int | float) -> str:
    """Format a rupee amount with thousands separators."""
    return f"Rs. {amount:,.0f}"


def format_timestamp(value: str) -> str:
    """Format a SQLite UTC timestamp in the viewer's local timezone."""
    try:
        parsed = datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        return parsed.astimezone().strftime("%d %b %Y, %I:%M %p")
    except (TypeError, ValueError):
        return value
