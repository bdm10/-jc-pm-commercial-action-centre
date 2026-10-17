"""Read-only commercial facts (PostgreSQL schema `facts`).

Only the importer writes here. Each import replaces the snapshot for the source
entities in its manifest. The API only reads these tables.

Customer identity is always (source_entity, source_customer_id). JC and PM
records are never merged; a link between them exists only through an
*approved* row in `customer_mapping`.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

SCHEMA = "facts"
JSONType = JSON().with_variant(JSONB(), "postgresql")


class ImportRun(Base):
    __tablename__ = "import_run"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    package_label: Mapped[str] = mapped_column(String(200))
    checksum: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))  # loaded | rejected
    summary: Mapped[dict] = mapped_column(JSONType, default=dict)


class SourceRefresh(Base):
    """One row per source entity per import: where the data came from and how fresh it is."""

    __tablename__ = "source_refresh"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.import_run.id"))
    source_entity: Mapped[str] = mapped_column(String(8))
    source_model: Mapped[str] = mapped_column(String(120))
    source_refreshed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    period_start: Mapped[dt.date] = mapped_column(Date)
    period_end: Mapped[dt.date] = mapped_column(Date)
    extract_grain: Mapped[str] = mapped_column(String(200))
    data_classification: Mapped[str] = mapped_column(String(20))  # synthetic | anonymised | live
    filters_applied: Mapped[str] = mapped_column(String(500))


class MeasureDefinition(Base):
    __tablename__ = "measure_definition"
    __table_args__ = {"schema": SCHEMA}

    measure_code: Mapped[str] = mapped_column(String(60), primary_key=True)
    display_name_es: Mapped[str] = mapped_column(String(120))
    display_name_en: Mapped[str] = mapped_column(String(120))
    certified_measure_name: Mapped[str] = mapped_column(String(200))
    source_model: Mapped[str] = mapped_column(String(120))
    source_entity: Mapped[str] = mapped_column(String(8))
    business_definition: Mapped[str] = mapped_column(Text)
    certification_status: Mapped[str] = mapped_column(String(20))  # certified | provisional | synthetic
    unit: Mapped[str] = mapped_column(String(10))
    additive_over_months: Mapped[bool] = mapped_column(Boolean)
    approved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    approved_at: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    run_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.import_run.id"))


class Customer(Base):
    __tablename__ = "customer"
    __table_args__ = (UniqueConstraint("source_entity", "source_customer_id"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_entity: Mapped[str] = mapped_column(String(8))
    source_customer_id: Mapped[str] = mapped_column(String(60))
    display_name: Mapped[str] = mapped_column(String(200))
    channel: Mapped[str | None] = mapped_column(String(60), nullable=True)
    segment: Mapped[str | None] = mapped_column(String(60), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    province: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_intercompany: Mapped[bool] = mapped_column(Boolean, default=False)
    seasonal_flag: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    transfer_cohort: Mapped[str | None] = mapped_column(String(60), nullable=True)
    source_status: Mapped[str | None] = mapped_column(String(60), nullable=True)
    run_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.import_run.id"))


class CustomerMapping(Base):
    """Approved group mapping between a customer in one entity and one in another.

    Only rows with mapping_status == 'approved' are used by the rules engine.
    """

    __tablename__ = "customer_mapping"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mapping_ref: Mapped[str] = mapped_column(String(60), unique=True)
    from_entity: Mapped[str] = mapped_column(String(8))
    from_customer_id: Mapped[str] = mapped_column(String(60))
    to_entity: Mapped[str] = mapped_column(String(8))
    to_customer_id: Mapped[str] = mapped_column(String(60))
    transfer_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    cohort: Mapped[str | None] = mapped_column(String(60), nullable=True)
    mapping_status: Mapped[str] = mapped_column(String(20))  # approved | provisional | rejected
    approved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    approved_at: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    run_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.import_run.id"))


class Assignment(Base):
    """Account ownership as supplied by the source (baseline; managers may override in app)."""

    __tablename__ = "assignment"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_entity: Mapped[str] = mapped_column(String(8))
    source_customer_id: Mapped[str] = mapped_column(String(60))
    salesperson_code: Mapped[str] = mapped_column(String(60))
    valid_from: Mapped[dt.date] = mapped_column(Date)
    valid_to: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    run_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.import_run.id"))


class MeasureMonthly(Base):
    """A certified measure evaluated by the source at customer x month grain."""

    __tablename__ = "measure_monthly"
    __table_args__ = (
        UniqueConstraint("source_entity", "record_key"),
        UniqueConstraint("source_entity", "source_customer_id", "measure_code", "month"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_entity: Mapped[str] = mapped_column(String(8))
    source_customer_id: Mapped[str] = mapped_column(String(60))
    measure_code: Mapped[str] = mapped_column(String(60))
    month: Mapped[dt.date] = mapped_column(Date)  # first day of month
    value: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    record_key: Mapped[str] = mapped_column(String(120))
    run_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.import_run.id"))


class Purchase(Base):
    """Document line (invoice or credit note). Used for dates, counts and evidence.

    `amount` is only displayed when supplied with a registered measure code; the
    app never derives sales or margin from quantity x price.
    """

    __tablename__ = "purchase"
    __table_args__ = (UniqueConstraint("source_entity", "record_key"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_entity: Mapped[str] = mapped_column(String(8))
    record_key: Mapped[str] = mapped_column(String(120))
    source_customer_id: Mapped[str] = mapped_column(String(60))
    document_date: Mapped[dt.date] = mapped_column(Date)
    document_type: Mapped[str] = mapped_column(String(20))  # invoice | credit_note
    document_ref: Mapped[str] = mapped_column(String(60))
    brand: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(60), nullable=True)
    sku_description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(60), nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    amount_measure_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    run_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.import_run.id"))


class DataIssue(Base):
    """Data-quality findings. Shown as data issues, never as customer-risk recommendations."""

    __tablename__ = "data_issue"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stage: Mapped[str] = mapped_column(String(20))  # import | refresh
    run_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.import_run.id"), nullable=True)
    detected_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    severity: Mapped[str] = mapped_column(String(10))  # error | warning | info
    issue_code: Mapped[str] = mapped_column(String(60))
    source_entity: Mapped[str | None] = mapped_column(String(8), nullable=True)
    source_customer_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    detail: Mapped[dict] = mapped_column(JSONType, default=dict)
