import type { ReactNode } from "react";

import type { ForecastBand, ForecastPlan, ForecastProposal, ForecastStrategy, ForecastView } from "@/lib/api/client";
import { formatUtc } from "@/lib/format";

import { atrDistance, floorTo, hoursBetween, levelStyle, toSeconds, type Span } from "./geometry";
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

function horizonOf<T extends { candles: number }>(items: T[], span: Span): T | undefined {
  return items.find((item) => item.candles === span) ?? items[0];
}

/** How long ago Kronos last ran, counted from the latest close. */
function kronosAge(view: ForecastView): string {
  return view.kronos ? `${hoursBetween(view.kronos.as_of, view.analysis_as_of)}h` : "";
}

/** Python's prices for a signal, in words. */
export function proposalText(proposal: ForecastProposal): string {
  const side = proposal.side === "SHORT" ? "Sell" : "Buy";
  const how = proposal.entry_type ? ` ${proposal.entry_type.toLowerCase()}` : "";
  const targets = proposal.targets.map(formatNumber).join(" / ");
  return `${side}${how} ${formatNumber(proposal.entry)} · stop ${formatNumber(proposal.stop)} · target${proposal.targets.length > 1 ? "s" : ""} ${targets}`;
}

function hasSignal(strategies: ForecastStrategy[]): boolean {
  return strategies.some((strategy) => strategy.action !== "NO_TRADE");
}

function StrategyList({ strategies }: { strategies: ForecastStrategy[] }) {
  return (
    <ul className="space-y-1 text-xs">
      {strategies.map((strategy) => (
        <li key={strategy.name}>
          <span className="text-muted">{strategy.name}: </span>
          <span className={strategy.action === "NO_TRADE" ? "" : "font-semibold"}>
            {strategy.action === "NO_TRADE" ? "no trade" : strategy.action}
          </span>
          <span className="text-muted"> · {strategy.reasons.join("; ")}</span>
          {strategy.proposal ? <span className="block">{proposalText(strategy.proposal)}</span> : null}
        </li>
      ))}
    </ul>
  );
}

/** Python's own signal at the latest close. Python calculates first; Claude only reviews. */
export function PythonSignalPanel({ view }: { view: ForecastView }) {
  const strategies = view.context.strategies;
  return (
    <Panel title={`Python signal · ${view.analysis_as_of.slice(11, 16)} UTC close`}>
      <StrategyList strategies={strategies} />
      <p className="mt-2 text-xs text-muted">
        {hasSignal(strategies)
          ? "Prices come from Python's levels, and the risk engine sizes the trade."
          : "No strategy has a setup at this close, so there is nothing for Claude to review."}{" "}
        Python calculates every signal first. Claude only reviews a Python signal and never sets a price.
      </p>
    </Panel>
  );
}

const KRONOS_LAYERS: readonly (keyof Layers)[] = ["paths", "band"];

const LAYER_ITEMS: { key: keyof Layers; label: string; swatch: ReactNode }[] = [
  { key: "paths", label: "Kronos paths", swatch: <span className="h-0.5 w-4" style={{ background: COLORS.kronosPath }} /> },
  { key: "band", label: "Kronos 10–90%", swatch: <span className="h-3 w-4 rounded-sm border-t-2" style={{ background: COLORS.kronosFill, borderColor: COLORS.kronos }} /> },
  { key: "baseline", label: "Baseline 10–90%", swatch: <span className="h-3 w-4 rounded-sm border-t-2 border-dashed" style={{ background: COLORS.baselineFill, borderColor: COLORS.baseline }} /> },
  { key: "zones", label: "Python levels", swatch: <span className="h-0.5 w-4" style={{ background: COLORS.zone }} /> },
  { key: "plan", label: "Plan", swatch: <span className="h-3 w-4 rounded-sm" style={{ background: `linear-gradient(${COLORS.riskFill} 50%, ${COLORS.rewardFill} 50%)` }} /> },
  { key: "patterns", label: "Patterns", swatch: <span className="h-0.5 w-4" style={{ background: COLORS.pattern }} /> },
  { key: "signals", label: "Candle signals", swatch: <span className="text-[10px] leading-none text-down">▼</span> },
];

/**
 * The legend doubles as the layer switches, so every colour on the chart is named. Kronos's
 * switches show only while a Kronos run is on the chart (D040).
 */
const SQUARE_SIGNAL = <span className="text-[10px] leading-none text-down">■</span>;

export function LayerToggles({
  layers,
  onChange,
  kronos = false,
  squareSignals = false,
}: {
  layers: Layers;
  onChange: (layers: Layers) => void;
  kronos?: boolean;
  /** The Bot chart marks candle signals with squares, because its arrows are trade entries. */
  squareSignals?: boolean;
}) {
  const items = (kronos ? LAYER_ITEMS : LAYER_ITEMS.filter((item) => !KRONOS_LAYERS.includes(item.key))).map(
    (item) => (squareSignals && item.key === "signals" ? { ...item, swatch: SQUARE_SIGNAL } : item),
  );
  return (
    <div role="group" aria-label="Chart layers" className="flex flex-wrap gap-1">
      {items.map((item) => (
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

/**
 * Values under the cursor: the projection and a current Kronos run at that hour, an older
 * run over the candles that followed it, or the candle signals on that bar.
 */
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
  const hour = hoverTime === null ? null : Math.floor(hoverTime / 3600);
  const atHour = <T extends { open_time: string }>(steps: T[]): T | undefined =>
    hour === null
      ? undefined
      : steps.slice(0, span).find((s) => Math.floor(Date.parse(s.open_time) / 3_600_000) === hour);
  const projected = atHour(view.projection?.steps ?? []);
  const kronos = atHour(view.kronos?.steps ?? []);
  const signals =
    hoverTime === null
      ? []
      : view.candle_signals.filter((s) => floorTo(toSeconds(s.open_time), barSeconds) === hoverTime);
  if (projected) {
    return (
      <p className="text-xs">
        <span className="text-muted">
          {projected.open_time.slice(11, 16)} UTC candle · Baseline {formatNumber(projected.close.p50.toFixed(1))} (
          {range(projected.close)})
        </span>
        {view.kronos?.current && kronos ? (
          <>
            <span className="text-muted"> · </span>
            <span style={{ color: COLORS.kronos }}>Kronos {formatNumber(kronos.model.p50.toFixed(1))}</span>
            <span className="text-muted"> ({range(kronos.model)})</span>
          </>
        ) : null}
      </p>
    );
  }
  if (kronos) {
    return (
      <p className="text-xs">
        <span className="text-muted">{kronos.open_time.slice(11, 16)} UTC candle · </span>
        <span style={{ color: COLORS.kronos }}>
          Kronos run from {view.kronos?.as_of.slice(11, 16)} UTC: {formatNumber(kronos.model.p50.toFixed(1))}
        </span>
        <span className="text-muted"> ({range(kronos.model)})</span>
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
  const baseline = horizonOf(view.projection?.horizons ?? [], span);
  const model = view.kronos?.current ? horizonOf(view.kronos.horizons, span) : undefined;
  return (
    <p className="text-xs">
      <span className="text-muted">
        Next {baseline?.candles ?? span}h from the {view.analysis_as_of.slice(11, 16)} UTC close:{" "}
        {baseline
          ? `baseline ${percent(baseline.baseline.share_ending_higher)} of paths end higher`
          : "too few candles for the baseline"}
      </span>
      {model ? (
        <span style={{ color: COLORS.kronos }}> · Kronos {percent(model.model.share_ending_higher)}</span>
      ) : view.kronos ? (
        <span className="text-muted"> · Kronos run is {kronosAge(view)} old</span>
      ) : null}
    </p>
  );
}

/**
 * The next hours from the latest close. Kronos has a column only while a run is shown, and
 * values only when that run is from the latest close.
 */
export function SummaryPanel({ view, span }: { view: ForecastView; span: Span }) {
  const projection = view.projection;
  const horizon = projection ? horizonOf(projection.horizons, span) : undefined;
  if (!projection || !horizon) {
    return (
      <Panel title={`Next ${span} hours`}>
        <p className="text-xs text-muted">Too few 1H candles are stored to project from the latest close.</p>
      </Panel>
    );
  }
  const close = Number(projection.last_close);
  const atr = projection.atr;
  const base = horizon.baseline;
  const run = view.kronos;
  const model = run?.current ? horizonOf(run.horizons, span)?.model : undefined;
  const rows: { label: string; model: string; baseline: string }[] = [
    { label: "Paths ending higher", model: model ? percent(model.share_ending_higher) : "–", baseline: percent(base.share_ending_higher) },
    { label: "Close, middle", model: model ? formatNumber(model.close.p50.toFixed(1)) : "–", baseline: formatNumber(base.close.p50.toFixed(1)) },
    { label: "Close, 10–90%", model: model ? range(model.close) : "–", baseline: range(base.close) },
    { label: "Highest, middle", model: model ? atrDistance(model.highest.p50, close, atr) : "–", baseline: atrDistance(base.highest.p50, close, atr) },
    { label: "Lowest, middle", model: model ? atrDistance(model.lowest.p50, close, atr) : "–", baseline: atrDistance(base.lowest.p50, close, atr) },
  ];
  return (
    <Panel title={`Next ${horizon.candles} hours · from ${projection.as_of.slice(11, 16)} UTC`}>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-muted">
            <th className="py-1 text-left font-normal" scope="col">Measure</th>
            {run ? (
              <th className="py-1 text-right font-normal" scope="col" style={{ color: COLORS.kronos }}>Kronos</th>
            ) : null}
            <th className="py-1 text-right font-normal" scope="col">Baseline</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label} className="border-t border-raised">
              <th className="py-1 text-left font-normal text-muted" scope="row">{row.label}</th>
              {run ? <td className="py-1 text-right">{row.model}</td> : null}
              <td className="py-1 text-right text-muted">{row.baseline}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-muted">
        The baseline replays this coin&apos;s own last 60 days from the latest close, with no view on direction.{" "}
        {!run
          ? ""
          : model
            ? "Kronos says something only where it differs."
            : `Kronos last ran from the ${run.as_of.slice(11, 16)} UTC close, ${kronosAge(view)} earlier, so it is left out.${
                view.kronos_enabled ? " Re-analyse runs it from the latest close." : ""
              }`}
      </p>
    </Panel>
  );
}

export function TrackRecordPanel({ view }: { view: ForecastView }) {
  const record = view.kronos?.track_record;
  if (!record) {
    return null;
  }
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
  const python = plan.python_at_close;
  return (
    <Panel title="Claude's plan">
      <p className="mb-2 rounded border border-line px-2 py-1 text-xs text-muted">
        {plan.source}. Paper only. Level IDs are from the {plan.as_of.slice(11, 16)} UTC catalogue.
      </p>
      <div className="mb-2">
        <p className="mb-1 text-xs text-muted">Python first, at the {plan.as_of.slice(11, 16)} UTC close:</p>
        {python ? (
          <StrategyList strategies={python} />
        ) : (
          <p className="text-xs text-warn">No Python calculation was saved with this plan.</p>
        )}
        {python && !hasSignal(python) ? (
          <p className="mt-1 flex items-start gap-1.5 text-xs text-warn">
            <span aria-hidden="true">⚠</span>
            <span>Python had no signal at this close, so this plan was Claude&apos;s own idea, not a review of a Python signal.</span>
          </p>
        ) : null}
      </div>
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
  const run = view.kronos !== null;
  return (
    <Panel title={`Python levels · reached within ${span}h`}>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-muted">
            <th className="py-1 text-left font-normal" scope="col">Level</th>
            <th className="py-1 text-right font-normal" scope="col">Price</th>
            {run ? (
              <th className="py-1 text-right font-normal" scope="col" style={{ color: COLORS.kronos }}>Kronos</th>
            ) : null}
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
                {run ? <td className="py-1 text-right">{reach && reach.model !== null ? percent(reach.model) : "–"}</td> : null}
                <td className="py-1 text-right text-muted">
                  {reach && reach.baseline !== null ? percent(reach.baseline) : "–"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-muted">
        Shares of the baseline&apos;s paths that touch each level within {span}h of the {view.analysis_as_of.slice(11, 16)} UTC close.
        {run ? " Kronos is shown only when its run is from that close." : ""}
      </p>
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
