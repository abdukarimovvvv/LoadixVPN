"""stars pricing + unlimited traffic + new plans

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-20
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) add price_stars to plans
    op.add_column("plans", sa.Column("price_stars", sa.Integer(), nullable=False, server_default="0"))

    # 2) deactivate legacy paid plans (week/month/quarter w/ RUB-only pricing)
    op.execute("UPDATE plans SET is_active = false WHERE code IN ('week','month','quarter')")

    # 2.1) bump Trial traffic to 5 GB
    op.execute("UPDATE plans SET traffic_limit_gb = 5 WHERE code = 'trial'")

    # 3) insert new Stars-only plans (codes prefixed s_ to avoid colliding with legacy)
    op.execute(
        """
        INSERT INTO plans (id, code, name, price_rub, price_stars, duration_days, traffic_limit_gb, device_limit, is_active, is_trial)
        VALUES
          (gen_random_uuid(), 's_30',  '30 дней',  0, 100, 30, 0, 3, true, false),
          (gen_random_uuid(), 's_45',  '45 дней',  0, 150, 45, 0, 4, true, false),
          (gen_random_uuid(), 's_90',  '90 дней',  0, 300, 90, 0, 5, true, false)
        ON CONFLICT (code) DO UPDATE SET
          name = EXCLUDED.name,
          price_stars = EXCLUDED.price_stars,
          duration_days = EXCLUDED.duration_days,
          traffic_limit_gb = EXCLUDED.traffic_limit_gb,
          device_limit = EXCLUDED.device_limit,
          is_active = true,
          is_trial = false
        """
    )

    # 4) migrate existing active paid subscriptions to new plans (free upgrade)
    #    week → s_30, month → s_45 (since old month was 2-dev, new s_45 = 4-dev),
    #    quarter → s_90 (new s_90 = 5-dev, 90 days)
    op.execute(
        """
        UPDATE subscriptions s
        SET plan_id = p.id,
            traffic_limit_gb = 0,
            device_limit = p.device_limit
        FROM plans p, plans old
        WHERE s.plan_id = old.id
          AND s.status = 'active'
          AND s.is_trial = false
          AND old.code IN ('week','month','quarter')
          AND p.code = CASE old.code
                         WHEN 'week'    THEN 's_30'
                         WHEN 'month'   THEN 's_45'
                         WHEN 'quarter' THEN 's_90'
                       END
        """
    )


def downgrade() -> None:
    # rollback: deactivate new plans, reactivate legacy
    op.execute("UPDATE plans SET is_active = false WHERE code IN ('s_30','s_45','s_90')")
    op.execute("UPDATE plans SET is_active = true WHERE code IN ('week','month','quarter')")
    op.drop_column("plans", "price_stars")
