import { describe, expect, it, vi } from "vitest";
import type { ImportPreviewResult, ImportResult } from "@/api/importCsv";
import { createCsvImportSession, EMPTY_CSV_IMPORT_STATE } from "./csvImportSession";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function draft() {
  return {
    file: new File(["date;amount\n2026-09-01;100"], "account-a.csv"),
    accountId: 1,
    fxRate: "0.92",
    profile: {
      delimiter: ";", skip_rows: 0, date_format: "%Y-%m-%d", date_column: "date",
      description_column: "description", amount_column: "amount", category_column: "category",
      decimal_separator: ".", default_currency: "USD",
    },
  };
}

function previewResult(page = 1): ImportPreviewResult {
  return {
    rows: [], total_rows: 500, duplicate_rows: 0, error_rows: 0,
    page, page_size: 200, total_pages: 3,
  };
}

const imported: ImportResult = { imported: 500, skipped_duplicates: 0, errors: 0 };

function setup() {
  const api = {
    preview: vi.fn().mockResolvedValue(previewResult()),
    confirm: vi.fn().mockResolvedValue(imported),
    onImported: vi.fn(),
  };
  const onChange = vi.fn();
  return { api, onChange, session: createCsvImportSession(api, onChange) };
}

describe("CSV import session", () => {
  it("pagination and confirmation reuse the original snapshot if the draft changes during a request", async () => {
    const { api, session } = setup();
    const slow = deferred<ImportPreviewResult>();
    api.preview.mockReturnValueOnce(slow.promise).mockResolvedValueOnce(previewResult(2));
    const input = draft();
    const originalFile = input.file;
    const originalProfile = { ...input.profile };
    const request = session.preview(input);

    input.file = new File(["other content"], "account-b.csv");
    input.accountId = 2;
    input.fxRate = "0.75";
    input.profile.amount_column = "another_amount";
    input.profile.default_currency = "GBP";
    slow.resolve(previewResult());
    await request;
    await session.page(2);
    await session.confirm();

    expect(api.preview).toHaveBeenNthCalledWith(2, originalFile, originalProfile, 1, "0.92", 2, 200);
    expect(api.confirm).toHaveBeenCalledWith(originalFile, originalProfile, 1, "0.92");
    expect(api.preview.mock.calls[1][1]).toBe(api.preview.mock.calls[0][1]);
    expect(api.confirm.mock.calls[0][1]).toBe(api.preview.mock.calls[0][1]);
    expect(Object.isFrozen(session.getState().snapshot)).toBe(true);
    expect(Object.isFrozen(session.getState().snapshot?.profile)).toBe(true);
  });

  it.each(["success", "error"])("ignores a delayed stale preview: %s", async (outcome) => {
    const { api, session, onChange } = setup();
    const slow = deferred<ImportPreviewResult>();
    api.preview.mockReturnValueOnce(slow.promise);
    const first = session.preview(draft());
    const secondInput = { ...draft(), accountId: 2 };
    await session.preview(secondInput);
    const acceptedState = session.getState();
    onChange.mockClear();

    if (outcome === "success") slow.resolve({ ...previewResult(), duplicate_rows: 400 });
    else slow.reject(new Error("old file error"));
    await first;

    expect(session.getState()).toBe(acceptedState);
    expect(session.getState().snapshot?.accountId).toBe(2);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("changing data or going back revokes confirmation even if preview arrives later", async () => {
    const { api, session } = setup();
    const slow = deferred<ImportPreviewResult>();
    api.preview.mockReturnValueOnce(slow.promise);
    const request = session.preview(draft());
    session.invalidate();
    slow.resolve(previewResult());
    await request;
    await session.confirm();
    expect(session.getState()).toEqual(EMPTY_CSV_IMPORT_STATE);
    expect(api.confirm).not.toHaveBeenCalled();

    await session.preview(draft());
    session.invalidate();
    await session.confirm();
    expect(api.confirm).not.toHaveBeenCalled();
  });

  it("an earlier page cannot restore preview after the file changes", async () => {
    const { api, session } = setup();
    await session.preview(draft());
    const slow = deferred<ImportPreviewResult>();
    api.preview.mockReturnValueOnce(slow.promise);
    const page = session.page(2);
    await session.confirm();
    expect(api.confirm).not.toHaveBeenCalled();
    session.invalidate();
    await session.preview({ ...draft(), accountId: 7 });
    slow.resolve(previewResult(2));
    await page;
    expect(session.getState().preview?.page).toBe(1);
    await session.confirm();
    expect(api.confirm.mock.calls[0][2]).toBe(7);
  });

  it.each(["success", "error"])("a stale page cannot enable confirmation while a new page is pending: %s", async (outcome) => {
    const { api, session, onChange } = setup();
    await session.preview(draft());
    const older = deferred<ImportPreviewResult>();
    const newer = deferred<ImportPreviewResult>();
    api.preview.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
    const secondPage = session.page(2);
    const thirdPage = session.page(3);
    onChange.mockClear();

    if (outcome === "success") older.resolve(previewResult(2));
    else older.reject(new Error("stale page error"));
    await secondPage;

    expect(onChange).not.toHaveBeenCalled();
    expect(session.getState().pending).toBe("preview");
    await session.confirm();
    expect(api.confirm).not.toHaveBeenCalled();

    newer.resolve(previewResult(3));
    await thirdPage;
    expect(session.getState().preview?.page).toBe(3);
    expect(session.getState().error).toBeNull();
    await session.confirm();
    expect(api.confirm).toHaveBeenCalledOnce();
  });

  it("a double click sends one POST and successful confirmation cannot be repeated", async () => {
    const { api, session } = setup();
    await session.preview(draft());
    const slow = deferred<ImportResult>();
    api.confirm.mockReturnValueOnce(slow.promise);
    const first = session.confirm();
    const second = session.confirm();
    expect(api.confirm).toHaveBeenCalledOnce();
    expect(session.getState().pending).toBe("confirm");
    await session.preview({ ...draft(), accountId: 2 });
    expect(api.preview).toHaveBeenCalledOnce();
    slow.resolve(imported);
    await Promise.all([first, second]);
    await session.confirm();
    expect(api.confirm).toHaveBeenCalledOnce();
    expect(api.onImported).toHaveBeenCalledOnce();
    expect(session.getState().result).toEqual(imported);
  });

  it("closing or unmounting ignores late updates but refreshes cache after successful import", async () => {
    const { api, session, onChange } = setup();
    await session.preview(draft());
    const slow = deferred<ImportResult>();
    api.confirm.mockReturnValueOnce(slow.promise);
    const request = session.confirm();
    session.invalidate(false);
    onChange.mockClear();
    slow.resolve(imported);
    await request;
    expect(onChange).not.toHaveBeenCalled();
    expect(api.onImported).toHaveBeenCalledOnce();
    expect(session.getState()).toEqual(EMPTY_CSV_IMPORT_STATE);
  });

  it("does not confirm without preview or with invalid rows", async () => {
    const { api, session } = setup();
    await session.confirm();
    api.preview.mockResolvedValueOnce({ ...previewResult(), error_rows: 1 });
    await session.preview(draft());
    await session.confirm();
    expect(api.confirm).not.toHaveBeenCalled();
  });

  it("a confirmation error remains visible and permits another explicit action", async () => {
    const { api, session } = setup();
    await session.preview(draft());
    api.confirm.mockRejectedValueOnce(new Error("Import rejected"));
    await session.confirm();
    expect(session.getState().error).toBe("Import rejected");
    expect(session.getState().pending).toBeNull();
    expect(api.onImported).not.toHaveBeenCalled();
    await session.confirm();
    expect(api.confirm).toHaveBeenCalledTimes(2);
    expect(session.getState().error).toBeNull();
    expect(session.getState().result).toEqual(imported);
  });
});
