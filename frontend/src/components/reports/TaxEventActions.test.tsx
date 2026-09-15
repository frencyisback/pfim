import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { describeTaxEvent, type TaxEventIdentity } from "@/lib/taxEventPresentation";
import TaxEventActions from "./TaxEventActions";

function markup(event: TaxEventIdentity, pending = false) {
  return renderToStaticMarkup(<TaxEventActions event={event} pending={pending} onDelete={() => {}} onUnlink={() => {}} />);
}

describe("tax actions by explicit origin", () => {
  it.each(["manual", "legacy_unknown"] as const)("keeps %s manageable even when linked", (origin) => {
    for (const links of [
      { related_trade_id: 12, related_income_id: null },
      { related_trade_id: null, related_income_id: 24 },
    ]) {
      const event = { origin, ...links };
      expect(describeTaxEvent(event).label).toBe(origin === "manual" ? "Manual" : "Origin requires verification");
      expect(markup(event)).toContain("Delete");
      expect(markup(event)).toContain("Unlink source");
      expect(markup(event)).not.toContain("Managed in Securities");
    }
  });

  it.each([null, 12])("keeps automatic entries protected with link %s", (related_trade_id) => {
    const html = markup({ origin: "automatic_trade", related_trade_id, related_income_id: null });
    expect(html).toContain("Managed in Securities");
    expect(html).not.toContain("<button");
  });

  it.each(["manual", "legacy_unknown"] as const)("preserves origin %s after unlinking", (origin) => {
    const event = { origin, related_trade_id: null, related_income_id: null };
    expect(describeTaxEvent(event).label).toBe(origin === "manual" ? "Manual" : "Origin requires verification");
    expect(markup(event)).toContain("Delete");
    expect(markup(event)).not.toContain("Unlink source");
  });

  it("flags an unknown origin without inventing actions", () => {
    const event = { origin: "future_origin", related_trade_id: null, related_income_id: null } as unknown as TaxEventIdentity;
    expect(describeTaxEvent(event).label).toBe("Unrecognised origin");
    expect(markup(event)).not.toContain("<button");
  });

  it("disables both actions during a request", () => {
    const html = markup({ origin: "manual", related_trade_id: 12, related_income_id: null }, true);
    expect(html.match(/disabled=""/g)).toHaveLength(2);
  });
});
