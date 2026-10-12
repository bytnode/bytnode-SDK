/**
 * Every error the SDK throws.
 *
 *     BytnodeError
 *     ├── MissingAPIKeyError          no key given and BYTNODE_API_KEY not set
 *     ├── APIConnectionError          the request never got an answer
 *     │   └── APITimeoutError
 *     ├── APIError                    the API answered with an error (status, code, message…)
 *     │   ├── InvalidRequestError     400 / 422: a parameter is wrong (see `.param`)
 *     │   ├── AuthenticationError     401: key missing, invalid or revoked
 *     │   ├── PermissionDeniedError   403: outside your plan (see `.reason`)
 *     │   ├── NotFoundError           404: unknown or retired route
 *     │   ├── RateLimitError          429: rate limit or monthly quota (see `.retryAfter`)
 *     │   └── ServerError             5xx
 *     └── StreamError                 a WebSocket error frame or closing code
 *         └── ConnectionLimitError    the plan's ceiling of simultaneous connections
 *
 * Branch on `error.code` (stable, see `ErrorCode`), never on the message.
 */

export class BytnodeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = new.target.name;
  }
}

export class MissingAPIKeyError extends BytnodeError {
  constructor() {
    super(
      'No API key: pass { apiKey } or set the BYTNODE_API_KEY environment variable. ' +
        'Create a key at https://bytnode.com/dashboard/keys',
    );
  }
}

export class APIConnectionError extends BytnodeError {
  constructor(
    message: string,
    readonly cause?: unknown,
  ) {
    super(message);
  }
}

export class APITimeoutError extends APIConnectionError {}

export interface APIErrorInit {
  code?: string | null;
  param?: string | null;
  details?: unknown;
  reason?: string | null;
  requestId?: string | null;
  headers?: Headers;
  body?: unknown;
}

export class APIError extends BytnodeError {
  /** HTTP status. */
  readonly status: number;
  /** Stable `error.code` (`invalid_symbol`, `history_depth`, `rate_limited`…). */
  readonly code: string | null;
  /** English, human-readable explanation from the API. */
  readonly apiMessage: string;
  /** The parameter at fault, when there is one. */
  readonly param: string | null;
  readonly details: unknown;
  /** `X-Deny-Reason` header: `key`, `family`, `rate`, `quota`, `depth`, `websocket`. */
  readonly reason: string | null;
  /** Request identifier, when the API sends one (quote it to support). */
  readonly requestId: string | null;
  readonly headers: Headers;
  /** The decoded error body (or its raw text). */
  readonly body: unknown;

  constructor(status: number, message: string, init: APIErrorInit = {}) {
    let text = `${status}${init.code ? ` ${init.code}` : ''}: ${message}`;
    if (init.param) text += ` (param: ${init.param})`;
    if (init.requestId) text += ` [request_id: ${init.requestId}]`;
    super(text);
    this.status = status;
    this.code = init.code ?? null;
    this.apiMessage = message;
    this.param = init.param ?? null;
    this.details = init.details;
    this.reason = init.reason ?? null;
    this.requestId = init.requestId ?? null;
    this.headers = init.headers ?? new Headers();
    this.body = init.body;
  }
}

/** 400 or 422: the request is wrong. `.param` names the culprit, the message says what is accepted. */
export class InvalidRequestError extends APIError {}
/** 401: the key is missing, invalid or revoked. */
export class AuthenticationError extends APIError {}
/** 403: valid key, outside your plan. `.reason` / `.code` say which limit (`family`, `depth`, `websocket`). */
export class PermissionDeniedError extends APIError {}
/** 404: unknown route, or a retired route (the message names its replacement). */
export class NotFoundError extends APIError {}
/** 429: too many requests, or the monthly quota is spent (`isQuota`). */
export class RateLimitError extends APIError {
  /** Seconds the API asks you to wait, or `null`. */
  get retryAfter(): number | null {
    return parseRetryAfter(this.headers.get('retry-after'));
  }
  /** `true` when the monthly quota is spent (waiting seconds will not help). */
  get isQuota(): boolean {
    return this.code === 'quota_exceeded' || this.reason === 'quota';
  }
}
/** 5xx: an error on BytNode's side. 502, 503 and 504 were already retried. */
export class ServerError extends APIError {}

export class StreamError extends BytnodeError {
  constructor(
    message: string,
    readonly code: string | null = null,
    readonly closeCode: number | null = null,
  ) {
    super(code ? `${code}: ${message}` : message);
  }
}

/** The plan's ceiling on simultaneous WebSocket connections is reached (close 4003). */
export class ConnectionLimitError extends StreamError {}

export function parseRetryAfter(value: string | null): number | null {
  if (value == null) return null;
  const n = Number(value);
  if (Number.isFinite(n)) return Math.max(0, n);
  const when = Date.parse(value);
  return Number.isNaN(when) ? null : Math.max(0, (when - Date.now()) / 1000);
}

/** Build the right `APIError` subclass from an error response. */
export function errorFromResponse(status: number, headers: Headers, text: string): APIError {
  let body: unknown = text;
  let code: string | null = null;
  let param: string | null = null;
  let details: unknown;
  let message = '';
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (body && typeof body === 'object') {
    const err = (body as { error?: unknown }).error;
    if (err && typeof err === 'object') {
      const e = err as { code?: string; message?: string; param?: string; details?: unknown };
      code = e.code ?? null;
      message = e.message ?? '';
      param = e.param ?? null;
      details = e.details;
    }
  }
  if (!message) message = (text || '').trim().slice(0, 300) || `HTTP ${status}`;
  const init: APIErrorInit = {
    code,
    param,
    details,
    reason: headers.get('x-deny-reason'),
    requestId: headers.get('x-request-id'),
    headers,
    body,
  };
  const Cls =
    status === 400 || status === 422
      ? InvalidRequestError
      : status === 401
        ? AuthenticationError
        : status === 403
          ? PermissionDeniedError
          : status === 404
            ? NotFoundError
            : status === 429
              ? RateLimitError
              : status >= 500
                ? ServerError
                : APIError;
  return new Cls(status, message, init);
}
