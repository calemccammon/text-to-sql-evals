"""Classifying why an attempt failed.

A single accuracy number tells you a model got 62% and nothing about what to do
next. The failure mode is the actionable part: a model that mostly picks wrong
columns needs a better schema prompt, one that mostly writes invalid SQL needs a
retry loop, and one that mostly returns the right rows in the wrong order barely
needs anything.
"""

import re
from enum import StrEnum

from .compare import Comparison


class Failure(StrEnum):
    NONE = "none"
    NO_SQL = "no_sql"                    # model answered without producing a query
    REFUSED_UNSAFE = "refused_unsafe"    # guard rejected it before execution
    SYNTAX_ERROR = "syntax_error"
    UNKNOWN_TABLE = "unknown_table"
    UNKNOWN_COLUMN = "unknown_column"
    TYPE_ERROR = "type_error"
    TIMEOUT = "timeout"
    EXECUTION_ERROR = "execution_error"  # ran, but failed for another reason
    WRONG_SHAPE = "wrong_shape"          # wrong row or column count
    WRONG_ORDER = "wrong_order"          # right rows, wrong sequence
    WRONG_VALUES = "wrong_values"


# DuckDB names its error classes in the message, which is more reliable than
# matching prose that changes between releases.
_ERROR_PATTERNS: list[tuple[str, Failure]] = [
    (r"\bParser Error\b", Failure.SYNTAX_ERROR),
    (r"\bSyntax Error\b", Failure.SYNTAX_ERROR),
    (r"\bCatalog Error\b.*\b(table|view)\b", Failure.UNKNOWN_TABLE),
    (r"does not exist.*\b(table|view)\b", Failure.UNKNOWN_TABLE),
    (r"\bBinder Error\b.*\bcolumn\b", Failure.UNKNOWN_COLUMN),
    (r"Referenced column.*not found", Failure.UNKNOWN_COLUMN),
    (r"\bCatalog Error\b", Failure.UNKNOWN_TABLE),
    (r"\bConversion Error\b", Failure.TYPE_ERROR),
    (r"\bType.*mismatch\b", Failure.TYPE_ERROR),
    (r"\bBinder Error\b", Failure.EXECUTION_ERROR),
]


def classify_error(message: str) -> Failure:
    """Map a database error message to a failure class."""
    for pattern, failure in _ERROR_PATTERNS:
        if re.search(pattern, message, re.IGNORECASE | re.DOTALL):
            return failure
    return Failure.EXECUTION_ERROR


def classify_mismatch(comparison: Comparison) -> Failure:
    """Map a failed comparison to a failure class."""
    if comparison.match:
        return Failure.NONE
    if comparison.order_only:
        return Failure.WRONG_ORDER
    if "column(s)" in comparison.reason or "row(s)" in comparison.reason:
        return Failure.WRONG_SHAPE
    return Failure.WRONG_VALUES


#  The failures that come with a database error message, which is what the
#  runner feeds back on a retry. NO_SQL is not here: there was no query to run,
#  so there is no error text, and the runner stops without retrying.
RETRYABLE = frozenset({
    Failure.SYNTAX_ERROR, Failure.UNKNOWN_TABLE, Failure.UNKNOWN_COLUMN,
    Failure.TYPE_ERROR, Failure.EXECUTION_ERROR,
})


def is_retryable(failure: Failure) -> bool:
    """True when the database told us something the model could act on.

    A wrong-but-valid query returns no error to feed back, so retrying it just
    resamples -- which costs a call and usually returns the same answer.
    """
    return failure in RETRYABLE
