"""allow bid rows without a campaign

Revision ID: 0003_bid_campaign_nullable
Revises: 0002_analytics_rollup
Create Date: 2026-10-15 00:00:00

The auction persists one bid row per DSP outcome, including timeouts and
no-bids, so the bid table is a complete per-DSP record of every auction.
Those outcomes have no campaign, and the previous NOT NULL foreign key made
every auction with a timed-out DSP fail on insert. campaign_id is now NULL
for outcomes that never named a known campaign.
"""
from alembic import op

revision = "0003_bid_campaign_nullable"
down_revision = "0002_analytics_rollup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE bid ALTER COLUMN campaign_id DROP NOT NULL")


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("DELETE FROM bid WHERE campaign_id IS NULL")
    connection.exec_driver_sql("ALTER TABLE bid ALTER COLUMN campaign_id SET NOT NULL")
