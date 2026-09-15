import type { ReactNode } from "react";

export default function CollapsibleTable({
  title,
  count,
  children,
}: {
  title: string;
  count?: number;
  children: ReactNode;
}) {
  return (
    <details className="group">
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
        <span aria-hidden="true" className="transition-transform group-open:rotate-90">
          ▸
        </span>
        <span>{title}</span>
        {count !== undefined && <span className="text-xs font-normal text-gray-400">({count})</span>}
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}
