import { describe, expect, it } from "vitest";

import { downloadFilename } from "./admin-api";

describe("downloadFilename", () => {
  it("prefers an RFC 5987 Thai filename", () => {
    expect(downloadFilename(
      "attachment; filename=spa49-sales.csv; filename*=UTF-8''%E0%B8%A3%E0%B8%B2%E0%B8%A2%E0%B8%81%E0%B8%B2%E0%B8%A3%E0%B8%82%E0%B8%B2%E0%B8%A2.csv",
    )).toBe("รายการขาย.csv");
  });

  it("falls back to the ASCII filename", () => {
    expect(downloadFilename('attachment; filename="spa49-export.csv"')).toBe("spa49-export.csv");
  });
});
