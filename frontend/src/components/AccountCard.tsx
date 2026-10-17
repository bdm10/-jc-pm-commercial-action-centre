import { Link } from "react-router-dom";
import { useI18n } from "../i18n";
import type { TodayCard } from "../api/types";
import { nextActionText, reasonText } from "../lib/text";
import { KeyFigures } from "./Evidence";
import { Chip, EntityBadge, PriorityChip } from "./ui";

export function AccountCard({ card, showAssignee, onRecord }: { card: TodayCard; showAssignee: boolean; onRecord: () => void }) {
  const { t, locale } = useI18n();
  const { customer: c, opportunity: o } = card;
  const href = `/customers/${c.source_entity}/${encodeURIComponent(c.source_customer_id)}`;
  const next = nextActionText(t, o);
  const resurfaced = o.reason_params.resurfaced as string | undefined;
  return (
    <article className="card acard" data-testid="account-card" aria-label={c.display_name ?? c.source_customer_id}>
      <div className="acard-head">
        <EntityBadge entity={c.source_entity} />
        <div className="acard-title">
          <Link to={href}>
            <h3>{c.display_name}</h3>
          </Link>
          <div className="acard-sub">
            {c.source_customer_id}
            {c.city ? ` · ${c.city}` : ""}
            {showAssignee && card.assignee.display_name ? ` · ${t("card.assignee", { name: card.assignee.display_name })}` : ""}
          </div>
        </div>
        <PriorityChip band={o.priority_band} />
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <Chip tone="type">{t(`oppType.${o.opp_type}`)}</Chip>
        {card.other_signals.length > 0 && (
          <Chip>{t("card.otherSignals", { n: card.other_signals.length, types: card.other_signals.map((s) => t(`oppType.${s.opp_type}`)).join(", ") })}</Chip>
        )}
        {resurfaced && <Chip tone="warn">{t(`card.resurfaced.${resurfaced}`)}</Chip>}
      </div>
      <p className="reason">{reasonText(t, locale, o)}</p>
      <KeyFigures items={o.key_figures} />
      {next && (
        <div className="next">
          <strong>{t("card.nextStep")}:</strong>
          <span>{next}</span>
        </div>
      )}
      <div className="actions-row">
        <button className="btn btn-primary" onClick={onRecord}>
          {t("card.record")}
        </button>
        <Link className="btn" to={href}>
          {t("card.open")}
        </Link>
      </div>
    </article>
  );
}
