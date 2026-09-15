import { describe, expect, it } from "vitest";

import { clampPageToTotal } from "./pagination";

describe("clampPageToTotal", () => {
  it("returns to the preceding page when the last row is deleted", () => {
    expect(clampPageToTotal(2, 20, 20)).toBe(1);
  });

  it("handles transfers that delete two rows", () => {
    expect(clampPageToTotal(2, 19, 20)).toBe(1);
  });

  it("does not change a page that remains valid", () => {
    expect(clampPageToTotal(2, 21, 20)).toBe(2);
  });

  it("always retains at least the first page", () => {
    expect(clampPageToTotal(3, 0, 20)).toBe(1);
  });
});
