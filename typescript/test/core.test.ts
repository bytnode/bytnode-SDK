import { describe, expect, it } from 'vitest';
import {
  APIConnectionError,
  AuthenticationError,
  Bytnode,
  InvalidRequestError,
  MissingAPIKeyError,
  NotFoundError,
  PermissionDeniedError,
  RateLimitError,
  ServerError,
  ind,
  toMs,
} from '../src/index.js';
import { SPEC, err, fakeClient, json } from './helpers.js';

const OK = { status: 'ok', server_time: '2026-10-12T09:00:00.000Z', data_type: 'funding_rate', data: null };
const KLINE = SPEC.paths['/v1/klines'].get.responses['200'].content['application/json'].example.data[0];
const page = (times: string[], next: unknown) => ({
  status: 'ok',
  server_time: '2026-10-12T09:00:00.000Z',
  data: times.map((t) => ({ ...KLINE, time: t })),
  next,
});

describe('client', () => {
  it('needs a key', () => {
    const saved = process.env.BYTNODE_API_KEY;
    delete process.env.BYTNODE_API_KEY;
    expect(() => new Bytnode()).toThrow(MissingAPIKeyError);
    process.env.BYTNODE_API_KEY = 'cb_live_env';
    expect(new Bytnode().apiKey).toBe('cb_live_env');
    if (saved === undefined) delete process.env.BYTNODE_API_KEY;
    else process.env.BYTNODE_API_KEY = saved;
  });
});

describe('retries', () => {
  it('retries a 503 then succeeds', async () => {
    const { client, calls } = fakeClient([() => json(503, err('service_unavailable', 'busy')), () => json(200, OK)]);
    const resp = await client.funding.rate({ symbol: 'BTCUSDT' });
    expect(resp.data).toBeNull();
    expect(calls).toHaveLength(2);
  });

  it('gives up after maxRetries', async () => {
    const { client, calls } = fakeClient(() => new Response('bad gateway', { status: 502 }));
    await expect(client.funding.rate({ symbol: 'BTCUSDT' })).rejects.toBeInstanceOf(ServerError);
    expect(calls).toHaveLength(4);
  });

  it('retries a 500 once', async () => {
    const { client, calls } = fakeClient(() => json(500, err('internal_error', 'boom')));
    await expect(client.funding.rate({ symbol: 'BTCUSDT' })).rejects.toBeInstanceOf(ServerError);
    expect(calls).toHaveLength(2);
  });

  it('honours Retry-After on a rate limit', async () => {
    const { client, calls } = fakeClient([
      () => json(429, err('rate_limited', 'slow down'), { 'retry-after': '2', 'x-deny-reason': 'rate' }),
      () => json(200, OK),
    ]);
    await client.funding.rate({ symbol: 'BTCUSDT' });
    expect(calls).toHaveLength(2);
  });

  it('never retries a spent quota', async () => {
    const { client, calls } = fakeClient(() =>
      json(429, err('quota_exceeded', 'monthly quota spent'), { 'retry-after': '86400', 'x-deny-reason': 'quota' }),
    );
    const e = await client.funding.rate({ symbol: 'BTCUSDT' }).catch((x) => x);
    expect(e).toBeInstanceOf(RateLimitError);
    expect(e.isQuota).toBe(true);
    expect(e.retryAfter).toBe(86400);
    expect(calls).toHaveLength(1);
  });

  it('retries network errors then throws APIConnectionError', async () => {
    const { client, calls } = fakeClient(() => {
      throw new TypeError('fetch failed');
    });
    await expect(client.funding.rate({ symbol: 'BTCUSDT' })).rejects.toBeInstanceOf(APIConnectionError);
    expect(calls).toHaveLength(4);
  });

  it('per-request options', async () => {
    const { client, calls } = fakeClient(() => json(503, err('service_unavailable', 'x')));
    await expect(client.funding.rate({ symbol: 'BTCUSDT' }, { maxRetries: 0, headers: { 'X-Trace': '1' } })).rejects.toBeInstanceOf(ServerError);
    expect(calls).toHaveLength(1);
    expect((calls[0]!.init.headers as Record<string, string>)['X-Trace']).toBe('1');
  });
});

describe('errors', () => {
  it.each([
    [401, 'invalid_api_key', 'key', AuthenticationError],
    [403, 'plan_family', 'family', PermissionDeniedError],
    [403, 'history_depth', 'depth', PermissionDeniedError],
    [404, 'not_found', null, NotFoundError],
    [422, 'invalid_symbol', null, InvalidRequestError],
  ] as const)('%i %s', async (status, code, reason, Cls) => {
    const headers: Record<string, string> = reason ? { 'x-deny-reason': reason } : {};
    const { client, calls } = fakeClient(() => json(status, err(code, 'explained', 'symbol'), headers));
    const e = await client.funding.rate({ symbol: 'BTCUSDT' }).catch((x) => x);
    expect(e).toBeInstanceOf(Cls);
    expect(e.status).toBe(status);
    expect(e.code).toBe(code);
    expect(e.param).toBe('symbol');
    expect(e.reason).toBe(reason);
    expect(e.message).toContain('explained');
    expect(calls).toHaveLength(1);
  });
});

describe('parameters', () => {
  it('converts times and lists', async () => {
    const { client, calls } = fakeClient(() => json(200, page([], null)));
    await client.klines({ symbol: 'BTCUSDT', timeframe: '1h', since: '2026-01-01', before: new Date('2026-01-02T00:00:00Z'), fields: ['time', 'close'], limit: 5 });
    const q = calls[0]!.url.searchParams;
    expect(q.get('since_ms')).toBe('1767225600000');
    expect(q.get('before_ms')).toBe('1767312000000');
    expect(q.get('fields')).toBe('time,close');
    expect(q.has('until_ms')).toBe(false);
  });

  it('refuses seconds', () => {
    expect(() => toMs(1767225600)).toThrow(/seconds/);
    expect(toMs('2026-01-01T00:00:00')).toBe(1767225600000); // naive = UTC
  });

  it('reads rate-limit headers', async () => {
    const { client } = fakeClient(() =>
      json(200, OK, {
        'ratelimit-policy': '"debit";q=600;w=60, "mensuel";q=100000;w=2592000',
        ratelimit: '"debit";r=599;t=1, "mensuel";r=87342;t=1234567',
      }),
    );
    const resp = await client.funding.rate({ symbol: 'BTCUSDT' });
    expect(resp.rateLimit).toMatchObject({ limit: 600, remaining: 599, windowSeconds: 60, quotaLimit: 100000, quotaRemaining: 87342 });
    expect(client.lastRateLimit).toEqual(resp.rateLimit);
  });
});

describe('pagination', () => {
  it('follows next and replaces the cursor', async () => {
    const { client, calls } = fakeClient([
      () => json(200, page(['2026-01-01T00:00:00.000Z', '2026-01-01T01:00:00.000Z'], { since_ms: 1767232800000, until_ms: null, before_ms: null, order: 'asc' })),
      () => json(200, page(['2026-01-01T02:00:00.000Z'], null)),
    ]);
    const rows = await client.klines.iter({ symbol: 'BTCUSDT', timeframe: '1h', since: '2026-01-01', until: '2026-01-02' }).toArray();
    expect(rows.map((r) => r.time.getUTCHours())).toEqual([0, 1, 2]);
    const [a, b] = calls.map((c) => c.url.searchParams);
    expect(a!.get('limit')).toBe('1000');
    expect(a!.get('order')).toBe('asc');
    expect(b!.get('since_ms')).toBe('1767232800000');
    expect(b!.has('until_ms')).toBe(false);
  });

  it('understands next as a URL', async () => {
    const { client, calls } = fakeClient([
      () => json(200, page(['2026-01-01T01:00:00.000Z'], '/v1/klines?symbol=BTCUSDT&timeframe=1h&limit=1000&before_ms=1767229200000&order=desc')),
      () => json(200, page(['2026-01-01T00:00:00.000Z'], null)),
    ]);
    expect(await client.klines.iter({ symbol: 'BTCUSDT', timeframe: '1h' }).toArray()).toHaveLength(2);
    expect(calls[1]!.url.searchParams.get('before_ms')).toBe('1767229200000');
    expect(calls[1]!.url.searchParams.get('symbol')).toBe('BTCUSDT');
  });

  it('respects maxItems and never loops on a stuck cursor', async () => {
    const stuck = { before_ms: 1767225600000, order: 'desc' };
    const { client, calls } = fakeClient(() => json(200, page(['2026-01-01T00:00:00.000Z'], stuck)));
    expect(await client.klines.iter({ symbol: 'BTCUSDT', timeframe: '1h' }).toArray()).toHaveLength(2);
    expect(calls).toHaveLength(2);
    const { client: c2 } = fakeClient(() => json(200, page(['2026-01-01T00:00:00.000Z', '2026-01-01T00:00:00.000Z'], { before_ms: 1767225600000, order: 'desc' })));
    expect(await c2.klines.iter({ symbol: 'BTCUSDT', timeframe: '1h', maxItems: 3 }).toArray()).toHaveLength(3);
  });

  it('puts trades in range reading', async () => {
    const { client, calls } = fakeClient(() => json(200, { status: 'ok', server_time: '2026-10-12T09:00:00.000Z', data: [], next: null }));
    await client.trades.spot.iter({ symbol: 'BTCUSDT' }).toArray();
    expect(calls[0]!.url.searchParams.get('order')).toBe('desc');
    expect(calls[0]!.url.searchParams.get('limit')).toBe('10000');
  });
});

describe('snapshot and indicators', () => {
  it('encodes snapshot fields', async () => {
    const { client, calls } = fakeClient(() => json(200, { status: 'ok', server_time: '2026-10-12T09:00:00.000Z', data: {} }));
    await client.snapshot({ symbol: 'BTCUSDT', funding_rate: true, basis: 5, klines: { '1h': 24, '1w': 2 }, cvd: { '5m': 3 } });
    expect(Object.fromEntries(calls[0]!.url.searchParams)).toEqual({
      symbol: 'BTCUSDT',
      funding_rate: 'true',
      basis: '5',
      'klines@1h': '24',
      'klines@1w': '2',
      'cvd@5m': '3',
    });
    expect(() => client.snapshot({ symbol: 'BTCUSDT' })).toThrow(/at least one field/);
  });

  it('builds indicator bodies with unique ids', async () => {
    const { client, calls } = fakeClient(() => json(200, { status: 'ok', server_time: '2026-10-12T09:00:00.000Z', data: null, unavailable: 'not_applicable' }));
    const resp = await client.indicators({ symbol: 'USDCUSDT', timeframe: '1h', indicators: [ind.rsi(14), ind.rsi(14), { type: 'ema', period: 50 }], results: 10 });
    const body = JSON.parse(String(calls[0]!.init.body));
    expect(body.indicators.map((i: { id: string }) => i.id)).toEqual(['rsi_14', 'rsi_14_2', 'ema_50']);
    expect(resp.data).toBeNull();
    expect(resp.unavailable).toBe('not_applicable');
    expect(() => ind.rsi(1)).toThrow(/>= 2/);
    expect(() => ind.bb({ std: 50 })).toThrow(/between 0.5 and 10/);
    expect(ind.bb({ period: 20, std: 2.5 }).defaultId()).toBe('bb_20_2p5');
  });
});

describe('the API key is never serialized', () => {
  it('stays out of JSON.stringify, spreads and the Node inspector', async () => {
    const { inspect } = await import('node:util');
    const client = new Bytnode({ apiKey: 'cb_test_never_logged' });
    expect(client.apiKey).toBe('cb_test_never_logged');
    expect(JSON.stringify(client)).not.toContain('cb_test_never_logged');
    expect(JSON.stringify({ ...client })).not.toContain('cb_test_never_logged');
    expect(Object.keys(client)).not.toContain('apiKey');
    expect(inspect(client, { depth: 5 })).not.toContain('cb_test_never_logged');
  });
});

describe('pagination: short pages and timeouts', () => {
  it('goes on after a short or empty page that has a next', async () => {
    const { client } = fakeClient([
      () => json(200, page(['2026-01-01T00:00:00.000Z'], '/v1/klines?symbol=BTCUSDT&timeframe=1h&since_ms=1767312000000&order=asc&limit=1000')),
      () => json(200, page([], '/v1/klines?symbol=BTCUSDT&timeframe=1h&since_ms=1767398400000&order=asc&limit=1000')),
      () => json(200, page(['2026-01-03T00:00:00.000Z', '2026-01-03T01:00:00.000Z'], null)),
    ]);
    const rows = await client.klines.iter({ symbol: 'BTCUSDT', timeframe: '1h', since: '2026-01-01' }).toArray();
    expect(rows).toHaveLength(3);
  });

  it('asks a smaller page after a 504', async () => {
    const limits: string[] = [];
    let n = 0;
    const fetchImpl = (async (input: RequestInfo | URL) => {
      limits.push(new URL(String(input)).searchParams.get('limit') ?? '');
      n += 1;
      if (n === 1) {
        return json(504, { status: 'error', server_time: '2026-10-13T00:00:00.000Z', error: { code: 'upstream_timeout', message: 'Took too long.' } });
      }
      return json(200, page(['2026-01-01T00:00:00.000Z'], null));
    }) as typeof fetch;
    const client = new Bytnode({ apiKey: 'cb_live_test_key', baseUrl: 'https://api.example.test', fetch: fetchImpl, maxRetries: 0 });
    const rows = await client.klines.iter({ symbol: 'BTCUSDT', timeframe: '1h', since: '2026-01-01' }).toArray();
    expect(rows).toHaveLength(1);
    expect(limits).toEqual(['1000', '500']);
  });
});
