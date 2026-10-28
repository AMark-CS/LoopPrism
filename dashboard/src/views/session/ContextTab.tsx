import { useEffect, useMemo, useState } from 'react';
import { Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { ChevronRight, HelpCircle } from 'lucide-react';
import { useContextOverview, useStepContext, useTiming } from '../../hooks/useSessions';
import { Badge, Card, Empty } from '../../components/ui';
import {
  CATEGORY_COLORS,
  CATEGORY_LABELS,
  formatMs,
  formatTokens,
  formatUsd,
} from '../../lib/format';
import type { CategoryKey, StepContext, TrendPoint } from '../../types/sessions';

const ORDER: CategoryKey[] = [
  'system_prompt',
  'tool_schemas',
  'user',
  'injected',
  'skills',
  'assistant',
  'tool_results',
  'unattributed',
];

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-background)] p-3" title={hint}>
      <div className="flex items-center justify-between text-[11px] text-[var(--color-muted-foreground)]">
        {label}
        {hint && <HelpCircle className="h-3 w-3 opacity-60" />}
      </div>
      <div className="mt-2 text-center text-lg font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function Donut({
  data,
  center,
  sub,
}: {
  data: { key: string; value: number }[];
  center: string;
  sub: string;
}) {
  return (
    <div className="relative h-32 w-32 shrink-0">
      <ResponsiveContainer>
        <PieChart>
          <Pie data={data} dataKey="value" innerRadius={42} outerRadius={60} stroke="none" paddingAngle={1}>
            {data.map((d) => (
              <Cell key={d.key} fill={CATEGORY_COLORS[d.key] ?? '#6b7280'} />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-sm font-semibold">{center}</span>
        <span className="text-[10px] text-[var(--color-muted-foreground)]">{sub}</span>
      </div>
    </div>
  );
}

function Legend({ step }: { step: StepContext }) {
  return (
    <div className="grid flex-1 grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
      {ORDER.map((k) => {
        const c = step.categories.find((x) => x.key === k);
        if (!c) return null;
        return (
          <div key={k} className="min-w-0">
            <div className="flex items-center gap-1.5 text-xs">
              <i className="inline-block h-2 w-2 rounded-sm" style={{ background: CATEGORY_COLORS[k] }} />
              <span className="truncate">{CATEGORY_LABELS[k]}</span>
              <span className="ml-auto tabular-nums text-[var(--color-foreground)]">{c.pct}%</span>
            </div>
            <div className="pl-3.5 text-[11px] tabular-nums text-[var(--color-muted-foreground)]">
              ≈{formatTokens(c.tokens)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ContextBar({ step }: { step: StepContext }) {
  const window = step.window ?? Math.max(step.actual_input, 1);
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <div>
          <span className="text-2xl font-semibold tabular-nums">{formatTokens(step.actual_input)}</span>
          <span className="ml-1 text-sm text-[var(--color-muted-foreground)]">
            / {step.window ? formatTokens(step.window) : '?'} tokens
          </span>
        </div>
        {step.window_pct != null && (
          <div className="text-right">
            <span className="text-2xl font-semibold tabular-nums">{Math.round(step.window_pct)}%</span>
            <span className="ml-1 text-xs text-[var(--color-muted-foreground)]">of context used</span>
          </div>
        )}
      </div>
      <div className="mt-2 flex h-3 w-full overflow-hidden rounded bg-[var(--color-background)]">
        {ORDER.map((k) => {
          const c = step.categories.find((x) => x.key === k);
          if (!c || !c.tokens) return null;
          return (
            <div
              key={k}
              title={`${CATEGORY_LABELS[k]} ≈${formatTokens(c.tokens)}`}
              style={{ width: `${(c.tokens / window) * 100}%`, background: CATEGORY_COLORS[k] }}
            />
          );
        })}
      </div>
      {step.window_source === 'assumed' && (
        <div className="mt-1 text-[10px] text-[var(--color-muted-foreground)]">
          Context window assumed for this model.
        </div>
      )}
    </div>
  );
}

function Trend({
  trend,
  selected,
  onSelect,
}: {
  trend: TrendPoint[];
  selected: number | null;
  onSelect: (step: number) => void;
}) {
  const [mode, setMode] = useState<'total' | 'delta'>('total');
  const data = useMemo(
    () =>
      trend
        .filter((p) => !p.sidechain)
        .slice(-300)
        .map((p) => ({
          step: p.step,
          label: `${p.step + 1}`,
          delta: Math.max(0, p.delta),
          ...p.categories,
        })),
    [trend],
  );
  return (
    <Card
      title="Context Trend"
      right={
        <div className="flex gap-1">
          {(['total', 'delta'] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`rounded px-2 py-0.5 text-[11px] capitalize ${
                mode === m ? 'bg-[var(--color-foreground)] text-[var(--color-background)]' : 'text-[var(--color-muted-foreground)]'
              }`}
            >
              {m}
            </button>
          ))}
        </div>
      }
    >
      <div className="h-52">
        <ResponsiveContainer>
          <BarChart
            data={data}
            margin={{ top: 4, right: 4, left: 0, bottom: 0 }}
            onClick={(s) => {
              const step = (s as unknown as { activePayload?: { payload: { step: number } }[] })?.activePayload?.[0]?.payload.step;
              if (step !== undefined) onSelect(step);
            }}
          >
            <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#71717a' }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 10, fill: '#71717a' }} axisLine={false} tickLine={false} width={42} tickFormatter={(v) => formatTokens(Number(v))} />
            <Tooltip
              cursor={{ fill: '#ffffff10' }}
              contentStyle={{ background: '#16161e', border: '1px solid #27273a', fontSize: 11 }}
              formatter={(v, name) => [formatTokens(Number(v)), CATEGORY_LABELS[String(name)] ?? String(name)]}
              labelFormatter={(l) => `Step ${l}`}
            />
            {mode === 'total' ? (
              ORDER.map((k) => (
                <Bar key={k} dataKey={k} stackId="a" fill={CATEGORY_COLORS[k]}>
                  {data.map((d) => (
                    <Cell key={d.step} fillOpacity={selected === null || selected === d.step ? 1 : 0.55} />
                  ))}
                </Bar>
              ))
            ) : (
              <Bar dataKey="delta" fill="#8b5cf6" />
            )}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function Browser({ id, step }: { id: string; step: number }) {
  const cur = useStepContext(id, step);
  const prev = useStepContext(id, step > 0 ? step - 1 : null);
  const [open, setOpen] = useState<Set<string>>(new Set());
  if (cur.isLoading) return <Empty>Loading step…</Empty>;
  if (!cur.data) return null;
  const c = cur.data;
  const prevItems = (k: CategoryKey) => prev.data?.categories.find((x) => x.key === k)?.items ?? 0;
  return (
    <Card
      title="Context Browser"
      right={
        <div className="flex items-center gap-2 text-[11px] text-[var(--color-muted-foreground)]">
          <Badge tone={c.exact_request ? 'ok' : 'warn'} title={c.exact_request ? 'The real request is recorded in the session file.' : 'The system prompt and tool schemas are not recorded; they are inferred.'}>
            {c.exact_request ? 'Exact request' : 'Estimated'}
          </Badge>
          Step {c.step + 1} · Estimated ≈{formatTokens(c.estimated_input)} · Actual {formatTokens(c.actual_input)}
        </div>
      }
    >
      <div className="space-y-1.5">
        {ORDER.map((k) => {
          const cat = c.categories.find((x) => x.key === k);
          const items = c.items?.[k];
          if (!cat || !items) return null;
          const isOpen = open.has(k);
          const added = step > 0 ? cat.items - prevItems(k) : 0;
          return (
            <div key={k} className="rounded-md border border-[var(--color-border)] bg-[var(--color-background)]">
              <button
                type="button"
                onClick={() => {
                  const n = new Set(open);
                  if (n.has(k)) n.delete(k);
                  else n.add(k);
                  setOpen(n);
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs"
              >
                <ChevronRight className={`h-3 w-3 transition-transform ${isOpen ? 'rotate-90' : ''}`} />
                <i className="inline-block h-2 w-2 rounded-sm" style={{ background: CATEGORY_COLORS[k] }} />
                <span className="font-medium">{CATEGORY_LABELS[k]}</span>
                <span className="text-[var(--color-muted-foreground)]">{cat.items} items</span>
                {added > 0 && <Badge tone="ok">+{added}</Badge>}
                <span className="ml-auto tabular-nums text-[var(--color-muted-foreground)]">
                  ≈{formatTokens(cat.tokens)} · {cat.pct}%
                </span>
              </button>
              {isOpen && (
                <div className="max-h-72 divide-y divide-[var(--color-border)] overflow-y-auto border-t border-[var(--color-border)]">
                  {items.slice(0, 400).map((it, i) => (
                    <div key={i} className="flex gap-3 px-3 py-1.5 text-[11px]">
                      <span className="w-40 shrink-0 truncate text-[var(--color-muted-foreground)]">{it.label}</span>
                      <span className="min-w-0 flex-1 truncate font-mono text-[var(--color-foreground)]">{it.preview}</span>
                      <span className="shrink-0 tabular-nums text-[var(--color-muted-foreground)]">≈{formatTokens(it.tokens)}</span>
                    </div>
                  ))}
                  {items.length > 400 && (
                    <div className="px-3 py-1.5 text-[11px] text-[var(--color-muted-foreground)]">
                      … {items.length - 400} more
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}

export function ContextTab({ id }: { id: string }) {
  const overview = useContextOverview(id);
  const timing = useTiming(id);
  const [selected, setSelected] = useState<number | null>(null);
  const lastStep = useMemo(() => {
    const t = overview.data?.trend.filter((p) => !p.sidechain) ?? [];
    return t.length ? t[t.length - 1].step : null;
  }, [overview.data]);
  useEffect(() => setSelected(null), [id]);
  const step = selected ?? lastStep;
  const stepCtx = useStepContext(id, step);

  if (overview.isLoading) return <Empty>Analysing context…</Empty>;
  if (!overview.data) return <Empty>No data.</Empty>;
  const { stats, trend } = overview.data;
  if (!trend.length) return <Empty>This session has no model calls yet.</Empty>;
  const t = timing.data;

  return (
    <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
      <Card title="Context Stats" right={<Badge tone={stats.fidelity === 'exact' ? 'ok' : 'warn'}>{stats.fidelity === 'exact' ? 'Exact requests' : 'Estimated'}</Badge>}>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-7">
          <Stat label="Turns" value={String(stats.turns)} />
          <Stat label="Steps" value={String(stats.steps)} hint="Model calls (one per assistant response)" />
          <Stat label="Human inputs" value={String(stats.human_inputs)} />
          <Stat label="Tool calls" value={String(stats.tool_calls)} />
          <Stat label="Cache hit" value={stats.cache_hit_pct != null ? `${stats.cache_hit_pct}%` : '—'} hint="Share of input tokens served from the prompt cache" />
          <Stat label="Cost" value={stats.cost_usd != null ? formatUsd(stats.cost_usd) : '—'} hint="Estimated at current API prices" />
          <Stat label="Subagent cost" value={stats.subagent_cost_usd != null ? formatUsd(stats.subagent_cost_usd) : '—'} />
        </div>
      </Card>

      <div className="grid gap-3 lg:grid-cols-2">
        <Card title="Token Stats" right={step !== null && <span className="text-[11px] text-[var(--color-muted-foreground)]">Step {step + 1}</span>}>
          {stepCtx.data ? (
            <div className="flex items-center gap-5">
              <Donut
                data={stepCtx.data.categories.map((c) => ({ key: c.key, value: Math.max(c.tokens, 0) }))}
                center={formatTokens(stepCtx.data.actual_input)}
                sub="Total"
              />
              <Legend step={stepCtx.data} />
            </div>
          ) : (
            <Empty>…</Empty>
          )}
        </Card>
        <Card
          title="Timing Stats"
          right={t?.tokens_per_second ? <Badge>{t.tokens_per_second} tok/s</Badge> : undefined}
        >
          {t ? (
            <div className="flex items-center gap-5">
              <Donut
                data={[
                  { key: 'assistant', value: t.thinking_ms },
                  { key: 'user', value: t.answer_ms },
                  { key: 'tool_schemas', value: t.tools_ms },
                  { key: 'unattributed', value: t.overhead_ms },
                ]}
                center={formatMs(t.model_ms + t.tools_ms)}
                sub="Active time"
              />
              <div className="grid flex-1 grid-cols-2 gap-x-6 gap-y-3 text-xs">
                {[
                  ['assistant', 'Thinking', t.thinking_ms],
                  ['user', 'Answer', t.answer_ms],
                  ['tool_schemas', 'Tool runs', t.tools_ms],
                  ['unattributed', 'Overhead', t.overhead_ms],
                ].map(([k, label, ms]) => (
                  <div key={String(k)}>
                    <div className="flex items-center gap-1.5">
                      <i className="inline-block h-2 w-2 rounded-sm" style={{ background: CATEGORY_COLORS[String(k)] }} />
                      {label}
                      <span className="ml-auto tabular-nums">
                        {t.wall_ms ? `${Math.round((Number(ms) / (t.wall_ms || 1)) * 100)}%` : ''}
                      </span>
                    </div>
                    <div className="pl-3.5 text-[11px] tabular-nums text-[var(--color-muted-foreground)]">
                      {formatMs(Number(ms))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <Empty>…</Empty>
          )}
          <div className="mt-2 text-[10px] text-[var(--color-muted-foreground)]">
            From session timestamps. Time to first token needs the API capture proxy.
          </div>
        </Card>
      </div>

      <Card title="Current Context" right={stepCtx.data && <span className="text-[11px] text-[var(--color-muted-foreground)]">{stepCtx.data.model}</span>}>
        {stepCtx.data ? <ContextBar step={stepCtx.data} /> : <Empty>…</Empty>}
      </Card>

      <Trend trend={trend} selected={step} onSelect={setSelected} />

      {step !== null && <Browser id={id} step={step} />}
    </div>
  );
}
