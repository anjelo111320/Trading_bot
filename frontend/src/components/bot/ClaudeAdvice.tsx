/**
 * Claude's exit advice on open paper trades, in shadow mode (D051): recorded, and scored when
 * the trade closes, but never acted on. The page only reads what the quant worker stored.
 */

import type { ExitReview, ExitReviews } from "@/lib/api/client";
import { formatUtc } from "@/lib/format";

import { Stat, tone } from "./BotPanels";

const ACTION_LABEL: Record<string, string> = {
  hold: "Hold",
  take_profit_now: "Take the profit now",
  stop_to_breakeven: "Stop to breakeven",
};

const STATUS_LABEL: Record<string, string> = {
  not_asked: "Not asked: no API key yet",
  skipped_budget: "Not asked: the daily budget is used",
  invalid: "Answer rejected: not in the required form",
  refused: "Claude declined to answer",
  error: "The call failed",
};

const ASKED = ["advised", "invalid", "refused"];

export function adviceLabel(review: ExitReview): string {
  if (review.status === "advised" && review.action) return ACTION_LABEL[review.action] ?? review.action;
  return STATUS_LABEL[review.status] ?? review.status;
}

/** The R the advice would have added, once the trade has finished. */
export function scoreOf(review: ExitReview): number | null {
  if (review.own_r === null || review.advised_r === null) return null;
  return Number(review.advised_r) - Number(review.own_r);
}

function r(value: number | string): string {
  const number = Number(value);
  return `${number >= 0 ? "+" : ""}${number.toFixed(2)}R`;
}

function Review({ review, current }: { review: ExitReview; current: boolean }) {
  const score = scoreOf(review);
  return (
    <li className={`border-t border-line py-2 text-sm ${current ? "" : "opacity-80"}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-2 text-xs text-muted">
        <span>
          {formatUtc(review.close_time)} · {review.symbol} · {review.account}
        </span>
        <span>{review.strategy}</span>
      </div>
      <p className="mt-0.5">
        <span className="font-semibold">{adviceLabel(review)}</span>
        <span className="text-muted"> at {r(review.progress_r)}</span>
      </p>
      <p className="text-xs text-muted">Check: {review.checks.join(", ")}</p>
      {review.reason ? <p className="mt-0.5 text-xs">{review.reason}</p> : null}
      {score !== null ? (
        <p className={`mt-0.5 text-xs ${tone(score)}`}>
          Scored: the trade made {r(review.own_r!)}, with this advice {r(review.advised_r!)} ({r(score)})
        </p>
      ) : review.status === "advised" ? (
        <p className="mt-0.5 text-xs text-muted">Scored when the trade closes.</p>
      ) : null}
    </li>
  );
}

export function ClaudeAdvice({ data, symbol }: { data: ExitReviews | undefined; symbol: string }) {
  const statuses = data?.statuses ?? {};
  const checks = Object.values(statuses).reduce((sum, count) => sum + count, 0);
  const asked = ASKED.reduce((sum, status) => sum + (statuses[status] ?? 0), 0);
  const change = data?.mean_change_r === null || data?.mean_change_r === undefined ? null : Number(data.mean_change_r);
  const reviews = [...(data?.reviews ?? [])].sort(
    (a, b) => Number(b.symbol === symbol) - Number(a.symbol === symbol),
  );
  return (
    <section aria-label="Claude's exit advice" className="rounded border border-line bg-panel p-3">
      <h2 className="mb-1 text-sm font-semibold">Claude&apos;s exit advice</h2>
      <p role="note" className="mb-2 text-xs text-warn">
        Shadow mode: the advice is recorded, and scored when the trade closes. It never changes a trade.
      </p>
      {data && !data.asking ? (
        <p className="mb-2 text-xs text-muted">
          No Anthropic API key yet, so Claude is not asked. Python still records every check, which counts them
          for free.
        </p>
      ) : null}
      <dl className="grid grid-cols-2 gap-3">
        <Stat label="Checks recorded" value={String(checks)} />
        <Stat label="Asked Claude" value={String(asked)} />
        <Stat label="Cost so far" value={`$${data?.cost_usd ?? "0"}`} />
        <Stat label="Scored, not hold" value={`${data?.scored_not_hold ?? 0} of ${data?.scored ?? 0}`} />
        <Stat
          label="Mean change, not hold"
          value={change === null ? "–" : r(change)}
          className={change === null ? "" : tone(change)}
        />
        <Stat label="Model" value={data?.model ?? "–"} />
      </dl>
      <p className="mt-2 text-xs text-muted">
        Python asks only when a check fires: a stall past +1R, a rejection near a target, or a volatility jump. Hold is
        the default, and a fixed rule that took profit early lost R in backtests (docs/37). A score is not a win
        probability.
      </p>
      {reviews.length ? (
        <ul className="mt-2">
          {reviews.slice(0, 12).map((review) => (
            <Review
              key={`${review.close_time}:${review.symbol}:${review.account}`}
              review={review}
              current={review.symbol === symbol}
            />
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-muted">No check has fired yet. Python looks at each open paper trade at every 15M close.</p>
      )}
    </section>
  );
}
