"""Deciding whether generated SQL produced the right answer.

This is the whole benchmark. Everything else is plumbing, and every judgement
call about correctness lives here -- which is why the policy is written down
rather than left implicit in a pile of conditionals.

The metric is execution accuracy: run the candidate, run the reference, compare
the result sets. That is deliberately not string comparison against the
reference SQL. There are many correct ways to write a query, and a benchmark
that rewards writing it one particular way measures imitation instead of
correctness.

The policy, and why each part is what it is:

* **Row order matters only if the reference asked for it.** If the reference has
  a top-level ORDER BY, the question implied an ordering and the candidate must
  reproduce it. Otherwise rows compare as a multiset -- a database is free to
  return unordered rows in any order, so demanding a match would fail correct
  queries at random.
* **Multiset, not set.** Duplicate rows are significant. Collapsing them would
  let a query that forgot a GROUP BY pass.
* **Columns align by name when names allow it, otherwise by position.** Aliasing
  a column differently is a formatting choice; putting a value in the wrong
  column is a real error. Sorting each row's values -- which some harnesses do --
  would forgive both, so this does not do that.
* **Floats compare with tolerance.** Summing in a different order changes the
  last bits. Exact equality would score arithmetic identity, not correctness.
* **NULL equals NULL.** SQL's own three-valued logic says otherwise, but here we
  are comparing answers, and two results that are both absent agree.
* **Booleans match an exact 1 or 0, never a tolerance.** Casting a boolean to an
  integer is a formatting choice like aliasing; matching something that merely
  rounds to 1 would not be.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from .warehouse import QueryResult, strip_sql_comments

# Absolute floor covers values near zero; the relative term covers large ones.
ABS_TOLERANCE = 1e-6
REL_TOLERANCE = 1e-6


@dataclass(frozen=True)
class Comparison:
    match: bool
    reason: str = ""
    #  Set when the results differ only by row ordering -- a distinct, and much
    #  milder, failure than returning the wrong rows.
    order_only: bool = False

    def __bool__(self) -> bool:
        return self.match


def has_top_level_order_by(sql: str) -> bool:
    """True if the query itself is ordered, ignoring ORDER BY inside brackets.

    Window functions (`OVER (ORDER BY ...)`) and subqueries both put ORDER BY in
    parentheses without ordering the result, so parenthesised groups are removed
    before looking.
    """
    text = strip_sql_comments(sql)
    previous = None
    # Repeatedly strip innermost bracket pairs until none remain.
    while previous != text:
        previous = text
        text = re.sub(r"\([^()]*\)", " ", text)
    return re.search(r"\border\s+by\b", text, re.IGNORECASE) is not None


def _normalise(value):
    """Reduce a cell to a comparable form without losing meaning."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.replace(microsecond=0)
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    return value


def values_equal(left, right) -> bool:
    """Compare two cells under the policy above."""
    left, right = _normalise(left), _normalise(right)

    if left is None or right is None:
        return left is None and right is None

    left_numeric = isinstance(left, (int, float)) and not isinstance(left, bool)
    right_numeric = isinstance(right, (int, float)) and not isinstance(right, bool)
    if left_numeric and right_numeric:
        difference = abs(float(left) - float(right))
        scale = max(abs(float(left)), abs(float(right)))
        return difference <= max(ABS_TOLERANCE, REL_TOLERANCE * scale)

    # A DATE and a DATETIME at midnight describe the same day.
    if isinstance(left, (date, datetime)) and isinstance(right, (date, datetime)):
        left_day = left.date() if isinstance(left, datetime) else left
        right_day = right.date() if isinstance(right, datetime) else right
        return left_day == right_day

    return left == right


def _column_permutation(candidate: list[str], reference: list[str]) -> list[int] | None:
    """Index into the candidate for each reference column, matched by name.

    Returns None when names cannot be matched one-to-one, which is the signal to
    fall back to positional comparison.
    """
    def key(name: str) -> str:
        return re.sub(r"[^a-z0-9]", "", name.lower())

    candidate_keys = [key(c) for c in candidate]
    reference_keys = [key(c) for c in reference]
    if len(set(candidate_keys)) != len(candidate_keys):
        return None  # duplicate names -- positional is the only safe reading
    if set(candidate_keys) != set(reference_keys):
        return None
    lookup = {name: index for index, name in enumerate(candidate_keys)}
    return [lookup[name] for name in reference_keys]


def _rows_equal(left: tuple, right: tuple) -> bool:
    return len(left) == len(right) and all(values_equal(a, b) for a, b in zip(left, right))


def _sort_key(row: tuple) -> tuple:
    """Order rows deterministically for multiset comparison.

    Sorts on a type tag first so mixed types never compare against each other,
    and rounds floats into the tolerance band so two values that count as equal
    also sort together.
    """
    key = []
    for value in row:
        value = _normalise(value)
        if value is None:
            key.append((0, ""))
        elif isinstance(value, bool):
            key.append((1, str(value)))
        elif isinstance(value, (int, float)):
            key.append((2, f"{round(float(value), 6):.6f}"))
        elif isinstance(value, (date, datetime)):
            key.append((3, value.isoformat()))
        else:
            key.append((4, str(value)))
    return tuple(key)


def compare_results(
    candidate: QueryResult,
    reference: QueryResult,
    ordered: bool,
) -> Comparison:
    """Compare a candidate result against the reference under the stated policy."""
    if len(candidate.columns) != len(reference.columns):
        return Comparison(
            False,
            f"expected {len(reference.columns)} column(s), got {len(candidate.columns)}",
        )
    if len(candidate.rows) != len(reference.rows):
        return Comparison(
            False, f"expected {len(reference.rows)} row(s), got {len(candidate.rows)}"
        )

    permutation = _column_permutation(candidate.columns, reference.columns)
    if permutation is not None:
        candidate_rows = [tuple(row[i] for i in permutation) for row in candidate.rows]
    else:
        candidate_rows = [tuple(row) for row in candidate.rows]
    reference_rows = [tuple(row) for row in reference.rows]

    in_order = all(_rows_equal(a, b) for a, b in zip(candidate_rows, reference_rows))
    if ordered:
        if in_order:
            return Comparison(True)
        # Distinguish "right rows, wrong sequence" from "wrong rows" -- the
        # first is a missing ORDER BY, the second is a wrong query.
        sorted_match = all(
            _rows_equal(a, b)
            for a, b in zip(
                sorted(candidate_rows, key=_sort_key),
                sorted(reference_rows, key=_sort_key),
            )
        )
        if sorted_match:
            return Comparison(False, "correct rows in the wrong order", order_only=True)
        return Comparison(False, _first_difference(candidate_rows, reference_rows))

    if in_order:
        return Comparison(True)
    candidate_sorted = sorted(candidate_rows, key=_sort_key)
    reference_sorted = sorted(reference_rows, key=_sort_key)
    if all(_rows_equal(a, b) for a, b in zip(candidate_sorted, reference_sorted)):
        return Comparison(True)
    return Comparison(False, _first_difference(candidate_sorted, reference_sorted))


def _first_difference(candidate: list[tuple], reference: list[tuple]) -> str:
    for index, (got, expected) in enumerate(zip(candidate, reference)):
        if not _rows_equal(got, expected):
            return f"row {index} differs: expected {expected!r}, got {got!r}"
    return "results differ"
