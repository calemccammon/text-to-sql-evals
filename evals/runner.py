"""The sweep: generate, execute, compare, score.

One attempt per (question, prompt variant), with a bounded retry when the
database returned an error the model could act on. Everything a later stage
needs -- the SQL, the failure class, tokens, cost, latency -- is recorded on the
attempt, so the report is a pure function of the run and re-reporting never
needs the model again.
"""

import time
from dataclasses import asdict, dataclass, field
from typing import Any

import duckdb

from .compare import Comparison, compare_results, has_top_level_order_by
from .providers import Completion, Provider, Usage, extract_sql
from .questions import Question
from .schema import PromptVariant, SYSTEM_PROMPT, build_prompt, introspect, render_schema
from .taxonomy import Failure, classify_error, classify_mismatch, is_retryable
from .warehouse import QueryResult, QueryTimeout, UnsafeSQLError, run_query

MAX_RETRIES = 1


@dataclass
class Attempt:
    question_id: str
    difficulty: str
    features: list[str]
    model: str
    variant: str
    sql: str
    correct: bool
    failure: str
    detail: str = ""
    attempts: int = 1
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunResult:
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        if not self.attempts:
            return 0.0
        return sum(a.correct for a in self.attempts) / len(self.attempts)

    @property
    def total_cost(self) -> float:
        return sum(a.cost_usd for a in self.attempts)


def _execute(con: duckdb.DuckDBPyConnection, sql: str, timeout: float):
    """Run candidate SQL, returning either a result or a (failure, message)."""
    try:
        return run_query(con, sql, timeout=timeout), None
    except UnsafeSQLError as exc:
        return None, (Failure.REFUSED_UNSAFE, str(exc))
    except QueryTimeout as exc:
        return None, (Failure.TIMEOUT, str(exc))
    except Exception as exc:  # noqa: BLE001 -- any DB error is a scored outcome
        return None, (classify_error(str(exc)), str(exc))


def run_question(
    con: duckdb.DuckDBPyConnection,
    question: Question,
    provider: Provider,
    variant: PromptVariant,
    schema_text: str,
    reference: QueryResult,
    ordered: bool,
    timeout: float = 15.0,
    max_retries: int = MAX_RETRIES,
) -> Attempt:
    prompt = build_prompt(question.question, schema_text)
    usage_total = Usage()
    latency_total = 0.0
    tries = 0
    completion: Completion | None = None
    failure = Failure.NONE
    detail = ""
    sql = ""

    while tries <= max_retries:
        tries += 1
        completion = provider.complete(SYSTEM_PROMPT, prompt)
        usage_total = Usage(
            usage_total.input_tokens + completion.usage.input_tokens,
            usage_total.output_tokens + completion.usage.output_tokens,
            usage_total.cache_read_tokens + completion.usage.cache_read_tokens,
            usage_total.cache_write_tokens + completion.usage.cache_write_tokens,
        )
        latency_total += completion.latency_ms

        if completion.refused or completion.error:
            failure, detail = Failure.NO_SQL, completion.error or "refused"
            break

        sql = extract_sql(completion.text)
        if not sql:
            failure, detail = Failure.NO_SQL, "no SQL in response"
            break

        result, problem = _execute(con, sql, timeout)
        if problem is None:
            comparison: Comparison = compare_results(result, reference, ordered)
            failure = classify_mismatch(comparison)
            detail = comparison.reason
            break

        failure, detail = problem
        # Retry only when the database said something specific enough to act on.
        # A wrong-but-valid query returns no error to feed back, so retrying it
        # just resamples at full price.
        if not is_retryable(failure) or tries > max_retries:
            break
        prompt = (
            f"{build_prompt(question.question, schema_text)}\n\n"
            f"A previous attempt failed with this database error:\n{detail}\n\n"
            "Write the query again, corrected."
        )

    model = completion.model if completion else provider.model
    return Attempt(
        question_id=question.id,
        difficulty=question.difficulty,
        features=list(question.features),
        model=model,
        variant=variant.value,
        sql=sql,
        correct=failure is Failure.NONE,
        failure=str(failure),
        detail=detail[:300],
        attempts=tries,
        input_tokens=usage_total.input_tokens,
        output_tokens=usage_total.output_tokens,
        cache_read_tokens=usage_total.cache_read_tokens,
        cache_write_tokens=usage_total.cache_write_tokens,
        cost_usd=usage_total.cost_usd(model),
        latency_ms=latency_total,
    )


def run_sweep(
    con: duckdb.DuckDBPyConnection,
    questions: list[Question],
    provider: Provider,
    variants: list[PromptVariant],
    timeout: float = 15.0,
    max_retries: int = MAX_RETRIES,
    progress: bool = True,
) -> RunResult:
    tables = introspect(con)
    rendered = {v: render_schema(tables, v, con) for v in variants}

    # Reference results are computed once and reused across every variant and
    # model in the sweep -- they cannot change, since the fixture is frozen.
    references: dict[str, tuple[QueryResult, bool]] = {}
    for question in questions:
        references[question.id] = (
            run_query(con, question.sql, timeout=timeout),
            has_top_level_order_by(question.sql),
        )

    result = RunResult()
    started = time.perf_counter()
    for variant in variants:
        for index, question in enumerate(questions, start=1):
            reference, ordered = references[question.id]
            attempt = run_question(
                con, question, provider, variant, rendered[variant],
                reference, ordered, timeout=timeout, max_retries=max_retries,
            )
            result.attempts.append(attempt)
            if progress:
                mark = "ok  " if attempt.correct else "FAIL"
                print(
                    f"  [{variant.value}] {index:>2}/{len(questions)} "
                    f"{question.id} {mark} {attempt.failure}"
                )

    if progress:
        elapsed = time.perf_counter() - started
        print(
            f"  {len(result.attempts)} attempts, "
            f"accuracy {result.accuracy:.1%}, "
            f"${result.total_cost:.4f}, {elapsed:.1f}s"
        )
    return result
