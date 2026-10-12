/** Read the IETF `RateLimit` / `RateLimit-Policy` headers of a response. */

// The API names its two policies "debit" (rate limit) and "mensuel" (monthly quota);
// English aliases are accepted so a future rename does not break the SDK.
const RATE_NAMES = new Set(['debit', 'rate', 'burst', 'rate_limit']);
const QUOTA_NAMES = new Set(['mensuel', 'monthly', 'quota', 'month']);

export interface RateLimit {
  /** Requests allowed per window by the rate limit. */
  limit: number | null;
  remaining: number | null;
  /** Seconds before the rate limit is fully restored. */
  resetSeconds: number | null;
  windowSeconds: number | null;
  /** Requests allowed per month. */
  quotaLimit: number | null;
  /** Requests left this month. */
  quotaRemaining: number | null;
  quotaResetSeconds: number | null;
  quotaWindowSeconds: number | null;
  /** Every policy, as sent. */
  policies: Record<string, Record<string, number>>;
}

export function parsePolicies(header: string | null): Record<string, Record<string, number>> {
  const out: Record<string, Record<string, number>> = {};
  if (!header) return out;
  for (const part of header.split(',')) {
    const pieces = part.split(';').map((p) => p.trim());
    const name = (pieces[0] ?? '').replace(/"/g, '').trim();
    if (!name) continue;
    const params: Record<string, number> = {};
    for (const kv of pieces.slice(1)) {
      const i = kv.indexOf('=');
      if (i < 0) continue;
      const v = Number(kv.slice(i + 1).replace(/"/g, ''));
      if (Number.isFinite(v)) params[kv.slice(0, i).trim()] = Math.trunc(v);
    }
    out[name] = params;
  }
  return out;
}

export function rateLimitFromHeaders(headers: Headers): RateLimit | null {
  const policy = parsePolicies(headers.get('ratelimit-policy'));
  const state = parsePolicies(headers.get('ratelimit'));
  const names = [...new Set([...Object.keys(policy), ...Object.keys(state)])];
  if (!names.length) return null;
  const pick = (known: Set<string>, largest: boolean): string | null => {
    const hit = names.find((n) => known.has(n.toLowerCase()));
    if (hit) return hit;
    const sorted = [...names].sort((a, b) => (policy[a]?.w ?? 0) - (policy[b]?.w ?? 0));
    return (largest ? sorted[sorted.length - 1] : sorted[0]) ?? null;
  };
  const rate = pick(RATE_NAMES, false);
  let quota = pick(QUOTA_NAMES, true);
  if (quota === rate) quota = null;
  const get = (name: string | null, src: Record<string, Record<string, number>>, k: string): number | null =>
    name ? (src[name]?.[k] ?? null) : null;
  const policies: Record<string, Record<string, number>> = {};
  for (const n of names) policies[n] = { ...(policy[n] ?? {}), ...(state[n] ?? {}) };
  return {
    limit: get(rate, policy, 'q'),
    remaining: get(rate, state, 'r'),
    resetSeconds: get(rate, state, 't'),
    windowSeconds: get(rate, policy, 'w'),
    quotaLimit: get(quota, policy, 'q'),
    quotaRemaining: get(quota, state, 'r'),
    quotaResetSeconds: get(quota, state, 't'),
    quotaWindowSeconds: get(quota, policy, 'w'),
    policies,
  };
}
