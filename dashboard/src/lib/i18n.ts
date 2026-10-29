/**
 * Interface language. The English text is the key: `t('Cost')`. Chinese lives in `zh.ts`; a string
 * with no entry shows in English. `{name}` placeholders are filled from the second argument.
 *
 * The language comes from `?lang=en|zh` (the desktop app passes its Settings choice), else the
 * choice kept for this tab, else the browser's language. It is fixed for a page load.
 */
import type { Locale } from 'date-fns';
import { zhCN } from 'date-fns/locale/zh-CN';
import { ZH } from './zh';

export type Lang = 'en' | 'zh';
const KEY = 'lp-lang';

function detect(): Lang {
  const fromUrl = new URLSearchParams(window.location.search).get('lang');
  if (fromUrl === 'en' || fromUrl === 'zh') {
    try {
      sessionStorage.setItem(KEY, fromUrl);
    } catch {
      /* the URL still decides */
    }
    return fromUrl;
  }
  try {
    const kept = sessionStorage.getItem(KEY);
    if (kept === 'en' || kept === 'zh') return kept;
  } catch {
    /* ignore */
  }
  return navigator.language.toLowerCase().startsWith('zh') ? 'zh' : 'en';
}

export const lang: Lang = detect();
document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';

/** date-fns locale for relative times; undefined = English. */
export const dateLocale: Locale | undefined = lang === 'zh' ? zhCN : undefined;

export function t(text: string, vars?: Record<string, string | number>): string {
  let out = lang === 'zh' ? (ZH[text] ?? text) : text;
  if (vars) for (const [k, v] of Object.entries(vars)) out = out.split(`{${k}}`).join(String(v));
  return out;
}

/** "1 turn" / "3 turns": English adds an s, Chinese has no plural (both forms get a `zh.ts` entry). */
export const plural = (n: number, one: string, many: string): string => t(n === 1 ? one : many, { n });

/** Titles the server builds from data ("Bash called 3× with identical input"): translated by pattern. */
const PATTERNS_ZH: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^(.+): (\d+)% of (\d+)k input tokens came from cache( \(some providers do not report cache reads at all\))?$/, (m) => `${m[1]}:${m[3]}k 输入 token 中只有 ${m[2]}% 来自缓存${m[4] ? '(有些服务商根本不报告缓存读取)' : ''}`],
  [/^(\d+) steps, (\d+) output tokens, no heavy tool use: (.+) → (.+)$/, (m) => `${m[1]} 步,${m[2]} 个输出 token,没有大量工具调用:${m[3]} → ${m[4]}`],
  [/^(\d+) tool results over 8k tokens \(largest ≈(\d+)k\)$/, (m) => `${m[1]} 个工具结果超过 8k token(最大约 ${m[2]}k)`],
  [/^(\d+) steps, the context grew to (\d+)k tokens$/, (m) => `${m[1]} 步,上下文增长到 ${m[2]}k token`],
  [/^Too early to tell: wait at least (\d+) days and some activity\.$/, (m) => `现在还看不出来:请至少等 ${m[1]} 天并有一些使用记录。`],
  [/^(.+) called (\d+)× with identical input$/, (m) => `${m[1]} 用相同的输入调用了 ${m[2]} 次`],
  [/^(\d+) tool errors in a row$/, (m) => `连续 ${m[1]} 次工具错误`],
];
export function tServer(text: string): string {
  if (lang !== 'zh') return text;
  if (ZH[text]) return ZH[text];
  for (const [re, fn] of PATTERNS_ZH) {
    const m = text.match(re);
    if (m) return fn(m);
  }
  return text;
}
