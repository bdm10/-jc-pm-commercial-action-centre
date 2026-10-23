"""Conversation points: deterministic templates (always) plus an optional AI draft.

Templates are returned as i18n keys + parameters so the frontend renders them
in the user's language. AI drafts are free text, validated by the guard, and
stored with the exact facts they were given (schema `ai`).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.ai import guard
from app.ai.provider import PROMPT_VERSION, ProviderError, get_provider
from app.config import get_settings
from app.models.ai import Suggestion
from app.models.records import Opportunity

LABELS = {
    "es": {
        "ev.transfer_date": "Fecha de transferencia",
        "ev.days_since_transfer": "Días desde la transferencia",
        "ev.orders_since_transfer": "Pedidos en la entidad receptora desde la transferencia",
        "ev.orders_before_transfer": "Pedidos en la entidad de origen en los 12 meses previos",
        "ev.last_order_before_transfer": "Último pedido en la entidad de origen",
        "ev.pre_transfer_12m_value": "Ventas en la entidad de origen, 12 meses previos a la transferencia",
        "ev.current_window_value": "Ventas en el periodo actual",
        "ev.prior_window_value": "Ventas en el mismo periodo del año anterior",
        "ev.change_pct": "Variación (%)",
        "ev.abs_change": "Variación (importe)",
        "ev.last_order": "Último pedido",
        "ev.prior_12m_value": "Ventas 12 meses (referencia)",
        "ev.days_since_last": "Días desde el último pedido",
        "ev.typical_interval": "Intervalo habitual entre pedidos (días)",
        "ev.orders_in_lookback": "Pedidos en el periodo analizado",
        "ev.expected_by": "Fecha esperada del siguiente pedido",
        "ev.last_12m_value": "Ventas últimos 12 meses",
        "customer.name": "Cliente",
        "customer.entity": "Entidad",
    },
    "en": {
        "ev.transfer_date": "Transfer date",
        "ev.days_since_transfer": "Days since transfer",
        "ev.orders_since_transfer": "Orders in the receiving entity since transfer",
        "ev.orders_before_transfer": "Orders in the origin entity in the previous 12 months",
        "ev.last_order_before_transfer": "Last order in the origin entity",
        "ev.pre_transfer_12m_value": "Sales in the origin entity, 12 months before transfer",
        "ev.current_window_value": "Sales in the current period",
        "ev.prior_window_value": "Sales in the same period last year",
        "ev.change_pct": "Change (%)",
        "ev.abs_change": "Change (amount)",
        "ev.last_order": "Last order",
        "ev.prior_12m_value": "12-month sales (reference)",
        "ev.days_since_last": "Days since last order",
        "ev.typical_interval": "Usual interval between orders (days)",
        "ev.orders_in_lookback": "Orders in the period analysed",
        "ev.expected_by": "Expected next order date",
        "ev.last_12m_value": "Sales, last 12 months",
        "customer.name": "Customer",
        "customer.entity": "Entity",
    },
}


def build_facts(customer: dict[str, Any], opps: list[Opportunity], language: str) -> list[dict[str, Any]]:
    labels = LABELS.get(language, LABELS["es"])
    facts: list[dict[str, Any]] = [
        {"id": "c.name", "label": labels["customer.name"], "value": customer["display_name"]},
        {"id": "c.entity", "label": labels["customer.entity"], "value": customer["source_entity"]},
    ]
    for o in opps:
        for e in o.evidence:
            prov = e.get("provenance", {})
            facts.append({
                "id": f"o{o.id}.{e['id']}",
                "label": labels.get(e["label_key"], e["label_key"]),
                "value": e["value"],
                "unit": e.get("unit"),
                "entity": e.get("entity"),
                "period": prov.get("period"),
                "status": prov.get("certification_status"),
            })
    return facts


def template_points(opps: list[Opportunity]) -> list[dict[str, Any]]:
    pts: list[dict[str, Any]] = []
    for o in opps:
        p = o.reason_params

        def f(eid: str, oid: int = o.id) -> str:
            return f"o{oid}.{eid}"

        if o.opp_type == "transfer_no_reorder":
            pts += [
                {"key": "tp.transfer.welcome", "params": {"to_entity": p["to_entity"], "transfer_date": p["transfer_date"]}, "fact_ids": [f("e1")]},
                {"key": "tp.transfer.history", "params": {"from_entity": p["from_entity"]}, "fact_ids": [f("e4"), f("e5")]},
                {"key": "tp.transfer.first_order", "params": {"to_entity": p["to_entity"]}, "fact_ids": [f("e3")]},
            ]
        elif o.opp_type == "declining_purchases":
            pts += [
                {"key": "tp.decline.change", "params": {"entity": p["entity"], "change_pct": p["change_pct"],
                                                         "current_start": p["current_start"], "current_end": p["current_end"]},
                 "fact_ids": [f("e1"), f("e2"), f("e3")]},
                {"key": "tp.decline.ask", "params": {}, "fact_ids": [f("e1")]},
            ]
        elif o.opp_type == "overdue_cadence":
            pts += [
                {"key": "tp.overdue.timing", "params": {"typical": p["typical_interval_days"], "last_order_date": p["last_order_date"]},
                 "fact_ids": [f("e1"), f("e3")]},
                {"key": "tp.overdue.next_date", "params": {}, "fact_ids": [f("e5")]},
            ]
    if pts:
        pts.append({"key": "tp.general.no_commitments", "params": {}, "fact_ids": []})
    return pts


def ai_points(db: Session, customer: dict[str, Any], opps: list[Opportunity], notes: list[str], language: str,
              user_id: int) -> dict[str, Any]:
    """Returns {"status": ..., "points": [...], "facts": [...]}. Never raises for provider problems."""
    settings = get_settings()
    provider = get_provider(settings)
    facts = build_facts(customer, opps, language)
    if provider is None:
        return {"status": "not_configured", "points": [], "facts": facts}
    if not opps:
        return {"status": "no_evidence", "points": [], "facts": facts}
    try:
        points = provider.talking_points(facts, notes, language)
        ok, detail = guard.check(points, facts)
    except ProviderError as exc:
        points, ok, detail = [], False, f"provider_error:{exc}"
    db.add(Suggestion(source_entity=customer["source_entity"], source_customer_id=customer["source_customer_id"],
                      opportunity_id=opps[0].id, kind="talking_points", provider=provider.name, model=provider.model,
                      prompt_version=PROMPT_VERSION, language=language, facts_used=facts, output=points,
                      guard_status="passed" if ok else "rejected", guard_detail=detail, created_by_user_id=user_id))
    db.commit()
    if not ok:
        return {"status": "rejected", "detail": detail, "points": [], "facts": facts}
    return {"status": "ok", "points": points, "facts": facts, "provider": provider.name, "model": provider.model}
