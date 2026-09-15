/** Monotonic gate for replaceable asynchronous operations. Responses
 * update state only if no newer request has started. It does not cancel
 * network requests; it prevents stale results attaching to new inputs. */
export function createLatestRequestGate() {
  let latest = 0;
  return {
    begin(): number {
      latest += 1;
      return latest;
    },
    isCurrent(requestId: number): boolean {
      return requestId === latest;
    },
    invalidate(): void {
      latest += 1;
    },
  };
}
