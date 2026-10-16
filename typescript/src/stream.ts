/**
 * The real-time WebSocket stream: subscriptions, typed messages, automatic reconnection.
 *
 * Protocol (https://bytnode.com/docs/websocket): the key is checked at the handshake;
 * `{"op":"subscribe","channels":[…],"depth":N}` answers `op: subscribed` with EVERY active
 * channel; data messages carry `channel`, `server_time`, `seq` (monotonic per channel, arbitrary start)
 * and `data`. A jump in `seq` on an event channel means messages were lost.
 *
 * Under Node the `ws` package is used, with the key in a header: a refused handshake is read
 * (401, 403, 429, 503) instead of the mute `1006` of the standard WebSocket. Elsewhere (browsers,
 * Deno, Bun) the global `WebSocket` is used, with the key in the URL as the API documents.
 */

import { APIError, ConnectionLimitError, StreamError, errorFromResponse } from './errors.js';
import { VERSION } from './version.js';

export interface StreamTrade {
  time: Date;
  /** Same identifier as the trades of `/v1/trades/*`: deduplicate against REST. */
  id?: string;
  /** Taker side: `buy` (a buyer lifted the offer) or `sell`. */
  side: 'buy' | 'sell' | string;
  price: number;
  /** In units of the base asset. */
  quantity: number;
  /** price × quantity, in USD. */
  value_usd?: number;
}

export interface StreamLiquidation {
  time: Date;
  price: number;
  quantity: number;
  /** The liquidated position: `long` or `short`. */
  side: 'long' | 'short' | string;
  value_usd?: number;
}

export interface StreamBook {
  /** `[price, quantity]`, decreasing prices. */
  bids: Array<[number, number]>;
  /** `[price, quantity]`, increasing prices. */
  asks: Array<[number, number]>;
  /** Average of the venues' mid prices (the reference price). */
  avg_mid_price: number | null;
  /** Average per-venue spread, in basis points. */
  avg_spread_bps: number | null;
}

interface Base {
  channel: string;
  /** When the server sent the message. */
  server_time: Date;
  seq: number | null;
  /** Messages LOST just before this one on its channel (event channels only). */
  gap: number;
  /** `BTCUSDT`. */
  symbol: string;
  /** `futures` or `spot` (`null` for liquidations). */
  market: 'futures' | 'spot' | null;
}
export interface TradesMessage extends Base {
  kind: 'trades';
  data: StreamTrade[];
}
export interface LiquidationsMessage extends Base {
  kind: 'liquidations';
  data: StreamLiquidation[];
}
export interface BookMessage extends Base {
  kind: 'orderbook';
  data: StreamBook;
}
/** A message of the stream: narrow it with `msg.kind`. */
export type StreamMessage = TradesMessage | LiquidationsMessage | BookMessage;

export interface StreamOptions {
  /** Channels to subscribe to at connection: `trades.futures.BTCUSDT` (see `channels`). */
  channels?: string[];
  /** Order book depth, 1 to 5 (default 5). */
  depth?: number;
  /** Reconnect and subscribe again after a drop (default true). */
  reconnect?: boolean;
  /** Give up after this many reconnections (default: never). */
  maxReconnects?: number;
  /** Called when messages were lost on an event channel. */
  onGap?: (channel: string, lost: number) => void;
  /** Called after each successful reconnection. */
  onReconnect?: (attempt: number) => void;
}

interface Socket {
  send(data: string): void;
  close(code?: number, reason?: string): void;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: ((ev: { code: number; reason: string }) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  onopen: (() => void) | null;
}

const EVENT_KINDS = new Set(['trades', 'liquidations']);
const REPLY_TIMEOUT_MS = 10_000;
const END = Symbol('end');

export function normalizeChannel(channel: string): string {
  if (typeof channel !== 'string') {
    throw new TypeError(
      `a channel is a string such as 'trades.futures.BTCUSDT', got ${Array.isArray(channel) ? 'an array' : typeof channel}: ` +
        'pass channels as separate arguments, or spread an array (...names)',
    );
  }
  const parts = channel.trim().split('.');
  if (parts.length < 2) throw new RangeError(`invalid channel ${JSON.stringify(channel)}: expected e.g. 'trades.futures.BTCUSDT'`);
  return [...parts.slice(0, -1).map((p) => p.toLowerCase()), parts[parts.length - 1]!.toUpperCase()].join('.');
}

export function classifyClose(code: number, reason: string): StreamError | null {
  if (code === 4001) return new StreamError(reason || 'key refused', 'invalid_api_key', code);
  // 4005 = the client fell behind: reconnect, it starts fresh.
  if (code === 4005 || (code === 4003 && /slow/i.test(reason))) return null;
  if (code === 4003) {
    return new ConnectionLimitError(reason || "the plan's ceiling of simultaneous connections is reached", 'connection_limit', code);
  }
  if (code === 1008) return new StreamError(reason || 'policy violation', 'policy_violation', code);
  return null;
}

function toMessage(obj: Record<string, unknown>): StreamMessage {
  const channel = String(obj.channel);
  const parts = channel.split('.');
  const kind = parts[0] as StreamMessage['kind'];
  const base = {
    channel,
    server_time: new Date(String(obj.server_time)),
    seq: typeof obj.seq === 'number' ? obj.seq : null,
    gap: 0,
    symbol: parts[parts.length - 1] ?? '',
    market: (parts.length === 3 ? parts[1] : null) as Base['market'],
  };
  if (kind === 'orderbook') return { ...base, kind, data: obj.data as StreamBook };
  const rows = ((obj.data as Array<Record<string, unknown>>) ?? []).map((r) => ({ ...r, time: new Date(String(r.time)) }));
  if (kind === 'liquidations') return { ...base, kind, data: rows as unknown as StreamLiquidation[] };
  return { ...base, kind: 'trades', data: rows as unknown as StreamTrade[] };
}

function backoffMs(attempt: number): number {
  return Math.min(30_000, 500 * 2 ** attempt) * (0.5 + Math.random() / 2);
}

const isNode = typeof process !== 'undefined' && !!process.versions?.node && typeof (globalThis as { Bun?: unknown }).Bun === 'undefined';

/** `for await (const msg of client.stream({ channels: [...] }))` — reconnects by itself. */
export class Stream implements AsyncIterable<StreamMessage> {
  /** The active channels, as last confirmed by the server. */
  channels: string[] = [];
  /** How many times the stream reconnected. */
  reconnects = 0;

  private socket: Socket | null = null;
  private wanted: Set<string>;
  private depth: number | undefined;
  private queue: Array<StreamMessage | Error | typeof END> = [];
  private waiters: Array<() => void> = [];
  private pending: Array<{ resolve: (v: Record<string, unknown>) => void; reject: (e: Error) => void }> = [];
  private expected = new Map<string, number>();
  private closed = false;
  private connecting: Promise<void> | null = null;
  private openedAt = 0;

  /** @internal overridable in tests */
  backoff: (attempt: number) => number = backoffMs;

  constructor(
    private readonly url: string,
    private readonly apiKey: string,
    private readonly options: StreamOptions = {},
  ) {
    if (options.depth != null && !(options.depth >= 1 && options.depth <= 5)) throw new RangeError(`depth must be between 1 and 5, got ${options.depth}`);
    this.wanted = new Set((options.channels ?? []).map(normalizeChannel));
    this.depth = options.depth;
  }

  /** Open the connection and subscribe to the channels given at creation (called by the first iteration). */
  connect(): Promise<void> {
    this.connecting ??= (async () => {
      await this.open();
      if (this.wanted.size) await this.ask('subscribe', [...this.wanted]);
    })();
    return this.connecting;
  }

  /** Add channels; resolves to every active channel. All or nothing: one bad channel, none applied. */
  async subscribe(channels: string[], options: { depth?: number } = {}): Promise<string[]> {
    if (options.depth != null) this.depth = options.depth;
    const names = channels.map(normalizeChannel);
    await this.connect();
    const reply = await this.ask('subscribe', names);
    names.forEach((n) => this.wanted.add(n));
    return (reply.channels as string[]) ?? [];
  }

  /** Remove channels; resolves to the channels still active. */
  async unsubscribe(channels: string[]): Promise<string[]> {
    const names = channels.map(normalizeChannel);
    const reply = await this.ask('unsubscribe', names);
    names.forEach((n) => this.wanted.delete(n));
    return (reply.channels as string[]) ?? [];
  }

  /** Close the connection and end the iteration. */
  close(): void {
    this.closed = true;
    this.socket?.close(1000, 'client closed');
    this.push(END);
  }

  async *[Symbol.asyncIterator](): AsyncGenerator<StreamMessage> {
    await this.connect();
    for (;;) {
      while (!this.queue.length) await new Promise<void>((r) => this.waiters.push(r));
      const item = this.queue.shift()!;
      if (item === END) return;
      if (item instanceof Error) throw item;
      yield item;
    }
  }

  // ------------------------------------------------------------------ internals

  private frame(op: string, channels: string[]): string {
    const msg: Record<string, unknown> = { op, channels: [...channels].sort() };
    if (op === 'subscribe' && this.depth != null) msg.depth = this.depth;
    return JSON.stringify(msg);
  }

  private ask(op: string, channels: string[]): Promise<Record<string, unknown>> {
    const socket = this.socket;
    if (!socket) return Promise.reject(new StreamError('the stream is not connected'));
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new StreamError('no answer from the server', 'timeout')), REPLY_TIMEOUT_MS);
      this.pending.push({
        resolve: (v) => (clearTimeout(timer), resolve(v)),
        reject: (e) => (clearTimeout(timer), reject(e)),
      });
      socket.send(this.frame(op, channels));
    });
  }

  private push(item: StreamMessage | Error | typeof END): void {
    this.queue.push(item);
    this.waiters.splice(0).forEach((w) => w());
  }

  private async open(): Promise<void> {
    const socket = await this.createSocket();
    this.socket = socket;
    this.openedAt = Date.now();
    socket.onmessage = (ev) => this.handle(typeof ev.data === 'string' ? ev.data : String(ev.data));
    socket.onclose = (ev) => void this.onClose(ev.code, ev.reason);
  }

  private async createSocket(): Promise<Socket> {
    if (isNode) {
      let WS: unknown;
      try {
        WS = (await import('ws')).default;
      } catch {
        WS = null;
      }
      if (WS) return this.openWithWs(WS as new (url: string, opts: object) => unknown);
    }
    const Global = (globalThis as { WebSocket?: new (url: string) => Socket }).WebSocket;
    if (!Global) throw new StreamError('no WebSocket implementation: install the `ws` package');
    const url = `${this.url}${this.url.includes('?') ? '&' : '?'}api_key=${encodeURIComponent(this.apiKey)}`;
    return new Promise((resolve, reject) => {
      const s = new Global(url);
      s.onopen = () => resolve(s);
      s.onerror = () => reject(new StreamError('the WebSocket handshake failed (key refused, plan without the stream, or service unavailable)', 'handshake_failed'));
    });
  }

  private openWithWs(WS: new (url: string, opts: object) => unknown): Promise<Socket> {
    return new Promise((resolve, reject) => {
      const s = new WS(this.url, { headers: { 'X-API-KEY': this.apiKey, 'User-Agent': `bytnode-node/${VERSION}` }, maxPayload: 0 }) as {
        on(ev: string, fn: (...a: unknown[]) => void): void;
        send(d: string): void;
        close(c?: number, r?: string): void;
      };
      const adapter: Socket = {
        send: (d) => s.send(d),
        close: (c, r) => s.close(c, r),
        onmessage: null,
        onclose: null,
        onerror: null,
        onopen: null,
      };
      s.on('open', () => resolve(adapter));
      s.on('message', (data) => adapter.onmessage?.({ data: String(data) }));
      s.on('close', (code, reason) => adapter.onclose?.({ code: Number(code), reason: String(reason ?? '') }));
      s.on('error', (err) => reject(err instanceof Error ? new StreamError(err.message, 'handshake_failed') : err));
      s.on('unexpected-response', (_req, res) => {
        const r = res as { statusCode: number; headers: Record<string, string>; on(ev: string, fn: (c?: unknown) => void): void };
        let text = '';
        r.on('data', (chunk) => (text += String(chunk)));
        r.on('end', () => reject(errorFromResponse(r.statusCode, new Headers(r.headers), text)));
      });
    });
  }

  private handle(raw: string): void {
    let obj: Record<string, unknown>;
    try {
      obj = JSON.parse(raw);
    } catch {
      return;
    }
    const op = obj.op as string | undefined;
    if (op) {
      if (op === 'error') {
        // `{error: {code, message, param, details}}` (the flat
        // `code` / `message` of earlier versions is still read).
        const e = (typeof obj.error === 'object' && obj.error !== null ? obj.error : obj) as Record<string, unknown>;
        const err = new StreamError(
          String(e.message ?? 'stream error'),
          (e.code as string) ?? null,
          null,
          (e.param as string) ?? null,
          e.details ?? null,
        );
        const p = this.pending.shift();
        if (p) p.reject(err);
        else this.push(err);
        return;
      }
      if (Array.isArray(obj.channels)) this.channels = obj.channels as string[];
      if (op === 'subscribed' || op === 'unsubscribed') this.pending.shift()?.resolve(obj);
      return;
    }
    if (typeof obj.channel !== 'string') return;
    const msg = toMessage(obj);
    if (msg.seq != null && EVENT_KINDS.has(msg.kind)) {
      const expected = this.expected.get(msg.channel);
      if (expected != null && msg.seq > expected) {
        msg.gap = msg.seq - expected;
        this.options.onGap?.(msg.channel, msg.gap);
      }
      this.expected.set(msg.channel, msg.seq + 1);
    }
    this.push(msg);
  }

  private async onClose(code: number, reason: string): Promise<void> {
    this.socket = null;
    if (this.closed) return;
    this.pending.splice(0).forEach((p) => p.reject(new StreamError('connection lost before the server answered', 'connection_lost')));
    const fatal = classifyClose(code, reason);
    if (fatal || this.options.reconnect === false) {
      this.push(fatal ?? new StreamError(`connection closed (${code} ${reason})`.trim(), 'closed', code));
      return;
    }
    let attempt = Date.now() - this.openedAt > 60_000 ? 0 : this.reconnects;
    while (!this.closed) {
      if (this.options.maxReconnects != null && this.reconnects >= this.options.maxReconnects) {
        this.push(new StreamError(`gave up after ${this.reconnects} reconnections`, 'reconnect_failed'));
        return;
      }
      await new Promise((r) => setTimeout(r, this.backoff(attempt++)));
      this.reconnects++;
      try {
        await this.open();
      } catch (err) {
        if (err instanceof APIError && err.status !== 429 && err.status < 500) {
          this.push(err);
          return;
        }
        continue;
      }
      if (this.wanted.size) (this.socket as Socket | null)?.send(this.frame("subscribe", [...this.wanted]));
      this.options.onReconnect?.(this.reconnects);
      return;
    }
  }
}

/** Names of the WebSocket channels, without typos. */
export const channels = {
  /** Every execution of `symbol`, pushed in 100 ms packets. */
  trades: (symbol: string, market: 'futures' | 'spot' = 'futures') => `trades.${checkMarket(market)}.${symbol.toUpperCase()}`,
  /** The consolidated order book of `symbol`, every 100 ms: `orderbook.<market>.<SYMBOL>`. */
  orderbook: (symbol: string, market: 'futures' | 'spot' = 'futures') => `orderbook.${checkMarket(market)}.${symbol.toUpperCase()}`,
  /** The liquidations of `symbol` (perpetual futures). */
  liquidations: (symbol: string) => `liquidations.${symbol.toUpperCase()}`,
};

function checkMarket(m: string): string {
  if (m !== 'futures' && m !== 'spot') throw new RangeError(`market must be 'futures' or 'spot', got ${JSON.stringify(m)}`);
  return m;
}
