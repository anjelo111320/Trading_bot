/**
 * A Binance account's limits as the settings form edits them (D058): percentages on screen,
 * fractions in the API. Shaping and checks only; the API and the risk engine decide.
 */

import type { Limits, LimitsUpdate } from "@/lib/api/client";

export type LimitsForm = {
  risk: string;
  openRisk: string;
  exposure: string;
  largestTrade: string; // Blank: no limit on one position alone (D061).
  oneDirection: string; // Blank: no limit on longs or shorts together (D072).
  leverage: string;
  dailyLoss: string;
  profitStop: string; // Blank: none.
  lossStop: string; // Blank: none.
  fromHigh: boolean;
};

function percent(value: string | null | undefined): string {
  if (value === null || value === undefined) return "";
  return String(Number((Number(value) * 100).toFixed(4)));
}

function fraction(value: string): string {
  return String(Number((Number(value) / 100).toFixed(6)));
}

export function formOf(limits: Limits): LimitsForm {
  return {
    risk: percent(limits.risk_per_trade),
    openRisk: percent(limits.open_risk),
    exposure: percent(limits.exposure),
    largestTrade: percent(limits.largest_trade),
    oneDirection: percent(limits.one_direction),
    leverage: limits.max_leverage,
    dailyLoss: percent(limits.daily_loss),
    profitStop: percent(limits.daily_profit_stop),
    lossStop: percent(limits.loss_stop),
    fromHigh: limits.loss_stop_from_high,
  };
}

/** Problems a person can fix before saving, in plain words. The API checks again. */
export function problems(form: LimitsForm, limits: Limits): string[] {
  const found: string[] = [];
  const number = (value: string) => (value.trim() === "" ? Number.NaN : Number(value));
  const ceiling = (value: string) => Number(value) * 100;
  const risk = number(form.risk);
  const open = number(form.openRisk);
  if (!(risk > 0 && risk <= ceiling(limits.ceilings.risk_per_trade)))
    found.push(`Risk per trade must be above 0% and at most ${ceiling(limits.ceilings.risk_per_trade)}%.`);
  if (!(open >= risk && open <= ceiling(limits.ceilings.open_risk)))
    found.push(`Risk across open trades must be at least the risk per trade and at most ${ceiling(limits.ceilings.open_risk)}%.`);
  const exposure = number(form.exposure);
  if (!(exposure > 0 && exposure <= ceiling(limits.ceilings.exposure)))
    found.push(`All positions together must be above 0% and at most ${ceiling(limits.ceilings.exposure)}% of equity.`);
  if (form.largestTrade.trim() !== "" && !(number(form.largestTrade) > 0 && number(form.largestTrade) <= exposure))
    found.push("The largest single trade must be above 0% and at most all positions together, or blank for none.");
  if (form.oneDirection.trim() !== "" && !(number(form.oneDirection) > 0 && number(form.oneDirection) <= exposure))
    found.push("One direction must be above 0% and at most all positions together, or blank for none.");
  const leverage = number(form.leverage);
  if (!(Number.isInteger(leverage) && leverage >= 1 && leverage <= Number(limits.ceilings.leverage)))
    found.push(`Leverage must be a whole number from 1 to ${limits.ceilings.leverage}.`);
  const daily = number(form.dailyLoss);
  if (!(daily > 0 && daily <= ceiling(limits.ceilings.daily_loss)))
    found.push(`The daily loss limit must be above 0% and at most ${ceiling(limits.ceilings.daily_loss)}%.`);
  if (form.profitStop.trim() !== "" && !(number(form.profitStop) > 0))
    found.push("The daily profit stop must be above 0%, or blank for none.");
  if (form.lossStop.trim() !== "" && !(number(form.lossStop) > 0 && number(form.lossStop) < 100))
    found.push("The loss stop must be between 0% and 100%, or blank for none.");
  return found;
}

export function updateOf(form: LimitsForm): LimitsUpdate {
  return {
    risk_per_trade: fraction(form.risk),
    open_risk: fraction(form.openRisk),
    exposure: fraction(form.exposure),
    largest_trade: form.largestTrade.trim() === "" ? null : fraction(form.largestTrade),
    one_direction: form.oneDirection.trim() === "" ? null : fraction(form.oneDirection),
    max_leverage: String(Number(form.leverage)),
    daily_loss: fraction(form.dailyLoss),
    daily_profit_stop: form.profitStop.trim() === "" ? null : fraction(form.profitStop),
    loss_stop: form.lossStop.trim() === "" ? null : fraction(form.lossStop),
    loss_stop_from_high: form.fromHigh,
  };
}

/** What two losing trades in a row cost at this risk, compounding: shown beside the field. */
export function twoLosses(risk: string): string {
  const r = Number(risk) / 100;
  if (!(r > 0 && r < 1)) return "";
  return `${((1 - (1 - r) ** 2) * 100).toFixed(1)}%`;
}
