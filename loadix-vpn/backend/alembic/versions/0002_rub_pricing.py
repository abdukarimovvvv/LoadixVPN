"""rename price_usd -> price_rub, default payment currency RUB

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("plans", "price_usd", new_column_name="price_rub")
    op.alter_column(
        "payments",
        "currency",
        existing_type=sa.String(length=16),
        server_default=sa.text("'RUB'"),
    )
    op.execute("UPDATE payments SET currency='RUB' WHERE currency='USDT'")


def downgrade() -> None:
    op.execute("UPDATE payments SET currency='USDT' WHERE currency='RUB'")
    op.alter_column(
        "payments",
        "currency",
        existing_type=sa.String(length=16),
        server_default=sa.text("'USDT'"),
    )
    op.alter_column("plans", "price_rub", new_column_name="price_usd")