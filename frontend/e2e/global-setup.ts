import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
const HERE = path.dirname(fileURLToPath(import.meta.url));

export default function globalSetup() {
  if (process.env.E2E_SKIP_SEED === "1") return;
  const backend = path.resolve(HERE, "../../backend");
  const python = process.env.E2E_PYTHON ?? path.join(backend, ".venv/bin/python");
  execFileSync(python, ["-m", "app.cli", "seed-demo"], { cwd: backend, stdio: "ignore" });
}
