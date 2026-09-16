"""multi-protocol devices (wireguard/openvpn alongside vless)

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscription_devices",
        sa.Column("protocol", sa.String(length=16), nullable=False, server_default="vless"),
    )
    op.add_column("subscription_devices", sa.Column("raw_config", sa.String(), nullable=True))
    op.alter_column("subscription_devices", "client_uuid", existing_type=sa.String(length=64), nullable=True)
    op.alter_column("subscription_devices", "xui_email", existing_type=sa.String(length=128), nullable=True)
    op.alter_column("subscription_devices", "vless_uri", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    op.alter_column("subscription_devices", "vless_uri", existing_type=sa.String(), nullable=False)
    op.alter_column("subscription_devices", "xui_email", existing_type=sa.String(length=128), nullable=False)
    op.alter_column("subscription_devices", "client_uuid", existing_type=sa.String(length=64), nullable=False)
    op.drop_column("subscription_devices", "raw_config")
    op.drop_column("subscription_devices", "protocol")
