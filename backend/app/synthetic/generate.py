"""Generate a clearly labelled SYNTHETIC import package for JC and PM.

Nothing here comes from company systems. Every ID starts with "SYN-", every
product/brand carries "(SINT)", measures are registered with
certification_status=synthetic and the manifest says data_classification=synthetic.

The package deliberately contains realistic positive cases, near-miss
negatives and data-quality problems (duplicates, unmapped / provisional /
ambiguous mappings, same-name customers that are NOT the same account,
intercompany accounts, negative months, unassigned accounts, seasonal
accounts with and without a seasonal flag).
"""

from __future__ import annotations

import csv
import datetime as dt
import random
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from app.importer.contract import FILES_BY_NAME
from app.rules.engine import add_months, month_start

SALES_CODES = ("SYN-SP-01", "SYN-SP-02", "SYN-SP-03", "SYN-SP-04", "SYN-SP-05")
CITIES = [("Barcelona", "Barcelona"), ("Sabadell", "Barcelona"), ("Girona", "Girona"), ("Tarragona", "Tarragona"),
          ("Sitges", "Barcelona"), ("Reus", "Tarragona"), ("Lleida", "Lleida"), ("Mataró", "Barcelona"),
          ("Terrassa", "Barcelona"), ("Figueres", "Girona")]
PREFIXES = ["Restaurante", "Bar", "Hotel", "Vinoteca", "Bodega", "Café", "Taberna", "Brasería", "Gastrobar", "Marisquería"]
NAMES = ["El Mirador", "La Plaça", "Can Roca Sintètic", "Els Pins", "La Brasa", "Mar i Muntanya", "El Racó", "La Lonja",
         "Las Acacias", "El Faro", "La Pèrgola", "Sant Jordi", "El Port", "La Masia", "L'Olivera", "Casa Nova",
         "El Celler", "La Riera", "Els Arcs", "La Fàbrica", "El Pati", "La Ronda", "Cap de Creus", "El Moll",
         "La Garriga", "El Jardí", "La Rambla", "Montseny", "El Born", "Llevant", "Ponent", "La Cala", "Vora Mar",
         "El Rebost", "La Sitja", "Cal Pere", "La Font", "El Trull", "La Teula", "Les Voltes"]
PRODUCTS = {
    "JC": [("SYN-JC-SKU-01", "Cava Brut Nature 75cl (SINT)", "Marca Cava A (SINT)", 11.0),
           ("SYN-JC-SKU-02", "Cava Reserva 75cl (SINT)", "Marca Cava A (SINT)", 15.5),
           ("SYN-JC-SKU-03", "Cava Rosado 75cl (SINT)", "Marca Cava B (SINT)", 12.0),
           ("SYN-JC-SKU-04", "Vino Blanco 75cl (SINT)", "Marca Vino C (SINT)", 8.5),
           ("SYN-JC-SKU-05", "Vino Tinto Crianza 75cl (SINT)", "Marca Vino D (SINT)", 10.0)],
    "PM": [("SYN-PM-SKU-01", "Ginebra Premium 70cl (SINT)", "Marca Destilado E (SINT)", 21.0),
           ("SYN-PM-SKU-02", "Vermut Rojo 1L (SINT)", "Marca Vermut F (SINT)", 9.0),
           ("SYN-PM-SKU-03", "Cava Brut Nature 75cl (SINT)", "Marca Cava A (SINT)", 11.0),
           ("SYN-PM-SKU-04", "Vino Tinto Roble 75cl (SINT)", "Marca Vino G (SINT)", 7.5),
           ("SYN-PM-SKU-05", "Whisky 12 años 70cl (SINT)", "Marca Destilado H (SINT)", 26.0)],
}


@dataclass
class Cust:
    entity: str
    cid: str
    name: str
    archetype: str
    salesperson: str | None
    city: tuple[str, str]
    seasonal_flag: bool | None = None
    is_intercompany: bool = False
    transfer_cohort: str | None = None
    orders: list[tuple[dt.date, float]] = field(default_factory=list)  # (date, value multiplier)
    aov: float = 500.0
    assignment_valid_to: dt.date | None = None
    assignment_valid_from: dt.date | None = None


class Gen:
    def __init__(self, as_of: dt.date, seed: int):
        self.as_of = as_of
        self.rng = random.Random(seed)
        self.period_start = add_months(month_start(as_of), -30)
        self.customers: list[Cust] = []
        self.mappings: list[dict[str, Any]] = []
        self.counters = {"JC": 10000, "PM": 20000}
        self.used_names: set[str] = set()
        self.notes: dict[str, str] = {}

    # ------------------------------------------------------------- basics
    def new_id(self, entity: str) -> str:
        self.counters[entity] += self.rng.randint(1, 9)
        return f"SYN-{entity}-{self.counters[entity]}"

    def new_name(self) -> str:
        for _ in range(500):
            n = f"{self.rng.choice(PREFIXES)} {self.rng.choice(NAMES)}"
            if n not in self.used_names:
                self.used_names.add(n)
                return n
        raise RuntimeError("name pool exhausted")

    def add(self, entity: str, archetype: str, sp: str | None, name: str | None = None, **kw: Any) -> Cust:
        c = Cust(entity, self.new_id(entity), name or self.new_name(), archetype, sp, self.rng.choice(CITIES), **kw)
        self.customers.append(c)
        return c

    def series(self, start: dt.date, end: dt.date, interval: float, mult=lambda d: 1.0, jitter: float = 0.15,
               pin_end: bool = True) -> list[tuple[dt.date, float]]:
        """Orders every ~interval days from start; with pin_end the last order falls exactly on `end`."""
        out, d = [], start
        while d <= end - dt.timedelta(days=int(interval * 0.5) if pin_end else 0):
            out.append((d, mult(d)))
            step = max(3, round(interval * (1 + self.rng.uniform(-jitter, jitter))))
            d = d + dt.timedelta(days=step)
        if pin_end and (not out or out[-1][0] < end):
            out.append((end, mult(end)))
        return out

    def start(self) -> dt.date:
        return self.period_start + dt.timedelta(days=self.rng.randint(0, 25))

    # ------------------------------------------------------------- archetypes
    def steady(self, entity: str, sp: str | None, name: str | None = None, **kw: Any) -> Cust:
        c = self.add(entity, "steady", sp, name, **kw)
        interval = self.rng.uniform(14, 30)
        c.aov = self.rng.uniform(250, 1400)
        end = self.as_of - dt.timedelta(days=self.rng.randint(1, max(2, int(interval * 0.8))))
        c.orders = self.series(self.start(), end, interval)
        return c

    def declining(self, entity: str, sp: str, factor: float | None = None, archetype: str = "declining", aov: tuple[float, float] = (700, 1800)) -> Cust:
        c = self.add(entity, archetype, sp)
        interval = self.rng.uniform(18, 30)
        c.aov = self.rng.uniform(*aov)
        f = factor if factor is not None else self.rng.uniform(0.4, 0.62)
        drop_from = add_months(month_start(self.as_of), -7)
        end = self.as_of - dt.timedelta(days=self.rng.randint(2, int(interval)))
        c.orders = self.series(self.start(), end, interval, mult=lambda d: f if d >= drop_from else 1.0)
        return c

    def overdue(self, entity: str, sp: str | None, archetype: str = "overdue", lateness: tuple[float, float] = (2.1, 3.2), **kw: Any) -> Cust:
        c = self.add(entity, archetype, sp, **kw)
        interval = self.rng.uniform(18, 30)
        c.aov = self.rng.uniform(400, 1500)
        last = self.as_of - dt.timedelta(days=round(interval * self.rng.uniform(*lateness)))
        c.orders = self.series(self.start(), last, interval, jitter=0.1)
        return c

    def stopped(self, entity: str, sp: str) -> Cust:
        c = self.add(entity, "stopped", sp)
        interval = self.rng.uniform(15, 25)
        c.aov = self.rng.uniform(600, 1600)
        last = self.as_of - dt.timedelta(days=self.rng.randint(200, 240))
        c.orders = self.series(self.start(), last, interval, jitter=0.1)
        return c

    def seasonal(self, entity: str, sp: str, flagged: bool) -> Cust:
        c = self.add(entity, "seasonal" if flagged else "seasonal_unflagged", sp, seasonal_flag=True if flagged else None)
        c.aov = self.rng.uniform(500, 1200)
        orders = []
        for y in range(self.period_start.year, self.as_of.year + 1):
            s, e = dt.date(y, 5, 2), min(dt.date(y, 9, 20), self.as_of)
            if s < self.period_start or s > self.as_of:
                continue
            orders += self.series(s, e, 12, jitter=0.15, pin_end=False)
        c.orders = orders
        return c

    def sparse(self, entity: str, sp: str) -> Cust:
        c = self.add(entity, "sparse", sp)
        c.aov = self.rng.uniform(800, 2500)
        c.orders = self.series(self.start(), self.as_of - dt.timedelta(days=60), self.rng.uniform(150, 190), jitter=0.1)
        return c

    def new(self, entity: str, sp: str) -> Cust:
        c = self.add(entity, "new_customer", sp)
        c.aov = self.rng.uniform(300, 900)
        c.orders = self.series(self.as_of - dt.timedelta(days=self.rng.randint(120, 150)), self.as_of - dt.timedelta(days=3), 14, jitter=0.1)
        return c

    def transfer(self, sp: str, kind: str) -> tuple[Cust, Cust]:
        """JC -> PM transfer. kind: pending | grace | reordered | unmapped | provisional."""
        name = self.new_name()
        cohort = "SYN-Nexora-W2"
        days_ago = {"pending": self.rng.randint(45, 110), "grace": self.rng.randint(8, 22), "reordered": self.rng.randint(60, 120),
                    "unmapped": self.rng.randint(45, 90), "provisional": self.rng.randint(45, 90)}[kind]
        tdate = self.as_of - dt.timedelta(days=days_ago)
        interval = self.rng.uniform(16, 28)
        jc = self.add("JC", f"transfer_{kind}_origin", sp, name,
                      transfer_cohort=cohort if kind == "unmapped" else None)
        jc.aov = self.rng.uniform(600, 1700)
        jc.orders = self.series(self.start(), tdate - dt.timedelta(days=self.rng.randint(3, 12)), interval, jitter=0.1)
        jc.assignment_valid_to = tdate - dt.timedelta(days=1)
        pm = self.add("PM", f"transfer_{kind}", sp, name, transfer_cohort=cohort if kind == "unmapped" else None)
        pm.aov = jc.aov
        pm.assignment_valid_from = tdate
        if kind == "reordered":
            pm.orders = self.series(tdate + dt.timedelta(days=self.rng.randint(8, 20)), self.as_of - dt.timedelta(days=2), interval, jitter=0.1)
        if kind != "unmapped":
            status = "provisional" if kind == "provisional" else "approved"
            self.mappings.append(self.mapping(jc, pm, tdate, status, cohort))
        return jc, pm

    def mapping(self, a: Cust, b: Cust, tdate: dt.date | None, status: str, cohort: str | None, ref: str | None = None) -> dict[str, Any]:
        approved = status == "approved"
        return {
            "mapping_ref": ref or f"SYN-MAP-{len(self.mappings) + 1:04d}",
            "from_entity": a.entity, "from_customer_id": a.cid, "to_entity": b.entity, "to_customer_id": b.cid,
            "transfer_date": tdate.isoformat() if tdate else "", "cohort": cohort or "", "mapping_status": status,
            "approved_by": "SYN data owner (synthetic approval)" if approved else "",
            "approved_at": (tdate - dt.timedelta(days=20)).isoformat() if approved and tdate else "",
        }

    # ------------------------------------------------------------- scenario
    def build(self) -> None:
        r = self.rng
        sp1 = SALES_CODES[0]
        for sp in SALES_CODES:
            for _ in range(7):
                self.steady(r.choice(["JC", "JC", "PM"]), sp)
            self.declining(r.choice(["JC", "PM"]), sp)
            self.overdue(r.choice(["JC", "PM"]), sp)
            self.overdue(r.choice(["JC", "PM"]), sp, archetype="slightly_late", lateness=(1.05, 1.3))
            self.declining(r.choice(["JC", "PM"]), sp, factor=0.86, archetype="mild_decline")
            self.declining("JC", sp, factor=0.5, archetype="small_decline", aov=(40, 70))
            self.transfer(sp, "pending")

        # Pilot salesperson (Ana): a richer mix for the demo journey.
        self.declining("JC", sp1)
        self.overdue("PM", sp1)
        self.overdue("JC", sp1)
        self.transfer(sp1, "pending")
        self.stopped("JC", sp1)
        self.transfer(sp1, "grace")
        self.transfer(sp1, "reordered")
        self.seasonal("JC", sp1, flagged=True)
        self.new("PM", sp1)
        twin = self.new_name()
        self.notes[self.steady("JC", sp1, name=twin).cid] = "name_twin"
        self.notes[self.steady("PM", sp1, name=twin).cid] = "name_twin (different customer, no mapping)"
        self.transfer(sp1, "unmapped")
        self.transfer(sp1, "provisional")
        credit = self.steady("JC", sp1)
        credit.archetype = "credit_note_month"
        # Was overdue 25 days ago (when the demo seed records an opportunity and an action), then re-ordered.
        out = self.add("PM", "outcome_demo", sp1)
        out.aov = 900.0
        out.orders = self.series(self.start(), self.as_of - dt.timedelta(days=80), 20, jitter=0.05)
        out.orders.append((self.as_of - dt.timedelta(days=8), 1.0))

        # Other teams / edge cases
        sp2, sp3, sp4 = SALES_CODES[1], SALES_CODES[2], SALES_CODES[3]
        self.seasonal("PM", sp2, flagged=False)
        self.sparse("JC", sp2)
        self.stopped("PM", sp4)
        amb_from, amb_to = self.transfer(sp2, "pending")
        amb_from.archetype = "ambiguous_origin"
        amb_to.archetype = "ambiguous_mapping"
        extra = self.add("PM", "ambiguous_mapping_second_target", sp2, amb_to.name + " (2)")
        self.mappings.append(self.mapping(amb_from, extra, amb_to.assignment_valid_from, "approved", "SYN-Nexora-W2"))
        ic = self.declining("JC", sp3, archetype="intercompany")
        ic.is_intercompany, ic.name = True, "Sociedad del Grupo (intercompañía, SINT)"
        jc_ghost = self.steady("JC", sp4)
        ghost = Cust("PM", "SYN-PM-99999", "(no existe en el paquete)", "ghost", None, CITIES[0])
        self.mappings.append(self.mapping(jc_ghost, ghost, self.as_of - dt.timedelta(days=50), "approved", "SYN-Nexora-W2"))
        jc_ghost.archetype = "mapped_to_missing_customer"
        self.overdue("PM", None, archetype="unassigned")
        self.overdue("PM", "SYN-SP-UNKNOWN", archetype="unknown_salesperson")

    # ------------------------------------------------------------- output
    def write(self, out: Path, refreshed: dict[str, dt.datetime]) -> dict[str, Any]:
        out.mkdir(parents=True, exist_ok=True)
        r = self.rng
        lines: list[dict[str, Any]] = []
        monthly: dict[tuple[str, str, dt.date], Decimal] = defaultdict(Decimal)
        doc_no = {"JC": 0, "PM": 0}
        period_end = {e: refreshed[e].date() - dt.timedelta(days=1) for e in refreshed}

        for c in self.customers:
            for d, mult in sorted(c.orders):
                if d < self.period_start or d > period_end[c.entity]:
                    continue
                doc_no[c.entity] += 1
                ref = f"SYN-{'FV' if c.entity == 'JC' else 'FP'}{d:%y}-{doc_no[c.entity]:06d}"
                target = c.aov * mult * r.uniform(0.9, 1.1)
                prods = r.sample(PRODUCTS[c.entity], k=r.randint(1, 3))
                for i, (sku, desc, brand, price) in enumerate(prods, start=1):
                    qty = max(1, round(target / len(prods) / price))
                    amount = Decimal(str(qty * price)).quantize(Decimal("0.01"), ROUND_HALF_UP)
                    lines.append(self._line(c, d, "invoice", ref, i, sku, desc, brand, qty, amount))
                    monthly[(c.entity, c.cid, month_start(d))] += amount
            if c.archetype == "credit_note_month":
                d = add_months(month_start(self.as_of), -4) + dt.timedelta(days=20)
                doc_no[c.entity] += 1
                ref = f"SYN-AB{d:%y}-{doc_no[c.entity]:06d}"
                amount = Decimal("-6500.00")
                sku, desc, brand, price = PRODUCTS[c.entity][1]
                lines.append(self._line(c, d, "credit_note", ref, 1, sku, desc, brand, -round(6500 / price), amount))
                monthly[(c.entity, c.cid, month_start(d))] += amount

        # Data-quality problems in the extract itself
        dup_src = next(row for row in lines if row["source_entity"] == "PM")
        lines.append(dict(dup_src))  # exact duplicate line -> dropped with a warning
        lines.append(dict(lines[10]))

        self._csv(out, "manifest.csv", [
            {"source_entity": e, "source_model": "JUVE Ventas base (SYNTHETIC)" if e == "JC" else "PM Ventas base (SYNTHETIC)",
             "source_refreshed_at": refreshed[e].isoformat(), "period_start": self.period_start.isoformat(),
             "period_end": period_end[e].isoformat(),
             "extract_grain": "customer-month for measures; invoice line for purchases",
             "data_classification": "synthetic", "filters_applied": "none (synthetic data)", "contract_version": "1"}
            for e in ("JC", "PM")
        ])
        self._csv(out, "customers.csv", [
            {"source_entity": c.entity, "source_customer_id": c.cid, "display_name": c.name, "channel": "Horeca",
             "segment": c.name.split(" ")[0], "city": c.city[0], "province": c.city[1],
             "is_intercompany": str(c.is_intercompany).lower(),
             "seasonal_flag": "" if c.seasonal_flag is None else str(c.seasonal_flag).lower(),
             "transfer_cohort": c.transfer_cohort or "", "source_status": "Activo"}
            for c in self.customers
        ])
        self._csv(out, "customer_mapping.csv", self.mappings)
        assignments = []
        for c in self.customers:
            if c.salesperson is None:
                continue
            assignments.append({"source_entity": c.entity, "source_customer_id": c.cid, "salesperson_code": c.salesperson,
                                "valid_from": (c.assignment_valid_from or self.period_start).isoformat(),
                                "valid_to": c.assignment_valid_to.isoformat() if c.assignment_valid_to else ""})
        self._csv(out, "assignments.csv", assignments)
        self._csv(out, "measure_definitions.csv", [
            {"measure_code": f"{e}_NET_SALES", "display_name_es": "Ventas netas (sintético)", "display_name_en": "Net sales (synthetic)",
             "certified_measure_name": "SYNTHETIC - not a certified measure", "source_model": m, "source_entity": e,
             "business_definition": "Synthetic value generated for the prototype. The approved definition (VAT, discounts, rappels, returns) is pending.",
             "certification_status": "synthetic", "unit": "EUR", "additive_over_months": "true", "approved_by": "", "approved_at": ""}
            for e, m in (("JC", "JUVE Ventas base (SYNTHETIC)"), ("PM", "PM Ventas base (SYNTHETIC)"))
        ])
        monthly_rows = [
            {"source_entity": e, "source_customer_id": cid, "measure_code": f"{e}_NET_SALES", "month": m.strftime("%Y-%m"),
             "value": f"{v:.2f}", "currency": "EUR", "record_key": f"{e}|{cid}|{e}_NET_SALES|{m:%Y-%m}"}
            for (e, cid, m), v in sorted(monthly.items()) if v != 0
        ]
        # Conflicting duplicate for one customer-month -> both rows rejected, customer flagged as incomplete
        conflict = next(row for row in monthly_rows if row["source_entity"] == "JC")
        monthly_rows.append({**conflict, "value": f"{Decimal(conflict['value']) + Decimal('100'):.2f}"})
        self._csv(out, "measure_monthly.csv", monthly_rows)
        self._csv(out, "purchases.csv", lines)
        self._csv_raw(out / "SYNTHETIC_DATA_README.txt", (
            "SYNTHETIC DATA - generated for the JC / PM Commercial Action Centre prototype.\n"
            "Not derived from any company system. Not certified. Do not use for business decisions.\n"
        ))
        archetypes: dict[str, int] = defaultdict(int)
        for c in self.customers:
            archetypes[c.archetype] += 1
        return {"customers": len(self.customers), "lines": len(lines), "monthly_rows": len(monthly_rows),
                "mappings": len(self.mappings), "archetypes": dict(sorted(archetypes.items()))}

    def _line(self, c: Cust, d: dt.date, dtype: str, ref: str, i: int, sku: str, desc: str, brand: str, qty: float, amount: Decimal) -> dict[str, Any]:
        return {"source_entity": c.entity, "record_key": f"{c.entity}|{ref}|{i}", "source_customer_id": c.cid,
                "document_date": d.isoformat(), "document_type": dtype, "document_ref": ref, "brand": brand, "sku": sku,
                "sku_description": desc, "channel": "Horeca", "quantity": str(qty), "unit": "botella",
                "amount": f"{amount:.2f}", "amount_measure_code": f"{c.entity}_NET_SALES", "currency": "EUR"}

    def _csv(self, out: Path, name: str, rows: list[dict[str, Any]]) -> None:
        cols = [c.name for c in FILES_BY_NAME[name].columns]
        with (out / name).open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for row in rows:
                w.writerow({k: row.get(k, "") for k in cols})

    @staticmethod
    def _csv_raw(path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")


def generate(out: Path, as_of: dt.date, seed: int = 20261017, stale_entity: str | None = None) -> tuple[dict[str, Any], Gen]:
    from app import clock
    from app.clock import BUSINESS_TZ

    g = Gen(as_of, seed)
    g.build()
    refreshed = {}
    latest_allowed = (clock.now() - dt.timedelta(minutes=5)).astimezone(BUSINESS_TZ).replace(second=0, microsecond=0)
    for e in ("JC", "PM"):
        day = as_of - dt.timedelta(days=5) if e == stale_entity else as_of
        # The "source refresh" is 06:00 on the as-of day, but never in the future (e.g. when seeding at 01:00).
        refreshed[e] = min(dt.datetime.combine(day, dt.time(6, 0), tzinfo=BUSINESS_TZ), latest_allowed)
    summary = g.write(Path(out), refreshed)
    return summary, g
