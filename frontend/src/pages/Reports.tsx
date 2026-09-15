import { useState } from "react";
import { useIncomeAnalysis, useSpendingAnalysis, useTransferAnalysis } from "@/api/reports";
import { BackupTab } from "@/components/reports/BackupTab";
import { CategoryAnalysisTab } from "@/components/reports/CategoryAnalysisTab";
import { CostsAnalysisTab } from "@/components/reports/CostsAnalysisTab";
import { DividendsAnalysisTab } from "@/components/reports/DividendsAnalysisTab";
import { IncomeStatementTab } from "@/components/reports/IncomeStatementTab";
import { NetWorthTab } from "@/components/reports/NetWorthTab";
import { SecuritiesAnalysisTab } from "@/components/reports/SecuritiesAnalysisTab";

/** Reports page: net worth, income statement, spending analysis, tax
 * register and backup/restore. Specification §7.5, §7.7 and §11.4. */
const TABS = [
  "Net worth",
  "Income Statement",
  "Securities Analysis",
  "Income Analysis",
  "Spending Analysis",
  "Inflow Analysis",
  "Transfer Analysis",
  "Costs and Taxation",
  "Backup",
] as const;

type Tab = (typeof TABS)[number];

export default function Reports() {
  const [tab, setTab] = useState<Tab>("Net worth");

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold">Reports</h2>

      <div className="flex gap-1 border-b border-gray-200">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-2 text-sm ${
              tab === t
                ? "border-b-2 border-gray-900 font-medium text-gray-900"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "Net worth" && <NetWorthTab />}
      {tab === "Income Statement" && <IncomeStatementTab />}
      {tab === "Securities Analysis" && <SecuritiesAnalysisTab />}
      {tab === "Income Analysis" && <DividendsAnalysisTab />}
      {tab === "Spending Analysis" && (
        <CategoryAnalysisTab
          useReport={useSpendingAnalysis}
          endpoint="spending-analysis"
          accent="text-red-600"
          barColor="#ef4444"
          emptyLabel="No expenses recorded."
          showTopLevel
        />
      )}
      {tab === "Inflow Analysis" && (
        <CategoryAnalysisTab
          useReport={useIncomeAnalysis}
          endpoint="income-analysis"
          accent="text-green-600"
          barColor="#22c55e"
          emptyLabel="No inflows recorded."
        />
      )}
      {tab === "Transfer Analysis" && (
        <CategoryAnalysisTab
          useReport={useTransferAnalysis}
          endpoint="transfer-analysis"
          accent="text-blue-600"
          barColor="#0ea5e9"
          emptyLabel="No transfers recorded."
        />
      )}
      {tab === "Costs and Taxation" && <CostsAnalysisTab />}
      {tab === "Backup" && <BackupTab />}
    </div>
  );
}
