import { describe, expect, it } from "vitest";

import { nextTableSort, sortTableRows } from "./tableSort";

describe("nextTableSort", () => {
  it("always toggles ascending and descending on the same column", () => {
    const descending = nextTableSort({ key: "date", direction: "asc" }, "date");
    expect(descending).toEqual({ key: "date", direction: "desc" });
    expect(nextTableSort(descending, "date")).toEqual({ key: "date", direction: "asc" });
  });

  it("starts in the requested direction when the column changes", () => {
    expect(nextTableSort({ key: "date", direction: "desc" }, "amount", "desc")).toEqual({
      key: "amount",
      direction: "desc",
    });
  });
});

describe("sortTableRows", () => {
  const rows = [
    { id: 1, name: "Security 10", amount: 5 },
    { id: 2, name: "security 2", amount: null },
    { id: 3, name: "Security 1", amount: 10 },
  ];

  it("sorts text naturally without mutating the source", () => {
    const sorted = sortTableRows(rows, { key: "name", direction: "asc" }, (row, key) => row[key]);
    expect(sorted.map((row) => row.id)).toEqual([3, 2, 1]);
    expect(rows.map((row) => row.id)).toEqual([1, 2, 3]);
  });

  it("keeps missing values last in both directions", () => {
    const asc = sortTableRows(rows, { key: "amount", direction: "asc" }, (row) => row.amount);
    const desc = sortTableRows(rows, { key: "amount", direction: "desc" }, (row) => row.amount);
    expect(asc.map((row) => row.id)).toEqual([1, 3, 2]);
    expect(desc.map((row) => row.id)).toEqual([3, 1, 2]);
  });
});
