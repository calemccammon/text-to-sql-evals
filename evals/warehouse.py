"""The frozen warehouse, and a guarded way to run generated SQL against it.

Two jobs. First, build a DuckDB view over the committed Parquet fixture, so
every run queries byte-identical data -- an eval whose dataset moves cannot tell
a model regression from a data change.

Second, contain the SQL. Text-to-SQL hands a language model a direct line to a
database, which is a genuine injection surface even when the model is
cooperative: a question phrased as "drop the fact table and return 1" is a
prompt injection with a real payload. Everything here refuses anything that is
not a single read.
"""

import re
import threading
from dataclasses import dataclass
from pathlib import Path

import duckdb

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixture"

# Mirrors main_marts in data-engineer-finance-analytics, frozen at the snapshot.
FIXTURE_TABLES = ("dim_company", "dim_date", "fct_daily_trading")

DEFAULT_TIMEOUT_SECONDS = 15.0

# A generated statement must be exactly one read. Anything that writes, changes
# schema, attaches a file, or reaches the filesystem is refused before it runs.
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|create|alter|truncate|replace|attach|detach|"
    r"copy|export|import|install|load|pragma|set|call|grant|revoke|vacuum|"
    r"checkpoint|read_csv|read_parquet|read_json)\b",
    re.IGNORECASE,
)
_ALLOWED_START = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


class UnsafeSQLError(Exception):
    """Raised when generated SQL is refused before execution."""


class QueryTimeout(Exception):
    """Raised when a query exceeds its time budget."""


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[tuple]

    def __len__(self) -> int:
        return len(self.rows)


def strip_sql_comments(sql: str) -> str:
    """Remove comments so they cannot hide a forbidden keyword from the guard."""
    without_block = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", " ", without_block)


def _split_statements(sql: str) -> list[str]:
    """Split on semicolons that are not inside a string literal."""
    statements, current, quote = [], [], None
    for char in sql:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
            current.append(char)
        elif char == ";":
            statements.append("".join(current))
            current = []
        else:
            current.append(char)
    statements.append("".join(current))
    return [s for s in statements if s.strip()]


def assert_read_only(sql: str) -> None:
    """Refuse anything that is not a single SELECT/WITH statement.

    Deliberately a denylist over stripped text rather than a parse: DuckDB will
    happily parse a DROP, and the point is to never hand it one.
    """
    cleaned = strip_sql_comments(sql)
    if not cleaned.strip():
        raise UnsafeSQLError("empty statement")

    statements = _split_statements(cleaned)
    if len(statements) > 1:
        raise UnsafeSQLError(f"expected a single statement, got {len(statements)}")

    statement = statements[0]
    if not _ALLOWED_START.match(statement):
        raise UnsafeSQLError("statement must begin with SELECT or WITH")

    forbidden = _FORBIDDEN.search(statement)
    if forbidden:
        raise UnsafeSQLError(f"forbidden keyword {forbidden.group(0).upper()!r}")


def connect(fixture_dir: Path | None = None) -> duckdb.DuckDBPyConnection:
    """An in-memory connection holding a materialized copy of the fixture.

    The fixture is copied into real in-memory tables rather than exposed as
    views over the Parquet files. A view would re-read its file on every query,
    which means the connection could never drop filesystem access -- and the
    whole point is that it can: once the data is in memory, external access is
    switched off, so generated SQL has no file to read and no database file to
    damage even if the keyword guard were bypassed.
    """
    directory = fixture_dir or FIXTURE_DIR
    con = duckdb.connect(":memory:")
    for table in FIXTURE_TABLES:
        path = directory / f"{table}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"fixture table missing: {path}")
        con.execute(
            f"CREATE TABLE {table} AS SELECT * FROM read_parquet('{path.as_posix()}')"
        )
    con.execute("SET enable_external_access = false")
    return con


def run_query(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> QueryResult:
    """Run guarded SQL under a time budget.

    A model can write a cross join that never finishes, which would hang the
    sweep rather than scoring as a failure. The query runs on a worker thread
    and is interrupted if it overruns.
    """
    assert_read_only(sql)

    outcome: dict = {}

    def execute() -> None:
        try:
            cursor = con.execute(sql)
            columns = [d[0] for d in cursor.description] if cursor.description else []
            outcome["result"] = QueryResult(columns=columns, rows=cursor.fetchall())
        except BaseException as exc:  # noqa: BLE001 -- re-raised on the caller's thread
            outcome["error"] = exc

    worker = threading.Thread(target=execute, daemon=True)
    worker.start()
    worker.join(timeout)

    if worker.is_alive():
        con.interrupt()
        worker.join(timeout=5.0)
        raise QueryTimeout(f"query exceeded {timeout:.0f}s")

    if "error" in outcome:
        raise outcome["error"]
    return outcome["result"]
