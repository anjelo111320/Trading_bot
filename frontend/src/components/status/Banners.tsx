type DataWarningProps = { problem: string | null };

/** Shown whenever data may not be current. Old prices must never look live. */
export function DataWarning({ problem }: DataWarningProps) {
  if (!problem) {
    return null;
  }
  return (
    <p role="alert" className="border-b border-bad bg-bad/15 px-4 py-2 text-sm font-medium">
      Data is not current: {problem}. Do not rely on the prices shown.
    </p>
  );
}

export function SyntheticBanner({ visible }: { visible: boolean }) {
  if (!visible) {
    return null;
  }
  return (
    <p role="alert" className="border-b border-warn bg-warn px-4 py-2 text-center text-sm font-bold text-surface">
      SYNTHETIC DATA. Generated for development. This is not real market data.
    </p>
  );
}
