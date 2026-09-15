import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import SortableHeader from "./SortableHeader";

describe("SortableHeader", () => {
  it("exposes aria-sort on the active column", () => {
    const html = renderToStaticMarkup(
      <table>
        <thead>
          <tr>
            <SortableHeader active direction="desc" onSort={vi.fn()}>
              Date
            </SortableHeader>
          </tr>
        </thead>
      </table>
    );

    expect(html).toContain('aria-sort="descending"');
    expect(html).toContain("▼");
  });

  it("declares none on inactive columns", () => {
    const html = renderToStaticMarkup(
      <table>
        <thead>
          <tr>
            <SortableHeader active={false} direction="asc" onSort={vi.fn()}>
              Account
            </SortableHeader>
          </tr>
        </thead>
      </table>
    );

    expect(html).toContain('aria-sort="none"');
    expect(html).not.toContain("▲");
  });
});
