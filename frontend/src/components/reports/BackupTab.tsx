import { useState } from "react";
import {
  backupDownloadUrl,
  backupManifestDownloadUrl,
  useBackupStatus,
  useBackups,
  useCreateBackup,
  type BackupInfo,
} from "@/api/backup";
import {
  describeBackupCreationAvailability,
  describeBackupVerification,
  describeRestoreAvailability,
} from "@/lib/backup";
import { formatUtcDateTime } from "@/lib/dates";
import { RestoreDialog } from "@/components/reports/RestoreDialog";
import CollapsibleTable from "@/components/common/CollapsibleTable";
import SortableHeader from "@/components/common/SortableHeader";
import { useTableSort } from "@/lib/useTableSort";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown error";
}

export function BackupTab() {
  const { data: backups, isLoading, error: backupsError } = useBackups();
  const {
    data: status,
    isLoading: isStatusLoading,
    error: statusError,
  } = useBackupStatus();
  const createBackup = useCreateBackup();
  const [message, setMessage] = useState<string | null>(null);
  const [restoreCandidate, setRestoreCandidate] = useState<BackupInfo | null>(null);
  const statusKnown = !isStatusLoading && statusError === null && status !== undefined;
  const creationAvailability = describeBackupCreationAvailability({
    backupEnabled: status?.backup_enabled,
    isLoading: isStatusLoading,
    hasError: statusError !== null,
  });
  type BackupSortKey = "filename" | "created" | "size" | "verification";
  const backupSort = useTableSort<BackupInfo, BackupSortKey>(
    backups ?? [],
    { key: "created", direction: "desc" },
    (backup, key) => {
      if (key === "filename") return backup.filename;
      if (key === "created") return backup.created_at;
      if (key === "size") return backup.size_bytes;
      return describeBackupVerification(backup).label;
    }
  );

  async function handleCreate() {
    setMessage(null);
    try {
      const backup = await createBackup.mutateAsync();
      setMessage(`Backup created: ${backup.filename}`);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Unknown error");
    }
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <p className="mb-3 text-sm text-gray-600">
          Backups use SQLite online snapshots and are published only after integrity,
          foreign-key, schema-revision and SHA-256 hash checks.
        </p>
        {creationAvailability.kind === "disabled" && (
          <p className="mb-3 rounded bg-amber-50 px-3 py-2 text-sm text-amber-800">
            Backup creation is disabled for safety: this deployment must enable it
            with the expected Alembic revision.
          </p>
        )}
        {creationAvailability.kind === "unavailable" && (
          <p
            role="alert"
            className="mb-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700"
          >
            Unable to verify backup status: the backend is unreachable or
            the status endpoint returned an error.
            {statusError && ` Details: ${errorMessage(statusError)}`}
          </p>
        )}
        {status?.maintenance_mode && (
          <p role="status" className="mb-3 rounded bg-amber-50 px-3 py-2 text-sm text-amber-800">
            Maintenance in progress · status {status.restore_state}
            {status.active_restore_id && ` · operation ${status.active_restore_id}`}.
          </p>
        )}
        <button
          onClick={handleCreate}
          disabled={
            createBackup.isPending ||
            !creationAvailability.createAllowed ||
            status?.maintenance_mode === true
          }
          className="rounded bg-gray-900 px-4 py-1.5 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
        >
          {createBackup.isPending ? "Creating backup..." : "Create backup now"}
        </button>
        {message && <p className="mt-2 text-sm text-gray-600">{message}</p>}
        {statusKnown && !status.maintenance_mode && status.restore_enabled && (
          <p className="mt-3 text-xs text-gray-500">
            Restore is available only for verified backups compatible with the expected
            schema revision. A safety backup is created before replacing the database.
          </p>
        )}
        {statusKnown && !status.maintenance_mode && !status.restore_enabled && (
          <p className="mt-3 text-xs text-gray-500">
            Restore is disabled in this deployment. Files remain available to download
            for external storage.
          </p>
        )}
      </div>

      {isLoading && <p className="text-sm text-gray-500">Loading...</p>}
      {backupsError && (
        <p role="alert" className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">
          Unable to load the backup list: {errorMessage(backupsError)}
        </p>
      )}
      {backups && (
        <CollapsibleTable title="Available backups" count={backups.length}>
          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
            <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-500">
              <tr>
                {([
                  ["filename", "File", "left"],
                  ["created", "Date", "left"],
                  ["size", "Size", "right"],
                  ["verification", "Verification", "left"],
                ] as const).map(([key, label, align]) => (
                  <SortableHeader
                    key={key}
                    active={backupSort.sort.key === key}
                    direction={backupSort.sort.direction}
                    onSort={() => backupSort.requestSort(key)}
                    align={align}
                    className="px-3 py-2"
                  >
                    {label}
                  </SortableHeader>
                ))}
                <th className="px-3 py-2 text-right">Download</th>
                <th className="px-3 py-2 text-right">Restore</th>
              </tr>
            </thead>
            <tbody>
              {backupSort.sortedRows.map((b) => {
                const verification = describeBackupVerification(b);
                const restoreAvailability = describeRestoreAvailability({
                  restoreEligible: b.restore_eligible,
                  restoreEnabled: status?.restore_enabled,
                  maintenanceMode: status?.maintenance_mode,
                  activeRestoreId: status?.active_restore_id,
                  statusKnown,
                });
                return (
                  <tr key={b.filename} className="border-t border-gray-100">
                    <td className="px-3 py-2 font-mono text-xs">{b.filename}</td>
                    <td className="px-3 py-2" title="Local time">
                      {formatUtcDateTime(b.created_at)}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {(b.size_bytes / 1024).toFixed(0)} KB
                    </td>
                    <td className="px-3 py-2 text-xs">
                      <span
                        className={
                          verification.kind === "verified"
                            ? "text-green-700"
                            : verification.kind === "invalid"
                              ? "text-red-700"
                              : "text-amber-700"
                        }
                        title={verification.title}
                      >
                        {verification.label}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      {verification.downloadAllowed ? (
                        <a
                          href={backupDownloadUrl(b.filename)}
                          className="text-xs text-blue-600 hover:underline"
                        >
                          Database
                        </a>
                      ) : (
                        <span className="text-xs text-gray-400" title={verification.title}>
                          Download blocked
                        </span>
                      )}
                      {b.verified && (
                        <a
                          href={backupManifestDownloadUrl(b.filename)}
                          className="ml-3 text-xs text-blue-600 hover:underline"
                        >
                          Manifest
                        </a>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {restoreAvailability.restoreAllowed && b.sha256 ? (
                        <button
                          type="button"
                          onClick={() => setRestoreCandidate(b)}
                          className="text-xs font-medium text-red-700 hover:underline"
                        >
                          Restore
                        </button>
                      ) : !b.restore_eligible ? (
                        <span
                          className="text-xs text-gray-400"
                          title={b.restore_ineligible_reason ?? "Backup cannot be restored"}
                        >
                          Ineligible
                        </span>
                      ) : (
                        <span className="text-xs text-gray-400">
                          {restoreAvailability.kind === "maintenance" ||
                          restoreAvailability.kind === "active"
                            ? "Maintenance"
                            : restoreAvailability.kind === "unavailable"
                              ? "Status unavailable"
                              : "Unavailable"}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
              {backups.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-3 py-6 text-center text-gray-400">
                    No backups created yet.
                  </td>
                </tr>
              )}
            </tbody>
            </table>
          </div>
        </CollapsibleTable>
      )}
      {restoreCandidate && (
        <RestoreDialog
          key={restoreCandidate.filename}
          backup={restoreCandidate}
          status={status}
          statusKnown={statusKnown}
          onClose={() => setRestoreCandidate(null)}
        />
      )}
    </div>
  );
}
