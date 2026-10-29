/**
 * Light/dark for the dashboard.
 *
 * Standalone (browser, `lprism proxy`) it stays dark. The desktop app opens it with `?theme=auto`
 * (or `light` / `dark`); "auto" follows the window's colour scheme, which the app's Theme setting
 * controls. The choice is kept for the tab so in-page navigation doesn't lose it.
 */
type Mode = 'auto' | 'light' | 'dark';

const KEY = 'lp-theme';

function readMode(): Mode {
  const fromUrl = new URLSearchParams(window.location.search).get('theme');
  if (fromUrl === 'auto' || fromUrl === 'light' || fromUrl === 'dark') {
    try {
      sessionStorage.setItem(KEY, fromUrl);
    } catch {
      /* private mode: the URL still decides */
    }
    return fromUrl;
  }
  try {
    const kept = sessionStorage.getItem(KEY);
    if (kept === 'auto' || kept === 'light' || kept === 'dark') return kept;
  } catch {
    /* ignore */
  }
  return 'dark';
}

export function initTheme(): void {
  const mode = readMode();
  const root = document.documentElement;
  if (mode !== 'auto') {
    root.dataset.theme = mode;
    return;
  }
  const query = window.matchMedia('(prefers-color-scheme: light)');
  const apply = () => {
    root.dataset.theme = query.matches ? 'light' : 'dark';
  };
  apply();
  query.addEventListener('change', apply);
}
