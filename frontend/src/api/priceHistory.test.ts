import { QueryClient, QueryObserver } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { invalidateAfterRestore } from "./backup";
import { invalidatePriceRelated, priceHistoryQueryOptions, type Price } from "./prices";

const price = (securityId: number, eur = "91.123456"): Price => ({
  id: securityId,
  security_id: securityId,
  date: "2026-01-02",
  price_close: "100.000000",
  price_close_eur: eur,
  fx_rate: "0.91123456",
  source: "csv_import",
  origin_trade_id: null,
});

const response = (rows: Price[]) => new Response(JSON.stringify(rows), {
  headers: { "Content-Type": "application/json" },
});

describe("security price-history queries", () => {
  let client: QueryClient;
  let stop: (() => void) | undefined;

  beforeEach(() => {
    client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  });

  afterEach(() => {
    stop?.();
    stop = undefined;
    client.clear();
    vi.unstubAllGlobals();
  });

  it("makes no request before a security is selected, including an explicit refetch", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const observer = new QueryObserver(client, priceHistoryQueryOptions(null));
    stop = observer.subscribe(() => undefined);
    expect(observer.getCurrentResult().fetchStatus).toBe("idle");
    await observer.refetch();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("uses a GET with a cancellation signal and preserves exact saved EUR values", async () => {
    const fetch = vi.fn().mockResolvedValue(response([price(7)]));
    vi.stubGlobal("fetch", fetch);
    const rows = await client.fetchQuery(priceHistoryQueryOptions(7));
    expect(rows).toEqual([price(7)]);
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, init] = fetch.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/prices\/7$/);
    expect(init.method ?? "GET").toBe("GET");
    expect(init.signal).toBeInstanceOf(AbortSignal);
    expect(init.body).toBeUndefined();
  });

  it("keeps empty history distinct from a failed request", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response([])));
    expect(await client.fetchQuery(priceHistoryQueryOptions(1))).toEqual([]);

    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error_code: "MAINTENANCE_MODE", message: "Database maintenance",
    }), { status: 503 }));
    vi.stubGlobal("fetch", fetch);
    await expect(client.fetchQuery(priceHistoryQueryOptions(2))).rejects.toThrow("Database maintenance");
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(client.getQueryState(["prices", 2, "history"])?.status).toBe("error");
    expect(client.getQueryData(["prices", 2, "history"])).toBeUndefined();
  });

  it("cancels the previous selection and rejects a late response under the new title", async () => {
    const pending: { resolve: (value: Response) => void; signal: AbortSignal }[] = [];
    const fetch = vi.fn((_url: string, init: RequestInit) => new Promise<Response>((resolve) => {
      // Deliberately allow resolution after abort: even a late transport response
      // must not replace the current security's result.
      pending.push({ resolve, signal: init.signal as AbortSignal });
    }));
    vi.stubGlobal("fetch", fetch);
    const observer = new QueryObserver(client, priceHistoryQueryOptions(1));
    stop = observer.subscribe(() => undefined);
    await vi.waitFor(() => expect(pending).toHaveLength(1));

    observer.setOptions(priceHistoryQueryOptions(2));
    await vi.waitFor(() => expect(pending).toHaveLength(2));
    expect(pending[0].signal.aborted).toBe(true);
    expect(observer.getCurrentResult().data).toBeUndefined();

    pending[1].resolve(response([price(2, "15.000001")]));
    await vi.waitFor(() => expect(observer.getCurrentResult().data).toEqual([price(2, "15.000001")]));
    pending[0].resolve(response([price(1)]));
    await vi.waitFor(() => expect(client.getQueryState(["prices", 1, "history"])?.fetchStatus).toBe("idle"));
    expect(observer.getCurrentResult().data).toEqual([price(2, "15.000001")]);
    expect(client.getQueryData(["prices", 1, "history"])).toBeUndefined();
  });

  it("clears displayed history when the selection disappears", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response([price(1)])));
    const observer = new QueryObserver(client, priceHistoryQueryOptions(1));
    stop = observer.subscribe(() => undefined);
    await vi.waitFor(() => expect(observer.getCurrentResult().data).toEqual([price(1)]));
    observer.setOptions(priceHistoryQueryOptions(null));
    expect(observer.getCurrentResult().data).toBeUndefined();
    expect(observer.getCurrentResult().fetchStatus).toBe("idle");
  });

  it.each(["price change", "restore"])("refreshes active history after %s", async (cause) => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(response([price(1)]))
      .mockResolvedValueOnce(response([price(1, "88.000001")]));
    vi.stubGlobal("fetch", fetch);
    const observer = new QueryObserver(client, priceHistoryQueryOptions(1));
    stop = observer.subscribe(() => undefined);
    await vi.waitFor(() => expect(observer.getCurrentResult().data).toEqual([price(1)]));
    if (cause === "restore") await invalidateAfterRestore(client);
    else invalidatePriceRelated(client);
    await vi.waitFor(() => expect(observer.getCurrentResult().data).toEqual([price(1, "88.000001")]));
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});
