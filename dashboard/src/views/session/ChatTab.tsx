import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ChevronRight } from 'lucide-react';
import { api } from '@/lib/api';
import { Empty } from '../../components/ui';
import type { SessionEvent } from '../../types/sessions';

function summarizeInput(e: SessionEvent): string {
  const i = e.tool_input as Record<string, unknown> | string | undefined;
  if (typeof i === 'string') return i.replace(/\s+/g, ' ').slice(0, 160);
  if (!i || typeof i !== 'object') return '';
  const v = i.command ?? i.file_path ?? i.path ?? i.pattern ?? i.query ?? i.description ?? i.cmd ?? i.url;
  if (typeof v === 'string') return v;
  return JSON.stringify(i).slice(0, 120);
}

function ToolRow({ call, result }: { call: SessionEvent; result?: SessionEvent }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-background)]">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs"
      >
        <ChevronRight className={`h-3 w-3 shrink-0 transition-transform ${open ? 'rotate-90' : ''}`} />
        <span className="rounded bg-[var(--tone-tool-bg)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--tone-tool-fg)]">
          {call.tool_name}
        </span>
        <span className="truncate font-mono text-[var(--color-muted-foreground)]">
          {summarizeInput(call)}
        </span>
        {result?.is_error && <span className="ml-auto text-[10px] text-[var(--tone-error-fg)]">error</span>}
      </button>
      {open && (
        <div className="space-y-2 border-t border-[var(--color-border)] p-2.5">
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words text-[11px] text-[var(--color-muted-foreground)]">
            {JSON.stringify(call.tool_input, null, 2)}
          </pre>
          {result && (
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-[var(--color-card)] p-2 text-[11px] text-[var(--color-foreground)]">
              {result.text}
              {result.truncated ? '\n…' : ''}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

export function ChatTab({ id }: { id: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['chat', id],
    queryFn: () =>
      api.getSessionEvents(id, {
        kinds: 'user,assistant,tool_call,tool_result',
        limit: 5000,
        preview: 6000,
      }),
  });

  const turns = useMemo(() => {
    const events = data?.events ?? [];
    const results = new Map<string, SessionEvent>();
    for (const e of events) if (e.kind === 'tool_result' && e.tool_use_id) results.set(e.tool_use_id, e);
    const out: { turn: number; items: (SessionEvent | { call: SessionEvent; result?: SessionEvent })[] }[] = [];
    for (const e of events) {
      if (e.sidechain || e.kind === 'tool_result') continue;
      if (e.kind === 'user' || out.length === 0) out.push({ turn: e.turn, items: [] });
      const cur = out[out.length - 1];
      cur.items.push(e.kind === 'tool_call' ? { call: e, result: results.get(e.tool_use_id ?? '') } : e);
    }
    return out;
  }, [data]);

  if (isLoading) return <Empty>Loading conversation…</Empty>;
  if (!turns.length) return <Empty>No messages in this session.</Empty>;

  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex-1 space-y-6 overflow-y-auto p-5">
        {turns.map((t, ti) => (
          <div key={ti} id={`turn-${ti}`} className="space-y-2">
            {t.items.map((it, i) => {
              if ('call' in it) return <ToolRow key={i} call={it.call} result={it.result} />;
              if (it.kind === 'user') {
                return (
                  <div
                    key={i}
                    className="rounded-lg border border-[var(--bubble-user-border)] bg-[var(--bubble-user-bg)] p-3 text-sm whitespace-pre-wrap break-words text-[var(--color-foreground)]"
                  >
                    <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--tone-user-fg)]">
                      User
                    </div>
                    {it.text}
                  </div>
                );
              }
              return (
                <div key={i} className="px-1 text-sm whitespace-pre-wrap break-words text-[var(--color-foreground)]">
                  {it.text}
                </div>
              );
            })}
          </div>
        ))}
      </div>
      <nav className="hidden w-56 shrink-0 overflow-y-auto border-l border-[var(--color-border)] p-3 xl:block">
        <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-muted-foreground)]">
          Contents
        </div>
        {turns.map((t, ti) => {
          const first = t.items.find((x) => 'kind' in x && x.kind === 'user') as SessionEvent | undefined;
          return (
            <button
              key={ti}
              type="button"
              onClick={() => document.getElementById(`turn-${ti}`)?.scrollIntoView({ behavior: 'smooth' })}
              className="flex w-full gap-2 py-1 text-left text-xs text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]"
            >
              <span className="shrink-0 tabular-nums opacity-60">{ti + 1}</span>
              <span className="truncate">{first?.text.slice(0, 60) || '(no prompt)'}</span>
            </button>
          );
        })}
      </nav>
    </div>
  );
}
