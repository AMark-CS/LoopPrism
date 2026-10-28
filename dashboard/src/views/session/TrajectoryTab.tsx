import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, ChevronRight, Info, Repeat, Search } from 'lucide-react';
import { api } from '@/lib/api';
import { useTrajectory } from '../../hooks/useSessions';
import { formatMs } from '../../lib/format';
import { Badge, Empty } from '../../components/ui';
import type { EventKind, Finding, SessionEvent, TrajectoryStep } from '../../types/sessions';

const KIND_STYLE: Record<string, { label: string; cls: string }> = {
  system: { label: 'SYSTEM', cls: 'bg-[#26262f] text-[#a1a1aa]' },
  user: { label: 'USER', cls: 'bg-[#16264d] text-[#7aa2f7]' },
  context: { label: 'CONTEXT', cls: 'bg-[#10301f] text-[#4ade80]' },
  assistant: { label: 'ASSISTANT', cls: 'bg-[#2b2150] text-[#b9a6ff]' },
  thinking: { label: 'THINKING', cls: 'bg-[#3a1a35] text-[#f0abfc]' },
  tool_call: { label: 'TOOL', cls: 'bg-[#3a2a0c] text-[#fbbf24]' },
  tool_result: { label: 'RESULT', cls: 'bg-[#3a2a0c] text-[#fbbf24]' },
  compaction: { label: 'COMPACT', cls: 'bg-[#3a1717] text-[#f87171]' },
  model_change: { label: 'MODEL', cls: 'bg-[#0c2f3a] text-[#67e8f9]' },
  system_event: { label: 'EVENT', cls: 'bg-[#1f1f28] text-[#71717a]' },
};

const FILTERS: { key: string; label: string; kinds: EventKind[] }[] = [
  { key: 'user', label: 'User', kinds: ['user'] },
  { key: 'assistant', label: 'Assistant', kinds: ['assistant', 'model_change'] },
  { key: 'tools', label: 'Tools', kinds: ['tool_call', 'tool_result'] },
  { key: 'context', label: 'Context', kinds: ['context', 'system', 'compaction'] },
  { key: 'thinking', label: 'Thinking', kinds: ['thinking'] },
  { key: 'events', label: 'Events', kinds: ['system_event'] },
];

function toolSummary(e: SessionEvent): string {
  const i = e.tool_input as Record<string, unknown> | string | undefined;
  if (typeof i === 'string') return `${e.tool_name} ${i}`;
  if (i && typeof i === 'object') {
    const v = i.command ?? i.file_path ?? i.path ?? i.pattern ?? i.query ?? i.description ?? i.cmd ?? i.url;
    if (typeof v === 'string') return `${e.tool_name} ${v}`;
    return `${e.tool_name} ${JSON.stringify(i)}`;
  }
  return e.tool_name ?? 'tool';
}

function Lanes({
  steps,
  onPick,
}: {
  steps: TrajectoryStep[];
  onPick: (s: TrajectoryStep) => void;
}) {
  const [mode, setMode] = useState<'duration' | 'steps'>('duration');
  const main = steps.filter((s) => !s.sidechain);
  const total = main.reduce((a, s) => a + (s.model_ms ?? 0) + (s.tools_ms ?? 0), 0) || 1;
  const width = (s: TrajectoryStep) =>
    mode === 'steps'
      ? 26
      : Math.max(6, (((s.model_ms ?? 0) + (s.tools_ms ?? 0)) / total) * Math.max(900, main.length * 10));
  let prevTurn = -1;
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex gap-1">
          {(['duration', 'steps'] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`rounded px-2 py-0.5 text-[11px] capitalize ${
                mode === m
                  ? 'bg-[var(--color-accent)] text-[var(--color-foreground)]'
                  : 'text-[var(--color-muted-foreground)]'
              }`}
            >
              {m}
            </button>
          ))}
        </div>
        <div className="flex gap-3 text-[10px] text-[var(--color-muted-foreground)]">
          <span><i className="mr-1 inline-block h-2 w-2 rounded-sm bg-[#3b82f6]" />prompt</span>
          <span><i className="mr-1 inline-block h-2 w-2 rounded-sm bg-[#22c55e]" />tool result</span>
          <span><i className="mr-1 inline-block h-2 w-2 rounded-sm bg-[#8b5cf6]" />model</span>
          <span><i className="mr-1 inline-block h-2 w-2 rounded-sm bg-[#f59e0b]" />tools</span>
        </div>
      </div>
      <div className="flex gap-2 overflow-x-auto pb-1">
        <div className="flex shrink-0 flex-col gap-1 pt-0.5 text-[10px] text-[var(--color-muted-foreground)]">
          <span className="h-3 leading-3">Input</span>
          <span className="h-3 leading-3">Model</span>
          <span className="h-3 leading-3">Tools</span>
        </div>
        <div className="flex items-start">
          {main.map((s) => {
            const w = width(s);
            const modelW = (s.model_ms ?? 0) + (s.tools_ms ?? 0) > 0
              ? (w * (s.model_ms ?? 0)) / ((s.model_ms ?? 0) + (s.tools_ms ?? 0))
              : w;
            const first = s.turn !== prevTurn;
            prevTurn = s.turn;
            return (
              <button
                key={s.step}
                type="button"
                title={`Step ${s.step + 1} · turn ${s.turn} · ${s.model}\nmodel ${formatMs(s.model_ms ?? 0)} · tools ${formatMs(s.tools_ms ?? 0)}\n${s.input_tokens.toLocaleString()} in / ${s.output_tokens.toLocaleString()} out`}
                onClick={() => onPick(s)}
                style={{ width: w, marginLeft: first ? 6 : 1 }}
                className="flex shrink-0 flex-col gap-1"
              >
                <span className={`h-3 w-full rounded-sm ${first ? 'bg-[#3b82f6]' : 'bg-[#22c55e]'}`} />
                <span className="h-3 rounded-sm bg-[#8b5cf6]" style={{ width: Math.max(2, modelW) }} />
                <span className="h-3 rounded-sm bg-[#f59e0b]" style={{ width: Math.max(0, w - modelW), marginLeft: modelW }} />
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function FindingChip({ f, onPick }: { f: Finding; onPick: (idx: number) => void }) {
  const Icon = f.kind === 'repeated_call' ? Repeat : f.severity === 'error' ? AlertTriangle : Info;
  const tone = f.severity === 'error' ? 'error' : f.severity === 'warn' ? 'warn' : 'muted';
  return (
    <button type="button" onClick={() => onPick(f.events[0])} title={`Turn ${f.turn}`}>
      <Badge tone={tone}>
        <Icon className="mr-1 h-3 w-3" />
        {f.title}
      </Badge>
    </button>
  );
}

function EventRow({
  e,
  result,
  id,
  focused,
}: {
  e: SessionEvent;
  result?: SessionEvent;
  id: string;
  focused: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const full = useQuery({
    queryKey: ['event', id, e.idx],
    queryFn: () => api.getSessionEvent(id, e.idx),
    enabled: open && (e.truncated ?? false),
  });
  const fullResult = useQuery({
    queryKey: ['event', id, result?.idx],
    queryFn: () => api.getSessionEvent(id, result!.idx),
    enabled: open && !!result?.truncated,
  });
  useEffect(() => {
    if (focused) {
      ref.current?.scrollIntoView({ block: 'center', behavior: 'smooth' });
      setOpen(true);
    }
  }, [focused]);
  const style = KIND_STYLE[e.kind] ?? KIND_STYLE.system_event;
  const isTool = e.kind === 'tool_call';
  const text = isTool ? toolSummary(e) : e.text;
  const body = (full.data ?? e).text;
  const resBody = (fullResult.data ?? result)?.text;
  return (
    <div
      ref={ref}
      className={`border-b border-[var(--color-border)] ${focused ? 'bg-[#1b1740]' : ''} ${e.sidechain ? 'opacity-70' : ''}`}
    >
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-[var(--color-accent)]"
      >
        <ChevronRight className={`h-3 w-3 shrink-0 text-[var(--color-muted-foreground)] transition-transform ${open ? 'rotate-90' : ''}`} />
        <span className={`w-[78px] shrink-0 rounded px-1.5 py-0.5 text-center text-[10px] font-semibold ${style.cls}`}>
          {style.label}
        </span>
        <span className="min-w-0 flex-1 truncate text-xs text-[var(--color-foreground)]">
          {text.replace(/\s+/g, ' ').slice(0, 300) || (e.kind === 'thinking' ? '(thinking)' : '')}
          {isTool && result && (
            <span className="text-[var(--color-muted-foreground)]">
              {' → '}
              {result.text.replace(/\s+/g, ' ').slice(0, 160)}
            </span>
          )}
        </span>
        {isTool && result?.is_error && <Badge tone="error">error</Badge>}
        {e.sidechain && <Badge>subagent</Badge>}
        {e.label && e.kind === 'context' && <Badge>{e.label}</Badge>}
      </button>
      {open && (
        <div className="space-y-2 border-t border-[var(--color-border)] bg-[var(--color-background)] px-4 py-3">
          {isTool ? (
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words text-[11px] text-[var(--color-muted-foreground)]">
              {JSON.stringify(e.tool_input, null, 2)}
            </pre>
          ) : (
            <pre className="max-h-[28rem] overflow-auto whitespace-pre-wrap break-words text-xs text-[var(--color-foreground)]">
              {body}
            </pre>
          )}
          {isTool && resBody !== undefined && (
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded bg-[var(--color-card)] p-2 text-[11px] text-[var(--color-foreground)]">
              {resBody}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

export function TrajectoryTab({ id, focus }: { id: string; focus: number | null }) {
  const traj = useTrajectory(id);
  const events = useQuery({
    queryKey: ['events', id],
    queryFn: () => api.getSessionEvents(id, { limit: 5000, preview: 300 }),
  });
  const [filters, setFilters] = useState<Set<string>>(new Set(['user', 'assistant', 'tools', 'context', 'thinking']));
  const [q, setQ] = useState('');
  const [focusIdx, setFocusIdx] = useState<number | null>(focus);
  const [shown, setShown] = useState(1500);
  useEffect(() => setFocusIdx(focus), [focus]);

  const rows = useMemo(() => {
    const all = events.data?.events ?? [];
    const results = new Map<string, SessionEvent>();
    for (const e of all) if (e.kind === 'tool_result' && e.tool_use_id) results.set(e.tool_use_id, e);
    const callIds = new Set(all.filter((e) => e.kind === 'tool_call').map((e) => e.tool_use_id));
    const kinds = new Set(FILTERS.filter((f) => filters.has(f.key)).flatMap((f) => f.kinds));
    const needle = q.trim().toLowerCase();
    return all
      .filter((e) => {
        // A result is shown inside its call's row.
        if (e.kind === 'tool_result' && callIds.has(e.tool_use_id)) return false;
        if (!kinds.has(e.kind)) return false;
        if (!needle) return true;
        const hay = `${e.text} ${e.tool_name ?? ''} ${JSON.stringify(e.tool_input ?? '')} ${results.get(e.tool_use_id ?? '')?.text ?? ''}`;
        return hay.toLowerCase().includes(needle);
      })
      .map((e) => ({ e, result: e.tool_use_id ? results.get(e.tool_use_id) : undefined }));
  }, [events.data, filters, q]);

  if (traj.isLoading || events.isLoading) return <Empty>Loading trajectory…</Empty>;
  if (!traj.data) return <Empty>No data.</Empty>;

  let lastTurn = -1;
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
      {traj.data.steps.length > 0 && (
        <Lanes steps={traj.data.steps} onPick={(s) => setFocusIdx(s.first_event)} />
      )}
      {traj.data.findings.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-muted-foreground)]">
            Worth a look
          </span>
          {traj.data.findings.slice(0, 12).map((f, i) => (
            <FindingChip key={i} f={f} onPick={setFocusIdx} />
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="absolute left-2 top-1.5 h-3.5 w-3.5 text-[var(--color-muted-foreground)]" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search this session"
            className="w-64 rounded-md border border-[var(--color-border)] bg-[var(--color-background)] py-1 pl-7 pr-2 text-xs outline-none focus:border-[var(--color-primary)]"
          />
        </div>
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            onClick={() => {
              const n = new Set(filters);
              if (n.has(f.key)) n.delete(f.key);
              else n.add(f.key);
              setFilters(n);
            }}
            className={`rounded-full border px-2.5 py-0.5 text-[11px] ${
              filters.has(f.key)
                ? 'border-[var(--color-primary)] text-[var(--color-foreground)]'
                : 'border-[var(--color-border)] text-[var(--color-muted-foreground)]'
            }`}
          >
            {f.label}
          </button>
        ))}
        <span className="ml-auto text-[11px] text-[var(--color-muted-foreground)]">
          {rows.length.toLocaleString()} rows
        </span>
      </div>
      <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-card)]">
        {rows.slice(0, shown).map(({ e, result }) => {
          const showTurn = e.turn !== lastTurn && e.turn > 0;
          lastTurn = e.turn;
          return (
            <div key={e.idx}>
              {showTurn && (
                <div className="border-b border-[var(--color-border)] bg-[var(--color-background)] px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-muted-foreground)]">
                  Turn {e.turn}
                </div>
              )}
              <EventRow e={e} result={result} id={id} focused={focusIdx === e.idx} />
            </div>
          );
        })}
        {rows.length > shown && (
          <button
            type="button"
            onClick={() => setShown(shown + 1500)}
            className="w-full p-3 text-xs text-[var(--color-muted-foreground)] hover:bg-[var(--color-accent)]"
          >
            Show more ({rows.length - shown} left)
          </button>
        )}
        {rows.length === 0 && (
          <div className="p-6 text-center text-xs text-[var(--color-muted-foreground)]">
            Nothing matches.
          </div>
        )}
      </div>
    </div>
  );
}
