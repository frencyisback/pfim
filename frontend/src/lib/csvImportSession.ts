import type { CsvProfile, ImportPreviewResult, ImportResult } from "@/api/importCsv";
import { createLatestRequestGate } from "./latestRequest";

export interface CsvImportSnapshot {
  readonly file: File;
  readonly profile: Readonly<CsvProfile>;
  readonly accountId: number;
  readonly fxRate: string;
}

export interface CsvImportState {
  snapshot: CsvImportSnapshot | null;
  preview: ImportPreviewResult | null;
  result: ImportResult | null;
  pending: "preview" | "confirm" | null;
  error: string | null;
}

export const EMPTY_CSV_IMPORT_STATE: CsvImportState = {
  snapshot: null,
  preview: null,
  result: null,
  pending: null,
  error: null,
};

interface CsvImportApi {
  preview: (
    file: File, profile: CsvProfile, accountId: number, fxRate: string,
    page: number, pageSize?: number
  ) => Promise<ImportPreviewResult>;
  confirm: (
    file: File, profile: CsvProfile, accountId: number, fxRate: string
  ) => Promise<ImportResult>;
  onImported: () => void;
}

/** Confirmation and pagination reuse preview inputs. The gate ignores
 * stale responses after input changes, back navigation or closing.
 * Pending updates before React renders, preventing duplicate POSTs. */
export function createCsvImportSession(
  api: CsvImportApi,
  onChange: (state: CsvImportState) => void
) {
  const gate = createLatestRequestGate();
  let state: CsvImportState = { ...EMPTY_CSV_IMPORT_STATE };

  function update(patch: Partial<CsvImportState>) {
    state = { ...state, ...patch };
    onChange(state);
  }

  async function loadPreview(snapshot: CsvImportSnapshot, page: number, pageSize?: number) {
    const requestId = gate.begin();
    update({ pending: "preview", error: null });
    try {
      const preview = await api.preview(
        snapshot.file, snapshot.profile, snapshot.accountId, snapshot.fxRate, page, pageSize
      );
      if (gate.isCurrent(requestId)) update({ preview, pending: null });
    } catch (error) {
      if (gate.isCurrent(requestId)) {
        update({ error: error instanceof Error ? error.message : "Unknown error", pending: null });
      }
    }
  }

  return {
    getState: () => state,
    invalidate(notify = true) {
      gate.invalidate();
      state = { ...EMPTY_CSV_IMPORT_STATE };
      if (notify) onChange(state);
    },
    async preview(input: CsvImportSnapshot) {
      if (state.pending === "confirm") return;
      const snapshot: CsvImportSnapshot = Object.freeze({
        ...input,
        profile: Object.freeze({ ...input.profile }),
      });
      update({ snapshot, preview: null, result: null });
      await loadPreview(snapshot, 1);
    },
    async page(page: number) {
      if (
        !state.snapshot || !state.preview || state.pending === "confirm" || state.result ||
        page < 1 || page > state.preview.total_pages
      ) return;
      await loadPreview(state.snapshot, page, state.preview.page_size);
    },
    async confirm() {
      if (!state.snapshot || !state.preview || state.pending || state.result || state.preview.error_rows > 0) return;
      const snapshot = state.snapshot;
      const requestId = gate.begin();
      update({ pending: "confirm", error: null });
      try {
        const result = await api.confirm(
          snapshot.file, snapshot.profile, snapshot.accountId, snapshot.fxRate
        );
        // A successful write must refresh shared data even after unmounting;
        // only the wizard's local state has expired.
        api.onImported();
        if (gate.isCurrent(requestId)) update({ result, pending: null });
      } catch (error) {
        if (gate.isCurrent(requestId)) {
          update({ error: error instanceof Error ? error.message : "Unknown error", pending: null });
        }
      }
    },
  };
}
