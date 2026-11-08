"""Text processing and role-scoped retrieval tests."""

from __future__ import annotations

from pathlib import Path

from xyz_portal.rag import (
    Passage,
    RagEngine,
    passage_access_level,
    scope_allows,
)
from xyz_portal.rag.engine import clean_text, split_passages


def test_clean_text_drops_table_of_contents() -> None:
    raw = "Contents\nLeave policy....4\nTravel policy....8\nPayroll....12\nIntro text."
    assert clean_text(raw) == "Intro text."


def test_split_passages_respects_size_and_minimum() -> None:
    text = " ".join(["Employees receive paid leave each year."] * 120)
    passages = split_passages(text, max_chars=300, overlap=40)
    assert len(passages) > 1
    assert all(len(passage) <= 300 for passage in passages)
    assert all(len(passage) >= 60 for passage in passages)


def test_access_levels() -> None:
    assert passage_access_level(Passage(0, 5, "Leave policy")) == "public"
    assert (
        passage_access_level(Passage(1, 25, "Employee directory work email"))
        == "directory"
    )
    assert (
        passage_access_level(Passage(2, 27, "Monthly gross salary payroll")) == "salary"
    )
    assert passage_access_level(Passage(3, 30, "Unclassified appendix")) == "directory"


def test_scope_allows() -> None:
    assert scope_allows("public", "public")
    assert not scope_allows("public", "directory")
    assert not scope_allows("public", "salary")
    assert scope_allows("directory", "directory")
    assert not scope_allows("directory", "salary")
    assert scope_allows("full", "salary")
    assert scope_allows("unknown", "public")
    assert not scope_allows("unknown", "directory")


def test_search_filters_restricted_passages_before_ranking() -> None:
    passages = [
        Passage(0, 5, "Salary and benefits policy for all employees. " * 8),
        Passage(1, 25, "Employee directory with salary details. " * 8),
    ]
    engine = RagEngine(Path("handbook.pdf"), passages, 30, embeddings=None)

    public_results = engine.search("salary", top_k=5, access_scope="public")
    assert [result.passage.page for result in public_results] == [5]

    full_results = engine.search("salary", top_k=5, access_scope="full")
    assert {result.passage.page for result in full_results} == {5, 25}


def test_search_handles_empty_queries() -> None:
    engine = RagEngine(
        Path("handbook.pdf"),
        [Passage(0, 5, "Leave policy " * 20)],
        10,
        embeddings=None,
    )
    assert engine.search("", access_scope="public") == []
