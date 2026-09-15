import { useState } from "react";

import {
  nextTableSort,
  sortTableRows,
  type SortDirection,
  type SortValue,
  type TableSortState,
} from "@/lib/tableSort";

/** Shared client state and sorting for tables without server pagination. */
export function useTableSort<Row, Key extends string>(
  rows: readonly Row[],
  initial: TableSortState<Key>,
  valueOf: (row: Row, key: Key) => SortValue
) {
  const [sort, setSort] = useState(initial);

  function requestSort(key: Key, firstDirection: SortDirection = "asc") {
    setSort((current) => nextTableSort(current, key, firstDirection));
  }

  return {
    sort,
    requestSort,
    sortedRows: sortTableRows(rows, sort, valueOf),
  };
}
