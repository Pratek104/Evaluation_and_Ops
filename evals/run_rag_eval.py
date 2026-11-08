"""Run the real role-scoped RAG pipeline and record answers plus latency.

This script intentionally calls the same `RagEngine`, prompt builder, and
OpenRouter client used by the Streamlit app. It does not mock answers. Results
are appended to JSONL after every case so a rate-limited run can be resumed.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from eval_utils import (  # noqa: E402
    DEFAULT_ANSWERS_PATH,
    DEFAULT_CASES_PATH,
    DEFAULT_RUN_METADATA_PATH,
    RESULTS_DIR,
    append_jsonl,
    citation_metrics,
    extract_cited_pages,
    find_terms,
    iso_now,
    latest_by_case,
    load_cases,
    read_jsonl,
    retrieval_metrics,
    term_coverage,
    write_json,
)
from xyz_portal import auth  # noqa: E402
from xyz_portal.chat import build_llm_messages  # noqa: E402
from xyz_portal.config import API_KEY, DEFAULT_MODEL, PDF_PATH  # noqa: E402
from xyz_portal.rag import (  # noqa: E402
    OpenRouterError,
    RagEngine,
    is_free_model,
    stream_chat,
    supports_reasoning,
)

NO_RESULTS_ANSWER = (
    "I couldn't find that in the handbook sections available to your role. "
    "Try rephrasing with a policy or section name, or contact HR if you need access."
)
MAX_TOKENS = 1600
TEMPERATURE = 0.2
GENERATION_ATTEMPTS = 2
ERROR_RETRY_DELAY_SECONDS = 10.0


def _relative_path(path: Path) -> str:
    """Return a project-relative path when possible."""
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_ANSWERS_PATH)
    parser.add_argument(
        "--case-id",
        action="append",
        dest="case_ids",
        help="Run only this case ID. Repeat for multiple IDs.",
    )
    parser.add_argument("--limit", type=int, help="Run at most N cases.")
    parser.add_argument(
        "--top-k",
        type=int,
        help="Override the number of retrieved passages for every case.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore existing results and start a fresh output file.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Do not skip cases that already have a successful record.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Retrieve passages and compute retrieval metrics without model calls.",
    )
    parser.add_argument(
        "--no-warmup",
        action="store_true",
        help="Skip the retrieval warm-up (timing will include embedding-model load).",
    )
    return parser.parse_args()


def _select_cases(
    cases: list[dict[str, Any]],
    case_ids: list[str] | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    selected = cases
    if case_ids:
        wanted = set(case_ids)
        selected = [case for case in selected if str(case.get("id")) in wanted]
        missing = wanted - {str(case.get("id")) for case in selected}
        if missing:
            raise SystemExit(f"Unknown case IDs: {', '.join(sorted(missing))}")
    if limit is not None:
        selected = selected[: max(0, limit)]
    return selected


def _generate_answer(
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    """Stream one answer, retrying once if the model returns no content."""
    total_start = time.perf_counter()
    notices: list[str] = []
    last_content: list[str] = []
    last_reasoning: list[str] = []
    last_model = DEFAULT_MODEL
    last_error = ""
    first_reasoning_ms: float | None = None
    first_content_ms: float | None = None
    retry_reason = ""

    for attempt in range(GENERATION_ATTEMPTS):
        use_reasoning = supports_reasoning(DEFAULT_MODEL)
        if attempt > 0 and retry_reason == "empty":
            use_reasoning = False

        attempt_content: list[str] = []
        attempt_reasoning: list[str] = []
        attempt_notices: list[str] = []
        attempt_model = DEFAULT_MODEL
        attempt_first_reasoning: float | None = None
        attempt_first_content: float | None = None
        attempt_start = time.perf_counter()
        attempt_error = ""

        try:
            for kind, value in stream_chat(
                DEFAULT_MODEL,
                messages,
                API_KEY,
                reasoning=use_reasoning,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                allow_free_fallback=is_free_model(DEFAULT_MODEL),
            ):
                elapsed = (time.perf_counter() - attempt_start) * 1000
                if kind == "content":
                    attempt_content.append(value)
                    if attempt_first_content is None:
                        attempt_first_content = elapsed
                elif kind == "reasoning":
                    attempt_reasoning.append(value)
                    if attempt_first_reasoning is None:
                        attempt_first_reasoning = elapsed
                elif kind == "notice":
                    attempt_notices.append(value)
                elif kind == "model":
                    attempt_model = value
        except OpenRouterError as exc:
            attempt_error = str(exc)

        last_content = attempt_content
        last_reasoning = attempt_reasoning
        last_model = attempt_model
        first_reasoning_ms = attempt_first_reasoning
        first_content_ms = attempt_first_content
        notices.extend(attempt_notices)
        last_error = attempt_error

        answer = "".join(attempt_content).strip()
        if answer:
            break

        if attempt < GENERATION_ATTEMPTS - 1:
            retry_reason = "error" if attempt_error else "empty"
            if retry_reason == "error":
                time.sleep(ERROR_RETRY_DELAY_SECONDS)

    return {
        "answer": "".join(last_content).strip(),
        "reasoning": "".join(last_reasoning),
        "notices": list(dict.fromkeys(notices)),
        "model_used": last_model,
        "generation_ms": round((time.perf_counter() - total_start) * 1000, 1),
        "time_to_first_reasoning_ms": (
            round(first_reasoning_ms, 1) if first_reasoning_ms is not None else None
        ),
        "time_to_first_content_ms": (
            round(first_content_ms, 1) if first_content_ms is not None else None
        ),
        "attempts": GENERATION_ATTEMPTS if retry_reason else 1,
        "retry_reason": retry_reason,
        "error": last_error,
        "reasoning_used": bool(last_reasoning),
    }


def _build_record(
    case: dict[str, Any],
    user: dict[str, Any],
    scope: str,
    retrieved: list[dict[str, Any]],
    retrieval_ms: float,
    prompt_build_ms: float,
    generation: dict[str, Any],
    status: str,
    error: str,
    case_start: float,
) -> dict[str, Any]:
    question = str(case["question"])
    expected_pages = [int(page) for page in case.get("expected_pages", [])]
    expected_terms = [str(term) for term in case.get("expected_terms", [])]
    forbidden_terms = [str(term) for term in case.get("forbidden_terms", [])]
    retrieval_applicable = bool(case.get("retrieval_applicable", bool(expected_pages)))

    retrieved_pages = [int(item["page"]) for item in retrieved]
    context = "\n\n".join(
        f"[Passage {index} | page {item['page']}]\n{item['text']}"
        for index, item in enumerate(retrieved, start=1)
    )
    answer = str(generation.get("answer", ""))
    cited_pages = extract_cited_pages(answer)

    retrieval = retrieval_metrics(retrieved_pages, expected_pages)
    citations = citation_metrics(cited_pages, retrieved_pages, expected_pages)
    forbidden_hits = find_terms(forbidden_terms, answer)
    forbidden_context_hits = find_terms(forbidden_terms, context)
    notices = list(generation.get("notices", []))
    model_used = str(generation.get("model_used", ""))

    return {
        "case_id": str(case["id"]),
        "category": str(case.get("category", "")),
        "question": question,
        "employee_id": user["employee_id"],
        "employee_name": user["name"],
        "role": user["role"],
        "role_label": user["role_label"],
        "department": user["department"],
        "access_scope": scope,
        "expected_behavior": str(case.get("expected_behavior", "answer")),
        "expected_pages": expected_pages,
        "expected_terms": expected_terms,
        "forbidden_terms": forbidden_terms,
        "retrieval_applicable": retrieval_applicable,
        "notes": str(case.get("notes", "")),
        "requested_model": DEFAULT_MODEL,
        "model_used": model_used,
        "fallback_used": bool(model_used and model_used != DEFAULT_MODEL),
        "fallback_notice": notices[0] if notices else "",
        "notices": notices,
        "status": status,
        "error": error,
        "answer": answer,
        "answer_chars": len(answer),
        "reasoning_chars": len(str(generation.get("reasoning", ""))),
        "reasoning_used": bool(generation.get("reasoning_used", False)),
        "generation_attempts": int(generation.get("attempts", 1)),
        "generation_retry_reason": str(generation.get("retry_reason", "")),
        "retrieved_count": len(retrieved),
        "retrieved": retrieved,
        "retrieved_pages": retrieved_pages,
        "retrieved_scores": [round(float(item["score"]), 6) for item in retrieved],
        **retrieval,
        "context_term_coverage": term_coverage(expected_terms, context),
        "forbidden_context_hits": forbidden_context_hits,
        "answer_term_coverage": term_coverage(expected_terms, answer),
        "forbidden_term_hits": forbidden_hits,
        "forbidden_leak": bool(forbidden_hits),
        "cited_pages": cited_pages,
        **citations,
        "retrieval_latency_ms": round(retrieval_ms, 1),
        "prompt_build_ms": round(prompt_build_ms, 1),
        "generation_latency_ms": round(float(generation.get("generation_ms", 0.0)), 1),
        "total_latency_ms": round((time.perf_counter() - case_start) * 1000, 1),
        "time_to_first_reasoning_ms": generation.get("time_to_first_reasoning_ms"),
        "time_to_first_content_ms": generation.get("time_to_first_content_ms"),
        "timestamp": iso_now(),
    }


def main() -> int:
    args = parse_args()
    payload, all_cases = load_cases(args.cases)
    default_top_k = int(payload.get("default_top_k", 5))
    cases = _select_cases(all_cases, args.case_ids, args.limit)
    if not cases:
        raise SystemExit("No cases selected.")

    output_path = args.output
    if args.dry_run and args.output == DEFAULT_ANSWERS_PATH:
        output_path = RESULTS_DIR / "retrieval_dry_run.jsonl"

    if args.force:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("", encoding="utf-8")

    completed: set[str] = set()
    if not args.force and not args.no_resume and output_path.exists():
        for record in latest_by_case(read_jsonl(output_path)).values():
            if record.get("status") in {"ok", "no_results"}:
                completed.add(str(record.get("case_id")))

    if not args.dry_run and not API_KEY:
        raise SystemExit(
            "OPENROUTER_API_KEY is missing. Add it to .env before running answers."
        )

    auth.ensure_database()
    started_at = iso_now()
    engine = RagEngine.load(PDF_PATH)

    warmup_ms: float | None = None
    if not args.no_warmup:
        warmup_start = time.perf_counter()
        engine.search("office working hours", top_k=1, access_scope="public")
        warmup_ms = round((time.perf_counter() - warmup_start) * 1000, 1)

    print(
        f"Loaded {engine.page_count} pages, {len(engine.passages)} passages, "
        f"{engine.search_mode}."
    )
    if warmup_ms is not None:
        print(f"Retrieval warm-up: {warmup_ms:.0f} ms")
    print(f"Running {len(cases)} case(s); output: {output_path}")

    completed_count = 0
    error_count = 0
    skipped_count = 0

    for index, case in enumerate(cases, start=1):
        case_id = str(case["id"])
        if case_id in completed:
            skipped_count += 1
            print(f"[{index}/{len(cases)}] {case_id} skipped (already complete)")
            continue

        case_start = time.perf_counter()
        user = auth.get_user(str(case["employee_id"]))
        if user is None:
            error_count += 1
            print(f"[{index}/{len(cases)}] {case_id} ERROR unknown employee")
            continue
        scope = auth.handbook_scope(user)
        top_k = int(case.get("top_k", args.top_k or default_top_k))
        question = str(case["question"])

        retrieval_start = time.perf_counter()
        results = engine.search(question, top_k=top_k, access_scope=scope)
        retrieval_ms = (time.perf_counter() - retrieval_start) * 1000
        retrieved = [
            {
                "page": result.passage.page,
                "score": result.score,
                "text": result.passage.text,
            }
            for result in results
        ]

        if args.dry_run:
            expected_pages = [int(page) for page in case.get("expected_pages", [])]
            metrics = retrieval_metrics(
                [item["page"] for item in retrieved], expected_pages
            )
            record = {
                "case_id": case_id,
                "category": str(case.get("category", "")),
                "employee_id": user["employee_id"],
                "role": user["role"],
                "access_scope": scope,
                "question": question,
                "expected_pages": expected_pages,
                "retrieved_pages": [item["page"] for item in retrieved],
                "retrieved_scores": [
                    round(float(item["score"]), 6) for item in retrieved
                ],
                "retrieval_latency_ms": round(retrieval_ms, 1),
                "status": "retrieval_ok",
                "timestamp": iso_now(),
                **metrics,
            }
            append_jsonl(output_path, record)
            completed_count += 1
            print(
                f"[{index}/{len(cases)}] {case_id} {scope:9} "
                f"pages={record['retrieved_pages']} "
                f"hit={record['retrieval_hit']} "
                f"p={record['retrieval_precision']} "
                f"r={record['retrieval_recall']} "
                f"{retrieval_ms:.0f}ms"
            )
            continue

        if not results:
            generation = {
                "answer": NO_RESULTS_ANSWER,
                "reasoning": "",
                "notices": [],
                "model_used": "",
                "generation_ms": 0.0,
                "time_to_first_reasoning_ms": None,
                "time_to_first_content_ms": None,
                "attempts": 0,
                "retry_reason": "",
                "error": "",
                "reasoning_used": False,
            }
            record = _build_record(
                case,
                user,
                scope,
                retrieved,
                retrieval_ms,
                0.0,
                generation,
                "no_results",
                "",
                case_start,
            )
            append_jsonl(output_path, record)
            completed_count += 1
            print(f"[{index}/{len(cases)}] {case_id} no_results")
            continue

        prompt_start = time.perf_counter()
        messages = build_llm_messages(question, [], results, user)
        prompt_build_ms = (time.perf_counter() - prompt_start) * 1000

        generation = _generate_answer(messages)
        answer = str(generation.get("answer", ""))
        error = str(generation.get("error", ""))
        if answer:
            status = "ok"
        elif error:
            status = "error"
        else:
            status = "empty"
            error = "The model returned no answer content."

        record = _build_record(
            case,
            user,
            scope,
            retrieved,
            retrieval_ms,
            prompt_build_ms,
            generation,
            status,
            error,
            case_start,
        )
        append_jsonl(output_path, record)

        if status == "ok":
            completed_count += 1
        else:
            error_count += 1

        print(
            f"[{index}/{len(cases)}] {case_id} {status:9} {scope:9} "
            f"pages={record['retrieved_pages']} "
            f"hit={record['retrieval_hit']} "
            f"retrieval={record['retrieval_latency_ms']:.0f}ms "
            f"generation={record['generation_latency_ms']:.0f}ms "
            f"total={record['total_latency_ms']:.0f}ms "
            f"model={record['model_used'] or '-'}"
        )
        if record["forbidden_leak"]:
            print(
                f"  WARNING forbidden terms in answer: {record['forbidden_term_hits']}"
            )
        if status != "ok" and error:
            print(f"  ERROR {error}")

    finished_at = iso_now()
    latest = latest_by_case(read_jsonl(output_path))
    status_counts = Counter(str(record.get("status")) for record in latest.values())
    metadata = {
        "started_at": started_at,
        "finished_at": finished_at,
        "dry_run": bool(args.dry_run),
        "requested_model": DEFAULT_MODEL,
        "pdf_path": _relative_path(PDF_PATH),
        "page_count": engine.page_count,
        "passage_count": len(engine.passages),
        "search_mode": engine.search_mode,
        "warmup_retrieval_ms": warmup_ms,
        "cases_in_dataset": len(all_cases),
        "cases_selected_this_run": len(cases),
        "cases_completed_this_run": completed_count,
        "cases_errored_this_run": error_count,
        "cases_skipped_this_run": skipped_count,
        "records_total": len(latest),
        "status_counts": dict(sorted(status_counts.items())),
        "output": _relative_path(output_path),
    }
    if not args.dry_run:
        write_json(DEFAULT_RUN_METADATA_PATH, metadata)

    print(
        f"Done: {completed_count} completed, {error_count} errored, "
        f"{skipped_count} skipped. Records: {len(latest)}."
    )
    return 0 if completed_count or skipped_count else 1


if __name__ == "__main__":
    raise SystemExit(main())
