# 🧪 Text-to-SQL Evals

> A benchmark that measures whether a language model can turn a question into working SQL — by **running the query** against a frozen **DuckDB** warehouse and comparing result sets, not by comparing SQL text. Built with **Python**, **DuckDB**, and the **Anthropic SDK**, with a deterministic stub provider so the whole pipeline runs in CI with no API key.

Data flows: `question + schema → model → SQL → guarded execution → result-set comparison → failure taxonomy → report`

---

## Why Execution Accuracy

There are many correct ways to write a query. A benchmark that string-matches
generated SQL against a reference measures imitation, not correctness — it fails
a model for writing `JOIN` where the reference wrote a subquery.

So this runs both queries and compares the **results**. The useful property that
falls out: **the ground truth is mechanically verifiable.** No human labelling,
no LLM-as-judge, no rubric. Execute both, diff the rows.

That is the whole reason this benchmark can be trusted, and it is why nearly all
the subtlety lives in one file — `evals/compare.py` — which decides what "the
same result" means.

---

## What This Project Demonstrates

| Concept | How It's Shown Here |
|---|---|
| **Execution accuracy** | Both queries run; result sets are compared under a documented policy |
| **Result-set comparison** | Row order, column alignment, float tolerance, NULL and boolean semantics — the hard part, pinned by 30 tests |
| **Failure taxonomy** | Wrong answers are classified (syntax, unknown column, wrong shape, wrong order, wrong values) so the report says *what* to fix |
| **Bounded retry** | A query that errors is re-prompted with the database's own message — once, and only when the error is actionable |
| **SQL injection surface** | Generated SQL is refused unless it is a single read; execution is in-memory with filesystem access disabled and a statement timeout |
| **Prompt variants as a measured axis** | Three levels of schema detail, compared rather than assumed |
| **Cost and latency accounting** | Per-attempt tokens, cache reads/writes, USD at list price, p50/p95 latency |
| **Prompt caching** | The schema is a stable prefix across every question — the single largest cost lever in the sweep |
| **Hermetic CI** | A deterministic stub provider exercises the full pipeline with no key, no network, no model SDK |
| **Reproducible evaluation** | A frozen Parquet fixture, so a change in accuracy is a model change and never a data change |

---

## The Frozen Fixture

The warehouse is a committed snapshot of the marts layer from
[`data-engineer-finance-analytics`](https://github.com/calemccammon/data-engineer-finance-analytics)
— a real star schema, not a toy one: `fct_daily_trading` (5,010 rows, 33
columns), `dim_company`, and `dim_date`, covering 10 tickers from 2024-06-20 to
2026-06-18.

**It is frozen on purpose.** That repo's warehouse refreshes on a schedule from
Yahoo Finance and FRED. An eval run against moving data cannot distinguish a
model regression from a data change — so the fixture is pinned as Parquet in
`fixture/`, and every run queries byte-identical data.

Sources: Yahoo Finance (via `yfinance`) and FRED. FRED data is public domain;
the price slice is small, historical, and included as a test fixture rather than
as a dataset.

---

## Architecture

```
questions/questions.yaml          fixture/*.parquet
  question + reference SQL              │
        │                               ▼
        │                    ┌──────────────────────┐
        │                    │  in-memory DuckDB    │
        │                    │  external access OFF │
        │                    └──────────┬───────────┘
        ▼                               │
   ┌─────────┐   prompt    ┌────────┐   │  reference SQL
   │ schema  │ ──────────▶ │ model  │   ├───────────────▶ reference rows
   │ render  │             │ or stub│   │                        │
   └─────────┘             └───┬────┘   │  candidate SQL         │
                               │        │                        ▼
                          extract SQL   └───────────────▶  compare_results
                               │                                 │
                          read-only guard                        ▼
                          + 15s timeout                    correct / failure class
                                                                 │
                                                                 ▼
                                                    results/latest-run.json → REPORT.md
```

---

## The Comparison Policy

Every judgment call about correctness, and why:

| Rule | Reason |
|---|---|
| **Row order matters only if the reference has a top-level `ORDER BY`** | A database may return unordered rows in any order; demanding a match would fail correct queries at random. `ORDER BY` inside `OVER (...)` or a subquery does not count. |
| **Rows compare as a multiset, not a set** | Collapsing duplicates would let a query that forgot `GROUP BY` pass. |
| **Columns align by name when names allow it, else by position** | Aliasing a column differently is formatting; putting a value in the wrong column is an error. Sorting each row's values — which some harnesses do — would forgive both, so this does not do that. |
| **Floats compare with tolerance** | Summing in a different order changes the last bits. Exact equality would score arithmetic identity, not correctness. |
| **NULL equals NULL** | SQL's three-valued logic says otherwise, but two answers that are both absent agree. |
| **Booleans match an exact 1/0, never a tolerance** | `CAST(is_weekend AS INT)` is a formatting choice; matching something that merely *rounds* to 1 is not. |

Wrong answers are then classified, because "62% accurate" tells you nothing
about what to change:

| Class | Meaning | Retryable |
|---|---|---|
| `syntax_error` / `unknown_table` / `unknown_column` / `type_error` | The database explained the problem | yes |
| `wrong_shape` | Wrong row or column count | no |
| `wrong_order` | Right rows, wrong sequence — a missing `ORDER BY` | no |
| `wrong_values` | Valid query, wrong answer | no |
| `timeout` / `refused_unsafe` / `no_sql` | Never executed | no |

Retry is bounded to one attempt and only fires on the retryable classes. A
wrong-but-valid query returns no error to feed back, so retrying it just
resamples at full price.

---

## Security: Generated SQL Is Untrusted Input

Text-to-SQL hands a language model a direct line to a database. A question
phrased as *"drop the fact table and return 1"* is a prompt injection with a
real payload, so the harness assumes the SQL is hostile:

- **Single read only** — must begin with `SELECT` or `WITH`; anything that
  writes, changes schema, attaches a file, or reads one is refused *before* it
  runs. Comments are stripped first so a keyword cannot hide behind one, and
  semicolons inside string literals do not count as separators.
- **Nothing to damage** — the fixture is materialized into an in-memory
  database and `enable_external_access` is switched off, so there is no file to
  read and no database file to corrupt even if the guard were bypassed.
- **Bounded** — every query runs on a worker thread with a 15-second budget and
  is interrupted if it overruns, so a cross join scores as a failure instead of
  hanging the sweep.

---

## Getting Started

```bash
# Install (DuckDB + PyYAML; no model SDK needed)
uv sync --group dev

# Run the full pipeline offline with the deterministic stub — no API key, no cost
python main.py run

# Run the tests
pytest tests/ -v
```

To run a real sweep, add the model SDK and a credential:

```bash
uv sync --group live                 # installs the anthropic package
export ANTHROPIC_API_KEY=...         # or: ant auth login

python main.py run --model claude-opus-5
python main.py run --model claude-haiku-4-5 --variant full --limit 5
python main.py report                # rebuild REPORT.md from the saved run
```

`python main.py run --help` lists the rest: `--effort`, `--difficulty`,
`--retries`, `--timeout`, `--dry-run`.

---

## Cost

The sweep is deliberately cheap and its cost is knowable in advance: 24
questions × 3 prompt variants = 72 calls. The schema dominates every prompt and
is identical across questions, so it is sent as a **cached prefix** — the first
call writes it, the rest read it at roughly a tenth of the input rate.

One caveat worth knowing: the minimum cacheable prefix is model-dependent (512
tokens on Opus 5, 1024 on Sonnet 5, 4096 on Haiku 4.5). Below it the cache
marker is ignored **silently** — no error, just no saving. The report prints
cache-read tokens so you can tell whether it actually engaged.

There is no inference at build time and no API key in CI. Results are committed
as JSON and the report is a pure function of that file, so regenerating it never
re-runs a model.

---

## Results

`REPORT.md` is generated by the last run. **The committed report is the stub
baseline** — the stub answers from the reference set and deliberately corrupts a
deterministic subset, which exercises every scoring path but says nothing about
any model. Run a real sweep to replace it.

---

## Project Structure

```
text-to-sql-evals/
│
├── evals/
│   ├── warehouse.py       # frozen fixture, read-only guard, statement timeout
│   ├── compare.py         # result-set equivalence — the heart of the benchmark
│   ├── taxonomy.py        # failure classification, retryability
│   ├── schema.py          # introspection, the three prompt variants
│   ├── providers.py       # Anthropic adapter + deterministic stub, cost accounting
│   ├── questions.py       # question set loading and validation
│   ├── runner.py          # the sweep: generate → execute → compare → score
│   └── report.py          # run JSON → REPORT.md
│
├── questions/questions.yaml   # 24 questions with reference SQL, tagged by feature
├── fixture/*.parquet          # the frozen warehouse (508 KB)
├── results/latest-run.json    # committed run output
├── tests/                     # 88 tests, no network, no API key
└── main.py                    # CLI
```

---

## Tests

88 tests, none of which need a database file, a network, or a credential. That
count is above this portfolio's usual 15–20, and deliberately so: the comparison
policy *is* the product here, and every rule in the table above is a case where
a plausible alternative would silently shift every accuracy number in the report.
Thirty tests cover `compare.py` alone.

The stub provider matters for the same reason — it drives correct, wrong, and
broken answers deterministically, so CI exercises the full scoring path rather
than just importing it.

---

## What This Does Not Measure

Stated plainly, because a benchmark that overstates its scope is worse than none:

- **Not schema retrieval.** Three tables fit comfortably in a prompt, so
  choosing the relevant ones is trivial. The prompt variants measure how much
  *column detail* a model needs, not table selection. Retrieval only becomes the
  bottleneck at roughly forty tables.
- **Not query quality.** A correct result from a full table scan scores the same
  as a correct result from an indexed lookup. There is no cost model here.
- **Not generalization.** 24 questions over one schema. It compares
  configurations against each other; it does not predict accuracy on your data.
- **Not determinism.** Sampling parameters were removed on current Claude models
  — `temperature` returns a 400 — so two runs of the same configuration can
  differ. A small accuracy gap between models is not automatically a real one.

---

## Project Comparison

`data-engineer-finance-analytics` builds the warehouse this benchmark queries,
and verifies its own AI-written market briefing against the data it was given.
That is a **grounding check** — does the prose match the numbers, on one live
system. This repo is the other half: a **capability benchmark**, measuring
models against a fixed task on frozen data. One protects a running pipeline; the
other decides which model to point at it.

---

## License

MIT
