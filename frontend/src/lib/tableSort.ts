export type SortDirection = "asc" | "desc";

export interface TableSortState<Key extends string> {
  key: Key;
  direction: SortDirection;
}

export type SortValue = string | number | boolean | null | undefined;

/** Two states: clicking the same column again always reverses order. */
export function nextTableSort<Key extends string>(
  current: TableSortState<Key>,
  key: Key,
  firstDirection: SortDirection = "asc"
): TableSortState<Key> {
  if (current.key !== key) return { key, direction: firstDirection };
  return { key, direction: current.direction === "asc" ? "desc" : "asc" };
}

function compareValues(left: SortValue, right: SortValue): number {
  const leftMissing = left === null || left === undefined || left === "";
  const rightMissing = right === null || right === undefined || right === "";
  if (leftMissing || rightMissing) {
    if (leftMissing && rightMissing) return 0;
    return leftMissing ? 1 : -1;
  }
  if (typeof left === "number" && typeof right === "number") return left - right;
  if (typeof left === "boolean" && typeof right === "boolean") {
    return Number(left) - Number(right);
  }
  return String(left).localeCompare(String(right), "it", {
    numeric: true,
    sensitivity: "base",
  });
}

/** Stable sort on a copy. Missing values remain last in both ascending
 * and descending order. */
export function sortTableRows<Row, Key extends string>(
  rows: readonly Row[],
  state: TableSortState<Key>,
  valueOf: (row: Row, key: Key) => SortValue
): Row[] {
  return rows
    .map((row, index) => ({ row, index }))
    .sort((left, right) => {
      const leftValue = valueOf(left.row, state.key);
      const rightValue = valueOf(right.row, state.key);
      const leftMissing = leftValue === null || leftValue === undefined || leftValue === "";
      const rightMissing = rightValue === null || rightValue === undefined || rightValue === "";
      const compared = compareValues(leftValue, rightValue);
      const directed =
        leftMissing || rightMissing || state.direction === "asc" ? compared : -compared;
      return directed || left.index - right.index;
    })
    .map(({ row }) => row);
}
