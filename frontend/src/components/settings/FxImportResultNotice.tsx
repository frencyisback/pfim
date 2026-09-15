import type { FxRateImportResult } from "@/api/fxRates";

export function FxImportResultNotice({ result }: { result: FxRateImportResult }) {
  return (
    <div className="mb-2 text-sm">
      <p className={result.errors ? "text-amber-700" : "text-green-700"}>
        {result.imported} rates imported, {result.reciprocal_calculated} reciprocal rates calculated,
        {" "}{result.errors} errors.
      </p>
      {result.row_errors.length > 0 && (
        <ul className="mt-2 max-h-48 list-disc overflow-auto pl-5 text-red-600">
          {result.row_errors.map((error, index) => (
            <li key={`${error.row_number}-${error.column}-${index}`}>
              Row {error.row_number}{error.column ? `, column ${error.column}` : ""}: {error.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
