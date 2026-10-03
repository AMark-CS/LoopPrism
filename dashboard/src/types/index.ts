/** Shared TypeScript types for the loopprism dashboard. */

export interface Trace {
  id: string;
  conversation_id: string | null;
  timestamp: string;
  root_span_type: string | null;
  root_span_name: string | null;
  total_latency_ms: number | null;
  total_cost_usd: number | null;
  span_count: number;
  error_count: number;
  mcp_servers: string | null;
  tags: string | null;
}

export interface Span {
  id: string;
  trace_id: string;
  parent_span_id: string | null;
  span_type: string;
  start_time: string;
  end_time: string | null;
  latency_ms: number | null;

  // MCP fields
  mcp_server_name: string | null;
  mcp_server_version: string | null;
  mcp_transport: string | null;
  mcp_request_method: string | null;
  mcp_request_id: string | null;

  // Tool fields
  tool_name: string | null;
  tool_arguments: string | null;
  tool_call_id: string | null;

  // Result
  result_content_preview: string | null;
  result_size_bytes: number | null;
  result_is_error: number;

  // Status
  status: string;
}

export interface MCPServerStat {
  mcp_server_name: string;
  call_count: number;
  avg_latency_ms: number | null;
  max_latency_ms: number | null;
  total_result_bytes: number | null;
  error_count: number;
}

export interface MCPToolStat {
  mcp_server_name: string;
  tool_name: string;
  call_count: number;
  avg_latency_ms: number | null;
  min_latency_ms: number | null;
  max_latency_ms: number | null;
  avg_result_bytes: number | null;
  error_count: number;
}

export interface CostItem {
  source: string;
  source_type: string;
  cost_usd: number;
  proportion: number;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number | null;
  result_bytes: number | null;
}

export interface CostBreakdown {
  trace_id: string;
  total_cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  mcp_tool_cost_usd: number;
  llm_cost_usd: number;
  by_server: Record<string, number>;
  by_tool: Record<string, number>;
  items: CostItem[];
}

export interface CostTrend {
  trace_id: string;
  timestamp: string;
  total_cost_usd: number;
  span_count: number;
  error_count: number;
  by_tool: Record<string, number>;
}

export interface TraceListResponse {
  traces: Trace[];
  limit: number;
  offset: number;
}

export interface CostSummary {
  total_tool_calls: number;
  total_errors: number;
  total_result_bytes: number;
  estimated_cost_usd: number;
  mcp_servers: MCPServerStat[];
  tools: MCPToolStat[];
}
