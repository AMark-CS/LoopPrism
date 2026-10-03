/** API client for the loopprism backend. */

const BASE = '';

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
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
};
