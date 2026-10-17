import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useI18n } from "../i18n";
import { api, ApiError, post } from "../api/client";
import type { AiPoints, CustomerDetail, Entity, Opportunity } from "../api/types";
import { useSession } from "../session";
import { fmtDate, fmtDateTime, fmtMoney, fmtMonthRange, fmtNumber } from "../lib/format";
import { evalDetailText, nextActionText, reasonText, talkingPointText } from "../lib/text";
import { EvidenceTable, KeyFigures, PriorityWhy } from "../components/Evidence";
import { Sparkline } from "../components/Sparkline";
import { Chip, EntityBadge, ErrorState, Loading, PriorityChip, Section } from "../components/ui";

export function CustomerDetailPage() {
  const { entity, customerId } = useParams() as { entity: Entity; customerId: string };
  const { t, locale } = useI18n();
  const { openSheet } = useSession();
  const q = useQuery({
    queryKey: ["customer", entity, customerId],
    queryFn: () => api<CustomerDetail>(`/customers/${entity}/${encodeURIComponent(customerId)}`),
  });

  if (q.isPending) return <Loading rows={3} />;
  if (q.isError) return <ErrorState notFound={q.error instanceof ApiError && q.error.status === 404} onRetry={() => q.refetch()} />;
  const d = q.data;
  const c = d.customer;
  const primary = d.opportunities.find((o) => o.condition_active) ?? null;
  const record = (o: Opportunity | null, initialMode: "action" | "more" = "action") =>
    openSheet({
      entity: c.source_entity,
      customerId: c.source_customer_id,
      customerName: c.display_name,
      opportunityId: o?.id ?? null,
      oppTypeLabel: o ? t(`oppType.${o.opp_type}`) : undefined,
      initialMode,
    });

  return (
    <>
      <div className="page-head">
        <Link to="/" className="btn btn-ghost btn-small" style={{ paddingLeft: 0 }}>← {t("app.back")}</Link>
        <div style={{ display: "flex", gap: 10, alignItems: "flex-start", marginTop: 4 }}>
          <EntityBadge entity={c.source_entity} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <h1 style={{ overflowWrap: "anywhere" }}>{c.display_name}</h1>
            <p className="muted small">
              {c.source_customer_id}
              {c.city ? ` · ${c.city}` : ""}
              {c.segment ? ` · ${c.segment}` : ""}
              {d.assignee.display_name ? ` · ${t("card.assignee", { name: d.assignee.display_name })}` : ""}
            </p>
            <p className="muted tiny">
              {d.freshness.map((f) => t("freshness.line", { entity: f.entity, date: fmtDateTime(f.refreshed_at, locale) })).join(" · ")}
            </p>
          </div>
        </div>
      </div>

      {d.data_issues.filter((i) => i.severity !== "info").length > 0 && (
        <div className="callout callout-warn" style={{ marginBottom: 12 }} role="note">
          <strong>{t("detail.dataIssues")}:</strong> {d.data_issues.filter((i) => i.severity !== "info").map((i) => t(`issue.${i.issue_code}`)).join(" · ")}.{" "}
          {t("detail.dataIssuesNote")}
        </div>
      )}

      <div className="grid-2">
        <div>
          <Section title={t("detail.whyNow")}>
            {d.opportunities.length === 0 && <p className="muted">{t("detail.noActive")}</p>}
            <div className="stack">
              {d.opportunities.map((o) => (
                <OpportunityBlock key={o.id} o={o} onRecord={() => record(o)} onMore={() => record(o, "more")} />
              ))}
            </div>
          </Section>

          <Section title={t("detail.talkingPoints")}>
            <TalkingPoints d={d} />
          </Section>

          <Section title={t("detail.history")}>
            <div className="card">
              {d.open_follow_ups.length > 0 && (
                <p className="small" style={{ marginTop: 0 }}>
                  <strong>{t("detail.followUpsOpen")}:</strong>{" "}
                  {d.open_follow_ups.map((f) => `${fmtDate(f.due_date, locale)} (${f.owner.display_name})`).join(", ")}
                </p>
              )}
              {d.activities.length === 0 ? (
                <p className="muted" style={{ margin: 0 }}>{t("detail.historyEmpty")}</p>
              ) : (
                <ul className="timeline">
                  {d.activities.map((a) => (
                    <li key={a.id}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                        <strong>{t(`action.${a.action_type}`)}</strong>
                        <span className="small muted">{fmtDateTime(a.created_at, locale)} · {a.user.display_name}</span>
                      </div>
                      <div className="small muted">
                        {a.opp_type ? t(`oppType.${a.opp_type}`) : ""}
                        {a.follow_up_date ? ` · ${t("fu.due", { date: fmtDate(a.follow_up_date, locale) })}` : ""}
                      </div>
                      {a.note && <div className="note" style={{ marginTop: 6 }}>{a.note}</div>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </Section>
        </div>

        <div>
          <Section title={t("detail.summary")}>
            <Summary d={d} />
          </Section>

          {d.linked_accounts.length > 0 && (
            <Section title={t("detail.linked")}>
              <div className="card stack">
                {d.linked_accounts.map((l) => (
                  <div key={l.mapping_ref}>
                    <div>
                      <EntityBadge entity={l.other.source_entity} />{" "}
                      {t(`detail.linked.${l.direction}`, { entity: l.other.source_entity, id: l.other.source_customer_id, date: fmtDate(l.transfer_date, locale) })}
                    </div>
                    <div className="small muted">{t("detail.linked.mapping", { ref: l.mapping_ref, by: l.approved_by ?? "—" })}</div>
                    <div className="small muted">{t("detail.linked.lastOrder", { entity: l.other.source_entity, date: fmtDate(l.other.last_order_date, locale) })}</div>
                    {l.other.can_open && (
                      <Link className="small" to={`/customers/${l.other.source_entity}/${encodeURIComponent(l.other.source_customer_id)}`}>
                        {l.other.display_name}
                      </Link>
                    )}
                  </div>
                ))}
                <p className="tiny muted" style={{ margin: 0 }}>{t("detail.linkedNote")}</p>
              </div>
            </Section>
          )}

          <Section title={t("detail.moreDetail")}>
            <div className="card">
              <details className="expand" style={{ borderTop: "none" }}>
                <summary>{t("detail.purchases")} ({d.recent_documents.length})</summary>
                {d.recent_documents.length === 0 ? (
                  <p className="muted">{t("detail.purchasesEmpty")}</p>
                ) : (
                  <ul className="timeline">
                    {d.recent_documents.map((doc) => (
                      <li key={doc.document_ref}>
                        <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                          <strong>{fmtDate(doc.document_date, locale)}</strong>
                          <span className="small muted">
                            {doc.document_type === "credit_note" ? t("detail.creditNote") : t("detail.invoice")} · {doc.document_ref}
                          </span>
                        </div>
                        {doc.lines.map((ln, i) => (
                          <div key={i} className="small" style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                            <span>
                              {ln.sku_description} {ln.quantity !== null ? `· ${fmtNumber(ln.quantity, locale)} ${ln.unit ?? ""}` : ""}
                            </span>
                            {ln.amount !== null && <span className="muted">{fmtMoney(ln.amount, locale)}</span>}
                          </div>
                        ))}
                      </li>
                    ))}
                  </ul>
                )}
              </details>
              <details className="expand">
                <summary>{t("detail.ruleEvaluations")}</summary>
                <ul className="timeline">
                  {d.rule_evaluations.map((e) => (
                    <li key={e.opp_type}>
                      <strong>{t(`oppType.${e.opp_type}`)}</strong>: {t(`eval.${e.status}`)}
                      <div className="small muted">{evalDetailText(t, locale, e.detail_code, e.detail_params)}</div>
                    </li>
                  ))}
                </ul>
              </details>
              {d.closed_opportunities.length > 0 && (
                <details className="expand">
                  <summary>{t("detail.closed")} ({d.closed_opportunities.length})</summary>
                  <ul className="timeline">
                    {d.closed_opportunities.map((o) => (
                      <li key={o.id}>
                        <strong>{t(`oppType.${o.opp_type}`)}</strong> · {t(`status.${o.status}`)}
                        {o.dismissed_reason ? ` · ${t(`dismiss.${o.dismissed_reason}`)}` : ""}
                        {o.observed_outcome && <OutcomeNote o={o} />}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          </Section>
        </div>
      </div>

      <div className="sticky-cta">
        <button className="btn btn-primary btn-block" onClick={() => record(primary)}>
          {t("card.record")}
        </button>
      </div>
    </>
  );
}

function OutcomeNote({ o }: { o: Opportunity }) {
  const { t, locale } = useI18n();
  if (!o.observed_outcome) return null;
  return (
    <div className="callout callout-ok small" style={{ marginTop: 6 }}>
      {t("detail.outcome", { date: fmtDate(o.observed_outcome.observed_document_date, locale), actionDate: fmtDate(o.observed_outcome.first_action_at.slice(0, 10), locale) })}
    </div>
  );
}

function OpportunityBlock({ o, onRecord, onMore }: { o: Opportunity; onRecord: () => void; onMore: () => void }) {
  const { t, locale } = useI18n();
  const status = o.condition_active ? o.status : "unconfirmed";
  const next = nextActionText(t, o);
  return (
    <article className="card acard" data-testid="opportunity">
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        <PriorityChip band={o.priority_band} />
        <Chip tone="type">{t(`oppType.${o.opp_type}`)}</Chip>
        <Chip tone={status === "unconfirmed" ? "warn" : "neutral"}>{t(`status.${status}`)}</Chip>
      </div>
      <p className="reason">{reasonText(t, locale, o)}</p>
      {!o.condition_active && <div className="callout callout-warn small">{t("detail.unconfirmed")}</div>}
      {o.snoozed_until && o.status === "snoozed" && <div className="small muted">{t("detail.snoozedUntil", { date: fmtDate(o.snoozed_until, locale) })}</div>}
      <KeyFigures items={o.key_figures} />
      {next && (
        <div className="next">
          <strong>{t("card.nextStep")}:</strong>
          <span>{next}</span>
        </div>
      )}
      {o.observed_outcome && <OutcomeNote o={o} />}
      <details className="expand">
        <summary>{t("detail.evidence")}</summary>
        {o.evidence && <EvidenceTable items={o.evidence} />}
        <p className="tiny muted">{t("detail.detected", { date: fmtDate(o.first_detected_at.slice(0, 10), locale) })}</p>
      </details>
      <details className="expand">
        <summary>{t("priority.why")}</summary>
        <PriorityWhy o={o} />
      </details>
      <div className="actions-row">
        <button className="btn btn-primary" onClick={onRecord}>{t("card.record")}</button>
        <button className="btn" onClick={onMore}>{t("detail.snooze")} / {t("detail.dismiss")}</button>
      </div>
    </article>
  );
}

function Summary({ d }: { d: CustomerDetail }) {
  const { t, locale, lang } = useI18n();
  const s = d.summary;
  const m = s.measure;
  const statusLabel = m ? (m.certification_status === "certified" ? t("prov.certified") : m.certification_status === "synthetic" ? t("prov.synthetic") : t("prov.provisional")) : "";
  return (
    <div className="card stack">
      <div className="kv">
        {s.last_12m && (
          <div>
            <div className="k">{t("detail.last12m")} · {fmtMonthRange(s.last_12m.start, s.last_12m.end, locale)}</div>
            <div className="v">{fmtMoney(s.last_12m.value, locale, m?.unit)}</div>
          </div>
        )}
        {s.prior_12m && (
          <div>
            <div className="k">{t("detail.prior12m")}</div>
            <div className="v">{fmtMoney(s.prior_12m.value, locale, m?.unit)}</div>
          </div>
        )}
        <div>
          <div className="k">{t("detail.lastOrder")}</div>
          <div className="v">{fmtDate(s.last_order_date, locale)}</div>
        </div>
        <div>
          <div className="k">{t("detail.orders12m")}</div>
          <div className="v">{s.orders_last_12m}</div>
        </div>
        {s.typical_interval_days !== undefined && (
          <div>
            <div className="k">{t("detail.typicalInterval")}</div>
            <div className="v">{t("detail.days", { n: s.typical_interval_days })}</div>
          </div>
        )}
      </div>
      {s.monthly && m && (
        <div>
          <div className="small muted" style={{ marginBottom: 4 }}>{t("detail.monthly")}</div>
          {s.monthly.some((x) => x.value !== 0) ? (
            <Sparkline data={s.monthly} unit={m.unit} />
          ) : (
            <p className="small muted" style={{ margin: 0 }}>{t("detail.noPurchasesPeriod", { entity: s.entity })}</p>
          )}
        </div>
      )}
      {m && (
        <p className="tiny muted" style={{ margin: 0 }}>
          {t("detail.summaryNote", { entity: s.entity, status: statusLabel })} {t("prov.measure")}: {lang === "es" ? m.name_es : m.name_en} ({m.certified_measure_name}) · {m.source_model} · {t("prov.sumMonthly")}.
        </p>
      )}
    </div>
  );
}

function TalkingPoints({ d }: { d: CustomerDetail }) {
  const { t, locale, lang } = useI18n();
  const { meta } = useSession();
  const ai = useMutation({
    mutationFn: () => post<AiPoints>(`/customers/${d.customer.source_entity}/${encodeURIComponent(d.customer.source_customer_id)}/ai-talking-points`, { language: lang }),
  });
  if (d.talking_points.length === 0) return <p className="muted">{t("detail.noActive")}</p>;
  return (
    <div className="card stack">
      <ol className="tp-list">
        {d.talking_points.map((tp, i) => (
          <li key={i}>{talkingPointText(tp, t, locale)}</li>
        ))}
      </ol>
      <p className="tiny muted" style={{ margin: 0 }}>{t("detail.tpDeterministic")}</p>
      {meta.ai_enabled ? (
        <>
          <button className="btn" disabled={ai.isPending} onClick={() => ai.mutate()}>{t("detail.aiDraft")}</button>
          {ai.data?.status === "ok" && (
            <div className="callout callout-info">
              <strong className="small">{t("detail.aiLabel")}</strong>
              <ol className="tp-list" style={{ marginTop: 8 }}>
                {ai.data.points.map((p, i) => (
                  <li key={i}>
                    {p.text}
                    <div className="facts">
                      {p.fact_ids.map((id) => {
                        const f = ai.data!.facts.find((x) => x.id === id);
                        return <Chip key={id}>{f ? `${f.label}: ${String(f.value)}` : id}</Chip>;
                      })}
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          )}
          {ai.data && ai.data.status !== "ok" && <div className="callout callout-warn small">{ai.data.status === "not_configured" ? t("detail.aiNotConfigured") : t("detail.aiRejected")}</div>}
        </>
      ) : (
        <p className="tiny muted" style={{ margin: 0 }}>{t("detail.aiNotConfigured")}</p>
      )}
    </div>
  );
}
