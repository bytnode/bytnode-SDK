/** HTTP core: requests, retries, errors, date conversion, pagination. */

import { APIConnectionError, APIError, APITimeoutError, errorFromResponse, parseRetryAfter } from './errors.js';
import { MODEL_SHAPES } from './generated/models.js';
import { API_VERSION, SNAPSHOT_FIELDS } from './generated/resources.js';
import { indicatorsBody, type IndicatorsParams } from './indicatorSpec.js';
import { type RateLimit, rateLimitFromHeaders } from './ratelimit.js';
import { type TimeLike, toMs } from './time.js';
import { VERSION } from './version.js';

export type { TimeLike } from './time.js';

/** Fields to keep in each row: an array, or a comma-separated string (`"time,close"`). */
export type Fields = string | readonly string[];

export interface RequestOptions {
  /** Milliseconds before giving up on one attempt (default 30 000). */
  timeout?: number;
  /** Automatic retries on rate limits, 502/503/504 and network errors (default 3). */
  maxRetries?: number;
  /** Extra HTTP headers. */
  headers?: Record<string, string>;
  /** Cancel the request. */
  signal?: AbortSignal;
}

export interface IterOptions {
  /** Rows per request (`limit`), up to the route's maximum (the default with `since`: fewest requests). */
  pageSize?: number;
  /** Stop after this many rows. */
  maxItems?: number;
}

/** @internal What the runtime needs to know about a route (filled in by the generated code). */
export interface RouteSpec {
  path: string;
  method: string;
  shape: 'object' | 'list' | 'scalar' | 'snapshot' | 'indicators' | string;
  model: string | null;
  paginated: boolean;
  pathParams: string[];
  maxLimit: number | null;
  rangeMode: boolean;
  wire: Record<string, string>;
}

export const DEFAULT_BASE_URL = 'https://api.bytnode.com';
export const DEFAULT_TIMEOUT_MS = 30_000;
export const DEFAULT_MAX_RETRIES = 3;
/** Beyond this wait a 429 is a spent quota, not a burst: fail fast, never sleep an hour. */
const MAX_RETRY_AFTER_S = 60;
const RETRY_STATUSES = new Set([429, 502, 503, 504]);
const TIME_WIRES = new Set(['since_ms', 'until_ms', 'before_ms']);
const CURSOR_KEYS = ['since_ms', 'until_ms', 'before_ms', 'after_id', 'order', 'since', 'until', 'before'];
const ENVELOPE = new Set(['status', 'server_time', 'data_type', 'data', 'next', 'unavailable', 'partial']);

let contractWarned = false;

/** Warn once when the API serves another MAJOR contract version than this SDK. */
function checkContract(headers: Headers): void {
  const served = headers.get('bytnode-contract-version');
  if (contractWarned || !served) return;
  if (served.split('.')[0] !== API_VERSION.split('.')[0]) {
    contractWarned = true;
    console.warn(`bytnode: the API serves contract ${served}, this SDK was generated for ${API_VERSION}. Upgrade the SDK (https://bytnode.com/docs/sdk).`);
  }
}

// --------------------------------------------------------------------------- response

/** One API response. `data` is a model, an array of models, or `null` (see `unavailable`). */
export class ApiResponse<T> {
  /** The payload. */
  readonly data: T;
  /** When the server answered (not the time of the data: rows carry `time`). */
  readonly serverTime: Date | null;
  /** Stable name of the payload. */
  readonly dataType: string | null;
  /** The other keys of the envelope (`symbol`, `timeframe`, `asset`, `market`…). */
  readonly meta: Record<string, unknown>;
  /** Why `data` is empty: `not_applicable`, `no_api_key` or `no_data` (on the snapshot, field -> reason). */
  readonly unavailable: string | Record<string, string> | null;
  readonly partial: boolean | null;
  /** Parameters of the following page (`null` = last page). `.iter()` follows it for you. */
  readonly next: Record<string, unknown> | string | null;
  /** Your rate limit and monthly quota after this request. */
  readonly rateLimit: RateLimit | null;
  /** The decoded JSON body, untouched (dates as strings). */
  readonly raw: Record<string, unknown>;
  readonly status: number;
  readonly headers: Headers;

  constructor(data: T, raw: Record<string, unknown>, status: number, headers: Headers) {
    this.data = data;
    this.raw = raw;
    this.status = status;
    this.headers = headers;
    this.serverTime = typeof raw.server_time === 'string' ? new Date(raw.server_time) : null;
    this.dataType = (raw.data_type as string | undefined) ?? null;
    this.unavailable = (raw.unavailable as string | Record<string, string> | undefined) ?? null;
    checkContract(headers);
    this.partial = (raw.partial as boolean | undefined) ?? null;
    this.next = (raw.next as Record<string, unknown> | string | undefined) ?? null;
    this.meta = Object.fromEntries(Object.entries(raw).filter(([k]) => !ENVELOPE.has(k)));
    this.rateLimit = rateLimitFromHeaders(headers);
  }

  /** Effective `symbol` of the request. */
  get symbol(): string | null {
    return (this.meta.symbol as string | undefined) ?? null;
  }

  /** Effective `timeframe` of the request. */
  get timeframe(): string | null {
    return (this.meta.timeframe as string | undefined) ?? null;
  }

  /** The rows: `data` itself for a list, `[data]` for an object, `[]` for `null`. */
  get rows(): T extends Array<infer U> ? U[] : Array<NonNullable<T>> {
    const d = this.data as unknown;
    return (Array.isArray(d) ? d : d == null ? [] : [d]) as never;
  }
}

/** Every row of a period, fetched page after page as you iterate: `for await (const row of it)`. */
export class RowIterator<T> implements AsyncIterable<T> {
  constructor(
    private readonly fetchPage: (params: Record<string, unknown>) => Promise<ApiResponse<T[]>>,
    private readonly params: Record<string, unknown>,
    private readonly maxItems: number | null,
  ) {}

  /** The `ApiResponse` of each page (rate limit, `serverTime`…). */
  async *pages(): AsyncGenerator<ApiResponse<T[]>> {
    let params = { ...this.params };
    let seen = 0;
    for (;;) {
      const page = await this.fetchPage(params);
      yield page;
      seen += page.data.length;
      if (!page.next || !page.data.length || (this.maxItems != null && seen >= this.maxItems)) return;
      const next = nextParams(params, page.next);
      if (JSON.stringify(next) === JSON.stringify(params)) return; // a cursor that does not move would loop forever
      params = next;
    }
  }

  async *[Symbol.asyncIterator](): AsyncGenerator<T> {
    let count = 0;
    for await (const page of this.pages()) {
      for (const row of page.data) {
        if (this.maxItems != null && count >= this.maxItems) return;
        count++;
        yield row;
      }
    }
  }

  /** Every row, collected in an array. */
  async toArray(): Promise<T[]> {
    const out: T[] = [];
    for await (const row of this) out.push(row);
    return out;
  }
}

/**
 * The parameters of the following page: the cursor of `next` replaces ours. `next` is an object of
 * parameters today; a URL (`/v1/klines?symbol=…&before_ms=…`) is understood too.
 */
export function nextParams(params: Record<string, unknown>, next: Record<string, unknown> | string): Record<string, unknown> {
  if (typeof next === 'string') {
    const query = Object.fromEntries(new URL(next, 'https://x.invalid').searchParams);
    return { ...(params.fields != null ? { fields: params.fields } : {}), ...query };
  }
  const out = Object.fromEntries(Object.entries(params).filter(([k]) => !CURSOR_KEYS.includes(k)));
  for (const [k, v] of Object.entries(next)) if (v != null) out[k] = v;
  return out;
}

// --------------------------------------------------------------------------- dates

function convertModel(model: string | null, value: unknown): unknown {
  if (!model || value == null || typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.map((v) => convertModel(model, v));
  const shape = MODEL_SHAPES[model];
  if (!shape) return value;
  const obj = value as Record<string, unknown>;
  for (const k of shape.dates) {
    const v = obj[k];
    if (typeof v === 'string') obj[k] = new Date(v);
  }
  for (const [k, sub] of Object.entries(shape.nested)) {
    if (obj[k] != null) obj[k] = convertModel(sub, obj[k]);
  }
  return obj;
}

function parseData(route: RouteSpec, raw: Record<string, unknown>): unknown {
  const data = raw.data === undefined ? null : structuredCloneSafe(raw.data);
  switch (route.shape) {
    case 'list':
      return convertModel(route.model, Array.isArray(data) ? data : data == null ? [] : [data]);
    case 'object':
      return convertModel(route.model, data);
    case 'snapshot': {
      const obj = (data ?? {}) as Record<string, unknown>;
      for (const [k, v] of Object.entries(obj)) obj[k] = convertModel(SNAPSHOT_FIELDS[k]?.model ?? null, v);
      return obj;
    }
    case 'indicators': {
      if (data == null) return null;
      const inds = (data as { indicators?: Record<string, Record<string, unknown>> }).indicators ?? {};
      for (const ind of Object.values(inds)) if (typeof ind.time === 'string') ind.time = new Date(ind.time);
      return data;
    }
    default:
      return data;
  }
}

function structuredCloneSafe(v: unknown): unknown {
  // `raw` stays untouched: dates are converted on a copy
  return v == null || typeof v !== 'object' ? v : JSON.parse(JSON.stringify(v));
}

// --------------------------------------------------------------------------- core

export interface CoreOptions {
  apiKey: string;
  baseUrl: string;
  timeout: number;
  maxRetries: number;
  defaultHeaders: Record<string, string>;
  fetch: typeof fetch;
}

function encode(wire: string, value: unknown): string | null {
  if (value === undefined || value === null) return null;
  if (TIME_WIRES.has(wire)) return String(toMs(value as TimeLike, wire.replace(/_ms$/, '')));
  if (wire === 'fields' && Array.isArray(value)) return value.join(',');
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value);
}

function backoffMs(attempt: number): number {
  return Math.min(8000, 500 * 2 ** attempt) * (0.5 + Math.random() / 2);
}

/** @internal */
export class Core {
  lastRateLimit: RateLimit | null = null;
  /** @internal overridable in tests */
  sleep: (ms: number) => Promise<void> = (ms) => new Promise((r) => setTimeout(r, ms));

  constructor(readonly options: CoreOptions) {}

  buildUrl(route: RouteSpec, params: Record<string, unknown> = {}): string {
    let path = route.path;
    const query = new URLSearchParams();
    for (const [name, value] of Object.entries(params)) {
      const wire = route.wire[name] ?? name;
      if (route.pathParams.includes(wire)) {
        if (value == null || value === '') throw new TypeError(`${wire} is required`);
        path = path.replace(`{${wire}}`, encodeURIComponent(String(value)));
        continue;
      }
      const encoded = encode(wire, value);
      if (encoded !== null) query.append(wire, encoded);
    }
    const qs = query.toString();
    return this.options.baseUrl.replace(/\/$/, '') + path + (qs ? `?${qs}` : '');
  }

  retryDelay(res: Response | null, text: string, attempt: number, maxRetries: number): number | null {
    if (attempt >= maxRetries) return null;
    if (!res) return backoffMs(attempt);
    if (res.status === 500) return attempt === 0 ? backoffMs(attempt) : null;
    if (!RETRY_STATUSES.has(res.status)) return null;
    if (res.status === 429) {
      if (res.headers.get('x-deny-reason') === 'quota' || text.includes('quota_exceeded')) return null;
      const wait = parseRetryAfter(res.headers.get('retry-after'));
      if (wait != null) return wait > MAX_RETRY_AFTER_S ? null : wait * 1000 + Math.random() * 250;
    }
    return backoffMs(attempt);
  }

  async request<T>(route: RouteSpec, params: Record<string, unknown> = {}, options: RequestOptions = {}, body?: unknown): Promise<ApiResponse<T>> {
    const url = this.buildUrl(route, params);
    const timeout = options.timeout ?? this.options.timeout;
    const maxRetries = options.maxRetries ?? this.options.maxRetries;
    const headers: Record<string, string> = {
      'X-API-KEY': this.options.apiKey,
      Accept: 'application/json',
      ...this.options.defaultHeaders,
      ...(options.headers ?? {}),
    };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    for (let attempt = 0; ; attempt++) {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(new APITimeoutError(`no answer from ${url} within ${timeout} ms`)), timeout);
      const onAbort = () => ctrl.abort(options.signal?.reason);
      options.signal?.addEventListener('abort', onAbort, { once: true });
      let res: Response | null = null;
      let text = '';
      let failure: unknown = null;
      try {
        res = await this.options.fetch(url, {
          method: route.method,
          headers,
          body: body === undefined ? undefined : JSON.stringify(body),
          signal: ctrl.signal,
        });
        text = await res.text();
      } catch (err) {
        failure = err;
      } finally {
        clearTimeout(timer);
        options.signal?.removeEventListener('abort', onAbort);
      }
      if (failure) {
        if (options.signal?.aborted) throw options.signal.reason ?? failure;
        const delay = this.retryDelay(null, '', attempt, maxRetries);
        if (delay == null) {
          if (ctrl.signal.reason instanceof APITimeoutError) throw ctrl.signal.reason;
          throw new APIConnectionError(`could not reach ${url}: ${(failure as Error)?.message ?? String(failure)}`, failure);
        }
        await this.sleep(delay);
        continue;
      }
      const response = res as Response;
      if (response.status < 400) return this.wrap<T>(route, response, text);
      const delay = this.retryDelay(response, text, attempt, maxRetries);
      if (delay == null) throw errorFromResponse(response.status, response.headers, text);
      await this.sleep(delay);
    }
  }

  private wrap<T>(route: RouteSpec, res: Response, text: string): ApiResponse<T> {
    let raw: unknown;
    try {
      raw = JSON.parse(text);
    } catch {
      throw new APIError(res.status, `the API answered with a non-JSON body (${res.headers.get('content-type')})`, {
        headers: res.headers,
        body: text.slice(0, 500),
      });
    }
    if (!raw || typeof raw !== 'object') throw new APIError(res.status, 'unexpected response body', { headers: res.headers, body: raw });
    const obj = raw as Record<string, unknown>;
    const resp = new ApiResponse<T>(parseData(route, obj) as T, obj, res.status, res.headers);
    if (resp.rateLimit) this.lastRateLimit = resp.rateLimit;
    return resp;
  }

  iterParams(route: RouteSpec, params: Record<string, unknown> = {}): { params: Record<string, unknown>; maxItems: number | null } {
    const { pageSize, maxItems, ...rest } = params as Record<string, unknown> & IterOptions;
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(rest)) if (v != null) out[route.wire[k] ?? k] = v;
    if (pageSize != null) {
      if (pageSize < 1 || (route.maxLimit != null && pageSize > route.maxLimit)) {
        throw new RangeError(`pageSize must be between 1 and ${route.maxLimit}`);
      }
      out.limit = pageSize;
    } else if (route.maxLimit && (rest.since != null || out.since_ms != null || route.rangeMode)) {
      // The largest pages (fewest requests, least quota) when the period is bounded
      // by `since`. Without it, the route's own default page: it stops at your
      // plan's history window, where `limit=1000` would be refused (403 history_depth).
      out.limit = route.maxLimit;
    }
    if (out.order == null) {
      if (out.since_ms != null) out.order = 'asc'; // a period read from its start comes in chronological order
      else if (route.rangeMode) out.order = 'desc'; // ticks only paginate in range reading
    }
    return { params: out, maxItems: maxItems ?? null };
  }

  /** A callable resource: `fn(params, options)`, plus `fn.iter(...)` when the route paginates. */
  resource(route: RouteSpec): object {
    const fn = (params?: Record<string, unknown>, options?: RequestOptions) => this.request(route, params ?? {}, options);
    if (route.paginated) {
      Object.assign(fn, {
        iter: (params?: Record<string, unknown>, options?: RequestOptions) => {
          const { params: p, maxItems } = this.iterParams(route, params);
          return new RowIterator((q) => this.request<unknown[]>(route, q, options), p, maxItems);
        },
      });
    }
    return fn;
  }

  snapshotResource(route: RouteSpec): object {
    const fn = (params: Record<string, unknown>, options?: RequestOptions) => {
      const { symbol, ...fields } = params;
      const query: Record<string, unknown> = { symbol };
      const put = (wire: string, depth: unknown) => {
        if (depth == null || depth === false) return;
        if (depth === true) query[wire] = 'true';
        else if (typeof depth === 'number' && Number.isInteger(depth) && depth >= 1) query[wire] = depth;
        else throw new RangeError(`snapshot field ${wire}: depth must be true or an integer >= 1, got ${String(depth)}`);
      };
      for (const [name, value] of Object.entries(fields)) {
        if (value && typeof value === 'object') for (const [tf, d] of Object.entries(value)) put(`${name}@${tf}`, d);
        else put(name, value);
      }
      if (Object.keys(query).length === 1) {
        throw new RangeError("snapshot: ask for at least one field, e.g. { symbol: 'BTCUSDT', funding_rate: true } (catalog() lists them)");
      }
      return this.request(route, query, options);
    };
    return Object.assign(fn, {
      catalog: (params: { symbol: string }, options?: RequestOptions) => this.request(route, { symbol: params.symbol }, options),
    });
  }

  indicatorsResource(route: RouteSpec): object {
    return (params: IndicatorsParams, options?: RequestOptions) => {
      const body: Record<string, unknown> = {
        symbol: params.symbol,
        timeframe: params.timeframe,
        indicators: indicatorsBody(params.indicators),
      };
      if (params.results != null) body.results = params.results;
      return this.request(route, {}, options, body);
    };
  }
}

export const USER_AGENT = `bytnode-node/${VERSION}`;
