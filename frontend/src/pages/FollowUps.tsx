import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useI18n } from "../i18n";
import { api, patch } from "../api/client";
import type { FollowUp, FollowUpList } from "../api/types";
import { useSession } from "../session";
import { addDays } from "../lib/format";
import { FollowUpRow } from "../components/FollowUpRow";
import { ErrorState, Loading, Section, useToast } from "../components/ui";

export function FollowUpsPage() {
  const { t } = useI18n();
  const { me, openSheet } = useSession();
  const [view, setView] = useState<"mine" | "team">("mine");
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["follow-ups", view], queryFn: () => api<FollowUpList>(`/follow-ups?view=${view}`) });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: number; body: unknown }) => patch(`/follow-ups/${id}`, body),
    onSuccess: () => {
      qc.invalidateQueries();
      toast("✓");
    },
  });
  const rec = (f: FollowUp) =>
    openSheet({
      entity: f.customer.source_entity,
      customerId: f.customer.source_customer_id,
      customerName: f.customer.display_name,
      opportunityId: f.opportunity_id,
      oppTypeLabel: f.opp_type ? t(`oppType.${f.opp_type}`) : undefined,
    });
  const canEdit = (f: FollowUp) => f.owner.id === me.id || me.role !== "sales";
  const extra = (f: FollowUp) =>
    canEdit(f) && (
      <>
        <button className="btn btn-ghost btn-small" onClick={() => update.mutate({ id: f.id, body: { due_date: addDays(me.today, 7) } })}>
          {t("fu.reschedule")} +7
        </button>
        <button className="btn btn-ghost btn-small" onClick={() => update.mutate({ id: f.id, body: { status: "cancelled" } })}>
          {t("fu.cancel")}
        </button>
      </>
    );

  const group = (title: string, rows: FollowUp[]) => (
    <Section title={title} count={rows.length}>
      <div className="card" style={{ paddingTop: 4, paddingBottom: 4 }}>
        {rows.length === 0 ? (
          <p className="muted">{t("fu.empty")}</p>
        ) : (
          <div className="list">
            {rows.map((f) => (
              <FollowUpRow key={f.id} f={f} onRecord={() => rec(f)} showOwner={view === "team"} extra={extra(f)} />
            ))}
          </div>
        )}
      </div>
    </Section>
  );

  return (
    <>
      <div className="page-head">
        <h1>{t("fu.title")}</h1>
      </div>
      {me.role !== "sales" && (
        <div className="filters">
          <div className="toggle" role="group">
            <button aria-pressed={view === "mine"} onClick={() => setView("mine")}>{t("fu.mine")}</button>
            <button aria-pressed={view === "team"} onClick={() => setView("team")}>{t("fu.team")}</button>
          </div>
        </div>
      )}
      {q.isPending && <Loading rows={3} />}
      {q.isError && <ErrorState onRetry={() => q.refetch()} />}
      {q.data && (
        <>
          {group(t("fu.overdue"), q.data.overdue)}
          {group(t("fu.today"), q.data.today)}
          {group(t("fu.upcoming"), q.data.upcoming)}
          {group(t("fu.done"), q.data.done_recent)}
        </>
      )}
    </>
  );
}
