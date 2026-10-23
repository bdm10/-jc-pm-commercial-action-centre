// Captures the documentation screenshots (docs/screenshots). Run with: npm run screenshots
import { expect, test } from "@playwright/test";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { loginAs, USERS } from "./helpers";
import { fileURLToPath } from "node:url";
const HERE = path.dirname(fileURLToPath(import.meta.url));

test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to capture documentation screenshots");

const OUT = path.resolve(HERE, "../../docs/screenshots");
const shot = (name: string, project: string) => path.join(OUT, `${name}-${project}.png`);

// Phone screenshots are framed like the real screen (fixed bottom navigation); long pages get extra scrolled frames.
async function capture(page: import("@playwright/test").Page, name: string, project: string, scrolls: string[] = []) {
  await page.evaluate(() => window.scrollTo(0, 0));
  if (project !== "phone") {
    await page.screenshot({ path: shot(name, project), fullPage: true });
    return;
  }
  await page.screenshot({ path: shot(name, project) });
  for (const [i, text] of scrolls.entries()) {
    await page.getByText(text, { exact: true }).first().scrollIntoViewIfNeeded();
    await page.evaluate(() => window.scrollBy(0, -80));
    await page.screenshot({ path: shot(`${name}-${String.fromCharCode(98 + i)}`, project) });
  }
}
const backend = path.resolve(HERE, "../../backend");
const seed = (...args: string[]) =>
  execFileSync(process.env.E2E_PYTHON ?? path.join(backend, ".venv/bin/python"), ["-m", "app.cli", "seed-demo", ...args], { cwd: backend, stdio: "ignore" });

test.beforeAll(() => seed());

test("01 today", async ({ page }, info) => {
  await loginAs(page, USERS.ana);
  await page.goto("/");
  await expect(page.getByTestId("account-card").first()).toBeVisible();
  await capture(page, "01-today", info.project.name, ["Seguimientos para hoy"]);
});

test("02 record action", async ({ page }, info) => {
  await loginAs(page, USERS.ana);
  await page.goto("/");
  await page.getByTestId("account-card").first().getByRole("button", { name: "Registrar acción" }).click();
  const sheet = page.getByTestId("action-sheet");
  await sheet.getByRole("button", { name: "Contactado" }).click();
  await sheet.getByLabel("Nota (opcional)").fill("Habla con el encargado el lunes; revisar carta de otoño.");
  await sheet.getByRole("button", { name: "En 1 semana" }).click();
  await page.screenshot({ path: shot("02-record-action", info.project.name), fullPage: false });
});

test("03 customer detail", async ({ page }, info) => {
  await loginAs(page, USERS.ana);
  await page.goto("/");
  await page.getByTestId("account-card").nth(1).getByRole("link", { name: "Ver ficha" }).click();
  await expect(page.getByTestId("opportunity").first()).toBeVisible();
  await page.getByTestId("opportunity").first().locator("summary", { hasText: "Evidencia" }).click();
  await capture(page, "03-customer-detail", info.project.name, ["Evidencia", "Puntos para la conversación", "Resumen comercial"]);
});

test("04 transferred customer", async ({ page }, info) => {
  await loginAs(page, USERS.ana);
  await page.goto("/customers?with_opportunity=1");
  const rows = page.getByTestId("customer-row").filter({ hasText: "Transferido sin pedido" });
  await rows.first().getByRole("link").click();
  await expect(page.getByText("Cuentas vinculadas")).toBeVisible();
  await capture(page, "04-transferred-customer", info.project.name, ["Cuentas vinculadas"]);
});

test("05 follow-ups", async ({ page }, info) => {
  await loginAs(page, USERS.ana);
  await page.goto("/follow-ups");
  await expect(page.getByTestId("follow-up-row").first()).toBeVisible();
  await capture(page, "05-follow-ups", info.project.name);
});

test("06 customers", async ({ page }, info) => {
  await loginAs(page, USERS.ana);
  await page.goto("/customers");
  await expect(page.getByTestId("customer-row").first()).toBeVisible();
  await page.screenshot({ path: shot("06-customers", info.project.name), fullPage: false });
});

test("07 team (manager)", async ({ page }, info) => {
  await loginAs(page, USERS.elena);
  await page.goto("/team");
  await expect(page.getByText("Resultados observados tras la acción")).toBeVisible();
  await capture(page, "07-team-manager", info.project.name, ["Resultados observados tras la acción"]);
});

test("08 admin data issues", async ({ page }, info) => {
  test.skip(info.project.name === "phone", "desktop only");
  await loginAs(page, USERS.admin);
  await page.goto("/admin");
  await expect(page.getByText("Reglas (provisionales)")).toBeVisible();
  await capture(page, "08-admin", info.project.name);
});

test("09 english", async ({ page }, info) => {
  test.skip(info.project.name === "desktop", "phone only");
  await loginAs(page, USERS.ana, "en");
  await page.goto("/");
  await expect(page.getByTestId("account-card").first()).toBeVisible();
  await page.screenshot({ path: shot("09-today-english", info.project.name), fullPage: false });
});

test("10 empty search state", async ({ page }, info) => {
  test.skip(info.project.name === "desktop", "phone only");
  await loginAs(page, USERS.ana);
  await page.goto("/customers?q=zzz");
  await page.getByPlaceholder("Buscar por nombre o código").fill("zzzz");
  await expect(page.getByText("No hay clientes que coincidan.")).toBeVisible();
  await page.screenshot({ path: shot("10-empty-state", info.project.name), fullPage: false });
});

test("11 demo user picker", async ({ page }, info) => {
  test.skip(info.project.name === "desktop", "phone only");
  await page.goto("/");
  await expect(page.getByText("Elija un usuario de demostración")).toBeVisible();
  await page.screenshot({ path: shot("11-demo-picker", info.project.name), fullPage: false });
});

test("12 stale data", async ({ page }, info) => {
  seed("--stale-entity", "PM");
  try {
    await loginAs(page, USERS.ana);
    await page.goto("/");
    await expect(page.getByTestId("stale-banner")).toBeVisible();
    await capture(page, "12-stale-data", info.project.name);
  } finally {
    seed();
  }
});
