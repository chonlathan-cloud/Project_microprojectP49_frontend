import { describe, expect, it } from "vitest";

import { INITIAL_SERVICE_CATALOG } from "./catalog";

describe("initial service catalog", () => {
  it("contains exactly 11 services and 17 variants", () => {
    expect(INITIAL_SERVICE_CATALOG).toHaveLength(11);
    expect(INITIAL_SERVICE_CATALOG.flatMap((service) => service.variants)).toHaveLength(17);
  });

  it("charges the couple package once for exactly two participants", () => {
    const service = INITIAL_SERVICE_CATALOG.find((item) => item.id === "couple-relaxation");
    expect(service?.variants).toEqual([
      expect.objectContaining({
        id: "couple-relaxation-90",
        priceSatang: 119000,
        pricingMode: "PER_BOOKING",
        requiredPax: 2
      })
    ]);
  });
});
