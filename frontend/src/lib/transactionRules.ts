import type { Category } from "@/api/types";

/** Manual transactions require a leaf category at any depth. Transfers
 * use a dedicated flow that creates both linked rows. */
export function getAssignableTransactionCategories(categories: Category[]): Category[] {
  const parentIds = new Set(
    categories.flatMap((category) =>
      category.parent_id === null ? [] : [category.parent_id]
    )
  );

  return categories.filter(
    (category) =>
      !parentIds.has(category.id) && category.type !== "transfer"
  );
}

interface ManualTransactionInput {
  accountId: string;
  categoryId: string;
  amount: string;
  categories: Category[];
}

/** Return the first form error to display, or null. */
export function validateManualTransaction({
  accountId,
  categoryId,
  amount,
  categories,
}: ManualTransactionInput): string | null {
  if (!accountId) return "Account is required.";
  if (!categoryId) return "Category is required.";
  if (!amount.trim()) return "Amount is required.";

  const numericAmount = Number(amount);
  if (!Number.isFinite(numericAmount)) return "Enter a valid numeric amount.";
  if (numericAmount === 0) return "Amount must be nonzero.";

  const category = categories.find((item) => item.id === Number(categoryId));
  if (!category) return "The selected category is unavailable.";
  if (category.type === "transfer") {
    return "Use the Transfer button for transfers.";
  }

  const assignable = getAssignableTransactionCategories(categories).some(
    (item) => item.id === category.id
  );
  if (!assignable) {
    return "Select a leaf category: categories containing subcategories cannot have associated transactions.";
  }

  if (category.type === "income" && numericAmount < 0) {
    return "An income category requires a positive amount.";
  }
  if (category.type === "expense" && numericAmount > 0) {
    return "An expense category requires a negative amount.";
  }

  return null;
}
