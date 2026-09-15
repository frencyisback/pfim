import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";

export interface PortfolioValuationMetadata {
  price_policy: "latest_price_at_or_before_date_else_fifo_cost";
  cost_fallback_used: boolean;
  cost_fallback_securities: { security_id: number; ticker: string; name: string }[];
}

export interface NetWorthReport {
  as_of_date: string;
  total_accounts_balance: string;
  total_portfolio_value: string;
  net_worth: string;
  by_account: { account_id: number; name: string; balance: string }[];
  /** Sum of checking account balances only. */
  liquid_balance: string;
  average_monthly_expenses: string | null;
  runway_months: string | null;
  /** Distinguishes market quotes from FIFO cost estimates. */
  portfolio_valuation: PortfolioValuationMetadata;
}

export interface IncomeStatementPeriod {
  period_label: string;
  total_income: string;
  total_expense: string;
  net: string;
  savings_rate_pct: string | null;
}

export interface IncomeStatementReport {
  periods: IncomeStatementPeriod[];
  total_income: string;
  total_expense: string;
  net: string;
  /** Mean of calculable monthly rates in the period, capped at P5/P95. */
  average_savings_rate_pct: string | null;
  savings_rate_months: number;
}

export interface CategoryAnalysisItem {
  category_id: number | null;
  category_name: string;
  total_amount: string;
  pct_of_total: string;
}

export interface CategoryAnalysisDetailItem extends CategoryAnalysisItem {
  top_level_category_id: number | null;
}

export interface CategoryAnalysisMonth {
  period_label: string;
  total_amount: string;
}

/** Shared structure for spending, income and transfer analysis. */
export interface CategoryAnalysisReport {
  period_from: string | null;
  period_to: string | null;
  total_amount: string;
  by_category: CategoryAnalysisItem[];
  /** Complete aggregation over the hierarchy's root categories. */
  by_top_level_category: CategoryAnalysisItem[];
  /** All categories with transactions, each linked to its root. */
  by_category_detail: CategoryAnalysisDetailItem[];
  by_month: CategoryAnalysisMonth[];
  top_transactions: {
    id: number;
    date: string;
    description: string | null;
    amount: string;
    currency: string;
    amount_eur: string;
  }[];
}

export interface DateRange {
  from?: string;
  to?: string;
}

export interface AccountsBalanceHistoryPoint {
  date: string;
  /** Cash only: decreases when securities are purchased. */
  total_balance: string;
  portfolio_value: string;
  net_worth: string;
  portfolio_valuation: PortfolioValuationMetadata;
}

export interface PortfolioConcentration {
  top_weight_pct: string | null;
  top_ticker: string | null;
  top3_weight_pct: string | null;
  top5_weight_pct: string | null;
  effective_holdings: string | null;
}

export interface SecuritiesByCurrency {
  currency: string;
  total_value: string;
  pct_of_total: string;
  positions_count: number;
}

export interface SecuritiesByType {
  type: string;
  total_value: string;
  pct_of_total: string;
  positions_count: number;
}

export interface SecurityPositionItem {
  security_id: number;
  ticker: string;
  name: string;
  type: string;
  sector: string | null;
  industry: string | null;
  country: string | null;
  current_value: string;
  total_invested: string;
  unrealized_gain_loss: string;
  unrealized_gain_loss_pct: string | null;
  valuation_source: "market_price" | "fifo_cost";
}

export interface SecuritiesByClassification {
  key: string;
  total_value: string;
  pct_of_total: string;
  positions_count: number;
}

export interface DividendYearPoint {
  year: number;
  gross: string;
  net: string;
  tax: string;
  cumulative_net: string;
  events_count: number;
  growth_pct: string | null;
}

export interface DividendMonthPoint {
  month: number;
  net: string;
  events_count: number;
}

export interface DividendBySecurity {
  security_id: number;
  ticker: string;
  name: string;
  type: string;
  gross: string;
  net: string;
  tax: string;
  events_count: number;
  pct_of_total: string;
  yield_on_cost_pct: string | null;
}

export interface DividendByKey {
  key: string;
  net: string;
  pct_of_total: string;
  events_count: number;
}

export interface DividendsAnalysisReport {
  period_from: string | null;
  period_to: string | null;
  total_gross: string;
  total_net: string;
  total_tax: string;
  tax_incidence_pct: string | null;
  events_count: number;
  first_event_date: string | null;
  last_event_date: string | null;
  trailing_12m_net: string;
  portfolio_yield_on_cost_pct: string | null;
  average_monthly_net: string | null;
  by_year: DividendYearPoint[];
  by_month: DividendMonthPoint[];
  by_security: DividendBySecurity[];
  by_security_type: DividendByKey[];
  by_event_type: DividendByKey[];
}

export interface CostItem {
  date: string | null;
  cost_type: string;
  description: string;
  amount_eur: string;
  is_estimated: boolean;
  ticker: string | null;
}

export interface CostGroup {
  group: "taxes" | "trading" | "recurring";
  total_eur: string;
  pct_of_total: string;
  estimated_eur: string;
  items: CostItem[];
}

export interface RealizedResult {
  capital_gains: string;
  capital_losses: string;
  net_realized: string;
  income_gross: string;
  gross_result: string;
}

export interface CostImpact {
  pct_of_invested: string | null;
  pct_of_gross_result: string | null;
  annual_incidence_pct: string | null;
  average_invested_capital: string | null;
  average_portfolio_value: string | null;
  period_days: number | null;
  twr_gross: string | null;
  twr_net: string | null;
  twr_drag_pct_points: string | null;
}

/** Period tax position, calculated centrally by the backend.
 * Capital losses offset gains; tax applies to the net amount.
 * Centralisation avoids inconsistent estimates between reports. */
export interface FiscalPosition {
  capital_gains: string;
  capital_losses: string;
  /** Taxable base: capital gains minus capital losses. */
  net_capital_gain_loss: string;
  tax_rate_pct: string;
  /** Theoretical tax on the net amount, before deducting withholding. */
  gross_estimated_tax: string;
  /** Capital gains tax already recorded as a cost on a sale. */
  tax_already_withheld: string;
  /** Estimated remaining tax payable. Never negative. */
  estimated_tax_due: string;
  dividend_withholding: string;
}

export interface CostsAnalysisReport {
  period_from: string | null;
  period_to: string | null;
  realized: RealizedResult;
  fiscal: FiscalPosition;
  total_costs: string;
  total_estimated: string;
  groups: CostGroup[];
  net_result: string;
  impact: CostImpact;
  /** Informational current estimate; excluded from period costs. */
  current_stamp_duty_estimate: CostItem | null;
  disclaimer: string;
}

export interface SecuritiesAnalysisReport {
  total_value: string;
  positions_count: number;
  concentration: PortfolioConcentration;
  by_type: SecuritiesByType[];
  by_currency: SecuritiesByCurrency[];
  by_sector: SecuritiesByClassification[];
  by_industry: SecuritiesByClassification[];
  by_country: SecuritiesByClassification[];
  positions: SecurityPositionItem[];
  top_by_value: SecurityPositionItem[];
  top_gainers: SecurityPositionItem[];
  top_losers: SecurityPositionItem[];
  portfolio_valuation: PortfolioValuationMetadata;
}

export function useNetWorth() {
  return useQuery({
    queryKey: ["reports", "net-worth"],
    queryFn: () => apiFetch<NetWorthReport>("/reports/net-worth"),
  });
}

export function useNetWorthHistory() {
  return useQuery({
    queryKey: ["reports", "net-worth", "history"],
    queryFn: () => apiFetch<AccountsBalanceHistoryPoint[]>("/reports/net-worth/history"),
  });
}

function analysisQueryString(range: DateRange): string {
  const params = new URLSearchParams();
  if (range.from) params.set("date_from", range.from);
  if (range.to) params.set("date_to", range.to);
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

/** All three analyses share endpoint shape and hooks, ensuring report
 * tabs display the same statistics (specification §7.5). */
function useCategoryAnalysis(endpoint: string, range: DateRange) {
  return useQuery({
    queryKey: ["reports", endpoint, range.from ?? null, range.to ?? null],
    queryFn: () =>
      apiFetch<CategoryAnalysisReport>(`/reports/${endpoint}${analysisQueryString(range)}`),
  });
}

export function useSpendingAnalysis(range: DateRange = {}) {
  return useCategoryAnalysis("spending-analysis", range);
}

export function useIncomeAnalysis(range: DateRange = {}) {
  return useCategoryAnalysis("income-analysis", range);
}

export function useTransferAnalysis(range: DateRange = {}) {
  return useCategoryAnalysis("transfer-analysis", range);
}

export function useDividendsAnalysis(range: DateRange) {
  return useQuery({
    queryKey: ["reports", "dividends-analysis", range.from ?? null, range.to ?? null],
    queryFn: () =>
      apiFetch<DividendsAnalysisReport>(`/reports/dividends-analysis${analysisQueryString(range)}`),
  });
}

export function useCostsAnalysis(range: DateRange) {
  return useQuery({
    queryKey: ["reports", "costs-analysis", range.from ?? null, range.to ?? null],
    queryFn: () =>
      apiFetch<CostsAnalysisReport>(`/reports/costs-analysis${analysisQueryString(range)}`),
  });
}

export function useSecuritiesAnalysis() {
  return useQuery({
    queryKey: ["reports", "securities-analysis"],
    queryFn: () => apiFetch<SecuritiesAnalysisReport>("/reports/securities-analysis"),
  });
}

export function useIncomeStatement(range: DateRange = {}) {
  return useQuery({
    queryKey: ["reports", "income-statement", range.from ?? null, range.to ?? null],
    queryFn: () =>
      apiFetch<IncomeStatementReport>(`/reports/income-statement${analysisQueryString(range)}`),
  });
}
