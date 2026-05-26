# Benchmark System

This directory contains benchmark manifests for the enzyme immobilization RAG system.

## Current Benchmark Tiers

| Manifest | Purpose | Target size | Current role |
| --- | --- | ---: | --- |
| `retrieval_smoke.json` | Legacy retrieval regression gate | 62 | Keep for collection/rerank/schema regression only |
| `retrieval_quality_v1.json` | Layered retrieval quality with Recall@3/5/8, MRR@3/5/8, nDCG@5 | 120 | Seed manifest |
| `answer_quality_v1.json` | Recommendation / evidence-QA answer quality, citation grounding, unsupported claims | 50 | Seed manifest |
| `no_answer_intent_v1.json` | Social, gibberish, out-of-domain, and prompt-injection no-answer behavior | 30 | Seed manifest |
| `formulation_optimizer_v1.json` | Field-level formulation optimization checks | 20 | Seed manifest |

The v1 target is 220 curated cases. The current `*_v1.json` files are seed manifests: they define the schema, runner semantics, and high-value regression cases, but they intentionally do not pretend to be a statistically complete 220-case set yet.

Current seed coverage is 29/220 cases. Use `--validate-only` to make that explicit in CI and reports instead of silently treating the seed set as complete.

The formal manifest schema is tracked at `schemas/generated/qa_benchmark_manifest.schema.json`. The runner also performs stricter semantic validation that JSON Schema cannot express cleanly, such as no-answer assertions and literature-derived query provenance.

## Runner

Use the unified QA runner:

```bash
.venv/bin/python scripts/benchmark_qa_system.py \
  --generation-mode mock \
  --allow-failures \
  --output artifacts/benchmarks/qa_system_seed.json \
  --markdown reports/qa_system_seed.md
```

Validate manifests without loading embedding, Qdrant, or an LLM provider:

```bash
.venv/bin/python scripts/benchmark_qa_system.py \
  --validate-only \
  --output artifacts/benchmarks/qa_manifest_validation.json \
  --markdown reports/qa_manifest_validation.md
```

Generation modes:

- `mock`: deterministic local generation. Use for CI and contract checks.
- `skip`: retrieval-only execution for non-generation endpoints.
- `real`: use the configured provider, currently SiliconFlow by default.

Run only the no-answer suite:

```bash
.venv/bin/python scripts/benchmark_qa_system.py \
  --benchmark benchmarks/no_answer_intent_v1.json \
  --generation-mode mock \
  --allow-failures
```

Keep the legacy retrieval gate:

```bash
PYTHONPATH=src .venv/bin/python scripts/benchmark_retrieval.py \
  --benchmark benchmarks/retrieval_smoke.json \
  --config configs/local.yaml
```

## Case Schema

Each effective v1 case, after manifest `defaults` are applied, must include:

- `id`
- `kind`: `positive`, `ambiguous`, `negative`, `exclusion`, `no_answer`, `answer_quality`, or `formulation`
- `query`
- `endpoint`: `search_evidence`, `recommend`, `recommend_stream`, or `optimize`
- `top_k`
- `expected_evidence`
- `forbidden_evidence`
- `expected_answer_facts`
- `forbidden_claims`
- `expected_behavior`
- `difficulty`: `easy`, `medium`, `hard`, or `adversarial`
- `source`: `manual_user_like`, `literature_derived`, `adversarial`, or `regression_bug`
- `construction_note`
- `literature_rewrite`: boolean marker for whether the query was rewritten from a source-paper span

Data leakage controls:

- `manual_user_like` queries must not copy source-paper text.
- Record whether a query is literature-derived, manually paraphrased, adversarial, or regression-derived.
- `literature_derived` cases must set `literature_rewrite=true`.
- At least 40% of the full v1 set should be user-like, fuzzy, or non-source phrasing.

## Acceptance Targets

Retrieval:

- Recall@5 >= 0.95
- MRR@5 >= 0.85
- Forbidden Hit Rate = 0

No-answer:

- NoAnswer Accuracy = 1.00
- Unexpected Candidate Rate = 0
- Unexpected Citation Rate = 0

Answer quality:

- Citation Accuracy >= 0.90
- Unsupported Claim Count <= 0.10 / answer
- Condition Type Accuracy >= 0.90
- Stream/final consistency >= 0.98

Formulation:

- Evidence-backed Change Rate >= 0.90
- Unsafe Global Optimum Claim Count = 0
