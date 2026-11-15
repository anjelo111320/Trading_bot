"use client";

import { Suspense } from "react";

import { SignalsScreen } from "@/components/signals/SignalsScreen";

export default function SignalsPage() {
  // The filters live in the address, which is read only in the browser.
  return (
    <Suspense fallback={<p className="p-6 text-sm text-muted">Loading…</p>}>
      <SignalsScreen />
    </Suspense>
  );
}
