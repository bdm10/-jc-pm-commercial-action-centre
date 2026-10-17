// Bottom sheet for recording an action in under 30 seconds: one tap for what happened,
// optional note, one tap for the follow-up date, save. Snooze/dismiss live behind a secondary link.
import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useI18n } from "../i18n";
import { ApiError, newRequestId, post } from "../api/client";
import type { ActionType, Entity, Me } from "../api/types";
import { addDays, fmtDate } from "../lib/format";
import { EntityBadge, useToast } from "./ui";

export interface SheetTarget {
  entity: Entity;
  customerId: string;
  customerName: string | null;
  opportunityId: number | null;
  oppTypeLabel?: string;
  initialMode?: "action" | "more";
}

const FU_PRESETS: { key: string; days: number | null }[] = [
  { key: "action.fu.none", days: null },
  { key: "action.fu.tomorrow", days: 1 },
  { key: "action.fu.3d", days: 3 },
  { key: "action.fu.1w", days: 7 },
  { key: "action.fu.2w", days: 14 },
];

export function ActionSheet({ target, me, today, onClose }: { target: SheetTarget; me: Me; today: string; onClose: () => void }) {
  const { t, locale } = useI18n();
  const toast = useToast();
  const qc = useQueryClient();
  const [mode, setMode] = useState<"action" | "more">(target.initialMode ?? "action");
  const [actionType, setActionType] = useState<ActionType | null>(null);
  const [note, setNote] = useState("");
  const [fuPreset, setFuPreset] = useState<string>("action.fu.3d");
  const [fuDate, setFuDate] = useState<string>(addDays(today, 3));
  const [snoozeDays, setSnoozeDays] = useState<number>(me.options.snooze_options_days[1] ?? 14);
  const [snoozeReason, setSnoozeReason] = useState("");
  const [dismissReason, setDismissReason] = useState<string>("already_handled");
  const [dismissNote, setDismissNote] = useState("");
  const [requestId] = useState(newRequestId);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    dialogRef.current?.querySelector<HTMLElement>("button.option, button")?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const invalidate = () => qc.invalidateQueries();

  const record = useMutation({
    mutationFn: () =>
      post<{ follow_up: { due_date: string } | null }>("/actions", {
        client_request_id: requestId,
        source_entity: target.entity,
        source_customer_id: target.customerId,
        opportunity_id: target.opportunityId,
        action_type: actionType,
        note: note.trim() || null,
        follow_up_date: fuPreset === "action.fu.none" || actionType === "not_relevant" ? null : fuDate,
      }),
    onSuccess: (r) => {
      invalidate();
      toast(`${t("action.saved")}${r.follow_up ? " " + t("action.savedFollowUp", { date: fmtDate(r.follow_up.due_date, locale) }) : ""}`);
      onClose();
    },
  });
  const snooze = useMutation({
    mutationFn: () => post<{ snoozed_until: string }>(`/opportunities/${target.opportunityId}/snooze`, { days: snoozeDays, reason: snoozeReason.trim() || null }),
    onSuccess: (r) => {
      invalidate();
      toast(t("snooze.done", { date: fmtDate(r.snoozed_until, locale) }));
      onClose();
    },
  });
  const dismiss = useMutation({
    mutationFn: () => post(`/opportunities/${target.opportunityId}/dismiss`, { reason_code: dismissReason, note: dismissNote.trim() || null }),
    onSuccess: () => {
      invalidate();
      toast(t("dismiss.done"));
      onClose();
    },
  });
  const noteRequired = ["other", "data_incorrect"].includes(dismissReason) && !dismissNote.trim();
  const busy = record.isPending || snooze.isPending || dismiss.isPending;
  const failed = [record.error, snooze.error, dismiss.error].find(Boolean) as ApiError | undefined;

  return (
    <div className="overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="sheet" role="dialog" aria-modal="true" aria-labelledby="sheet-title" ref={dialogRef} data-testid="action-sheet">
        <div className="sheet-grip" />
        <div className="sheet-head">
          <EntityBadge entity={target.entity} />
          <div className="title">
            <h2 id="sheet-title">{mode === "action" ? t("action.title") : `${t("snooze.title")} / ${t("dismiss.title")}`}</h2>
            <div className="muted small">
              {target.customerName} · {target.customerId}
              {target.oppTypeLabel ? ` · ${target.oppTypeLabel}` : ""}
            </div>
          </div>
          <button className="btn btn-ghost btn-small" onClick={onClose} aria-label={t("app.close")}>
            ✕
          </button>
        </div>

        {mode === "action" ? (
          <>
            <fieldset className="sheet-section" style={{ border: 0, padding: 0, margin: 0 }}>
              <legend className="label" style={{ fontWeight: 600, marginBottom: 8 }}>
                {t("action.what")}
              </legend>
              <div className="options">
                {me.options.action_types.map((a) => (
                  <button key={a} type="button" className="option" aria-pressed={actionType === a} onClick={() => setActionType(a)}>
                    <span className="tick" aria-hidden="true" />
                    {t(`action.${a}`)}
                  </button>
                ))}
              </div>
              {actionType === "not_relevant" && <p className="small muted">{t("action.notRelevantHint")}</p>}
            </fieldset>

            <div className="sheet-section field">
              <label htmlFor="note">{t("action.note")}</label>
              <textarea id="note" maxLength={280} value={note} placeholder={t("action.notePlaceholder")} onChange={(e) => setNote(e.target.value)} />
              <span className="tiny muted" style={{ alignSelf: "flex-end" }}>
                {t("action.chars", { n: note.length })}
              </span>
            </div>

            {actionType !== "not_relevant" && (
              <div className="sheet-section field">
                <span className="label">{t("action.followUp")}</span>
                <div className="chips-select" role="group" aria-label={t("action.followUp")}>
                  {FU_PRESETS.map((p) => (
                    <button
                      key={p.key}
                      type="button"
                      aria-pressed={fuPreset === p.key}
                      onClick={() => {
                        setFuPreset(p.key);
                        if (p.days !== null) setFuDate(addDays(today, p.days));
                      }}
                    >
                      {t(p.key)}
                    </button>
                  ))}
                  <button type="button" aria-pressed={fuPreset === "action.fu.pick"} onClick={() => setFuPreset("action.fu.pick")}>
                    {t("action.fu.pick")}
                  </button>
                </div>
                {fuPreset === "action.fu.pick" && (
                  <input
                    className="input"
                    type="date"
                    aria-label={t("action.fu.pick")}
                    min={today}
                    max={addDays(today, me.options.follow_up_max_days_ahead)}
                    value={fuDate}
                    onChange={(e) => setFuDate(e.target.value)}
                  />
                )}
                {fuPreset !== "action.fu.none" && <span className="small muted">{t("fu.due", { date: fmtDate(fuDate, locale) })}</span>}
              </div>
            )}

            <div className="sheet-foot">
              {failed && <div className="callout callout-warn">{t("action.error")}</div>}
              <button className="btn btn-primary btn-block" disabled={!actionType || busy} onClick={() => record.mutate()}>
                {t("app.save")}
              </button>
              {target.opportunityId && (
                <button className="linkbtn" onClick={() => setMode("more")}>
                  {t("action.more")}
                </button>
              )}
            </div>
          </>
        ) : (
          <>
            <div className="sheet-section field">
              <span className="label">{t("snooze.title")}</span>
              <div className="chips-select">
                {me.options.snooze_options_days.map((d) => (
                  <button key={d} type="button" aria-pressed={snoozeDays === d} onClick={() => setSnoozeDays(d)}>
                    {t("snooze.days", { n: d })}
                  </button>
                ))}
              </div>
              <input className="input" aria-label={t("snooze.reason")} placeholder={t("snooze.reason")} maxLength={280} value={snoozeReason} onChange={(e) => setSnoozeReason(e.target.value)} />
              <button className="btn" disabled={busy} onClick={() => snooze.mutate()}>
                {t("snooze.title")} · {t("snooze.days", { n: snoozeDays })}
              </button>
            </div>
            <div className="sheet-section field">
              <label htmlFor="dismiss-reason">{t("dismiss.title")}</label>
              <select id="dismiss-reason" className="input" value={dismissReason} onChange={(e) => setDismissReason(e.target.value)}>
                {me.options.dismiss_reasons.map((r) => (
                  <option key={r} value={r}>
                    {t(`dismiss.${r}`)}
                  </option>
                ))}
              </select>
              <input className="input" aria-label={t("dismiss.note")} placeholder={t("dismiss.note")} maxLength={280} value={dismissNote} onChange={(e) => setDismissNote(e.target.value)} />
              {noteRequired && <span className="small muted">{t("dismiss.noteRequired")}</span>}
              <button className="btn" disabled={busy || noteRequired} onClick={() => dismiss.mutate()}>
                {t("dismiss.title")}
              </button>
            </div>
            <div className="sheet-foot">
              {failed && <div className="callout callout-warn">{t("action.error")}</div>}
              <button className="linkbtn" onClick={() => setMode("action")}>
                ← {t("action.title")}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
