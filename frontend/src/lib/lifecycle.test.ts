import { describe, expect, it } from "vitest";

import type { Account, Security } from "@/api/types";
import {
  containsSelectedId,
  getWritableCashAccounts,
  getWritableInvestmentAccounts,
  getWritableSecurities,
  isAccountPresentOn,
} from "./lifecycle";

const accounts: Account[] = [
  {
    id: 1,
    name: "Active checking account",
    type: "checking",
    currency: "EUR",
    opening_balance: "0",
    notes: null,
    is_active: true,
    reference_account_id: null,
  },
  {
    id: 2,
    name: "Historical checking account",
    type: "checking",
    currency: "EUR",
    opening_balance: "0",
    notes: null,
    is_active: false,
    reference_account_id: null,
  },
  {
    id: 3,
    name: "Active investment account",
    type: "investment",
    currency: "EUR",
    opening_balance: "0",
    notes: null,
    is_active: true,
    reference_account_id: 1,
  },
  {
    id: 4,
    name: "Historical investment account",
    type: "investment",
    currency: "EUR",
    opening_balance: "0",
    notes: null,
    is_active: false,
    reference_account_id: 2,
  },
];

const securities: Security[] = [
  {
    id: 10,
    ticker: "ACT",
    name: "Active security",
    type: "stock",
    market: null,
    currency: "EUR",
    isin: null,
    sector: null,
    industry: null,
    country: null,
    is_active: true,
  },
  {
    id: 11,
    ticker: "OLD",
    name: "Historical security",
    type: "stock",
    market: null,
    currency: "EUR",
    isin: null,
    sector: null,
    industry: null,
    country: null,
    is_active: false,
  },
];

describe("selectors for new writes", () => {
  it("allows only active cash accounts", () => {
    expect(getWritableCashAccounts(accounts).map((account) => account.id)).toEqual([1]);
  });

  it("allows only active investment accounts", () => {
    expect(getWritableInvestmentAccounts(accounts).map((account) => account.id)).toEqual([
      3,
    ]);
  });

  it("allows only active securities", () => {
    expect(getWritableSecurities(securities).map((security) => security.id)).toEqual([10]);
  });

  it("rechecks a stale selection before submission", () => {
    const writableAccounts = getWritableCashAccounts(accounts);

    expect(containsSelectedId(writableAccounts, "1")).toBe(true);
    expect(containsSelectedId(writableAccounts, "2")).toBe(false);
    expect(containsSelectedId(writableAccounts, "")).toBe(false);
  });

  it("excludes accounts from writes before their opening date", () => {
    const datedAccounts = accounts.map((account) =>
      account.id === 1 ? { ...account, opened_on: "2026-08-20" } : account
    );

    expect(isAccountPresentOn(datedAccounts[0], "2026-08-19")).toBe(false);
    expect(getWritableCashAccounts(datedAccounts, "2026-08-19")).toEqual([]);
    expect(getWritableCashAccounts(datedAccounts, "2026-08-20").map((a) => a.id)).toEqual([1]);
  });

  it("treats opening and closing dates as inclusive and leaves legacy dates unrestricted", () => {
    const datedAccount: Account = {
      ...accounts[0],
      opened_on: "2026-08-10",
      closed_on: "2026-08-20",
    };

    expect(isAccountPresentOn(datedAccount, "2026-08-09")).toBe(false);
    expect(isAccountPresentOn(datedAccount, "2026-08-10")).toBe(true);
    expect(isAccountPresentOn(datedAccount, "2026-08-20")).toBe(true);
    expect(isAccountPresentOn(datedAccount, "2026-08-21")).toBe(false);
    expect(
      isAccountPresentOn(
        { ...datedAccount, opened_on: null, closed_on: null },
        "1990-01-01"
      )
    ).toBe(true);
  });
});
