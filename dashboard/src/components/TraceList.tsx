import { formatDistanceToNow } from 'date-fns';
import { AlertCircle } from 'lucide-react';
import type { Trace } from '../types';
import { formatUsd, parseUtc } from '../lib/format';

interface TraceListProps {
  traces: Trace[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function TraceList({ traces, selectedId, onSelect }: TraceListProps) {
  return (
    <div className="flex flex-col">
      <div className="sticky top-0 z-10 flex h-9 items-center border-b border-[var(--color-border)] bg-[var(--color-background)] px-3">
        <span className="text-xs font-medium text-[var(--color-muted-foreground)]">
          {traces.length} traces
        </span>
      </div>

      {traces.map((trace) => (
        <button
          key={trace.id}
          onClick={() => onSelect(trace.id)}
          className={`flex w-full flex-col items-start gap-1 border-b border-[var(--color-border)] px-3 py-2.5 text-left transition-colors hover:bg-[var(--color-accent)] ${
            selectedId === trace.id
              ? 'bg-[var(--color-accent)]'
              : ''
          }`}
        >
          {/* Top row */}
          <div className="flex w-full items-center justify-between gap-2">
            <span className="truncate text-xs font-medium text-[var(--color-foreground)]">
              {trace.root_span_name ?? 'mcp_call'}
            </span>
            <div className="flex items-center gap-1 shrink-0">
              {trace.error_count > 0 && (
                <AlertCircle className="h-3 w-3 text-[var(--color-destructive)]" />
              )}
              {trace.total_latency_ms != null && (
                <span className="text-[10px] text-[var(--color-muted-foreground)]">
                  {trace.total_latency_ms.toFixed(0)}ms
                </span>
              )}
            </div>
          </div>

          {/* Bottom row */}
          <div className="flex w-full items-center justify-between">
            <span className="text-[10px] text-[var(--color-muted-foreground)]">
              {trace.timestamp
                ? formatDistanceToNow(parseUtc(trace.timestamp), { addSuffix: true })
                : ''}
            </span>
            <span className="text-[10px] text-[var(--color-muted-foreground)]">
              {trace.span_count} spans
              {trace.total_cost_usd != null && ` · ${formatUsd(trace.total_cost_usd)}`}
            </span>
          </div>
        </button>
      ))}
    </div>
  );
}
