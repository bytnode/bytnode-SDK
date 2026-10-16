import { BytnodeError, MissingAPIKeyError } from './errors.js';
import { Core, DEFAULT_BASE_URL, DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT_MS } from './core.js';
import type { RateLimit } from './ratelimit.js';
import { createResources, type Resources } from './generated/resources.js';
import { Stream, type StreamOptions } from './stream.js';
import { VERSION } from './version.js';

export interface ClientOptions {
  /** Your key (`cb_live_…`). Default: the `BYTNODE_API_KEY` environment variable. */
  apiKey?: string;
  /** Default `https://api.bytnode.com` (or `BYTNODE_BASE_URL`). */
  baseUrl?: string;
  /** Milliseconds per attempt (default 30 000). */
  timeout?: number;
  /** Automatic retries on 429 (rate limit), 502, 503, 504 and network errors (default 3; a spent monthly quota is never retried). */
  maxRetries?: number;
  /** Extra headers sent with every request. */
  defaultHeaders?: Record<string, string>;
  /** Your own `fetch` (proxies, tests…). Default: the global one (Node 18+, Deno, Bun). */
  fetch?: typeof fetch;
  /** WebSocket URL (default `wss://api.bytnode.com/ws`). */
  streamUrl?: string;
  /**
   * The REST API is server-side only (it sends no CORS headers, and a key in a web page is a key
   * anyone can read). Set this to `true` only if you know what you are doing.
   */
  dangerouslyAllowBrowser?: boolean;
}

const env = (name: string): string | undefined =>
  typeof process !== 'undefined' && process.env ? process.env[name] : undefined;

const inBrowser = typeof window !== 'undefined' && typeof (globalThis as { document?: unknown }).document !== 'undefined';

// The resource properties (`client.klines`, `client.funding`…) are declared by this interface
// merge: they are created in the constructor from the generated route table.
export interface Bytnode extends Resources {}

/**
 * Client of the BytNode API.
 *
 * ```ts
 * import { Bytnode } from 'bytnode';
 *
 * const client = new Bytnode();                                   // reads BYTNODE_API_KEY
 * const { data } = await client.klines.history({ symbol: 'BTCUSDT', timeframe: '1h', limit: 24 });
 * for await (const row of client.funding.rate.history.iter({ symbol: 'BTCUSDT', since: '2026-01-01' })) {}
 * ```
 *
 * Every route is a property named after its path: `/v1/funding/rate/history` is
 * `client.funding.rate.history(...)`.
 */
export class Bytnode {
  /** Your API key (not enumerable: it is never serialized with the client). */
  declare readonly apiKey: string;
  readonly baseUrl: string;
  readonly streamUrl: string;
  /** @internal */
  readonly core: Core;

  constructor(options: ClientOptions = {}) {
    if (inBrowser && !options.dangerouslyAllowBrowser) {
      throw new BytnodeError(
        'Keep the BytNode API key server-side: an API key in a web page can be read by anyone. ' +
          'Call it from your backend (Node, Deno, Bun, a serverless function) and send your page only what it needs. ' +
          'Pass { dangerouslyAllowBrowser: true } to override.',
      );
    }
    const key = (options.apiKey ?? env('BYTNODE_API_KEY'))?.trim();
    if (!key) throw new MissingAPIKeyError();
    // Not enumerable: `JSON.stringify(client)`, `{ ...client }` or a structured logger
    // never write the key (see also `toJSON` and the Node inspector below).
    Object.defineProperty(this, 'apiKey', { value: key, enumerable: false, writable: false });
    this.baseUrl = options.baseUrl ?? env('BYTNODE_BASE_URL') ?? DEFAULT_BASE_URL;
    this.streamUrl = options.streamUrl ?? env('BYTNODE_STREAM_URL') ?? 'wss://api.bytnode.com/ws';
    const fetchImpl = options.fetch ?? globalThis.fetch?.bind(globalThis);
    if (!fetchImpl) throw new BytnodeError('no global fetch: use Node 18+, or pass { fetch }');
    this.core = new Core({
      apiKey: key,
      baseUrl: this.baseUrl,
      timeout: options.timeout ?? DEFAULT_TIMEOUT_MS,
      maxRetries: options.maxRetries ?? DEFAULT_MAX_RETRIES,
      defaultHeaders: { ...(inBrowser ? {} : { 'User-Agent': `bytnode-node/${VERSION}` }), ...(options.defaultHeaders ?? {}) },
      fetch: fetchImpl,
    });
    Object.assign(this, createResources(this.core));
  }

  /** What `JSON.stringify(client)` writes: never the API key. */
  toJSON(): { baseUrl: string; streamUrl: string } {
    return { baseUrl: this.baseUrl, streamUrl: this.streamUrl };
  }

  /** What `console.log(client)` shows in Node: never the API key. */
  [Symbol.for('nodejs.util.inspect.custom')](): string {
    return `Bytnode { baseUrl: '${this.baseUrl}' }`;
  }

  /** Your rate limit and monthly quota, as announced by the last response. */
  get lastRateLimit(): RateLimit | null {
    return this.core.lastRateLimit;
  }

  /**
   * The real-time WebSocket stream.
   *
   * ```ts
   * const stream = client.stream({ channels: [channels.trades('BTCUSDT'), channels.orderbook('BTCUSDT')] });
   * for await (const msg of stream) {
   *   if (msg.kind === 'orderbook') console.log(msg.data.avg_mid_price);
   *   else for (const t of msg.data) console.log(t.price, t.quantity);
   * }
   * ```
   * Reconnects by itself and subscribes again; `msg.gap` counts the messages lost before `msg`.
   */
  stream(options: StreamOptions = {}): Stream {
    // Without the `ws` package (browser, Deno, Bun), the stream asks `POST /v1/ws/token` for
    // a short-lived token instead of putting the key in the URL.
    const issueToken = async (): Promise<string> => {
      const resp = await this.ws.token();
      const token = resp.data?.token;
      if (!token) throw new BytnodeError('POST /v1/ws/token returned no token');
      return token;
    };
    return new Stream(this.streamUrl, this.apiKey, options, issueToken);
  }
}
