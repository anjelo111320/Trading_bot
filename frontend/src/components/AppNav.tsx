import Link from "next/link";

import { TradingBadge } from "./TradingBadge";

const LINKS = [
  { href: "/", label: "Market" },
  { href: "/forecast", label: "Forecast" },
  { href: "/signals", label: "Signals" },
  { href: "/coins", label: "Coins" },
  { href: "/paper", label: "Paper trading" },
  { href: "/bot", label: "Bot" },
  { href: "/news", label: "News" },
];

export function AppNav({ current }: { current: string }) {
  return (
    <nav aria-label="Main" className="flex flex-wrap items-center gap-3">
      <span className="text-sm font-semibold">AI Trading Intelligence</span>
      <TradingBadge />
      {LINKS.map((link) => (
        <Link
          key={link.href}
          href={link.href}
          aria-current={link.href === current ? "page" : undefined}
          className={`text-sm ${link.href === current ? "font-semibold text-ink" : "text-muted hover:text-ink"}`}
        >
          {link.label}
        </Link>
      ))}
    </nav>
  );
}
