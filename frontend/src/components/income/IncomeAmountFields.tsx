import { formatEur, formatMoney } from "@/lib/formatters";
import { needsFxRate } from "@/lib/currency";
import { previewIncomeNet, type IncomePreviewInput } from "@/lib/incomePreview";

interface Props extends IncomePreviewInput {
  onGrossChange: (value: string) => void;
  onWithheldChange: (value: string) => void;
}

export default function IncomeAmountFields(props: Props) {
  const { currency, gross, withheld, onGrossChange, onWithheldChange } = props;
  const net = previewIncomeNet(props);

  return (
    <>
      <label className="flex flex-col gap-1 text-xs text-gray-500">
        Gross amount ({currency})
        <input
          type="number"
          step="0.01"
          className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
          value={gross}
          onChange={(event) => onGrossChange(event.target.value)}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-gray-500">
        Withholding ({currency})
        <input
          type="number"
          step="0.01"
          className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
          value={withheld}
          onChange={(event) => onWithheldChange(event.target.value)}
        />
      </label>
      <p className="col-span-full text-xs text-gray-500" role="status">
        {net === null ? (
          <>Net preview: enter valid gross and withholding amounts in the same currency.</>
        ) : (
          <>
            Net amount to credit (gross − withholding): <strong>{formatMoney(net.native, currency)}</strong>.
            {needsFxRate(currency) && (
              <> EUR value: {net.eur === null
                ? "— (enter a valid positive exchange rate)"
                : <strong>{formatEur(net.eur)}</strong>}.</>
            )}
          </>
        )}
      </p>
    </>
  );
}
