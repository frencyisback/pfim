import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { apiFetch } from "./client";

export interface BackupInfo {
  filename: string;
  size_bytes: number;
  created_at: string;
  verified: boolean;
  verification_error?: string | null;
  sha256: string | null;
  alembic_revision: string | null;
  manifest_filename: string | null;
  restore_eligible: boolean;
  restore_ineligible_reason: string | null;
}

export interface BackupStatus {
  backup_enabled: boolean;
  restore_enabled: boolean;
  expected_alembic_revision: string;
  maintenance_mode: boolean;
  restore_state: string;
  active_restore_id: string | null;
}

export interface RestoreBackupRequest {
  filename: string;
  request_id: string;
  expected_sha256: string;
  confirmation: string;
}

export interface RestoreOperation {
  operation_id: string;
  state: string;
  restored: boolean;
  restored_backup: string | null;
  expected_sha256: string;
  pre_restore_backup: string | null;
  alembic_revision: string | null;
  started_at: string | null;
  completed_at: string | null;
  requires_reload: boolean;
  error_code: string | null;
  message: string | null;
}

export function useBackups() {
  return useQuery({
    queryKey: ["backups"],
    queryFn: () => apiFetch<BackupInfo[]>("/backup"),
  });
}

export function useBackupStatus() {
  return useQuery({
    queryKey: ["backup-status"],
    queryFn: () => apiFetch<BackupStatus>("/backup/status"),
  });
}

export function useCreateBackup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<BackupInfo>("/backup", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["backups"] }),
  });
}

export function isRestoreOperationTerminal(operation: RestoreOperation): boolean {
  if (operation.restored) return true;
  return ["completed", "failed", "cancelled", "rolled_back"].includes(
    operation.state.toLowerCase()
  );
}

export async function restoreBackup(request: RestoreBackupRequest): Promise<RestoreOperation> {
  const { filename, ...body } = request;
  return apiFetch<RestoreOperation>(`/backup/${encodeURIComponent(filename)}/restore`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function getRestoreOperation(operationId: string): Promise<RestoreOperation> {
  return apiFetch<RestoreOperation>(
    `/backup/restore-operations/${encodeURIComponent(operationId)}`
  );
}

export async function invalidateAfterRestore(
  queryClient: Pick<QueryClient, "invalidateQueries">
): Promise<void> {
  await queryClient.invalidateQueries();
}

export function useRestoreBackup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: restoreBackup,
    retry: false,
    onSuccess: () => invalidateAfterRestore(qc),
  });
}

export function useRestoreOperation(operationId: string | null, enabled = true) {
  return useQuery({
    queryKey: ["backup-restore-operation", operationId],
    queryFn: () => getRestoreOperation(operationId!),
    enabled: enabled && operationId !== null,
    retry: false,
    refetchInterval: (query) => {
      const operation = query.state.data;
      return operation && isRestoreOperationTerminal(operation) ? false : 1_000;
    },
  });
}

export function backupDownloadUrl(filename: string): string {
  const base = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
  return `${base}/backup/${filename}/download`;
}

export function backupManifestDownloadUrl(filename: string): string {
  const base = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
  return `${base}/backup/${filename}/manifest`;
}
