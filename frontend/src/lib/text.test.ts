import { describe, expect, it } from "vitest";
import { translate } from "../i18n";
import { evidenceValue, provenanceLabel, reasonText } from "./text";
import type { EvidenceItem } from "../api/types";

const tES = (k: string, p?: Record<string, string | number | null | undefined>) => translate("es", k, p);

describe("plain-language text", () => {
  it("explains a declining-purchases signal with the comparison period", () => {
    const s = reasonText(tES, "es-ES", {
      opp_type: "declining_purchases",
      reason_params: { entity: "JC", change_pct: -51.8, current_start: "2026-04-01", current_end: "2026-09-30" },
    });
    expect(s).toContain("JC");
    expect(s).toMatch(/51,8\s?%/);
    expect(s).toContain("2026");
  });

  it("never labels synthetic figures as certified", () => {
    const e: EvidenceItem = {
      id: "e1", label_key: "ev.current_window_value", kind: "money", value: 6945.5, unit: "EUR", entity: "JC",
      provenance: { type: "synthetic_measure", certification_status: "synthetic" },
    };
    expect(provenanceLabel(e, tES)).toBe("Sintética · no certificada");
    expect(evidenceValue(e, tES, "es-ES")).toMatch(/6\.?946\s?€/);
  });

  it("labels app calculations as provisional", () => {
    const e: EvidenceItem = { id: "e3", label_key: "ev.change_pct", kind: "pct", value: -51.8, entity: "JC",
      provenance: { type: "app_calculation", certification_status: "provisional" } };
    expect(provenanceLabel(e, tES)).toContain("provisional");
  });
});
