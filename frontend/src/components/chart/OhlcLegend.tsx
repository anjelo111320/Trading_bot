import { formatPrice } from "@/lib/format";

type Values = { open: string; high: string; low: string; close: string };

type Props = { values: Values | null; tickSize: string | null | undefined; forming: boolean };

/** Exact values as text, so direction never depends on colour alone. */
export function OhlcLegend({ values, tickSize, forming }: Props) {
  if (!values) {
    return <p className="text-xs text-muted">No candle data yet.</p>;
  }
  const change = Number(values.close) - Number(values.open);
  const rising = change >= 0;
  const percent = (change / Number(values.open)) * 100;
  return (
    <dl className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
      {(["open", "high", "low", "close"] as const).map((field) => (
        <div key={field} className="flex gap-1">
          <dt className="uppercase text-muted">{field[0]}</dt>
          <dd>{formatPrice(values[field], tickSize)}</dd>
        </div>
      ))}
      <div className={rising ? "text-up" : "text-down"}>
        <dt className="sr-only">Change</dt>
        <dd>
          {rising ? "▲ +" : "▼ "}
          {percent.toFixed(2)}%
        </dd>
      </div>
      {forming ? <span className="rounded border border-line px-1 text-muted">Forming</span> : null}
    </dl>
  );
}
