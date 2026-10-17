# Hosted demo (password-protected, synthetic data)

A browser-accessible demo for showing the prototype to colleagues.

**What it is:**
- **Synthetic data only.** It is generated inside the app; the demo refuses any other import, and there are no connections to company systems.
- **No AI calls.** The AI provider is off.
- **No credentials in Git.**

**What it is not:** the pilot. Real data, Microsoft sign-in and the integrations remain open ([INTEGRATION_CHECKLIST.md](INTEGRATION_CHECKLIST.md)).

## Why Render

| Need | How it is met |
|---|---|
| Simplest setup for one container plus PostgreSQL | One **Blueprint** file ([`render.yaml`](../render.yaml)): a few clicks create the web service and database from the PR branch |
| Credentials outside GitHub | Render generates `DEMO_ACCESS_PASSWORD` and stores it in the service settings. The database URL is injected by Render. |
| HTTPS, EU region | Automatic TLS on `*.onrender.com`; region `frankfurt` |
| Easy updates | Every push to the branch redeploys automatically |

**Longer term:** the company stack points to **Azure** (Container Apps + Azure Database for PostgreSQL + Entra ID) for the real pilot. That needs an Azure subscription and IT permissions, so it is not the quickest way to a demo.

## Cost (confirm before applying)

| Resource | Plan in `render.yaml` | Approx. price |
|---|---|---|
| Web service | `starter` (512 MB, always on) | US$7 / month |
| PostgreSQL | `basic-256mb` | US$6 / month, plus storage ≈ US$0.30 per GB-month |
| **Total** | | **≈ US$13–14 / month**, billed by the second, stops when deleted |

- **Source:** third-party price summaries dated July 2026. Render's own site was not reachable from the build environment. Render shows the exact monthly cost in the Blueprint review screen **before** anything is created. Paid plans need a card on the Render workspace.
- **Free alternative:** set both `plan:` values to `free`. The web service then sleeps after 15 idle minutes (the first visit takes about a minute), and the free database is **deleted 30 days after creation** (plus a 14-day grace period).

## How the demo is protected

- **Shared password on everything.** Every page, static file, API endpoint and the API docs require `DEMO_ACCESS_USER` / `DEMO_ACCESS_PASSWORD` (browser sign-in prompt, HTTP Basic over HTTPS).
- **Open health check:** only `/healthz`, which returns `{"status":"ok"}` and no data.
- **Brute-force throttle:** 20 wrong attempts from one address within 10 minutes block that address for 10 minutes.
- **Demo-user switching** (Ana, Elena, Admin and so on) sits *behind* the password, by design. Anyone with the password can act as any demo user.
- **Fail-closed configuration.** `APP_ENV=demo` refuses to start if any of these holds:
  - the password is missing or shorter than 16 characters;
  - `AUTH_MODE` is not `demo`;
  - AI is enabled;
  - live or inbox imports are configured;
  - local development database credentials are used.
- **Synthetic data only.** The importer accepts nothing but `data_classification=synthetic`.
- **Hidden from search engines and private database.** Responses carry `X-Robots-Tag: noindex`, and the database has no public access (`ipAllowList: []`).

## Deploy: minimum account steps (about 15 minutes, mostly build time)

1. **Create the Render account.** Go to <https://dashboard.render.com/register> and choose **Sign up with GitHub** (the account that owns the repository).
2. **Give Render access to the repository.** When Render asks to install its GitHub app, choose **Only select repositories** → `bdm10/-jc-pm-commercial-action-centre`.
3. **Add a payment method:** Workspace → **Billing** → add a card. This is only needed for the paid plans.
4. **Create the Blueprint:** **New → Blueprint** → select the repository → branch **`dev/commercial-action-centre-prototype`**. Render reads `render.yaml` and lists:
   - web service `jc-pm-action-centre-demo`;
   - database `jc-pm-action-centre-demo-db`.
   
   Check the cost shown, then **Apply** (or **Deploy Blueprint**).
5. **Wait for the first build.** It takes about 5–10 minutes; the service's **Events** shows *Deploy live*. On first start the app creates its tables and generates the synthetic demo.
6. **Get the password:** open the web service → **Environment** → `DEMO_ACCESS_PASSWORD` → reveal and copy.
   - To use a memorable passphrase instead, edit the value (at least 16 characters) and **Save changes**; the service restarts.
7. **Open the URL** at the top of the service page, e.g. `https://jc-pm-action-centre-demo.onrender.com`. Render adds a suffix if that name is taken.

## Check it (2 minutes)

1. Open the URL in a **private window**. The browser asks for a username and password. Press **Cancel**: you see only `{"error":{"code":"access_required"}}`.
2. Reload and sign in with **`demo`** and the password. Pick **Ana Ruiz** and record an action on a card.
3. Switch to **Elena Martín** (top right) and open **Equipo**.

The same checks are automated (`frontend/e2e/access.spec.ts`, plus the journeys). Run them against the live URL with:

```bash
cd frontend
E2E_BASE_URL=https://<your-url> E2E_HTTP_PASSWORD='<password>' E2E_SKIP_SEED=1 \
  npx playwright test e2e/access.spec.ts
```

Run only `access.spec.ts` against the hosted demo. `journeys.spec.ts` re-seeds a database through the local CLI, so it is meant for local runs.

## Giving colleagues access

- **Share the URL and the password separately**, for example the URL in the meeting invite and the password in a direct message. The username is `demo`.
- **Everyone sees the same demo.** Actions recorded by one person are visible to others, because they share the demo users.
- **The demo resets once a day.** When the synthetic data is more than 24 hours old (first check after about 06:00 Madrid time), the app regenerates it and clears recorded actions. This keeps dates current and avoids the stale-data state. Restarts and redeploys on the same day keep the data.

## Update, pause or shut down

| Task | How |
|---|---|
| **Update the demo** | Push to `dev/commercial-action-centre-prototype`; Render rebuilds and redeploys automatically (~5 min) |
| **After merging the PR** | Change `branch:` in `render.yaml` to `main`, or in Render: service → **Settings → Build & Deploy → Branch** |
| **Change the password** | Service → **Environment** → edit `DEMO_ACCESS_PASSWORD` → **Save changes** (old password stops working after the restart) |
| **Reset the data now** | Service → **Shell** → `python -m app.cli demo-refresh --force` (paid plans), or simply wait for the daily reset |
| **Pause** | Service → **Settings → Suspend**. The web service stops serving and billing; the database keeps billing until deleted. |
| **Shut down completely** | Delete the **web service** and then the **database** (each: **Settings → Delete**). Charges stop; the synthetic data is discarded. Optionally remove Render's access in GitHub → Settings → Applications. |
