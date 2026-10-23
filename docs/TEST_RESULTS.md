# Test results

_Run on 17 Oct 2026 in the development container: Python 3.13, PostgreSQL 16, Node 22, Chromium (Playwright 1.56)._

| Suite | Command | Result |
|---|---|---|
| Backend lint | `ruff check app tests` | **passed** |
| Backend tests (PostgreSQL) | `pytest -q` | **128 passed** |
| Frontend typecheck | `tsc --noEmit` | **passed** |
| Frontend unit tests | `vitest run` | **7 passed** |
| End-to-end journeys, phone 390×844 + desktop 1366×900 | `playwright test e2e/journeys.spec.ts` | **16 passed** (8 journeys × 2 viewports) |
| Screenshot capture | `npm run screenshots` | 20 passed, 4 skipped by design (single-viewport shots) |
| Hosted-demo backend checks (login gate, sessions, fail-closed config, synthetic-only, daily refresh) | `pytest tests/test_demo_deploy.py` | **42 passed** (included in the 128 backend total) |
| Clean checkout (fresh clone of the branch) | `npm ci`, `npm run build`, `npm test`, fresh venv + `pip install -r requirements-dev.txt`, `ruff`, `pytest` | build OK; **7** and **128 passed** |
| Render-style container (image built from the clean checkout's `Dockerfile`; `PORT=10000`, `APP_ENV=demo`, credentials only in environment variables, `postgresql://` URL) | `curl` checks + `playwright test e2e/access.spec.ts e2e/journeys.spec.ts` with `E2E_LOGIN_USER` / `E2E_LOGIN_PASSWORD` | **22 passed** (3 login-gate checks + 8 journeys, × phone and desktop). Bound to `0.0.0.0:10000`; pages redirect to `/login`, API and assets return 401 without a session; deep-link refresh served by the SPA fallback; `Secure` cookie behind HTTPS; started without credentials → refused (exit 1) |
| Local mode without the login gate | `playwright test e2e/journeys.spec.ts e2e/access.spec.ts` | **16 passed**, 6 skipped (gate checks need credentials) |

## What is covered

### Opportunity rules and boundaries (`test_rules.py`, 32 tests, no database)
- **Declining purchases:**
  - exactly −25 % flags, −24.94 % does not, and −100 % flags;
  - prior value or absolute decline below materiality does not flag;
  - 18 months of history evaluates, 17 months is *insufficient_history*;
  - an extract too short for the comparison period is *not evaluable*;
  - a missing or non-additive measure is *suppressed*;
  - a customer transferred out is excluded.
- **Overdue cadence:** 33 vs 34 days at a 20-day typical interval; 4 vs 5 minimum orders; a flagged seasonal account is excluded while an unknown flag is evaluated; infrequent buyers are excluded.
- **Transfer without reorder:** grace boundary at 30 vs 31 days and maximum age at 365 vs 366; an existing reorder means not met; too few orders before transfer excludes; a missing counterpart suppresses.
- **Customer matching:** the same name with no mapping is never linked.
- **Gates:** stale source, intercompany, unapproved or ambiguous mapping, incomplete data and an unmapped transfer cohort never produce a flag.
- **Evidence:** keeps JC and PM entities separate; the transfer date's provenance is the approved mapping.
- **Priority:** the formula is exposed and monotonic in size.
- **Labels:** no "lost" or "perdido" in any evaluation output; the approval flag defaults to false.

### Import contract (`test_import.py`, 8 tests)
- The synthetic package validates and reports its planted problems.
- Exact duplicates are kept once. Conflicting duplicates are dropped and the customer's recommendations suppressed (no silent zero).
- A missing column rejects the whole package and keeps the previous snapshot.
- `live` data and future refresh timestamps are refused.
- Re-importing an identical package is a no-op.
- Same-entity mappings and approved mappings without an approver are rejected.
- Rows for unknown customers are rejected.

### Refresh job (`test_refresh.py`, 9 tests)
- Repeated refreshes create no duplicate opportunities.
- Every planted positive case is flagged and every planted negative case is not.
- Mapping failures become data issues, not recommendations.
- Same-name JC/PM customers are not linked.
- A stale source creates no new opportunities for that entity. Existing ones become *unconfirmed* rather than resolved.
- Dismissal cooldown is respected, and snooze expiry resurfaces the opportunity.
- An observed outcome is recorded and labelled.

### Access control and authentication (`test_api_access.py`, 18 tests)
- **Fail closed:**
  - no identity gives 401;
  - unset `AUTH_MODE` gives 401 `auth_not_configured`;
  - production with demo or unset auth reports startup problems and `create_app()` refuses to start.
- **Entra token checks (scaffold, locally signed keys):** valid accepted; wrong audience, tenant, issuer, signing key, scope, and expired tokens rejected.
- **Isolation:**
  - salespeople's customer sets do not overlap;
  - another salesperson's customer returns 404 for detail, action, snooze, dismiss and AI points;
  - managers see only their own team;
  - role gates for Team and Admin.
- **Today:** at most 5 cards, unique customers, all in scope, sorted by score.
- **Reassignment:** within scope only; another team's assignee is rejected; another team's customer gives 404; salespeople get 403; audit entry written; open follow-ups move to the new owner.

### Actions and follow-ups (`test_workflow.py`, 12 tests)
- An action with a note and follow-up is persisted, the opportunity becomes *in progress* (not resolved), it leaves Today and appears under Follow-ups, and the audit entry is written.
- Idempotent re-submit.
- The next action completes the due follow-up, and the customer is shown once (as a follow-up, not also as a card).
- Validation: note longer than 280, past or too-distant dates, unknown action type.
- *Not relevant* dismisses the opportunity.
- Snooze options and dismissal rules ("other" and "data incorrect" require a note). User data reports reach Admin.
- Follow-ups can be rescheduled and cancelled.
- The audit log rejects UPDATE and DELETE.
- Customer detail shows evidence, priority components and history, with no "lost" label.

### AI behaviour (`test_ai.py`, 7 tests)
- The guard accepts figures taken from the facts (Spanish number formats) and rejects:
  - invented or calculated figures;
  - discounts, stock and "lost";
  - uncited or unknown facts.
- A simulated prompt injection in a customer note produces a rejected draft. The user sees nothing from it and the rejected draft is stored for audit.
- The app works without an AI key (templates; `ai_enabled=false`).
- The system prompt marks notes as untrusted.

### Frontend (`vitest`, 7 tests)
- The English catalogue has exactly the Spanish keys and placeholders.
- No message labels a customer as lost.
- Synthetic figures are labelled "Sintética · no certificada"; app calculations are labelled provisional.

### End-to-end journeys (Playwright, each on phone and desktop)
1. Discover on Today, record *Contactado* with a note and a 1-week follow-up (**under 30 s**), toast states that an action is not an outcome, card leaves Today, follow-up listed, note visible in history.
2. A due follow-up is completed by recording the next action.
3. Snoozing removes the card from Today.
4. Evidence shows provenance; no "Certificada" label on synthetic data; no "perdido".
5. A salesperson cannot reach Team or another team's customer ("No encontrado o fuera de su ámbito").
6. The manager sees the team and the attribution caveat, cannot see the other team, and reassigns within scope.
7. The interface works in English.
8. A stale PM source shows the banner and leaves only JC cards.

## Known limitations of the testing

- **Entra:** not tested against a real tenant; frontend MSAL sign-in is not implemented.
- **AI:** the Anthropic adapter was not called live; the guard is tested with a fake provider.
- **Docker / hosting:** the image was built and run locally (base images adjusted only on the build machine to trust the sandbox's TLS proxy; the committed Dockerfile is unchanged). The Render deployment itself was not performed from here and `render.yaml` has not been validated by Render; `docker-compose.yml` was not run.
- **Data:** all tests use synthetic data. No reconciliation against approved reports is possible until certified extracts are supplied (GAPS F7).
- **Accessibility:** checked by design (text on every status, 44–56 px touch targets, focus rings, `aria` labels) but not by an automated audit tool.
