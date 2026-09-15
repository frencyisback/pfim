import { useCallback, useState } from "react";

interface ConfirmState {
  message: string;
  onConfirm: () => void;
  confirmLabel: string;
}

/** Confirm destructive actions, such as deletion.
 * Usage: const { confirm, dialog } = useConfirmDialog();
 * confirm("Delete X?", () => mutate()); render {dialog} once. */
export function useConfirmDialog() {
  const [state, setState] = useState<ConfirmState | null>(null);

  const confirm = useCallback((message: string, onConfirm: () => void, confirmLabel = "Delete") => {
    setState({ message, onConfirm, confirmLabel });
  }, []);

  const dialog = state && (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="w-full max-w-sm rounded-lg bg-white p-5 shadow-xl">
        <p className="text-sm text-gray-700">{state.message}</p>
        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={() => setState(null)}
            className="rounded border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={() => {
              state.onConfirm();
              setState(null);
            }}
            className="rounded bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-700"
          >
            {state.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );

  return { confirm, dialog };
}
