import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { invalidatePriceRelated, PRICE_RELATED_QUERY_KEYS } from "./prices";

describe("invalidatePriceRelated", () => {
  it("refreshes all consumers after both single-price and batch updates", () => {
    const queryClient = new QueryClient();
    const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries");

    invalidatePriceRelated(queryClient);

    expect(invalidateQueries.mock.calls.map(([filters]) => filters?.queryKey)).toEqual(
      PRICE_RELATED_QUERY_KEYS.map((key) => [key])
    );
  });
});
