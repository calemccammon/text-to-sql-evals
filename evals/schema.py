"""Describing the warehouse to a model.

How much schema to send is the cheapest lever in text-to-SQL and the one most
often set by guesswork, so it is a measured axis here rather than a constant.
Three variants, increasing in tokens: table names only, full columns and types,
and columns plus a few sample rows.

A note on scope, since it would be easy to overclaim: this warehouse has three
tables, so *retrieving* the relevant ones is trivial and is not what the prompt
variants measure. They measure how much column detail a model needs. Table
retrieval only starts to matter at the point where the schema no longer fits
comfortably in the prompt -- around forty tables, not three.
"""

from dataclasses import dataclass
from enum import StrEnum

import duckdb


class PromptVariant(StrEnum):
    NAMES_ONLY = "names_only"
    FULL = "full"
    FULL_WITH_SAMPLES = "full_with_samples"


@dataclass(frozen=True)
class Column:
    name: str
    type: str


@dataclass(frozen=True)
class Table:
    name: str
    columns: list[Column]
    row_count: int


def introspect(con: duckdb.DuckDBPyConnection) -> list[Table]:
    """Read the live schema rather than hard-coding it.

    The fixture is frozen, but reading it here means a regenerated fixture
    cannot silently disagree with the prompt the model was given.
    """
    names = [
        row[0]
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables ORDER BY table_name"
        ).fetchall()
    ]
    tables = []
    for name in names:
        columns = [
            Column(row[0], row[1])
            for row in con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = ? ORDER BY ordinal_position",
                [name],
            ).fetchall()
        ]
        count = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        tables.append(Table(name=name, columns=columns, row_count=count))
    return tables


def _sample_rows(con: duckdb.DuckDBPyConnection, table: str, limit: int = 3) -> list[tuple]:
    # Ordered rather than arbitrary: the sample must be identical on every run,
    # or the prompt changes between runs and the comparison stops being fair.
    columns = con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = ? ORDER BY ordinal_position",
        [table],
    ).fetchall()
    order = ", ".join(f'"{c[0]}"' for c in columns[:3])
    return con.execute(f'SELECT * FROM "{table}" ORDER BY {order} LIMIT {limit}').fetchall()


def render_schema(
    tables: list[Table],
    variant: PromptVariant,
    con: duckdb.DuckDBPyConnection | None = None,
) -> str:
    """Render the schema at the requested level of detail."""
    if variant is PromptVariant.NAMES_ONLY:
        return "\n".join(f"- {t.name} ({t.row_count} rows)" for t in tables)

    blocks = []
    for table in tables:
        lines = [f"TABLE {table.name}  -- {table.row_count} rows"]
        lines += [f"  {c.name} {c.type}" for c in table.columns]

        if variant is PromptVariant.FULL_WITH_SAMPLES and con is not None:
            names = [c.name for c in table.columns]
            lines.append("  -- sample rows:")
            for row in _sample_rows(con, table.name):
                pairs = ", ".join(
                    f"{name}={value!r}" for name, value in list(zip(names, row))[:6]
                )
                lines.append(f"  --   {pairs}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


SYSTEM_PROMPT = (
    "You translate questions into a single DuckDB SQL query.\n"
    "Return only the SQL. No explanation, no markdown fences, no trailing semicolon.\n"
    "The query must be a single read-only SELECT (a leading WITH is fine).\n"
    "Order the results only when the question asks for an ordering."
)


def build_prompt(question: str, schema_text: str) -> str:
    return (
        f"Schema:\n\n{schema_text}\n\n"
        f"Question: {question}\n\n"
        "SQL:"
    )
