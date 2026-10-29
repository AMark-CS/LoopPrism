/** Types for the session inspector API (/api/sessions). */

export type AgentId = 'claude-code' | 'codex' | 'dsh' | 'workbuddy';

export interface SessionSummary {
  id: string;
  agent: AgentId;
  /** LoopPrism only reads these sessions: no resume, no delete. */
  read_only?: boolean;
  path: string;
  project: string | null;
  title: string;
  started_at: string | null;
  ended_at: string | null;
  models: string[];
  version: string | null;
  git_branch: string | null;
  turns: number;
  steps: number;
  messages: number;
  tool_calls: number;
  cost_usd: number | null;
  fidelity: 'exact' | 'estimated';
  subagent_steps: number;
  snippet?: string;
}

export interface SessionList {
  sessions: SessionSummary[];
  total: number;
  pending: number;
}

export interface Finding {
  kind: 'repeated_call' | 'error_streak' | 'compaction';
  severity: 'info' | 'warn' | 'error';
  title: string;
  turn: number;
  events: number[];
}

export interface SessionStats {
  turns: number;
  steps: number;
  human_inputs: number;
  tool_calls: number;
  cache_hit_pct: number | null;
  cost_usd: number | null;
  subagent_cost_usd: number | null;
  current_context: number;
  window: number | null;
  window_source: 'reported' | 'assumed' | 'unknown';
  fidelity: 'exact' | 'estimated';
  unresolved_messages: number;
  models: string[];
}

export interface SessionDetail {
  session: SessionSummary & { resume_command: string | null };
  stats: SessionStats;
  findings: Finding[];
}

export type EventKind =
  | 'system'
  | 'user'
  | 'context'
  | 'assistant'
  | 'thinking'
  | 'tool_call'
  | 'tool_result'
  | 'compaction'
  | 'model_change'
  | 'system_event';

export interface SessionEvent {
  idx: number;
  kind: EventKind;
  ts: string | null;
  turn: number;
  step: number | null;
  text: string;
  truncated?: boolean;
  size: number;
  tool_name: string | null;
  tool_input?: unknown;
  tool_use_id: string | null;
  is_error: boolean;
  sidechain: boolean;
  model: string | null;
  label: string | null;
}

export interface TrajectoryStep {
  step: number;
  turn: number;
  model: string;
  ts: string | null;
  sidechain: boolean;
  first_event: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
  model_ms: number | null;
  thinking_ms: number | null;
  tools_ms: number | null;
}

export interface Trajectory {
  turns: { turn: number; first_event: number; ts: string | null; text: string }[];
  steps: TrajectoryStep[];
  findings: Finding[];
  event_count: number;
}

export type CategoryKey =
  | 'system_prompt'
  | 'tool_schemas'
  | 'user'
  | 'injected'
  | 'skills'
  | 'assistant'
  | 'tool_results'
  | 'unattributed';

export interface TrendPoint {
  step: number;
  turn: number;
  sidechain: boolean;
  total: number;
  delta: number;
  categories: Partial<Record<CategoryKey, number>>;
  output_tokens: number;
  cache_hit_pct: number | null;
}

export interface ContextOverview {
  stats: SessionStats;
  trend: TrendPoint[];
}

export interface StepContext {
  step: number;
  turn: number;
  ts: string | null;
  model: string;
  exact_request: boolean;
  actual_input: number;
  estimated_input: number;
  window: number | null;
  window_source: string;
  window_pct: number | null;
  output_tokens: number;
  cache_hit_pct: number | null;
  cost_usd: number | null;
  categories: { key: CategoryKey; label: string; tokens: number; pct: number; items: number }[];
  items?: Partial<Record<CategoryKey, { label: string; tokens: number; preview: string }[]>>;
  message_hashes?: string[] | null;
}

export interface Timing {
  approximate: boolean;
  model_ms: number;
  thinking_ms: number;
  answer_ms: number;
  tools_ms: number;
  overhead_ms: number;
  wall_ms: number;
  tokens_per_second: number | null;
}

export interface CostBreakdown {
  total_usd: number;
  subagent_usd: number | null;
  unpriced_steps: number;
  by_type: { key: string; label: string; usd: number }[];
  by_category: { key: string; label: string; usd: number }[];
  by_model: { model: string; usd: number }[];
  by_turn: { turn: number; usd: number }[];
  top_steps: { step: number; turn: number; usd: number }[];
}

export interface AgentText {
  text: string;
  tokens: number;
  estimated: boolean;
  truncated: boolean;
}

export interface AgentNode {
  id: string;
  parent_id: string | null;
  name: string;
  role: string;
  description: string;
  background: boolean;
  status: string;
  /** Id to open this agent's own transcript ("<session>~<agent>"); null when none was found. */
  session_id: string | null;
  start: string | null;
  end: string | null;
  spawned_at: string | null;
  duration_ms: number | null;
  model: string | null;
  models: string[];
  steps: number;
  tool_calls: number;
  tools: Record<string, number>;
  errors: number;
  cost_usd: number | null;
  tokens: { input: number; output: number; cache_read: number; cache_write: number; total: number };
  task: AgentText | null;
  result: AgentText | null;
}

export interface AgentTree {
  supported: boolean;
  reason: string | null;
  agents: AgentNode[];
  totals: {
    subagents: number;
    peak_parallel: number;
    subagent_cost_usd: number | null;
    main_cost_usd: number | null;
    total_cost_usd: number | null;
    passed_tokens: number;
  };
}
