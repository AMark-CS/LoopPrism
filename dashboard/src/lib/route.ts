import { useEffect, useState } from 'react';

/** Tiny hash router: "#/sessions/<id>/context" → ["sessions", "<id>", "context"]. */
function parse(): string[] {
  return window.location.hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent);
}

export function useRoute(): [string[], (path: string) => void] {
  const [segments, setSegments] = useState<string[]>(parse);
  useEffect(() => {
    const onChange = () => setSegments(parse());
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return [segments, (path) => (window.location.hash = path.startsWith('#') ? path : `#/${path}`)];
}
