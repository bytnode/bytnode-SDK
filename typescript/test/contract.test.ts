/**
 * Every route of the contract: its SDK method builds the right request, and the REAL example
 * response captured from production comes back with its dates as `Date`.
 */
import { describe, expect, it } from 'vitest';
import { ROUTES, ind } from '../src/index.js';
import { FORCE_REQUIRED, KEY, example, fakeClient, json, operations } from './helpers.js';

const SAMPLE: Record<string, string> = {
  symbol: 'BTCUSDT',
  timeframe: '1h',
  asset: 'BTC',
  series: 'DGS10',
  expiry: '2026-10-30',
  dataset: 'concentration',
};
const OPS = operations();

function method(client: any, dotted: string): any {
  return dotted.split('.').reduce((o, k) => o[k], client);
}

describe('contract', () => {
  it('maps every route to a method', () => {
    expect(OPS).toHaveLength(132);
    expect(Object.keys(ROUTES).sort()).toEqual(OPS.map((o) => o.path).sort());
  });

  it.each(OPS.map((o) => [o.path, o] as const))('%s', async (path, { method: verb, op }) => {
    const { client, calls } = fakeClient(() => json(200, example(op)));
    const fn = method(client, ROUTES[path]!);
    expect(typeof fn).toBe('function');
    let resp: any;
    if (path === '/v1/snapshot') resp = await fn({ symbol: 'BTCUSDT', funding_rate: true, klines: { '1h': 2 } });
    else if (path === '/v1/indicators') resp = await fn({ symbol: 'BTCUSDT', timeframe: '1h', indicators: [ind.rsi(14), ind.macd()], limit: 3 });
    else {
      const params: Record<string, string> = {};
      const forced = FORCE_REQUIRED[path] ?? [];
      for (const p of op.parameters ?? []) if (p.required || forced.includes(p.name)) params[p.name] = SAMPLE[p.name]!;
      resp = await fn(params);
    }
    const sent = calls[0]!;
    expect(sent.init.method).toBe(verb.toUpperCase());
    expect(sent.url.pathname).toBe(path.replace('{symbol}', 'BTCUSDT'));
    expect((sent.init.headers as Record<string, string>)['X-API-KEY']).toBe(KEY);
    for (const p of op.parameters ?? []) {
      if (p.required && p.in === 'query') expect(sent.url.searchParams.get(p.name)).toBe(SAMPLE[p.name]);
    }
    const data = example(op).data;
    if (Array.isArray(data)) expect(resp.data).toHaveLength(data.length);
    expect(resp.serverTime).toBeInstanceOf(Date);
    const first = Array.isArray(resp.data) ? resp.data[0] : resp.data;
    if (first && typeof first === 'object' && 'time' in first && path !== '/v1/snapshot' && path !== '/v1/indicators') {
      expect(first.time).toBeInstanceOf(Date);
    }
    expect(resp.raw).toEqual(example(op)); // the raw body is never mutated
  });
});
