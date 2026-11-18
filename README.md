# Text-to-SQL Evals

A benchmark that measures whether a language model can turn a question into working SQL. It runs the generated query against a frozen DuckDB warehouse and compares the result set with the result of a reference query. SQL text is never compared.

```
question + schema -> model -> SQL -> guarded execution -> result-set comparison -> failure class -> report
```

Three providers sit behind one interface: Claude through the Anthropic SDK, a local model served by Ollama, and a deterministic stub that needs no network. The committed results come from a local `llama3.2` run. No hosted sweep has been committed.

## Running it

Python 3.11 or later is required. Dependencies are managed with [uv](https://docs.astral.sh/uv/).

```bash
uv sync --group dev                              # duckdb, pyyaml, pytest
uv run pytest tests/ -v                          # the test suite
uv run python main.py run --model stub --dry-run # full pipeline, offline, writes nothing
```

`python main.py run` without `--dry-run` overwrites `results/latest-run.json` and `REPORT.md`, including the committed llama3.2 results. Restore them with `git checkout results/latest-run.json REPORT.md`.

A sweep against a local model needs a running [Ollama](https://ollama.com) daemon and no API key. This is the command that produced the committed report:

```bash
ollama pull llama3.2
uv run python main.py run --model ollama:llama3.2
```

A hosted sweep needs the `anthropic` package and a credential, and is billed:

```bash
uv sync --group live
export ANTHROPIC_API_KEY=...

uv run python main.py run --model claude-opus-5
uv run python main.py run --model claude-sonnet-5 --variant full --limit 5
```

The accepted hosted model IDs are the keys of `PRICING` in `evals/providers.py`: `claude-opus-5`, `claude-opus-4-8`, `claude-sonnet-5` and `claude-haiku-4-5`.

| Command or flag | Effect |
|---|---|
| `main.py run` | Run a sweep and write `results/latest-run.json` and `REPORT.md` |
| `main.py report` | Rebuild `REPORT.md` from the saved run without calling a model |
| `--model` | `stub` (default), `ollama:<model>`, or a hosted model ID |
| `--variant` | Prompt variant, repeatable. Defaults to all three |
| `--difficulty` | Only `easy`, `medium` or `hard` questions |
| `--limit N` | Only the first N questions |
| `--retries N` | Retries after a retryable database error (default 1) |
| `--timeout S` | Per-query time budget in seconds (default 15) |
| `--effort` | `output_config.effort` for the hosted provider (default `high`). Not sent to `claude-haiku-4-5`, which has no effort parameter |
| `--dry-run` | Run the sweep and write nothing |

## How it works

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

| Path | Contents |
|---|---|
| `evals/warehouse.py` | Loads the fixture, read-only guard, query timeout |
| `evals/compare.py` | Result-set comparison policy |
| `evals/taxonomy.py` | Failure classes and which of them are retried |
| `evals/schema.py` | Schema introspection, the three prompt variants, the system prompt |
| `evals/providers.py` | Anthropic, Ollama and stub providers, SQL extraction, cost calculation |
| `evals/questions.py` | Question loading and validation |
| `evals/runner.py` | The sweep: generate, execute, compare, score, retry |
| `evals/report.py` | Run JSON to `REPORT.md` |
| `questions/questions.yaml` | 24 questions with reference SQL, a difficulty and feature tags |
| `fixture/*.parquet` | The frozen warehouse (508 KB) |
| `results/latest-run.json` | The committed run |
| `main.py` | CLI |

### The fixture

The warehouse is a committed snapshot of the marts layer of [`data-engineer-finance-analytics`](https://github.com/calemccammon/data-engineer-finance-analytics), a star schema of daily equity prices joined to macroeconomic series.

| Table | Rows | Columns |
|---|---|---|
| `fct_daily_trading` | 5,010 | 33 |
| `dim_company` | 10 | 12 |
| `dim_date` | 2,922 | 20 |

The fact table covers 2024-06-20 to 2026-06-18. An eval run against data that changes cannot distinguish a model regression from a data change, so the fixture is pinned as Parquet and every run queries the same bytes. `tests/test_warehouse.py` asserts the date span and row count, so replacing the fixture fails CI.

### Prompt variants

How much schema to send is treated as a measured axis. Each question is asked once per variant.

| Variant | Schema text sent |
|---|---|
| `names_only` | Table names and row counts |
| `full` | Every column with its type |
| `full_with_samples` | `full`, plus three sample rows per table showing the first six columns |

The schema is read from the live connection through `information_schema`, and sample rows are selected with a fixed `ORDER BY` so the prompt is identical on every run. The schema text is appended to the system prompt, and the user message holds only the question.

### Comparison policy

`evals/compare.py` decides what counts as the same result.

| Rule | Reason |
|---|---|
| Row order matters only if the reference has a top-level `ORDER BY` | A database may return unordered rows in any order, so requiring a match would fail correct queries at random. `ORDER BY` inside `OVER (...)` or a subquery does not count. |
| Rows compare as a multiset | Collapsing duplicates would let a query that forgot `GROUP BY` pass. |
| Columns align by name when the two name sets match (ignoring case and punctuation), otherwise by position | A different alias is formatting. A value in the wrong column is an error. Sorting the values within each row would forgive both, so rows are never sorted internally. |
| Numbers compare within an absolute and relative tolerance of 1e-6 | Summing in a different order changes the last bits of a float. `Decimal` values are compared as floats. |
| NULL equals NULL | Two answers that are both absent agree, whatever SQL's three-valued logic says. |
| A boolean matches an exact 1 or 0, with no tolerance | `CAST(is_weekend AS INT)` is a formatting choice. A value that only rounds to 1 is not a match. |
| A `DATE` equals a `DATETIME` on the same day, and strings are compared after trimming whitespace | These are differences of representation. |

A mismatch where the right rows come back in the wrong sequence is recorded separately from wrong rows.

### Failure classes and retry

Every wrong answer gets a class, so the report shows what to change and not only a score.

| Class | Meaning | Retried |
|---|---|---|
| `syntax_error`, `unknown_table`, `unknown_column`, `type_error`, `execution_error` | DuckDB raised an error, classified by matching its message | yes |
| `wrong_shape` | Wrong row or column count | no |
| `wrong_order` | Right rows, wrong sequence | no |
| `wrong_values` | Valid query, wrong answer | no |
| `timeout`, `refused_unsafe` | The query overran its budget or the guard rejected it | no |
| `no_sql` | The provider call failed, the model declined, or the response held no query | no |

When a query fails with a database error, the model is prompted again with the error text appended. The default is one retry (`--retries`). A query that runs and returns the wrong answer produces no error to feed back, so it is not retried.

### Handling generated SQL

Generated SQL is treated as untrusted input. Three measures apply, in `evals/warehouse.py`:

- **Guard.** After comments are stripped, the text must be a single statement that begins with `SELECT` or `WITH` and contains none of a list of keywords covering writes, schema changes, `ATTACH`, `COPY`, `PRAGMA`, `SET` and the `read_csv`, `read_parquet` and `read_json` functions. Comment markers and semicolons inside quoted strings are treated as text, so `SELECT '--'; DROP TABLE dim_company` is refused as two statements. `REPLACE` is refused as a keyword and allowed when a bracket follows it, as in the `REPLACE()` string function. The query that runs is the comment-stripped text the guard inspected.
- **Isolation.** The Parquet files are copied into in-memory tables and `enable_external_access` is then set to false. There is no database file, and the connection cannot read the filesystem.
- **Timeout.** Each query runs on a worker thread with a 15-second budget and is interrupted if it overruns, so a runaway cross join is scored as `timeout`.

The guard's false positives are listed under Limitations.

### Providers and cost

All providers return the same `Completion` record, and the runner does not branch on which one produced it.

- **Stub** answers from the reference SQL. Keyed on the question text, it returns the reference unchanged, a wrong-but-valid variant, or a query against a table that does not exist. CI uses it to run the scoring path end to end.
- **Ollama** posts to `/api/chat` with the standard library. Temperature is set to 0 and the seed is fixed. `OLLAMA_HOST` overrides the default `http://localhost:11434`.
- **Anthropic** calls `messages.create` with `output_config.effort` and no sampling parameters, and marks the system block, which holds the instructions and the schema, with `cache_control`. The code comments give the reason for omitting sampling parameters: `temperature`, `top_p` and `top_k` are rejected with a 400 on Claude Opus 5, Sonnet 5 and Opus 4.8/4.7. API errors and refusals are recorded as `no_sql` failures and do not stop the sweep.

Each attempt records input, output, cache-read and cache-write tokens, latency and cost. Cost is computed from the per-model list prices in `PRICING`, with cache reads at 0.1x and cache writes at 1.25x the input rate. Models without a price entry, including every Ollama model, cost 0. The report shows total and per-variant cost and p50 and p95 latency.

Results are committed as JSON and the report is a pure function of that file. CI regenerates `REPORT.md` from the committed run and fails if it differs.

## Results

The committed [`REPORT.md`](REPORT.md) is a sweep of `llama3.2` through Ollama: 22 of 72 correct (30.6%). The 72 attempts took 114 model calls including retries, and about six minutes of generation time.

| Variant | Correct |
|---|---|
| `names_only` | 1/24 |
| `full` | 10/24 |
| `full_with_samples` | 11/24 |

- **Column names are the main constraint.** 28 of the 50 failures (56%) are `unknown_column`, and the guesses are near-misses such as `company` for `company_name` and `date` for `trading_date`. Given only table names, the model invents plausible column names and the binder rejects them.
- **Sample rows added one correct answer** over `full`, for a longer prompt.
- **Joins and CTEs failed every time**: 0/9 on questions tagged `join` and 0/3 on `cte`.
- **Feeding the error back rarely helped.** 42 attempts hit a retryable error and were re-prompted, and 2 then succeeded.
- **Accuracy falls with the difficulty label**: 9/18 easy, 9/33 medium, 4/21 hard.

These figures describe one small local model on 24 questions over one schema. The run was made with the schema in the user message. It is now sent in the system prompt, so a new run of the same command may not reproduce these numbers exactly.

## Testing

The suite has 107 test cases and needs no network, credential or database file. 28 of them cover `compare.py`, one or more per rule in the comparison policy. The rest cover the read-only guard and timeout, the fixture's row count and date span, error classification, SQL extraction, cost arithmetic, question validation, the Ollama provider through an injected transport, the retry path through a scripted provider, and stub sweeps through the runner and report.

CI (`.github/workflows/ci.yml`) runs the tests, checks that `REPORT.md` matches the committed run, and runs a stub sweep with `--dry-run`.

The Anthropic provider has no tests.

## Limitations

- **Prompt caching is unmeasured.** The API ignores a cache marker on a prefix shorter than a model-dependent minimum, without an error. Whether the system prompt and schema reach that minimum for a given model and variant has not been measured. The report does not show cache token counts, which are only in the run JSON.
- **No hosted run has been committed.** The Anthropic provider and the cost figures have not been exercised in the committed results.
- **Hosted runs are not reproducible.** No temperature or seed is sent on the hosted path, so two runs of the same configuration can differ and a small accuracy gap between models may be noise. Ollama runs pin both.
- **The guard is a keyword filter over text.** It rejects valid reads that contain a listed word anywhere, including inside a string literal such as `'call'`, and scores them as `refused_unsafe`.
- **Schema retrieval is not measured.** Three tables fit in a prompt, so the variants measure how much column detail a model needs, not table selection.
- **Query quality is not measured.** A correct result from a full scan scores the same as any other correct result.
- **The question set is small.** 24 questions over one schema can compare configurations with each other. They do not predict accuracy on other data.

## Data

The fixture data originates from Yahoo Finance (via `yfinance`) and FRED, by way of the `data-engineer-finance-analytics` warehouse. It is a small historical slice included as a test fixture.
