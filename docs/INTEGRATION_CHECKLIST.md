# Integration checklist (before any live pilot)

Status key: ☐ not started · ◐ scaffolded / partial (not verified against the real system) · ☑ done and verified

## 1. Microsoft Entra ID (authentication)

| | Item | Status |
|---|---|---|
| 1.1 | Register an **API** app (expose scope `access_as_user`) and a **SPA** app (redirect URIs for the hosted URL) | ☐ |
| 1.2 | Set `AUTH_MODE=entra`, `ENTRA_TENANT_ID`, `ENTRA_API_CLIENT_ID`, `ENTRA_SPA_CLIENT_ID`, `ENTRA_API_SCOPE` from Key Vault | ☐ |
| 1.3 | Backend validates v2.0 access tokens: signature via tenant JWKS, issuer, audience, expiry, tenant, scope (`app/auth/entra.py`) | ◐ unit-tested with locally signed keys only |
| 1.4 | Frontend sign-in (MSAL redirect and silent token, `Authorization: Bearer`) | ☐ the UI shows "not connected yet" in entra mode |
| 1.5 | Provision users: map Entra `oid` to `app_user.entra_object_id`, role, salesperson code, team (`python -m app.cli create-user`). Decide whether roles come from Entra groups or app records. | ◐ CLI only |
| 1.6 | Fail closed: production refuses to start without `AUTH_MODE=entra`; unset auth rejects every request | ☑ tested |
| 1.7 | Cross-user access tests with real accounts (salesperson A vs B; manager A vs manager B) | ◐ covered with demo identities |

## 2. Certified Fabric / Power BI data

| | Item | Status |
|---|---|---|
| 2.1 | Confirm workspace and model IDs, owners, refresh schedule and **certification** for *JUVE Ventas base* and *PM Ventas base* | ☐ |
| 2.2 | Approved read-only access method (service principal with Build permission, or a Fabric lakehouse export). Credentials in Key Vault only. | ☐ |
| 2.3 | Exact certified measure names and business definitions entered in `measure_definitions.csv` with approver and date | ☐ |
| 2.4 | Extract job applies the **approved default filters** for each model, records the filter version in `filters_applied`, and writes the contract package to the import inbox | ☐ |
| 2.5 | `source_refreshed_at` taken from the model's last successful refresh, not from the extract time | ☐ |
| 2.6 | Nexora / JC↔PM mapping table with approval status, transfer date and cohort, as `customer_mapping.csv` | ☐ |
| 2.7 | Assignment source (salesperson, manager, validity dates) as `assignments.csv` | ☐ |
| 2.8 | **Reconcile** a sample of totals with an approved report and record the result | ☐ |
| 2.9 | Allow live data only after 2.1–2.8 (`ALLOW_LIVE_IMPORT=true`) | ☐ |
| 2.10 | Import validation, duplicate control, stale handling and data issues | ☑ with synthetic data |
| 2.11 | Scheduled refresh (`python -m app.cli scheduler`, inbox + re-evaluation) | ◐ runs locally; not deployed |

## 3. MiPM (current workflow)

| | Item | Status |
|---|---|---|
| 3.1 | Document where visits, notes, tasks and follow-ups are recorded today (3–5 anonymised screenshots) | ☐ |
| 3.2 | Decide the **system of record** for activities (this app, MiPM, or both) | ☐ |
| 3.3 | Choose **embed / link / synchronise**. If syncing, confirm MiPM's integration options (API, export) and the direction. | ☐ |
| 3.4 | Until then: no writeback, no automatic messages (enforced: there are no outbound integrations) | ☑ |

## 4. Hosting and operations

| | Item | Status |
|---|---|---|
| 4.1 | Container platform (for example Azure Container Apps or App Service) running the single image: API + built SPA | ◐ image built and run locally (demo mode, access + journey checks passed); no pilot hosting yet |
| 4.1a | Login-protected **synthetic demo** on Render's free tier (`render.yaml`, [DEPLOY_DEMO.md](DEPLOY_DEMO.md)) | ◐ configuration ready; image built from a clean checkout and tested as Render runs it; Render account and deployment pending |
| 4.2 | Managed PostgreSQL 16 with private networking, backups and point-in-time restore. Run `python -m app.cli migrate` on deploy. | ☐ |
| 4.3 | Separate DB roles: the API role needs `SELECT` on `facts`; only the import/refresh job writes `facts` | ☐ |
| 4.4 | Scheduler as a second container or job, with the same image and `python -m app.cli scheduler` | ◐ |
| 4.5 | Secrets in Key Vault and managed identity. Nothing in the repository (`.env` is gitignored). | ◐ |
| 4.6 | Restrict access to the corporate network or Entra Conditional Access; HTTPS only | ☐ |
| 4.7 | Logging and monitoring; alert on failed or stale refresh | ☐ |
| 4.8 | Retention for notes, audit log and AI drafts agreed with the data owner | ☐ |

## 5. Optional AI provider

| | Item | Status |
|---|---|---|
| 5.1 | Approval to send customer evidence (names, figures, notes) to an external model provider | ☐ |
| 5.2 | `AI_PROVIDER=anthropic`, key in Key Vault | ☐ (off by default) |
| 5.3 | Guard: only cited facts, no invented numbers, no prices, discounts or stock, notes treated as untrusted | ☑ tested with a fake provider. No live calls were made. |
