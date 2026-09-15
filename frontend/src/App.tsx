import { lazy, Suspense } from "react";
import { NavLink, Route, Routes } from "react-router-dom";

// Pages contain large charts and tables; route-based loading avoids
// transferring the full bundle when users only open the dashboard.
const Dashboard = lazy(() => import("./pages/Dashboard"));
const CashFlow = lazy(() => import("./pages/CashFlow"));
const Portfolio = lazy(() => import("./pages/Portfolio"));
const Securities = lazy(() => import("./pages/Securities"));
const IncomeEvents = lazy(() => import("./pages/IncomeEvents"));
const Reports = lazy(() => import("./pages/Reports"));
const Forecasts = lazy(() => import("./pages/Forecasts"));
const Settings = lazy(() => import("./pages/Settings"));

// Layout: fixed sidebar and main content area (specification §7.1).
const NAV_ITEMS = [
  { to: "/", label: "🏠 Dashboard" },
  { to: "/cashflow", label: "💸 Cashflow" },
  { to: "/portfolio", label: "📈 Portfolio" },
  { to: "/securities", label: "🎯 Securities" },
  { to: "/income-events", label: "🎁 Income" },
  { to: "/reports", label: "📊 Reports" },
  { to: "/forecasts", label: "🔮 Forecasts" },
  { to: "/settings", label: "⚙️ Settings" },
];

export default function App() {
  return (
    <div className="flex h-screen w-screen bg-gray-50 text-gray-900">
      <aside className="w-56 shrink-0 border-r border-gray-200 bg-white p-4">
        <h1 className="mb-6 text-lg font-semibold">PFIM</h1>
        <nav className="flex flex-col gap-1">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `rounded px-3 py-2 text-sm ${
                  isActive ? "bg-gray-900 text-white" : "hover:bg-gray-100"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="flex-1 overflow-auto p-6">
        <Suspense fallback={<p className="text-sm text-gray-500">Loading page...</p>}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/cashflow" element={<CashFlow />} />
            <Route path="/portfolio" element={<Portfolio />} />
            <Route path="/securities" element={<Securities />} />
            <Route path="/income-events" element={<IncomeEvents />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/forecasts" element={<Forecasts />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </Suspense>
      </main>
    </div>
  );
}
