/**
 * Drawings on top of the candles: the baseline projected from the latest close, Kronos's
 * paths and band from its own close, Python's levels, the plan's position box and chart
 * patterns. Positions come from the chart's own scales, so they follow every zoom and scroll.
 */

import type {
  AutoscaleInfo,
  IChartApiBase,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  Logical,
  PrimitivePaneViewZOrder,
  SeriesAttachedParameter,
  SeriesType,
  Time,
} from "lightweight-charts";

import type { ForecastKronos, ForecastPlan, ForecastView } from "@/lib/api/client";

import { hoursBetween, interpolateX, levelStyle, momentX, spreadLabels, toSeconds, type Span } from "./geometry";

type Target = Parameters<IPrimitivePaneRenderer["draw"]>[0];
type Context = CanvasRenderingContext2D;
type Point = { x: number; y: number };
type Row = { price: number; text: string; color: string; dash: number[]; strong: boolean };
/** A fan of paths: where it starts, and the close moment of each later candle. */
type Fan = { start: Point; times: number[] };

export type Layers = {
  paths: boolean;
  band: boolean;
  baseline: boolean;
  zones: boolean;
  plan: boolean;
  patterns: boolean;
  signals: boolean;
};

/** Validated on the chart surface #0e1223 with the dataviz palette checker: CVD ΔE 26.8. */
export const COLORS = {
  kronos: "#3987e5",
  kronosFill: "rgba(57, 135, 229, 0.20)",
  kronosPath: "rgba(57, 135, 229, 0.32)",
  // An older run keeps its hue, faded, and is named as old in its label.
  kronosOld: "rgba(57, 135, 229, 0.6)",
  kronosOldFill: "rgba(57, 135, 229, 0.10)",
  kronosOldPath: "rgba(57, 135, 229, 0.16)",
  baseline: "#94a3b8",
  baselineFill: "rgba(148, 163, 184, 0.12)",
  pattern: "#d95926",
  risk: "#d03b3b",
  riskFill: "rgba(208, 59, 59, 0.16)",
  reward: "#0ca30c",
  rewardFill: "rgba(12, 163, 12, 0.15)",
  rewardFar: "rgba(12, 163, 12, 0.07)",
  ink: "#f8fafc",
  muted: "#94a3b8",
  zone: "rgba(148, 163, 184, 0.5)",
  window: "rgba(148, 163, 184, 0.06)",
  surface: "rgba(14, 18, 35, 0.88)",
} as const;

export const ALL_LAYERS: Layers = {
  paths: true,
  band: true,
  baseline: true,
  zones: true,
  plan: true,
  patterns: true,
  signals: true,
};

const FONT = "11px ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif";
const BOLD = "600 11px ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif";
const LABEL_GAP = 15;
const HOUR = 3600;

export type OverlayState = {
  view: ForecastView | null;
  layers: Layers;
  span: Span;
  slots: number[];
  barSeconds: number;
};

/** A plan still waiting for its fill or holding a position. A finished plan is history. */
export function planActive(plan: ForecastPlan): boolean {
  return plan.status.state === "waiting" || plan.status.state === "open";
}

/**
 * Which current levels an active plan uses. Catalogue IDs are renumbered at every analysis,
 * so levels are matched to the plan by price. The stop sits beyond its level, so its ID is
 * trusted only while the analysis is still at the plan's own close.
 */
export function planRoles(view: ForecastView): Map<string, string> {
  const roles = new Map<string, string>();
  const plan = view.plan;
  if (!plan || !planActive(plan)) return roles;
  for (const level of view.levels) {
    const price = Number(level.price);
    if (price === Number(plan.entry)) roles.set(level.id, "entry");
    plan.targets.forEach((target, index) => {
      if (price === Number(target)) roles.set(level.id, `T${index + 1}`);
    });
  }
  if (plan.stop_level_id && plan.as_of === view.analysis_as_of) {
    roles.set(plan.stop_level_id, "stop beyond");
  }
  return roles;
}

/** The current level ID at a plan price, if one matches. */
function levelAt(view: ForecastView, price: string): string | null {
  return view.levels.find((level) => Number(level.price) === Number(price))?.id ?? null;
}

export function formatNumber(value: number | string): string {
  return Number(value).toLocaleString("en-US", { maximumFractionDigits: 8 });
}

class Renderer implements IPrimitivePaneRenderer {
  constructor(private readonly paint: (context: Context, width: number, height: number) => void) {}

  draw(target: Target): void {
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      context.save();
      this.paint(context, mediaSize.width, mediaSize.height);
      context.restore();
    });
  }
}

class View implements IPrimitivePaneView {
  constructor(
    private readonly order: PrimitivePaneViewZOrder,
    private readonly drawing: Renderer,
  ) {}

  zOrder(): PrimitivePaneViewZOrder {
    return this.order;
  }

  renderer(): IPrimitivePaneRenderer {
    return this.drawing;
  }
}

function label(
  context: Context,
  text: string,
  x: number,
  y: number,
  color: string,
  align: CanvasTextAlign,
  strong = false,
) {
  context.font = strong ? BOLD : FONT;
  const width = context.measureText(text).width;
  const left = align === "right" ? x - width - 6 : align === "center" ? x - width / 2 - 3 : x;
  context.fillStyle = COLORS.surface;
  context.fillRect(left, y - 8, width + 6, 16);
  context.fillStyle = color;
  context.textAlign = "left";
  context.textBaseline = "middle";
  context.fillText(text, left + 3, y);
}

function polyline(context: Context, points: Point[]) {
  context.beginPath();
  points.forEach((point, index) =>
    index === 0 ? context.moveTo(point.x, point.y) : context.lineTo(point.x, point.y),
  );
}

function verticalLine(context: Context, x: number, height: number, color: string) {
  context.strokeStyle = color;
  context.lineWidth = 1;
  context.setLineDash([3, 3]);
  context.beginPath();
  context.moveTo(x, 0);
  context.lineTo(x, height);
  context.stroke();
  context.setLineDash([]);
}

/** The close moment of a forecast candle, an hour after it opens. */
function closeOf(step: { open_time: string }): number {
  return toSeconds(step.open_time) + HOUR;
}

export class ForecastOverlay implements ISeriesPrimitive<Time> {
  private chart: IChartApiBase<Time> | null = null;
  private series: ISeriesApi<SeriesType, Time> | null = null;
  private requestUpdate: (() => void) | null = null;
  private state: OverlayState = { view: null, layers: ALL_LAYERS, span: 4, slots: [], barSeconds: HOUR };
  private readonly views: readonly IPrimitivePaneView[] = [
    new View("bottom", new Renderer((c, w, h) => this.paintBehind(c, w, h))),
    new View("top", new Renderer((c, w, h) => this.paintAbove(c, w, h))),
  ];

  attached(param: SeriesAttachedParameter<Time>): void {
    this.chart = param.chart;
    this.series = param.series;
    this.requestUpdate = param.requestUpdate;
  }

  detached(): void {
    this.chart = null;
    this.series = null;
    this.requestUpdate = null;
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this.views;
  }

  setState(state: OverlayState): void {
    this.state = state;
    this.requestUpdate?.();
  }

  /**
   * Keep what matters now inside the price scale: the projection, a current Kronos run and
   * an active plan, when they are in view. An old run or a finished plan never stretches
   * the scale away from today's candles.
   */
  autoscaleInfo(start: Logical, end: Logical): AutoscaleInfo | null {
    const { view, layers, span, slots } = this.state;
    if (!view || slots.length === 0) {
      return null;
    }
    const slot = (index: number) => slots[Math.min(Math.max(index, 0), slots.length - 1)]!;
    const from = slot(Math.floor(Number(start)));
    const to = slot(Math.ceil(Number(end)));
    const inView = (first: number, last: number) => last >= from && first <= to;
    const values: number[] = [];
    const projection = view.projection;
    const projected = projection?.steps.slice(0, span) ?? [];
    if (projection && layers.baseline && projected.length > 0) {
      if (inView(toSeconds(projection.as_of), closeOf(projected[projected.length - 1]!))) {
        values.push(Number(projection.last_close));
        for (const step of projected) values.push(step.close.p10, step.close.p90);
      }
    }
    const run = view.kronos;
    const steps = run?.steps.slice(0, span) ?? [];
    if (run?.current && steps.length > 0 && inView(toSeconds(run.as_of), closeOf(steps[steps.length - 1]!))) {
      if (layers.band) for (const step of steps) values.push(step.model.p10, step.model.p90);
      if (layers.paths) for (const path of run.paths) values.push(...path.slice(0, span));
    }
    const plan = view.plan;
    if (layers.plan && plan && planActive(plan) && inView(toSeconds(plan.created_at), toSeconds(plan.expires_at))) {
      values.push(Number(plan.entry), Number(plan.stop), ...plan.targets.map(Number));
    }
    if (values.length === 0) {
      return null;
    }
    return { priceRange: { minValue: Math.min(...values), maxValue: Math.max(...values) } };
  }

  /** The x coordinate of a bar's open time, between slots when bars are longer than 1H. */
  private x(seconds: number): number | null {
    const scale = this.chart?.timeScale();
    if (!scale) {
      return null;
    }
    return interpolateX(seconds, this.state.slots, (slot) => scale.timeToCoordinate(slot as Time));
  }

  /** The x coordinate of an exact moment, such as a close. */
  private at(seconds: number): number | null {
    const scale = this.chart?.timeScale();
    if (!scale) {
      return null;
    }
    return momentX(seconds, this.state.barSeconds, this.state.slots, (slot) =>
      scale.timeToCoordinate(slot as Time),
    );
  }

  private y(price: number): number | null {
    return this.series?.priceToCoordinate(price) ?? null;
  }

  private point(moment: number, price: number): Point | null {
    const x = this.at(moment);
    const y = this.y(price);
    return x === null || y === null ? null : { x, y };
  }

  /** A fan starting at a close, with one point per later 1H close. */
  private fan(asOf: string, lastClose: string, steps: { open_time: string }[]): Fan | null {
    const start = this.point(toSeconds(asOf), Number(lastClose));
    return start ? { start, times: steps.map(closeOf) } : null;
  }

  private line(values: number[], fan: Fan): Point[] {
    const points = [fan.start];
    values.forEach((value, index) => {
      const point = this.point(fan.times[index]!, value);
      if (point) points.push(point);
    });
    return points;
  }

  private projected(view: ForecastView): { fan: Fan | null; steps: NonNullable<ForecastView["projection"]>["steps"] } {
    const projection = view.projection;
    if (!projection) return { fan: null, steps: [] };
    const steps = projection.steps.slice(0, this.state.span);
    return { fan: this.fan(projection.as_of, projection.last_close, steps), steps };
  }

  /** The Kronos run, when Kronos is on and one is stored (D040). */
  private kronos(view: ForecastView): { fan: Fan | null; steps: ForecastKronos["steps"]; run: ForecastKronos | null } {
    const run = view.kronos;
    if (!run) return { fan: null, steps: [], run: null };
    const steps = run.steps.slice(0, this.state.span);
    return { fan: this.fan(run.as_of, run.last_close, steps), steps, run };
  }

  /** The future from the latest close, shaded, so it is clear where "now" ends. */
  private window(view: ForecastView): { start: number; end: number } | null {
    const { fan, steps } = view.projection ? this.projected(view) : view.kronos?.current ? this.kronos(view) : { fan: null, steps: [] };
    const last = steps[steps.length - 1];
    if (!fan || !last) {
      return null;
    }
    const end = this.at(closeOf(last));
    return end === null ? null : { start: fan.start.x, end };
  }

  private band(context: Context, upper: Point[], lower: Point[], fill: string) {
    polyline(context, [...upper, ...lower.slice(1).reverse()]);
    context.closePath();
    context.fillStyle = fill;
    context.fill();
  }

  private paintBehind(context: Context, width: number, height: number): void {
    const { view, layers } = this.state;
    if (!view) {
      return;
    }
    const window = this.window(view);
    if (window) {
      context.fillStyle = COLORS.window;
      context.fillRect(window.start, 0, window.end - window.start, height);
    }
    const ahead = this.projected(view);
    if (layers.baseline && ahead.fan) {
      const upper = this.line(ahead.steps.map((s) => s.close.p90), ahead.fan);
      const lower = this.line(ahead.steps.map((s) => s.close.p10), ahead.fan);
      this.band(context, upper, lower, COLORS.baselineFill);
    }
    const kronos = this.kronos(view);
    if (layers.band && kronos.fan) {
      const upper = this.line(kronos.steps.map((s) => s.model.p90), kronos.fan);
      const lower = this.line(kronos.steps.map((s) => s.model.p10), kronos.fan);
      this.band(context, upper, lower, view.kronos?.current ? COLORS.kronosFill : COLORS.kronosOldFill);
    }
    if (layers.zones) {
      context.lineWidth = 1;
      context.strokeStyle = COLORS.zone;
      for (const level of view.levels) {
        const y = this.y(Number(level.price));
        if (y === null) continue;
        context.setLineDash(levelStyle(level.kind).dash);
        context.beginPath();
        context.moveTo(0, y);
        context.lineTo(width, y);
        context.stroke();
      }
      context.setLineDash([]);
    }
    const plan = view.plan;
    if (layers.plan && plan) {
      const left = this.at(toSeconds(plan.created_at));
      const right = this.at(toSeconds(plan.expires_at));
      const entry = this.y(Number(plan.entry));
      const stop = this.y(Number(plan.stop));
      const targets = plan.targets.map((t) => this.y(Number(t)));
      if (left !== null && right !== null && entry !== null && stop !== null) {
        context.fillStyle = COLORS.riskFill;
        context.fillRect(left, Math.min(entry, stop), right - left, Math.abs(stop - entry));
        let from = entry;
        targets.forEach((target, index) => {
          if (target === null || target === undefined) return;
          context.fillStyle = index === 0 ? COLORS.rewardFill : COLORS.rewardFar;
          context.fillRect(left, Math.min(from, target), right - left, Math.abs(target - from));
          from = target;
        });
      }
    }
  }

  private paintAbove(context: Context, width: number, height: number): void {
    const { view, layers, span } = this.state;
    if (!view) {
      return;
    }
    const current = view.kronos?.current ?? false;
    const kronos = this.kronos(view);
    const ahead = this.projected(view);
    const window = this.window(view);

    if (layers.paths && kronos.fan) {
      context.lineWidth = 1;
      context.strokeStyle = current ? COLORS.kronosPath : COLORS.kronosOldPath;
      for (const path of kronos.run?.paths ?? []) {
        polyline(context, this.line(path.slice(0, span), kronos.fan));
        context.stroke();
      }
    }
    if (layers.baseline && ahead.fan) {
      context.lineWidth = 1.5;
      context.strokeStyle = COLORS.baseline;
      context.setLineDash([5, 4]);
      polyline(context, this.line(ahead.steps.map((s) => s.close.p50), ahead.fan));
      context.stroke();
      context.setLineDash([]);
    }
    if (layers.band && kronos.fan) {
      context.lineWidth = current ? 2 : 1.5;
      context.strokeStyle = current ? COLORS.kronos : COLORS.kronosOld;
      polyline(context, this.line(kronos.steps.map((s) => s.model.p50), kronos.fan));
      context.stroke();
    }
    if (window) {
      verticalLine(context, window.start, height, COLORS.muted);
      label(context, `From the ${view.analysis_as_of.slice(11, 16)} UTC close · next ${span}h →`, window.start - 4, 12, COLORS.muted, "right");
    }
    if (!current && kronos.fan && (layers.paths || layers.band)) {
      // Where the older run started, so it reads as history rather than as the forecast.
      verticalLine(context, kronos.fan.start.x, height, COLORS.kronosOld);
      const runAt = kronos.run?.as_of ?? view.analysis_as_of;
      const age = hoursBetween(runAt, view.analysis_as_of);
      label(context, `Kronos run from ${runAt.slice(11, 16)} UTC · ${age}h old`, kronos.fan.start.x + 4, 30, COLORS.kronos, "left");
    }

    if (layers.patterns) {
      this.paintPatterns(context, view, width);
    }
    if (layers.plan && view.plan) {
      this.paintPlan(context, view);
    }
    this.paintLabels(context, view, width, height);
  }

  private paintPatterns(context: Context, view: ForecastView, width: number): void {
    for (const pattern of view.patterns) {
      const points = pattern.points
        .map((p) => ({ x: this.x(toSeconds(p.time)), y: this.y(p.price), name: p.name }))
        .filter((p): p is Point & { name: string } => p.x !== null && p.y !== null);
      if (points.length === 0) continue;
      context.strokeStyle = COLORS.pattern;
      context.fillStyle = COLORS.pattern;
      context.lineWidth = 2;
      polyline(context, points);
      context.stroke();
      for (const point of points) {
        context.beginPath();
        context.arc(point.x, point.y, 3, 0, Math.PI * 2);
        context.fill();
      }
      const breakout = this.x(toSeconds(pattern.breakout_at));
      const name = pattern.type.replaceAll("_", " ");
      const verdict = pattern.decision === "NO_TRADE" ? "refused" : pattern.decision.toLowerCase();
      const head = points[points.length - 1]!;
      label(context, `${name}, ${verdict}`, head.x + 6, head.y - 14, COLORS.pattern, "left");
      context.setLineDash([6, 4]);
      context.lineWidth = 1.5;
      pattern.measured_moves.forEach((move, index) => {
        const y = this.y(move);
        if (y === null || breakout === null) return;
        context.beginPath();
        context.moveTo(breakout, y);
        context.lineTo(width, y);
        context.stroke();
        label(context, `${name} target ${index + 1}× ${formatNumber(move)}`, breakout + 4, y - 9, COLORS.pattern, "left");
      });
      if (pattern.invalidation !== null) {
        const y = this.y(pattern.invalidation);
        if (y !== null && breakout !== null) {
          context.setLineDash([2, 3]);
          context.beginPath();
          context.moveTo(points[0]!.x, y);
          context.lineTo(breakout, y);
          context.stroke();
          label(context, `invalidation ${formatNumber(pattern.invalidation)}`, points[0]!.x, y + 10, COLORS.pattern, "left");
        }
      }
      context.setLineDash([]);
    }
  }

  private planRows(view: ForecastView): Row[] {
    const plan = view.plan;
    if (!plan) return [];
    const side = plan.side === "SHORT" ? "Sell" : "Buy";
    const by = (id: string | null | undefined) => (id ? ` · ${id}` : "");
    const sameClose = plan.as_of === view.analysis_as_of;
    return [
      {
        price: Number(plan.entry),
        text: `${side} ${plan.entry_type.toLowerCase()} ${formatNumber(plan.entry)}${by(levelAt(view, plan.entry))}`,
        color: COLORS.ink,
        dash: [4, 3],
        strong: true,
      },
      {
        price: Number(plan.stop),
        text: `Stop ${formatNumber(plan.stop)}${sameClose && plan.stop_level_id ? ` · beyond ${plan.stop_level_id}` : ""}`,
        color: COLORS.risk,
        dash: [],
        strong: true,
      },
      ...plan.targets.map((target, index) => ({
        price: Number(target),
        text: `T${index + 1} ${formatNumber(target)}${plan.reward_risk[index] ? ` · ${plan.reward_risk[index]}R` : ""}${by(levelAt(view, target))}`,
        color: COLORS.reward,
        dash: [4, 3],
        strong: true,
      })),
    ];
  }

  /**
   * The position box's lines and status, in the window the plan was valid. An active plan's
   * prices are also labelled in the right-hand column; a finished one's are in the panel.
   */
  private paintPlan(context: Context, view: ForecastView): void {
    const plan = view.plan!;
    const left = this.at(toSeconds(plan.created_at));
    const right = this.at(toSeconds(plan.expires_at));
    if (left === null || right === null) return;
    const rows = this.planRows(view);
    context.lineWidth = 1.5;
    for (const row of rows) {
      const y = this.y(row.price);
      if (y === null) continue;
      context.strokeStyle = row.color;
      context.setLineDash(row.dash);
      context.beginPath();
      context.moveTo(left, y);
      context.lineTo(right, y);
      context.stroke();
    }
    context.setLineDash([]);
    const top = Math.min(...rows.map((row) => this.y(row.price) ?? Infinity));
    if (Number.isFinite(top)) {
      label(context, `Plan ${plan.grade} · ${planState(plan.status.state)}`, left + 2, top - 12, COLORS.ink, "left");
    }
    const marks = [
      { time: plan.status.entry_time, price: plan.status.entry_price, color: COLORS.ink },
      { time: plan.status.exit_time, price: plan.status.exit_price, color: COLORS.muted },
    ];
    for (const mark of marks) {
      if (!mark.time || !mark.price) continue;
      const x = this.at(toSeconds(mark.time));
      const y = this.y(Number(mark.price));
      if (x === null || y === null) continue;
      context.fillStyle = mark.color;
      context.beginPath();
      context.arc(x, y, 4, 0, Math.PI * 2);
      context.fill();
    }
  }

  /**
   * One column of labels on the right, in the room kept free of candles: an active plan's
   * prices first, then Python's levels. Labels are spaced so none overlap, and a short tick
   * joins a moved label to its price.
   */
  private paintLabels(context: Context, view: ForecastView, width: number, height: number): void {
    const { layers } = this.state;
    const plan = layers.plan && view.plan && planActive(view.plan) ? view.plan : null;
    const covered = new Set(
      [...planRoles(view)].filter(([, role]) => role !== "stop beyond").map(([id]) => id),
    );
    const rows: Row[] = [
      ...(plan ? this.planRows(view) : []),
      ...(layers.zones
        ? view.levels
            .filter((level) => !covered.has(level.id))
            .map((level) => ({
              price: Number(level.price),
              text: `${level.id} ${levelStyle(level.kind).label} ${formatNumber(level.price)}`,
              color: COLORS.muted,
              dash: [] as number[],
              strong: false,
            }))
        : []),
    ];
    const visible = rows
      .map((row) => ({ row, y: this.y(row.price) }))
      .filter((item): item is { row: Row; y: number } => item.y !== null && item.y > 0 && item.y < height);
    const placed = spreadLabels(visible.map((item) => item.y), LABEL_GAP, 9, height - 9);
    const planRight = plan ? this.at(toSeconds(plan.expires_at)) : null;
    visible.forEach((item, index) => {
      const y = placed[index]!;
      context.font = item.row.strong ? BOLD : FONT;
      const left = width - 4 - context.measureText(item.row.text).width - 6;
      if (item.row.strong && planRight !== null && planRight < left) {
        context.strokeStyle = item.row.color;
        context.globalAlpha = 0.5;
        context.lineWidth = 1;
        context.setLineDash([1, 3]);
        context.beginPath();
        context.moveTo(planRight, item.y);
        context.lineTo(left - 6, item.y);
        context.stroke();
        context.setLineDash([]);
        context.globalAlpha = 1;
      }
      if (Math.abs(y - item.y) > 1) {
        context.strokeStyle = item.row.color;
        context.lineWidth = 1;
        context.beginPath();
        context.moveTo(left - 6, item.y);
        context.lineTo(left - 1, y);
        context.stroke();
      }
      label(context, item.row.text, width - 4, y, item.row.color, "right", item.row.strong);
    });
  }
}

export function planState(state: string): string {
  switch (state) {
    case "waiting":
      return "waiting for fill";
    case "open":
      return "filled, open";
    case "closed":
      return "closed";
    case "not_filled":
      return "not filled";
    default:
      return state;
  }
}
