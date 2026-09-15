function queryErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown error";
}

/** Shared read-query status distinguishes network errors from
 * genuinely empty lists or reports. */
export default function QueryStateNotice({
  isLoading = false,
  error = null,
  errorPrefix = "Loading error",
}: {
  isLoading?: boolean;
  error?: unknown;
  errorPrefix?: string;
}) {
  if (error) {
    return (
      <p
        role="alert"
        className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
      >
        {errorPrefix}: {queryErrorMessage(error)}
      </p>
    );
  }

  if (isLoading) {
    return (
      <p role="status" className="text-sm text-gray-500">
        Loading...
      </p>
    );
  }

  return null;
}
