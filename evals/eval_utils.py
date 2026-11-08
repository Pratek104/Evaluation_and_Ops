"""Shared helpers for the RAG evaluation scripts."""

from __future__ import annotations

import json
import math
import os
import re
import statistics
import unicodedata
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVALS_DIR = PROJECT_ROOT / "evals"
RESULTS_DIR = EVALS_DIR / "results"
DEFAULT_CASES_PATH = EVALS_DIR / "cases.json"
DEFAULT_ANSWERS_PATH = RESULTS_DIR / "rag_answers.jsonl"
DEFAULT_JUDGMENTS_PATH = RESULTS_DIR / "judge_scores.jsonl"
DEFAULT_CSV_PATH = RESULTS_DIR / "rag_evaluation.csv"
DEFAULT_SUMMARY_JSON_PATH = RESULTS_DIR / "summary.json"
DEFAULT_SUMMARY_MD_PATH = RESULTS_DIR / "summary.md"
DEFAULT_RUN_METADATA_PATH = RESULTS_DIR / "run_metadata.json"
DEFAULT_JUDGE_METADATA_PATH = RESULTS_DIR / "judge_metadata.json"

EXPECTED_BEHAVIORS = {"answer", "refuse_or_scope_denial", "not_in_handbook"}
JUDGE_SCORE_KEYS = (
    "relevance",
    "groundedness",
    "completeness",
    "role_compliance",
    "citation_quality",
    "clarity",
    "overall",
)
JUDGE_VERDICTS = {"pass", "partial", "fail"}

_NUMBER_WORDS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "fifteen": "15",
    "twenty": "20",
    "thirty": "30",
    "fifty": "50",
    "hundred": "100",
}
_DIGIT_WORDS = {
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
    "10": "ten",
    "11": "eleven",
    "12": "twelve",
    "13": "thirteen",
    "14": "fourteen",
    "15": "fifteen",
    "16": "sixteen",
    "17": "seventeen",
    "18": "eighteen",
    "19": "nineteen",
    "20": "twenty",
    "22": "twenty two",
    "26": "twenty six",
}
_COMPOUND_NUMBERS = {
    "twenty two": "22",
    "twenty-two": "22",
    "twenty six": "26",
    "twenty-six": "26",
    "twenty five": "25",
    "twenty-five": "25",
}
_CITATION_RE = re.compile(
    r"\b(?:pages?|pp?\.)\s*"
    r"(\d+(?:\s*(?:[-\u2013\u2014]|to)\s*\d+)?"
    r"(?:\s*(?:,|and|&)\s*\d+(?:\s*(?:[-\u2013\u2014]|to)\s*\d+)?)*)",
    re.IGNORECASE,
)


def iso_now() -> str:
    """Return a timezone-aware ISO timestamp."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_cases(
    path: str | Path = DEFAULT_CASES_PATH,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load the case file and validate its top-level shape."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return {"version": 1, "default_top_k": 5}, payload
    if not isinstance(payload, dict):
        raise ValueError(f"Case file must contain an object or list: {path}")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError(f"Case file is missing a 'cases' list: {path}")
    return payload, cases


def normalize_text(text: Any) -> str:
    """Normalize text for tolerant, case-insensitive term matching."""
    value = unicodedata.normalize("NFKC", str(text))
    value = value.replace("\u2018", "'").replace("\u2019", "'")
    value = value.replace("\u201c", '"').replace("\u201d", '"')
    value = value.replace("\u2013", "-").replace("\u2014", "-")
    value = value.replace("\u202f", " ").replace("\u00a0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip().lower()


def _term_variants(term: str) -> set[str]:
    """Return equivalent forms such as '6 months' and 'six months'."""
    normalized = normalize_text(term)
    variants = {normalized}

    compound = normalized
    for phrase, digits in _COMPOUND_NUMBERS.items():
        compound = compound.replace(phrase, digits)
    variants.add(compound)

    with_digits = normalized
    for word, digits in _NUMBER_WORDS.items():
        with_digits = re.sub(rf"\b{re.escape(word)}\b", digits, with_digits)
    variants.add(with_digits)

    with_words = normalized
    for digit, word in _DIGIT_WORDS.items():
        with_words = re.sub(rf"\b{digit}\b", word, with_words)
    variants.add(with_words)

    return {variant for variant in variants if variant}


def _is_pure_numeric(term: str) -> bool:
    """Return whether a term is a number with optional grouping punctuation."""
    return bool(re.fullmatch(r"[0-9][0-9,.\s]*", term))


def _numeric_pattern(term: str) -> str | None:
    """Build a regex that tolerates Indian and Western digit grouping."""
    digits = re.sub(r"\D", "", term)
    if not digits:
        return None
    body = r"[,\s]*".join(re.escape(digit) for digit in digits)
    return rf"(?<![\d,]){body}(?![\d,])"


def term_in_text(term: str, text: Any) -> bool:
    """Return whether a term or a close equivalent appears in text."""
    normalized_text = normalize_text(text)
    if not normalized_text:
        return False

    # Numeric terms need boundary-aware matching so "2,85,000" does not match
    # inside "12,85,000" and "75,000" still matches "75000".
    if _is_pure_numeric(term):
        pattern = _numeric_pattern(term)
        return bool(pattern and re.search(pattern, normalized_text))

    return any(variant in normalized_text for variant in _term_variants(term))


def find_terms(terms: Iterable[str], text: Any) -> list[str]:
    """Return the terms that appear in text, preserving input order."""
    return [term for term in terms if term_in_text(term, text)]


def term_coverage(terms: Iterable[str], text: Any) -> float | None:
    """Return the fraction of expected terms found in text."""
    term_list = list(terms)
    if not term_list:
        return None
    return len(find_terms(term_list, text)) / len(term_list)


def extract_cited_pages(answer: str) -> list[int]:
    """Extract page citations such as '(page 7)', 'pages 6-8', or 'p. 4'."""
    pages: set[int] = set()
    for match in _CITATION_RE.finditer(answer or ""):
        chunk = match.group(1)
        for part in re.split(r"\s*(?:,|and|&)\s*", chunk):
            part = part.strip()
            if not part:
                continue
            range_match = re.fullmatch(r"(\d+)\s*(?:[-\u2013\u2014]|to)\s*(\d+)", part)
            if range_match:
                start, end = int(range_match.group(1)), int(range_match.group(2))
                if end >= start and end - start <= 50:
                    pages.update(range(start, end + 1))
                else:
                    pages.update({start, end})
            elif part.isdigit():
                pages.add(int(part))
    return sorted(pages)


def retrieval_metrics(
    retrieved_pages: Iterable[int],
    expected_pages: Iterable[int],
) -> dict[str, Any]:
    """Compute page-level retrieval hit, precision, recall, and MRR."""
    retrieved_list = [int(page) for page in retrieved_pages]
    expected_list = list(dict.fromkeys(int(page) for page in expected_pages))
    retrieved_unique = list(dict.fromkeys(retrieved_list))

    found = [page for page in expected_list if page in retrieved_unique]
    missing = [page for page in expected_list if page not in retrieved_unique]
    hit = bool(found)

    precision = (
        len(found) / len(retrieved_unique)
        if retrieved_unique and expected_list
        else None
    )
    recall = len(found) / len(expected_list) if expected_list else None

    reciprocal_rank = None
    if expected_list:
        for rank, page in enumerate(retrieved_list, start=1):
            if page in expected_list:
                reciprocal_rank = 1.0 / rank
                break

    return {
        "retrieval_hit": hit,
        "retrieval_precision": precision,
        "retrieval_recall": recall,
        "retrieval_mrr": reciprocal_rank,
        "expected_pages_found": found,
        "expected_pages_missing": missing,
    }


def citation_metrics(
    cited_pages: Iterable[int],
    retrieved_pages: Iterable[int],
    expected_pages: Iterable[int],
) -> dict[str, Any]:
    """Measure whether cited pages were retrieved and whether expected pages were cited."""
    cited = list(dict.fromkeys(int(page) for page in cited_pages))
    retrieved = {int(page) for page in retrieved_pages}
    expected = {int(page) for page in expected_pages}

    if not cited:
        return {
            "citation_precision": None,
            "citation_recall": None,
            "citation_hallucination_rate": None,
        }

    valid = [page for page in cited if page in retrieved]
    precision = len(valid) / len(cited)
    recall = (
        len([page for page in cited if page in expected]) / len(expected)
        if expected
        else None
    )
    return {
        "citation_precision": precision,
        "citation_recall": recall,
        "citation_hallucination_rate": 1.0 - precision,
    }


def latency_stats(values: Iterable[float | None]) -> dict[str, Any]:
    """Return count, mean, median, p95, min, and max for a latency list."""
    clean = sorted(float(value) for value in values if value is not None)
    if not clean:
        return {
            "count": 0,
            "mean_ms": None,
            "median_ms": None,
            "p95_ms": None,
            "min_ms": None,
            "max_ms": None,
        }
    p95_index = max(0, math.ceil(0.95 * len(clean)) - 1)
    return {
        "count": len(clean),
        "mean_ms": round(statistics.mean(clean), 1),
        "median_ms": round(statistics.median(clean), 1),
        "p95_ms": round(clean[p95_index], 1),
        "min_ms": round(clean[0], 1),
        "max_ms": round(clean[-1], 1),
    }


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Read a JSONL file, skipping blank lines."""
    file_path = Path(path)
    if not file_path.exists():
        return []
    records: list[dict[str, Any]] = []
    with file_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON in {file_path} at line {line_number}: {exc}"
                ) from exc
            if isinstance(record, dict):
                records.append(record)
    return records


def append_jsonl(path: str | Path, record: dict[str, Any]) -> None:
    """Append one JSON object to a UTF-8 JSONL file and flush it to disk."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def write_json(path: str | Path, payload: Any) -> None:
    """Write an indented UTF-8 JSON document."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_json(path: str | Path) -> dict[str, Any] | None:
    """Read a JSON object if the file exists."""
    file_path = Path(path)
    if not file_path.exists():
        return None
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def latest_by_case(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Keep the most recent record for each case ID."""
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        case_id = str(record.get("case_id") or record.get("id") or "")
        if case_id:
            latest[case_id] = record
    return latest


def mean_or_none(values: Iterable[float | None]) -> float | None:
    """Return the mean of non-null values, or None when there are none."""
    clean = [float(value) for value in values if value is not None]
    return round(statistics.mean(clean), 4) if clean else None


def rate_or_none(values: Iterable[bool | None]) -> float | None:
    """Return the fraction of true values, or None when there are none."""
    clean = [bool(value) for value in values if value is not None]
    return round(sum(clean) / len(clean), 4) if clean else None


def compact_cell(value: Any) -> Any:
    """Convert values into CSV-friendly cells."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set)):
        return "; ".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return value
