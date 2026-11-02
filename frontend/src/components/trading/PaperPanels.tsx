import type { PaperSummary, Position } from "@/lib/api/client";
import { formatUtc } from "@/lib/format";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="text-lg font-semibold">{value}</dd>
    </div>
  );
}

function money(value: string): string {
  return Number(value).toFixed(2);
}

export function PaperAccount({ summary }: { summary: PaperSummary }) {
  const winRate = summary.win_rate === null ? "No resolved trades" : `${(summary.win_rate * 100).toFixed(1)}%`;
  const expectancy = summary.expectancy_r === null ? "No resolved trades" : `${summary.expectancy_r.toFixed(2)}R`;
  return (
    <section aria-label="Paper account" className="rounded border border-line bg-panel p-4">
      <dl className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="Simulated equity" value={money(summary.equity)} />
        <Stat label="Net P/L after costs" value={money(summary.net_pnl)} />
        <Stat label="Win rate" value={winRate} />
        <Stat label="Expectancy" value={expectancy} />
        <Stat label="Open or pending" value={String(summary.open_positions)} />
        <Stat label="Wins / losses" value={`${summary.wins} / ${summary.losses}`} />
        <Stat label="Not filled" value={String(summary.unfilled)} />
        <Stat label="Costs" value={money(summary.costs)} />
      </dl>
      <p className="mt-3 text-xs text-muted">
        Simulated results from paper trading. Unfilled trades are excluded from the win rate. This
        is not proof of future performance.
      </p>
    </section>
  );
}

export function PositionsTable({ positions }: { positions: Position[] }) {
  if (positions.length === 0) {
    return <p className="text-sm text-muted">No simulated positions yet.</p>;
  }
  return (
    <div className="overflow-x-auto rounded border border-line bg-panel">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Simulated positions</caption>
        <thead className="text-xs text-muted">
          <tr>
            <th scope="col" className="p-2">Instrument</th>
            <th scope="col" className="p-2">Side</th>
            <th scope="col" className="p-2">Status</th>
            <th scope="col" className="p-2 text-right">Quantity</th>
            <th scope="col" className="p-2 text-right">Entry</th>
            <th scope="col" className="p-2 text-right">Realized P/L</th>
            <th scope="col" className="p-2">Opened</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((position) => (
            <tr key={position.id} className="border-t border-line">
              <td className="p-2">{position.symbol}</td>
              <td className="p-2">{position.side}</td>
              <td className="p-2">
                {position.status}
                {position.reconstructed ? " (reconstructed)" : ""}
              </td>
              <td className="p-2 text-right">{position.planned_quantity}</td>
              <td className="p-2 text-right">{position.average_entry ?? "Not filled"}</td>
              <td className="p-2 text-right">{money(position.realized_pnl)}</td>
              <td className="p-2">{position.opened_at ? formatUtc(position.opened_at) : "Pending"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
