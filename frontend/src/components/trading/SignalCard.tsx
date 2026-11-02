import type { Signal } from "@/lib/api/client";
import { formatUtc } from "@/lib/format";

function Row({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-muted">{label}</dt>
      <dd className="text-right">{value ?? "Not available"}</dd>
    </div>
  );
}

function round(value: string | null | undefined, digits = 2): string | null {
  return value ? Number(value).toFixed(digits) : null;
}

const ACTION_LABEL: Record<string, string> = {
  BUY: "BUY",
  SELL: "SELL",
  WAIT: "WAIT",
  NO_TRADE: "NO TRADE",
};

/** Quality, news, data and probability stay separate. None of them is a win chance. */
export function SignalCard({ signal }: { signal: Signal }) {
  const rejected = signal.decision === "REJECTED";
  const tone = signal.action === "BUY" ? "text-up" : "text-down";
  return (
    <article className="rounded border border-line bg-panel p-4">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h2 className={`text-base font-semibold ${tone}`}>
          {signal.action === "BUY" ? "▲ " : "▼ "}
          {ACTION_LABEL[signal.action] ?? signal.action} on {signal.provider}, instrument{" "}
          {signal.instrument_id}
        </h2>
        <span className="rounded border border-line px-2 py-0.5 text-xs">{signal.state}</span>
      </header>

      {rejected ? (
        <p role="status" className="mt-2 text-sm text-warn">
          Rejected by the risk engine: {signal.rejection_codes.join(", ")}
        </p>
      ) : null}

      <div className="mt-3 grid gap-4 text-sm md:grid-cols-2">
        <dl className="space-y-1">
          <Row label="Entry" value={`${signal.entry_type ?? ""} ${signal.entry_price ?? ""}`} />
          <Row label="Stop-loss" value={signal.stop_loss} />
          {signal.targets.map((target, index) => (
            <Row
              key={target.price}
              label={`Take-profit ${index + 1}`}
              value={`${target.price} (net ${round(target.net_reward_risk)}R)`}
            />
          ))}
          {signal.targets.length === 0 ? <Row label="Take-profit" value={null} /> : null}
          <Row label="Net reward/risk" value={round(signal.reward_risk_net)} />
        </dl>
        <dl className="space-y-1">
          <Row label="Position size" value={signal.quantity} />
          <Row label="Maximum account risk" value={round(signal.max_account_risk)} />
          <Row label="Estimated fees per unit" value={round(signal.estimated_fees, 4)} />
          <Row label="Technical setup quality" value={`${round(signal.setup_quality_score, 0)} / 100`} />
          <Row label="News alignment" value={signal.news_alignment} />
          <Row label="Data reliability" value={`${round(signal.data_reliability_score, 0)} / 100`} />
          <Row
            label="Probability of success"
            value={signal.probability_status === "calibrated" ? "Calibrated" : "Unavailable"}
          />
        </dl>
      </div>

      <p className="mt-3 text-sm">{signal.technical_explanation}</p>
      <p className="mt-1 text-sm text-muted">{signal.fundamental_explanation}</p>
      <p className="mt-2 text-sm">
        <span className="text-muted">Invalidation: </span>
        {signal.invalidation_conditions.map(String).join("; ")}
      </p>
      <p className="mt-2 text-xs text-muted">
        Created {formatUtc(signal.created_at)}. Expires {formatUtc(signal.expires_at)}.
      </p>
    </article>
  );
}
