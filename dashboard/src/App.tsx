import { useState } from 'react';
import './index.css';
import { TraceList } from './components/TraceList';
import { TraceDetail } from './components/TraceDetail';
import { CostPanel } from './components/CostPanel';
import { MCPServerPanel } from './components/MCPServerPanel';
import { EmptyState } from './components/EmptyState';
import { useTraces, useMCPServers, useCostSummary } from './hooks/useTraces';
import { Activity, Server, DollarSign, Search } from 'lucide-react';

export default function App() {
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);

  const { data: tracesData } = useTraces({ limit: 50 });
  const { data: serversData } = useMCPServers();
  const { data: costData } = useCostSummary();

  const traces = tracesData?.traces ?? [];
  const servers = serversData ?? [];
  const cost = costData ?? {
    total_tool_calls: 0,
    total_errors: 0,
    total_result_bytes: 0,
    estimated_cost_usd: 0,
  };

  const hasData = traces.length > 0;

  return (
    <div className="flex min-h-screen flex-col">
      {/* Header */}
      <header className="flex h-14 items-center justify-between border-b border-[var(--color-border)] px-6">
        <div className="flex items-center gap-2">
          <Activity className="h-5 w-5 text-[var(--color-primary)]" />
          <span className="text-sm font-semibold tracking-tight text-[var(--color-foreground)]">
            LoopPrism
          </span>
          <span className="text-xs text-[var(--color-muted-foreground)]">
            Looking glass for your AI tools
          </span>
        </div>
        <div className="flex items-center gap-4 text-xs text-[var(--color-muted-foreground)]">
          <span className="flex items-center gap-1">
            <Server className="h-3 w-3" />
            {servers.length} servers
          </span>
          <span className="flex items-center gap-1">
            <Activity className="h-3 w-3" />
            {cost.total_tool_calls} calls
          </span>
          <span className="flex items-center gap-1">
            <DollarSign className="h-3 w-3" />
            {cost.estimated_cost_usd > 0
              ? `$${cost.estimated_cost_usd.toFixed(4)}`
              : '$0'}
          </span>
        </div>
      </header>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {!hasData ? (
          <EmptyState />
        ) : (
          <>
            {/* Left panel */}
            <div className="flex w-80 flex-col border-r border-[var(--color-border)] overflow-hidden">
              {/* Server stats */}
              {servers.length > 0 && (
                <MCPServerPanel servers={servers} />
              )}

              {/* Trace list */}
              <div className="flex-1 overflow-y-auto">
                <TraceList
                  traces={traces}
                  selectedId={selectedTraceId}
                  onSelect={setSelectedTraceId}
                />
              </div>
            </div>

            {/* Right panel */}
            <div className="flex flex-1 flex-col overflow-hidden">
              {selectedTraceId ? (
                <TraceDetail
                  traceId={selectedTraceId}
                  onClose={() => setSelectedTraceId(null)}
                />
              ) : (
                <div className="flex flex-1 items-center justify-center">
                  <div className="text-center">
                    <Search className="mx-auto h-8 w-8 text-[var(--color-muted)]" />
                    <p className="mt-2 text-sm text-[var(--color-muted-foreground)]">
                      Select a trace to view details
                    </p>
                  </div>
                </div>
              )}
            </div>

            {/* Cost sidebar */}
            {selectedTraceId && (
              <CostPanel traceId={selectedTraceId} />
            )}
          </>
        )}
      </div>
    </div>
  );
}
