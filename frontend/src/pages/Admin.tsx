import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useI18n } from "../i18n";
import { api, ApiError, post, put } from "../api/client";
import { fmtDateTime } from "../lib/format";
import { Chip, ErrorState, Loading, Section, useToast } from "../components/ui";

type Params = Record<string, Record<string, unknown> | boolean>;
interface ConfigResp { version: number; params: Params; history: { version: number; created_at: string; note: string | null }[] }
interface Issue { id: number; stage: string; severity: string; issue_code: string; source_entity: string | null; source_customer_id: string | null; detail: Record<string, unknown> }

// Only scalar numeric/boolean parameters are editable here; nested maps (weights, measure codes) stay as configured.
const EDITABLE: [string, string[]][] = [
  ["freshness", ["stale_after_hours", "month_complete_lag_days"]],
  ["transfer_no_reorder", ["enabled", "grace_days", "max_days_since_transfer", "min_orders_before_transfer"]],
  ["declining_purchases", ["enabled", "window_months", "min_history_months", "decline_threshold_pct", "min_prior_value", "min_abs_decline"]],
  ["overdue_cadence", ["enabled", "lookback_months", "min_orders", "tolerance_factor", "min_days_overdue", "max_typical_interval_days", "exclude_seasonal"]],
  ["priority", ["high_threshold", "medium_threshold", "value_scale"]],
  ["workflow", ["today_max_cards", "dismiss_cooldown_days", "resurface_after_days", "outcome_window_days"]],
];

export function AdminPage() {
  const { t, locale } = useI18n();
  const qc = useQueryClient();
  const toast = useToast();
  const cfg = useQuery({ queryKey: ["admin-config"], queryFn: () => api<ConfigResp>("/admin/config") });
  const issues = useQuery({ queryKey: ["admin-issues"], queryFn: () => api<{ items: Issue[]; user_reports: { opportunity_id: number; source_customer_id: string; note: string | null }[] }>("/admin/data-issues") });
  const imports = useQuery({ queryKey: ["admin-imports"], queryFn: () => api<{ runs: { id: number; started_at: string; package_label: string; status: string }[] }>("/admin/imports") });
  const [draft, setDraft] = useState<Params | null>(null);
  const [note, setNote] = useState("");
  const save = useMutation({
    mutationFn: () => put<{ version: number }>("/admin/config", { params: draft, note }),
    onSuccess: (r) => {
      qc.invalidateQueries();
      setDraft(null);
      setNote("");
      toast(t("admin.saved", { v: r.version }));
    },
  });
  const refresh = useMutation({ mutationFn: () => post("/admin/refresh", {}), onSuccess: () => { qc.invalidateQueries(); toast(t("admin.refreshed")); } });

  if (cfg.isPending) return <Loading rows={3} />;
  if (cfg.isError) return <ErrorState onRetry={() => cfg.refetch()} />;
  const params = draft ?? cfg.data.params;
  const setParam = (group: string, key: string, value: unknown) =>
    setDraft({ ...params, [group]: { ...(params[group] as Record<string, unknown>), [key]: value } });
  const problems = save.error instanceof ApiError ? ((save.error.body as { error?: { problems?: string[] } })?.error?.problems ?? [save.error.code]) : [];

  return (
    <>
      <div className="page-head">
        <h1>{t("admin.title")}</h1>
      </div>
      <Section title={t("admin.config")} count={t("admin.version", { v: cfg.data.version })}>
        <div className="card stack">
          <div className="callout callout-warn small">{t("admin.configNote")}</div>
          {EDITABLE.map(([group, keys]) => (
            <fieldset key={group} style={{ border: "1px solid var(--line)", borderRadius: 10, padding: 12 }}>
              <legend className="small" style={{ fontWeight: 650 }}>{group}</legend>
              <div className="kv">
                {keys.map((k) => {
                  const v = (params[group] as Record<string, unknown>)[k];
                  return (
                    <label key={k} className="field small">
                      <span className="k">{k}</span>
                      {typeof v === "boolean" ? (
                        <input type="checkbox" checked={v} onChange={(e) => setParam(group, k, e.target.checked)} style={{ width: 22, height: 22 }} />
                      ) : (
                        <input className="input" type="number" step="any" value={String(v)} onChange={(e) => setParam(group, k, e.target.value === "" ? "" : Number(e.target.value))} />
                      )}
                    </label>
                  );
                })}
              </div>
            </fieldset>
          ))}
          <label className="field">
            <span>{t("admin.note")}</span>
            <input className="input" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
          </label>
          {problems.length > 0 && <div className="callout callout-warn small">{problems.join(" · ")}</div>}
          <div className="actions-row">
            <button className="btn btn-primary" disabled={!draft || note.trim().length < 3 || save.isPending} onClick={() => save.mutate()}>{t("admin.saveConfig")}</button>
            <button className="btn" disabled={refresh.isPending} onClick={() => refresh.mutate()}>{t("admin.refresh")}</button>
          </div>
          <p className="tiny muted" style={{ margin: 0 }}>
            {cfg.data.history.map((h) => `v${h.version} · ${fmtDateTime(h.created_at, locale)} · ${h.note ?? ""}`).join(" | ") || "v0 (defaults)"}
          </p>
        </div>
      </Section>

      <Section title={t("admin.dataIssues")} count={issues.data?.items.length}>
        <div className="card table-wrap">
          {issues.isPending ? <Loading rows={1} /> : (
            <table className="data">
              <thead><tr><th>Severity</th><th>Issue</th><th>Customer</th><th>Detail</th></tr></thead>
              <tbody>
                {issues.data?.items.map((i) => (
                  <tr key={i.id}>
                    <td><Chip tone={i.severity === "error" ? "high" : i.severity === "warning" ? "warn" : "neutral"}>{i.severity}</Chip></td>
                    <td>{t(`issue.${i.issue_code}`)}<div className="tiny muted">{i.stage}</div></td>
                    <td className="small">{i.source_entity ?? ""} {i.source_customer_id ?? ""}</td>
                    <td className="tiny muted" style={{ maxWidth: 320, overflowWrap: "anywhere" }}>{JSON.stringify(i.detail)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {issues.data && issues.data.user_reports.length > 0 && (
            <>
              <h3 style={{ marginTop: 16 }}>{t("admin.userReports")}</h3>
              <ul className="timeline">
                {issues.data.user_reports.map((r) => <li key={r.opportunity_id} className="small">{r.source_customer_id}: {r.note}</li>)}
              </ul>
            </>
          )}
        </div>
      </Section>

      <Section title={t("admin.imports")}>
        <div className="card">
          <ul className="timeline">
            {imports.data?.runs.map((r) => (
              <li key={r.id} className="small">#{r.id} · {fmtDateTime(r.started_at, locale)} · {r.package_label} · <Chip tone={r.status === "loaded" ? "ok" : "high"}>{r.status}</Chip></li>
            ))}
          </ul>
        </div>
      </Section>
    </>
  );
}
