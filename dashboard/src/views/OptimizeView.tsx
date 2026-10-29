import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ExternalLink, Star } from 'lucide-react';
import { useOptimize, useOptimizeTools } from '../hooks/useSessions';
import { api } from '../lib/api';
import { Badge, Button, Card, Empty } from '../components/ui';
import { formatUsd } from '../lib/format';
import { t, tServer } from '../lib/i18n';
import type { OptimizeSettings, Suggestion, ToolRec } from '../types/sessions';

const RANGES = [
  { days: 7, label: t('7 days') },
  { days: 30, label: t('30 days') },
  { days: 90, label: t('90 days') },
] as const;

const CONF: Record<string, { tone: 'ok' | 'warn' | 'muted'; label: string }> = {
  high: { tone: 'ok', label: t('high confidence') },
  medium: { tone: 'warn', label: t('medium confidence') },
  low: { tone: 'muted', label: t('rough estimate') },
};

const KIND_LABEL: Record<string, string> = { compress: t('compresses output'), retrieval: t('smarter retrieval'), measure: t('measures'), router: t('model router'), gateway: t('gateway'), discovered: t('found on GitHub') };

function ToolRow({ tool }: { tool: ToolRec }) {
  return (
    <a href={tool.url} target="_blank" rel="noreferrer" className="block rounded-md border border-[var(--color-border)] p-2 text-xs hover:bg-[var(--hover)]">
      <div className="flex items-center gap-2">
        <span className="font-medium">{tool.repo}</span>
        <ExternalLink className="h-3 w-3 text-[var(--color-muted-foreground)]" />
        {!tool.reviewed && <Badge tone="warn" title={t('Found by search, not reviewed by hand: read the project before installing')}>{t('not reviewed')}</Badge>}
        <span className="ml-auto flex items-center gap-2 text-[var(--color-muted-foreground)]">
          {tool.stars != null && <span className="inline-flex items-center gap-0.5"><Star className="h-3 w-3" />{tool.stars.toLocaleString()}</span>}
          {tool.license && <span>{tool.license}</span>}
          {tool.pushed_days_ago != null && <span>{t('updated {n}d ago', { n: tool.pushed_days_ago })}</span>}
        </span>
      </div>
      <div className="mt-1 text-[var(--color-muted-foreground)]">{tool.why ? tServer(tool.why) : tool.description}</div>
      <div className="mt-1 text-[10px] text-[var(--color-muted-foreground)]">{KIND_LABEL[tool.kind] ?? tool.kind}</div>
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
      <div className="mb-1 font-medium">{t('Since you adopted it ({n} days ago)', { n: a.days_since ?? 0 })}</div>
      <div className="grid grid-cols-3 gap-3 text-[var(--color-muted-foreground)]">
        <div>{t('Cost per model call')}<div className="text-sm text-[var(--color-foreground)]">{fmt(a.before.cost_per_call)} → {fmt(a.after.cost_per_call)}</div></div>
        <div>{t('Cache hit')}<div className="text-sm text-[var(--color-foreground)]">{a.before.cache_hit_pct ?? '—'}% → {a.after.cache_hit_pct ?? '—'}%</div></div>
        <div>{t('Result')}<div className={`text-sm font-medium ${tone}`}>{a.cost_per_call_change_pct != null ? `${a.cost_per_call_change_pct > 0 ? '+' : ''}${a.cost_per_call_change_pct}%` : t('too early')}</div></div>
      </div>
      {a.note && <div className="mt-1.5 text-[10px] text-[var(--color-muted-foreground)]">{tServer(a.note)}</div>}
    </div>
  );
}

function SuggestionCard({ s, tools, onChange }: { s: Suggestion; tools: ToolRec[]; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  const act = async (a: 'adopt' | 'dismiss' | 'reset') => {
    await api.optimizeAction(s.id, a);
    onChange();
  };
  const mine = tools.filter((x) => x.tags.includes(s.id)).slice(0, 3);
  const dismissed = s.adoption?.state === 'dismissed';
  return (
    <Card className={dismissed ? 'opacity-60' : ''}>
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold">{tServer(s.title)}</h3>
            <Badge tone={CONF[s.confidence].tone}>{CONF[s.confidence].label}</Badge>
            {s.adoption?.state === 'adopted' && <Badge tone="ok">{t('adopted')}</Badge>}
          </div>
          <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">{tServer(s.how)}</p>
        </div>
        <div className="text-right">
          <div className="text-lg font-semibold tabular-nums text-[var(--tone-ok-fg)]">−{formatUsd(s.saving_usd)}</div>
          <div className="text-[11px] text-[var(--color-muted-foreground)]">{t(s.sessions > 1 ? '{p}% of spend · {n} sessions' : '{p}% of spend · {n} session', { p: s.saving_pct, n: s.sessions })}</div>
        </div>
      </div>
      <Compare s={s} />
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {!s.adoption && <Button tone="primary" onClick={() => act('adopt')}>{t('I\'ll do this')}</Button>}
        {!s.adoption && <Button onClick={() => act('dismiss')}>{t('Not for me')}</Button>}
        {s.adoption && <Button onClick={() => act('reset')}>{t('Undo')}</Button>}
        <button type="button" onClick={() => setOpen(!open)} className="text-xs text-[var(--color-primary)] underline">{open ? t('Hide the sessions') : t('Show the sessions')}</button>
      </div>
      {open && (
        <div className="mt-2 space-y-1">
          {s.evidence.map((e) => (
            <a key={e.session_id} href={`#/sessions/${encodeURIComponent(e.session_id)}/trajectory`} className="flex items-baseline justify-between gap-3 rounded px-1.5 py-1 text-xs hover:bg-[var(--hover)]">
              <span className="min-w-0"><span className="font-medium">{e.title}</span><span className="ml-2 text-[var(--color-muted-foreground)]">{tServer(e.detail)}</span></span>
              <span className="shrink-0 tabular-nums">−{formatUsd(e.saving_usd)}</span>
            </a>
          ))}
        </div>
      )}
      {mine.length > 0 && (
        <div className="mt-3 space-y-1.5">
          <div className="text-[11px] font-medium text-[var(--color-muted-foreground)]">{t('Tools that can help')}</div>
          {mine.map((x) => <ToolRow key={x.repo} tool={x} />)}
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
    <Card title={t('AI analysis (optional)')}>
      {!ready ? (
        <p className="text-xs text-[var(--color-muted-foreground)]">
          {t('Let a model you choose (any OpenAI-compatible endpoint, even a local one) turn these findings into advice. Turn it on in Settings below. Off by default; nothing is sent until you confirm the exact request.')}
        </p>
      ) : (
        <div className="space-y-3">
          <Button onClick={async () => { setErr(''); setText(''); try { setPreview(await api.aiPreview(days)); } catch (e) { setErr((e as Error).message); } }}>{t('Analyze with AI…')}</Button>
          {preview && (
            <div className="rounded-md border border-[var(--color-border)] p-3 text-xs">
              <div className="mb-1 font-medium">{t('This will be sent to {url} (model {model}). Numbers only: no prompts, code, titles or paths.', { url: String(preview.endpoint), model: preview.model })}</div>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-[var(--color-background)] p-2 text-[11px]">{preview.messages.map((m) => `[${m.role}]\n${m.content}`).join('\n\n')}</pre>
              <div className="mt-2 flex gap-2">
                <Button tone="primary" disabled={busy} onClick={async () => { setBusy(true); setErr(''); try { setText((await api.aiRun(days)).text); setPreview(null); } catch (e) { setErr((e as Error).message); } setBusy(false); }}>{busy ? t('Waiting for the model…') : t('Send')}</Button>
                <Button onClick={() => setPreview(null)}>{t('Cancel')}</Button>
              </div>
            </div>
          )}
          {text && (
            <div className="rounded-md border border-[var(--color-border)] p-3 text-xs">
              <div className="mb-1 flex items-center gap-2 font-medium">{t('Advice')} <Badge tone="warn">{t('AI generated, check it')}</Badge></div>
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
      setMsg(t('Saved'));
      setForm((f) => ({ ...f, key: '' }));
      onSaved();
    } catch (e) {
      setMsg((e as Error).message);
    }
  };
  return (
    <Card title={t('Settings')} right={<button type="button" className="text-xs text-[var(--color-primary)] underline" onClick={() => { setOpen(!open); setForm({ url: settings.ai.url, model: settings.ai.model, key: '' }); }}>{open ? t('Close') : t('Edit')}</button>}>
      {!open ? (
        <p className="text-xs text-[var(--color-muted-foreground)]">
          {t('Tool lookup on GitHub')}: {settings.live_tools ? t('on (once a day)') : t('off')} · {t('AI analysis')}: {settings.ai.enabled ? t('on ({model})', { model: settings.ai.model }) : t('off')}
        </p>
      ) : (
        <div className="space-y-3 text-xs">
          <label className="flex items-center gap-2"><input type="checkbox" checked={settings.live_tools} onChange={(e) => save({ live_tools: e.target.checked })} /> {t('Look up tools on GitHub (once a day; off = only the saved list)')}</label>
          <div className="space-y-2 rounded-md border border-[var(--color-border)] p-3">
            <div className="font-medium">{t('AI analysis')}</div>
            <label className="block">{t('Endpoint URL (OpenAI-compatible)')}<input className={field} placeholder="https://api.deepseek.com/v1" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} /></label>
            <label className="block">{t('Model')}<input className={field} placeholder="deepseek-chat" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} /></label>
            <label className="block">{t('API key')} {settings.ai.key_set && <span className="text-[var(--color-muted-foreground)]">{t('(saved; leave empty to keep it)')}</span>}<input className={field} type="password" autoComplete="off" value={form.key} onChange={(e) => setForm({ ...form, key: e.target.value })} /></label>
            <div className="flex flex-wrap items-center gap-2">
              <Button tone="primary" onClick={() => save({ ai: { url: form.url, model: form.model, api_key: form.key } })}>{t('Save')}</Button>
              <label className="flex items-center gap-1.5"><input type="checkbox" checked={settings.ai.enabled} onChange={(e) => save({ ai: { enabled: e.target.checked } })} /> {t('Turn AI analysis on')}</label>
              {settings.ai.key_set && <button type="button" className="text-[var(--tone-error-fg)] underline" onClick={() => save({ ai: { clear_key: true, enabled: false } })}>{t('Remove key')}</button>}
            </div>
            <p className="text-[10px] text-[var(--color-muted-foreground)]">{t('The key is stored in')} <code>~/.loopprism/optimize.json</code> {t('(readable by you only) and is never shown again. Only aggregate numbers are sent.')}</p>
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
          <h1 className="text-lg font-semibold">{t('Optimize')}</h1>
          <p className="text-xs text-[var(--color-muted-foreground)]">{t('Where your agents spend more than they need to, what you would have saved, and tools that help. Savings are estimates from re-pricing the same tokens.')}</p>
        </div>
        <div className="ml-auto flex gap-1.5">{RANGES.map((r) => <button key={r.days} type="button" className={pill(days === r.days)} onClick={() => setDays(r.days)}>{r.label}</button>)}</div>
      </div>

      {isLoading && <Empty>{t('Analyzing your sessions…')}</Empty>}
      {data && (
        <>
          <Card>
            <div className="flex flex-wrap items-end gap-x-8 gap-y-2">
              <div><div className="text-[11px] text-[var(--color-muted-foreground)]">{t('Spent')}</div><div className="text-2xl font-semibold tabular-nums">{formatUsd(data.spend_usd)}</div></div>
              <div><div className="text-[11px] text-[var(--color-muted-foreground)]">{t('With every suggestion')}</div><div className="text-2xl font-semibold tabular-nums">{formatUsd(data.optimized_usd)}</div></div>
              <div><div className="text-[11px] text-[var(--color-muted-foreground)]">{t('Estimated saving')}</div><div className="text-2xl font-semibold tabular-nums text-[var(--tone-ok-fg)]">−{data.saving_pct}%</div></div>
              <div className="text-[11px] text-[var(--color-muted-foreground)]">{t('{c} · from the {n} most expensive sessions', { c: formatUsd(data.saving_usd), n: data.analyzed_sessions })}</div>
            </div>
            <div className="mt-3 h-2 rounded-full bg-[var(--tone-ok-bg)]"><div className="h-2 rounded-full bg-[var(--color-primary)]" style={{ width: `${pct}%` }} /></div>
            <p className="mt-2 text-[10px] text-[var(--color-muted-foreground)]">{t('Suggestions overlap (they re-price the same tokens), so the total is capped per session and is less than the sum below.')}</p>
          </Card>

          {data.suggestions.length === 0 && <Empty>{t('No suggestions for this period. Either spending is already efficient, or there is not enough priced activity yet.')}</Empty>}
          {data.suggestions.map((s) => <SuggestionCard key={s.id} s={s} tools={tools.data?.tools ?? []} onChange={refresh} />)}
        </>
      )}

      <AiPanel days={days} settings={settings} />
      <SettingsPanel settings={settings} onSaved={refresh} />
      <div className="pb-2 text-[11px] text-[var(--color-muted-foreground)]">
        {t('Tools come from a short reviewed list and a GitHub search ({source}); only open-source projects with a permissive licence and recent updates are shown. Check any project before you install it.', { source: tools.data?.source ?? '…' })}
      </div>
    </div>
  );
}
