"""Shared helper for Alembic migrations that execute hand-written, multi-
statement DDL against an asyncpg-backed connection.

Two asyncpg-specific quirks motivate this, discovered by actually running
these migrations against a live Postgres instance rather than assuming
`op.execute()` would just work:

1. asyncpg refuses to run multiple SQL statements in a single prepared
   statement -- each `CREATE TABLE ...;` etc. must be sent as its own
   `execute()` call.
2. SQLAlchemy's asyncpg dialect trips over `op.execute()` with plain DDL
   text in a way that raises a confusing
   `TypeError: expected string or bytes-like object, got NoneType`
   instead of a real error. Going through the raw connection's
   `exec_driver_sql` avoids that path entirely.

On top of that, a naive `sql.split(";")` is NOT safe if any SQL comment in
the DDL contains a semicolon in its prose (easy to do by accident when
documenting *why* a table/index exists) -- the split would cut a comment in
half and leave a syntactically invalid fragment. So comments are stripped
line-by-line *before* splitting on ';', not after.
"""
from __future__ import annotations


def strip_sql_comments(ddl: str) -> str:
    return "\n".join(
        line for line in ddl.splitlines() if not line.strip().startswith("--")
    )


def execute_multi_statement_ddl(connection, ddl: str) -> None:
    cleaned = strip_sql_comments(ddl)
    for statement in cleaned.split(";"):
        statement = statement.strip()
        if statement:
            connection.exec_driver_sql(statement)