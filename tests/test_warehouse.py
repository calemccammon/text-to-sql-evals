"""Tests for the frozen warehouse and the guard around generated SQL."""

import pytest

from evals.warehouse import (
    FIXTURE_TABLES,
    QueryTimeout,
    UnsafeSQLError,
    assert_read_only,
    connect,
    run_query,
    strip_sql_comments,
)


@pytest.fixture(scope="module")
def con():
    connection = connect()
    yield connection
    connection.close()


# ── The fixture ───────────────────────────────────────────────────────────────

def test_every_fixture_table_loads(con):
    for table in FIXTURE_TABLES:
        assert run_query(con, f"SELECT COUNT(*) FROM {table}").rows[0][0] > 0


def test_the_fixture_is_frozen(con):
    """A moving dataset would make a model regression indistinguishable from a
    data change, which is the whole reason this fixture is committed."""
    span = run_query(
        con, "SELECT MIN(trading_date), MAX(trading_date), COUNT(*) FROM fct_daily_trading"
    ).rows[0]
    assert str(span[0]) == "2024-06-20"
    assert str(span[1]) == "2026-06-18"
    assert span[2] == 5010


def test_the_connection_cannot_reach_the_filesystem(con):
    """Data is materialized in memory, so external access stays switched off."""
    with pytest.raises(Exception):
        con.execute("SELECT * FROM read_csv('/etc/passwd')")


# ── The read-only guard ───────────────────────────────────────────────────────

@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "select ticker from dim_company",
    "WITH x AS (SELECT 1 AS n) SELECT n FROM x",
    "  \n SELECT 1 ",
])
def test_accepts_a_single_read(sql):
    assert_read_only(sql) is None


@pytest.mark.parametrize("sql", [
    "DROP TABLE dim_company",
    "DELETE FROM fct_daily_trading",
    "INSERT INTO dim_company VALUES (1)",
    "UPDATE dim_company SET ticker = 'X'",
    "CREATE TABLE evil (a INT)",
    "ATTACH 'other.db'",
    "COPY dim_company TO 'out.csv'",
    "PRAGMA database_list",
])
def test_refuses_anything_that_is_not_a_read(sql):
    with pytest.raises(UnsafeSQLError):
        assert_read_only(sql)


def test_refuses_a_read_that_smuggles_a_write_after_a_semicolon():
    with pytest.raises(UnsafeSQLError, match="single statement"):
        assert_read_only("SELECT 1; DROP TABLE dim_company")


def test_refuses_a_forbidden_keyword_hidden_in_a_comment():
    """Comments are stripped before the guard runs, so a keyword cannot hide
    behind one -- and a payload commented out cannot smuggle itself past."""
    with pytest.raises(UnsafeSQLError):
        assert_read_only("SELECT 1 /* harmless */ ; DROP TABLE dim_company")


def test_refuses_reading_a_file_from_inside_a_select():
    with pytest.raises(UnsafeSQLError, match="READ_PARQUET|READ_CSV"):
        assert_read_only("SELECT * FROM read_parquet('/etc/shadow')")


def test_refuses_an_empty_statement():
    with pytest.raises(UnsafeSQLError, match="empty"):
        assert_read_only("   ")


def test_a_semicolon_inside_a_string_literal_is_not_a_separator():
    assert_read_only("SELECT 'a;b' AS s") is None


def test_strip_sql_comments_removes_both_forms():
    cleaned = strip_sql_comments("SELECT 1 -- line\n/* block */ FROM t")
    assert "line" not in cleaned and "block" not in cleaned
    assert "SELECT 1" in cleaned and "FROM t" in cleaned


# ── Execution ─────────────────────────────────────────────────────────────────

def test_run_query_returns_columns_and_rows(con):
    result = run_query(con, "SELECT ticker, sector FROM dim_company ORDER BY ticker LIMIT 2")
    assert result.columns == ["ticker", "sector"]
    assert len(result) == 2


def test_run_query_enforces_the_guard(con):
    with pytest.raises(UnsafeSQLError):
        run_query(con, "DROP TABLE dim_company")


def test_a_database_error_propagates_for_classification(con):
    with pytest.raises(Exception) as excinfo:
        run_query(con, "SELECT * FROM no_such_table")
    assert "no_such_table" in str(excinfo.value)


def test_a_runaway_query_times_out_rather_than_hanging(con):
    """A model can write a cross join that never finishes; without the timeout
    it would stall the sweep instead of scoring as a failure."""
    with pytest.raises(QueryTimeout):
        run_query(
            con,
            "SELECT COUNT(*) FROM fct_daily_trading a, fct_daily_trading b, "
            "fct_daily_trading c, fct_daily_trading d",
            timeout=1.0,
        )


def test_the_connection_still_works_after_a_timeout(con):
    """An interrupted query must not poison the session for later questions."""
    assert run_query(con, "SELECT 1").rows == [(1,)]
