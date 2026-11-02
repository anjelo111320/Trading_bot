import type { LivePrice } from "@/features/market/useLiveMarket";
import { formatAge, formatPrice, formatUtc } from "@/lib/format";

export const STALE_PRICE_MS = 5_000;

type Props = {
  price: LivePrice | null;
  tickSize: string | null | undefined;
  now: number;
  isCurrentFeed: boolean;
};

export function isPriceCurrent(price: LivePrice | null, now: number, feedOk: boolean): boolean {
  return Boolean(price) && feedOk && now - Date.parse(price!.receivedAt) <= STALE_PRICE_MS;
}

/** A price older than five seconds stops looking like a live price. */
export function PricePanel({ price, tickSize, now, isCurrentFeed }: Props) {
  if (!price) {
    return (
      <section aria-label="Live price" className="rounded border border-line bg-panel p-3">
        <p className="text-sm text-muted">No live price.</p>
      </section>
    );
  }
  const current = isPriceCurrent(price, now, isCurrentFeed);
  const age = (now - Date.parse(price.receivedAt)) / 1000;
  const tone = current ? "text-ink" : "text-muted line-through";
  return (
    <section aria-label="Live price" className="rounded border border-line bg-panel p-3">
      <dl className="grid grid-cols-2 gap-2">
        <div>
          <dt className="text-xs text-muted">Bid</dt>
          <dd className={`text-lg font-semibold ${tone}`}>{formatPrice(price.bid, tickSize)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Ask</dt>
          <dd className={`text-lg font-semibold ${tone}`}>{formatPrice(price.ask, tickSize)}</dd>
        </div>
      </dl>
      <p className={`mt-2 text-xs ${current ? "text-muted" : "font-semibold text-warn"}`}>
        {current ? "Live" : "NOT CURRENT"}, age {formatAge(Math.max(age, 0))}
      </p>
      <p className="text-xs text-muted">{formatUtc(price.receivedAt)}</p>
    </section>
  );
}
