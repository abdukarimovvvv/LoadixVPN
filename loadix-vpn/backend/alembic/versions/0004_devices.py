"""subscription devices (multi-key per subscription)

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription_devices",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "subscription_id",
            UUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_uuid", sa.String(length=64), nullable=False),
        sa.Column("xui_email", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=True),
        sa.Column("vless_uri", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("client_uuid", name="uq_devices_client_uuid"),
        sa.UniqueConstraint("xui_email", name="uq_devices_xui_email"),
    )
    op.create_index("ix_devices_subscription_id", "subscription_devices", ["subscription_id"])

    op.execute(
        """
        INSERT INTO subscription_devices (id, subscription_id, client_uuid, xui_email, name, vless_uri, created_at)
        SELECT gen_random_uuid(), id, client_uuid, xui_email, 'Устройство 1', vless_uri, created_at
        FROM subscriptions
        WHERE client_uuid IS NOT NULL
        """
    )

    op.drop_constraint("uq_subscriptions_client_uuid", "subscriptions", type_="unique")
    op.drop_constraint("uq_subscriptions_xui_email", "subscriptions", type_="unique")
    op.drop_column("subscriptions", "client_uuid")
    op.drop_column("subscriptions", "xui_email")
    op.drop_column("subscriptions", "vless_uri")


def downgrade() -> None:
    op.add_column("subscriptions", sa.Column("client_uuid", sa.String(length=64), nullable=True))
    op.add_column("subscriptions", sa.Column("xui_email", sa.String(length=128), nullable=True))
    op.add_column("subscriptions", sa.Column("vless_uri", sa.String(), nullable=True))
    op.execute(
        """
        UPDATE subscriptions s SET
            client_uuid = d.client_uuid,
            xui_email = d.xui_email,
            vless_uri = d.vless_uri
        FROM subscription_devices d
        WHERE d.subscription_id = s.id
        """
    )
    op.create_unique_constraint("uq_subscriptions_client_uuid", "subscriptions", ["client_uuid"])
    op.create_unique_constraint("uq_subscriptions_xui_email", "subscriptions", ["xui_email"])
    op.drop_index("ix_devices_subscription_id", table_name="subscription_devices")
    op.drop_table("subscription_devices")
