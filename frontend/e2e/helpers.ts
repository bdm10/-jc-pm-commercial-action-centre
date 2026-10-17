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

export async function loginAs(page: Page, email: string, lang: "es" | "en" = "es") {
  await page.addInitScript(
    ([e, l]) => {
      localStorage.setItem("cac.demoUser", e);
      localStorage.setItem("cac.lang", l);
    },
    [email, lang],
  );
}

export function reseed(...args: string[]) {
  const backend = path.resolve(HERE, "../../backend");
  execFileSync(process.env.E2E_PYTHON ?? path.join(backend, ".venv/bin/python"), ["-m", "app.cli", "seed-demo", ...args], { cwd: backend, stdio: "ignore" });
}
