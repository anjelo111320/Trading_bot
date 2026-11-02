import Link from "next/link";

const LINKS = [
  { href: "/", label: "Market" },
  { href: "/signals", label: "Signals" },
  { href: "/paper", label: "Paper trading" },
  { href: "/news", label: "News" },
];

export function AppNav({ current }: { current: string }) {
  return (
    <nav aria-label="Main" className="flex flex-wrap items-center gap-3">
      <span className="text-sm font-semibold">AI Trading Intelligence</span>
      <span className="rounded border border-line px-2 py-0.5 text-xs text-muted">Paper only</span>
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
