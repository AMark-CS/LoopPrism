import { useState } from 'react';
import './index.css';
import { TraceList } from './components/TraceList';
import { TraceDetail } from './components/TraceDetail';
import { CostPanel } from './components/CostPanel';
import { MCPServerPanel } from './components/MCPServerPanel';
import { EmptyState } from './components/EmptyState';
import { useTraces, useMCPServers, useCostSummary } from './hooks/useTraces';
import { Header } from './components/Header';
import { Search } from 'lucide-react';

export default function App() {
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);

  const { data: tracesData } = useTraces({ limit: 50 });
  const { data: serversData } = useMCPServers();
  const { data: costData } = useCostSummary();

  const traces = tracesData?.traces ?? [];
  const servers = serversData ?? [];
  const hasData = traces.length > 0;

  return (
    <div className="flex min-h-screen flex-col">
      <Header summary={costData} />

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
