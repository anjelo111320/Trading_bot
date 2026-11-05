import type { LivePrice } from "@/features/market/useLiveMarket";
import type { AnalysisJob } from "@/lib/api/client";
import type { ConnectionState } from "@/lib/ws/market-socket";

import { formatNumber } from "./overlay";

function clock(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/** What the latest re-analysis is doing, in words. Null when none has run. */
export function analysisText(job: AnalysisJob | undefined, now: number): string | null {
  if (!job || job.state === "idle") {
    return null;
  }
  const close = job.as_of ? `the ${job.as_of.slice(11, 16)} UTC close` : "the latest close";
  if (job.state === "running") {
    const started = job.started_at ? Date.parse(job.started_at) : now;
    const seconds = Math.max(0, Math.round((now - started) / 1000));
    return `Analysing ${job.symbol} from ${close} · ${clock(seconds)}, about 1:30 for Kronos`;
  }
  if (job.state === "failed") {
    return `Analysis failed: ${job.message ?? "unknown reason"}`;
  }
  return job.message ?? `Analysed ${job.symbol} from ${close}`;
}

export function ReanalyseButton({
  job,
  now,
  error,
  onClick,
}: {
  job: AnalysisJob | undefined;
  now: number;
  error: string | null;
  onClick: () => void;
}) {
  const running = job?.state === "running";
  const text = error ?? analysisText(job, now);
  const failed = Boolean(error) || job?.state === "failed";
  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {text ? (
        <span role="status" className={`text-xs ${failed ? "text-bad" : "text-muted"}`}>
          {text}
        </span>
      ) : null}
      <button
        type="button"
        onClick={onClick}
        disabled={running}
        aria-busy={running}
        title="Recompute Python's view and run a new Kronos forecast from the latest 1H close"
        className="min-h-9 cursor-pointer rounded border border-line bg-raised px-3 text-xs font-semibold text-ink transition-colors duration-150 hover:border-ink disabled:cursor-wait disabled:opacity-60"
      >
        {running ? "Analysing…" : "Re-analyse"}
      </button>
    </div>
  );
}

/** Whether the chart is streaming, and the live mid price when it is. */
export function LiveStatus({
  connection,
  price,
}: {
  connection: ConnectionState;
  price: LivePrice | null;
}) {
  const live = connection === "open";
  const mid = price ? (Number(price.bid) + Number(price.ask)) / 2 : null;
  return (
    <span className="flex items-center gap-1.5 text-xs" role="status">
      <span aria-hidden="true" className={live ? "text-good" : "text-warn"}>
        ●
      </span>
      <span className={live ? "text-ink" : "text-warn"}>{live ? "Live" : "Reconnecting…"}</span>
      {live && mid !== null ? <span className="text-muted">{formatNumber(mid.toFixed(2))}</span> : null}
    </span>
  );
}
