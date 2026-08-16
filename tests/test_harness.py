"""Tests for the question set, taxonomy, providers, runner, and report."""

import json

import pytest

from evals.compare import Comparison
from evals.providers import PRICING, StubProvider, Usage, build_provider, extract_sql
from evals.questions import Question, answer_key, load_questions, validate
from evals.report import build_report
from evals.runner import run_sweep
from evals.schema import PromptVariant, build_prompt, introspect, render_schema
from evals.taxonomy import Failure, classify_error, classify_mismatch, is_retryable
from evals.warehouse import connect, run_query


@pytest.fixture(scope="module")
def con():
    connection = connect()
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def questions():
    return load_questions()


# ── The question set ──────────────────────────────────────────────────────────

def test_the_committed_question_set_is_valid(questions):
    assert len(questions) >= 20
    assert validate(questions) == []


def test_every_reference_query_executes_and_returns_rows(con, questions):
    """A reference that returns nothing scores every candidate as correct if the
    candidate also returns nothing -- an empty reference is a broken question."""
    for question in questions:
        result = run_query(con, question.sql)
        assert len(result) > 0, f"{question.id} reference returned no rows"


def test_every_reference_query_passes_the_read_only_guard(con, questions):
    for question in questions:
        run_query(con, question.sql)  # raises UnsafeSQLError if it would not


def test_validation_catches_duplicate_ids():
    problems = validate([
        Question("q1", "a?", "SELECT 1"),
        Question("q1", "b?", "SELECT 2"),
    ])
    assert any("duplicate" in p for p in problems)


def test_validation_catches_an_unknown_difficulty():
    problems = validate([Question("q1", "a?", "SELECT 1", difficulty="trivial")])
    assert any("difficulty" in p for p in problems)


def test_validation_catches_a_comma_inside_a_feature_tag():
    """'[a, b]' written as one string would create a phantom grouping key."""
    problems = validate([Question("q1", "a?", "SELECT 1", features=["join, window"])])
    assert any("comma" in p for p in problems)


# ── Taxonomy ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("message,expected", [
    ('Parser Error: syntax error at or near "FRM"', Failure.SYNTAX_ERROR),
    ("Catalog Error: Table with name nope does not exist!", Failure.UNKNOWN_TABLE),
    ("Binder Error: Referenced column \"nope\" not found", Failure.UNKNOWN_COLUMN),
    ("Conversion Error: Could not convert string to double", Failure.TYPE_ERROR),
    ("Out of Memory Error: failed to allocate", Failure.EXECUTION_ERROR),
])
def test_database_errors_map_to_failure_classes(message, expected):
    assert classify_error(message) is expected


def test_a_matching_comparison_is_not_a_failure():
    assert classify_mismatch(Comparison(True)) is Failure.NONE


def test_an_ordering_mismatch_is_its_own_class():
    """A missing ORDER BY is a much milder error than wrong rows."""
    assert classify_mismatch(
        Comparison(False, "correct rows in the wrong order", order_only=True)
    ) is Failure.WRONG_ORDER


def test_a_shape_mismatch_is_distinguished_from_wrong_values():
    assert classify_mismatch(Comparison(False, "expected 2 column(s), got 1")) is Failure.WRONG_SHAPE
    assert classify_mismatch(Comparison(False, "row 0 differs")) is Failure.WRONG_VALUES


def test_only_failures_the_database_explained_are_retryable():
    assert is_retryable(Failure.SYNTAX_ERROR)
    assert is_retryable(Failure.UNKNOWN_COLUMN)
    # Nothing to feed back for a wrong-but-valid query, so retrying just resamples.
    assert not is_retryable(Failure.WRONG_VALUES)
    assert not is_retryable(Failure.WRONG_ORDER)
    assert not is_retryable(Failure.TIMEOUT)


# ── SQL extraction ────────────────────────────────────────────────────────────

def test_extracts_bare_sql_unchanged():
    assert extract_sql("SELECT 1") == "SELECT 1"


def test_extracts_sql_from_a_fenced_block():
    assert extract_sql("Here you go:\n```sql\nSELECT 1\n```\n") == "SELECT 1"


def test_extracts_sql_after_a_sentence_of_preamble():
    assert extract_sql("Sure! Here is the query:\nSELECT ticker FROM t") == (
        "SELECT ticker FROM t"
    )


def test_strips_a_trailing_semicolon():
    """The guard rejects multi-statement input, so a trailing ';' would
    otherwise score a correct query as unsafe."""
    assert extract_sql("SELECT 1;") == "SELECT 1"


def test_keeps_a_leading_cte():
    assert extract_sql("```\nWITH x AS (SELECT 1) SELECT * FROM x\n```").startswith("WITH")


# ── Cost accounting ───────────────────────────────────────────────────────────

def test_cost_uses_per_model_rates():
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert usage.cost_usd("claude-opus-5") == pytest.approx(30.0)
    assert usage.cost_usd("claude-haiku-4-5") == pytest.approx(6.0)


def test_cached_input_is_billed_at_a_fraction_of_full_input():
    cached = Usage(cache_read_tokens=1_000_000).cost_usd("claude-opus-5")
    uncached = Usage(input_tokens=1_000_000).cost_usd("claude-opus-5")
    assert cached == pytest.approx(uncached * 0.1)


def test_a_cache_write_costs_more_than_plain_input():
    write = Usage(cache_write_tokens=1_000_000).cost_usd("claude-opus-5")
    assert write == pytest.approx(Usage(input_tokens=1_000_000).cost_usd("claude-opus-5") * 1.25)


def test_an_unknown_model_reports_zero_rather_than_guessing():
    assert Usage(input_tokens=1_000).cost_usd("stub-v1") == 0.0


# ── Providers ─────────────────────────────────────────────────────────────────

def test_the_stub_is_deterministic(questions):
    stub = StubProvider(answer_key(questions))
    prompt = build_prompt(questions[0].question, "schema")
    first = stub.complete("sys", prompt)
    second = stub.complete("sys", prompt)
    assert first.text == second.text


def test_the_stub_produces_correct_wrong_and_broken_answers(questions):
    stub = StubProvider(answer_key(questions))
    answers = {
        q.id: stub.complete("sys", build_prompt(q.question, "schema")).text
        for q in questions
    }
    exact = sum(answers[q.id] == q.sql for q in questions)
    assert 0 < exact < len(questions), "the stub must exercise both paths"


def test_build_provider_rejects_an_unknown_model():
    with pytest.raises(ValueError, match="unknown model"):
        build_provider("gpt-4", {})


def test_build_provider_returns_the_stub_without_credentials():
    assert isinstance(build_provider("stub", {}), StubProvider)


def test_every_priced_model_is_a_claude_id():
    assert all(name.startswith("claude-") for name in PRICING)


# ── Schema rendering ──────────────────────────────────────────────────────────

def test_prompt_variants_increase_in_detail(con):
    tables = introspect(con)
    names = render_schema(tables, PromptVariant.NAMES_ONLY)
    full = render_schema(tables, PromptVariant.FULL)
    samples = render_schema(tables, PromptVariant.FULL_WITH_SAMPLES, con)
    assert len(names) < len(full) < len(samples)
    assert "close_price" not in names and "close_price" in full


def test_sample_rows_are_deterministic(con):
    """A varying sample would change the prompt between runs and make the
    comparison between models unfair."""
    tables = introspect(con)
    first = render_schema(tables, PromptVariant.FULL_WITH_SAMPLES, con)
    second = render_schema(tables, PromptVariant.FULL_WITH_SAMPLES, con)
    assert first == second


# ── End to end ────────────────────────────────────────────────────────────────

def test_a_full_stub_sweep_runs_and_scores(con, questions):
    provider = StubProvider(answer_key(questions))
    result = run_sweep(
        con, questions[:8], provider, [PromptVariant.FULL], progress=False
    )
    assert len(result.attempts) == 8
    assert 0.0 < result.accuracy < 1.0, "the stub should produce both outcomes"
    assert all(a.sql for a in result.attempts if a.failure != "no_sql")


def test_the_sweep_records_a_failure_class_for_every_wrong_answer(con, questions):
    provider = StubProvider(answer_key(questions))
    result = run_sweep(con, questions[:8], provider, [PromptVariant.FULL], progress=False)
    for attempt in result.attempts:
        if attempt.correct:
            assert attempt.failure == "none"
        else:
            assert attempt.failure != "none" and attempt.detail


def test_the_report_builds_from_a_run(con, questions):
    provider = StubProvider(answer_key(questions))
    result = run_sweep(con, questions[:8], provider, [PromptVariant.FULL], progress=False)
    run = {
        "generated_at": "2026-08-16T00:00:00+00:00",
        "fixture": "fixture",
        "question_count": 8,
        "models": ["stub-v1"],
        "variants": ["full"],
        "attempts": [a.to_dict() for a in result.attempts],
    }
    report = build_report(run)
    assert "Text-to-SQL evaluation" in report
    assert "Accuracy by SQL feature" in report
    # The run must round-trip through JSON, since that is how it is committed.
    assert json.loads(json.dumps(run))["attempts"]
