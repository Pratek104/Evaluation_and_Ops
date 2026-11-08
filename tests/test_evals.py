"""Tests for the offline RAG evaluation helpers."""

from __future__ import annotations

import pytest
from evals.eval_utils import (
    citation_metrics,
    extract_cited_pages,
    latest_by_case,
    load_cases,
    retrieval_metrics,
    term_coverage,
    term_in_text,
)


def test_numeric_term_matching_tolerates_grouping() -> None:
    assert term_in_text("18,50,000", "The total is Rs. 18,50,000 per month.")
    assert term_in_text("18,50,000", "The total is Rs. 1850000 per month.")
    assert term_in_text("18,50,000", "The total is Rs. 1,850,000 per month.")
    assert term_in_text("75,000", "Karan earns Rs. 75000 per month.")
    assert not term_in_text("75,000", "Rohan earns Rs. 7,50,000 per month.")
    assert not term_in_text("2,85,000", "A different figure is Rs. 12,85,000.")


def test_number_word_matching() -> None:
    assert term_in_text("six months", "The probation period is 6 months.")
    assert term_in_text("3 months", "The probation may be extended by three months.")
    assert term_in_text("one month", "After confirmation, 1 month of notice applies.")
    assert term_in_text("15 working days", "You may take fifteen working days.")


def test_extract_cited_pages() -> None:
    assert extract_cited_pages("Leave is described on page 7 and page 8.") == [7, 8]
    assert extract_cited_pages("See pages 6-8 and p. 17.") == [6, 7, 8, 17]
    assert extract_cited_pages("See pages 6, 7 and 8.") == [6, 7, 8]
    assert extract_cited_pages("No citation here.") == []


def test_retrieval_metrics() -> None:
    metrics = retrieval_metrics([4, 7, 7, 9, 8], [4])
    assert metrics["retrieval_hit"] is True
    assert metrics["retrieval_precision"] == 0.25
    assert metrics["retrieval_recall"] == 1.0
    assert metrics["retrieval_mrr"] == 1.0
    assert metrics["expected_pages_found"] == [4]
    assert metrics["expected_pages_missing"] == []

    metrics = retrieval_metrics([4, 7, 9, 8], [6, 7])
    assert metrics["retrieval_hit"] is True
    assert metrics["retrieval_precision"] == 0.25
    assert metrics["retrieval_recall"] == 0.5
    assert metrics["retrieval_mrr"] == 0.5
    assert metrics["expected_pages_missing"] == [6]


def test_retrieval_metrics_without_expected_pages() -> None:
    metrics = retrieval_metrics([4, 7], [])
    assert metrics["retrieval_hit"] is False
    assert metrics["retrieval_precision"] is None
    assert metrics["retrieval_recall"] is None
    assert metrics["retrieval_mrr"] is None


def test_citation_metrics() -> None:
    metrics = citation_metrics([4, 7, 99], [4, 7, 8], [4, 7])
    assert metrics["citation_precision"] == 2 / 3
    assert metrics["citation_recall"] == 1.0
    assert metrics["citation_hallucination_rate"] == pytest.approx(1 / 3)

    empty = citation_metrics([], [4, 7], [4])
    assert empty["citation_precision"] is None
    assert empty["citation_recall"] is None
    assert empty["citation_hallucination_rate"] is None


def test_term_coverage() -> None:
    assert (
        term_coverage(["22 working days", "15 working days"], "22 working days") == 0.5
    )
    assert term_coverage([], "anything") is None


def test_latest_by_case_keeps_last_record() -> None:
    records = [
        {"case_id": "A", "status": "error"},
        {"case_id": "B", "status": "ok"},
        {"case_id": "A", "status": "ok"},
    ]
    latest = latest_by_case(records)
    assert latest["A"]["status"] == "ok"
    assert latest["B"]["status"] == "ok"


def test_cases_file_is_valid() -> None:
    payload, cases = load_cases()
    assert payload["version"] == 1
    assert len(cases) == 25
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))
    valid_behaviors = {"answer", "refuse_or_scope_denial", "not_in_handbook"}
    for case in cases:
        assert case["employee_id"].startswith("XYZ")
        assert case["expected_behavior"] in valid_behaviors
        assert isinstance(case["expected_pages"], list)
        assert isinstance(case["expected_terms"], list)
        assert isinstance(case["forbidden_terms"], list)
        assert all(int(page) > 0 for page in case["expected_pages"])
