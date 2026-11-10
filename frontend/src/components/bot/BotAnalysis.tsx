import {
  CandleSignalsPanel,
  ContextPanel,
  LevelsPanel,
  PlanPanel,
  PythonSignalPanel,
  SummaryPanel,
} from "@/components/forecast/ForecastPanels";
import { useNow } from "@/features/market/useNow";
import type { ForecastView } from "@/lib/api/client";

import { ANALYSIS_SPAN, hoursBehind } from "./analysis";

/** A latest 1H close older than this means the data feed has stopped, as on the Forecast page. */
const BEHIND_HOURS = 2;

/** The Forecast page's panels for the coin on the chart: Python first, then any plan. */
export function BotAnalysis({
  view,
  symbol,
  missing,
  failed,
}: {
  view: ForecastView | undefined;
  symbol: string;
  missing: boolean;
  failed: boolean;
}) {
  const now = useNow();
  if (missing) {
    return (
      <p className="rounded border border-line bg-panel p-3 text-sm text-muted">
        No Python analysis for {symbol} yet: its candles or rules are not stored.
      </p>
    );
  }
  if (failed) {
    return (
      <p role="alert" className="rounded border border-line bg-panel p-3 text-sm text-bad">
        Python&apos;s analysis could not be loaded. It retries every minute.
      </p>
    );
  }
  if (!view) {
    return <p className="rounded border border-line bg-panel p-3 text-sm text-muted">Loading Python&apos;s analysis…</p>;
  }
  const behind = hoursBehind(view, now);
  return (
    <>
      <p className="px-1 text-xs text-muted">
        Python&apos;s view of {symbol} at the {view.analysis_as_of.slice(11, 16)} UTC 1H close, as on the Forecast
        page. Information only: the bot&apos;s trades come from its strategies and the risk engine.
      </p>
      {behind > BEHIND_HOURS ? (
        <p role="alert" className="px-1 text-xs text-warn">
          No new 1H close for {behind}h: the data feed may be stopped
        </p>
      ) : null}
      <PythonSignalPanel view={view} />
      {view.plan ? <PlanPanel plan={view.plan} /> : null}
      {view.projection ? <SummaryPanel view={view} span={ANALYSIS_SPAN} /> : null}
      <LevelsPanel view={view} span={ANALYSIS_SPAN} />
      <ContextPanel view={view} />
      <CandleSignalsPanel view={view} />
    </>
  );
}
