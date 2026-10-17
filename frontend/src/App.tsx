import { useEffect, useState, type ReactNode } from "react";
import { BrowserRouter, Navigate, NavLink, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { I18nProvider, useI18n } from "./i18n";
import { api, ApiError, getDemoUser, setDemoUser } from "./api/client";
import type { Me, Meta } from "./api/types";
import { fmtDateTime } from "./lib/format";
import { ErrorState, Loading, ToastProvider } from "./components/ui";
import { ActionSheet, type SheetTarget } from "./components/ActionSheet";
import { TodayPage } from "./pages/Today";
import { CustomersPage } from "./pages/Customers";
import { CustomerDetailPage } from "./pages/CustomerDetail";
import { FollowUpsPage } from "./pages/FollowUps";
import { TeamPage } from "./pages/Team";
import { AdminPage } from "./pages/Admin";
import { SessionCtx, useSession, type Session } from "./session";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (n, err) => !(err instanceof ApiError && err.status < 500) && n < 2,
      refetchOnWindowFocus: true,
    },
  },
});


export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <ToastProvider>
          <BrowserRouter>
            <Bootstrap />
          </BrowserRouter>
        </ToastProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
}

function Bootstrap() {
  const { t } = useI18n();
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => api<Meta>("/meta"), staleTime: Infinity });
  const [demoUser, setDemoUserState] = useState<string | null>(getDemoUser);

  if (meta.isPending) return <div className="authbox"><Loading rows={1} /></div>;
  if (meta.isError) return <div className="authbox"><ErrorState onRetry={() => meta.refetch()} /></div>;
  const m = meta.data;
  if (!m.auth_configured) return <AuthMessage title={t("auth.notConfigured.title")} body={t("auth.notConfigured.body")} />;
  if (m.auth_mode === "entra") return <AuthMessage title={t("auth.entra.title")} body={t("auth.entra.body")} />;
  const choose = (email: string | null) => {
    setDemoUser(email);
    setDemoUserState(email);
    queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== "meta" });
  };
  if (m.demo_mode && !demoUser) return <DemoPicker onPick={choose} />;
  return <Authenticated meta={m} demoUser={demoUser} onSwitch={choose} />;
}

function AuthMessage({ title, body }: { title: string; body: string }) {
  return (
    <div className="authbox card" role="alert">
      <h1 style={{ fontSize: 20 }}>{title}</h1>
      <p className="muted">{body}</p>
    </div>
  );
}

function DemoPicker({ onPick }: { onPick: (email: string) => void }) {
  const { t } = useI18n();
  const users = useQuery({ queryKey: ["demo-users"], queryFn: () => api<{ email: string; display_name: string; role: string }[]>("/demo/users") });
  return (
    <div className="authbox">
      <div className="card">
        <h1 style={{ fontSize: 20 }}>{t("app.title")}</h1>
        <div className="callout callout-info" style={{ marginTop: 8 }}>{t("banner.demo")}</div>
        <p style={{ marginBottom: 0 }}><strong>{t("auth.demo.pick")}</strong></p>
        {users.isPending ? <Loading rows={2} /> : (
          <div className="userpick">
            {users.data?.map((u) => (
              <button key={u.email} className="btn" onClick={() => onPick(u.email)}>
                <span>{u.display_name}</span>
                <span className="muted small">{t(`role.${u.role}`)}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Authenticated({ meta, demoUser, onSwitch }: { meta: Meta; demoUser: string | null; onSwitch: (e: string | null) => void }) {
  const { t } = useI18n();
  const me = useQuery({ queryKey: ["me", demoUser], queryFn: () => api<Me>("/me") });
  const [sheet, setSheet] = useState<SheetTarget | null>(null);
  const unknownDemoUser = me.error instanceof ApiError && me.error.status === 401 && meta.demo_mode;
  useEffect(() => {
    if (unknownDemoUser) onSwitch(null); // stale demo selection (e.g. after re-seeding): pick again
  }, [unknownDemoUser, onSwitch]);
  if (me.isPending || unknownDemoUser) return <div className="authbox"><Loading rows={2} /></div>;
  if (me.isError) {
    return <AuthMessage title={t("auth.error")} body={String((me.error as ApiError).code ?? "")} />;
  }
  const session: Session = { me: me.data, meta, openSheet: setSheet };
  return (
    <SessionCtx.Provider value={session}>
      <Shell demoUser={demoUser} onSwitch={onSwitch}>
        <Routes>
          <Route path="/" element={<TodayPage />} />
          <Route path="/customers" element={<CustomersPage />} />
          <Route path="/customers/:entity/:customerId" element={<CustomerDetailPage />} />
          <Route path="/follow-ups" element={<FollowUpsPage />} />
          {me.data.role !== "sales" && <Route path="/team" element={<TeamPage />} />}
          {me.data.role === "admin" && <Route path="/admin" element={<AdminPage />} />}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Shell>
      {sheet && <ActionSheet target={sheet} me={me.data} today={me.data.today} onClose={() => setSheet(null)} />}
    </SessionCtx.Provider>
  );
}

const icons: Record<string, ReactNode> = {
  today: <path d="M4 6h16M4 12h16M4 18h10" />,
  customers: <><circle cx="9" cy="8" r="3.2" /><path d="M3 19c0-3.3 2.7-5.5 6-5.5s6 2.2 6 5.5M16 5.5a3 3 0 0 1 0 5.8M18 13.8c1.9.6 3 2.6 3 5.2" /></>,
  followups: <><rect x="4" y="5" width="16" height="15" rx="2" /><path d="M8 3v4M16 3v4M4 10h16M9 15l2 2 4-4" /></>,
  team: <><circle cx="12" cy="7" r="3" /><path d="M5 20c0-3.6 3.1-6 7-6s7 2.4 7 6" /></>,
  admin: <><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" /></>,
};

function NavItems({ role }: { role: Me["role"] }) {
  const { t } = useI18n();
  const items: [string, string, string][] = [
    ["/", "today", t("nav.today")],
    ["/customers", "customers", t("nav.customers")],
    ["/follow-ups", "followups", t("nav.followups")],
  ];
  if (role !== "sales") items.push(["/team", "team", t("nav.team")]);
  if (role === "admin") items.push(["/admin", "admin", t("nav.admin")]);
  return (
    <>
      {items.map(([to, icon, label]) => (
        <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => `navlink${isActive ? " active" : ""}`}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            {icons[icon]}
          </svg>
          <span>{label}</span>
        </NavLink>
      ))}
    </>
  );
}

function Shell({ children, demoUser, onSwitch }: { children: ReactNode; demoUser: string | null; onSwitch: (e: string) => void }) {
  const { t, lang, setLang, locale } = useI18n();
  const { me, meta } = useSession();
  const users = useQuery({
    queryKey: ["demo-users"],
    queryFn: () => api<{ email: string; display_name: string; role: string }[]>("/demo/users"),
    enabled: meta.demo_mode,
  });
  const synthetic = me.freshness.some((f) => f.data_classification === "synthetic");
  return (
    <div className="app">
      <header className={`topbar${meta.demo_mode ? " has-switcher" : ""}`}>
        <div className="brand">
          <strong>{t("app.title")}</strong>
          <span>{t("app.subtitle")} · {me.display_name} · {t(`role.${me.role}`)}</span>
        </div>
        <div className="spacer" />
        {meta.demo_mode && users.data && (
          <select aria-label={t("app.user")} value={demoUser ?? ""} onChange={(e) => onSwitch(e.target.value)} data-testid="demo-switcher">
            {users.data.map((u) => (
              <option key={u.email} value={u.email}>
                {u.display_name} ({t(`role.${u.role}`)})
              </option>
            ))}
          </select>
        )}
        <button className="lang" onClick={() => setLang(lang === "es" ? "en" : "es")} aria-label={t("app.language")}>
          {lang === "es" ? "EN" : "ES"}
        </button>
      </header>
      <div className="banners">
        {meta.demo_mode && (
          <div className="banner banner-demo"><span className="tag">Demo</span><span>{t("banner.demo")}</span></div>
        )}
        {synthetic && (
          <div className="banner banner-synthetic" data-testid="synthetic-banner"><span className="tag">{lang === "es" ? "Sintético" : "Synthetic"}</span><span>{t("banner.synthetic")}</span></div>
        )}
        {me.freshness.filter((f) => f.is_stale).map((f) => (
          <div key={f.entity} className="banner banner-stale" role="alert" data-testid="stale-banner">
            <span className="tag">{f.entity}</span>
            <span>{t("banner.stale", { entity: f.entity, date: fmtDateTime(f.refreshed_at, locale) })}</span>
          </div>
        ))}
      </div>
      <div className="layout">
        <nav className="sidenav" aria-label="principal"><NavItems role={me.role} /></nav>
        <main id="main">{children}</main>
      </div>
      <nav className="bottomnav" aria-label="principal"><NavItems role={me.role} /></nav>
    </div>
  );
}
