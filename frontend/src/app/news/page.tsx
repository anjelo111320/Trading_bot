"use client";

import { AppNav } from "@/components/AppNav";
import { NewsCard } from "@/components/trading/NewsCard";
import { useNews } from "@/features/trading/queries";

export default function NewsPage() {
  const news = useNews();
  return (
    <div className="min-h-screen">
      <header className="border-b border-line px-4 py-2">
        <AppNav current="/news" />
      </header>
      <main className="mx-auto max-w-3xl space-y-3 p-4">
        <h1 className="text-lg font-semibold">News</h1>
        <p className="text-sm text-muted">
          Official Federal Reserve items. Tone describes the text and does not predict price.
        </p>
        {news.isError ? <p role="alert" className="text-bad">News could not be loaded.</p> : null}
        {news.data?.map((item) => <NewsCard key={item.id} item={item} />)}
      </main>
    </div>
  );
}
