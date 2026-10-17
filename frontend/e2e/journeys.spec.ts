// Core journeys on phone and desktop: discover -> prepare -> act -> follow up, plus scope and data-state checks.
import { expect, test } from "@playwright/test";
import { GATE, loginAs, reseed, USERS } from "./helpers";

test.beforeEach(() => reseed());

test("discover, record an action with follow-up in under 30 seconds, and see it persisted", async ({ page }) => {
  await loginAs(page, USERS.ana);
  await page.goto("/");
  await expect(page.getByTestId("synthetic-banner")).toBeVisible();
  const cards = page.getByTestId("account-card");
  await expect(cards.first()).toBeVisible();
  expect(await cards.count()).toBeLessThanOrEqual(5);
  for (const chip of await page.getByTestId("priority").all()) await expect(chip).toContainText("Prioridad"); // never colour alone

  const card = cards.first();
  const name = (await card.locator("h3").textContent())!.trim();
  const started = Date.now();
  await card.getByRole("button", { name: "Registrar acción" }).click();
  const sheet = page.getByTestId("action-sheet");
  await sheet.getByRole("button", { name: "Contactado" }).click();
  await sheet.getByLabel("Nota (opcional)").fill("Pide volver a llamar el martes");
  await sheet.getByRole("button", { name: "En 1 semana" }).click();
  await sheet.getByRole("button", { name: "Guardar" }).click();
  await expect(page.getByTestId("toast")).toContainText("Acción registrada");
  expect(Date.now() - started).toBeLessThan(30_000);
  await expect(page.getByTestId("toast")).toContainText("registrar la acción no implica un resultado");
  await expect(cards.filter({ hasText: name })).toHaveCount(0);

  await page.goto("/follow-ups");
  await expect(page.getByTestId("follow-up-row").filter({ hasText: name })).toBeVisible();
  await page.getByTestId("follow-up-row").filter({ hasText: name }).getByRole("link").click();
  await expect(page.getByText("Pide volver a llamar el martes")).toBeVisible();
});

test("a due follow-up is completed by recording the next action", async ({ page }) => {
  await loginAs(page, USERS.ana);
  await page.goto("/");
  const rows = page.getByTestId("follow-up-row");
  await expect(rows.first()).toBeVisible();
  const before = await rows.count();
  await rows.first().getByRole("button", { name: "Registrar" }).click();
  const sheet = page.getByTestId("action-sheet");
  await sheet.getByRole("button", { name: "Reunión concertada" }).click();
  await sheet.getByRole("button", { name: "Sin seguimiento" }).click();
  await sheet.getByRole("button", { name: "Guardar" }).click();
  await expect(page.getByTestId("toast")).toBeVisible();
  await expect(rows).toHaveCount(before - 1);
});

test("snoozing removes the card from Today", async ({ page }) => {
  await loginAs(page, USERS.ana);
  await page.goto("/");
  const card = page.getByTestId("account-card").first();
  const name = (await card.locator("h3").textContent())!.trim();
  await card.getByRole("button", { name: "Registrar acción" }).click();
  await page.getByRole("button", { name: "Posponer o descartar" }).click();
  await page.getByRole("button", { name: "7 días", exact: true }).click();
  await page.getByRole("button", { name: /^Posponer · 7 días/ }).click();
  await expect(page.getByTestId("toast")).toContainText("Pospuesta hasta");
  await expect(page.getByTestId("account-card").filter({ hasText: name })).toHaveCount(0);
});

test("evidence shows provenance and synthetic figures are never labelled certified", async ({ page }) => {
  await loginAs(page, USERS.ana);
  await page.goto("/");
  await page.getByTestId("account-card").first().getByRole("link", { name: "Ver ficha" }).click();
  const opp = page.getByTestId("opportunity").first();
  await opp.locator("summary", { hasText: "Evidencia" }).click();
  await expect(opp.getByText("Sintética · no certificada").first()).toBeVisible();
  await expect(page.getByText("Certificada", { exact: true })).toHaveCount(0);
  await expect(page.getByText(/perdid/i)).toHaveCount(0);
});

test("a salesperson cannot reach the team view or another team's customers", async ({ page, request }) => {
  const gate: Record<string, string> = GATE ? { Authorization: "Basic " + Buffer.from(`${GATE.user}:${GATE.password}`).toString("base64") } : {};
  const other = await request.get("/api/customers", { headers: { "X-Demo-User": USERS.david, ...gate } });
  const item = (await other.json()).items[0];
  await loginAs(page, USERS.ana);
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Equipo" })).toHaveCount(0);
  await page.goto(`/customers/${item.source_entity}/${item.source_customer_id}`);
  await expect(page.getByText("No encontrado o fuera de su ámbito.")).toBeVisible();
});

test("a manager sees the team, observed results with the attribution caveat, and reassigns within scope", async ({ page }) => {
  await loginAs(page, USERS.elena);
  await page.goto("/team");
  await expect(page.getByText("no impacto incremental demostrado", { exact: false })).toBeVisible();
  await expect(page.locator("main").getByText("David Serra")).toHaveCount(0);
  const row = page.locator(".row").filter({ has: page.getByRole("button", { name: "Reasignar" }) }).first();
  await row.getByRole("button", { name: "Reasignar" }).click();
  const select = page.getByLabel("Reasignar a");
  const options = await select.locator("option").allTextContents();
  expect(options.join(" ")).not.toContain("David Serra");
  await select.selectOption({ index: 1 });
  await page.getByRole("button", { name: "Reasignar", exact: true }).first().click();
  await expect(page.getByTestId("toast")).toContainText("Cliente reasignado");
});

test("the interface is available in English", async ({ page }) => {
  await loginAs(page, USERS.ana, "en");
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Today", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Record action" }).first()).toBeVisible();
  await expect(page.getByText("Synthetic data, not certified.", { exact: false })).toBeVisible();
});

test("stale source data hides that entity's recommendations and says so", async ({ page }) => {
  reseed("--stale-entity", "PM");
  await loginAs(page, USERS.ana);
  await page.goto("/");
  await expect(page.getByTestId("stale-banner")).toContainText("PM");
  await expect(page.getByTestId("stale-banner")).toContainText("recomendaciones están ocultas");
  for (const card of await page.getByTestId("account-card").all()) await expect(card.locator(".ebadge")).toHaveText("JC");
});
