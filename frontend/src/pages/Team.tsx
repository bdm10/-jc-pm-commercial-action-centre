import { useDeferredValue, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useI18n } from "../i18n";
import { api, post } from "../api/client";
import type { AssignmentList, FollowUp, OppType, TeamView } from "../api/types";
import { useSession } from "../session";
import { fmtDate } from "../lib/format";
import { FollowUpRow } from "../components/FollowUpRow";
import { EntityBadge, ErrorState, Loading, Section, useToast } from "../components/ui";

const STATUSES = ["open", "in_progress", "snoozed", "unconfirmed", "dismissed", "resolved"];
const TYPES: OppType[] = ["transfer_no_reorder", "declining_purchases", "overdue_cadence"];

export function TeamPage() {
  const { t, locale } = useI18n();
  const { openSheet } = useSession();
  const q = useQuery({ queryKey: ["team"], queryFn: () => api<TeamView>("/team") });
  if (q.isPending) return <Loading rows={3} />;
  if (q.isError) return <ErrorState onRetry={() => q.refetch()} />;
  const d = q.data;
  const rec = (f: FollowUp) =>
    openSheet({ entity: f.customer.source_entity, customerId: f.customer.source_customer_id, customerName: f.customer.display_name, opportunityId: f.opportunity_id });
  const totalActions = Object.values(d.actions_last_30d).reduce((a, b) => a + b, 0);

  return (
    <>
      <div className="page-head">
        <h1>{t("team.title")}</h1>
        <p className="muted small">{d.teams.filter((x) => x !== "*").join(" · ")}</p>
      </div>

      <Section title={t("team.members")}>
        <div className="card table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>{t("app.user")}</th>
                <th className="num">{t("team.assigned")}</th>
                <th className="num">{t("team.active")}</th>
                <th className="num">{t("team.actions30")}</th>
                <th className="num">{t("team.fuOverdue")}</th>
                <th className="num">{t("team.outcomes90")}</th>
              </tr>
            </thead>
            <tbody>
              {d.members.map((m) => (
                <tr key={m.id}>
                  <td>{m.display_name} <span className="tiny muted">{t(`role.${m.role}`)}</span></td>
                  <td className="num">{m.assigned_customers}</td>
                  <td className="num">{m.active_opportunities}</td>
                  <td className="num">{m.actions_last_30d}</td>
                  <td className="num">{m.follow_ups_overdue > 0 ? <strong className="fu-overdue">{m.follow_ups_overdue}</strong> : 0}</td>
                  <td className="num">{m.observed_outcomes_90d}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title={t("team.statusByType")}>
        <div className="card table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th />
                {TYPES.map((type) => (
                  <th key={type} className="num">{t(`oppType.${type}`)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {STATUSES.map((s) => (
                <tr key={s}>
                  <td>{t(`status.${s}`)}</td>
                  {TYPES.map((type) => (
                    <td key={type} className="num">{d.opportunity_status[type]?.[s] ?? 0}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="tiny muted">{t("team.statusNote")}</p>
        </div>
      </Section>

      <div className="grid-2">
        <div>
          <Section title={t("team.overdueList")} count={d.overdue_follow_ups.length}>
            <div className="card" style={{ paddingTop: 4, paddingBottom: 4 }}>
              {d.overdue_follow_ups.length === 0 ? (
                <p className="muted">{t("team.overdueEmpty")}</p>
              ) : (
                <div className="list">
                  {d.overdue_follow_ups.map((f) => (
                    <FollowUpRow key={f.id} f={f} showOwner onRecord={() => rec(f)} />
                  ))}
                </div>
              )}
            </div>
          </Section>

          <Section title={t("team.actionsVsOutcomes")}>
            <div className="stat-grid">
              <div className="stat">
                <div className="k">{t("team.actions30")}</div>
                <div className="v">{totalActions}</div>
                <div className="tiny muted">{Object.entries(d.actions_last_30d).map(([k, v]) => `${t(`action.${k}`)}: ${v}`).join(" · ")}</div>
              </div>
              <div className="stat">
                <div className="k">{t("team.outcomes90")}</div>
                <div className="v">{d.observed_outcomes.length}</div>
              </div>
            </div>
            <p className="tiny muted">{t("team.actionsNote")}</p>
          </Section>

          <Section title={t("team.outcomes")}>
            <div className="card">
              <div className="callout callout-info small" style={{ marginBottom: 8 }}>{t("team.outcomesNote")}</div>
              {d.observed_outcomes.length === 0 ? (
                <p className="muted" style={{ margin: 0 }}>{t("team.outcomesEmpty")}</p>
              ) : (
                <ul className="timeline">
                  {d.observed_outcomes.map((o) => (
                    <li key={o.opportunity_id}>
                      <Link to={`/customers/${o.customer.source_entity}/${encodeURIComponent(o.customer.source_customer_id)}`}>
                        <EntityBadge entity={o.customer.source_entity} /> <strong>{o.customer.display_name}</strong>
                      </Link>
                      <div className="small muted">
                        {o.opp_type ? `${t(`oppType.${o.opp_type}`)} · ` : ""}
                        {t("team.outcomeRow", {
                          action: o.action ? t(`action.${o.action.action_type}`) : "—",
                          user: o.action?.user ?? "—",
                          actionDate: fmtDate(o.first_action_at.slice(0, 10), locale),
                          orderDate: fmtDate(o.observed_document_date, locale),
                        })}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </Section>
        </div>

        <div>
          <Section title={t("team.dataIssues")}>
            <div className="card">
              {Object.keys(d.data_issues).length === 0 ? (
                <p className="muted" style={{ margin: 0 }}>{t("team.dataIssuesEmpty")}</p>
              ) : (
                <ul className="timeline">
                  {Object.entries(d.data_issues).map(([code, n]) => (
                    <li key={code} style={{ display: "flex", justifyContent: "space-between" }}>
                      <span>{t(`issue.${code}`)}</span>
                      <strong>{n}</strong>
                    </li>
                  ))}
                </ul>
              )}
              {d.user_reported_data_problems > 0 && <p className="small">{t("team.userReports", { n: d.user_reported_data_problems })}</p>}
              <p className="tiny muted" style={{ marginBottom: 0 }}>{t("detail.dataIssuesNote")}</p>
            </div>
          </Section>
        </div>
      </div>

      <Assignments />
    </>
  );
}

function Assignments() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const toast = useToast();
  const [q, setQ] = useState("");
  const dq = useDeferredValue(q);
  const [editing, setEditing] = useState<string | null>(null);
  const [target, setTarget] = useState<string>("");
  const [reason, setReason] = useState("");
  const [showAll, setShowAll] = useState(false);
  const list = useQuery({ queryKey: ["assignments", dq], queryFn: () => api<AssignmentList>(`/team/assignments?q=${encodeURIComponent(dq)}`), placeholderData: (p) => p });
  const reassign = useMutation({
    mutationFn: (body: unknown) => post("/assignments", body),
    onSuccess: () => {
      qc.invalidateQueries();
      setEditing(null);
      setReason("");
      toast(t("team.reassigned"));
    },
  });
  return (
    <Section title={t("team.assignments")} count={list.data?.total}>
      <input className="input" type="search" placeholder={t("team.assignSearch")} aria-label={t("team.assignSearch")} value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="card" style={{ marginTop: 10, paddingTop: 4, paddingBottom: 4 }}>
        {list.isPending && <Loading rows={2} />}
        <div className="list">
          {list.data?.items.slice(0, showAll ? 300 : 12).map((c) => {
            const key = `${c.source_entity}:${c.source_customer_id}`;
            return (
              <div className="row" key={key} style={{ flexWrap: "wrap" }}>
                <EntityBadge entity={c.source_entity} />
                <div className="row-main">
                  <div className="row-title">{c.display_name}</div>
                  <div className="row-meta">
                    <span>{c.source_customer_id}</span>
                    <span>{c.assignee.display_name ?? t("team.unassigned")}</span>
                    {c.active_opportunities > 0 && <span>{t("team.active")}: {c.active_opportunities}</span>}
                  </div>
                </div>
                {editing === key ? (
                  <div className="stack" style={{ width: "100%" }}>
                    <select className="input" aria-label={t("team.reassignTo")} value={target} onChange={(e) => setTarget(e.target.value)}>
                      <option value="">{t("team.reassignTo")}…</option>
                      {list.data!.assignable_users.filter((u) => u.id !== c.assignee.id).map((u) => (
                        <option key={u.id} value={u.id}>{u.display_name}</option>
                      ))}
                    </select>
                    <input className="input" placeholder={t("team.reassignReason")} aria-label={t("team.reassignReason")} maxLength={280} value={reason} onChange={(e) => setReason(e.target.value)} />
                    <div className="actions-row">
                      <button className="btn btn-primary" disabled={!target || reassign.isPending}
                        onClick={() => reassign.mutate({ source_entity: c.source_entity, source_customer_id: c.source_customer_id, user_id: Number(target), reason: reason || null })}>
                        {t("team.reassign")}
                      </button>
                      <button className="btn" onClick={() => setEditing(null)}>{t("app.cancel")}</button>
                    </div>
                  </div>
                ) : (
                  <button className="btn btn-small" onClick={() => { setEditing(key); setTarget(""); }}>{t("team.reassign")}</button>
                )}
              </div>
            );
          })}
        </div>
        {list.data && list.data.items.length > 12 && (
          <button className="linkbtn" onClick={() => setShowAll(!showAll)}>{showAll ? t("app.less") : `${t("app.more")} (${list.data.items.length})`}</button>
        )}
      </div>
    </Section>
  );
}
