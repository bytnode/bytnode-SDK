/** Against the PRODUCTION API, read-only: `BYTNODE_API_KEY=... npm run test:live`. */
import { describe, expect, it } from 'vitest';
import { Bytnode, InvalidRequestError, channels, ind } from '../src/index.js';

const run = process.env.BYTNODE_API_KEY ? describe : describe.skip;
const pause = () => new Promise((r) => setTimeout(r, 500));

run('live', () => {
  const client = process.env.BYTNODE_API_KEY ? new Bytnode() : (null as unknown as Bytnode);

  it('latest values', async () => {
    const last = await client.klines({ symbol: 'BTCUSDT', timeframe: '1h' });
    expect(last.data?.is_closed).toBe(true);
    const candles = await client.klines.history({ symbol: 'BTCUSDT', timeframe: '1h', limit: 3 });
    expect(candles.data).toHaveLength(3);
    expect(candles.data![0]!.time).toBeInstanceOf(Date);
    const funding = await client.funding.rate({ symbol: 'BTCUSDT' });
    expect(funding.data?.time).toBeInstanceOf(Date);
    await pause();
  });

  it('paginated history', async () => {
    const rows = await client.klines.history.iter({ symbol: 'BTCUSDT', timeframe: '1h', since: '2026-10-01', until: '2026-10-03', pageSize: 10 }).toArray();
    expect(rows).toHaveLength(49);
    const t = rows.map((r) => r.time.getTime());
    expect([...t].sort((a, b) => a - b)).toEqual(t);
    await pause();
  });

  it('typed error', async () => {
    const e = await client.klines({ symbol: 'NOPEUSDT', timeframe: '1h' }).catch((x) => x);
    expect(e).toBeInstanceOf(InvalidRequestError);
    expect(e.code).toBe('invalid_symbol');
    await pause();
  });

  it('snapshot and indicators', async () => {
    const snap = await client.snapshot({ symbol: 'ETHUSDT', funding_rate: true, klines: { '1h': 3 } });
    expect(snap.data['klines@1h']).toHaveLength(3);
    const res = await client.indicators({ symbol: 'BTCUSDT', timeframe: '1h', indicators: [ind.rsi(14), ind.macd()], limit: 5 });
    expect(Object.keys(res.data!.indicators).sort()).toEqual(['macd_12_26_9', 'rsi_14']);
    await pause();
  });

  it('stream', async () => {
    const stream = client.stream({ channels: [channels.trades('BTCUSDT'), channels.orderbook('BTCUSDT')], depth: 3 });
    const kinds = new Set<string>();
    const deadline = Date.now() + 10_000;
    for await (const msg of stream) {
      kinds.add(msg.kind);
      if (msg.kind === 'trades') expect(msg.data[0]!.price).toBeGreaterThan(0);
      if (Date.now() > deadline || kinds.size === 2) break;
    }
    stream.close();
    expect(kinds.has('trades') && kinds.has('orderbook')).toBe(true);
  });
});
