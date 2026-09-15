import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import QueryStateNotice from "./QueryStateNotice";

describe("QueryStateNotice", () => {
  it("makes a query error visible and accessible", () => {
    const html = renderToStaticMarkup(
      <QueryStateNotice error={new Error("backend unreachable")} />
    );

    expect(html).toContain('role="alert"');
    expect(html).toContain("Loading error: backend unreachable");
    expect(html).not.toContain("Loading...");
  });

  it("shows loading only when no error exists", () => {
    const html = renderToStaticMarkup(<QueryStateNotice isLoading />);

    expect(html).toContain('role="status"');
    expect(html).toContain("Loading...");
  });

  it("normalises errors that are not Error objects", () => {
    const html = renderToStaticMarkup(<QueryStateNotice error="raw error" />);

    expect(html).toContain("Unknown error");
  });
});
