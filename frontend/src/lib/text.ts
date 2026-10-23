// Turns machine-readable reasons, evidence and templates from the API into plain-language text.
import type { Params } from "../i18n";
import type { EvidenceItem, Opportunity, TalkingPoint } from "../api/types";
import { fmtDate, fmtMoney, fmtMonthRange, fmtNumber, fmtPct } from "./format";

type T = (key: string, params?: Params) => string;

export function reasonText(t: T, locale: string, o: Pick<Opportunity, "opp_type" | "reason_params">): string {
  const p = o.reason_params;
  switch (o.opp_type) {
    case "transfer_no_reorder":
      return t("reason.transfer_no_reorder", {
        from_entity: p.from_entity,
        to_entity: p.to_entity,
        transfer_date: fmtDate(String(p.transfer_date), locale),
        days: p.days_since_transfer,
      });
    case "declining_purchases":
      return t("reason.declining_purchases", {
        entity: p.entity,
        pct: fmtPct(Number(p.change_pct), locale),
        current: fmtMonthRange(String(p.current_start), String(p.current_end), locale),
      });
    case "overdue_cadence":
      return t("reason.overdue_cadence", {
        typical: p.typical_interval_days,
        days: p.days_since_last,
        last_order: fmtDate(String(p.last_order_date), locale),
      });
  }
}

export function nextActionText(t: T, o: Pick<Opportunity, "next_action" | "reason_params">): string | null {
  return o.next_action ? t(`next.${o.next_action}`, { to_entity: o.reason_params.to_entity }) : null;
}

export function evidenceValue(e: EvidenceItem, t: T, locale: string): string {
  switch (e.kind) {
    case "money":
      return fmtMoney(Number(e.value), locale, e.unit);
    case "pct":
      return fmtPct(Number(e.value), locale, true);
    case "date":
      return fmtDate(String(e.value), locale);
    case "days":
      return t("detail.days", { n: e.value });
    case "count":
      return fmtNumber(Number(e.value), locale);
    default:
      return String(e.value);
  }
}

/** Short provenance label. Synthetic or provisional figures are never presented as certified. */
export function provenanceLabel(e: EvidenceItem, t: T): string {
  const p = e.provenance;
  if (p.type === "app_calculation") return t("prov.calc");
  if (p.type === "approved_mapping") return t("prov.mapping", { ref: p.mapping_ref ?? "" });
  if (p.type === "source_documents") return `${t("prov.docs")} · ${t(`prov.${p.certification_status ?? "provisional"}`)}`;
  const status = p.certification_status ?? "provisional";
  return t(`prov.${status === "certified" ? "certified" : status === "synthetic" ? "synthetic" : "provisional"}`);
}

export function talkingPointText(tp: TalkingPoint, t: T, locale: string): string {
  if (tp.text) return tp.text;
  const p = { ...(tp.params ?? {}) } as Params;
  for (const k of ["transfer_date", "last_order_date"]) if (p[k]) p[k] = fmtDate(String(p[k]), locale);
  if (p.change_pct !== undefined) p.pct = fmtPct(Number(p.change_pct), locale);
  if (p.current_start && p.current_end) p.current = fmtMonthRange(String(p.current_start), String(p.current_end), locale);
  return t(tp.key ?? "", p);
}

export function evalDetailText(t: T, locale: string, code: string, params: Record<string, string | number>): string {
  const p: Params = { ...params };
  for (const k of ["grace_ends", "first_order_date", "alert_from"]) if (p[k]) p[k] = fmtDate(String(p[k]), locale);
  if (typeof p.change_pct === "number") p.change_pct = fmtNumber(p.change_pct, locale);
  return t(`evald.${code}`, p);
}
