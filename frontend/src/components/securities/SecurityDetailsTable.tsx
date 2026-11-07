import type { Security } from "@/api/types";
import { securityTypeLabel } from "@/lib/securityTypes";

/** Match the fields exposed by SecuritiesRegistrySection, without exposing hidden metadata. */
export default function SecurityDetailsTable({ security }: { security: Security }) {
  const fields: [string, string | null][] = [
    ["Ticker", security.ticker],
    ["Name", security.name],
    ["ISIN", security.isin],
    ["Type", securityTypeLabel(security.type)],
    ["Currency", security.currency],
    ["Sector", security.sector],
    ["Industry", security.industry],
    ["Country", security.country],
    ["Status", security.is_active ? "Active" : "Inactive"],
  ];

  return (
    <section aria-labelledby="security-record-title">
      <h3 id="security-record-title" className="mb-3 font-medium">Security record</h3>
      <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
        <table className="w-full table-fixed text-sm" aria-labelledby="security-record-title">
          <tbody>
            {fields.map(([label, value]) => (
              <tr key={label} className="border-t border-gray-100 first:border-t-0">
                <th scope="row" className="w-32 bg-gray-50 px-4 py-2 text-left font-medium text-gray-500 sm:w-44">
                  {label}
                </th>
                <td className="break-words px-4 py-2">{value?.trim() ? value : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
