import type { ReactNode } from "react";

import type { SortDirection } from "@/lib/tableSort";

export default function SortableHeader({
  children,
  active,
  direction,
  onSort,
  align = "left",
  className = "",
}: {
  children: ReactNode;
  active: boolean;
  direction: SortDirection;
  onSort: () => void;
  align?: "left" | "right";
  className?: string;
}) {
  return (
    <th
      scope="col"
      aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}
      className={`${align === "right" ? "text-right" : "text-left"} ${className}`}
    >
      <button
        type="button"
        onClick={onSort}
        className={`inline-flex w-full items-center gap-1 hover:text-gray-900 ${
          align === "right" ? "justify-end" : "justify-start"
        }`}
      >
        {children}
        {active && <span aria-hidden="true">{direction === "asc" ? "▲" : "▼"}</span>}
      </button>
    </th>
  );
}
