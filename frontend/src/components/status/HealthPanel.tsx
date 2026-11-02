import type { Health } from "@/lib/api/client";

type Props = { health: Health | undefined; failed: boolean };

export function HealthPanel({ health, failed }: Props) {
  if (failed) {
    return (
      <p role="alert" className="rounded border border-bad p-3 text-bad">
        Backend unreachable. Data on this page may be out of date.
      </p>
    );
  }
  if (!health) {
    return <p className="text-muted">Checking backend…</p>;
  }
  return (
    <section className="rounded border border-line bg-panel p-4">
      <p className={health.ready ? "text-good" : "text-warn"}>
        {health.ready ? "All systems ready" : "Not ready"}
      </p>
      <p className="mt-1 text-sm text-muted">Mode: {health.trading_mode}</p>
      <ul className="mt-3 space-y-1 text-sm">
        {health.dependencies.map((dependency) => (
          <li key={dependency.name} className="flex justify-between">
            <span>{dependency.name}</span>
            <span className={dependency.ok ? "text-good" : "text-bad"}>
              {dependency.ok ? "OK" : (dependency.detail ?? "Failed")}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-muted">Checked {health.checked_at} UTC</p>
    </section>
  );
}
