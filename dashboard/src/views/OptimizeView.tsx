import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ExternalLink, Star } from 'lucide-react';
import { useOptimize, useOptimizeTools } from '../hooks/useSessions';
import { api } from '../lib/api';
import { Badge, Button, Card, Empty } from '../components/ui';
import { formatUsd } from '../lib/format';
import type { OptimizeSettings, Suggestion, ToolRec } from '../types/sessions';

const RANGES = [
  { days: 7, label: '7 days' },
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
] as const;

const CONF: Record<string, { tone: 'ok' | 'warn' | 'muted'; label: string }> = {
  high: { tone: 'ok', label: 'high confidence' },
  medium: { tone: 'warn', label: 'medium confidence' },
  low: { tone: 'muted', label: 'rough estimate' },
};

const KIND_LABEL: Record<string, string> = { compress: 'compresses output', retrieval: 'smarter retrieval', measure: 'measures', router: 'model router', gateway: 'gateway', discovered: 'found on GitHub' };

function ToolRow({ t }: { t: ToolRec }) {
  return (
    <a href={t.url} target="_blank" rel="noreferrer" className="block rounded-md border border-[var(--color-border)] p-2 text-xs hover:bg-[var(--hover)]">
      <div className="flex items-center gap-2">
        <span className="font-medium">{t.repo}</span>
        <ExternalLink className="h-3 w-3 text-[var(--color-muted-foreground)]" />
        {!t.reviewed && <Badge tone="warn" title="Found by search, not reviewed by hand: read the project before installing">not reviewed</Badge>}
        <span className="ml-auto flex items-center gap-2 text-[var(--color-muted-foreground)]">
          {t.stars != null && <span className="inline-flex items-center gap-0.5"><Star className="h-3 w-3" />{t.stars.toLocaleString()}</span>}
          {t.license && <span>{t.license}</span>}
          {t.pushed_days_ago != null && <span>updated {t.pushed_days_ago}d ago</span>}
        </span>
      </div>
      <div className="mt-1 text-[var(--color-muted-foreground)]">{t.why || t.description}</div>
      <div className="mt-1 text-[10px] text-[var(--color-muted-foreground)]">{KIND_LABEL[t.kind] ?? t.kind}</div>
    </a>
  );
}

function Compare({ s }: { s: Suggestion }) {
  const a = s.adoption;
  if (!a || a.state !== 'adopted' || !a.before || !a.after) return null;
  const fmt = (v: number | null | undefined) => (v == null ? '—' : formatUsd(v));
  const tone = a.verdict === 'better' ? 'text-[var(--tone-ok-fg)]' : a.verdict === 'worse' ? 'text-[var(--tone-error-fg)]' : 'text-[var(--color-muted-foreground)]';
  return (
    <div className="mt-3 rounded-md border border-[var(--color-border)] p-3 text-xs">
      <div className="mb-1 font-medium">Since you adopted it ({a.days_since} days ago)</div>
      <div className="grid grid-cols-3 gap-3 text-[var(--color-muted-foreground)]">
        <div>Cost per model call<div className="text-sm text-[var(--color-foreground)]">{fmt(a.before.cost_per_call)} → {fmt(a.after.cost_per_call)}</div></div>
        <div>Cache hit<div className="text-sm text-[var(--color-foreground)]">{a.before.cache_hit_pct ?? '—'}% → {a.after.cache_hit_pct ?? '—'}%</div></div>
        <div>Result<div className={`text-sm font-medium ${tone}`}>{a.cost_per_call_change_pct != null ? `${a.cost_per_call_change_pct > 0 ? '+' : ''}${a.cost_per_call_change_pct}%` : 'too early'}</div></div>
      </div>
      {a.note && <div className="mt-1.5 text-[10px] text-[var(--color-muted-foreground)]">{a.note}</div>}
    </div>
  );
}

function SuggestionCard({ s, tools, onChange }: { s: Suggestion; tools: ToolRec[]; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  const act = async (a: 'adopt' | 'dismiss' | 'reset') => {
    await api.optimizeAction(s.id, a);
    onChange();
  };
  const mine = tools.filter((t) => t.tags.includes(s.id)).slice(0, 3);
  const dismissed = s.adoption?.state === 'dismissed';
  return (
    <Card className={dismissed ? 'opacity-60' : ''}>
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold">{s.title}</h3>
            <Badge tone={CONF[s.confidence].tone}>{CONF[s.confidence].label}</Badge>
            {s.adoption?.state === 'adopted' && <Badge tone="ok">adopted</Badge>}
          </div>
          <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">{s.how}</p>
        </div>
        <div className="text-right">
          <div className="text-lg font-semibold tabular-nums text-[var(--tone-ok-fg)]">−{formatUsd(s.saving_usd)}</div>
          <div className="text-[11px] text-[var(--color-muted-foreground)]">{s.saving_pct}% of spend · {s.sessions} session{s.sessions > 1 ? 's' : ''}</div>
        </div>
      </div>
      <Compare s={s} />
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {!s.adoption && <Button tone="primary" onClick={() => act('adopt')}>I'll do this</Button>}
        {!s.adoption && <Button onClick={() => act('dismiss')}>Not for me</Button>}
        {s.adoption && <Button onClick={() => act('reset')}>Undo</Button>}
        <button type="button" onClick={() => setOpen(!open)} className="text-xs text-[var(--color-primary)] underline">{open ? 'Hide' : 'Show'} the sessions</button>
      </div>
      {open && (
        <div className="mt-2 space-y-1">
          {s.evidence.map((e) => (
            <a key={e.session_id} href={`#/sessions/${encodeURIComponent(e.session_id)}/trajectory`} className="flex items-baseline justify-between gap-3 rounded px-1.5 py-1 text-xs hover:bg-[var(--hover)]">
              <span className="min-w-0"><span className="font-medium">{e.title}</span><span className="ml-2 text-[var(--color-muted-foreground)]">{e.detail}</span></span>
              <span className="shrink-0 tabular-nums">−{formatUsd(e.saving_usd)}</span>
            </a>
          ))}
        </div>
      )}
      {mine.length > 0 && (
        <div className="mt-3 space-y-1.5">
          <div className="text-[11px] font-medium text-[var(--color-muted-foreground)]">Tools that can help</div>
          {mine.map((t) => <ToolRow key={t.repo} t={t} />)}
        </div>
      )}
    </Card>
  );
}

function AiPanel({ days, settings }: { days: number; settings: OptimizeSettings | undefined }) {
  const [preview, setPreview] = useState<{ endpoint: string | null; model: string; messages: { role: string; content: string }[] } | null>(null);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const ready = settings?.ai.enabled && settings.ai.key_set;
  return (
    <Card title="AI analysis (optional)">
      {!ready ? (
        <p className="text-xs text-[var(--color-muted-foreground)]">
          Let a model you choose (any OpenAI-compatible endpoint, even a local one) turn these findings into advice. Turn it on in Settings below. Off by default; nothing is sent until you confirm the exact request.
        </p>
      ) : (
        <div className="space-y-3">
          <Button onClick={async () => { setErr(''); setText(''); try { setPreview(await api.aiPreview(days)); } catch (e) { setErr((e as Error).message); } }}>Analyze with AI…</Button>
          {preview && (
            <div className="rounded-md border border-[var(--color-border)] p-3 text-xs">
              <div className="mb-1 font-medium">This will be sent to {preview.endpoint} (model {preview.model}). Numbers only: no prompts, code, titles or paths.</div>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-[var(--color-background)] p-2 text-[11px]">{preview.messages.map((m) => `[${m.role}]\n${m.content}`).join('\n\n')}</pre>
              <div className="mt-2 flex gap-2">
                <Button tone="primary" disabled={busy} onClick={async () => { setBusy(true); setErr(''); try { setText((await api.aiRun(days)).text); setPreview(null); } catch (e) { setErr((e as Error).message); } setBusy(false); }}>{busy ? 'Waiting for the model…' : 'Send'}</Button>
                <Button onClick={() => setPreview(null)}>Cancel</Button>
              </div>
            </div>
          )}
          {text && (
            <div className="rounded-md border border-[var(--color-border)] p-3 text-xs">
              <div className="mb-1 flex items-center gap-2 font-medium">Advice <Badge tone="warn">AI generated, check it</Badge></div>
              <div className="whitespace-pre-wrap">{text}</div>
            </div>
          )}
        </div>
      )}
      {err && <div className="mt-2 text-xs text-[var(--tone-error-fg)]">{err}</div>}
    </Card>
  );
}

function SettingsPanel({ settings, onSaved }: { settings: OptimizeSettings | undefined; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ url: '', model: '', key: '' });
  const [msg, setMsg] = useState('');
  if (!settings) return null;
  const field = 'w-full rounded-md border border-[var(--color-border)] bg-[var(--color-background)] px-2 py-1.5 text-xs outline-none focus:border-[var(--color-primary)]';
  const save = async (body: unknown) => {
    try {
      await api.saveOptimizeSettings(body);
      setMsg('Saved');
      setForm((f) => ({ ...f, key: '' }));
      onSaved();
    } catch (e) {
      setMsg((e as Error).message);
    }
  };
  return (
    <Card title="Settings" right={<button type="button" className="text-xs text-[var(--color-primary)] underline" onClick={() => { setOpen(!open); setForm({ url: settings.ai.url, model: settings.ai.model, key: '' }); }}>{open ? 'Close' : 'Edit'}</button>}>
      {!open ? (
        <p className="text-xs text-[var(--color-muted-foreground)]">
          Tool lookup on GitHub: {settings.live_tools ? 'on (once a day)' : 'off'} · AI analysis: {settings.ai.enabled ? `on (${settings.ai.model})` : 'off'}
        </p>
      ) : (
        <div className="space-y-3 text-xs">
          <label className="flex items-center gap-2"><input type="checkbox" checked={settings.live_tools} onChange={(e) => save({ live_tools: e.target.checked })} /> Look up tools on GitHub (once a day; off = only the saved list)</label>
          <div className="space-y-2 rounded-md border border-[var(--color-border)] p-3">
            <div className="font-medium">AI analysis</div>
            <label className="block">Endpoint URL (OpenAI-compatible)<input className={field} placeholder="https://api.deepseek.com/v1" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} /></label>
            <label className="block">Model<input className={field} placeholder="deepseek-chat" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} /></label>
            <label className="block">API key {settings.ai.key_set && <span className="text-[var(--color-muted-foreground)]">(saved; leave empty to keep it)</span>}<input className={field} type="password" autoComplete="off" value={form.key} onChange={(e) => setForm({ ...form, key: e.target.value })} /></label>
            <div className="flex flex-wrap items-center gap-2">
              <Button tone="primary" onClick={() => save({ ai: { url: form.url, model: form.model, api_key: form.key } })}>Save</Button>
              <label className="flex items-center gap-1.5"><input type="checkbox" checked={settings.ai.enabled} onChange={(e) => save({ ai: { enabled: e.target.checked } })} /> Turn AI analysis on</label>
              {settings.ai.key_set && <button type="button" className="text-[var(--tone-error-fg)] underline" onClick={() => save({ ai: { clear_key: true, enabled: false } })}>Remove key</button>}
            </div>
            <p className="text-[10px] text-[var(--color-muted-foreground)]">The key is stored in <code>~/.loopprism/optimize.json</code> (readable by you only) and is never shown again. Only aggregate numbers are sent.</p>
          </div>
          {msg && <div className="text-[var(--color-muted-foreground)]">{msg}</div>}
        </div>
      )}
    </Card>
  );
}

export function OptimizeView() {
  const [days, setDays] = useState<number>(30);
  const qc = useQueryClient();
  const { data, isLoading } = useOptimize(days);
  const tools = useOptimizeTools();
  const [settings, setSettings] = useState<OptimizeSettings | undefined>();
  useEffect(() => {
    api.optimizeSettings().then(setSettings).catch(() => undefined);
  }, []);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['optimize'] });
    api.optimizeSettings().then(setSettings).catch(() => undefined);
  };
  const pill = (active: boolean) => `rounded-full border px-2.5 py-0.5 text-[11px] ${active ? 'border-[var(--color-primary)] text-[var(--color-foreground)]' : 'border-[var(--color-border)] text-[var(--color-muted-foreground)]'}`;
  const pct = data && data.spend_usd ? Math.min(100, (data.optimized_usd / data.spend_usd) * 100) : 100;

  return (
    <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <div>
          <h1 className="text-lg font-semibold">Optimize</h1>
          <p className="text-xs text-[var(--color-muted-foreground)]">Where your agents spend more than they need to, what you would have saved, and tools that help. Savings are estimates from re-pricing the same tokens.</p>
        </div>
        <div className="ml-auto flex gap-1.5">{RANGES.map((r) => <button key={r.days} type="button" className={pill(days === r.days)} onClick={() => setDays(r.days)}>{r.label}</button>)}</div>
      </div>

      {isLoading && <Empty>Analyzing your sessions…</Empty>}
      {data && (
        <>
          <Card>
            <div className="flex flex-wrap items-end gap-x-8 gap-y-2">
              <div><div className="text-[11px] text-[var(--color-muted-foreground)]">Spent</div><div className="text-2xl font-semibold tabular-nums">{formatUsd(data.spend_usd)}</div></div>
              <div><div className="text-[11px] text-[var(--color-muted-foreground)]">With every suggestion</div><div className="text-2xl font-semibold tabular-nums">{formatUsd(data.optimized_usd)}</div></div>
              <div><div className="text-[11px] text-[var(--color-muted-foreground)]">Estimated saving</div><div className="text-2xl font-semibold tabular-nums text-[var(--tone-ok-fg)]">−{data.saving_pct}%</div></div>
              <div className="text-[11px] text-[var(--color-muted-foreground)]">{formatUsd(data.saving_usd)} · from the {data.analyzed_sessions} most expensive sessions</div>
            </div>
            <div className="mt-3 h-2 rounded-full bg-[var(--tone-ok-bg)]"><div className="h-2 rounded-full bg-[var(--color-primary)]" style={{ width: `${pct}%` }} /></div>
            <p className="mt-2 text-[10px] text-[var(--color-muted-foreground)]">Suggestions overlap (they re-price the same tokens), so the total is capped per session and is less than the sum below.</p>
          </Card>

          {data.suggestions.length === 0 && <Empty>No suggestions for this period. Either spending is already efficient, or there is not enough priced activity yet.</Empty>}
          {data.suggestions.map((s) => <SuggestionCard key={s.id} s={s} tools={tools.data?.tools ?? []} onChange={refresh} />)}
        </>
      )}

      <AiPanel days={days} settings={settings} />
      <SettingsPanel settings={settings} onSaved={refresh} />
      <div className="pb-2 text-[11px] text-[var(--color-muted-foreground)]">
        Tools come from a short reviewed list and a GitHub search ({tools.data?.source ?? '…'}); only open-source projects with a permissive licence and recent updates are shown. Check any project before you install it.
      </div>
    </div>
  );
}
