"""add auction_minute_rollup

Revision ID: 0002_analytics_rollup
Revises: 0001_initial_schema
Create Date: 2026-01-02 00:00:00

Adds the per-minute analytics rollup table maintained asynchronously by the
Kafka analytics consumer (see app/events/consumers/analytics_consumer.py and
docs/architecture.md Section 6's "extension point" note, now implemented).
"""
from alembic import op

revision = "0002_analytics_rollup"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None

DDL_UP = """
CREATE TABLE auction_minute_rollup (
    minute_bucket       TIMESTAMPTZ PRIMARY KEY,
    total_auctions      BIGINT NOT NULL DEFAULT 0,
    completed_auctions  BIGINT NOT NULL DEFAULT 0,
    no_bid_auctions     BIGINT NOT NULL DEFAULT 0,
    failed_auctions     BIGINT NOT NULL DEFAULT 0,
    sum_winning_bid     NUMERIC(14, 4) NOT NULL DEFAULT 0,
    count_winning_bid   BIGINT NOT NULL DEFAULT 0,
    bucket_5            BIGINT NOT NULL DEFAULT 0,
    bucket_10           BIGINT NOT NULL DEFAULT 0,
    bucket_20           BIGINT NOT NULL DEFAULT 0,
    bucket_30           BIGINT NOT NULL DEFAULT 0,
    bucket_50           BIGINT NOT NULL DEFAULT 0,
    bucket_75           BIGINT NOT NULL DEFAULT 0,
    bucket_100          BIGINT NOT NULL DEFAULT 0,
    bucket_150          BIGINT NOT NULL DEFAULT 0,
    bucket_200          BIGINT NOT NULL DEFAULT 0,
    bucket_300          BIGINT NOT NULL DEFAULT 0,
    bucket_500          BIGINT NOT NULL DEFAULT 0,
    bucket_1000         BIGINT NOT NULL DEFAULT 0,
    bucket_inf          BIGINT NOT NULL DEFAULT 0
);

-- Time-range scans ("last N minutes") are the only access pattern this
-- table serves; the primary key on minute_bucket already supports that
-- as a btree range scan, so no separate index is needed.
"""

DDL_DOWN = "DROP TABLE IF EXISTS auction_minute_rollup;"


def _strip_sql_comments(ddl: str) -> str:
    """See 0001_initial_schema.py for why this is duplicated here rather
    than imported from a shared module."""
    return "\n".join(
        line for line in ddl.splitlines() if not line.strip().startswith("--")
    )


def _execute_statements(ddl: str) -> None:
    connection = op.get_bind()
    cleaned = _strip_sql_comments(ddl)
    for statement in cleaned.split(";"):
        statement = statement.strip()
        if statement:
            connection.exec_driver_sql(statement)


def upgrade() -> None:
    _execute_statements(DDL_UP)


def downgrade() -> None:
    _execute_statements(DDL_DOWN)