import type { Account, Security } from "@/api/types";

/** Inactive records remain available for historical reads but cannot
 * receive new writes. Centralising this rule keeps forms consistent. */
export function isAccountPresentOn(account: Account, effectiveOn?: string): boolean {
  if (!effectiveOn) return true;
  return (
    (!account.opened_on || account.opened_on <= effectiveOn) &&
    (!account.closed_on || account.closed_on >= effectiveOn)
  );
}

export function getWritableCashAccounts(
  accounts: Account[] | undefined,
  effectiveOn?: string
): Account[] {
  return (accounts ?? []).filter(
    (account) =>
      account.is_active &&
      account.type !== "investment" &&
      isAccountPresentOn(account, effectiveOn)
  );
}

export function getWritableInvestmentAccounts(
  accounts: Account[] | undefined,
  effectiveOn?: string
): Account[] {
  return (accounts ?? []).filter(
    (account) =>
      account.is_active &&
      account.type === "investment" &&
      isAccountPresentOn(account, effectiveOn)
  );
}

export function getWritableSecurities(
  securities: Security[] | undefined
): Security[] {
  return (securities ?? []).filter((security) => security.is_active);
}

export function containsSelectedId(
  items: ReadonlyArray<{ id: number }>,
  selectedId: string
): boolean {
  return items.some((item) => String(item.id) === selectedId);
}
