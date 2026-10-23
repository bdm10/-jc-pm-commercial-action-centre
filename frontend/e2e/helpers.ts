import type { Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
const HERE = path.dirname(fileURLToPath(import.meta.url));

export const USERS = {
  ana: "ana.ruiz@example.com",
  jordi: "jordi.puig@example.com",
  elena: "elena.martin@example.com",
  david: "david.serra@example.com",
  admin: "admin@example.com",
};

/** Credentials of a login-protected deployment (never hard-coded; pass via environment). */
export const GATE = process.env.E2E_LOGIN_PASSWORD
  ? { user: process.env.E2E_LOGIN_USER ?? "", password: process.env.E2E_LOGIN_PASSWORD }
  : null;

export async function signIn(page: Page, next = "/") {
  if (!GATE) return;
  await page.goto(`/login?next=${encodeURIComponent(next)}`);
  await page.getByLabel(/Usuario/).fill(GATE.user);
  await page.getByLabel(/Contraseña/).fill(GATE.password);
  await page.getByRole("button", { name: /Entrar/ }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
}

export async function loginAs(page: Page, email: string, lang: "es" | "en" = "es") {
  await page.addInitScript(
    ([e, l]) => {
      localStorage.setItem("cac.demoUser", e);
      localStorage.setItem("cac.lang", l);
    },
    [email, lang],
  );
  await signIn(page);
}

export function reseed(...args: string[]) {
  const backend = path.resolve(HERE, "../../backend");
  execFileSync(process.env.E2E_PYTHON ?? path.join(backend, ".venv/bin/python"), ["-m", "app.cli", "seed-demo", ...args], { cwd: backend, stdio: "ignore" });
}
