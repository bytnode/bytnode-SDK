/** The indicator spec sent to `POST /v1/indicators`, and its local checks. */

import type { KlineTimeframe } from './generated/literals.js';

const ID = /^[A-Za-z0-9_.-]{1,64}$/;

export class IndicatorSpec {
  constructor(
    readonly type: string,
    readonly params: Record<string, number> = {},
    readonly id?: string,
  ) {}

  defaultId(): string {
    const values = Object.values(this.params)
      .map((v) => String(v).replace('.', 'p').replace('-', 'm'))
      .join('_');
    return values ? `${this.type}_${values}` : this.type;
  }
}

/** Refuse locally what the API would refuse with a 422 — sooner and clearer. */
export function check(kind: string, name: string, value: number, min: number, max: number | null, integer: boolean): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new TypeError(`${kind}.${name} must be a number, got ${String(value)}`);
  if (integer && !Number.isInteger(value)) throw new RangeError(`${kind}.${name} must be an integer, got ${value}`);
  if (value < min || (max != null && value > max)) {
    throw new RangeError(`${kind}.${name} must be ${max == null ? `>= ${min}` : `between ${min} and ${max}`}, got ${value}`);
  }
  return value;
}

export interface IndicatorsParams {
  /** Trading pair, e.g. `BTCUSDT`. */
  symbol: string;
  /** Candle size, `1m` to `1w`. */
  timeframe: KlineTimeframe;
  /** Up to 50 specs: `ind.rsi(14)`, or plain objects `{ type: 'rsi', period: 14 }`. Ids are generated when missing. */
  indicators: Array<IndicatorSpec | ({ type: string; id?: string } & Record<string, unknown>)>;
  /** Values per indicator, 1 to 1000 (default 1). */
  results?: number;
}

/** One computed indicator. Its parameters (`period`, `fast`…) are extra properties. */
export interface IndicatorValue {
  /** Start of the candle of the LAST value of `values`. */
  time: Date | null;
  type: string;
  /** Values oldest to newest; a map of series for multi-output indicators (MACD, Bollinger…). */
  values: Array<number | null> | Record<string, Array<number | null>>;
  [param: string]: unknown;
}

/** `data` of `POST /v1/indicators`: the results keyed by the `id` of each spec. */
export interface IndicatorsResult {
  indicators: Record<string, IndicatorValue>;
}

export function indicatorsBody(indicators: IndicatorsParams['indicators']): Array<Record<string, unknown>> {
  if (!indicators?.length) throw new RangeError('indicators: give at least one indicator, e.g. ind.rsi(14)');
  if (indicators.length > 50) throw new RangeError(`indicators: at most 50 per call, got ${indicators.length}`);
  const used = new Set<string>();
  return indicators.map((spec) => {
    let item: Record<string, unknown>;
    let id: string;
    if (spec instanceof IndicatorSpec) {
      item = { type: spec.type, ...spec.params };
      id = spec.id ?? spec.defaultId();
    } else {
      if (!spec || typeof spec.type !== 'string') throw new TypeError(`indicators: missing 'type' in ${JSON.stringify(spec)}`);
      const { id: given, ...rest } = spec;
      item = rest;
      const params = Object.fromEntries(Object.entries(rest).filter(([k, v]) => k !== 'type' && typeof v === 'number')) as Record<
        string,
        number
      >;
      id = given ?? new IndicatorSpec(spec.type, params).defaultId();
    }
    if (!ID.test(id)) throw new RangeError(`indicators: invalid id ${JSON.stringify(id)} (1 to 64 letters, digits, '_', '-', '.')`);
    const base = id;
    for (let n = 2; used.has(id); n++) id = `${base}_${n}`;
    used.add(id);
    return { id, ...item };
  });
}
