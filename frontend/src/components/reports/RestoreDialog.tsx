import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  invalidateAfterRestore,
  isRestoreOperationTerminal,
  useRestoreBackup,
  useRestoreOperation,
  type BackupInfo,
  type BackupStatus,
  type RestoreOperation,
} from "@/api/backup";
import { ApiError, ApiNetworkError } from "@/api/client";
import {
  describeRestoreAvailability,
  describeRestoreError,
  isRestoreConfirmationValid,
  restoreConfirmationPhrase,
} from "@/lib/backup";
import { formatUtcDateTime } from "@/lib/dates";

interface RestoreDialogProps {
  backup: BackupInfo;
  status: BackupStatus | undefined;
  statusKnown: boolean;
  onClose: () => void;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown error";
}

export function RestoreDialog({ backup, status, statusKnown, onClose }: RestoreDialogProps) {
  const queryClient = useQueryClient();
  const restore = useRestoreBackup();
  const [confirmation, setConfirmation] = useState("");
  const [operationId, setOperationId] = useState<string | null>(null);
  const [initialOperation, setInitialOperation] = useState<RestoreOperation | null>(null);
  const [knownError, setKnownError] = useState<string | null>(null);
  const [uncertainOutcome, setUncertainOutcome] = useState(false);
  const submitted = useRef(false);
  const invalidatedOperation = useRef<string | null>(null);

  const initialOperationTerminal =
    initialOperation !== null && isRestoreOperationTerminal(initialOperation);
  const operationQuery = useRestoreOperation(
    operationId,
    operationId !== null && !initialOperationTerminal
  );
  const operation = operationQuery.data ?? initialOperation;
  const operationTerminal = operation !== null && isRestoreOperationTerminal(operation);
  const operationPending = operationId !== null && !operationTerminal;
  const pending = restore.isPending || operationPending;
  const phrase = restoreConfirmationPhrase(backup.filename);
  const availability = describeRestoreAvailability({
    restoreEligible: backup.restore_eligible,
    restoreEnabled: status?.restore_enabled,
    maintenanceMode: status?.maintenance_mode,
    activeRestoreId: status?.active_restore_id,
    statusKnown,
  });
  const canSubmit =
    availability.restoreAllowed &&
    backup.sha256 !== null &&
    isRestoreConfirmationValid(confirmation, backup.filename) &&
    !pending &&
    operationId === null &&
    knownError === null;

  useEffect(() => {
    if (!operation?.restored || invalidatedOperation.current === operation.operation_id) return;
    invalidatedOperation.current = operation.operation_id;
    void invalidateAfterRestore(queryClient);
  }, [operation, queryClient]);

  async function handleRestore() {
    if (!canSubmit || backup.sha256 === null || submitted.current) return;

    submitted.current = true;
    const requestId = crypto.randomUUID();
    setKnownError(null);
    setUncertainOutcome(false);
    restore.reset();
    try {
      const result = await restore.mutateAsync({
        filename: backup.filename,
        request_id: requestId,
        expected_sha256: backup.sha256,
        confirmation: phrase,
      });
      setInitialOperation(result);
      setOperationId(result.operation_id);
    } catch (error) {
      if (error instanceof ApiError) {
        setKnownError(describeRestoreError(error.errorCode, error.message));
        void queryClient.invalidateQueries({ queryKey: ["backups"] });
        void queryClient.invalidateQueries({ queryKey: ["backup-status"] });
        return;
      }
      if (error instanceof ApiNetworkError && !error.requestSent) {
        setKnownError(error.message);
        return;
      }

      // The request may have been received and completed even if the response
      // was lost. Do not repeat the POST: request_id identifies the operation
      // to poll until its outcome becomes known.
      setUncertainOutcome(true);
      setOperationId(requestId);
    }
  }

  const terminalFailure = operationTerminal && operation !== null && !operation.restored;
  const closeLabel = operationId !== null || knownError ? "Close" : "Cancel";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="restore-dialog-title"
        className="max-h-[90vh] w-full max-w-xl overflow-auto rounded-lg bg-white p-5 shadow-xl"
      >
        <h3 id="restore-dialog-title" className="text-lg font-semibold text-red-800">
          Restore database from backup
        </h3>
        <p className="mt-2 text-sm text-gray-700">
          This operation replaces all current data. The backend enters maintenance mode, verifies the candidate again and creates a safety backup first.
        </p>

        <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded bg-gray-50 p-3 text-xs">
          <dt className="font-medium text-gray-500">File</dt>
          <dd className="break-all font-mono">{backup.filename}</dd>
          <dt className="font-medium text-gray-500">Date</dt>
          <dd>{formatUtcDateTime(backup.created_at)}</dd>
          <dt className="font-medium text-gray-500">Revision</dt>
          <dd className="font-mono">{backup.alembic_revision ?? "—"}</dd>
          <dt className="font-medium text-gray-500">SHA-256</dt>
          <dd className="break-all font-mono">{backup.sha256 ?? "—"}</dd>
        </dl>

        {!operationId && !knownError && (
          <label className="mt-4 block text-sm text-gray-700">
            To confirm, type exactly:
            <code className="my-2 block break-all rounded bg-red-50 px-2 py-1 text-xs text-red-800">
              {phrase}
            </code>
            <input
              autoFocus
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              disabled={pending}
              autoComplete="off"
              spellCheck={false}
              className="w-full rounded border border-gray-300 px-3 py-2 font-mono text-sm disabled:opacity-50"
            />
          </label>
        )}

        {availability.kind !== "enabled" && !operationId && !knownError && (
          <p role="alert" className="mt-3 rounded bg-amber-50 px-3 py-2 text-sm text-amber-800">
            Restore is no longer available: the backend status or backup eligibility has changed. Close and refresh the list.
          </p>
        )}

        {restore.isPending && (
          <p role="status" className="mt-3 rounded bg-blue-50 px-3 py-2 text-sm text-blue-800">
            Starting restore and entering maintenance…
          </p>
        )}

        {uncertainOutcome && !operation && (
          <p role="alert" className="mt-3 rounded bg-amber-50 px-3 py-2 text-sm text-amber-800">
            The network response was lost and the outcome is uncertain. The POST will not be repeated; checking operation {operationId}.
          </p>
        )}

        {operationQuery.error && !operationTerminal && (
          <p role="status" className="mt-3 rounded bg-amber-50 px-3 py-2 text-sm text-amber-800">
            Operation status temporarily unavailable: {errorMessage(operationQuery.error)}. Checks will continue without repeating the restore.
          </p>
        )}

        {operation && !operationTerminal && (
          <p role="status" className="mt-3 rounded bg-blue-50 px-3 py-2 text-sm text-blue-800">
            {operation.message ?? `Restore in progress · status ${operation.state}`}
          </p>
        )}

        {operation?.restored && (
          <div role="status" className="mt-3 rounded bg-green-50 px-3 py-2 text-sm text-green-800">
            <p className="font-medium">Restore completed.</p>
            <p className="mt-1 break-all">Database: {operation.restored_backup ?? backup.filename}</p>
            <p className="break-all">
              Safety backup: {operation.pre_restore_backup ?? "not specified"}
            </p>
            {operation.requires_reload && (
              <p className="mt-1">Reload the application to use only the restored data.</p>
            )}
          </div>
        )}

        {terminalFailure && operation && (
          <p role="alert" className="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">
            {describeRestoreError(
              operation.error_code,
              operation.message ?? "The restore did not complete."
            )}
          </p>
        )}

        {knownError && (
          <p role="alert" className="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">
            {knownError}
          </p>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={pending}
            className="rounded border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"
          >
            {closeLabel}
          </button>
          {operation?.restored && operation.requires_reload ? (
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="rounded bg-gray-900 px-3 py-1.5 text-sm text-white hover:bg-gray-700"
            >
              Reload application
            </button>
          ) : (
            !operationId &&
            !knownError && (
              <button
                type="button"
                onClick={handleRestore}
                disabled={!canSubmit}
                className="rounded bg-red-700 px-3 py-1.5 text-sm text-white hover:bg-red-800 disabled:opacity-50"
              >
                {restore.isPending ? "Restore in progress…" : "Permanently restore"}
              </button>
            )
          )}
        </div>
      </div>
    </div>
  );
}
