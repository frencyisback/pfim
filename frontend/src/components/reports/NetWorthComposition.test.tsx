import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { NetWorthAccountComposition, NetWorthReport } from "@/api/reports";
import { formatEur } from "@/lib/formatters";
import { NetWorthComposition } from "./NetWorthComposition";

const report: NetWorthReport = {
  as_of_date: "2026-01-31",
  total_accounts_balance: "950",
  total_portfolio_value: "1650",
  net_worth: "2600",
  // The compatibility list still contains investments: the composition must use its dedicated data.
  by_account: [
    { account_id: 1, name: "Checking", balance: "1000" },
    { account_id: 2, name: "Overdraft", balance: "-50" },
    { account_id: 3, name: "Broker A", balance: "0" },
    { account_id: 4, name: "Broker B", balance: "0" },
    { account_id: 5, name: "Empty broker", balance: "0" },
  ],
  account_composition: {
    cash_accounts: [
      { account_id: 1, name: "Checking", balance: "1000" },
      { account_id: 2, name: "Overdraft", balance: "-50" },
    ],
    investment_accounts: [
      { account_id: 3, name: "Broker A", value: "1200.00", cost_fallback_securities: [] },
      { account_id: 4, name: "Broker B", value: "450.00", cost_fallback_securities: [] },
      { account_id: 5, name: "Empty broker", value: "0.00", cost_fallback_securities: [] },
    ],
    unallocated_account_balance: "0",
    unallocated_portfolio_value: "0",
    issues: [],
  },
  liquid_balance: "950",
  average_monthly_expenses: null,
  runway_months: null,
  portfolio_valuation: {
    price_policy: "latest_price_at_or_before_date_else_fifo_cost",
    cost_fallback_used: false,
    cost_fallback_securities: [],
  },
};

function text(markup: string) {
  return markup.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

const eur = (amount: number) => text(formatEur(amount));

function render(changes: Partial<NetWorthReport> = {}) {
  return renderToStaticMarkup(<NetWorthComposition netWorth={{ ...report, ...changes }} />);
}

function branches(markup: string) {
  const [cash, investments] = markup.split('aria-label="Account balances"')[1].split('aria-label="Portfolio value"');
  return { cash: text(cash), investments: text(investments.split("</ul>")[0]) };
}

describe("Net worth account composition", () => {
  it("places two cash accounts and three investment accounts in the correct branches with their values", () => {
    const markup = render();
    const { cash, investments } = branches(markup);
    expect(cash).toContain("Account balances 950,00 €");
    expect(cash).toContain(`Checking ${eur(1000)}`);
    expect(cash).toContain("Overdraft -50,00 €");
    expect(cash).not.toMatch(/Broker|Empty broker/);
    expect(investments).toContain(`Portfolio value ${eur(1650)}`);
    expect(investments).toContain(`Broker A ${eur(1200)}`);
    expect(investments).toContain("Broker B 450,00 €");
    expect(investments).toContain("Empty broker 0,00 €");
    expect(investments).not.toMatch(/Checking|Overdraft/);
    expect(text(markup)).toContain(`Net worth ${eur(2600)}`);
    expect(markup.match(/<li role="treeitem"/g)).toHaveLength(5);
    expect(markup).not.toContain("Unallocated");
    expect(markup).not.toContain('role="status"');
  });

  it("keeps distinct accounts with the same name and a zero cash balance", () => {
    const composition = structuredClone(report.account_composition);
    composition.cash_accounts[0].name = "Shared name";
    composition.cash_accounts[0].balance = "0";
    composition.investment_accounts[0].name = "Shared name";
    composition.investment_accounts[1].name = "Shared name";
    const { cash, investments } = branches(render({ account_composition: composition }));
    expect(cash).toContain("Shared name 0,00 €");
    expect(investments.match(/Shared name/g)).toHaveLength(2);
    expect(investments).toContain(`Shared name ${eur(1200)} Shared name 450,00 €`);
  });

  it("identifies the accounts using allocated FIFO estimates and keeps market-valued accounts unmarked", () => {
    const security = { security_id: 7, ticker: "NOQUOTE", name: "Missing quote" };
    const composition = structuredClone(report.account_composition);
    composition.investment_accounts[1].cost_fallback_securities = [security];
    const markup = render({
      account_composition: composition,
      portfolio_valuation: { ...report.portfolio_valuation, cost_fallback_used: true, cost_fallback_securities: [security] },
    });
    const { investments } = branches(markup);
    expect(investments).toContain(`Broker A ${eur(1200)} Broker B 450,00 € Includes an allocated FIFO cost estimate for NOQUOTE.`);
    expect(text(markup)).toContain("allocated between accounts in proportion to their holdings where attribution is possible");
    expect(text(markup)).toContain("This is a cost estimate");
  });

  it("shows unavailable account attribution as a dash and the excluded value as an explicit remainder", () => {
    const composition = structuredClone(report.account_composition);
    composition.investment_accounts[0].value = null;
    composition.unallocated_portfolio_value = "1200.00";
    composition.issues = [{ account_id: 3, name: "Broker A", security_id: 7, ticker: "LEGACY", reason: "negative_quantity" }];
    const markup = render({ account_composition: composition });
    const { investments } = branches(markup);
    expect(investments).toContain("Broker A — Valuation unavailable");
    expect(investments).toContain("Broker B 450,00 €");
    expect(investments).toContain(`Unallocated portfolio value ${eur(1200)}`);
    expect(investments).toContain(`Portfolio value ${eur(1650)}`);
    expect(text(markup)).toContain("Broker A — LEGACY: Recorded sales exceed purchases in this account.");
  });

  it.each([
    ["negative_quantity", "Recorded sales exceed purchases"],
    ["account_not_present", "Holdings fall outside the account’s opening or closing dates"],
    ["not_investment_account", "Holdings are linked to an account that is not an investment account"],
  ] as const)("keeps the %s warning visible even when the unallocated amount is zero", (reason, message) => {
    const composition: NetWorthAccountComposition = {
      ...report.account_composition,
      issues: [{ account_id: 9, name: "Legacy account", security_id: 7, ticker: "LEGACY", reason }],
    };
    const markup = render({ account_composition: composition });
    expect(markup).toContain('role="status"');
    expect(text(markup)).toContain(message);
    expect(markup).not.toContain("Unallocated portfolio value");
  });

  it("keeps legacy investment cash in a separate cash remainder instead of counting it as holdings", () => {
    const markup = render({
      total_accounts_balance: "975", net_worth: "2625",
      account_composition: { ...report.account_composition, unallocated_account_balance: "25" },
    });
    const { cash, investments } = branches(markup);
    expect(cash).toContain("Account balances 975,00 €");
    expect(cash).toContain("Unallocated account balance 25,00 €");
    expect(cash).not.toContain("Broker A");
    expect(investments).not.toContain("Unallocated account balance");
    expect(investments).toContain(`Portfolio value ${eur(1650)}`);
  });

  it("uses reconciled cents supplied by the backend without independently revaluing the holdings", () => {
    const composition = structuredClone(report.account_composition);
    composition.investment_accounts[0].value = "0.01";
    composition.investment_accounts[1].value = "0.00";
    const { investments } = branches(render({ total_portfolio_value: "0.014", account_composition: composition }));
    expect(investments).toContain("Portfolio value 0,01 €");
    expect(investments).toContain("Broker A 0,01 € Broker B 0,00 € Empty broker 0,00 €");
  });

  it("handles an empty snapshot with separate empty states for cash and investments", () => {
    const markup = render({
      total_accounts_balance: "0", total_portfolio_value: "0", net_worth: "0", by_account: [],
      account_composition: { cash_accounts: [], investment_accounts: [], unallocated_account_balance: "0", unallocated_portfolio_value: "0", issues: [] },
    });
    expect(text(markup)).toContain("No cash accounts present on the report date.");
    expect(text(markup)).toContain("No investment accounts present on the report date.");
    expect(markup).not.toContain('<li role="treeitem"');
    expect(markup).not.toContain('role="status"');
  });
});
