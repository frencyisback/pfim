import { describeTaxEvent, type TaxEventIdentity } from "@/lib/taxEventPresentation";

interface Props {
  event: TaxEventIdentity;
  pending: boolean;
  onDelete: () => void;
  onUnlink: () => void;
}

export default function TaxEventActions({ event, pending, onDelete, onUnlink }: Props) {
  const presentation = describeTaxEvent(event);
  if (!presentation.editable) {
    return (
      <span className="text-xs text-gray-400">
        {presentation.sourceManaged
          ? `Managed in Securities${event.related_trade_id === null ? "" : ` · trade #${event.related_trade_id}`}`
          : "Verify the entry's origin"}
      </span>
    );
  }
  return (
    <span className="inline-flex gap-3">
      {presentation.canUnlink && (
        <button disabled={pending} onClick={onUnlink} className="text-xs text-gray-500 hover:text-gray-900 disabled:opacity-50">
          Unlink source
        </button>
      )}
      <button disabled={pending} onClick={onDelete} className="text-xs text-gray-400 hover:text-red-600 disabled:opacity-50">
        Delete
      </button>
    </span>
  );
}
