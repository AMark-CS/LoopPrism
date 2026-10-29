import { useState } from 'react';
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useCostOverview, useOptimize } from '../hooks/useSessions';
import { Card, Empty } from '../components/ui';
import { formatTokens, formatUsd } from '../lib/format';
import { t } from '../lib/i18n';
import type { CostRow } from '../types/sessions';

const RANGES = [
  { days: 7, label: t('7 days') },
  { days: 30, label: t('30 days') },
  { days: 90, label: t('90 days') },
  { days: 0, label: t('All time') },
] as const;

const AGENTS: [string, string][] = [
  ['', t('All agents')],
  ['claude-code', 'Claude Code'],
  ['codex', 'Codex'],
  ['dsh', 'DeepSeek Harness'],
  ['workbuddy', 'WorkBuddy'],
  ['opencode', 'OpenCode'],
];
const AGENT_LABEL = Object.fromEntries(AGENTS);

const totalIn = (r: Pick<CostRow, 'input' | 'cache_read' | 'cache_write'>) => r.input + r.cache_read + r.cache_write;
const money = (v: number | null | undefined) => (v == null ? '—' : formatUsd(v));
const projectName = (p: string) => (p ? p.split(/[\\/]/).filter(Boolean).pop() ?? p : t('No project'));

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
                <span className="text-[var(--color-muted-foreground)]">{t('no price · {n} tok', { n: formatTokens(totalIn(r) + r.output) })}</span>
              ) : (
                <>
                  {formatUsd(r.cost)}
                  <span className="ml-2 text-[var(--color-muted-foreground)]">{t('{n} tok', { n: formatTokens(totalIn(r) + r.output) })}</span>
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

  const tt = data?.totals;
  const input = tt ? totalIn(tt) : 0;
  const cacheHit = tt && input ? (100 * tt.cache_read) / input : null;
  const hasData = !!tt && (tt.steps ?? 0) > 0;

  return (
    <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <div>
          <h1 className="text-lg font-semibold">{t('Cost')}</h1>
          <p className="text-xs text-[var(--color-muted-foreground)]">
            {t('Every session of every agent on this computer, priced at API list prices. An estimate of what the work would cost on the API: subscriptions and free tiers bill differently.')}
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

      {isLoading && <Empty>{t('Adding up your sessions…')}</Empty>}
      {!isLoading && !hasData && (
        <Empty>{agent ? t('No sessions with token usage in this period for {agent}.', { agent: AGENT_LABEL[agent] }) : t('No sessions with token usage in this period.')}</Empty>
      )}

      {hasData && tt && data && (
        <>
          {!!data.pending && (
            <div className="text-[11px] text-[var(--color-muted-foreground)]">{t('Still reading {n} sessions; the totals grow as they are indexed.', { n: data.pending })}</div>
          )}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
            <Tile label={t('Estimated spend')} value={money(tt.cost)} hint={tt.unpriced_steps ? t('{n} calls have no price', { n: tt.unpriced_steps }) : t('all calls priced')} />
            <Tile label={t('Sessions')} value={tt.sessions.toLocaleString()} hint={t('{n} model calls', { n: tt.steps.toLocaleString() })} />
            <Tile label={t('Input tokens')} value={formatTokens(input)} hint={t('{n} uncached', { n: formatTokens(tt.input) })} />
            <Tile label={t('Output tokens')} value={formatTokens(tt.output)} />
            <Tile label={t('Cache hit')} value={cacheHit == null ? '—' : `${cacheHit.toFixed(1)}%`} hint={t('of input read from cache')} />
            <Tile label={t('Per session')} value={tt.cost != null && tt.sessions ? formatUsd(tt.cost / tt.sessions) : '—'} hint={t('average')} />
          </div>

          {opt && opt.suggestions.length > 0 && (
            <a href="#/optimize" className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-[var(--color-primary)] bg-[var(--tone-primary-bg)] px-4 py-3 text-sm hover:opacity-90">
              <span className="font-medium text-[var(--tone-primary-fg)]">{t(opt.suggestions.length > 1 ? '{n} ways to spend less' : '{n} way to spend less', { n: opt.suggestions.length })}</span>
              <span className="text-[var(--color-foreground)]">{t('about {c} (−{p}%) in this period', { c: formatUsd(opt.saving_usd), p: opt.saving_pct })}</span>
              <span className="ml-auto text-xs text-[var(--tone-primary-fg)]">{t('See the suggestions →')}</span>
            </a>
          )}

          <Card title={t('Spend per day')}>
            <div className="h-48">
              <ResponsiveContainer>
                <BarChart data={perDay(data.by_day, days)} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                  <XAxis dataKey="day" tick={{ fontSize: 10, fill: 'var(--color-muted-foreground)' }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 10, fill: 'var(--color-muted-foreground)' }} axisLine={false} tickLine={false} width={46} tickFormatter={(v) => formatUsd(Number(v))} />
                  <Tooltip
                    cursor={{ fill: 'var(--hover)' }}
                    contentStyle={{ background: 'var(--tooltip-bg)', border: '1px solid var(--color-border)', fontSize: 11 }}
                    formatter={(v) => [formatUsd(Number(v)), t('Spend')]}
                  />
                  <Bar dataKey="cost" fill="#8b5cf6" radius={[2, 2, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title={t('By model')}>
              <Breakdown rows={data.by_model.slice(0, 12)} label={(k) => k} empty={t('No models.')} />
              {data.unpriced_models.length > 0 && (
                <p className="mt-3 text-[11px] text-[var(--color-muted-foreground)]">
                  {t('No price for {models}. Add one in', { models: data.unpriced_models.join(', ') })} <code>~/.loopprism/pricing.json</code> {t('and it is counted.')}
                </p>
              )}
            </Card>
            <Card title={t('By agent')}>
              <Breakdown rows={data.by_agent} label={(k) => AGENT_LABEL[k] ?? k} empty={t('No agents.')} />
            </Card>
            <Card title={t('By project')}>
              <Breakdown rows={data.by_project} label={(k) => projectName(k)} empty={t('No projects.')} />
            </Card>
            <Card title={t('Most expensive sessions')}>
              {data.top_sessions.length === 0 ? (
                <div className="text-xs text-[var(--color-muted-foreground)]">{t('No priced sessions.')}</div>
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
        {t('Runs recorded by the proxy and the hooks, including MCP tool calls:')} <a className="text-[var(--color-primary)] underline" href="#/live">{t('open the run viewer')}</a>.
      </div>
    </div>
  );
}
