import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useI18n } from "../i18n";
import { api } from "../api/client";
import type { Today } from "../api/types";
import { useSession } from "../session";
import { fmtDateTime, fmtLongDate } from "../lib/format";
import { AccountCard } from "../components/AccountCard";
import { FollowUpRow } from "../components/FollowUpRow";
import { EmptyState, ErrorState, Loading, Section } from "../components/ui";

export function TodayPage() {
  const { t, locale } = useI18n();
  const { me, openSheet } = useSession();
  const q = useQuery({ queryKey: ["today"], queryFn: () => api<Today>("/today") });

  return (
    <>
      <div className="page-head">
        <h1>{t("today.title")}</h1>
        <p className="muted small">{fmtLongDate(me.today, locale)}</p>
        <p className="muted small">
          {me.freshness.map((f) => `${t("freshness.line", { entity: f.entity, date: fmtDateTime(f.refreshed_at, locale) })}${f.is_stale ? ` (${t("freshness.stale")})` : ""}`).join(" · ")}
        </p>
      </div>
      {q.isPending && <Loading rows={3} />}
      {q.isError && <ErrorState onRetry={() => q.refetch()} />}
      {q.data && (
        <div className="grid-2">
          <div>
            <Section title={t("today.priorities")} count={q.data.cards.length || undefined}>
              <p className="muted small" style={{ marginTop: 0 }}>{t("today.prioritiesHint", { n: me.options.today_max_cards })}</p>
              {q.data.hidden_due_to_stale_data > 0 && (
                <div className="callout callout-warn" style={{ marginBottom: 12 }}>{t("today.hiddenStale", { n: q.data.hidden_due_to_stale_data })}</div>
              )}
              {q.data.cards.length === 0 ? (
                <EmptyState title={t("today.empty.title")} body={t("today.empty.body")}>
                  <Link className="btn" to="/customers">{t("nav.customers")}</Link>
                </EmptyState>
              ) : (
                <div className="stack">
                  {q.data.cards.map((c) => (
                    <AccountCard
                      key={c.opportunity.id}
                      card={c}
                      showAssignee={me.role !== "sales"}
                      onRecord={() =>
                        openSheet({
                          entity: c.customer.source_entity,
                          customerId: c.customer.source_customer_id,
                          customerName: c.customer.display_name,
                          opportunityId: c.opportunity.id,
                          oppTypeLabel: t(`oppType.${c.opportunity.opp_type}`),
                        })
                      }
                    />
                  ))}
                </div>
              )}
              {q.data.more_count > 0 && (
                <Link className="btn btn-ghost" to="/customers?with_opportunity=1" style={{ marginTop: 8 }}>
                  {t("today.more", { n: q.data.more_count })} →
                </Link>
              )}
            </Section>
          </div>
          <div>
            <Section title={t("today.followups")} count={q.data.follow_ups_due.length || undefined}>
              <div className="card">
                {q.data.follow_ups_due.length === 0 ? (
                  <p className="muted" style={{ margin: 0 }}>{t("today.followupsEmpty")}</p>
                ) : (
                  <div className="list">
                    {q.data.follow_ups_due.map((f) => (
                      <FollowUpRow
                        key={f.id}
                        f={f}
                        onRecord={() =>
                          openSheet({
                            entity: f.customer.source_entity,
                            customerId: f.customer.source_customer_id,
                            customerName: f.customer.display_name,
                            opportunityId: f.opportunity_id,
                            oppTypeLabel: f.opp_type ? t(`oppType.${f.opp_type}`) : undefined,
                          })
                        }
                      />
                    ))}
                  </div>
                )}
              </div>
            </Section>
            <p className="tiny muted" style={{ marginTop: 12 }}>{t("banner.provisional", { version: q.data.config_version })}</p>
          </div>
        </div>
      )}
    </>
  );
}
