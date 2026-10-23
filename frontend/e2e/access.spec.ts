// Login gate of a hosted demo. Runs only when E2E_LOGIN_PASSWORD is set (login-protected deployment).
import { expect, test } from "@playwright/test";
import { GATE, signIn, USERS } from "./helpers";

test.skip(!GATE, "set E2E_LOGIN_USER and E2E_LOGIN_PASSWORD to check a login-protected deployment");

test("a visitor who is not signed in sees only the login page, in the browser or via the API", async ({ page, baseURL }) => {
  await page.goto("/customers");
  await expect(page).toHaveURL(/\/login\?next=%2Fcustomers/);
  await expect(page.getByLabel(/Contraseña/)).toBeVisible();
  await expect(page.getByText("Ana Ruiz")).toHaveCount(0);

  for (const path of ["/api/meta", "/api/today", "/api/demo/users", "/api/admin/config"]) {
    const r = await fetch(new URL(path, baseURL), { headers: { "X-Demo-User": "admin@example.com" } });
    expect(r.status, path).toBe(401);
    expect(await r.json()).toEqual({ error: { code: "login_required" } });
  }
  const post = await fetch(new URL("/api/actions", baseURL), { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  expect(post.status).toBe(401);
  expect((await fetch(new URL("/healthz", baseURL))).status).toBe(200);
});

test("a wrong password is rejected", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel(/Usuario/).fill(GATE!.user);
  await page.getByLabel(/Contraseña/).fill("not-the-password");
  await page.getByRole("button", { name: /Entrar/ }).click();
  await expect(page.getByRole("alert")).toContainText("incorrectos");
  expect((await page.request.get("/api/meta")).status()).toBe(401);
});

test("signing in returns to the requested page; refreshing a deep link works; signing out ends the session", async ({ page }) => {
  await page.addInitScript((e) => localStorage.setItem("cac.demoUser", e), USERS.ana);
  await signIn(page, "/follow-ups");
  await expect(page).toHaveURL(/\/follow-ups$/);
  await expect(page.getByRole("heading", { name: "Seguimientos" })).toBeVisible();

  await page.goto("/customers");
  await page.getByTestId("customer-row").first().getByRole("link").click();
  await expect(page.getByText("Resumen comercial")).toBeVisible();
  const deepLink = page.url();
  await page.reload(); // SPA fallback: a browser refresh on a client-side route still loads the app
  await expect(page).toHaveURL(deepLink);
  await expect(page.getByText("Resumen comercial")).toBeVisible();

  await page.getByTestId("logout").click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
});
