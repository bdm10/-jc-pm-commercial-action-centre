import { describe, expect, it } from "vitest";
import { en } from "./en";
import { es } from "./es";
import { interpolate, translate } from "./index";

const placeholders = (s: string) => (s.match(/\{\w+\}/g) ?? []).sort().join(",");

describe("i18n catalogues", () => {
  it("English has exactly the Spanish keys", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(es).sort());
  });

  it("translations keep the same placeholders", () => {
    for (const key of Object.keys(es) as (keyof typeof es)[]) {
      expect([key, placeholders(en[key])]).toEqual([key, placeholders(es[key])]);
    }
  });

  it("no message labels a customer as lost", () => {
    for (const msg of [...Object.values(es), ...Object.values(en)]) {
      expect(msg.toLowerCase()).not.toMatch(/perdid|lost customer|cliente perdido/);
    }
  });

  it("interpolates and falls back to the key", () => {
    expect(interpolate("Hola {name}", { name: "Ana" })).toBe("Hola Ana");
    expect(translate("en", "nav.today")).toBe("Today");
    expect(translate("es", "missing.key")).toBe("missing.key");
  });
});
