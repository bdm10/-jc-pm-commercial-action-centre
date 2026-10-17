// Hosted demo access protection. Runs only when E2E_HTTP_PASSWORD is set (password-protected deployment).
import { expect, test } from "@playwright/test";

const password = process.env.E2E_HTTP_PASSWORD;
const user = process.env.E2E_HTTP_USER ?? "demo";
test.skip(!password, "set E2E_HTTP_PASSWORD to check a password-protected deployment");

test("a visitor without the password sees nothing, in the browser or via the API", async ({ browser, baseURL }) => {
  const ctx = await browser.newContext({ httpCredentials: undefined });
  const page = await ctx.newPage();
  const res = await page.goto("/");
  expect(res?.status()).toBe(401);
  await expect(page.getByText("Centro de Acción Comercial")).toHaveCount(0);
  await ctx.close();

  // Plain fetch: Playwright's own request contexts inherit the configured credentials.
  for (const path of ["/", "/customers", "/api/meta", "/api/today", "/api/demo/users", "/api/admin/config"]) {
    const r = await fetch(new URL(path, baseURL), { headers: { "X-Demo-User": "admin@example.com" } });
    expect(r.status, path).toBe(401);
    expect(r.headers.get("www-authenticate")).toContain("Basic");
    expect(await r.text()).not.toContain("Ana Ruiz");
  }
  const post = await fetch(new URL("/api/actions", baseURL), { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  expect(post.status).toBe(401);
  expect((await fetch(new URL("/healthz", baseURL))).status).toBe(200);
});

test("a wrong password is rejected", async ({ baseURL }) => {
  const auth = "Basic " + Buffer.from(`${user}:not-the-password`).toString("base64");
  expect((await fetch(new URL("/api/meta", baseURL), { headers: { Authorization: auth } })).status).toBe(401);
});

test("with the password the app loads and the API answers", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Elija un usuario de demostración")).toBeVisible();
});
