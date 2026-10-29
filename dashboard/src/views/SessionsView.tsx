import { useEffect, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { formatDistanceToNow } from 'date-fns';
import { Download, FolderOpen, Play, Search, Trash2 } from 'lucide-react';
import { api } from '@/lib/api';
import { useSession, useSessionList } from '../hooks/useSessions';
import { formatUsd, parseUtc } from '../lib/format';
import { dateLocale, t } from '../lib/i18n';
import { useRoute } from '../lib/route';
import { Badge, Button, CopyButton, Empty } from '../components/ui';
import { ChatTab } from './session/ChatTab';
import { AgentsTab } from './session/AgentsTab';
import { ContextTab } from './session/ContextTab';
import { TrajectoryTab } from './session/TrajectoryTab';
import type { SessionSummary } from '../types/sessions';

const AGENT_LABEL: Record<string, string> = {
  'claude-code': 'Claude Code',
  codex: 'Codex',
  dsh: 'DeepSeek Harness',
  workbuddy: 'WorkBuddy',
  opencode: 'OpenCode',
};
const AGENT_TONE: Record<string, 'muted' | 'primary' | 'ok' | 'warn' | 'error'> = {
  'claude-code': 'muted',
  codex: 'primary',
  dsh: 'ok',
  workbuddy: 'warn',
  opencode: 'error',
};
const TABS = [
  { key: 'chat', label: t('Chat') },
  { key: 'trajectory', label: t('Trajectory') },
  { key: 'context', label: t('Context') },
  { key: 'agents', label: t('Agents') },
] as const;

const basename = (p: string | null) => (p ? p.split(/[\\/]/).filter(Boolean).pop() ?? p : t('No project'));
// Windows has a Recycle Bin, not a Trash.
const BIN = t(/Windows/i.test(navigator.userAgent) ? 'Recycle Bin' : 'Trash');
const ago = (s: SessionSummary) => {
  const ts = s.ended_at ?? s.started_at;
  return ts ? formatDistanceToNow(parseUtc(ts), { addSuffix: true, locale: dateLocale }) : '';
};

function dayLabel(s: SessionSummary): string {
  const ts = s.ended_at ?? s.started_at;
  if (!ts) return t('Unknown');
  const d = parseUtc(ts);
  const days = Math.floor((Date.now() - d.getTime()) / 86_400_000);
  if (days < 1) return t('Today');
  if (days < 2) return t('Yesterday');
  if (days < 7) return t('This week');
  if (days < 30) return t('This month');
  return t('Older');
}

function SessionList({
  activeId,
  onOpen,
}: {
  activeId: string | null;
  onOpen: (id: string) => void;
}) {
  const qc = useQueryClient();
  const [q, setQ] = useState('');
  const [debounced, setDebounced] = useState('');
  const [agent, setAgent] = useState<string>('');
  const [groupBy, setGroupBy] = useState<'time' | 'project'>('time');
  const [selecting, setSelecting] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [error, setError] = useState('');
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(q), 250);
    return () => clearTimeout(timer);
  }, [q]);
  const { data, isLoading } = useSessionList({ q: debounced || undefined, agent: agent || undefined });
  const sessions = data?.sessions ?? [];

  const groups = useMemo(() => {
    const m = new Map<string, SessionSummary[]>();
    for (const s of sessions) {
      const key = groupBy === 'time' ? dayLabel(s) : basename(s.project);
      m.set(key, [...(m.get(key) ?? []), s]);
    }
    return [...m.entries()];
  }, [sessions, groupBy]);

  async function deletePicked() {
    if (!picked.size) return;
    if (!window.confirm(t(picked.size > 1 ? 'Move {n} sessions to the {bin}?' : 'Move {n} session to the {bin}?', { n: picked.size, bin: BIN }))) return;
    setError('');
    for (const id of picked) {
      try {
        await api.deleteSession(id);
      } catch (e) {
        setError((e as Error).message);
      }
    }
    setPicked(new Set());
    setSelecting(false);
    qc.invalidateQueries({ queryKey: ['sessions'] });
  }

  return (
    <aside
      className={`${
        // Narrow window: show either the list or the open session, never both squeezed side by side.
        activeId ? 'hidden md:flex' : 'flex w-full'
      } shrink-0 flex-col border-r border-[var(--color-border)] md:w-80`}
    >
      <div className="space-y-2 border-b border-[var(--color-border)] p-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm font-semibold">
            {t('Sessions')}
            <Badge>{data?.total ?? 0}</Badge>
            {!!data?.pending && <span className="text-[10px] font-normal text-[var(--color-muted-foreground)]">{t('indexing {n}…', { n: data.pending })}</span>}
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setGroupBy(groupBy === 'time' ? 'project' : 'time')}
              title={t('Group by')}
              className="rounded p-1 text-[var(--color-muted-foreground)] hover:bg-[var(--color-accent)]"
            >
              <FolderOpen className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => {
                setSelecting(!selecting);
                setPicked(new Set());
              }}
              className={`rounded px-2 py-0.5 text-[11px] ${selecting ? 'bg-[var(--color-accent)]' : 'text-[var(--color-muted-foreground)]'}`}
            >
              {t('Select')}
            </button>
          </div>
        </div>
        <div className="relative">
          <Search className="absolute left-2 top-2 h-3.5 w-3.5 text-[var(--color-muted-foreground)]" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t('Search titles and messages')}
            className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-background)] py-1.5 pl-7 pr-2 text-xs outline-none focus:border-[var(--color-primary)]"
          />
        </div>
        <div className="flex flex-wrap gap-1">
          {[
            ['', t('All')],
            ['claude-code', 'Claude Code'],
            ['codex', 'Codex'],
            ['dsh', 'DeepSeek Harness'],
            ['workbuddy', 'WorkBuddy'],
            ['opencode', 'OpenCode'],
          ].map(([k, label]) => (
            <button
              key={k}
              type="button"
              onClick={() => setAgent(k)}
              className={`rounded-full border px-2.5 py-0.5 text-[11px] ${
                agent === k
                  ? 'border-[var(--color-primary)] text-[var(--color-foreground)]'
                  : 'border-[var(--color-border)] text-[var(--color-muted-foreground)]'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        {selecting && (
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-[var(--color-muted-foreground)]">{t('{n} selected', { n: picked.size })}</span>
            <Button tone="danger" disabled={!picked.size} onClick={deletePicked}>
              <Trash2 className="h-3 w-3" /> {t('Move to {bin}', { bin: BIN })}
            </Button>
          </div>
        )}
        {error && <div className="text-[11px] text-[var(--tone-error-fg)]">{error}</div>}
      </div>

      <div className="flex-1 overflow-y-auto">
        {isLoading && <Empty>{t('Loading sessions…')}</Empty>}
        {!isLoading && sessions.length === 0 && (
          <Empty>{debounced ? t('No sessions match.') : t('No agent sessions found on this computer.')}</Empty>
        )}
        {groups.map(([label, items]) => (
          <div key={label}>
            <div className="sticky top-0 z-10 bg-[var(--color-background)] px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-muted-foreground)]">
              {label}
            </div>
            {items.map((s) => (
              <div
                key={s.id}
                className={`flex gap-2 border-b border-[var(--color-border)] px-3 py-2.5 ${
                  activeId === s.id ? 'bg-[var(--color-accent)]' : 'hover:bg-[var(--hover)]'
                }`}
              >
                {selecting && (
                  <input
                    type="checkbox"
                    className="mt-1 shrink-0"
                    disabled={s.read_only}
                    title={s.read_only ? t('Read-only: delete it from its own app') : undefined}
                    checked={picked.has(s.id)}
                    onChange={(e) => {
                      const n = new Set(picked);
                      if (e.target.checked) n.add(s.id);
                      else n.delete(s.id);
                      setPicked(n);
                    }}
                  />
                )}
                <button type="button" onClick={() => onOpen(s.id)} className="min-w-0 flex-1 text-left">
                  <div className="truncate text-xs font-medium text-[var(--color-foreground)]">{s.title}</div>
                  {s.snippet && (
                    <div className="mt-0.5 line-clamp-2 text-[11px] text-[var(--color-muted-foreground)]">
                      {s.snippet}
                    </div>
                  )}
                  <div className="mt-1 flex items-center gap-2 text-[10px] text-[var(--color-muted-foreground)]">
                    <Badge tone={AGENT_TONE[s.agent] ?? 'muted'}>{AGENT_LABEL[s.agent] ?? s.agent}</Badge>
                    <span className="truncate">{basename(s.project)}</span>
                    <span className="ml-auto shrink-0">{ago(s)}</span>
                  </div>
                  <div className="mt-0.5 text-[10px] text-[var(--color-muted-foreground)]">
                    {t('{n} turns · {s} steps', { n: s.turns, s: s.steps })}{s.cost_usd != null && ` · ${formatUsd(s.cost_usd)}`}
                  </div>
                </button>
              </div>
            ))}
          </div>
        ))}
      </div>
    </aside>
  );
}

function SessionPane({ id, tab: tabProp, focus }: { id: string; tab: string; focus: number | null }) {
  let tab = tabProp;
  const qc = useQueryClient();
  const [, go] = useRoute();
  const { data, isLoading, error } = useSession(id);
  const [msg, setMsg] = useState('');
  if (isLoading) return <Empty>{t('Loading session…')}</Empty>;
  if (error || !data) return <Empty>{t('Session not found.')}</Empty>;
  const { session: s, stats, findings } = data;
  const isSub = id.includes('~'); // a subagent's own transcript, opened from the Agents tab
  const parentId = id.split('~')[0];
  const tabs = TABS.filter((x) => x.key !== 'agents' || (!isSub && s.agent === 'claude-code'));
  if (isSub && tab === 'agents') tab = 'chat';

  async function resume() {
    setMsg('');
    try {
      await api.resumeSession(id, true);
      setMsg(t('Opened in a terminal'));
    } catch (e) {
      setMsg((e as Error).message);
    }
  }
  async function remove() {
    if (!window.confirm(t('Move “{title}” to the {bin}?', { title: s.title, bin: BIN }))) return;
    try {
      await api.deleteSession(id);
      qc.invalidateQueries({ queryKey: ['sessions'] });
      go('sessions');
    } catch (e) {
      setMsg((e as Error).message);
    }
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <div className="space-y-2 border-b border-[var(--color-border)] px-5 py-3">
        {isSub && (
          <button
            type="button"
            onClick={() => go(`sessions/${parentId}/agents`)}
            className="text-xs text-[var(--color-primary)] hover:underline"
          >
            {t('← Back to the agent flow')}
          </button>
        )}
        <button
          type="button"
          onClick={() => go('sessions')}
          className="text-xs text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)] md:hidden"
        >
          {t('← All sessions')}
        </button>
        <div className="flex flex-wrap items-start justify-between gap-2 md:gap-4">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold">{s.title}</h2>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-[var(--color-muted-foreground)]">
              <Badge tone={AGENT_TONE[s.agent] ?? 'muted'}>{AGENT_LABEL[s.agent] ?? s.agent}</Badge>
              {s.started_at && <span>{parseUtc(s.started_at).toLocaleString()}</span>}
              {s.project && <span className="truncate font-mono">{s.project}</span>}
              {s.models.map((m) => (
                <Badge key={m}>{m}</Badge>
              ))}
              {s.cost_usd != null && <span>{t('{c} est.', { c: formatUsd(s.cost_usd) })}</span>}
            </div>
          </div>
          {!isSub && (
          <div className="flex shrink-0 items-center gap-2">
            {!s.read_only && (
              <Button tone="primary" onClick={resume} title={t('Open a new terminal window and resume this session')}>
                <Play className="h-3 w-3" /> {t('Resume')}
              </Button>
            )}
            <a
              href={`/api/sessions/${id}/export.md`}
              download={`${s.title.slice(0, 40)}.md`}
              className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-border)] px-3 py-1.5 text-xs font-medium hover:bg-[var(--color-accent)]"
            >
              <Download className="h-3 w-3" /> {t('Export')}
            </a>
            {!s.read_only && (
              <Button tone="danger" onClick={remove}>
                <Trash2 className="h-3 w-3" />
              </Button>
            )}
          </div>
          )}
        </div>
        {s.resume_command && (
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded-md bg-[var(--color-background)] px-2 py-1 font-mono text-[11px] text-[var(--color-muted-foreground)]">
              {s.resume_command}
            </code>
            <CopyButton text={s.resume_command} />
            {msg && <span className="text-[11px] text-[var(--color-muted-foreground)]">{msg}</span>}
          </div>
        )}
        {findings.filter((f) => f.severity !== 'info').length > 0 && tab === 'chat' && (
          <div className="text-[11px] text-[var(--tone-warn-fg)]">
            {t('{n} patterns worth a look — see Trajectory.', { n: findings.filter((f) => f.severity !== 'info').length })}
          </div>
        )}
      </div>
      <div className="flex gap-6 border-b border-[var(--color-border)] px-5">
        {tabs.map((x) => (
          <button
            key={x.key}
            type="button"
            onClick={() => go(`sessions/${id}/${x.key}`)}
            className={`-mb-px border-b-2 py-2.5 text-sm ${
              tab === x.key
                ? 'border-[var(--color-primary)] text-[var(--color-primary)]'
                : 'border-transparent text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]'
            }`}
          >
            {x.label}
          </button>
        ))}
        <span className="ml-auto self-center text-[11px] text-[var(--color-muted-foreground)]">
          {t('{a} turns · {b} steps · {c} tool calls', { a: stats.turns, b: stats.steps, c: stats.tool_calls })}
        </span>
      </div>
      <div className="flex min-h-0 flex-1 flex-col">
        {tab === 'chat' && <ChatTab id={id} />}
        {tab === 'trajectory' && <TrajectoryTab id={id} focus={focus} />}
        {tab === 'context' && <ContextTab id={id} />}
        {tab === 'agents' && <AgentsTab id={id} />}
      </div>
    </div>
  );
}

export function SessionsView() {
  const [seg, go] = useRoute();
  const id = seg[1] ?? null;
  const tab = TABS.some((x) => x.key === seg[2]) ? seg[2] : 'chat';
  const focus = seg[3] !== undefined && /^\d+$/.test(seg[3]) ? Number(seg[3]) : null;
  return (
    <div className="flex min-h-0 flex-1">
      <SessionList activeId={id} onOpen={(sid) => go(`sessions/${sid}/${tab}`)} />
      {id ? (
        <SessionPane key={id} id={id} tab={tab} focus={focus} />
      ) : (
        <div className="hidden min-w-0 flex-1 md:flex">
          <Empty>{t('Pick a session to inspect its chat, trajectory and context.')}</Empty>
        </div>
      )}
    </div>
  );
}
