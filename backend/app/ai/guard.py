"""Output guard for AI drafts.

An AI draft is accepted only if:
  * every point cites at least one fact ID that was actually supplied;
  * every number in the text matches a number present in the supplied facts
    (so the model cannot calculate or invent figures);
  * it does not mention prices, discounts, rappels, stock availability,
    promises, contact details or "lost" customers.
Otherwise it is rejected and the deterministic template is shown instead.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

MAX_POINTS = 5
MAX_POINT_CHARS = 300

FORBIDDEN = re.compile(
    r"descuent|discount|rappel|precio|price|tarifa|promoci|promotion|oferta especial|special offer|"
    r"disponibilidad|availability|en stock|in stock|garantiz|guarantee|perdid[oa]|lost customer|"
    r"https?://|www\.|@[a-z0-9-]+\.",
    re.IGNORECASE,
)
NUMBER = re.compile(r"\d[\d.,]*\d|\d")


def _allowed_numbers(facts: list[dict[str, Any]]) -> set[float]:
    allowed: set[float] = set()

    def add_num(v: float) -> None:
        for x in (v, abs(v)):
            allowed.update({round(x, 2), float(round(x)), round(x, 1)})
            if abs(x) >= 1000:
                allowed.update({float(round(x / 1000)), round(x / 1000, 1)})

    def add_any(v: Any) -> None:
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            add_num(float(v))
        elif isinstance(v, str):
            try:
                d = dt.date.fromisoformat(v[:10])
                allowed.update({float(d.year), float(d.month), float(d.day), float(d.year % 100)})
                return
            except ValueError:
                pass
            for tok in NUMBER.findall(v):
                for val in _interpretations(tok):
                    add_num(val)
        elif isinstance(v, dict):
            for x in v.values():
                add_any(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                add_any(x)

    for f in facts:
        add_any(f.get("value"))
        add_any(f.get("period"))
    return allowed


def _interpretations(token: str) -> set[float]:
    token = token.strip(".,")
    out: set[float] = set()
    for t in (token.replace(".", "").replace(",", "."), token.replace(",", ""), token):
        try:
            out.add(float(t))
        except ValueError:
            continue
    return out


def check(points: list[dict[str, Any]], facts: list[dict[str, Any]]) -> tuple[bool, str]:
    if not points:
        return False, "empty_output"
    if len(points) > MAX_POINTS:
        return False, "too_many_points"
    fact_ids = {f["id"] for f in facts}
    allowed = _allowed_numbers(facts)
    for i, p in enumerate(points):
        text = str(p.get("text", ""))
        cited = p.get("fact_ids") or []
        if not text.strip() or len(text) > MAX_POINT_CHARS:
            return False, f"point_{i}_length"
        if not cited or any(c not in fact_ids for c in cited):
            return False, f"point_{i}_uncited_or_unknown_fact"
        if FORBIDDEN.search(text):
            return False, f"point_{i}_forbidden_topic"
        for tok in NUMBER.findall(text):
            if not any(any(abs(v - a) < 0.051 for a in allowed) for v in _interpretations(tok)):
                return False, f"point_{i}_number_not_in_facts:{tok}"
    return True, "passed"
