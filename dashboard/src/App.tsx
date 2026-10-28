import './index.css';
import { Activity } from 'lucide-react';
import { useRoute } from './lib/route';
import { LiveView } from './views/LiveView';
import { SessionsView } from './views/SessionsView';

// Inside the desktop app the sidebar already provides navigation.
const inDesktopApp = window.parent !== window;

const VIEWS = [
  { key: 'sessions', label: 'Sessions' },
  { key: 'live', label: 'Live runs' },
] as const;

export default function App() {
  const [seg, go] = useRoute();
  const view = seg[0] === 'live' ? 'live' : 'sessions';
  return (
    <div className="flex h-screen flex-col">
      {!inDesktopApp && (
        <nav className="flex h-12 shrink-0 items-center gap-6 border-b border-[var(--color-border)] px-5">
          <div className="flex items-center gap-2">
            <Activity className="h-5 w-5 text-[var(--color-primary)]" />
            <span className="text-sm font-semibold tracking-tight">LoopPrism</span>
          </div>
          {VIEWS.map((v) => (
            <button
              key={v.key}
              type="button"
              onClick={() => go(v.key)}
              className={`text-sm ${
                view === v.key
                  ? 'text-[var(--color-primary)]'
                  : 'text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]'
              }`}
            >
              {v.label}
            </button>
          ))}
        </nav>
      )}
      {view === 'live' ? <LiveView /> : <SessionsView />}
    </div>
  );
}
