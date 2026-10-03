/** React hooks for loopprism data. */
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function useTraces(params?: { limit?: number; offset?: number }) {
  return useQuery({
    queryKey: ['traces', params],
    queryFn: () => api.listTraces(params),
    refetchInterval: 5000,
  });
}

export function useTrace(traceId: string | null) {
  return useQuery({
    queryKey: ['trace', traceId],
    queryFn: () => api.getTrace(traceId!),
    enabled: !!traceId,
  });
}

export function useMCPServers() {
  return useQuery({
    queryKey: ['mcp-servers'],
    queryFn: api.listMCPServers,
    refetchInterval: 10000,
  });
}

export function useMCPTools(server?: string) {
  return useQuery({
    queryKey: ['mcp-tools', server],
    queryFn: () => api.listMCPTools(server),
    refetchInterval: 10000,
  });
}

export function useCostSummary() {
  return useQuery({
    queryKey: ['cost-summary'],
    queryFn: api.getCostSummary,
    refetchInterval: 10000,
  });
}

export function useTraceCost(traceId: string | null) {
  return useQuery({
    queryKey: ['trace-cost', traceId],
    queryFn: () => api.getTraceCost(traceId!),
    enabled: !!traceId,
  });
}
