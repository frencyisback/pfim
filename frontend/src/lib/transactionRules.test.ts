import { describe, expect, it } from "vitest";

import type { Category } from "@/api/types";
import {
  getAssignableTransactionCategories,
  validateManualTransaction,
} from "./transactionRules";

function category(
  id: number,
  name: string,
  type: Category["type"],
  parentId: number | null = null
): Category {
  return {
    id,
    name,
    type,
    parent_id: parentId,
    color: null,
    icon: null,
    is_system: false,
  };
}

const categories = [
  category(1, "Example work", "income"),
  category(2, "Example salary", "income", 1),
  category(3, "Example refunds", "income"),
  category(4, "Example housing", "expense"),
  category(5, "Example rent", "expense", 4),
  category(6, "Example internal transfer", "transfer"),
];

describe("getAssignableTransactionCategories", () => {
  it("includes income/expense leaves even when they are root categories", () => {
    expect(getAssignableTransactionCategories(categories).map((item) => item.id)).toEqual([
      2, 3, 5,
    ]);
  });

  it("excludes categories with children and all transfer categories", () => {
    const ids = getAssignableTransactionCategories(categories).map((item) => item.id);
    expect(ids).not.toContain(1);
    expect(ids).not.toContain(4);
    expect(ids).not.toContain(6);
  });
});

describe("validateManualTransaction", () => {
  const validate = (categoryId: string, amount: string) =>
    validateManualTransaction({ accountId: "10", categoryId, amount, categories });

  it("accepts positive inflows and negative outflows", () => {
    expect(validate("2", "1800.00")).toBeNull();
    expect(validate("3", "25.50")).toBeNull();
    expect(validate("5", "-750.00")).toBeNull();
  });

  it("rejects zero amounts including signed zero", () => {
    expect(validate("2", "0")).toMatch(/nonzero/i);
    expect(validate("5", "-0.00")).toMatch(/nonzero/i);
  });

  it("flags signs inconsistent with category types", () => {
    expect(validate("2", "-1")).toMatch(/income.*positive/i);
    expect(validate("5", "1")).toMatch(/expense.*negative/i);
  });

  it("rejects parent and transfer categories", () => {
    expect(validate("1", "100")).toMatch(/leaf category/i);
    expect(validate("6", "100")).toMatch(/Transfer button/i);
  });

  it("explicitly requires account, category and amount", () => {
    expect(
      validateManualTransaction({ accountId: "", categoryId: "2", amount: "1", categories })
    ).toMatch(/account.*required/i);
    expect(validate("", "1")).toMatch(/category.*required/i);
    expect(validate("2", " ")).toMatch(/amount.*required/i);
  });
});
