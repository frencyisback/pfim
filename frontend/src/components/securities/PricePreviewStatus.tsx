import type { PriceImportPreviewRow } from "@/api/prices";

export function PricePreviewStatus({ row }: { row: PriceImportPreviewRow }) {
  if (row.errors.length) return <>{row.errors.join("; ")}</>;
  if (row.security_id === null) return <>Unrecognised ticker</>;
  return (
    <>
      {row.is_update ? "Update" : "New"}
      {row.final_row_number != null && (
        <div className="mt-1 text-gray-600">
          {row.superseded_by_row != null
            ? `Replaced by row ${row.superseded_by_row}. `
            : "Last valid row. "}
          Final value: {row.final_close} {row.currency}
          {row.currency !== "EUR" && (
            <> (exchange rate {row.final_fx_rate}; {row.final_close_eur} EUR)</>
          )}.
        </div>
      )}
    </>
  );
}
