/** The WebSocket client against a local server that speaks the BytNode stream protocol. */
import { afterEach, describe, expect, it } from 'vitest';
import { WebSocketServer, type WebSocket } from 'ws';
import { AuthenticationError, Bytnode, ConnectionLimitError, StreamError, channels, type StreamMessage } from '../src/index.js';

const T = '2026-10-12T09:00:00.000Z';
const trades = (seq: number) =>
  JSON.stringify({ channel: 'trades.futures.BTCUSDT', time: T, seq, data: [{ time: T, id: `id${seq}`, side: 'buy', price: 83000, quantity: 0.01, usd_value: 830 }] });
const book = (seq: number) =>
  JSON.stringify({ channel: 'book.futures.BTCUSDT', time: T, seq, data: { bids: [[82999, 1.5]], asks: [[83001, 2]], mid_avg: 83000, spread_bps_avg: 0.03 } });

type Script = (ws: WebSocket) => void;
const servers: WebSocketServer[] = [];

async function start(scripts: Script[]) {
  const state = { connections: 0, frames: [] as any[], keys: [] as Array<string | undefined> };
  const wss = new WebSocketServer({
    port: 0,
    verifyClient: (info, cb) => {
      const key = info.req.headers['x-api-key'] as string | undefined;
      state.keys.push(key);
      if (key === 'bad') cb(false, 401, 'Unauthorized', { 'X-Deny-Reason': 'key', 'Content-Type': 'application/json' });
      else cb(true);
    },
  });
  servers.push(wss);
  wss.on('connection', (ws) => {
    const script = scripts[Math.min(state.connections, scripts.length - 1)]!;
    state.connections++;
    const active = new Set<string>();
    ws.on('message', (raw) => {
      const frame = JSON.parse(String(raw));
      state.frames.push(frame);
      if (frame.op !== 'subscribe') return;
      if (frame.channels.some((c: string) => c.endsWith('FAKE'))) {
        ws.send(JSON.stringify({ op: 'error', code: 'invalid_symbol', message: 'Unknown symbol' }));
        return;
      }
      frame.channels.forEach((c: string) => active.add(c));
      ws.send(JSON.stringify({ op: 'subscribed', channels: [...active].sort() }));
      script(ws);
    });
  });
  await new Promise<void>((r) => wss.on('listening', () => r()));
  const port = (wss.address() as { port: number }).port;
  return { url: `ws://127.0.0.1:${port}/ws`, state };
}

afterEach(() => {
  servers.splice(0).forEach((s) => s.close());
});

const client = (url: string, apiKey = 'cb_live_k') => new Bytnode({ apiKey, streamUrl: url, baseUrl: 'https://x' });

async function collect(stream: ReturnType<Bytnode['stream']>): Promise<{ got: StreamMessage[]; error: unknown }> {
  const got: StreamMessage[] = [];
  try {
    for await (const m of stream) got.push(m);
  } catch (e) {
    return { got, error: e };
  }
  return { got, error: null };
}

describe('stream', () => {
  it('builds channel names', () => {
    expect(channels.trades('btcusdt')).toBe('trades.futures.BTCUSDT');
    expect(channels.book('ETHUSDT', 'spot')).toBe('book.spot.ETHUSDT');
    expect(channels.liquidations('solusdt')).toBe('liquidations.SOLUSDT');
  });

  it('types messages, detects gaps, sends the key in a header', async () => {
    const { url, state } = await start([
      (ws) => {
        [trades(10), trades(11), book(500), trades(14)].forEach((f) => ws.send(f));
        setTimeout(() => ws.close(1000), 50);
      },
    ]);
    const gaps: Array<[string, number]> = [];
    const s = client(url).stream({ channels: ['trades.futures.btcusdt', channels.book('BTCUSDT')], depth: 3, reconnect: false, onGap: (c, n) => gaps.push([c, n]) });
    const { got, error } = await collect(s);
    expect(error).toBeInstanceOf(StreamError);
    expect(state.keys).toEqual(['cb_live_k']);
    expect(state.frames[0]).toEqual({ op: 'subscribe', channels: ['book.futures.BTCUSDT', 'trades.futures.BTCUSDT'], depth: 3 });
    expect(got.map((m) => m.kind)).toEqual(['trades', 'trades', 'book', 'trades']);
    expect(got.map((m) => m.gap)).toEqual([0, 0, 0, 2]);
    expect(gaps).toEqual([['trades.futures.BTCUSDT', 2]]);
    const first = got[0]!;
    if (first.kind !== 'trades') throw new Error('expected trades');
    expect(first.data[0]!.time).toBeInstanceOf(Date);
    expect(first.symbol).toBe('BTCUSDT');
    expect(first.market).toBe('futures');
    const b = got[2]!;
    if (b.kind !== 'book') throw new Error('expected book');
    expect(b.data.bids[0]).toEqual([82999, 1.5]);
    expect(s.channels).toEqual(['book.futures.BTCUSDT', 'trades.futures.BTCUSDT']);
  });

  it('reconnects, subscribes again, stops on the connection ceiling', async () => {
    const { url, state } = await start([
      (ws) => {
        ws.send(trades(1));
        setTimeout(() => ws.close(1011, 'restart'), 30);
      },
      (ws) => {
        ws.send(trades(5));
        setTimeout(() => ws.close(4003, 'connection ceiling reached (3)'), 30);
      },
    ]);
    const s = client(url).stream({ channels: [channels.trades('BTCUSDT')] });
    s.backoff = () => 10;
    const { got, error } = await collect(s);
    expect(error).toBeInstanceOf(ConnectionLimitError);
    expect(s.reconnects).toBe(1);
    expect(got.map((m) => [m.seq, m.gap])).toEqual([
      [1, 0],
      [5, 3],
    ]);
    expect(state.connections).toBe(2);
    expect(state.frames.map((f) => f.op)).toEqual(['subscribe', 'subscribe']);
  });

  it('reads a refused handshake as an AuthenticationError', async () => {
    const { url } = await start([() => {}]);
    const s = client(url, 'bad').stream({ channels: [channels.trades('BTCUSDT')] });
    await expect(s.connect()).rejects.toBeInstanceOf(AuthenticationError);
  });

  it('rejects a bad subscription', async () => {
    const { url } = await start([() => {}]);
    const s = client(url).stream({ channels: ['trades.futures.FAKE'] });
    await expect(s.connect()).rejects.toThrow(/Unknown symbol/);
    s.close();
  });
});
