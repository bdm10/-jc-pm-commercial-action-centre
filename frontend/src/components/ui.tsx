import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useI18n } from "../i18n";
import type { Band, Entity } from "../api/types";

export function EntityBadge({ entity }: { entity: Entity }) {
  return (
    <span className={`ebadge ebadge-${entity}`} title={entity}>
      {entity}
    </span>
  );
}

export function PriorityChip({ band }: { band: Band }) {
  const { t } = useI18n();
  const level = band === "high" ? 3 : band === "medium" ? 2 : 1;
  return (
    <span className={`chip chip-${band}`} data-testid="priority">
      <span className="bars" aria-hidden="true">
        {[1, 2, 3].map((i) => (
          <i key={i} className={i <= level ? "on" : ""} />
        ))}
      </span>
      {t(`priority.${band}`)}
    </span>
  );
}

export function Chip({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "ok" | "warn" | "type" | "high" | "low" }) {
  return <span className={`chip chip-${tone}`}>{children}</span>;
}

export function Loading({ rows = 3 }: { rows?: number }) {
  const { t } = useI18n();
  return (
    <div className="stack" aria-busy="true" aria-live="polite">
      <span className="visually-hidden">{t("app.loading")}</span>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton" style={{ height: 132 }} />
      ))}
    </div>
  );
}

export function ErrorState({ onRetry, notFound }: { onRetry?: () => void; notFound?: boolean }) {
  const { t } = useI18n();
  return (
    <div className="card state" role="alert">
      <h3>{notFound ? t("state.notFound") : t("state.error.title")}</h3>
      {!notFound && <p>{t("state.error.body")}</p>}
      {onRetry && (
        <button className="btn" onClick={onRetry}>
          {t("app.retry")}
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, body, children }: { title: string; body?: string; children?: ReactNode }) {
  return (
    <div className="card flat state">
      <h3>{title}</h3>
      {body && <p>{body}</p>}
      {children}
    </div>
  );
}

export function Section({ title, count, children, action }: { title: string; count?: ReactNode; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="section">
      <div className="section-head">
        <h2>{title}</h2>
        {count !== undefined && <span className="count">{count}</span>}
        {action}
      </div>
      {children}
    </section>
  );
}

// ---------- toast ----------
const ToastCtx = createContext<(msg: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [msg, setMsg] = useState<string | null>(null);
  const show = useCallback((m: string) => setMsg(m), []);
  useEffect(() => {
    if (!msg) return;
    const id = setTimeout(() => setMsg(null), 5000);
    return () => clearTimeout(id);
  }, [msg]);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      <div aria-live="polite" role="status">
        {msg && (
          <div className="toast" data-testid="toast">
            {msg}
          </div>
        )}
      </div>
    </ToastCtx.Provider>
  );
}
