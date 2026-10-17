import { useI18n } from "../i18n";
import type { EvidenceItem, Opportunity } from "../api/types";
import { fmtDate, fmtDateTime, fmtMoney, fmtNumber } from "../lib/format";
import { evidenceValue, provenanceLabel } from "../lib/text";

export function KeyFigures({ items }: { items: EvidenceItem[] }) {
  const { t, locale } = useI18n();
  if (!items.length) return null;
  return (
    <div className="figures">
      {items.map((e) => (
        <div className="figure" key={e.id}>
          <div className="label">
            {t(e.label_key)}
            {e.entity ? ` · ${e.entity}` : ""}
          </div>
          <div className="value">{evidenceValue(e, t, locale)}</div>
          <div className="prov">{provenanceLabel(e, t)}</div>
        </div>
      ))}
    </div>
  );
}

function ProvenanceDetail({ e }: { e: EvidenceItem }) {
  const { t, locale } = useI18n();
  const p = e.provenance;
  const parts: string[] = [provenanceLabel(e, t)];
  if (p.measure_name) parts.push(`${t("prov.measure")}: ${p.measure_name}${p.derivation === "sum_of_monthly_values" ? ` (${t("prov.sumMonthly")})` : ""}`);
  if (p.period) parts.push(`${t("prov.period")}: ${fmtDate(p.period.start, locale)} – ${fmtDate(p.period.end, locale)}`);
  if (p.source_model) parts.push(`${t("prov.source")}: ${p.source_model}`);
  if (p.refreshed_at) parts.push(`${t("prov.refreshed")}: ${fmtDateTime(p.refreshed_at, locale)}`);
  if (p.approved_by) parts.push(p.approved_by);
  return <div className="prov-detail">{parts.join(" · ")}</div>;
}

export function EvidenceTable({ items }: { items: EvidenceItem[] }) {
  const { t, locale } = useI18n();
  return (
    <div className="table-wrap">
      <table className="evidence">
        <thead>
          <tr>
            <th>{t("detail.evidence")}</th>
            <th>{t("detail.entityCol")}</th>
            <th className="num">{t("detail.valueCol")}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((e) => (
            <tr key={e.id}>
              <td>
                {t(e.label_key)}
                <ProvenanceDetail e={e} />
              </td>
              <td>{e.entity ?? "—"}</td>
              <td className="num">{evidenceValue(e, t, locale)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PriorityWhy({ o }: { o: Opportunity }) {
  const { t, locale } = useI18n();
  const c = o.priority_components;
  if (!c) return null;
  return (
    <p className="small muted" style={{ margin: 0 }}>
      {t("priority.formula", {
        score: fmtNumber(o.priority_score, locale),
        weight: fmtNumber(c.type_weight, locale),
        value: fmtNumber(c.value_factor, locale),
        urgency: fmtNumber(c.urgency, locale),
        size: fmtMoney(c.size_value, locale),
        high: fmtNumber(c.thresholds.high, locale),
        medium: fmtNumber(c.thresholds.medium, locale),
      })}
    </p>
  );
}
