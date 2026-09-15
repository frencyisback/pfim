export const CATEGORY_COLUMN_REQUIRED_MESSAGE =
  "Category column mapping is required. Enter the CSV column name containing the category.";

export function validateCategoryColumn(value: string | null | undefined): string | null {
  return value?.trim() ? null : CATEGORY_COLUMN_REQUIRED_MESSAGE;
}
