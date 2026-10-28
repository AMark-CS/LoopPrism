import { Activity, Plug } from 'lucide-react';

// Inside the desktop app the dashboard is embedded in an iframe, and the app's
// "Apps" tab is where agents get connected.
const inDesktopApp = window.parent !== window;

export function EmptyState() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center p-8 text-center">
      <Activity className="h-12 w-12 text-[var(--color-muted)]" />
      <h2 className="mt-4 text-base font-semibold text-[var(--color-foreground)]">
        No runs yet
      </h2>
      <p className="mt-2 max-w-sm text-sm text-[var(--color-muted-foreground)]">
        LoopPrism is running. Runs show up here as soon as a connected agent
        does something.
      </p>

      {inDesktopApp ? (
        <button
          type="button"
          onClick={() =>
            window.parent.postMessage({ type: 'loopprism:open-apps' }, '*')
          }
          className="mt-6 inline-flex items-center gap-2 rounded-md bg-[var(--color-primary)] px-3 py-1.5 text-xs font-medium text-white hover:opacity-90"
        >
          <Plug className="h-3.5 w-3.5" />
          Choose apps to monitor
        </button>
      ) : (
        <div className="mt-6 flex w-full max-w-md flex-col gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] p-4 text-left text-xs text-[var(--color-muted-foreground)]">
          <div className="flex items-center gap-2">
            <span className="text-[var(--color-foreground)]">
              Claude Code / Codex
            </span>
            <code className="ml-auto rounded bg-[var(--color-secondary)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-foreground)]">
              npx loopprism install
            </code>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[var(--color-foreground)]">
              Any HTTP MCP client
            </span>
            <code className="ml-auto rounded bg-[var(--color-secondary)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-foreground)]">
              {window.location.protocol}//{window.location.hostname}:4317/&lt;server&gt;
            </code>
          </div>
        </div>
      )}
    </div>
  );
}
