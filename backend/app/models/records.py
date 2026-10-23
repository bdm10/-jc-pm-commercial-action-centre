"""Application records (PostgreSQL schema `app`): users, teams, opportunities,
actions, follow-ups, assignment overrides, configuration and audit history.

App records reference customers by natural key (source_entity,
source_customer_id) rather than by foreign key to `facts`, so that replacing a
facts snapshot never deletes user work.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.facts import JSONType

SCHEMA = "app"

ACTIVE_OPPORTUNITY_STATUSES = ("open", "in_progress", "snoozed")


class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))  # sales | manager | admin
    salesperson_code: Mapped[str | None] = mapped_column(String(60), unique=True, nullable=True)
    entra_object_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Team(Base):
    __tablename__ = "team"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)


class TeamMember(Base):
    __tablename__ = "team_member"
    __table_args__ = {"schema": SCHEMA}

    team_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.team.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.app_user.id"), primary_key=True)


class TeamManager(Base):
    __tablename__ = "team_manager"
    __table_args__ = {"schema": SCHEMA}

    team_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.team.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.app_user.id"), primary_key=True)


class AssignmentOverride(Base):
    """A reassignment made in the app. The latest non-superseded row wins over the imported baseline."""

    __tablename__ = "assignment_override"
    __table_args__ = (
        Index("ix_override_customer", "source_entity", "source_customer_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_entity: Mapped[str] = mapped_column(String(8))
    source_customer_id: Mapped[str] = mapped_column(String(60))
    user_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.app_user.id"))
    assigned_by_user_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.app_user.id"))
    reason: Mapped[str | None] = mapped_column(String(280), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    superseded_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RuleConfig(Base):
    """Versioned rule parameters. Every version is provisional until the business approves it."""

    __tablename__ = "rule_config"
    __table_args__ = {"schema": SCHEMA}

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    params: Mapped[dict] = mapped_column(JSONType)
    approval_status: Mapped[str] = mapped_column(String(20), default="provisional")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.app_user.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Opportunity(Base):
    __tablename__ = "opportunity"
    __table_args__ = (
        # At most one active opportunity per customer and type: no duplicate alerts.
        Index(
            "uq_opportunity_active",
            "source_entity",
            "source_customer_id",
            "opp_type",
            unique=True,
            postgresql_where=text("status IN ('open','in_progress','snoozed')"),
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_entity: Mapped[str] = mapped_column(String(8))
    source_customer_id: Mapped[str] = mapped_column(String(60))
    opp_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))  # open | in_progress | snoozed | dismissed | resolved
    condition_active: Mapped[bool] = mapped_column(Boolean, default=True)
    priority_score: Mapped[float] = mapped_column(Float)
    priority_band: Mapped[str] = mapped_column(String(10))  # high | medium | low
    priority_components: Mapped[dict] = mapped_column(JSONType, default=dict)
    reason_code: Mapped[str] = mapped_column(String(60))
    reason_params: Mapped[dict] = mapped_column(JSONType, default=dict)
    evidence: Mapped[list] = mapped_column(JSONType, default=list)
    rule_version: Mapped[str] = mapped_column(String(20))
    config_version: Mapped[int] = mapped_column(Integer)
    data_refreshed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    first_detected_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_evaluated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_action_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snoozed_until: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    snooze_reason: Mapped[str | None] = mapped_column(String(280), nullable=True)
    dismissed_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    dismissed_note: Mapped[str | None] = mapped_column(String(280), nullable=True)
    dismissed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.app_user.id"), nullable=True)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_code: Mapped[str | None] = mapped_column(String(40), nullable=True)


class Activity(Base):
    """An action a salesperson completed. Completing an action is not a customer outcome."""

    __tablename__ = "activity"
    __table_args__ = (
        Index("ix_activity_customer", "source_entity", "source_customer_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_request_id: Mapped[str] = mapped_column(String(64), unique=True)  # idempotent submits
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.opportunity.id"), nullable=True)
    source_entity: Mapped[str] = mapped_column(String(8))
    source_customer_id: Mapped[str] = mapped_column(String(60))
    user_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.app_user.id"))
    action_type: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(String(280), nullable=True)
    follow_up_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FollowUp(Base):
    __tablename__ = "follow_up"
    __table_args__ = (
        Index("ix_follow_up_owner_status", "owner_user_id", "status", "due_date"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_entity: Mapped[str] = mapped_column(String(8))
    source_customer_id: Mapped[str] = mapped_column(String(60))
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.opportunity.id"), nullable=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.app_user.id"))
    due_date: Mapped[dt.date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | done | cancelled
    created_by_activity_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.activity.id"), nullable=True)
    closed_by_activity_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.activity.id"), nullable=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ObservedOutcome(Base):
    """A later order observed in the source data after an action.

    This is an *observed post-action result*, not proof of incremental uplift:
    no approved attribution method exists.
    """

    __tablename__ = "observed_outcome"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.opportunity.id"), unique=True)
    source_entity: Mapped[str] = mapped_column(String(8))
    source_customer_id: Mapped[str] = mapped_column(String(60))
    outcome_code: Mapped[str] = mapped_column(String(40))
    first_action_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    observed_document_date: Mapped[dt.date] = mapped_column(Date)
    observed_document_ref: Mapped[str] = mapped_column(String(60))
    detected_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    """Append-only audit trail for every change to application records."""

    __tablename__ = "audit_log"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.app_user.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(120))
    detail: Mapped[dict] = mapped_column(JSONType, default=dict)
