# ruff: noqa: E501 - the embedded page keeps its own line lengths.
"""Render the pattern backtest data into one local HTML page.

Reads data/reports/pattern-backtest-*.json, written by
`python -m trading_intel.entrypoints.pattern_backtest`, and writes
data/reports/pattern-backtest.html. The page embeds Binance-derived data, so it stays on
this computer under data/, which git ignores (D006).
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "reports"
OUTPUT = DATA / "pattern-backtest.html"

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pattern breakout backtest</title>
<style>
.viz-root {
  color-scheme: light;
  --page: #f9f9f7; --surface-1: #fcfcfb;
  --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a;
  --good: #0ca30c; --critical: #d03b3b; --wash: rgba(42,120,214,0.10);
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) .viz-root {
    color-scheme: dark;
    --page: #0d0d0d; --surface-1: #1a1a19;
    --text-primary: #f0efec; --text-secondary: #c3c2b7; --text-muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70;
    --wash: rgba(57,135,229,0.14);
  }
}
:root[data-theme="dark"] .viz-root {
  color-scheme: dark;
  --page: #0d0d0d; --surface-1: #1a1a19;
  --text-primary: #f0efec; --text-secondary: #c3c2b7; --text-muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70;
  --wash: rgba(57,135,229,0.14);
}
* { box-sizing: border-box; }
body { margin: 0; }
.viz-root { background: var(--page); color: var(--text-primary); min-height: 100vh;
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; padding: 24px; }
.wrap { max-width: 1180px; margin: 0 auto; }
h1 { font-size: 22px; margin: 0 0 4px; font-weight: 600; }
h2 { font-size: 16px; margin: 0 0 4px; font-weight: 600; }
.sub, .caption { color: var(--text-secondary); margin: 0; }
.caption { font-size: 13px; margin-bottom: 12px; }
.statement { color: var(--text-secondary); font-weight: 600; margin: 6px 0 0; }
.filters { display: flex; gap: 8px; align-items: center; margin: 18px 0; flex-wrap: wrap; }
.filters .label { color: var(--text-secondary); margin-right: 4px; }
button, select { font: inherit; color: var(--text-primary); background: var(--surface-1);
  border: 1px solid var(--border); border-radius: 8px; padding: 6px 12px; cursor: pointer; }
button[aria-pressed="true"] { border-color: var(--series-1); box-shadow: inset 0 0 0 1px var(--series-1); font-weight: 600; }
button:focus-visible, select:focus-visible { outline: 2px solid var(--series-1); outline-offset: 2px; }
.card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px;
  padding: 18px 20px; margin-bottom: 16px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 12px; }
.tile { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; }
.tile .k { color: var(--text-secondary); font-size: 13px; }
.tile .v { font-size: 26px; font-weight: 600; margin-top: 2px; }
.tile .d { color: var(--text-muted); font-size: 12px; margin-top: 2px; }
.verdict { margin: 0 0 16px; padding: 12px 14px; border-radius: 12px; border: 1px solid var(--border);
  background: var(--surface-1); }
.verdict strong { font-weight: 600; }
.explorer { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 18px; }
@media (max-width: 900px) { .explorer { grid-template-columns: 1fr; } }
.controls { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
.controls select { max-width: 100%; }
.steps { list-style: none; margin: 0; padding: 0; counter-reset: step; }
.steps li { counter-increment: step; position: relative; padding: 0 0 12px 30px; }
.steps li::before { content: counter(step); position: absolute; left: 0; top: 0; width: 20px; height: 20px;
  border-radius: 10px; border: 1px solid var(--axis); color: var(--text-secondary); font-size: 12px;
  display: flex; align-items: center; justify-content: center; }
.steps .t { font-weight: 600; }
.steps .x { color: var(--text-secondary); }
.decision { font-weight: 600; }
.legend { display: flex; gap: 16px; flex-wrap: wrap; color: var(--text-secondary); font-size: 13px; margin: 6px 0 4px; }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.key { display: inline-block; width: 16px; height: 0; border-top: 2px solid; border-radius: 1px; }
.dotkey { display: inline-block; width: 8px; height: 8px; border-radius: 4px; }
svg { display: block; width: 100%; height: auto; overflow: visible; }
svg text { fill: var(--text-secondary); font: 12px system-ui, -apple-system, "Segoe UI", sans-serif; }
svg .muted { fill: var(--text-muted); }
svg .ink { fill: var(--text-primary); }
.tooltip { position: fixed; pointer-events: none; background: var(--surface-1); border: 1px solid var(--border);
  border-radius: 8px; padding: 8px 10px; font-size: 12px; box-shadow: 0 4px 16px rgba(0,0,0,0.12);
  display: none; z-index: 10; min-width: 140px; }
.tooltip .row { display: flex; align-items: center; gap: 8px; justify-content: space-between; }
.tooltip .row b { font-weight: 600; font-variant-numeric: tabular-nums; }
.tooltip .when { color: var(--text-secondary); margin-bottom: 4px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: right; padding: 6px 8px; border-bottom: 1px solid var(--grid); font-variant-numeric: tabular-nums; }
th:first-child, td:first-child, th.l, td.l { text-align: left; }
th { color: var(--text-secondary); font-weight: 600; position: sticky; top: 0; background: var(--surface-1); }
.scroll { max-height: 420px; overflow: auto; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 900px) { .two { grid-template-columns: 1fr; } }
.notes { color: var(--text-secondary); font-size: 13px; }
.notes li { margin-bottom: 4px; }
</style>
</head>
<body>
<div class="viz-root"><div class="wrap">
<header>
  <h1>Pattern breakout backtest</h1>
  <p class="sub" id="subtitle"></p>
  <p class="statement" id="statement"></p>
</header>
<div class="filters" role="group" aria-label="Coin">
  <span class="label">Coin</span>
  <span id="coins"></span>
</div>
<div class="tiles" id="tiles"></div>
<p class="verdict" id="verdict"></p>

<section class="card">
  <h2>How the code makes a signal</h2>
  <p class="caption">Every trade the strategy took, and breakouts it refused. Candles are 1H, in UTC. Prices come from Python, never from a model.</p>
  <div class="controls">
    <button id="mode-trades" aria-pressed="true">Trades taken</button>
    <button id="mode-refused" aria-pressed="false">Refused breakouts</button>
    <button id="prev" aria-label="Previous">&#8592;</button>
    <select id="pick" aria-label="Choose a trade"></select>
    <button id="next" aria-label="Next">&#8594;</button>
  </div>
  <div class="explorer">
    <div>
      <div class="legend" id="trade-legend"></div>
      <svg id="trade-chart" viewBox="0 0 860 440" role="img" aria-label="Candles around the selected signal"></svg>
    </div>
    <ol class="steps" id="steps"></ol>
  </div>
</section>

<section class="card">
  <h2>Equity, starting at 10,000 USDT</h2>
  <p class="caption" id="equity-caption"></p>
  <div class="legend" id="equity-legend"></div>
  <svg id="equity-chart" viewBox="0 0 1100 320" role="img" aria-label="Equity over time"></svg>
</section>

<div class="two">
  <section class="card">
    <h2>Did the patterns beat random timing?</h2>
    <p class="caption">Each grey dot is one run of random entries at 1H candles where 4H and 1D agree, with stops and targets copied from real signals. Same costs, same risk engine.</p>
    <svg id="random-chart" viewBox="0 0 520 170" role="img" aria-label="Expectancy of random entries against the strategy"></svg>
  </section>
  <section class="card">
    <h2>From breakout to trade</h2>
    <p class="caption">How many 1H chart-pattern breakouts survived each rule.</p>
    <svg id="funnel-chart" viewBox="0 0 520 200" role="img" aria-label="Signal funnel"></svg>
  </section>
</div>

<section class="card">
  <h2>By pattern</h2>
  <p class="caption">Small samples. A pattern with few trades says almost nothing, and choosing patterns from this table would be fitting the past.</p>
  <div class="scroll"><table id="pattern-table"></table></div>
</section>

<section class="card">
  <h2>All trades</h2>
  <div class="scroll"><table id="trade-table"></table></div>
</section>

<section class="card notes">
  <h2>How to read this</h2>
  <ul id="notes"></ul>
</section>
<div class="tooltip" id="tooltip" role="status"></div>
</div></div>
<script type="application/json" id="report-data">__DATA__</script>
<script>
"use strict";
const DATA = JSON.parse(document.getElementById("report-data").textContent);
const NS = "http://www.w3.org/2000/svg";
const symbols = Object.keys(DATA);
let symbol = symbols[0];
let mode = "trades";
let position = 0;

const $ = (id) => document.getElementById(id);
function el(tag, attrs = {}, parent = null, text = null) {
  const node = tag.startsWith("svg:") ? document.createElementNS(NS, tag.slice(4)) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== null) node.textContent = text;
  if (parent) parent.appendChild(node);
  return node;
}
const svg = (tag, attrs, parent, text = null) => el("svg:" + tag, attrs, parent, text);
function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
const css = (name) => getComputedStyle(document.querySelector(".viz-root")).getPropertyValue(name).trim();

const fmt = (v, d = 2) => Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const price = (v) => Number(v).toLocaleString("en-US", { maximumFractionDigits: v >= 1000 ? 1 : 2 });
const signed = (v, d = 2) => (v > 0 ? "+" : v < 0 ? "\u2212" : "") + fmt(Math.abs(v), d);
const pct = (v) => (v * 100).toLocaleString("en-US", { maximumFractionDigits: 1 }) + "%";
const pretty = (s) => { const t = s.replaceAll("_", " "); return t.charAt(0).toUpperCase() + t.slice(1); };
const when = (ms) => new Date(ms).toISOString().slice(0, 16).replace("T", " ") + " UTC";
const date = (iso) => iso.slice(0, 16).replace("T", " ") + " UTC";

const tooltip = $("tooltip");
function showTip(event, title, rows) {
  clear(tooltip);
  el("div", { class: "when" }, tooltip, title);
  for (const [label, value, color] of rows) {
    const row = el("div", { class: "row" }, tooltip);
    const name = el("span", {}, row);
    if (color) el("span", { class: "key", style: `border-color:${color}` }, name);
    name.appendChild(document.createTextNode(" " + label));
    el("b", {}, row, value);
  }
  tooltip.style.display = "block";
  const box = tooltip.getBoundingClientRect();
  let x = event.clientX + 14, y = event.clientY + 14;
  if (x + box.width > window.innerWidth - 8) x = event.clientX - box.width - 14;
  if (y + box.height > window.innerHeight - 8) y = event.clientY - box.height - 14;
  tooltip.style.left = x + "px"; tooltip.style.top = y + "px";
}
function hideTip() { tooltip.style.display = "none"; }

function niceTicks(lo, hi, count = 5) {
  const span = hi - lo, raw = span / count, mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= count) || mag * 10;
  const ticks = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(+v.toFixed(10));
  return ticks;
}
function pointer(svgNode, event) {
  const p = svgNode.createSVGPoint(); p.x = event.clientX; p.y = event.clientY;
  return p.matrixTransform(svgNode.getScreenCTM().inverse());
}
function spread(labels, gap, top, bottom) {
  labels.sort((a, b) => a.y - b.y);
  for (let i = 1; i < labels.length; i++) labels[i].y = Math.max(labels[i].y, labels[i - 1].y + gap);
  const over = labels.length ? labels[labels.length - 1].y - bottom : 0;
  if (over > 0) for (const l of labels) l.y -= over;
  for (let i = labels.length - 2; i >= 0; i--) labels[i].y = Math.min(labels[i].y, labels[i + 1].y - gap);
  for (const l of labels) l.y = Math.max(l.y, top);
  return labels;
}

function renderCoins() {
  const box = $("coins"); clear(box);
  for (const s of symbols) {
    const b = el("button", { "aria-pressed": String(s === symbol) }, box, s.replace("USDT", ""));
    b.style.marginRight = "6px";
    b.addEventListener("click", () => { symbol = s; position = 0; renderAll(); });
  }
}

function renderHeader() {
  const d = DATA[symbol];
  $("subtitle").textContent = `${d.symbol} perpetual on Binance. ${d.strategy}. 1H setups with the 4H and 1D trend, ${d.period[0].slice(0, 10)} to ${d.period[1].slice(0, 10)}, which ends where the frozen holdout begins.`;
  $("statement").textContent = d.statement;
}

function p95(values) { const s = [...values].sort((a, b) => a - b); return s[Math.max(Math.floor(s.length * 0.95) - 1, 0)]; }
function mean(values) { return values.reduce((a, b) => a + b, 0) / values.length; }

function renderTiles() {
  const d = DATA[symbol], m = d.summary["trial1_1x"], box = $("tiles"); clear(box);
  const breakouts = Object.values(d.funnel).reduce((a, b) => a + b, 0);
  const tiles = [
    ["Trades", String(m.trades), `from ${breakouts.toLocaleString("en-US")} breakouts`],
    ["Win rate", pct(m.win_rate), "wins over all closed trades"],
    ["Expectancy", signed(m.expectancy_r) + "R", m.interval ? `per trade. 95% interval ${signed(m.interval[0])} to ${signed(m.interval[1])}R` : "per trade"],
    ["Profit factor", fmt(m.profit_factor), "gross profit over gross loss"],
    ["Net result", signed(m.net_pnl, 0), `USDT on 10,000, risking 1% a trade`],
    ["Largest drawdown", pct(m.max_drawdown), "peak to trough"],
    ["Buy and hold", d.buy_and_hold === null ? "n/a" : signed(d.buy_and_hold * 100, 0) + "%", "no costs, fully exposed"],
  ];
  for (const [k, v, sub] of tiles) {
    const t = el("div", { class: "tile" }, box);
    el("div", { class: "k" }, t, k); el("div", { class: "v" }, t, v); el("div", { class: "d" }, t, sub);
  }
  const random = d.benchmark ? d.benchmark.expectancies : [];
  const parts = [];
  parts.push(m.net_pnl > 0 ? "Profitable in simulation after fees, spread, slippage and funding." : "Lost money in simulation after costs.");
  parts.push(m.interval && m.interval[0] > 0 ? "The 95% interval for expectancy is above zero." : "But the 95% interval for expectancy includes zero, so the result could be luck.");
  if (random.length) {
    parts.push(m.expectancy_r > p95(random)
      ? `It beat 95% of random-timing runs (random mean ${signed(mean(random), 3)}R).`
      : `Random entries with the same trend filter and exits averaged ${signed(mean(random), 3)}R, so the patterns added little beyond the trend filter.`);
  }
  parts.push("Not proven. It stays in paper trading.");
  const v = $("verdict"); clear(v);
  el("strong", {}, v, "Verdict: "); v.appendChild(document.createTextNode(parts.join(" ")));
}

function items() { const d = DATA[symbol]; return mode === "trades" ? d.trades : d.refused; }

function renderPicker() {
  const pick = $("pick"); clear(pick);
  items().forEach((t, i) => {
    const label = mode === "trades"
      ? `#${t.number}  ${t.signal_time.slice(0, 10)}  ${pretty(t.pattern.type)}  ${t.side}  ${signed(t.r)}R`
      : `${t.time.slice(0, 10)}  ${pretty(t.pattern.type)}  refused`;
    el("option", { value: String(i) }, pick, label);
  });
  pick.value = String(position);
  $("mode-trades").setAttribute("aria-pressed", String(mode === "trades"));
  $("mode-refused").setAttribute("aria-pressed", String(mode === "refused"));
}

function renderTrade() {
  const list = items(); const node = $("trade-chart"); clear(node);
  const steps = $("steps"); clear(steps);
  if (!list.length) { svg("text", { x: 20, y: 40 }, node, "Nothing to show."); return; }
  const t = list[Math.min(position, list.length - 1)];
  const c = t.candles, p = t.pattern, n = c.length;
  const W = 860, H = 440, L = 64, R = 150, T = 18, B = 30;
  const levels = [];
  const isTrade = mode === "trades";
  if (isTrade) {
    levels.push({ v: t.entry_plan, color: css("--text-primary"), label: "Entry " + price(t.entry_plan) });
    levels.push({ v: t.stop, color: css("--critical"), label: "Stop " + price(t.stop) });
    t.targets.forEach((v, i) => levels.push({ v, color: css("--good"), label: `TP${i + 1} ` + price(v) }));
  }
  p.measured_moves.forEach((v, i) => levels.push({ v, color: css("--text-muted"), label: `${i + 1}x move ` + price(v), thin: true }));
  let lo = Math.min(...c.map((k) => k[3])), hi = Math.max(...c.map((k) => k[2]));
  for (const l of levels) { lo = Math.min(lo, l.v); hi = Math.max(hi, l.v); }
  const pad = (hi - lo) * 0.04; lo -= pad; hi += pad;
  const step = (W - L - R) / n;
  const x = (i) => L + (i + 0.5) * step;
  const y = (v) => T + (hi - v) / (hi - lo) * (H - T - B);
  for (const tick of niceTicks(lo, hi, 6)) {
    svg("line", { x1: L, x2: W - R, y1: y(tick), y2: y(tick), stroke: css("--grid"), "stroke-width": 1 }, node);
    svg("text", { x: L - 8, y: y(tick) + 4, "text-anchor": "end", class: "muted" }, node, price(tick));
  }
  svg("line", { x1: L, x2: W - R, y1: H - B, y2: H - B, stroke: css("--axis"), "stroke-width": 1 }, node);
  const dayTicks = [];
  c.forEach((k, i) => { const d = new Date(k[0]); if (d.getUTCHours() === 0) dayTicks.push(i); });
  const every = Math.max(1, Math.ceil(dayTicks.length / 7));
  dayTicks.filter((_, j) => j % every === 0).forEach((i) => {
    svg("text", { x: x(i), y: H - B + 18, "text-anchor": "middle", class: "muted" }, node, new Date(c[i][0]).toISOString().slice(5, 10));
  });
  const signal = isTrade ? t.signal_index : t.signal_index;
  svg("line", { x1: x(signal), x2: x(signal), y1: T, y2: H - B, stroke: css("--axis"), "stroke-width": 1 }, node);
  svg("text", { x: x(signal) + 4, y: T + 10, class: "ink" }, node, isTrade ? "Signal" : "Breakout");
  const body = Math.max(1, Math.min(step * 0.62, 9));
  c.forEach((k, i) => {
    const [ , o, h, l, cl] = k, up = cl >= o;
    svg("line", { x1: x(i), x2: x(i), y1: y(h), y2: y(l), stroke: css("--text-secondary"), "stroke-width": 1 }, node);
    const top = y(Math.max(o, cl)), height = Math.max(1, Math.abs(y(o) - y(cl)));
    svg("rect", { x: x(i) - body / 2, y: top, width: body, height, rx: 1,
      fill: up ? css("--surface-1") : css("--text-secondary"), stroke: css("--text-secondary"), "stroke-width": 1 }, node);
  });
  const blue = css("--series-1");
  const line = (a, b, attrs = {}) => svg("line", { x1: x(a[0]), y1: y(a[1]), x2: x(b[0]), y2: y(b[1]), stroke: blue, "stroke-width": 1.5, "stroke-linecap": "round", ...attrs }, node);
  const extend = (a, b, to) => { const slope = (b[1] - a[1]) / ((b[0] - a[0]) || 1); return [to, b[1] + slope * (to - b[0])]; };
  if (p.upper && p.lower) {
    line(p.upper[0], extend(p.upper[0], p.upper[1], p.detected));
    line(p.lower[0], extend(p.lower[0], p.lower[1], p.detected));
  } else if (p.points.length > 1) {
    line(p.points[1], [p.detected, p.trigger]);
  }
  svg("polyline", { points: p.points.map((q) => `${x(q[0])},${y(q[1])}`).join(" "), fill: "none", stroke: blue,
    "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, node);
  p.points.forEach((q, i) => {
    svg("circle", { cx: x(q[0]), cy: y(q[1]), r: 4, fill: blue, stroke: css("--surface-1"), "stroke-width": 2 }, node);
    svg("text", { x: x(q[0]), y: y(q[1]) + (i % 2 ? 16 : -9), "text-anchor": "middle", class: "muted" }, node, String(i + 1));
  });
  const end = isTrade ? Math.min(t.exit_index, n - 1) : n - 1;
  const labels = [];
  for (const l of levels) {
    const from = l.thin ? p.detected : signal;
    svg("line", { x1: x(from), x2: x(end), y1: y(l.v), y2: y(l.v), stroke: l.color, "stroke-width": l.thin ? 1 : 1.5 }, node);
    labels.push({ y: y(l.v) + 4, line: y(l.v), text: l.label, color: l.color });
  }
  for (const lab of spread(labels, 15, T + 8, H - B)) {
    svg("line", { x1: x(end) + 2, x2: W - R + 10, y1: lab.line, y2: lab.y - 4, stroke: lab.color, "stroke-width": 1 }, node);
    const g = svg("g", {}, node);
    svg("line", { x1: W - R + 12, x2: W - R + 24, y1: lab.y - 4, y2: lab.y - 4, stroke: lab.color, "stroke-width": 2 }, g);
    svg("text", { x: W - R + 28, y: lab.y }, g, lab.text);
  }
  if (isTrade) {
    svg("circle", { cx: x(t.exit_index), cy: y(t.exit_price), r: 5, fill: css("--text-primary"), stroke: css("--surface-1"), "stroke-width": 2 }, node);
    svg("circle", { cx: x(t.signal_index), cy: y(t.entry_price), r: 4, fill: css("--text-primary"), stroke: css("--surface-1"), "stroke-width": 2 }, node);
  }
  const legend = $("trade-legend"); clear(legend);
  const key = (color, text, dot = false) => { const s = el("span", {}, legend); el("span", { class: dot ? "dotkey" : "key", style: dot ? `background:${color}` : `border-color:${color}` }, s); s.appendChild(document.createTextNode(text)); };
  key(blue, pretty(p.type) + " and its trigger line");
  if (isTrade) { key(css("--text-primary"), "Entry and exit", true); key(css("--critical"), "Stop"); key(css("--good"), "Targets"); }
  key(css("--text-muted"), "Measured moves");
  const cross = svg("line", { y1: T, y2: H - B, stroke: css("--axis"), "stroke-width": 1, visibility: "hidden" }, node);
  const hit = svg("rect", { x: L, y: T, width: W - L - R, height: H - T - B, fill: "transparent" }, node);
  hit.addEventListener("pointermove", (e) => {
    const q = pointer(node, e); const i = Math.max(0, Math.min(n - 1, Math.floor((q.x - L) / step)));
    cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
    const k = c[i];
    showTip(e, when(k[0]), [["Open", price(k[1])], ["High", price(k[2])], ["Low", price(k[3])], ["Close", price(k[4])]]);
  });
  hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
  const add = (title, text) => { const li = el("li", {}, steps); el("div", { class: "t" }, li, title); el("div", { class: "x" }, li, text); };
  const dir = p.direction === "bullish" ? "up" : "down";
  if (isTrade) {
    add("Pattern confirmed", `${pretty(p.type)} on 1H. The candle closing ${date(t.signal_time)} closed ${dir === "up" ? "above" : "below"} its trigger line at ${price(p.trigger)}. Points 1 to ${p.points.length} are the turning points it was drawn on.`);
    add("Trend filter", `The 4H and 1D swing trends were both ${dir}, so a ${t.side === "LONG" ? "buy" : "sell"} goes with the trend.`);
    add("Stop", `${price(t.stop)}: beyond the pattern's invalidation level ${price(p.invalidation)}, plus a quarter of the 1H ATR.`);
    add("Targets", `${t.targets.map(price).join(", ")}: the nearest catalogue levels at least 2R away. The pattern's measured moves are ${p.measured_moves.map(price).join(" and ")}.`);
    add("Risk engine", "Sized so a stop-out loses 1% of equity, and approved because reward to risk is at least 2:1 after fees, spread and slippage.");
    const li = el("li", {}, steps); el("div", { class: "t" }, li, "Result");
    el("div", { class: "x" }, li, `Exit by ${t.exit_reason === "stop" ? "stop" : t.exit_reason.toUpperCase()} at ${price(t.exit_price)}, ${date(t.exit_time)}. `);
    el("div", { class: "decision" }, li, `${signed(t.r)}R, ${signed(t.net_pnl)} USDT after ${fmt(t.fees)} fees and ${signed(t.funding)} funding.`);
  } else {
    add("Pattern confirmed", `${pretty(p.type)} on 1H, breaking ${dir} at ${date(t.time)}.`);
    add("Trend filter", `4H trend ${t.trend_4h}, 1D trend ${t.trend_1d}.`);
    const li = el("li", {}, steps); el("div", { class: "t" }, li, "Decision");
    el("div", { class: "decision" }, li, "NO TRADE");
    el("div", { class: "x" }, li, t.reason.includes("against the trend") ? `A ${dir === "up" ? "buy" : "sell"} would go against the higher timeframes, so the strategy waits.` : "No catalogue level was at least 2R away, so a 2:1 trade was not possible.");
  }
}

function renderEquity() {
  const d = DATA[symbol], node = $("equity-chart"); clear(node);
  const W = 1100, H = 320, L = 64, R = 160, T = 14, B = 28;
  const series = [
    { key: "trial1_1x", name: "Trial 1, normal costs", color: css("--series-1") },
    { key: "trial1_2x", name: "Trial 1, double costs", color: css("--series-2") },
    { key: "trial2_1x", name: "Trial 2, candle confirmation", color: css("--series-3") },
  ].map((s) => ({ ...s, points: d.equity[s.key] }));
  const t0 = Date.parse(d.period[0]), t1 = Date.parse(d.period[1]);
  let lo = Infinity, hi = -Infinity;
  for (const s of series) for (const [, v] of s.points) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  lo = Math.min(lo, 10000); hi = Math.max(hi, 10000);
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const x = (t) => L + (t - t0) / (t1 - t0) * (W - L - R);
  const y = (v) => T + (hi - v) / (hi - lo) * (H - T - B);
  for (const tick of niceTicks(lo, hi, 5)) {
    svg("line", { x1: L, x2: W - R, y1: y(tick), y2: y(tick), stroke: css("--grid"), "stroke-width": 1 }, node);
    svg("text", { x: L - 8, y: y(tick) + 4, "text-anchor": "end", class: "muted" }, node, tick.toLocaleString("en-US"));
  }
  svg("line", { x1: L, x2: W - R, y1: H - B, y2: H - B, stroke: css("--axis"), "stroke-width": 1 }, node);
  for (let year = new Date(t0).getUTCFullYear(); year <= new Date(t1).getUTCFullYear(); year++) {
    const t = Date.UTC(year, 0, 1); if (t < t0 || t > t1) continue;
    svg("text", { x: x(t), y: H - B + 18, "text-anchor": "middle", class: "muted" }, node, String(year));
  }
  svg("line", { x1: L, x2: W - R, y1: y(10000), y2: y(10000), stroke: css("--axis"), "stroke-width": 1 }, node);
  const valueAt = (pts, t) => { let v = 10000; for (const [at, value] of pts) { if (at > t) break; v = value; } return v; };
  const labels = [];
  for (const s of series) {
    const pts = [[t0, 10000], ...s.points.filter(([at]) => at > t0), [t1, s.points.length ? s.points[s.points.length - 1][1] : 10000]];
    let path = `M${x(pts[0][0])},${y(pts[0][1])}`;
    for (let i = 1; i < pts.length; i++) path += `H${x(pts[i][0])}V${y(pts[i][1])}`;
    svg("path", { d: path, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, node);
    const last = pts[pts.length - 1][1];
    svg("circle", { cx: x(t1), cy: y(last), r: 4, fill: s.color, stroke: css("--surface-1"), "stroke-width": 2 }, node);
    labels.push({ y: y(last) + 4, line: y(last), text: `${Math.round(last).toLocaleString("en-US")}`, color: s.color });
  }
  for (const lab of spread(labels, 15, T + 6, H - B)) {
    svg("line", { x1: x(t1) + 6, x2: x(t1) + 16, y1: lab.line, y2: lab.y - 4, stroke: lab.color, "stroke-width": 1 }, node);
    svg("text", { x: x(t1) + 20, y: lab.y }, node, lab.text);
  }
  const legend = $("equity-legend"); clear(legend);
  for (const s of series) { const span = el("span", {}, legend); el("span", { class: "key", style: `border-color:${s.color}` }, span); span.appendChild(document.createTextNode(s.name)); }
  $("equity-caption").textContent = `Each step is a closed trade. Buy and hold made ${d.buy_and_hold === null ? "n/a" : signed(d.buy_and_hold * 100, 0) + "%"} over the same period, with full exposure and far deeper drawdowns, so it is shown as a number rather than on this axis.`;
  const cross = svg("line", { y1: T, y2: H - B, stroke: css("--axis"), "stroke-width": 1, visibility: "hidden" }, node);
  const hit = svg("rect", { x: L, y: T, width: W - L - R, height: H - T - B, fill: "transparent" }, node);
  hit.addEventListener("pointermove", (e) => {
    const q = pointer(node, e); const t = t0 + (q.x - L) / (W - L - R) * (t1 - t0);
    cross.setAttribute("x1", x(t)); cross.setAttribute("x2", x(t)); cross.setAttribute("visibility", "visible");
    showTip(e, new Date(t).toISOString().slice(0, 10), series.map((s) => [s.name, Math.round(valueAt(s.points, t)).toLocaleString("en-US"), s.color]));
  });
  hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
}

function renderRandom() {
  const d = DATA[symbol], node = $("random-chart"); clear(node);
  const W = 520, H = 170, L = 20, R = 20, mid = 92;
  if (!d.benchmark || !d.benchmark.expectancies.length) { svg("text", { x: 20, y: 40 }, node, "No benchmark."); return; }
  const values = d.benchmark.expectancies, trades = d.benchmark.trades, me = d.summary["trial1_1x"].expectancy_r;
  let lo = Math.min(-0.2, ...values, me), hi = Math.max(0.4, ...values, me);
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const x = (v) => L + (v - lo) / (hi - lo) * (W - L - R);
  svg("line", { x1: L, x2: W - R, y1: mid + 34, y2: mid + 34, stroke: css("--axis"), "stroke-width": 1 }, node);
  for (const tick of niceTicks(lo, hi, 6)) {
    svg("line", { x1: x(tick), x2: x(tick), y1: mid + 34, y2: mid + 38, stroke: css("--axis"), "stroke-width": 1 }, node);
    svg("text", { x: x(tick), y: mid + 52, "text-anchor": "middle", class: "muted" }, node, (tick > 0 ? "+" : "") + tick.toFixed(2) + "R");
  }
  svg("line", { x1: x(0), x2: x(0), y1: 22, y2: mid + 34, stroke: css("--axis"), "stroke-width": 1 }, node);
  svg("text", { x: x(0) + 4, y: 30, class: "muted" }, node, "break-even");
  const sorted = values.map((v, i) => ({ v, i })).sort((a, b) => a.v - b.v);
  const rows = [];
  for (const item of sorted) {
    let row = 0; while (rows[row] !== undefined && x(item.v) - rows[row] < 10) row++;
    rows[row] = x(item.v);
    const cy = mid + 20 - row * 10;
    const dot = svg("circle", { cx: x(item.v), cy, r: 4, fill: css("--text-muted"), stroke: css("--surface-1"), "stroke-width": 2 }, node);
    const target = svg("circle", { cx: x(item.v), cy, r: 12, fill: "transparent" }, node);
    target.addEventListener("pointermove", (e) => { dot.setAttribute("r", 5); showTip(e, `Random run ${item.i + 1}`, [["Expectancy", signed(item.v, 3) + "R"], ["Trades", String(trades[item.i])]]); });
    target.addEventListener("pointerleave", () => { dot.setAttribute("r", 4); hideTip(); });
  }
  const blue = css("--series-1");
  svg("line", { x1: x(me), x2: x(me), y1: 40, y2: mid + 30, stroke: blue, "stroke-width": 2 }, node);
  svg("circle", { cx: x(me), cy: 40, r: 6, fill: blue, stroke: css("--surface-1"), "stroke-width": 2 }, node);
  const anchor = x(me) > W - 150 ? "end" : "start";
  svg("text", { x: x(me) + (anchor === "end" ? -10 : 10), y: 44, "text-anchor": anchor, class: "ink" }, node, `This strategy ${signed(me, 3)}R`);
  svg("text", { x: L, y: 14, class: "muted" }, node, `Random mean ${signed(mean(values), 3)}R, 95th percentile ${signed(p95(values), 3)}R`);
}

function renderFunnel() {
  const d = DATA[symbol], node = $("funnel-chart"); clear(node);
  const total = Object.values(d.funnel).reduce((a, b) => a + b, 0);
  const aligned = total - (d.funnel["against the 4H or 1D trend"] || 0);
  const stages = [
    ["Chart-pattern breakouts", total],
    ["4H and 1D agree", aligned],
    ["A target 2R away exists", d.funnel["proposed"] || 0],
    ["No trade already open", d.signals],
    ["Approved and filled", d.trades.length],
  ];
  const W = 520, L = 190, R = 50, rowH = 36, bar = 14;
  const x = (v) => (W - L - R) * v / total;
  stages.forEach(([label, value], i) => {
    const cy = 18 + i * rowH;
    svg("text", { x: L - 10, y: cy + 4, "text-anchor": "end" }, node, label);
    const w = Math.max(2, x(value)), r = Math.min(4, w / 2);
    const path = `M${L},${cy - bar / 2}H${L + w - r}Q${L + w},${cy - bar / 2} ${L + w},${cy - bar / 2 + r}V${cy + bar / 2 - r}Q${L + w},${cy + bar / 2} ${L + w - r},${cy + bar / 2}H${L}Z`;
    const shape = svg("path", { d: path, fill: css("--series-1") }, node);
    svg("text", { x: L + w + 6, y: cy + 4, class: "ink" }, node, value.toLocaleString("en-US"));
    const target = svg("rect", { x: 0, y: cy - rowH / 2, width: W, height: rowH, fill: "transparent" }, node);
    target.addEventListener("pointermove", (e) => { shape.setAttribute("opacity", "0.8"); showTip(e, label, [["Count", value.toLocaleString("en-US")], ["Share of breakouts", pct(value / total)]]); });
    target.addEventListener("pointerleave", () => { shape.setAttribute("opacity", "1"); hideTip(); });
  });
  svg("line", { x1: L, x2: L, y1: 4, y2: 18 + (stages.length - 1) * rowH + 14, stroke: css("--axis"), "stroke-width": 1 }, node);
}

function table(node, head, rows) {
  clear(node);
  const tr = el("tr", {}, el("thead", {}, node));
  head.forEach((h, i) => el("th", i === 0 ? { class: "l" } : {}, tr, h));
  const body = el("tbody", {}, node);
  for (const row of rows) { const r = el("tr", {}, body); row.forEach((v, i) => el("td", i === 0 ? { class: "l" } : {}, r, v)); }
}

function renderTables() {
  const d = DATA[symbol], groups = {};
  for (const t of d.trades) (groups[t.pattern.type] ||= []).push(t);
  const rows = Object.entries(groups).sort((a, b) => b[1].length - a[1].length).map(([name, list]) => {
    const wins = list.filter((t) => t.net_pnl > 0).length;
    return [pretty(name), String(list.length), pct(wins / list.length), signed(mean(list.map((t) => t.r))) + "R", signed(list.reduce((a, t) => a + t.net_pnl, 0), 0)];
  });
  table($("pattern-table"), ["Pattern", "Trades", "Win rate", "Average R", "Net USDT"], rows);
  table($("trade-table"), ["#", "Signal (UTC)", "Pattern", "Side", "Entry", "Stop", "Exit", "Result", "R", "Net USDT"],
    d.trades.map((t) => [String(t.number), date(t.signal_time), pretty(t.pattern.type), t.side, price(t.entry_price), price(t.stop), price(t.exit_price), t.exit_reason, signed(t.r), signed(t.net_pnl)]));
}

function renderNotes() {
  const d = DATA[symbol], box = $("notes"); clear(box);
  const notes = [
    "A pattern only counts once a 1H candle closes beyond its trigger line, and only then is it visible to the strategy. Nothing here uses data from after the decision.",
    "R is the result divided by the planned risk. +2R means the trade made twice what it risked, and -1R means a full stop-out.",
    "Two trials were declared before any run and nothing was tuned. Trial 2 also requires a confirming candle pattern.",
    "Fills use 15-minute candles. When a stop and a target fall in the same candle, the stop is assumed, so results can only be understated by this.",
    "Costs include Binance taker fees, a spread and slippage allowance, and real funding payments. Double costs are shown as a stress test.",
    "BTC and ETH were chosen with hindsight. The 12 months from 2025-11-01 are frozen and untouched, kept for one final check.",
    "This page is simulated research for personal use. It is not financial advice, and no real order can be placed by this system.",
    `Generated ${d.generated_at} from public Binance market data.`,
  ];
  for (const n of notes) el("li", {}, box, n);
}

function renderAll() { renderCoins(); renderHeader(); renderTiles(); renderPicker(); renderTrade(); renderEquity(); renderRandom(); renderFunnel(); renderTables(); renderNotes(); remember(); }

// Views are linkable: #BTCUSDT/trades/12 opens trade 12, #ETHUSDT/refused/1 the first refusal.
function remember() { history.replaceState(null, "", `#${symbol}/${mode}/${position + 1}`); }
function restore() {
  const [s, m, n] = decodeURIComponent(location.hash.slice(1)).split("/");
  if (symbols.includes(s)) symbol = s;
  if (m === "trades" || m === "refused") mode = m;
  const wanted = Number(n) - 1;
  if (Number.isInteger(wanted) && wanted >= 0 && wanted < items().length) position = wanted;
}
function showTrade() { renderPicker(); renderTrade(); remember(); }

$("mode-trades").addEventListener("click", () => { mode = "trades"; position = 0; showTrade(); });
$("mode-refused").addEventListener("click", () => { mode = "refused"; position = 0; showTrade(); });
$("prev").addEventListener("click", () => { position = (position - 1 + items().length) % Math.max(items().length, 1); showTrade(); });
$("next").addEventListener("click", () => { position = (position + 1) % Math.max(items().length, 1); showTrade(); });
$("pick").addEventListener("change", (e) => { position = Number(e.target.value); renderTrade(); remember(); });
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", renderAll);
restore();
renderAll();
</script>
</body>
</html>
"""


def main() -> None:
    reports = {}
    for path in sorted(DATA.glob("pattern-backtest-*.json")):
        report = json.loads(path.read_text())
        reports[report["symbol"]] = report
    if not reports:
        raise SystemExit("no data: run python -m trading_intel.entrypoints.pattern_backtest first")
    payload = json.dumps(reports, separators=(",", ":")).replace("</", "<\\/")
    OUTPUT.write_text(PAGE.replace("__DATA__", payload))
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size / 1e6:.1f} MB) for {', '.join(reports)}")


if __name__ == "__main__":
    main()
