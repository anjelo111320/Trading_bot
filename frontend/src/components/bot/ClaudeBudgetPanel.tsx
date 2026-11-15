"use client";

import { useState } from "react";

import { useAiBudget, useSaveAiBudget } from "@/features/trading/queries";
import { ApiError, type AiBudget } from "@/lib/api/client";
import { formatUtc } from "@/lib/format";

/** Tokens in thousands, for a short line. */
export function thousands(tokens: number): string {
  return tokens < 1000 ? String(tokens) : `${(tokens / 1000).toFixed(1)}k`;
}

/** Today's Claude spend against its daily limit, in one line. */
export function spendLine(budget: AiBudget): string {
  const tokens = budget.input_tokens_today + budget.output_tokens_today;
  return (
    `$${budget.spent_today_usd} of $${budget.daily_limit_usd} today, ` +
    `${budget.calls_today} call${budget.calls_today === 1 ? "" : "s"}, ${thousands(tokens)} tokens`
  );
}

/** A limit a person typed, checked before saving. The API checks again. */
export function limitProblem(value: string, ceiling: string): string | null {
  const number = value.trim() === "" ? Number.NaN : Number(value);
  if (!(number >= 0 && number <= Number(ceiling))) return `Claude's daily limit must be from $0 to $${ceiling}.`;
  return null;
}

/**
 * Claude's daily cost limit, for every Claude call together: news labels and exit advice
 * (D062). At the limit Claude is not asked again until 00:00 UTC. Each save is logged.
 */
export function ClaudeBudgetPanel() {
  const budget = useAiBudget(true);
  const save = useSaveAiBudget();
  // Unsaved edits only; without any, the form shows the saved limit.
  const [draft, setDraft] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  if (!budget.data) {
    return (
      <p className="rounded border border-line bg-panel p-3 text-sm text-muted">
        {budget.isError ? "Claude's limit could not be loaded." : "Loading Claude's limit…"}
      </p>
    );
  }
  const current = budget.data;
  const value = draft ?? current.daily_limit_usd;
  const problem = limitProblem(value, current.ceiling_usd);
  const error = save.error instanceof ApiError ? save.error.message : save.error ? "The limit could not be saved." : null;
  return (
    <section aria-label="Claude's daily limit" className="rounded border border-line bg-panel p-3">
      <h2 className="mb-1 text-sm font-semibold">Claude&apos;s daily limit</h2>
      <p className="mb-3 text-xs text-muted">
        For every Claude call together: news labels and exit advice. At the limit, Claude is not asked again until
        00:00 UTC.{current.changed_at ? ` Saved ${formatUtc(current.changed_at)}.` : ""}
      </p>
      <form
        className="space-y-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (problem) return;
          save.mutate(String(Number(value)), {
            onSuccess: () => {
              setDraft(null);
              setSaved(true);
            },
          });
        }}
      >
        <label className="flex items-baseline justify-between gap-2 text-sm">
          <span>Daily limit</span>
          <span className="flex items-center gap-1">
            <span className="text-xs text-muted">$</span>
            <input
              type="number"
              inputMode="decimal"
              step="any"
              min="0"
              value={value}
              onChange={(event) => {
                setSaved(false);
                setDraft(event.target.value);
              }}
              className="min-h-9 w-24 rounded border border-line bg-raised px-2 text-right tabular-nums text-ink"
              aria-label="Claude's daily limit (USD)"
            />
          </span>
        </label>
        <p className={`text-xs ${current.reached ? "font-semibold text-warn" : "text-muted"}`}>
          {spendLine(current)}
          {current.reached ? ". Reached: Claude is not asked again until 00:00 UTC." : "."}
        </p>
        {problem ? (
          <p role="alert" className="text-xs text-warn">
            {problem}
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-xs text-bad">
            {error}
          </p>
        ) : null}
        {saved ? <p className="text-xs text-good">Saved: ${current.daily_limit_usd} a day.</p> : null}
        <button
          type="submit"
          disabled={problem !== null || save.isPending}
          className="min-h-9 cursor-pointer rounded border border-ink bg-raised px-3 text-sm font-semibold text-ink disabled:cursor-not-allowed disabled:opacity-50"
        >
          {save.isPending ? "Saving…" : "Save Claude's limit"}
        </button>
      </form>
    </section>
  );
}
