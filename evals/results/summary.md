# RAG evaluation summary

Generated: 2026-11-08T07:55:54+00:00

## Run

- Dataset: `evals/cases.json`
- Cases in dataset: 25
- Cases answered: 25
- Cases judged: 25
- Answer errors: 0
- Judge errors: 0
- Requested answer model: `google/gemma-4-26b-a4b-it:free`
- Judge model: `deepseek/deepseek-v4.1-flash`
- Judge tokens: 80,306 (prompt 69,213; completion 11,093)
- Judge cost: $0.014166
- Retrieval warm-up: 14,764 ms
- Index: 23 pages, 44 passages, Hybrid (semantic + keyword)

## Key findings

- Retrieval hit rate: 100.0%; mean page precision: 0.48; mean MRR: 1.00.
- Generation latency: mean 9,584 ms, p95 19,286 ms; retrieval latency: mean 9 ms.
- Judge pass rate: 100.0%; mean role compliance: 5.00.
- Forbidden-term leaks: 0 of 25 answered cases.

## Latency

| Metric | Mean | Median | P95 | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| Retrieval | 9 ms | 9 ms | 11 ms | 8 ms | 12 ms |
| Generation | 9,584 ms | 7,301 ms | 19,286 ms | 3,681 ms | 21,264 ms |
| Total | 9,595 ms | 7,312 ms | 19,298 ms | 3,690 ms | 21,274 ms |

## Retrieval quality

| Metric | Value |
| --- | ---: |
| Retrieval hit rate | 100.0% |
| Mean page precision | 0.48 |
| Mean page recall | 1.00 |
| Mean MRR | 1.00 |
| Mean expected-term coverage in context | 80.4% |
| Mean expected-term coverage in answer | 86.8% |

## Model-judge scores

| Dimension | Mean |
| --- | ---: |
| Relevance | 5.00 |
| Groundedness | 5.00 |
| Completeness | 4.96 |
| Role compliance | 5.00 |
| Citation quality | 4.84 |
| Clarity | 5.00 |
| Overall | 4.92 |

## Verdicts

| Pass | Partial | Fail | Pass rate |
| ---: | ---: | ---: | ---: |
| 25 | 0 | 0 | 100.0% |

## Automated safety checks

- Answers with forbidden terms: 0 (0.0%)
- Answers with forbidden terms in retrieved context: 0
- Answers with no page citations: 0

## By category

| Category | Cases | Retrieval hit | Mean overall | Pass rate | Mean total |
| --- | ---: | ---: | ---: | ---: | ---: |
| compensation | 4 | 100.0% | 4.75 | 100.0% | 10,570 ms |
| directory | 5 | 100.0% | 5.00 | 100.0% | 9,160 ms |
| out_of_scope | 2 | — | 5.00 | 100.0% | 9,721 ms |
| privacy_probe | 6 | — | 4.83 | 100.0% | 11,858 ms |
| public_policy | 8 | 100.0% | 5.00 | 100.0% | 7,650 ms |

## By role

| Role | Cases | Retrieval hit | Mean overall | Pass rate | Mean total |
| --- | ---: | ---: | ---: | ---: | ---: |
| CEO | 2 | 100.0% | 4.50 | 100.0% | 16,251 ms |
| CTO | 5 | 100.0% | 5.00 | 100.0% | 12,844 ms |
| EMPLOYEE | 14 | 100.0% | 4.93 | 100.0% | 8,619 ms |
| HR | 4 | 100.0% | 5.00 | 100.0% | 5,621 ms |

## Human review

The CSV contains blank `human_*` columns for independent review. Suggested verdict values are `pass`, `partial`, and `fail`.
