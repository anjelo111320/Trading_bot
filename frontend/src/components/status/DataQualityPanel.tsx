import type { FeedStatus } from "@/lib/api/client";
import { formatAge } from "@/lib/format";

const STATE_STYLE: Record<FeedStatus["state"], string> = {
  HEALTHY: "text-good",
  DEGRADED: "text-warn",
  RECOVERING: "text-warn",
  STALE: "text-bad",
  DISCONNECTED: "text-bad",
};

const FEED_NAME: Record<string, string> = {
  binance_spot: "Binance Spot",
  binance_usdm: "Binance USD-M",
  synthetic: "Synthetic",
};

function Feed({ feed }: { feed: FeedStatus }) {
  return (
    <li className="border-t border-line py-2 first:border-t-0 first:pt-0">
      <div className="flex items-center justify-between text-sm">
        <span>{FEED_NAME[feed.provider] ?? feed.provider}</span>
        <span className={`font-semibold ${STATE_STYLE[feed.state]}`}>{feed.state}</span>
      </div>
      <dl className="mt-1 grid grid-cols-2 gap-x-2 text-xs text-muted">
        <dt>Data age</dt>
        <dd className="text-right">{formatAge(feed.lag_seconds)}</dd>
        <dt>Open gaps</dt>
        <dd className="text-right">{feed.open_gaps}</dd>
        <dt>Clock skew</dt>
        <dd className="text-right">
          {feed.clock_skew_ms === null ? "unknown" : `${feed.clock_skew_ms.toFixed(0)} ms`}
        </dd>
      </dl>
      {feed.reasons.length > 0 ? (
        <ul className="mt-1 space-y-0.5 text-xs text-warn">
          {feed.reasons.slice(0, 3).map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
          {feed.reasons.length > 3 ? <li>and {feed.reasons.length - 3} more</li> : null}
        </ul>
      ) : null}
    </li>
  );
}

export function DataQualityPanel({ feeds }: { feeds: FeedStatus[] | undefined }) {
  return (
    <section aria-label="Data quality" className="rounded border border-line bg-panel p-3">
      <h2 className="mb-2 text-sm font-semibold">Data quality</h2>
      {feeds ? (
        <ul>
          {feeds.map((feed) => (
            <Feed key={feed.provider} feed={feed} />
          ))}
        </ul>
      ) : (
        <p role="alert" className="text-sm text-bad">
          Status is unavailable.
        </p>
      )}
    </section>
  );
}
