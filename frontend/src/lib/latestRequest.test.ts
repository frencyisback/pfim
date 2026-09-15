import { describe, expect, it } from "vitest";

import { createLatestRequestGate } from "./latestRequest";

describe("createLatestRequestGate", () => {
  it("ignores the previous file's preview when a new one starts", () => {
    const gate = createLatestRequestGate();
    const fileA = gate.begin();
    const fileB = gate.begin();

    expect(gate.isCurrent(fileA)).toBe(false);
    expect(gate.isCurrent(fileB)).toBe(true);
  });

  it("invalidates a request without immediately starting another", () => {
    const gate = createLatestRequestGate();
    const page = gate.begin();

    gate.invalidate();

    expect(gate.isCurrent(page)).toBe(false);
  });
});
