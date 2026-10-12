/** Turn the time bounds people actually write into the epoch milliseconds the API wants. */

/** A point in time: a `Date`, an ISO string (`2026-01-01`, `2026-01-01T12:00:00Z`) or epoch MILLISECONDS. */
export type TimeLike = Date | string | number;

// 1e11 ms = 1973-03-03: anything below is a timestamp in SECONDS (or a mistake).
const SECONDS_CEILING = 100_000_000_000;

export const TIMEFRAME_MS: Record<string, number> = {
  '1m': 60_000,
  '5m': 300_000,
  '15m': 900_000,
  '30m': 1_800_000,
  '1h': 3_600_000,
  '4h': 14_400_000,
  '1d': 86_400_000,
  '1w': 604_800_000,
};

export function toMs(value: TimeLike, name = 'time'): number {
  if (value instanceof Date) {
    const ms = value.getTime();
    if (Number.isNaN(ms)) throw new TypeError(`${name}: invalid Date`);
    return ms;
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new TypeError(`${name}: not a finite number`);
    const ms = Math.trunc(value);
    if (Math.abs(ms) < SECONDS_CEILING) {
      throw new RangeError(
        `${name}=${value} looks like a timestamp in seconds: pass epoch milliseconds (${ms * 1000}), a Date or an ISO string`,
      );
    }
    return ms;
  }
  if (typeof value === 'string') {
    const text = value.trim();
    if (/^-?\d+$/.test(text)) return toMs(Number(text), name);
    // a date alone is midnight UTC (Date.parse already does that for YYYY-MM-DD)
    const iso = /^\d{4}-\d{2}-\d{2}T[^Z+-]*$/.test(text) ? `${text}Z` : text;
    const ms = Date.parse(iso);
    if (Number.isNaN(ms)) {
      throw new RangeError(`${name}=${JSON.stringify(value)} is not a date: use an ISO string ('2026-01-01'), a Date or epoch milliseconds`);
    }
    return ms;
  }
  throw new TypeError(`${name}: expected a Date, an ISO string or epoch milliseconds`);
}
