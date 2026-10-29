import { useState, type ReactNode } from 'react';
import { Check, Copy } from 'lucide-react';
import { t } from '../lib/i18n';

export function Card({
  title,
  right,
  children,
  className = '',
}: {
  title?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] p-4 ${className}`}
    >
      {(title || right) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-[var(--color-foreground)]">{title}</h3>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Badge({
  children,
  tone = 'muted',
  title,
}: {
  children: ReactNode;
  tone?: 'muted' | 'primary' | 'ok' | 'warn' | 'error';
  title?: string;
}) {
  const tones = {
    muted: 'bg-[var(--color-secondary)] text-[var(--color-muted-foreground)]',
    primary: 'bg-[var(--tone-primary-bg)] text-[var(--tone-primary-fg)]',
    ok: 'bg-[var(--tone-ok-bg)] text-[var(--tone-ok-fg)]',
    warn: 'bg-[var(--tone-warn-bg)] text-[var(--tone-warn-fg)]',
    error: 'bg-[var(--tone-error-bg)] text-[var(--tone-error-fg)]',
  };
  return (
    <span
      title={title}
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

export function CopyButton({ text, label = t('Copy') }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setDone(true);
        setTimeout(() => setDone(false), 1500);
      }}
      className="inline-flex items-center gap-1 rounded-md border border-[var(--color-border)] px-2 py-1 text-xs text-[var(--color-muted-foreground)] hover:bg-[var(--color-accent)] hover:text-[var(--color-foreground)]"
    >
      {done ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
      {done ? t('Copied') : label}
    </button>
  );
}

export function Button({
  children,
  onClick,
  tone = 'default',
  disabled,
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  tone?: 'default' | 'primary' | 'danger';
  disabled?: boolean;
  title?: string;
}) {
  const tones = {
    default:
      'border border-[var(--color-border)] text-[var(--color-foreground)] hover:bg-[var(--color-accent)]',
    primary: 'bg-[var(--color-primary)] text-white hover:opacity-90',
    danger: 'bg-[var(--danger)] text-white hover:bg-[var(--danger-hover)]',
  };
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium disabled:opacity-50 ${tones[tone]}`}
    >
      {children}
    </button>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-1 items-center justify-center p-8 text-sm text-[var(--color-muted-foreground)]">
      {children}
    </div>
  );
}
