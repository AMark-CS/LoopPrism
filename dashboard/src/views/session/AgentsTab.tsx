import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowDownLeft, ArrowUpRight, Bot, Brain, Eye, FileSearch, FileText, FlaskConical, Pause, Play, Search } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useAgents } from '../../hooks/useSessions';
import { useRoute } from '../../lib/route';
import { Badge, Button, Card, Empty } from '../../components/ui';
import { formatMs, formatTokens, formatUsd } from '../../lib/format';
import { layoutAgents, MAIN_COLOR } from '../../lib/agentLayout';
import type { Placed } from '../../lib/agentLayout';
import type { AgentNode } from '../../types/sessions';

const ICONS: Record<string, LucideIcon> = { main: Brain, search: Search, review: Eye, test: FlaskConical, docs: FileText, plan: FileSearch, bot: Bot };

function iconKey(a: AgentNode): string {
  if (a.parent_id === null) return 'main';
  const k = `${a.role} ${a.name}`.toLowerCase();
  if (/explor|search|research|find|map/.test(k)) return 'search';
  if (/review|audit|check/.test(k)) return 'review';
  if (/test|qa|verify/.test(k)) return 'test';
  if (/doc|write|note|readme|draft/.test(k)) return 'docs';
  if (/plan|design|architect/.test(k)) return 'plan';
  return 'bot';
}

const pct = (n: number, total: number) => `${(n / total) * 100}%`;
const meta = (a: AgentNode) =>
  [
    a.cost_usd != null ? formatUsd(a.cost_usd) : null,
    a.tokens.total ? `${formatTokens(a.tokens.total)} tok` : null,
    a.duration_ms != null ? formatMs(a.duration_ms) : null,
  ]
    .filter(Boolean)
    .join(' · ');

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-background)] p-3" title={hint}>
      <div className="text-[11px] text-[var(--color-muted-foreground)]">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums">{value}</div>
    </div>
  );
}

export function AgentsTab({ id }: { id: string }) {
  const { data, isLoading, error } = useAgents(id);
  if (isLoading) return <Empty>Reading subagent transcripts…</Empty>;
  if (error || !data) return <Empty>Could not read the agent tree.</Empty>;
  if (!data.supported) return <Empty>{data.reason}</Empty>;
  if (data.totals.subagents === 0) return <Empty>This session did not spawn any subagents.</Empty>;
  return <Tree id={id} tree={data} />;
}

function Tree({ id, tree }: { id: string; tree: NonNullable<ReturnType<typeof useAgents>['data']> }) {
  const layout = useMemo(() => layoutAgents(tree.agents), [tree.agents]);
  const [selected, setSelected] = useState<string>(() => tree.agents.find((a) => a.parent_id !== null)?.id ?? 'main');
  const [playing, setPlaying] = useState(true);
  if (!layout) return <Empty>No agents found.</Empty>;
  const t = tree.totals;
  const all = [layout.main, ...layout.placed];
  const costTotal = t.total_cost_usd ?? 0;
  const current = all.find((p) => p.agent.id === selected) ?? layout.main;

  return (
    <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
      <Card title="Agent summary">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label="Subagents" value={String(t.subagents)} />
          <Stat label="Peak parallel" value={String(t.peak_parallel)} hint="Most subagents running at the same moment" />
          <Stat
            label="Subagent cost"
            value={t.subagent_cost_usd != null ? formatUsd(t.subagent_cost_usd) : '—'}
            hint="Estimated at current API prices; models without a published price are not counted"
          />
          <Stat label="Passed between agents" value={`~${formatTokens(t.passed_tokens)} tok`} hint="Tasks handed out plus results returned (estimated)" />
        </div>
        {costTotal > 0 && (
          <>
            <div className="mt-3 flex h-1.5 gap-0.5 overflow-hidden rounded-full" aria-hidden="true">
              {all.filter((p) => p.agent.cost_usd).map((p) => (
                <i key={p.agent.id} style={{ width: pct(p.agent.cost_usd ?? 0, costTotal), background: p.color }} />
              ))}
            </div>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[var(--color-muted-foreground)]">
              {all.filter((p) => p.agent.cost_usd).map((p) => (
                <span key={p.agent.id} className="inline-flex items-center gap-1.5">
                  <i className="inline-block h-2 w-2 rounded-sm" style={{ background: p.color }} />
                  {p.agent.name} {formatUsd(p.agent.cost_usd ?? 0)}
                </span>
              ))}
            </div>
          </>
        )}
      </Card>

      <Card
        title="Agent flow"
        right={
          <div className="flex items-center gap-3">
            <span className="text-[11px] text-[var(--color-muted-foreground)]">Click an agent for details</span>
            <Button onClick={() => setPlaying((p) => !p)} title={playing ? 'Pause the moving dots' : 'Play the moving dots'}>
              {playing ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />} {playing ? 'Pause flow' : 'Play flow'}
            </Button>
          </div>
        }
      >
        <Flow layout={layout} selected={selected} onSelect={setSelected} playing={playing} />
        <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[var(--color-muted-foreground)]">
          <span><i className="mr-1.5 inline-block h-2 w-2 rounded-full bg-[#a1a1aa]" />task out</span>
          <span><i className="mr-1.5 inline-block h-2 w-2 rounded-full border-2 border-[#a1a1aa]" />result back</span>
          <span>line weight = cost</span>
          <span><i className="mr-1.5 inline-block h-2 w-3.5 rounded-sm border border-dashed border-[#7c3aed99] bg-[#7c3aed22]" />agents running in parallel</span>
          <span>time runs left to right</span>
        </div>
      </Card>

      <Detail id={id} placed={current} />
    </div>
  );
}

function Flow({ layout, selected, onSelect, playing }: { layout: NonNullable<ReturnType<typeof layoutAgents>>; selected: string; onSelect: (id: string) => void; playing: boolean }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const fxRef = useRef<SVGGElement>(null);
  const playingRef = useRef(playing);
  useEffect(() => {
    playingRef.current = playing;
  }, [playing]);
  const { width: W, height: H } = layout;

  // Dots that carry the task out, pulse along the lane while the agent works, and carry the result back.
  useEffect(() => {
    const svg = svgRef.current;
    const fx = fxRef.current;
    if (!svg || !fx) return;
    const NS = 'http://www.w3.org/2000/svg';
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const items = layout.placed
      .filter((p) => !p.open)
      .map((p, i) => {
        const path = (s: string) => svg.querySelector<SVGPathElement>(`[data-flow="${p.agent.id}-${s}"]`);
        const segs = [path('out'), path('lane'), path('back')];
        if (segs.some((s) => !s)) return null;
        const mk = () => fx.appendChild(document.createElementNS(NS, 'circle'));
        return {
          p, segs: segs as SVGPathElement[], lens: segs.map((s) => s!.getTotalLength()),
          halo: mk(), trail: [mk(), mk(), mk()], ring: mk(),
          period: 6 + (i % 4) * 1.3, offset: (i * 1.7) % 6,
          task: 3 + Math.min(2, (p.agent.task?.tokens ?? 0) / 800),
          res: 3 + Math.min(3, (p.agent.result?.tokens ?? 0) / 1500),
        };
      })
      .filter((v): v is NonNullable<typeof v> => v !== null);
    const mainFlow = svg.querySelector<SVGPathElement>('[data-flow="main"]');
    const bubble = (id: string) => svg.parentElement?.querySelector<HTMLElement>(`[data-bubble="${CSS.escape(id)}"]`) ?? null;
    const point = (it: (typeof items)[number], s: number, f: number) =>
      it.segs[s].getPointAtLength(it.lens[s] * Math.min(1, Math.max(0, f)));

    const draw = (sec: number) => {
      if (mainFlow) mainFlow.style.strokeDashoffset = String((-sec * 18) % 24);
      for (const it of items) {
        const u = ((sec + it.offset) % it.period) / it.period;
        const hide = (el: SVGElement) => el.setAttribute('opacity', '0');
        it.trail.forEach(hide);
        hide(it.halo);
        hide(it.ring);
        let seg = -1;
        let f = 0;
        if (u < 0.15) { seg = 0; f = u / 0.15; }
        else if (u < 0.75) { seg = 1; f = (u - 0.15) / 0.6; }
        else if (u < 0.9) { seg = 2; f = (u - 0.75) / 0.15; }
        const b = bubble(it.p.agent.id);
        if (b) b.style.boxShadow = seg === 1 ? `0 0 0 3px ${it.p.color}44` : 'none';
        if (seg < 0) continue;
        if (seg === 1) {
          const pt = point(it, 1, f);
          it.ring.setAttribute('cx', String(pt.x));
          it.ring.setAttribute('cy', String(pt.y));
          it.ring.setAttribute('r', String(3 + 1.5 * Math.sin(sec * 6)));
          it.ring.setAttribute('fill', 'none');
          it.ring.setAttribute('stroke', it.p.color);
          it.ring.setAttribute('stroke-width', '2');
          it.ring.setAttribute('opacity', '0.9');
          continue;
        }
        const r = seg === 0 ? it.task : it.res;
        const h = point(it, seg, f);
        it.halo.setAttribute('cx', String(h.x));
        it.halo.setAttribute('cy', String(h.y));
        it.halo.setAttribute('r', String(r * 2.4));
        it.halo.setAttribute('fill', it.p.color);
        it.halo.setAttribute('opacity', '0.16');
        it.trail.forEach((el, i) => {
          const pt = point(it, seg, f - i * 0.07);
          el.setAttribute('cx', String(pt.x));
          el.setAttribute('cy', String(pt.y));
          el.setAttribute('r', String(r * (1 - i * 0.25)));
          if (seg === 2) {
            el.setAttribute('fill', '#111118');
            el.setAttribute('stroke', it.p.color);
            el.setAttribute('stroke-width', '2');
          } else {
            el.setAttribute('fill', it.p.color);
            el.removeAttribute('stroke');
          }
          el.setAttribute('opacity', String((1 - i * 0.35) * (f - i * 0.07 >= 0 ? 1 : 0)));
        });
      }
    };

    if (reduce) {
      draw(1.2);
      return () => fx.replaceChildren();
    }
    let raf = 0;
    let elapsed = 0;
    let last = performance.now();
    const loop = (now: number) => {
      if (playingRef.current) {
        elapsed += (now - last) / 1000;
        draw(elapsed);
      }
      last = now;
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      fx.replaceChildren();
      for (const it of items) {
        const b = bubble(it.p.agent.id);
        if (b) b.style.boxShadow = 'none';
      }
    };
  }, [layout]);

  const all = [layout.main, ...layout.placed];
  const pos = (x: number, y: number): React.CSSProperties => ({ left: `${(x / W) * 100}%`, top: `${(y / H) * 100}%` });

  return (
    <div className="overflow-x-auto">
      <div className="relative min-w-[680px]" style={{ aspectRatio: `${W} / ${H}` }}>
        <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} className="absolute inset-0 h-full w-full" aria-hidden="true">
          {layout.bands.map((b, i) => (
            <rect key={i} x={b.x0} y={layout.bandTop} width={b.x1 - b.x0} height={layout.bandBottom - layout.bandTop} rx={14}
              fill="#7c3aed" fillOpacity={0.07} stroke="#7c3aed" strokeOpacity={0.35} strokeDasharray="4 4" />
          ))}
          <g stroke="#27273a" strokeWidth={1}>
            <path d={`M60 ${layout.axisY} H700`} />
            {layout.ticks.map((t, i) => <path key={i} d={`M${t.x} ${layout.axisY - 4} V${layout.axisY + 4}`} />)}
          </g>
          <g fill="#71717a" fontSize={10} textAnchor="middle">
            {layout.ticks.map((t, i) => <text key={i} x={t.x} y={layout.axisY + 18}>{t.label}</text>)}
          </g>
          <g fill="none" strokeLinecap="round" opacity={0.12}>
            <path d={layout.main.lanePath} stroke={MAIN_COLOR} strokeWidth={12} />
            {layout.placed.map((p) => <path key={p.agent.id} d={`${p.out} ${p.lanePath} ${p.back.replace(/^M[^C]*/, '')}`} stroke={p.color} strokeWidth={p.width + 6} />)}
          </g>
          <path d={layout.main.lanePath} stroke={MAIN_COLOR} strokeWidth={4} strokeLinecap="round" fill="none" opacity={0.6} />
          <path data-flow="main" d={layout.main.lanePath} stroke="#c4b5fd" strokeWidth={4} strokeLinecap="round" fill="none" strokeDasharray="2 22" />
          <g fill="none" strokeLinecap="round" opacity={0.75}>
            {layout.placed.map((p) => (
              <g key={p.agent.id} stroke={p.color} strokeWidth={p.width} strokeDasharray={p.open ? '4 4' : undefined}>
                <path d={p.out} /><path d={p.lanePath} />{p.back && <path d={p.back} />}
              </g>
            ))}
          </g>
          {layout.placed.map((p) => (
            <g key={p.agent.id}>
              <circle cx={p.xb} cy={p.parentY} r={4} fill="#e4e4e7" />
              {!p.open && <circle cx={p.xm} cy={p.parentY} r={4} fill="#111118" stroke="#e4e4e7" strokeWidth={2} />}
              <g fill="none" stroke="none">
                <path data-flow={`${p.agent.id}-out`} d={p.out} />
                <path data-flow={`${p.agent.id}-lane`} d={p.lanePath} />
                {p.back && <path data-flow={`${p.agent.id}-back`} d={p.back} />}
              </g>
            </g>
          ))}
          <g ref={fxRef} />
        </svg>

        {layout.placed.map((p) => {
          const task = p.agent.task?.tokens;
          const res = p.agent.result?.tokens;
          return (
            <div key={`pill-${p.agent.id}`}>
              {task != null && <Pill style={pos(...p.outMid)} up color={p.color} value={task} />}
              {res != null && !p.open && <Pill style={pos(...p.backMid)} color={p.color} value={res} />}
            </div>
          );
        })}

        {all.map((p) => {
          const Icon = ICONS[iconKey(p.agent)];
          const x = p.agent.parent_id === null ? 30 : p.xs + 16;
          const isMain = p.agent.parent_id === null;
          const sel = p.agent.id === selected;
          return (
            <div key={p.agent.id}>
              <button
                type="button"
                data-bubble={p.agent.id}
                onClick={() => onSelect(p.agent.id)}
                aria-label={`Show ${p.agent.name}`}
                className="absolute flex h-[30px] w-[30px] -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border-[3px] border-[#111118] text-white transition-shadow"
                style={{ ...pos(x, p.y), background: p.color, outline: sel ? `2px solid ${p.color}` : undefined, outlineOffset: 2 }}
              >
                <Icon className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={() => onSelect(p.agent.id)}
                className={`absolute max-w-[190px] rounded-lg border bg-[#0a0a0fcc] px-2.5 py-1.5 text-left leading-tight ${
                  sel ? 'border-[var(--color-primary)]' : 'border-[var(--color-border)] hover:border-[var(--color-primary)]'
                }`}
                style={isMain ? pos(52, 8) : pos(p.xs + 2, p.y + 16)}
              >
                <b className="block truncate text-xs font-semibold">{p.agent.name}</b>
                <span className="block truncate text-[11px] text-[var(--color-muted-foreground)]">{isMain ? p.agent.model ?? 'main agent' : p.agent.role}</span>
                <i className="block truncate text-[11px] not-italic tabular-nums text-[#a1a1aa]">{meta(p.agent) || '—'}</i>
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Pill({ style, value, color, up }: { style: React.CSSProperties; value: number; color: string; up?: boolean }) {
  const Arrow = up ? ArrowUpRight : ArrowDownLeft;
  return (
    <span
      className="absolute flex -translate-x-1/2 -translate-y-1/2 items-center gap-0.5 whitespace-nowrap rounded-full border border-[var(--color-border)] bg-[var(--color-background)] py-px pl-1 pr-1.5 text-[10px] tabular-nums text-[#a1a1aa]"
      style={style}
      title={up ? 'Task handed to the subagent (estimated tokens)' : 'Result returned to its parent (estimated tokens)'}
    >
      <Arrow className="h-2.5 w-2.5" style={{ color }} />~{formatTokens(value)}
    </span>
  );
}

function Detail({ id, placed }: { id: string; placed: Placed }) {
  const [, go] = useRoute();
  const a = placed.agent;
  const Icon = ICONS[iconKey(a)];
  const target = a.parent_id === null ? id : a.session_id;
  const open = (tab: string) => target && go(`sessions/${target}/${tab}`);
  const tone = a.status === 'completed' ? 'ok' : a.status === 'unknown' ? 'muted' : 'warn';
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 rounded px-1.5 py-0.5 text-[11px] font-medium" style={{ background: `${placed.color}22`, color: placed.color }}>
          <Icon className="h-3 w-3" /> {a.name}
        </span>
        {a.parent_id !== null && <span className="text-xs text-[var(--color-muted-foreground)]">{a.role}</span>}
        {a.model && <Badge tone="primary">{a.model}</Badge>}
        {a.cost_usd != null && <Badge>{formatUsd(a.cost_usd)}</Badge>}
        {a.tokens.total > 0 && <Badge title={`input ${a.tokens.input}, output ${a.tokens.output}, cache read ${a.tokens.cache_read}, cache write ${a.tokens.cache_write}`}>{formatTokens(a.tokens.total)} tok</Badge>}
        {a.duration_ms != null && <Badge>{formatMs(a.duration_ms)}</Badge>}
        <Badge>{a.steps} steps · {a.tool_calls} tool calls</Badge>
        {a.errors > 0 && <Badge tone="error">{a.errors} errors</Badge>}
        {a.parent_id !== null && <Badge tone={tone}>{a.status}</Badge>}
        {a.background && <Badge>background</Badge>}
        <span className="ml-auto flex gap-1.5">
          <Button onClick={() => open('chat')} disabled={!target} title={target ? 'Open this agent’s conversation' : 'Its transcript was not found'}>Open chat</Button>
          <Button onClick={() => open('trajectory')} disabled={!target}>Open trajectory</Button>
        </span>
      </div>
      {Object.keys(a.tools).length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {Object.entries(a.tools).map(([name, n]) => (
            <span key={name} className="rounded bg-[var(--color-secondary)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-muted-foreground)]">{name} ×{n}</span>
          ))}
        </div>
      )}
      {a.parent_id !== null && (
        <div className="mt-3 grid gap-2.5 md:grid-cols-2">
          <Handoff icon={<ArrowUpRight className="h-3 w-3" />} title="Task handed over" text={a.task} />
          <Handoff icon={<ArrowDownLeft className="h-3 w-3" />} title="Result returned" text={a.result} />
        </div>
      )}
    </Card>
  );
}

function Handoff({ icon, title, text }: { icon: React.ReactNode; title: string; text: AgentNode['task'] }) {
  return (
    <div className="min-w-0 rounded-md border border-[var(--color-border)] bg-[var(--color-background)] p-2.5">
      <h4 className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold text-[#a1a1aa]">
        {icon} {title}
        {text && <span className="ml-auto"><Badge>~{formatTokens(text.tokens)} tok</Badge></span>}
      </h4>
      {text ? (
        <p className="max-h-44 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed">
          {text.text}
          {text.truncated && <span className="text-[var(--color-muted-foreground)]"> … (cut)</span>}
        </p>
      ) : (
        <p className="text-[11px] text-[var(--color-muted-foreground)]">Not available.</p>
      )}
    </div>
  );
}

