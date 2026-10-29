import { useState } from 'react';
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useCostOverview, useOptimize } from '../hooks/useSessions';
import { Card, Empty } from '../components/ui';
import { formatTokens, formatUsd } from '../lib/format';
import type { CostRow } from '../types/sessions';

const RANGES = [
  { days: 7, label: '7 days' },
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
  { days: 0, label: 'All time' },
] as const;

const AGENTS: [string, string][] = [
  ['', 'All agents'],
  ['claude-code', 'Claude Code'],
  ['codex', 'Codex'],
  ['dsh', 'DeepSeek Harness'],
  ['workbuddy', 'WorkBuddy'],
  ['opencode', 'OpenCode'],
];
const AGENT_LABEL = Object.fromEntries(AGENTS);

const totalIn = (r: Pick<CostRow, 'input' | 'cache_read' | 'cache_write'>) => r.input + r.cache_read + r.cache_write;
const money = (v: number | null | undefined) => (v == null ? '—' : formatUsd(v));
const projectName = (p: string) => (p ? p.split(/[\\/]/).filter(Boolean).pop() ?? p : 'No project');

/** One bar per calendar day of the period, so quiet days show as gaps instead of vanishing. */
function perDay(rows: CostRow[], days: number) {
  const byKey = new Map(rows.map((r) => [r.key, r.cost ?? 0]));
  if (!days) return rows.map((r) => ({ day: r.key.slice(5), cost: r.cost ?? 0 }));
  const out = [];
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - (days - 1));
  for (let i = 0; i < days; i++) {
    const key = d.toISOString().slice(0, 10);
    out.push({ day: key.slice(5), cost: byKey.get(key) ?? 0 });
    d.setUTCDate(d.getUTCDate() + 1);
  }
  return out;
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-background)] p-3">
      <div className="text-[11px] text-[var(--color-muted-foreground)]">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="mt-0.5 text-[10px] text-[var(--color-muted-foreground)]">{hint}</div>}
    </div>
  );
}

/** Rows as horizontal bars, longest = the biggest spender. */
function Breakdown({ rows, label, empty }: { rows: CostRow[]; label: (k: string) => string; empty: string }) {
  const max = Math.max(...rows.map((r) => r.cost ?? 0), 0.000001);
  if (!rows.length) return <div className="text-xs text-[var(--color-muted-foreground)]">{empty}</div>;
  return (
    <div className="space-y-2">
      {rows.map((r) => (
        <div key={r.key}>
          <div className="flex items-baseline justify-between gap-3 text-xs">
            <span className="min-w-0 truncate" title={label(r.key)}>{label(r.key)}</span>
            <span className="shrink-0 tabular-nums">
              {r.cost == null ? (
                <span className="text-[var(--color-muted-foreground)]">no price · {formatTokens(totalIn(r) + r.output)} tok</span>
              ) : (
                <>
                  {formatUsd(r.cost)}
                  <span className="ml-2 text-[var(--color-muted-foreground)]">{formatTokens(totalIn(r) + r.output)} tok</span>
                </>
              )}
            </span>
          </div>
          <div className="mt-1 h-1.5 rounded-full bg-[var(--color-secondary)]">
            <div className="h-1.5 rounded-full bg-[var(--color-primary)]" style={{ width: `${Math.max(2, ((r.cost ?? 0) / max) * 100)}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

export function CostView() {
  const [days, setDays] = useState<number>(30);
  const [agent, setAgent] = useState('');
  const { data, isLoading } = useCostOverview(days, agent || undefined);
  const opt = useOptimize(days || 365, agent || undefined).data;

  const pill = (active: boolean) =>
    `rounded-full border px-2.5 py-0.5 text-[11px] ${
      active ? 'border-[var(--color-primary)] text-[var(--color-foreground)]' : 'border-[var(--color-border)] text-[var(--color-muted-foreground)]'
    }`;

  const t = data?.totals;
  const input = t ? totalIn(t) : 0;
  const cacheHit = t && input ? (100 * t.cache_read) / input : null;
  const hasData = !!t && (t.steps ?? 0) > 0;

  return (
    <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <div>
          <h1 className="text-lg font-semibold">Cost</h1>
          <p className="text-xs text-[var(--color-muted-foreground)]">
            Every session of every agent on this computer, priced at API list prices. An estimate of what the work would cost on the API:
            subscriptions and free tiers bill differently.
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          {RANGES.map((r) => (
            <button key={r.days} type="button" className={pill(days === r.days)} onClick={() => setDays(r.days)}>{r.label}</button>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {AGENTS.map(([k, label]) => (
          <button key={k} type="button" className={pill(agent === k)} onClick={() => setAgent(k)}>{label}</button>
        ))}
      </div>

      {isLoading && <Empty>Adding up your sessions…</Empty>}
      {!isLoading && !hasData && (
        <Empty>No sessions with token usage in this period{agent ? ` for ${AGENT_LABEL[agent]}` : ''}.</Empty>
      )}

      {hasData && t && data && (
        <>
          {!!data.pending && (
            <div className="text-[11px] text-[var(--color-muted-foreground)]">Still reading {data.pending} sessions; the totals grow as they are indexed.</div>
          )}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
            <Tile label="Estimated spend" value={money(t.cost)} hint={t.unpriced_steps ? `${t.unpriced_steps} calls have no price` : 'all calls priced'} />
            <Tile label="Sessions" value={t.sessions.toLocaleString()} hint={`${t.steps.toLocaleString()} model calls`} />
            <Tile label="Input tokens" value={formatTokens(input)} hint={`${formatTokens(t.input)} uncached`} />
            <Tile label="Output tokens" value={formatTokens(t.output)} />
            <Tile label="Cache hit" value={cacheHit == null ? '—' : `${cacheHit.toFixed(1)}%`} hint="of input read from cache" />
            <Tile label="Per session" value={t.cost != null && t.sessions ? formatUsd(t.cost / t.sessions) : '—'} hint="average" />
          </div>

          {opt && opt.suggestions.length > 0 && (
            <a href="#/optimize" className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-[var(--color-primary)] bg-[var(--tone-primary-bg)] px-4 py-3 text-sm hover:opacity-90">
              <span className="font-medium text-[var(--tone-primary-fg)]">{opt.suggestions.length} way{opt.suggestions.length > 1 ? 's' : ''} to spend less</span>
              <span className="text-[var(--color-foreground)]">about {formatUsd(opt.saving_usd)} (−{opt.saving_pct}%) in this period</span>
              <span className="ml-auto text-xs text-[var(--tone-primary-fg)]">See the suggestions →</span>
            </a>
          )}

          <Card title="Spend per day">
            <div className="h-48">
              <ResponsiveContainer>
                <BarChart data={perDay(data.by_day, days)} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                  <XAxis dataKey="day" tick={{ fontSize: 10, fill: 'var(--color-muted-foreground)' }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 10, fill: 'var(--color-muted-foreground)' }} axisLine={false} tickLine={false} width={46} tickFormatter={(v) => formatUsd(Number(v))} />
                  <Tooltip
                    cursor={{ fill: 'var(--hover)' }}
                    contentStyle={{ background: 'var(--tooltip-bg)', border: '1px solid var(--color-border)', fontSize: 11 }}
                    formatter={(v) => [formatUsd(Number(v)), 'Spend']}
                  />
                  <Bar dataKey="cost" fill="#8b5cf6" radius={[2, 2, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="By model">
              <Breakdown rows={data.by_model.slice(0, 12)} label={(k) => k} empty="No models." />
              {data.unpriced_models.length > 0 && (
                <p className="mt-3 text-[11px] text-[var(--color-muted-foreground)]">
                  No price for {data.unpriced_models.join(', ')}. Add one in <code>~/.loopprism/pricing.json</code> and it is counted.
                </p>
              )}
            </Card>
            <Card title="By agent">
              <Breakdown rows={data.by_agent} label={(k) => AGENT_LABEL[k] ?? k} empty="No agents." />
            </Card>
            <Card title="By project">
              <Breakdown rows={data.by_project} label={(k) => projectName(k)} empty="No projects." />
            </Card>
            <Card title="Most expensive sessions">
              {data.top_sessions.length === 0 ? (
                <div className="text-xs text-[var(--color-muted-foreground)]">No priced sessions.</div>
              ) : (
                <div className="space-y-1.5">
                  {data.top_sessions.map((s) => (
                    <a
                      key={s.id}
                      href={`#/sessions/${encodeURIComponent(s.id)}/context`}
                      className="flex items-baseline justify-between gap-3 rounded px-1.5 py-1 text-xs hover:bg-[var(--hover)]"
                    >
                      <span className="min-w-0 truncate">{s.title}<span className="ml-2 text-[10px] text-[var(--color-muted-foreground)]">{AGENT_LABEL[s.agent] ?? s.agent}</span></span>
                      <span className="shrink-0 tabular-nums">{formatUsd(s.cost)}</span>
                    </a>
                  ))}
                </div>
              )}
            </Card>
          </div>
        </>
      )}
      <div className="pb-2 text-[11px] text-[var(--color-muted-foreground)]">
        Runs recorded by the proxy and the hooks, including MCP tool calls: <a className="text-[var(--color-primary)] underline" href="#/live">open the run viewer</a>.
      </div>
    </div>
  );
}
