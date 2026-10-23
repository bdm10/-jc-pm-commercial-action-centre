import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useI18n } from "../i18n";
import type { FollowUp } from "../api/types";
import { fmtDate } from "../lib/format";
import { useSession } from "../session";
import { EntityBadge } from "./ui";

export function FollowUpRow({ f, onRecord, showOwner, extra }: { f: FollowUp; onRecord: () => void; showOwner?: boolean; extra?: ReactNode }) {
  const { t, locale } = useI18n();
  const { me } = useSession();
  const c = f.customer;
  const when =
    f.status !== "open"
      ? fmtDate(f.closed_at ?? f.due_date, locale)
      : f.days_overdue > 0
        ? t("fu.overdueBy", { n: f.days_overdue })
        : f.due_date <= me.today
          ? t("fu.dueToday")
          : t("fu.due", { date: fmtDate(f.due_date, locale) });
  return (
    <div className="row" data-testid="follow-up-row">
      <Link className="row-link" to={`/customers/${c.source_entity}/${encodeURIComponent(c.source_customer_id)}`}>
        <EntityBadge entity={c.source_entity} />
        <div className="row-main">
          <div className="row-title">{c.display_name ?? c.source_customer_id}</div>
          <div className="row-meta">
            <span className={f.status === "open" && f.days_overdue > 0 ? "fu-overdue" : ""}>{when}</span>
            {f.opp_type && <span>{t(`oppType.${f.opp_type}`)}</span>}
            {f.last_action && <span>{t("fu.lastAction", { action: t(`action.${f.last_action.action_type}`) })}</span>}
            {showOwner && <span>{t("fu.owner", { name: f.owner.display_name })}</span>}
          </div>
          {f.last_action?.note && <div className="note" style={{ marginTop: 6 }}>{f.last_action.note}</div>}
        </div>
      </Link>
      {f.status === "open" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <button className="btn btn-small" onClick={onRecord}>
            {t("fu.record")}
          </button>
          {extra}
        </div>
      )}
    </div>
  );
}
