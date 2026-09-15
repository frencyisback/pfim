import { describe, expect, it } from "vitest";

import {
  describeBackupCreationAvailability,
  describeBackupVerification,
  describeRestoreAvailability,
  describeRestoreError,
  isRestoreConfirmationValid,
  restoreConfirmationPhrase,
} from "./backup";

describe("backup creation availability", () => {
  it("enables creation only after a successful status response", () => {
    expect(
      describeBackupCreationAvailability({
        backupEnabled: true,
        isLoading: false,
        hasError: false,
      })
    ).toEqual({ kind: "enabled", createAllowed: true });
  });

  it("distinguishes disabling declared by the backend", () => {
    expect(
      describeBackupCreationAvailability({
        backupEnabled: false,
        isLoading: false,
        hasError: false,
      })
    ).toEqual({ kind: "disabled", createAllowed: false });
  });

  it("keeps creation blocked while loading", () => {
    expect(
      describeBackupCreationAvailability({
        backupEnabled: undefined,
        isLoading: true,
        hasError: false,
      })
    ).toEqual({ kind: "loading", createAllowed: false });
  });

  it("reports a failed status as unavailable rather than disabled", () => {
    expect(
      describeBackupCreationAvailability({
        backupEnabled: undefined,
        isLoading: false,
        hasError: true,
      })
    ).toEqual({ kind: "unavailable", createAllowed: false });
  });

  it("fails closed when status is missing without an explicit error", () => {
    expect(
      describeBackupCreationAvailability({
        backupEnabled: undefined,
        isLoading: false,
        hasError: false,
      })
    ).toEqual({ kind: "unavailable", createAllowed: false });
  });
});

describe("restore availability", () => {
  const enabledInput = {
    restoreEligible: true,
    restoreEnabled: true,
    maintenanceMode: false,
    activeRestoreId: null,
    statusKnown: true,
  };

  it("enables only an eligible candidate with an available backend", () => {
    expect(describeRestoreAvailability(enabledInput)).toEqual({
      kind: "enabled",
      restoreAllowed: true,
    });
  });

  it("blocks a backup declared ineligible by the backend", () => {
    expect(
      describeRestoreAvailability({ ...enabledInput, restoreEligible: false })
    ).toEqual({ kind: "ineligible", restoreAllowed: false });
  });

  it("blocks during maintenance or another active operation", () => {
    expect(
      describeRestoreAvailability({ ...enabledInput, maintenanceMode: true })
    ).toEqual({ kind: "maintenance", restoreAllowed: false });
    expect(
      describeRestoreAvailability({ ...enabledInput, activeRestoreId: "restore-1" })
    ).toEqual({ kind: "active", restoreAllowed: false });
  });

  it("fails closed when status is absent or restore is disabled", () => {
    expect(describeRestoreAvailability({ ...enabledInput, statusKnown: false })).toEqual({
      kind: "unavailable",
      restoreAllowed: false,
    });
    expect(describeRestoreAvailability({ ...enabledInput, restoreEnabled: false })).toEqual({
      kind: "disabled",
      restoreAllowed: false,
    });
  });
});

describe("restore confirmation and errors", () => {
  const filename = "pfim_backup_20260829_090000_123456_deadbeef.db";

  it("requires the exact phrase without permissive normalisation", () => {
    const phrase = restoreConfirmationPhrase(filename);
    expect(phrase).toBe(`RESTORE ${filename}`);
    expect(isRestoreConfirmationValid(phrase, filename)).toBe(true);
    expect(isRestoreConfirmationValid(phrase.toLowerCase(), filename)).toBe(false);
    expect(isRestoreConfirmationValid(` ${phrase}`, filename)).toBe(false);
  });

  it("specifically presents verification failure and database busy errors", () => {
    expect(describeRestoreError("BACKUP_VERIFICATION_FAILED", "fallback")).toContain(
      "no longer passes verification"
    );
    expect(describeRestoreError("DATABASE_BUSY", "fallback")).toContain("database is busy");
    expect(describeRestoreError("UNKNOWN", "fallback")).toBe("fallback");
  });
});

describe("backup verification status", () => {
  it.each(["manifest_invalid", "hash_mismatch", "sidecars_present", "backup_changed"])(
    "blocks a legacy name when the backend reports %s", (verification_error) => {
      const result = describeBackupVerification({
        filename: "pfim_backup_20260818_091627.db", verified: false,
        sha256: null, alembic_revision: null, verification_error,
      });
      expect(result.kind).toBe("invalid");
      expect(result.downloadAllowed).toBe(false);
      expect(result.title).toContain("blocked");
    }
  );

  it("preserves downloads for legacy files genuinely lacking a manifest", () => {
    expect(describeBackupVerification({
      filename: "pfim_backup_20260818_091627.db", verified: false,
      sha256: null, alembic_revision: null, verification_error: "manifest_missing",
    }).downloadAllowed).toBe(true);
  });
  it("exposes revision and hash for a verified backup", () => {
    const presentation = describeBackupVerification({
      filename: "pfim_backup_20260818_091627_123456_deadbeef.db",
      verified: true,
      sha256: "abc123",
      alembic_revision: "e7b3c9a5d1f4",
    });

    expect(presentation.kind).toBe("verified");
    expect(presentation.label).toContain("e7b3c9a5d1f4");
    expect(presentation.title).toContain("abc123");
    expect(presentation.downloadAllowed).toBe(true);
  });

  it("distinguishes the unverified legacy format", () => {
    const presentation = describeBackupVerification({
      filename: "pfim_backup_20260818_091627.db",
      verified: false,
      sha256: null,
      alembic_revision: null,
    });

    expect(presentation.kind).toBe("legacy");
    expect(presentation.title).toContain("previous format");
    expect(presentation.downloadAllowed).toBe(true);
  });

  it("blocks downloads in the UI for modern backups that fail verification", () => {
    const presentation = describeBackupVerification({
      filename: "pfim_backup_20260818_091627_123456_deadbeef.db",
      verified: false,
      sha256: null,
      alembic_revision: null,
    });

    expect(presentation.kind).toBe("invalid");
    expect(presentation.title).toContain("hash mismatch");
    expect(presentation.downloadAllowed).toBe(false);
  });
});
