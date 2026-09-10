import { describe, expect, it } from "vitest";

import { parseSettlementAmountDraft, settlementAmountDraft } from "./settlement-amount";

describe("settlement amount drafts", () => {
  it("renders zero as an empty editable field", () => {
    expect(settlementAmountDraft(0)).toBe("");
  });

  it("treats an empty field as zero when saving", () => {
    expect(parseSettlementAmountDraft("")).toBe(0);
    expect(parseSettlementAmountDraft("   ")).toBe(0);
  });

  it("converts non-negative whole baht to satang", () => {
    expect(parseSettlementAmountDraft("450")).toBe(45_000);
  });

  it.each(["-1", "1.5", "1e3", "abc"])("rejects invalid whole-baht input: %s", (value) => {
    expect(parseSettlementAmountDraft(value)).toBeNull();
  });

  it("rejects values that cannot be represented safely in satang", () => {
    expect(parseSettlementAmountDraft(String(Math.floor(Number.MAX_SAFE_INTEGER / 100) + 1))).toBeNull();
  });
});
