import { Activity, Terminal } from 'lucide-react';

export function EmptyState() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center p-8 text-center">
      <Activity className="h-12 w-12 text-[var(--color-muted)]" />
      <h2 className="mt-4 text-base font-semibold text-[var(--color-foreground)]">
        No traces yet
      </h2>
      <p className="mt-2 max-w-sm text-sm text-[var(--color-muted-foreground)]">
        Start the loopprism proxy to begin recording MCP calls.
      </p>

      <div className="mt-6 flex w-full max-w-md flex-col gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] p-4">
        <div className="flex items-center gap-2 text-xs font-medium text-[var(--color-foreground)]">
          <Terminal className="h-3.5 w-3.5 text-[var(--color-primary)]" />
          Quick start
        </div>
        <div className="flex flex-col gap-2 text-xs text-[var(--color-muted-foreground)]">
          <div className="flex items-center gap-2">
            <span className="shrink-0 rounded bg-[var(--color-muted)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-foreground)]">
              1
            </span>
            <span>Install from GitHub</span>
            <code className="ml-auto rounded bg-[var(--color-secondary)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-foreground)]">
              pip install "git+https://github.com/AMark-CS/LoopPrism.git"
            </code>
          </div>
          <div className="flex items-center gap-2">
            <span className="shrink-0 rounded bg-[var(--color-muted)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-foreground)]">
              2
            </span>
            <span>Start the proxy</span>
            <code className="ml-auto rounded bg-[var(--color-secondary)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-foreground)]">
              loopprism proxy --port 4317
            </code>
          </div>
          <div className="flex items-center gap-2">
            <span className="shrink-0 rounded bg-[var(--color-muted)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-foreground)]">
              3
            </span>
            <span>Point your MCP clients to</span>
            <code className="ml-auto rounded bg-[var(--color-secondary)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-foreground)]">
              http://localhost:4317
            </code>
          </div>
          <div className="flex items-center gap-2">
            <span className="shrink-0 rounded bg-[var(--color-muted)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-foreground)]">
              4
            </span>
            <span>Open the dashboard</span>
            <code className="ml-auto rounded bg-[var(--color-secondary)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-foreground)]">
              http://localhost:8080
            </code>
          </div>
        </div>
      </div>
    </div>
  );
}
