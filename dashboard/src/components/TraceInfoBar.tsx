import { parseUtc } from '../lib/format';
import { formatDistanceToNow } from 'date-fns';
import { X, Clock, AlertCircle, Activity } from 'lucide-react';
import type { Trace } from '../types';

interface TraceInfoBarProps {
  trace: Trace;
  onClose: () => void;
}

export function TraceInfoBar({ trace, onClose }: TraceInfoBarProps) {
  return (
    <div className="flex h-12 items-center justify-between border-b border-[var(--color-border)] px-4">
      {/* Left: trace info */}
      <div className="flex min-w-0 flex-1 items-center gap-3">
        {/* Name */}
        <span className="truncate text-xs font-medium text-[var(--color-foreground)]">
          {trace.root_span_name ?? 'mcp_call'}
        </span>

        {/* Timestamp */}
        <span className="shrink-0 text-[10px] text-[var(--color-muted-foreground)]">
          {trace.timestamp
            ? formatDistanceToNow(parseUtc(trace.timestamp), { addSuffix: true })
            : ''}
        </span>

        {/* Error indicator */}
        {trace.error_count > 0 && (
          <span className="flex items-center gap-1 rounded bg-red-950/50 px-1.5 py-0.5 text-[10px] text-red-400">
            <AlertCircle className="h-3 w-3" />
            {trace.error_count} error{trace.error_count > 1 ? 's' : ''}
          </span>
        )}

        {/* Spans count */}
        <span className="flex items-center gap-1 text-[10px] text-[var(--color-muted-foreground)]">
          <Activity className="h-3 w-3" />
          {trace.span_count} spans
        </span>

        {/* Latency */}
        {trace.total_latency_ms != null && (
          <span className="flex items-center gap-1 text-[10px] text-[var(--color-muted-foreground)]">
            <Clock className="h-3 w-3" />
            {trace.total_latency_ms.toFixed(0)}ms
          </span>
        )}
      </div>

      {/* Right: close button */}
      <button
        onClick={onClose}
        className="ml-3 flex h-7 w-7 shrink-0 items-center justify-center rounded text-[var(--color-muted-foreground)] hover:bg-[var(--color-accent)] hover:text-[var(--color-foreground)]"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
