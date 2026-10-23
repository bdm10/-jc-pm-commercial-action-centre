"""AI-generated explanations and drafts (PostgreSQL schema `ai`).

Kept apart from facts and application records. Every suggestion stores the
exact facts it was given, so a reader can see what supports each point.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.facts import JSONType

SCHEMA = "ai"


class Suggestion(Base):
    __tablename__ = "suggestion"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_entity: Mapped[str] = mapped_column(String(8))
    source_customer_id: Mapped[str] = mapped_column(String(60))
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("app.opportunity.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(30))  # talking_points
    provider: Mapped[str] = mapped_column(String(30))  # template | anthropic
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(20))
    language: Mapped[str] = mapped_column(String(5))
    facts_used: Mapped[list] = mapped_column(JSONType)
    output: Mapped[list] = mapped_column(JSONType)
    guard_status: Mapped[str] = mapped_column(String(20))  # passed | rejected | not_applicable
    guard_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("app.app_user.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
