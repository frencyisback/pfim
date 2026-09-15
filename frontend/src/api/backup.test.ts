import type { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

const completedOperation = {
  operation_id: "restore-request-1",
  state: "completed",
  restored: true,
  restored_backup: "pfim_backup_20260829_090000_123456_deadbeef.db",
  expected_sha256: "a".repeat(64),
  pre_restore_backup: "pfim_backup_20260829_100000_123456_cafebabe.db",
  alembic_revision: "revision-1",
  started_at: "2026-08-29T09:00:00Z",
  completed_at: "2026-08-29T09:00:02Z",
  requires_reload: true,
  error_code: null,
  message: "Restore completed",
};

describe("backup restore API", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
  });

  it("sends request id, hash and confirmation with a capability token", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ token: "secret-token", header_name: "X-PFIM-Capability" })
      )
      .mockResolvedValueOnce(jsonResponse(completedOperation));
    vi.stubGlobal("fetch", fetchMock);
    const { restoreBackup } = await import("./backup");
    const filename = completedOperation.restored_backup;

    await expect(
      restoreBackup({
        filename,
        request_id: "restore-request-1",
        expected_sha256: completedOperation.expected_sha256,
        confirmation: `RESTORE ${filename}`,
      })
    ).resolves.toEqual(completedOperation);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][0]).toContain(`/backup/${filename}/restore`);
    const request = fetchMock.mock.calls[1][1] as RequestInit;
    expect(request.method).toBe("POST");
    expect(new Headers(request.headers).get("X-PFIM-Capability")).toBe("secret-token");
    expect(JSON.parse(String(request.body))).toEqual({
      request_id: "restore-request-1",
      expected_sha256: completedOperation.expected_sha256,
      confirmation: `RESTORE ${filename}`,
    });
  });

  it("does not automatically retry an application restore rejection", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ token: "secret-token", header_name: "X-PFIM-Capability" })
      )
      .mockResolvedValueOnce(
        jsonResponse(
          { error_code: "MAINTENANCE_BUSY", message: "maintenance already active", detail: {} },
          { status: 503 }
        )
      );
    vi.stubGlobal("fetch", fetchMock);
    const { restoreBackup } = await import("./backup");

    await expect(
      restoreBackup({
        filename: completedOperation.restored_backup,
        request_id: "restore-request-2",
        expected_sha256: completedOperation.expected_sha256,
        confirmation: `RESTORE ${completedOperation.restored_backup}`,
      })
    ).rejects.toMatchObject({ status: 503, errorCode: "MAINTENANCE_BUSY" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("queries operation status without a capability token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(completedOperation));
    vi.stubGlobal("fetch", fetchMock);
    const { getRestoreOperation, isRestoreOperationTerminal } = await import("./backup");

    await expect(getRestoreOperation("restore-request-1")).resolves.toEqual(completedOperation);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain(
      "/backup/restore-operations/restore-request-1"
    );
    expect(isRestoreOperationTerminal(completedOperation)).toBe(true);
  });

  it("invalidates the entire cache after a restore", async () => {
    const invalidateQueries = vi.fn().mockResolvedValue(undefined);
    const queryClient = { invalidateQueries } as unknown as Pick<
      QueryClient,
      "invalidateQueries"
    >;
    const { invalidateAfterRestore } = await import("./backup");

    await invalidateAfterRestore(queryClient);

    expect(invalidateQueries).toHaveBeenCalledOnce();
    expect(invalidateQueries).toHaveBeenCalledWith();
  });
});
