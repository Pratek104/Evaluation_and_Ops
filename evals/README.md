# RAG evaluation

This folder evaluates the real handbook assistant pipeline, not a mock. Each
case runs the same components as the Streamlit page:

1. `auth.get_user()` loads the seeded employee and role.
2. `auth.handbook_scope()` selects `public`, `directory`, or `full`.
3. `RagEngine.search()` performs role-filtered hybrid retrieval.
4. `build_llm_messages()` builds the grounded prompt.
5. `stream_chat()` calls OpenRouter with the app's free-model fallback.
6. `deepseek/deepseek-v4.1-flash` scores the answer with a fixed rubric.

The final CSV contains one row per case, the RAG answer, automated retrieval and
latency metrics, the DeepSeek judge's scores and notes, and blank `human_*`
columns for independent review.

## Case set

`cases.json` contains 25 role-spanning cases:

| Category | Cases | What it checks |
| --- | ---: | --- |
| `public_policy` | 8 | Working hours, probation, leave, notice, payroll, PF, travel |
| `directory` | 5 | Reporting lines, team membership, work emails, headcounts |
| `compensation` | 4 | Salary totals, highest/lowest pay, individual salary |
| `privacy_probe` | 6 | Role-boundary refusals and prompt-injection resistance |
| `out_of_scope` | 2 | No outside knowledge or code generation |

Cases use four personas:

| Role | Employee | Handbook scope |
| --- | --- | --- |
| CEO | `XYZ001` Arjun Mehta | `full` |
| CTO | `XYZ002` Priya Nair | `directory` |
| HR | `XYZ004` Kavya Sharma | `full` |
| Employee | `XYZ011` Karan Joshi | `public` |

Expected pages refer to `data/raw/xyz_company.pdf`. Pages 1–20 are public
handbook content, Appendix B (pages 21–22) is directory content, and Appendix C
(pages 22–23) is salary content.

## Metrics

### Latency

- **Retrieval latency** — time for `RagEngine.search()`.
- **Generation latency** — time from the first OpenRouter call to the last
  streamed token, including any retry.
- **Total latency** — retrieval plus prompt construction plus generation.
- **Time to first token** — first reasoning and first content chunk.

The runner warms up retrieval once before timing because the first search loads
the local embedding model. Without the warm-up, the first case would include
roughly 15–20 seconds of model loading.

### Retrieval quality

- **Hit rate** — at least one expected page was retrieved.
- **Page precision** — expected pages divided by unique retrieved pages.
- **Page recall** — expected pages found divided by expected pages.
- **MRR** — reciprocal rank of the first expected page.
- **Context term coverage** — fraction of expected key terms present in the
  retrieved passages.
- **Answer term coverage** — fraction of expected key terms present in the
  answer.

Precision and recall are page-level and use unique pages, because the retriever
can return several passages from the same page.

### Automated safety checks

- **Forbidden term hits** — salary figures, emails, or outside-knowledge terms
  that should not appear in the answer.
- **Forbidden context hits** — the same terms in the retrieved context. This
  should be zero for public and directory scopes.
- **Citation precision** — cited pages that were actually retrieved.
- **Citation recall** — expected pages that were cited.
- **Citation hallucination rate** — cited pages that were not retrieved.

### Model judge

DeepSeek V4.1 Flash scores each answer from 1–5 on relevance, groundedness,
completeness, role compliance, citation quality, clarity, and overall, then
returns `pass`, `partial`, or `fail`. The full rubric is in
[`judge_rubric.md`](judge_rubric.md). The judge treats the answer and retrieved
passages as untrusted data, so a prompt injection inside the corpus cannot
change the scoring instructions.

### Human review

The CSV leaves these columns blank:

`human_reviewer`, `human_relevance`, `human_groundedness`,
`human_completeness`, `human_role_compliance`, `human_citation_quality`,
`human_clarity`, `human_overall`, `human_verdict`, `human_notes`.

Use the same 1–5 scale and the same `pass` / `partial` / `fail` verdicts as the
model judge. Reviewing a sample independently is the best way to check whether
the judge is calibrated.

## Quick start

From the project root, with `OPENROUTER_API_KEY` set in `.env`:

```bash
python evals/run_all.py
```

This runs generation, judging, and CSV export. To run the stages separately:

```bash
python evals/run_rag_eval.py
python evals/judge_answers.py
python evals/export_csv.py
```

Useful options:

```bash
# Retrieval only, no model calls
python evals/run_rag_eval.py --dry-run

# A small smoke test
python evals/run_rag_eval.py --limit 3
python evals/judge_answers.py --limit 3
python evals/export_csv.py

# Re-run a single case
python evals/run_rag_eval.py --case-id PUB-001 --force
python evals/judge_answers.py --case-id PUB-001 --force
python evals/export_csv.py

# Retry only missing/errored cases (successful cases are skipped)
python evals/run_rag_eval.py
python evals/judge_answers.py
```

The generation and judging stages append to JSONL after every case. If a free
model is rate-limited, completed cases are not lost; rerun the same command to
resume.

## Outputs

| File | Contents |
| --- | --- |
| `results/rag_evaluation.csv` | Final dataset for human and model review |
| `results/summary.md` | Human-readable aggregate report |
| `results/summary.json` | Machine-readable aggregate metrics |
| `results/rag_answers.jsonl` | Raw answers, retrieved passages, timings, errors |
| `results/judge_scores.jsonl` | Raw judge scores, notes, usage, parse errors |
| `results/run_metadata.json` | Index size, warm-up time, requested model |
| `results/judge_metadata.json` | Judge model and token usage |

`results/rag_evaluation.csv` is UTF-8 with a BOM so Excel opens it correctly on
Windows. `results/rag_answers.jsonl` and `results/judge_scores.jsonl` are plain
UTF-8 JSONL.

## Notes and limitations

- The configured default model is `google/gemma-4-26b-a4b-it:free`. If it is
  unavailable, the app's existing fallback chain is used and the CSV records
  both `requested_model` and `model_used`.
- Free models are rate-limited and can be slow. The runner retries an empty
  answer once without extended reasoning, and retries a failed request once
  after a short delay.
- The judge model is paid. A full run is 25 judge calls; check OpenRouter
  pricing before running repeatedly.
- The handbook appendix contains a duplicated Rohan Desai salary row with two
  different values. The case set avoids making that ambiguity a scored fact.
- The department-counts sentence sits in the same passage as the start of the
  salary appendix, so directory-only retrieval cannot return that passage. The
  CTO Technology case is answered from the directory rows instead. This is a
  real corpus/classification limitation worth reviewing separately.
- Retrieval and generation are measured on the local machine and the public
  OpenRouter endpoint, so absolute latency depends on hardware, network, and
  upstream queueing. Compare medians and repeated runs rather than one number.
