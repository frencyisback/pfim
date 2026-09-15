interface BackupVerificationInput {
  filename: string;
  verified: boolean;
  verification_error?: string | null;
  sha256: string | null;
  alembic_revision: string | null;
}

export interface BackupVerificationPresentation {
  kind: "verified" | "legacy" | "invalid";
  label: string;
  title: string;
  downloadAllowed: boolean;
}

interface BackupCreationAvailabilityInput {
  backupEnabled: boolean | undefined;
  isLoading: boolean;
  hasError: boolean;
}

export interface BackupCreationAvailability {
  kind: "loading" | "enabled" | "disabled" | "unavailable";
  createAllowed: boolean;
}

interface RestoreAvailabilityInput {
  restoreEligible: boolean;
  restoreEnabled: boolean | undefined;
  maintenanceMode: boolean | undefined;
  activeRestoreId: string | null | undefined;
  statusKnown: boolean;
}

export interface RestoreAvailability {
  kind: "enabled" | "unavailable" | "disabled" | "maintenance" | "active" | "ineligible";
  restoreAllowed: boolean;
}

const VERIFIED_FILENAME_PATTERN =
  /^pfim_backup_\d{8}_\d{6}_\d{6}_[0-9a-f]{8}\.db$/i;

/** Distinguishes a backend-declared block from unreadable status. Both
 * fail closed, but only the former means deployment disabled backups. */
export function describeBackupCreationAvailability({
  backupEnabled,
  isLoading,
  hasError,
}: BackupCreationAvailabilityInput): BackupCreationAvailability {
  if (hasError) {
    return { kind: "unavailable", createAllowed: false };
  }
  if (isLoading) {
    return { kind: "loading", createAllowed: false };
  }
  if (backupEnabled === undefined) {
    return { kind: "unavailable", createAllowed: false };
  }
  return backupEnabled
    ? { kind: "enabled", createAllowed: true }
    : { kind: "disabled", createAllowed: false };
}

/** The backend is authoritative; this function makes the UI fail closed. */
export function describeRestoreAvailability({
  restoreEligible,
  restoreEnabled,
  maintenanceMode,
  activeRestoreId,
  statusKnown,
}: RestoreAvailabilityInput): RestoreAvailability {
  if (!statusKnown || restoreEnabled === undefined || maintenanceMode === undefined) {
    return { kind: "unavailable", restoreAllowed: false };
  }
  if (maintenanceMode) {
    return { kind: "maintenance", restoreAllowed: false };
  }
  if (activeRestoreId) {
    return { kind: "active", restoreAllowed: false };
  }
  if (!restoreEnabled) {
    return { kind: "disabled", restoreAllowed: false };
  }
  if (!restoreEligible) {
    return { kind: "ineligible", restoreAllowed: false };
  }
  return { kind: "enabled", restoreAllowed: true };
}

export function restoreConfirmationPhrase(filename: string): string {
  return `RESTORE ${filename}`;
}

export function isRestoreConfirmationValid(value: string, filename: string): boolean {
  return value === restoreConfirmationPhrase(filename);
}

export function describeRestoreError(errorCode: string | null, fallback: string): string {
  switch (errorCode) {
    case "RESTORE_DISABLED":
      return "Restore is not enabled by the backend. Status has been refreshed.";
    case "BACKUP_VERIFICATION_FAILED":
      return "The backup no longer passes verification. The list has been refreshed: select it again.";
    case "BACKUP_TIMEOUT":
      return "The preliminary safety backup timed out: restore was not performed.";
    case "SCHEMA_REVISION_MISMATCH":
      return "The backup schema revision is incompatible with this build.";
    case "DATABASE_BUSY":
    case "DATABASE_LOCKED":
      return "The database is busy: restore did not start. Try again later.";
    case "MAINTENANCE_BUSY":
    case "MAINTENANCE_MODE":
    case "RESTORE_IN_PROGRESS":
      return "A maintenance operation is already running. Wait for it to complete.";
    default:
      return fallback;
  }
}

/** Legacy backups are downloadable but unverified. Modern backups
 * with invalid manifests or hashes are blocked. */
export function describeBackupVerification(
  backup: BackupVerificationInput
): BackupVerificationPresentation {
  if (backup.verified) {
    return {
      kind: "verified",
      label: `Verified · ${backup.alembic_revision ?? "unknown revision"}`,
      title: `Integrity verified with SHA-256 ${backup.sha256 ?? "—"}`,
      downloadAllowed: true,
    };
  }

  const verificationMessages: Record<string, string> = {
    manifest_missing: "Manifest unavailable.",
    manifest_invalid: "The manifest has an invalid format or fields.",
    hash_mismatch: "Backup contents do not match its SHA-256.",
    sidecars_present: "The backup contains SQLite sidecar files and is not self-contained.",
    backup_changed: "The backup changed during verification.",
  };
  if (
    VERIFIED_FILENAME_PATTERN.test(backup.filename) ||
    (backup.verification_error && backup.verification_error !== "manifest_missing")
  ) {
    return {
      kind: "invalid",
      label: "Unverified",
      title: backup.verification_error
        ? `${verificationMessages[backup.verification_error] ?? "Backup verification failed."} Download is blocked.`
        : "Modern backup with a missing/invalid manifest or hash mismatch: the backend blocks download.",
      downloadAllowed: false,
    };
  }

  return {
    kind: "legacy",
    label: "Legacy / unverified",
    title:
      "Backup in the previous format without PFIM verification metadata: integrity and schema revision cannot be verified automatically.",
    downloadAllowed: true,
  };
}
