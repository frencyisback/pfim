import { useEffect, useMemo, useState } from "react";
import { usePriceHistory } from "@/api/prices";
import { useSecurities } from "@/api/securities";
import type { Security } from "@/api/types";
import QueryStateNotice from "@/components/common/QueryStateNotice";
import SecurityDetailsTable from "@/components/securities/SecurityDetailsTable";
import SecurityPriceHistoryChart from "@/components/securities/SecurityPriceHistoryChart";
import { buildSecurityPriceHistory } from "@/lib/securityPriceHistory";
import { useTodayIso } from "@/lib/useTodayIso";

/** Subscribe to price history and the daily cutoff only while a record is open. */
export function SelectedSecurityDetail({ security }: { security: Security }) {
  const today = useTodayIso();
  const pricesQuery = usePriceHistory(security.id);
  const historyBusy = pricesQuery.isLoading || pricesQuery.isFetching;
  const history = useMemo(
    () => buildSecurityPriceHistory(pricesQuery.data ?? [], security.id, today),
    [pricesQuery.data, security.id, today]
  );

  return (
    <>
      <SecurityDetailsTable security={security} />
      <QueryStateNotice isLoading={historyBusy} error={pricesQuery.error} errorPrefix="Price history error" />
      {!historyBusy && !pricesQuery.error && pricesQuery.data !== undefined && (
        <SecurityPriceHistoryChart points={history.points} invalidCount={history.invalidCount} today={today} />
      )}
    </>
  );
}

export default function SecurityDetail() {
  const securitiesQuery = useSecurities();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const securities = securitiesQuery.data ?? [];
  const registryBusy = securitiesQuery.isLoading || securitiesQuery.isFetching;
  const registryReady = !registryBusy && !securitiesQuery.error && securitiesQuery.data !== undefined;
  const selectedSecurity = registryReady
    ? securities.find((security) => security.id === selectedId)
    : undefined;

  useEffect(() => {
    // A deletion or restored backup can remove the selected record. Deriving the selection
    // above hides its details immediately, even before this state update runs.
    if (registryReady && selectedId !== null && !selectedSecurity) setSelectedId(null);
  }, [registryReady, selectedId, selectedSecurity]);

  return (
    <div className="min-w-0 space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Security detail</h2>
        <p className="mt-1 text-sm text-gray-500">Select a security to view its record and saved price history in euros.</p>
      </div>
      <QueryStateNotice isLoading={registryBusy} error={securitiesQuery.error} />
      {registryReady && securities.length === 0 && (
        <p role="status" className="rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-500">
          No securities registered. Add a security in Securities to view its details here.
        </p>
      )}
      {securities.length > 0 && (
        <label className="flex max-w-xl flex-col gap-1 text-sm font-medium text-gray-600">
          Security
          <select
            className="rounded border border-gray-300 bg-white px-3 py-2 font-normal disabled:opacity-50"
            value={selectedId ?? ""}
            onChange={(event) => setSelectedId(event.target.value ? Number(event.target.value) : null)}
            disabled={!registryReady}
          >
            <option value="">Select a security...</option>
            {securities.map((security) => (
              <option key={security.id} value={security.id}>
                {security.ticker} — {security.name}{security.is_active ? "" : " (inactive)"}
              </option>
            ))}
          </select>
        </label>
      )}
      {registryReady && securities.length > 0 && !selectedSecurity && (
        <p role="status" className="text-sm text-gray-500">Choose a security to see its details and recorded prices.</p>
      )}
      {selectedSecurity && <SelectedSecurityDetail security={selectedSecurity} />}
    </div>
  );
}
