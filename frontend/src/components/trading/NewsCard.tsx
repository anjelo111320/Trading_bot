import type { NewsItem } from "@/lib/api/client";
import { formatUtc } from "@/lib/format";

const SAFE_LINK = /^https:\/\//;

/** Outside text is shown as plain text, and only https links become clickable. */
export function NewsCard({ item }: { item: NewsItem }) {
  return (
    <article className="rounded border border-line bg-panel p-3">
      <h2 className="text-sm font-semibold">{item.headline}</h2>
      <p className="mt-1 text-xs text-muted">
        {item.source ?? "Unknown source"}
        {item.credibility_tier ? ` (${item.credibility_tier})` : ""}. Published{" "}
        {formatUtc(item.published_at)}. Retrieved {formatUtc(item.retrieved_at)}.
      </p>
      {item.classified ? (
        <>
          <p className="mt-2 text-sm">{item.ai_summary}</p>
          <dl className="mt-2 flex flex-wrap gap-x-4 text-xs text-muted">
            <div>Event: {item.event_type}</div>
            <div>Tone: {item.sentiment}</div>
            <div>Potential impact: {item.potential_impact}</div>
            <div>Certainty: {item.certainty}</div>
          </dl>
          {item.possibly_misleading ? (
            <p className="mt-1 text-xs text-warn">Possibly misleading</p>
          ) : null}
        </>
      ) : (
        <p className="mt-2 text-xs text-muted">Not classified.</p>
      )}
      {SAFE_LINK.test(item.url) ? (
        <a className="mt-2 inline-block text-xs underline" href={item.url} rel="noreferrer noopener" target="_blank">
          Original source
        </a>
      ) : null}
    </article>
  );
}
