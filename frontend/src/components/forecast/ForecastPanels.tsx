import type { ReactNode } from "react";

import type { ForecastBand, ForecastHorizon, ForecastPlan, ForecastView } from "@/lib/api/client";
import { formatUtc } from "@/lib/format";

import { atrDistance, floorTo, levelStyle, toSeconds, type Span } from "./geometry";
import { COLORS, formatNumber, planRoles, planState, type Layers } from "./overlay";

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded border border-line bg-panel p-3">
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{title}</h2>
      {children}
    </section>
  );
}

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function range(band: ForecastBand): string {
  return `${formatNumber(band.p10.toFixed(1))} – ${formatNumber(band.p90.toFixed(1))}`;
}

const LAYER_ITEMS: { key: keyof Layers; label: string; swatch: ReactNode }[] = [
  { key: "paths", label: "Kronos paths", swatch: <span className="h-0.5 w-4" style={{ background: COLORS.kronosPath }} /> },
  { key: "band", label: "Kronos 10–90%", swatch: <span className="h-3 w-4 rounded-sm border-t-2" style={{ background: COLORS.kronosFill, borderColor: COLORS.kronos }} /> },
  { key: "baseline", label: "Baseline 10–90%", swatch: <span className="h-3 w-4 rounded-sm border-t-2 border-dashed" style={{ background: COLORS.baselineFill, borderColor: COLORS.baseline }} /> },
  { key: "zones", label: "Python levels", swatch: <span className="h-0.5 w-4" style={{ background: COLORS.zone }} /> },
  { key: "plan", label: "Plan", swatch: <span className="h-3 w-4 rounded-sm" style={{ background: `linear-gradient(${COLORS.riskFill} 50%, ${COLORS.rewardFill} 50%)` }} /> },
  { key: "patterns", label: "Patterns", swatch: <span className="h-0.5 w-4" style={{ background: COLORS.pattern }} /> },
  { key: "signals", label: "Candle signals", swatch: <span className="text-[10px] leading-none text-down">▼</span> },
];

/** The legend doubles as the layer switches, so every colour on the chart is named. */
export function LayerToggles({ layers, onChange }: { layers: Layers; onChange: (layers: Layers) => void }) {
  return (
    <div role="group" aria-label="Chart layers" className="flex flex-wrap gap-1">
      {LAYER_ITEMS.map((item) => (
        <button
          key={item.key}
          type="button"
          aria-pressed={layers[item.key]}
          onClick={() => onChange({ ...layers, [item.key]: !layers[item.key] })}
          className={`flex min-h-8 cursor-pointer items-center gap-1.5 rounded border px-2 text-xs transition-colors duration-150 ${
            layers[item.key] ? "border-line bg-raised text-ink" : "border-line text-muted line-through opacity-60"
          }`}
        >
          {item.swatch}
          {item.label}
        </button>
      ))}
    </div>
  );
}

function signalName(type: string): string {
  const words = type.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function Arrow({ direction }: { direction: string }) {
  const bearish = direction === "bearish";
  return (
    <span className={bearish ? "text-down" : "text-up"} aria-label={bearish ? "bearish" : "bullish"}>
      {bearish ? "▼" : "▲"}
    </span>
  );
}

/** Values under the cursor: the forecast at that hour, or the candle signals on that bar. */
export function HoverReadout({
  view,
  hoverTime,
  span,
  barSeconds,
}: {
  view: ForecastView;
  hoverTime: number | null;
  span: Span;
  barSeconds: number;
}) {
  const horizon = view.horizons.find((h) => h.candles === span) ?? view.horizons[0];
  const signals =
    hoverTime === null
      ? []
      : view.candle_signals.filter((s) => floorTo(toSeconds(s.open_time), barSeconds) === hoverTime);
  const step =
    hoverTime === null
      ? undefined
      : view.steps
          .slice(0, span)
          .find((s) => Math.floor(Date.parse(s.open_time) / 3_600_000) === Math.floor(hoverTime / 3600));
  if (step) {
    return (
      <p className="text-xs">
        <span className="text-muted">{step.open_time.slice(11, 16)} UTC close · </span>
        <span style={{ color: COLORS.kronos }}>Kronos {formatNumber(step.model.p50.toFixed(1))}</span>
        <span className="text-muted"> ({range(step.model)}) · </span>
        <span className="text-muted">Baseline {formatNumber(step.baseline.p50.toFixed(1))} ({range(step.baseline)})</span>
      </p>
    );
  }
  if (signals.length > 0) {
    return (
      <p className="flex flex-wrap gap-x-2 text-xs">
        <span className="text-muted">{new Date(hoverTime! * 1000).toISOString().slice(11, 16)} UTC bar:</span>
        {signals.map((signal) => (
          <span key={signal.type}>
            <Arrow direction={signal.direction} /> {signalName(signal.type)}
          </span>
        ))}
      </p>
    );
  }
  if (!horizon) {
    return null;
  }
  return (
    <p className="text-xs">
      <span className="text-muted">Next {horizon.candles}h: </span>
      <span style={{ color: COLORS.kronos }}>Kronos {percent(horizon.model.share_ending_higher)} of paths end higher</span>
      <span className="text-muted"> · baseline {percent(horizon.baseline.share_ending_higher)}</span>
    </p>
  );
}

export function SummaryPanel({ horizon, lastClose, atr }: { horizon: ForecastHorizon; lastClose: number; atr: number }) {
  const rows: { label: string; model: string; baseline: string }[] = [
    { label: "Paths ending higher", model: percent(horizon.model.share_ending_higher), baseline: percent(horizon.baseline.share_ending_higher) },
    { label: "Close, middle", model: formatNumber(horizon.model.close.p50.toFixed(1)), baseline: formatNumber(horizon.baseline.close.p50.toFixed(1)) },
    { label: "Close, 10–90%", model: range(horizon.model.close), baseline: range(horizon.baseline.close) },
    { label: "Highest, middle", model: atrDistance(horizon.model.highest.p50, lastClose, atr), baseline: atrDistance(horizon.baseline.highest.p50, lastClose, atr) },
    { label: "Lowest, middle", model: atrDistance(horizon.model.lowest.p50, lastClose, atr), baseline: atrDistance(horizon.baseline.lowest.p50, lastClose, atr) },
  ];
  return (
    <Panel title={`Next ${horizon.candles} hours`}>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-muted">
            <th className="py-1 text-left font-normal" scope="col">Measure</th>
            <th className="py-1 text-right font-normal" scope="col" style={{ color: COLORS.kronos }}>Kronos</th>
            <th className="py-1 text-right font-normal" scope="col">Baseline</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label} className="border-t border-raised">
              <th className="py-1 text-left font-normal text-muted" scope="row">{row.label}</th>
              <td className="py-1 text-right">{row.model}</td>
              <td className="py-1 text-right text-muted">{row.baseline}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-muted">
        The baseline replays this coin&apos;s own last 60 days with no view on direction. Kronos says something only where it differs.
      </p>
    </Panel>
  );
}

export function TrackRecordPanel({ view }: { view: ForecastView }) {
  const record = view.track_record;
  const worse =
    record.brier_model !== null && record.brier_baseline !== null && record.brier_model > record.brier_baseline;
  return (
    <Panel title="Kronos track record">
      <p className="flex items-start gap-1.5 text-xs text-warn" role="status">
        <span aria-hidden="true">⚠</span>
        <span>
          Unvalidated model output: {record.status}, {record.resolved} resolved forecast{record.resolved === 1 ? "" : "s"}.
        </span>
      </p>
      {record.brier_model !== null && record.brier_baseline !== null ? (
        <p className="mt-1 text-xs text-muted">
          Direction score (Brier, lower is better): Kronos {record.brier_model.toFixed(3)}, baseline{" "}
          {record.brier_baseline.toFixed(3)}. {worse ? "The baseline has been better so far." : "Kronos has been better so far."}
        </p>
      ) : null}
      <p className="mt-1 text-xs text-muted">Not a price to trade, and never a win probability.</p>
    </Panel>
  );
}

function statusLine(plan: ForecastPlan): string {
  const status = plan.status;
  if (status.state === "closed") {
    const r = status.result_r === null ? "" : ` (${status.result_r >= 0 ? "+" : ""}${status.result_r.toFixed(2)}R)`;
    return `Closed by ${status.exit_reason}: ${status.net_pnl} USDT${r}`;
  }
  if (status.state === "open") {
    return `Filled at ${formatNumber(status.entry_price ?? "")} at ${status.entry_time?.slice(11, 16)} UTC`;
  }
  if (status.state === "not_filled") {
    return `Not filled: ${status.exit_reason}`;
  }
  return `Waiting for fill until ${plan.expires_at.slice(11, 16)} UTC`;
}

export function PlanPanel({ plan }: { plan: ForecastPlan }) {
  const rows: [string, string, string?][] = [
    ["Entry", `${plan.side === "SHORT" ? "Sell" : "Buy"} ${plan.entry_type.toLowerCase()} ${formatNumber(plan.entry)}`, plan.entry_level_id ?? undefined],
    ["Stop", formatNumber(plan.stop), plan.stop_level_id ? `beyond ${plan.stop_level_id}` : undefined],
    ...plan.targets.map((target, index): [string, string, string?] => [
      `Target ${index + 1}`,
      `${formatNumber(target)}${plan.reward_risk[index] ? ` · ${plan.reward_risk[index]}R` : ""}`,
      plan.target_level_ids[index],
    ]),
    ["Size", `${plan.quantity ?? "–"} · max loss ${plan.max_loss ?? "–"} USDT`],
    ["Grade", `${plan.grade} · risk engine ${plan.approved ? "approved" : `rejected (${plan.rejection_codes.join(", ")})`}`],
  ];
  return (
    <Panel title="Analyst plan">
      <p className="mb-2 rounded border border-line px-2 py-1 text-xs text-muted">
        {plan.source}. Paper only. Level IDs are from the {plan.as_of.slice(11, 16)} UTC catalogue.
      </p>
      <dl className="space-y-1 text-xs">
        {rows.map(([name, value, id]) => (
          <div key={name} className="flex justify-between gap-2">
            <dt className="text-muted">{name}</dt>
            <dd className="text-right">
              {value}
              {id ? <span className="ml-1 text-muted">{id}</span> : null}
            </dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 text-xs font-semibold" role="status">
        {planState(plan.status.state)} · {statusLine(plan)}
      </p>
      {plan.status.checked_until ? (
        <p className="text-xs text-muted">Checked on 15M candles up to {formatUtc(plan.status.checked_until)}</p>
      ) : (
        <p className="text-xs text-muted">No 15M candle after the plan is stored yet.</p>
      )}
      <details className="mt-2 text-xs">
        <summary className="cursor-pointer text-muted">Reasoning</summary>
        <p className="mt-1"><span className="text-up">For: </span>{plan.bull_case}</p>
        <p className="mt-1"><span className="text-down">Against: </span>{plan.bear_case}</p>
        <p className="mt-1"><span className="text-muted">Pre-mortem: </span>{plan.pre_mortem}</p>
      </details>
    </Panel>
  );
}

export function LevelsPanel({ view, span }: { view: ForecastView; span: Span }) {
  const roles = planRoles(view);
  const levels = [...view.levels].sort((a, b) => Number(b.price) - Number(a.price));
  return (
    <Panel title={`Python levels · reached within ${span}h`}>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-muted">
            <th className="py-1 text-left font-normal" scope="col">Level</th>
            <th className="py-1 text-right font-normal" scope="col">Price</th>
            <th className="py-1 text-right font-normal" scope="col" style={{ color: COLORS.kronos }}>Kronos</th>
            <th className="py-1 text-right font-normal" scope="col">Base</th>
          </tr>
        </thead>
        <tbody>
          {levels.map((level) => {
            const reach = level.reach.find((r) => r.candles === span) ?? level.reach[0];
            const role = roles.get(level.id);
            return (
              <tr key={level.id} className="border-t border-raised" title={level.evidence}>
                <th className="py-1 text-left font-normal" scope="row">
                  <span className={role ? "text-ink" : "text-muted"}>{level.id}</span>{" "}
                  <span className="text-muted">{levelStyle(level.kind).label}</span>
                  {role ? <span className="ml-1 rounded bg-raised px-1">{role}</span> : null}
                </th>
                <td className="py-1 text-right">
                  {formatNumber(level.price)}
                  <span className="block text-muted">{level.distance_atr >= 0 ? "+" : ""}{level.distance_atr.toFixed(2)} ATR</span>
                </td>
                <td className="py-1 text-right">{reach ? percent(reach.model) : "–"}</td>
                <td className="py-1 text-right text-muted">{reach ? percent(reach.baseline) : "–"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-muted">Shares of paths that touch each level, from each source&apos;s percentiles.</p>
    </Panel>
  );
}

export function ContextPanel({ view }: { view: ForecastView }) {
  const context = view.context;
  const chips: [string, string][] = [
    ["4H trend", context.trend_4h],
    ["1D trend", context.trend_1d],
    ["Regime", `${context.regime_trend}, ${context.regime_volatility}`],
    ["RSI 1H / 4H", `${context.rsi_1h ?? "–"} / ${context.rsi_4h ?? "–"}`],
  ];
  return (
    <Panel title="What Python sees">
      <dl className="grid grid-cols-2 gap-1 text-xs">
        {chips.map(([name, value]) => (
          <div key={name} className="rounded bg-raised px-2 py-1">
            <dt className="text-muted">{name}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <ul className="mt-2 space-y-1 text-xs">
        {context.strategies.map((strategy) => (
          <li key={strategy.name}>
            <span className="text-muted">{strategy.name}: </span>
            {strategy.action === "NO_TRADE" ? "no trade" : strategy.action}
            <span className="text-muted"> · {strategy.reasons.join("; ")}</span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

export function CandleSignalsPanel({ view }: { view: ForecastView }) {
  const signals = [...view.candle_signals].sort((a, b) => b.open_time.localeCompare(a.open_time));
  return (
    <Panel title="Candle signals · last 24h">
      {signals.length === 0 ? (
        <p className="text-xs text-muted">None in the last 24 hours.</p>
      ) : (
        <ul className="space-y-1 text-xs">
          {signals.map((signal) => (
            <li key={`${signal.type}:${signal.open_time}`} className="flex gap-2">
              <span className="w-20 shrink-0 text-muted">
                {signal.open_time.slice(5, 10)} {signal.open_time.slice(11, 16)}
              </span>
              <Arrow direction={signal.direction} />
              <span>{signalName(signal.type)}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-xs text-muted">A label means a written candle rule fired, nothing more.</p>
    </Panel>
  );
}
