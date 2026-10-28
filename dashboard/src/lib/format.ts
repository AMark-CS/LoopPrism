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
