"""Tests for the correctness judgment.

Every decision the benchmark makes about whether an answer is right passes
through compare_results, so the policy in evals/compare.py is pinned here case
by case. A silent change to any of these would move every accuracy number in
the report without failing anything else.
"""

from datetime import date, datetime
from decimal import Decimal

import pytest

from evals.compare import (
    compare_results,
    has_top_level_order_by,
    values_equal,
)
from evals.warehouse import QueryResult


def R(columns: list[str], rows: list[tuple]) -> QueryResult:
    return QueryResult(columns=columns, rows=rows)


# ── Ordering ──────────────────────────────────────────────────────────────────

def test_detects_a_top_level_order_by():
    assert has_top_level_order_by("SELECT a FROM t ORDER BY a")


def test_ignores_order_by_inside_a_window_function():
    """RANK() OVER (ORDER BY x) does not order the result set."""
    sql = "SELECT RANK() OVER (ORDER BY close DESC) AS r FROM t"
    assert not has_top_level_order_by(sql)


def test_ignores_order_by_inside_a_subquery():
    sql = "SELECT * FROM (SELECT a FROM t ORDER BY a) x"
    assert not has_top_level_order_by(sql)


def test_finds_a_top_level_order_by_alongside_a_window_function():
    sql = "SELECT RANK() OVER (PARTITION BY s ORDER BY c DESC) r FROM t ORDER BY s, r"
    assert has_top_level_order_by(sql)


def test_ignores_order_by_inside_a_comment():
    assert not has_top_level_order_by("SELECT a FROM t -- ORDER BY a\n")


# ── Unordered comparison is a multiset ────────────────────────────────────────

def test_row_order_is_irrelevant_when_the_reference_is_unordered():
    candidate = R(["t"], [("B",), ("A",)])
    reference = R(["t"], [("A",), ("B",)])
    assert compare_results(candidate, reference, ordered=False)


def test_row_order_matters_when_the_reference_is_ordered():
    candidate = R(["t"], [("B",), ("A",)])
    reference = R(["t"], [("A",), ("B",)])
    result = compare_results(candidate, reference, ordered=True)
    assert not result
    assert result.order_only, "right rows, wrong sequence should be distinguishable"


def test_duplicate_rows_are_significant():
    """Comparing as a set would let a query that forgot GROUP BY pass."""
    candidate = R(["t"], [("A",), ("A",)])
    reference = R(["t"], [("A",), ("B",)])
    assert not compare_results(candidate, reference, ordered=False)


# ── Column alignment ──────────────────────────────────────────────────────────

def test_columns_align_by_name_when_names_match():
    candidate = R(["close", "ticker"], [(1.0, "A")])
    reference = R(["ticker", "close"], [("A", 1.0)])
    assert compare_results(candidate, reference, ordered=False)


def test_column_names_match_ignoring_case_and_punctuation():
    candidate = R(["Total_Volume"], [(5,)])
    reference = R(["totalvolume"], [(5,)])
    assert compare_results(candidate, reference, ordered=False)


def test_falls_back_to_position_when_names_do_not_match():
    """Different aliases are a formatting choice, not a wrong answer."""
    candidate = R(["a", "b"], [("A", 1.0)])
    reference = R(["ticker", "close"], [("A", 1.0)])
    assert compare_results(candidate, reference, ordered=False)


def test_values_in_the_wrong_columns_are_wrong():
    """Sorting each row's values -- which some harnesses do -- would pass this."""
    candidate = R(["a", "b"], [(1.0, 2.0)])
    reference = R(["x", "y"], [(2.0, 1.0)])
    assert not compare_results(candidate, reference, ordered=False)


def test_duplicate_column_names_fall_back_to_position():
    candidate = R(["c", "c"], [(1, 2)])
    reference = R(["c", "c"], [(1, 2)])
    assert compare_results(candidate, reference, ordered=False)


# ── Shape ─────────────────────────────────────────────────────────────────────

def test_wrong_column_count_is_reported_as_such():
    result = compare_results(R(["a"], [(1,)]), R(["a", "b"], [(1, 2)]), ordered=False)
    assert not result
    assert "column" in result.reason


def test_wrong_row_count_is_reported_as_such():
    result = compare_results(R(["a"], [(1,)]), R(["a"], [(1,), (2,)]), ordered=False)
    assert not result
    assert "row" in result.reason


# ── Value semantics ───────────────────────────────────────────────────────────

def test_floats_compare_within_tolerance():
    """Summing in a different order changes the last bits."""
    assert values_equal(0.1 + 0.2, 0.3)
    assert values_equal(1e9, 1e9 + 0.0001)


def test_genuinely_different_numbers_are_not_equal():
    assert not values_equal(1.0, 1.01)


def test_int_and_float_of_the_same_value_are_equal():
    assert values_equal(5, 5.0)


def test_decimal_compares_as_a_number():
    assert values_equal(Decimal("2.50"), 2.5)


def test_null_equals_null_but_not_zero():
    assert values_equal(None, None)
    assert not values_equal(None, 0)
    assert not values_equal(0, None)


def test_a_date_equals_a_midnight_datetime_for_the_same_day():
    assert values_equal(date(2026, 6, 18), datetime(2026, 6, 18, 0, 0))


def test_strings_compare_after_stripping_surrounding_whitespace():
    assert values_equal(" AAPL ", "AAPL")
    assert not values_equal("AAPL", "MSFT")


def test_a_boolean_matches_an_exact_1_or_0_but_never_by_tolerance():
    """CAST(is_weekend AS INT) is a formatting choice, like aliasing a column,
    so an exact 1/0 matches. Tolerance is withheld: a boolean must not match a
    value that merely rounds to 1, which is why bool is excluded from the
    numeric branch rather than from comparison entirely."""
    assert values_equal(True, 1)
    assert values_equal(False, 0)
    assert not values_equal(True, 1.0000001)
    assert not values_equal(True, 0)


# ── Whole-result behaviour ────────────────────────────────────────────────────

def test_a_scalar_answer_compares_correctly():
    assert compare_results(R(["n"], [(10,)]), R(["count"], [(10,)]), ordered=False)
    assert not compare_results(R(["n"], [(11,)]), R(["count"], [(10,)]), ordered=False)


def test_empty_results_match_each_other():
    assert compare_results(R(["a"], []), R(["a"], []), ordered=False)


def test_the_mismatch_reason_names_the_first_differing_row():
    result = compare_results(
        R(["a"], [(1,), (99,)]), R(["a"], [(1,), (2,)]), ordered=True
    )
    assert not result
    assert "row 1 differs" in result.reason


@pytest.mark.parametrize("ordered", [True, False])
def test_identical_results_always_match(ordered):
    rows = [("A", 1.5, date(2026, 1, 1)), ("B", None, date(2026, 1, 2))]
    assert compare_results(R(["t", "v", "d"], rows), R(["t", "v", "d"], rows), ordered)
