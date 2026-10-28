import { Activity } from 'lucide-react';
import type { CostSummary } from '../types';
import { formatUsd } from '../lib/format';

// Inside the desktop app the sidebar already carries the LoopPrism name.
const inDesktopApp = window.parent !== window;

function Stat({
  label,
  value,
  title,
}: {
  label: string;
  value: string;
  title?: string;
}) {
  return (
    <div className="flex flex-col items-end" title={title}>
      <span className="text-[10px] font-medium uppercase tracking-wider text-[var(--color-muted-foreground)]">
        {label}
      </span>
      <span className="text-sm font-semibold tabular-nums text-[var(--color-foreground)]">
        {value}
      </span>
    </div>
  );
}

export function Header({ summary }: { summary: CostSummary | undefined }) {
  const priced = (summary?.priced_runs ?? 0) > 0;
  const costTitle = summary
    ? `Estimated at current API prices (as of ${summary.pricing_as_of}) from the token usage your agents report. ` +
      `Subscription plans are billed differently.` +
      (summary.priced_runs < summary.run_count
        ? ` ${summary.run_count - summary.priced_runs} runs have no token data and are not counted.`
        : '')
    : undefined;

  return (
    <header className="flex h-14 items-center justify-between border-b border-[var(--color-border)] px-6">
      {inDesktopApp ? (
        <span className="text-sm font-semibold tracking-tight text-[var(--color-foreground)]">
          Runs
        </span>
      ) : (
        <div className="flex items-center gap-2">
          <Activity className="h-5 w-5 text-[var(--color-primary)]" />
          <span className="text-sm font-semibold tracking-tight text-[var(--color-foreground)]">
            LoopPrism
          </span>
        </div>
      )}

      <div className="flex items-center gap-6">
        <Stat label="Runs" value={String(summary?.run_count ?? 0)} />
        <Stat label="Tool calls" value={String(summary?.tool_call_count ?? 0)} />
        <Stat
          label="Est. cost"
          value={priced ? formatUsd(summary!.estimated_cost_usd) : '—'}
          title={costTitle}
        />
      </div>
    </header>
  );
}
