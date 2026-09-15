/** Keep the requested page in range after the total changes. */
export function clampPageToTotal(page: number, total: number, pageSize: number): number {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  return Math.min(Math.max(1, page), totalPages);
}
