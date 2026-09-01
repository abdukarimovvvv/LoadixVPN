from __future__ import annotations

import uuid as uuidlib
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Referral(Base):
    __tablename__ = "referrals"
    __table_args__ = (CheckConstraint("referrer_id <> referee_id", name="ck_referrals_no_self"),)

    id: Mapped[uuidlib.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuidlib.uuid4)
    referrer_id: Mapped[uuidlib.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    referee_id: Mapped[uuidlib.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    first_payment_id: Mapped[uuidlib.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("payments.id", ondelete="SET NULL"), nullable=True
    )
    bonus_days_granted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bonus_granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
