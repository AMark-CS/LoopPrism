import { t } from './i18n';

/** SQLite stores UTC timestamps without a zone ("2026-10-28 04:07:26"). */
export function parseUtc(ts: string): Date {
  if (/[zZ]|[+-]\d\d:?\d\d$/.test(ts)) return new Date(ts);
  return new Date(`${ts.replace(' ', 'T')}Z`);
}

/** "$1.84", "<$0.01", "$1,204". */
export function formatUsd(value: number): string {
  if (value > 0 && value < 0.01) return '<$0.01';
  if (value >= 1000) {
    return `$${Math.round(value).toLocaleString('en-US')}`;
  }
  return `$${value.toFixed(2)}`;
}

/** 1234 → "1.2k", 1_500_000 → "1.5M". */
export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return String(Math.round(n));
}

/** 1500 → "1.5s", 90_000 → "1m 30s". */
export function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${Math.round(s % 60)}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

export const CATEGORY_COLORS: Record<string, string> = {
  system_prompt: '#6366f1',
  tool_schemas: '#f59e0b',
  user: '#22c55e',
  injected: '#a855f7',
  skills: '#f97316',
  assistant: '#3b82f6',
  tool_results: '#14b8a6',
  unattributed: '#6b7280',
};

export const CATEGORY_LABELS: Record<string, string> = {
  system_prompt: t('System Prompt'),
  tool_schemas: t('Tool Schemas'),
  user: t('User Messages'),
  injected: t('Injected Context'),
  skills: t('Skill Injections'),
  assistant: t('Assistant Messages'),
  tool_results: t('Tool Results'),
  unattributed: t('System & tools (inferred)'),
};
