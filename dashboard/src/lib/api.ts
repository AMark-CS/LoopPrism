/** API client for the loopprism backend. */
import type * as S from '../types/sessions';

const BASE = '';

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function post<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: 'POST' });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* keep status text */
    }
    throw new Error(detail);
  }
  return res.json();
}

export const api = {
  // Health
  health: () => get<{ status: string }>('/api/health'),

  // Traces
  listTraces: (params?: {
    limit?: number;
    offset?: number;
    mcp_server?: string;
    time_from?: string;
    time_to?: string;
  }) => {
    const qs = new URLSearchParams();
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.offset) qs.set('offset', String(params.offset));
    if (params?.mcp_server) qs.set('mcp_server', params.mcp_server);
    if (params?.time_from) qs.set('time_from', params.time_from);
    if (params?.time_to) qs.set('time_to', params.time_to);
    const q = qs.toString();
    return get<import('../types').TraceListResponse>(
      `/api/traces${q ? `?${q}` : ''}`,
    );
  },

  getTrace: (traceId: string) =>
    get<{
      trace: import('../types').Trace;
      spans: import('../types').Span[];
    }>(`/api/traces/${traceId}`),

  // MCP servers
  listMCPServers: () =>
    get<import('../types').MCPServerStat[]>('/api/mcp-servers'),

  listMCPTools: (server?: string) =>
    get<import('../types').MCPToolStat[]>(
      `/api/mcp-tools${server ? `?server=${server}` : ''}`,
    ),

  // Cost
  getCostSummary: () =>
    get<import('../types').CostSummary>('/api/cost/summary'),

  getTraceCost: (traceId: string) =>
    get<import('../types').CostBreakdown>(`/api/cost/trace/${traceId}`),

  getCostTrend: (limit = 50) =>
    get<{ trends: import('../types').CostTrend[] }>(
      `/api/cost/trend?limit=${limit}`,
    ),

  // Sessions (inspector)
  listSessions: (params: { q?: string; agent?: string; project?: string }) => {
    const qs = new URLSearchParams();
    if (params.q) qs.set('q', params.q);
    if (params.agent) qs.set('agent', params.agent);
    if (params.project) qs.set('project', params.project);
    return get<S.SessionList>(`/api/sessions?${qs}`);
  },
  getSession: (id: string) => get<S.SessionDetail>(`/api/sessions/${id}`),
  getSessionEvents: (
    id: string,
    params: { offset?: number; limit?: number; kinds?: string; q?: string; preview?: number },
  ) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== '') qs.set(k, String(v));
    }
    return get<{ total: number; events: S.SessionEvent[] }>(
      `/api/sessions/${id}/events?${qs}`,
    );
  },
  getSessionEvent: (id: string, idx: number) =>
    get<S.SessionEvent>(`/api/sessions/${id}/events/${idx}`),
  getTrajectory: (id: string) => get<S.Trajectory>(`/api/sessions/${id}/trajectory`),
  getContext: (id: string) => get<S.ContextOverview>(`/api/sessions/${id}/context`),
  getStepContext: (id: string, step: number) =>
    get<S.StepContext>(`/api/sessions/${id}/context/${step}`),
  getCost: (id: string) => get<S.CostBreakdown>(`/api/sessions/${id}/cost`),
  getTiming: (id: string) => get<S.Timing>(`/api/sessions/${id}/timing`),
  resumeSession: (id: string, terminal: boolean) =>
    post<{ command: string; opened: boolean }>(
      `/api/sessions/${id}/resume?terminal=${terminal}`,
    ),
  deleteSession: (id: string) => post<{ trashed: string }>(`/api/sessions/${id}/delete`),
};
