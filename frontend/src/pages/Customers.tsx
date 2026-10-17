import { useDeferredValue, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useI18n } from "../i18n";
import { api } from "../api/client";
import type { CustomerListItem } from "../api/types";
import { fmtDate } from "../lib/format";
import { Chip, EmptyState, EntityBadge, ErrorState, Loading, PriorityChip } from "../components/ui";

export function CustomersPage() {
  const { t, locale } = useI18n();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const entity = params.get("entity") ?? "";
  const withOpp = params.get("with_opportunity") === "1";
  const dq = useDeferredValue(q);
  const query = useQuery({
    queryKey: ["customers", dq, entity, withOpp],
    queryFn: () =>
      api<{ total: number; items: CustomerListItem[] }>(
        `/customers?limit=200&q=${encodeURIComponent(dq)}&entity=${entity}&with_opportunity=${withOpp}`,
      ),
    placeholderData: (prev) => prev,
  });
  const set = (k: string, v: string | null) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    setParams(next, { replace: true });
  };

  return (
    <>
      <div className="page-head">
        <h1>{t("customers.title")}</h1>
      </div>
      <div className="field">
        <label className="visually-hidden" htmlFor="customer-search">{t("customers.search")}</label>
        <input id="customer-search" className="input" type="search" placeholder={t("customers.search")} value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="filters">
        <div className="toggle" role="group">
          {["", "JC", "PM"].map((e) => (
            <button key={e || "all"} aria-pressed={entity === e} onClick={() => set("entity", e || null)}>
              {e || t("customers.all")}
            </button>
          ))}
        </div>
        <label className="check">
          <input type="checkbox" checked={withOpp} onChange={(e) => set("with_opportunity", e.target.checked ? "1" : null)} />
          {t("customers.withOpp")}
        </label>
        {query.data && <span className="muted small">{t("customers.count", { n: query.data.total })}</span>}
      </div>
      {query.isPending && <Loading rows={4} />}
      {query.isError && <ErrorState onRetry={() => query.refetch()} />}
      {query.data &&
        (query.data.items.length === 0 ? (
          <EmptyState title={t("customers.empty")} />
        ) : (
          <div className="card" style={{ paddingTop: 4, paddingBottom: 4 }}>
            <div className="list">
              {query.data.items.map((c) => (
                <div className="row" key={`${c.source_entity}:${c.source_customer_id}`} data-testid="customer-row">
                  <Link className="row-link" to={`/customers/${c.source_entity}/${encodeURIComponent(c.source_customer_id)}`}>
                    <EntityBadge entity={c.source_entity} />
                    <div className="row-main">
                      <div className="row-title">{c.display_name}</div>
                      <div className="row-meta">
                        <span>{c.source_customer_id}</span>
                        {c.city && <span>{c.city}</span>}
                        <span>{c.last_order_date ? t("customers.lastOrder", { date: fmtDate(c.last_order_date, locale) }) : t("customers.noOrders")}</span>
                        {c.opportunities.map((o) => (
                          <span key={o.id}>{t(`oppType.${o.opp_type}`)}</span>
                        ))}
                      </div>
                    </div>
                  </Link>
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
                    {c.best_priority ? <PriorityChip band={c.best_priority} /> : <span className="tiny muted">{t("customers.noOpp")}</span>}
                    {c.has_data_issue && <Chip tone="warn">{t("customers.dataIssue")}</Chip>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
    </>
  );
}
