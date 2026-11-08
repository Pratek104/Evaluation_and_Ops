"""Merge RAG answers and judge scores into the final CSV and summary."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from eval_utils import (  # noqa: E402
    DEFAULT_ANSWERS_PATH,
    DEFAULT_CASES_PATH,
    DEFAULT_CSV_PATH,
    DEFAULT_JUDGE_METADATA_PATH,
    DEFAULT_JUDGMENTS_PATH,
    DEFAULT_RUN_METADATA_PATH,
    DEFAULT_SUMMARY_JSON_PATH,
    DEFAULT_SUMMARY_MD_PATH,
    JUDGE_SCORE_KEYS,
    compact_cell,
    iso_now,
    latency_stats,
    latest_by_case,
    load_cases,
    mean_or_none,
    rate_or_none,
    read_json,
    read_jsonl,
    write_json,
)

COLUMNS = [
    "case_id",
    "category",
    "employee_id",
    "employee_name",
    "role",
    "role_label",
    "department",
    "access_scope",
    "question",
    "expected_behavior",
    "expected_pages",
    "expected_terms",
    "forbidden_terms",
    "retrieval_applicable",
    "case_notes",
    "requested_model",
    "model_used",
    "fallback_used",
    "fallback_notice",
    "status",
    "answer",
    "answer_chars",
    "reasoning_chars",
    "reasoning_used",
    "generation_attempts",
    "generation_retry_reason",
    "retrieved_count",
    "retrieved_pages",
    "retrieved_scores",
    "retrieved_sources",
    "retrieval_hit",
    "retrieval_precision",
    "retrieval_recall",
    "retrieval_mrr",
    "expected_pages_found",
    "expected_pages_missing",
    "context_term_coverage",
    "forbidden_context_hits",
    "retrieval_latency_ms",
    "prompt_build_ms",
    "generation_latency_ms",
    "total_latency_ms",
    "time_to_first_reasoning_ms",
    "time_to_first_content_ms",
    "answer_term_coverage",
    "forbidden_term_hits",
    "forbidden_leak",
    "cited_pages",
    "citation_precision",
    "citation_recall",
    "citation_hallucination_rate",
    "judge_model",
    "judge_model_used",
    "judge_relevance",
    "judge_groundedness",
    "judge_completeness",
    "judge_role_compliance",
    "judge_citation_quality",
    "judge_clarity",
    "judge_overall",
    "judge_verdict",
    "judge_notes",
    "judge_latency_ms",
    "judge_error",
    "human_reviewer",
    "human_relevance",
    "human_groundedness",
    "human_completeness",
    "human_role_compliance",
    "human_citation_quality",
    "human_clarity",
    "human_overall",
    "human_verdict",
    "human_notes",
    "error",
    "timestamp",
]

HUMAN_COLUMNS = [
    "human_reviewer",
    "human_relevance",
    "human_groundedness",
    "human_completeness",
    "human_role_compliance",
    "human_citation_quality",
    "human_clarity",
    "human_overall",
    "human_verdict",
    "human_notes",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--answers", type=Path, default=DEFAULT_ANSWERS_PATH)
    parser.add_argument("--judgments", type=Path, default=DEFAULT_JUDGMENTS_PATH)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY_JSON_PATH)
    parser.add_argument("--summary-md", type=Path, default=DEFAULT_SUMMARY_MD_PATH)
    return parser.parse_args()


def _join(values: Any) -> str:
    if values is None:
        return ""
    if isinstance(values, (list, tuple, set)):
        return "; ".join(str(value) for value in values)
    return str(values)


def _json_cell(value: Any) -> str:
    if value in (None, "", []):
        return ""
    return json.dumps(value, ensure_ascii=False)


def _score_cell(value: Any) -> Any:
    if value is None or value == "":
        return ""
    return value


def _build_row(
    case: dict[str, Any],
    answer: dict[str, Any],
    judgment: dict[str, Any],
) -> dict[str, Any]:
    case_id = str(case.get("id", answer.get("case_id", "")))
    row: dict[str, Any] = {
        "case_id": case_id,
        "category": case.get("category", answer.get("category", "")),
        "employee_id": answer.get("employee_id", case.get("employee_id", "")),
        "employee_name": answer.get("employee_name", ""),
        "role": answer.get("role", ""),
        "role_label": answer.get("role_label", ""),
        "department": answer.get("department", ""),
        "access_scope": answer.get("access_scope", ""),
        "question": case.get("question", answer.get("question", "")),
        "expected_behavior": case.get("expected_behavior", ""),
        "expected_pages": _join(case.get("expected_pages", [])),
        "expected_terms": _join(case.get("expected_terms", [])),
        "forbidden_terms": _join(case.get("forbidden_terms", [])),
        "retrieval_applicable": compact_cell(
            case.get("retrieval_applicable", bool(case.get("expected_pages")))
        ),
        "case_notes": case.get("notes", ""),
    }

    answer_fields = (
        "requested_model",
        "model_used",
        "fallback_used",
        "fallback_notice",
        "status",
        "answer",
        "answer_chars",
        "reasoning_chars",
        "reasoning_used",
        "generation_attempts",
        "generation_retry_reason",
        "retrieved_count",
        "retrieval_hit",
        "retrieval_precision",
        "retrieval_recall",
        "retrieval_mrr",
        "context_term_coverage",
        "retrieval_latency_ms",
        "prompt_build_ms",
        "generation_latency_ms",
        "total_latency_ms",
        "time_to_first_reasoning_ms",
        "time_to_first_content_ms",
        "answer_term_coverage",
        "forbidden_leak",
        "citation_precision",
        "citation_recall",
        "citation_hallucination_rate",
        "error",
        "timestamp",
    )
    for field in answer_fields:
        row[field] = compact_cell(answer.get(field))
    if not answer:
        row["status"] = "missing"

    row["retrieved_pages"] = _join(answer.get("retrieved_pages", []))
    row["retrieved_scores"] = _join(
        [round(float(score), 4) for score in answer.get("retrieved_scores", [])]
    )
    row["retrieved_sources"] = _json_cell(answer.get("retrieved", []))
    row["expected_pages_found"] = _join(answer.get("expected_pages_found", []))
    row["expected_pages_missing"] = _join(answer.get("expected_pages_missing", []))
    row["forbidden_context_hits"] = _join(answer.get("forbidden_context_hits", []))
    row["forbidden_term_hits"] = _join(answer.get("forbidden_term_hits", []))
    row["cited_pages"] = _join(answer.get("cited_pages", []))

    row["judge_model"] = judgment.get("judge_model", "")
    row["judge_model_used"] = judgment.get("judge_model_used", "")
    row["judge_verdict"] = judgment.get("judge_verdict", "")
    row["judge_notes"] = judgment.get("judge_notes", "")
    row["judge_latency_ms"] = compact_cell(judgment.get("judge_latency_ms"))
    row["judge_error"] = judgment.get("judge_error", "")
    scores = judgment.get("judge_scores")
    if not isinstance(scores, dict):
        scores = {}
    for key in JUDGE_SCORE_KEYS:
        value = judgment.get(f"judge_{key}", scores.get(key))
        row[f"judge_{key}"] = _score_cell(value)

    for column in HUMAN_COLUMNS:
        row[column] = ""

    return {column: row.get(column, "") for column in COLUMNS}


def _answered(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if record.get("status") in {"ok", "no_results"}
        and str(record.get("answer", "")).strip()
    ]


def _judged(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if record.get("judge_overall") is not None
        and record.get("judge_verdict") in {"pass", "partial", "fail"}
    ]


def _group_metrics(
    records: list[dict[str, Any]],
    judgments: dict[str, dict[str, Any]],
    key: str,
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[str(record.get(key, "unknown"))].append(record)

    output: dict[str, Any] = {}
    for name, group in sorted(groups.items()):
        applicable = [record for record in group if record.get("retrieval_applicable")]
        judged = [
            judgments[str(record.get("case_id"))]
            for record in group
            if str(record.get("case_id")) in judgments
            and judgments[str(record.get("case_id"))].get("judge_overall") is not None
        ]
        output[name] = {
            "cases": len(group),
            "retrieval_hit_rate": rate_or_none(
                record.get("retrieval_hit") for record in applicable
            ),
            "mean_retrieval_precision": mean_or_none(
                record.get("retrieval_precision") for record in applicable
            ),
            "mean_total_latency_ms": mean_or_none(
                record.get("total_latency_ms") for record in group
            ),
            "mean_judge_overall": mean_or_none(
                record.get("judge_overall") for record in judged
            ),
            "judge_pass_rate": rate_or_none(
                record.get("judge_verdict") == "pass" for record in judged
            ),
            "judged": len(judged),
        }
    return output


def _fmt_ms(value: Any) -> str:
    if value is None:
        return "—"
    return f"{float(value):,.0f} ms"


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "—"
    return f"{float(value) * 100:.1f}%"


def _fmt_score(value: Any) -> str:
    if value is None:
        return "—"
    return f"{float(value):.2f}"


def _display_path(path: Path) -> str:
    """Return a project-relative path when possible."""
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def _summary_markdown(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    latency = summary["latency"]
    retrieval = summary["retrieval"]
    judge = summary["judge"]
    run = summary.get("run_metadata") or {}

    lines = [
        "# RAG evaluation summary",
        "",
        f"Generated: {summary['generated_at']}",
        "",
        "## Run",
        "",
        f"- Dataset: `{summary['dataset']['path']}`",
        f"- Cases in dataset: {counts['cases_total']}",
        f"- Cases answered: {counts['cases_answered']}",
        f"- Cases judged: {counts['cases_judged']}",
        f"- Answer errors: {counts['answer_errors']}",
        f"- Judge errors: {counts['judge_errors']}",
        f"- Requested answer model: `{summary['answer_model']['requested']}`",
        f"- Judge model: `{summary['judge_model']}`",
    ]
    judge_usage = (summary.get("judge_metadata") or {}).get("usage_totals") or {}
    if judge_usage.get("total_tokens"):
        lines.append(
            f"- Judge tokens: {int(judge_usage['total_tokens']):,} "
            f"(prompt {int(judge_usage.get('prompt_tokens', 0)):,}; "
            f"completion {int(judge_usage.get('completion_tokens', 0)):,})"
        )
    if judge_usage.get("cost_usd"):
        lines.append(f"- Judge cost: ${float(judge_usage['cost_usd']):.6f}")
    if run.get("warmup_retrieval_ms") is not None:
        lines.append(f"- Retrieval warm-up: {_fmt_ms(run['warmup_retrieval_ms'])}")
    if run.get("page_count"):
        lines.append(
            f"- Index: {run.get('page_count')} pages, "
            f"{run.get('passage_count')} passages, {run.get('search_mode')}"
        )
    lines.extend(
        [
            "",
            "## Key findings",
            "",
            f"- Retrieval hit rate: {_fmt_pct(retrieval['hit_rate'])}; "
            f"mean page precision: {_fmt_score(retrieval['mean_precision'])}; "
            f"mean MRR: {_fmt_score(retrieval['mean_mrr'])}.",
            f"- Generation latency: mean {_fmt_ms(latency['generation']['mean_ms'])}, "
            f"p95 {_fmt_ms(latency['generation']['p95_ms'])}; retrieval latency: "
            f"mean {_fmt_ms(latency['retrieval']['mean_ms'])}.",
            f"- Judge pass rate: {_fmt_pct(judge['pass_rate'])}; mean role "
            f"compliance: {_fmt_score(judge['mean_scores'].get('role_compliance'))}.",
            f"- Forbidden-term leaks: {counts['forbidden_leak_count']} of "
            f"{counts['cases_answered']} answered cases.",
            "",
            "## Latency",
            "",
            "| Metric | Mean | Median | P95 | Min | Max |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for label, key in (
        ("Retrieval", "retrieval"),
        ("Generation", "generation"),
        ("Total", "total"),
    ):
        stats = latency[key]
        lines.append(
            f"| {label} | {_fmt_ms(stats['mean_ms'])} | "
            f"{_fmt_ms(stats['median_ms'])} | {_fmt_ms(stats['p95_ms'])} | "
            f"{_fmt_ms(stats['min_ms'])} | {_fmt_ms(stats['max_ms'])} |"
        )

    lines.extend(
        [
            "",
            "## Retrieval quality",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
            f"| Retrieval hit rate | {_fmt_pct(retrieval['hit_rate'])} |",
            f"| Mean page precision | {_fmt_score(retrieval['mean_precision'])} |",
            f"| Mean page recall | {_fmt_score(retrieval['mean_recall'])} |",
            f"| Mean MRR | {_fmt_score(retrieval['mean_mrr'])} |",
            f"| Mean expected-term coverage in context | {_fmt_pct(retrieval['mean_context_term_coverage'])} |",
            f"| Mean expected-term coverage in answer | {_fmt_pct(retrieval['mean_answer_term_coverage'])} |",
            "",
            "## Model-judge scores",
            "",
            "| Dimension | Mean |",
            "| --- | ---: |",
        ]
    )
    for key, label in (
        ("relevance", "Relevance"),
        ("groundedness", "Groundedness"),
        ("completeness", "Completeness"),
        ("role_compliance", "Role compliance"),
        ("citation_quality", "Citation quality"),
        ("clarity", "Clarity"),
        ("overall", "Overall"),
    ):
        lines.append(f"| {label} | {_fmt_score(judge['mean_scores'].get(key))} |")

    verdicts = judge["verdicts"]
    lines.extend(
        [
            "",
            "## Verdicts",
            "",
            "| Pass | Partial | Fail | Pass rate |",
            "| ---: | ---: | ---: | ---: |",
            f"| {verdicts.get('pass', 0)} | {verdicts.get('partial', 0)} | "
            f"{verdicts.get('fail', 0)} | {_fmt_pct(judge['pass_rate'])} |",
            "",
            "## Automated safety checks",
            "",
            f"- Answers with forbidden terms: {counts['forbidden_leak_count']} "
            f"({_fmt_pct(retrieval['forbidden_leak_rate'])})",
            f"- Answers with forbidden terms in retrieved context: "
            f"{counts['forbidden_context_leak_count']}",
            f"- Answers with no page citations: {counts['answers_without_citations']}",
            "",
            "## By category",
            "",
            "| Category | Cases | Retrieval hit | Mean overall | Pass rate | Mean total |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for name, group in summary["by_category"].items():
        lines.append(
            f"| {name} | {group['cases']} | {_fmt_pct(group['retrieval_hit_rate'])} | "
            f"{_fmt_score(group['mean_judge_overall'])} | "
            f"{_fmt_pct(group['judge_pass_rate'])} | "
            f"{_fmt_ms(group['mean_total_latency_ms'])} |"
        )

    lines.extend(
        [
            "",
            "## By role",
            "",
            "| Role | Cases | Retrieval hit | Mean overall | Pass rate | Mean total |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for name, group in summary["by_role"].items():
        lines.append(
            f"| {name} | {group['cases']} | {_fmt_pct(group['retrieval_hit_rate'])} | "
            f"{_fmt_score(group['mean_judge_overall'])} | "
            f"{_fmt_pct(group['judge_pass_rate'])} | "
            f"{_fmt_ms(group['mean_total_latency_ms'])} |"
        )

    lines.extend(
        [
            "",
            "## Human review",
            "",
            "The CSV contains blank `human_*` columns for independent review. "
            "Suggested verdict values are `pass`, `partial`, and `fail`.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    _, cases = load_cases(args.cases)
    answers = latest_by_case(read_jsonl(args.answers))
    judgments = latest_by_case(read_jsonl(args.judgments))
    answered = _answered(answers.values())
    judged = _judged(judgments.values())

    rows = [
        _build_row(
            case, answers.get(str(case["id"]), {}), judgments.get(str(case["id"]), {})
        )
        for case in cases
    ]
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    successful = [record for record in answered if record.get("status") == "ok"]
    applicable = [record for record in answered if record.get("retrieval_applicable")]
    retrieval = {
        "hit_rate": rate_or_none(record.get("retrieval_hit") for record in applicable),
        "mean_precision": mean_or_none(
            record.get("retrieval_precision") for record in applicable
        ),
        "mean_recall": mean_or_none(
            record.get("retrieval_recall") for record in applicable
        ),
        "mean_mrr": mean_or_none(record.get("retrieval_mrr") for record in applicable),
        "mean_context_term_coverage": mean_or_none(
            record.get("context_term_coverage") for record in applicable
        ),
        "mean_answer_term_coverage": mean_or_none(
            record.get("answer_term_coverage") for record in answered
        ),
        "forbidden_leak_rate": rate_or_none(
            record.get("forbidden_leak") for record in answered
        ),
    }
    judge_means = {
        key: mean_or_none(record.get(f"judge_{key}") for record in judged)
        for key in JUDGE_SCORE_KEYS
    }
    verdicts = Counter(str(record.get("judge_verdict", "")) for record in judged)
    judge = {
        "mean_scores": judge_means,
        "verdicts": {
            "pass": verdicts.get("pass", 0),
            "partial": verdicts.get("partial", 0),
            "fail": verdicts.get("fail", 0),
        },
        "pass_rate": rate_or_none(
            record.get("judge_verdict") == "pass" for record in judged
        ),
    }

    counts = {
        "cases_total": len(cases),
        "cases_answered": len(answered),
        "cases_judged": len(judged),
        "answer_errors": sum(
            1
            for record in answers.values()
            if record.get("status") in {"error", "empty"}
        ),
        "judge_errors": sum(
            1 for record in judgments.values() if record.get("judge_error")
        ),
        "forbidden_leak_count": sum(
            1 for record in answered if record.get("forbidden_leak")
        ),
        "forbidden_context_leak_count": sum(
            1 for record in answered if record.get("forbidden_context_hits")
        ),
        "answers_without_citations": sum(
            1
            for record in successful
            if record.get("retrieval_applicable") and not record.get("cited_pages")
        ),
    }

    run_metadata = read_json(DEFAULT_RUN_METADATA_PATH)
    judge_metadata = read_json(DEFAULT_JUDGE_METADATA_PATH)
    judge_models = sorted(
        {
            str(record.get("judge_model"))
            for record in judgments.values()
            if record.get("judge_model")
        }
    )
    summary = {
        "generated_at": iso_now(),
        "dataset": {
            "path": _display_path(args.cases),
            "cases": len(cases),
        },
        "answer_model": {
            "requested": (run_metadata or {}).get("requested_model", ""),
            "used": sorted(
                {
                    str(record.get("model_used"))
                    for record in answered
                    if record.get("model_used")
                }
            ),
        },
        "judge_model": (judge_metadata or {}).get(
            "judge_model", ", ".join(judge_models)
        ),
        "run_metadata": run_metadata,
        "judge_metadata": judge_metadata,
        "counts": counts,
        "latency": {
            "retrieval": latency_stats(
                record.get("retrieval_latency_ms") for record in answered
            ),
            "generation": latency_stats(
                record.get("generation_latency_ms") for record in successful
            ),
            "total": latency_stats(
                record.get("total_latency_ms") for record in answered
            ),
        },
        "retrieval": retrieval,
        "judge": judge,
        "by_category": _group_metrics(answered, judgments, "category"),
        "by_role": _group_metrics(answered, judgments, "role"),
    }

    write_json(args.summary_json, summary)
    args.summary_md.parent.mkdir(parents=True, exist_ok=True)
    args.summary_md.write_text(_summary_markdown(summary), encoding="utf-8")

    print(f"Wrote {len(rows)} rows to {args.csv}")
    print(f"Wrote {args.summary_json}")
    print(f"Wrote {args.summary_md}")
    print(
        f"Answered {counts['cases_answered']}/{counts['cases_total']}, "
        f"judged {counts['cases_judged']}, "
        f"pass rate {_fmt_pct(judge['pass_rate'])}."
    )
    print(
        f"Latency: retrieval {_fmt_ms(latency_stats([record.get('retrieval_latency_ms') for record in answered])['mean_ms'])}, "
        f"generation {_fmt_ms(latency_stats([record.get('generation_latency_ms') for record in successful])['mean_ms'])}, "
        f"total {_fmt_ms(latency_stats([record.get('total_latency_ms') for record in answered])['mean_ms'])}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
