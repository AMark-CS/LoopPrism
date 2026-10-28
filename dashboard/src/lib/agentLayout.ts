/** Geometry of the agent flow: one lane per subagent, branching off its parent and merging back. */
import type { AgentNode } from '../types/sessions';

export const VIEW_W = 740;
const LEFT = 60;
const RIGHT = 700;
const TOP = 84;
const LANE_GAP = 104;
const SIBLING_GAP = 28;
const BRANCH_W = 30;
const MIN_LEN = 44;

export const MAIN_COLOR = '#7c3aed';
const PALETTE = ['#14b8a6', '#3b82f6', '#f59e0b', '#ec4899', '#10b981', '#f97316', '#06b6d4', '#a855f7'];

export interface Placed {
  agent: AgentNode;
  parentId: string | null;
  color: string;
  lane: number;
  y: number;
  parentY: number;
  /** Where the branch leaves the parent, where the lane starts and ends, where it rejoins. */
  xb: number;
  xs: number;
  xe: number;
  xm: number;
  /** No known end: the lane stops short and never rejoins. */
  open: boolean;
  width: number;
  out: string;
  lanePath: string;
  back: string;
  /** Midpoints of the branch and merge curves, where the token pills sit. */
  outMid: [number, number];
  backMid: [number, number];
}

export interface Layout {
  width: number;
  height: number;
  axisY: number;
  main: Placed;
  placed: Placed[];
  ticks: { x: number; label: string }[];
  /** x-ranges where two or more subagents run at once. */
  bands: { x0: number; x1: number }[];
  bandTop: number;
  bandBottom: number;
}

const ms = (iso: string | null | undefined): number | null => {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? t : null;
};

const bez = (p0: number, p1: number, p2: number, p3: number) => (p0 + 3 * p1 + 3 * p2 + p3) / 8;

function curve(x0: number, y0: number, x1: number, y1: number, k: number): { d: string; mid: [number, number] } {
  const down = y1 > y0;
  const c1y = down ? y0 + k : y0 - k;
  const c2y = down ? y1 - k : y1 + k;
  return {
    d: `C${x0} ${c1y},${x1} ${c2y},${x1} ${y1}`,
    mid: [bez(x0, x0, x1, x1), bez(y0, c1y, c2y, y1)],
  };
}

function tickLabel(elapsed: number): string {
  if (elapsed < 90_000) return `${Math.round(elapsed / 1000)}s`;
  if (elapsed < 90 * 60_000) return `${Math.round(elapsed / 60_000)}m`;
  return `${(elapsed / 3_600_000).toFixed(1)}h`;
}

export function layoutAgents(agents: AgentNode[]): Layout | null {
  const root = agents.find((a) => a.parent_id === null);
  if (!root) return null;
  const starts = agents.map((a) => ms(a.start)).filter((v): v is number => v !== null);
  const ends = agents.map((a) => ms(a.end)).filter((v): v is number => v !== null);
  const t0 = Math.min(...(starts.length ? starts : [0]));
  const t1 = Math.max(...(ends.length ? ends : [t0 + 1]), t0 + 1);
  const xOf = (t: number | null, fallback: number) =>
    t === null ? fallback : LEFT + ((t - t0) / (t1 - t0)) * (RIGHT - LEFT);

  const maxCost = Math.max(...agents.map((a) => a.cost_usd ?? 0), 0.0001);
  const widthOf = (a: AgentNode) => 2.2 + 2.2 * Math.min(1, (a.cost_usd ?? 0) / maxCost);

  const main: Placed = {
    agent: root, parentId: null, color: MAIN_COLOR, lane: 0, y: TOP, parentY: TOP,
    xb: LEFT - 30, xs: LEFT - 30, xe: RIGHT + 10, xm: RIGHT + 10, open: false, width: 4,
    out: '', lanePath: `M${LEFT - 30} ${TOP} H${RIGHT + 10}`, back: '', outMid: [0, 0], backMid: [0, 0],
  };
  const placed: Placed[] = [];
  const byId = new Map<string, Placed>([[root.id, main]]);
  const lanes: [number, number][][] = [[]];
  const lastBranch = new Map<string, number>();

  const children = agents
    .filter((a) => a.parent_id !== null)
    .sort((a, b) => (ms(a.start ?? a.spawned_at) ?? 0) - (ms(b.start ?? b.spawned_at) ?? 0));
  // A child can only be placed once its parent is; retry until the queue settles.
  let queue = children;
  for (let guard = 0; queue.length && guard < 50; guard++) {
    const next: AgentNode[] = [];
    for (const a of queue) {
      const parent = byId.get(a.parent_id ?? '');
      if (!parent) {
        next.push(a);
        continue;
      }
      // Agents spawned together would leave the parent on the same spot; fan them out.
      const last = lastBranch.get(parent.agent.id) ?? -Infinity;
      const xb = Math.min(Math.max(xOf(ms(a.spawned_at ?? a.start), LEFT), parent.xs, last + SIBLING_GAP), RIGHT - 90);
      lastBranch.set(parent.agent.id, xb);
      const xs = xb + BRANCH_W;
      const end = ms(a.end);
      const open = end === null;
      let xe = open ? xs + MIN_LEN * 0.6 : Math.max(xOf(end, xs + MIN_LEN), xs + MIN_LEN);
      xe = Math.min(xe, RIGHT + 6);
      const xm = xe + BRANCH_W;
      const span: [number, number] = [xb - 8, xm + 8];
      let lane = parent.lane + 1;
      while ((lanes[lane] ?? []).some(([s, e]) => span[0] < e && span[1] > s)) lane++;
      (lanes[lane] ??= []).push(span);
      const y = TOP + lane * LANE_GAP;
      const k = Math.abs(y - parent.y) * 0.6;
      const o = curve(xb, parent.y, xs, y, k);
      const b = open ? null : curve(xe, y, xm, parent.y, k);
      const p: Placed = {
        agent: a, parentId: parent.agent.id, color: PALETTE[placed.length % PALETTE.length], lane, y, parentY: parent.y,
        xb, xs, xe, xm, open, width: widthOf(a),
        out: `M${xb} ${parent.y} ${o.d}`,
        lanePath: `M${xs} ${y} H${xe}`,
        back: b ? `M${xe} ${y} ${b.d}` : '',
        outMid: o.mid, backMid: b ? b.mid : [xe, y],
      };
      placed.push(p);
      byId.set(a.id, p);
    }
    if (next.length === queue.length) break; // orphans: leave them out
    queue = next;
  }

  const maxLane = Math.max(0, ...placed.map((p) => p.lane));
  const bottom = TOP + maxLane * LANE_GAP + 96;
  const axisY = bottom + 14;

  // x-ranges with two or more subagents running at once
  const marks = placed.flatMap((p) => [[p.xs, 1], [p.xe, -1]] as [number, number][]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const bands: { x0: number; x1: number }[] = [];
  let cur = 0;
  let from = 0;
  for (const [x, d] of marks) {
    const before = cur;
    cur += d;
    if (before < 2 && cur >= 2) from = x;
    if (before >= 2 && cur < 2 && x > from) bands.push({ x0: from, x1: x });
  }

  const ticks = Array.from({ length: 5 }, (_, i) => ({
    x: LEFT + (i / 4) * (RIGHT - LEFT),
    label: tickLabel((i / 4) * (t1 - t0)),
  }));
  return {
    width: VIEW_W, height: axisY + 36, axisY, main, placed, ticks, bands,
    bandTop: TOP + 26, bandBottom: bottom,
  };
}
