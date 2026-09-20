"""hysteria2 device password column

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-20
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscription_devices",
        sa.Column("hysteria_password", sa.String(length=64), nullable=True),
    )
    op.create_unique_constraint(
        "uq_devices_hysteria_password", "subscription_devices", ["hysteria_password"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_devices_hysteria_password", "subscription_devices", type_="unique")
    op.drop_column("subscription_devices", "hysteria_password")
