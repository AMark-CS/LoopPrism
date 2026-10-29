/** React hooks for the session inspector. */
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function useSessionList(params: { q?: string; agent?: string; project?: string }) {
  return useQuery({
    queryKey: ['sessions', params],
    queryFn: () => api.listSessions(params),
    // While files are still being indexed, poll quickly; then slowly for new sessions.
    refetchInterval: (q) => (q.state.data?.pending ? 1500 : 10000),
    placeholderData: (prev) => prev,
  });
}

export const useCostOverview = (days: number, agent?: string) =>
  useQuery({
    queryKey: ['cost-overview', days, agent ?? ''],
    queryFn: () => api.costOverview(days, agent),
    refetchInterval: (q) => (q.state.data?.pending ? 2000 : 30000),
    placeholderData: (prev) => prev,
  });

export const useSession = (id: string | null) =>
  useQuery({
    queryKey: ['session', id],
    queryFn: () => api.getSession(id!),
    enabled: !!id,
  });

export const useTrajectory = (id: string) =>
  useQuery({ queryKey: ['trajectory', id], queryFn: () => api.getTrajectory(id) });

export const useContextOverview = (id: string) =>
  useQuery({ queryKey: ['context', id], queryFn: () => api.getContext(id) });

export const useStepContext = (id: string, step: number | null) =>
  useQuery({
    queryKey: ['context-step', id, step],
    queryFn: () => api.getStepContext(id, step!),
    enabled: step !== null,
  });

export const useTiming = (id: string) =>
  useQuery({ queryKey: ['timing', id], queryFn: () => api.getTiming(id) });

export const useCostBreakdown = (id: string) =>
  useQuery({ queryKey: ['cost-breakdown', id], queryFn: () => api.getCost(id) });

export const useAgents = (id: string) =>
  useQuery({ queryKey: ['agents', id], queryFn: () => api.getAgents(id) });
