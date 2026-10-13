# BytNode TypeScript SDK

The official TypeScript / JavaScript client of the [BytNode](https://bytnode.com) crypto market-data
API: candles, order flow, derivatives, liquidations, options, macro, on-chain and ETF data — fully
typed, paginated for you, plus the real-time WebSocket stream.

```bash
npm install https://github.com/bytnode/bytnode-SDK/releases/download/v0.3.0/bytnode-0.3.0.tgz
export BYTNODE_API_KEY=cb_live_...   # create one at https://bytnode.com/dashboard/keys
```

```ts
import { Bytnode } from 'bytnode';

const client = new Bytnode(); // reads BYTNODE_API_KEY

const candles = await client.klines({ symbol: 'BTCUSDT', timeframe: '1h', limit: 24 });
console.log(candles.data[0].close, candles.data[0].time); // typed rows, times are Date

const since = new Date(Date.now() - 7 * 86_400_000); // inside every plan's window
for await (const row of client.funding.rate.history.iter({ symbol: 'BTCUSDT', since })) {
  console.log(row.time, row.rate_pct);
}
```

Node 18+, Deno, Bun. ESM and CommonJS, types included, one dependency (`ws`, for the stream under
Node).

> **Server-side only.** The REST API does answer browsers (CORS, any origin), but an API key in a web
> page can be read by anyone: call BytNode from your backend (Node, a serverless function...) and send your page only
> what it needs. The client refuses to start in a browser unless you pass
> `{ dangerouslyAllowBrowser: true }`.

---

## The rule: the URL is the method

Every route of the [API reference](https://bytnode.com/docs) is a property named after its path:

| Route | Method |
|---|---|
| `GET /v1/klines` | `client.klines({ symbol, timeframe, ... })` |
| `GET /v1/funding/rate` | `client.funding.rate({ symbol })` |
| `GET /v1/funding/rate/history` | `client.funding.rate.history({ symbol, ... })` |
| `GET /v1/options/max-pain/history` | `client.options.maxPain.history({ expiry: '2026-12-25', asset: 'BTC' })` |
| `GET /v1/symbols/{symbol}/capabilities` | `client.symbols.capabilities({ symbol: 'BTCUSDT' })` |
| `GET /v1/global` | `client.globalMarket()` |

Path segments are camelCase; parameter and field names are the API's own (`snake_case`), so the docs
read the same. Closed values are typed (`timeframe: Timeframe`, `asset: Asset`): a typo does not
compile. Every method carries the documentation of its route.

## Responses

```ts
const resp = await client.funding.rate({ symbol: 'BTCUSDT' });
resp.data;          // FundingRate | null — a model, an array of models, or null
resp.data?.rate_pct;
resp.serverTime;    // Date: when the server answered (rows carry their own `time`)
resp.symbol;        // effective symbol (resp.meta holds the rest of the envelope)
resp.unavailable;   // why data is empty: 'not_applicable' | 'no_api_key' | 'no_data' | null
resp.rateLimit;     // your rate limit and monthly quota after this call
resp.rows;          // data as an array, whatever its shape
resp.raw;           // the JSON body, untouched (dates as strings)
```

Every date-time field is a `Date`; dates alone (`YYYY-MM-DD`) stay strings. Fields added by the API
after this release are still there (index signature): a newer API never breaks an older SDK.

## History and pagination

Time bounds take a `Date`, an ISO string (`'2026-01-01'`, naive = UTC) or epoch milliseconds:

```ts
const since = new Date(Date.now() - 12 * 3_600_000); // inside every plan's window
const page = await client.oi.history({ symbol: 'BTCUSDT', timeframe: '1h', since, limit: 100 });
page.next; // relative URL of the following page, or null (.iter() follows it for you)

// .iter() follows `next` for you, page after page:
const rows = await client.klines.iter({ symbol: 'ETHUSDT', timeframe: '4h', since: new Date(Date.now() - 3 * 86_400_000) }).toArray();
for await (const page of client.cvd.history.iter({ symbol: 'BTCUSDT', timeframe: '1h', since }).pages()) {
  console.log(page.data.length, page.rateLimit?.quotaRemaining);
}
```

Pages are as large as the route allows (`pageSize` changes it, `maxItems` stops early). With `since`,
rows come oldest first. A number that looks like seconds is refused with the millisecond value to use.

## Errors

```ts
import { InvalidRequestError, PermissionDeniedError, RateLimitError } from 'bytnode';

try {
  await client.klines({ symbol: 'BTCUSD', timeframe: '1h' });
} catch (e) {
  if (e instanceof InvalidRequestError) console.log(e.code, e.param, e.apiMessage); // invalid_symbol symbol "Unknown symbol..."
}
```

| Class | When | Useful properties |
|---|---|---|
| `InvalidRequestError` | 400 / 422 | `code`, `param`, `apiMessage` |
| `AuthenticationError` | 401 | |
| `PermissionDeniedError` | 403: outside your plan | `reason` (`family`, `depth`, `websocket`), `code` |
| `NotFoundError` | 404: unknown or retired route | the message names the replacement |
| `RateLimitError` | 429 | `retryAfter`, `isQuota` |
| `ServerError` | 5xx (after retries) | `status` |
| `APIConnectionError` / `APITimeoutError` | no answer | |
| `MissingAPIKeyError` | no key | |
| `StreamError` / `ConnectionLimitError` | WebSocket | `code`, `closeCode` |

All extend `BytnodeError`; HTTP ones `APIError` (`status`, `code`, `param`, `details`, `reason`,
`headers`, `body`). Branch on `code` (type `ErrorCode`), never on the message.


Every error carries `requestId` (quote it to support). A value the SDK checks before sending (an indicator parameter out of range, a time in seconds instead of milliseconds) throws a plain `RangeError` at once, without a request: it is a bug in the calling code, not an API answer. Closed values such as `timeframe` are typed (`tsc` refuses `'60m'`); sent anyway, they come back from the API as a 422 (`invalid_timeframe`, with the accepted values). If the API serves a newer MAJOR contract than the SDK, a warning says so once.

## Retries, timeouts and rate limits

429 rate limits are retried after `Retry-After` (up to 60 s); 502, 503, 504 and network errors up to
`maxRetries` times (default 3) with exponential backoff and jitter; a 500 once. A spent **monthly
quota** is never retried (`RateLimitError` with `isQuota`).

```ts
const client = new Bytnode({ timeout: 10_000, maxRetries: 5 });
await client.klines({ symbol: 'BTCUSDT', timeframe: '1m' }, { timeout: 60_000, maxRetries: 0, signal });
client.lastRateLimit; // { limit, remaining, resetSeconds, quotaLimit, quotaRemaining, ... }
```

## Snapshot: many fields in one call

```ts
const snap = await client.snapshot({ symbol: 'BTCUSDT', funding_rate: true, basis: 5, klines: { '1h': 24, '1d': 7 } });
snap.data.funding_rate;   // a depth-1-only field: the object of /v1/funding/rate, or null
const bars = snap.data['klines@1h']; // Kline | Kline[] | null: a list above depth 1
if (Array.isArray(bars)) console.log(bars[0].close);
(await client.snapshot.catalog({ symbol: 'BTCUSDT' })).meta.available_fields;
```

## Technical indicators

```ts
import { ind } from 'bytnode';

const res = await client.indicators({
  symbol: 'BTCUSDT',
  timeframe: '1h',
  indicators: [ind.rsi(14), ind.macd(), ind.bb({ period: 20, std: 2.5 })],
  results: 200,
});
res.data?.indicators['rsi_14']?.values; // oldest to newest
```

Builders are typed and check their bounds locally; ids are generated (`rsi_14`) or given
(`ind.rsi({ period: 7, id: 'fast' })`).

## Real-time WebSocket

```ts
import { channels } from 'bytnode';

const stream = client.stream({
  channels: [channels.trades('BTCUSDT'), channels.book('BTCUSDT')],
  depth: 5,
  onGap: (channel, lost) => console.warn(`${lost} message(s) lost on ${channel}`),
});

for await (const msg of stream) {
  if (msg.kind === 'book') console.log(msg.data.mid_avg, msg.data.bids[0]);
  else for (const t of msg.data) console.log(t.side, t.price, t.quantity);
}
```

- **Reconnects by itself** with backoff and subscribes again (`stream.reconnects`). A refused key, a
  plan without the stream or the connection ceiling of your plan end the iteration with an error.
- Under Node the key travels in a header and a refused handshake is read precisely
  (`AuthenticationError`, `PermissionDeniedError`...), not as the mute `1006` of a raw WebSocket.
- `msg.gap` counts the messages lost before `msg` on an event channel.
- `await stream.subscribe([...])`, `await stream.unsubscribe([...])`, `stream.close()`.

## MCP and command line

```bash
npx bytnode check                       # key valid? latency? rate limit and quota left?
npx bytnode mcp install cursor          # or claude-desktop, claude-code, vscode, windsurf
npx bytnode mcp config vscode           # print the snippet (key masked)
```

From code (Node): `import { installMcp } from 'bytnode/mcp'`.

## Configuration

| Option | Environment | Default |
|---|---|---|
| `apiKey` | `BYTNODE_API_KEY` | — |
| `baseUrl` | `BYTNODE_BASE_URL` | `https://api.bytnode.com` |
| `streamUrl` | `BYTNODE_STREAM_URL` | `wss://api.bytnode.com/ws` |
| `timeout` | | 30 000 ms per attempt |
| `maxRetries` | | 3 |
| `defaultHeaders` | | |
| `fetch` | | the global `fetch` |

## Links

- Documentation: https://bytnode.com/docs
- OpenAPI contract: https://api.bytnode.com/openapi.json
- Source and issues: https://github.com/bytnode/bytnode-SDK

MIT licensed (the code of this SDK; the data stays under your BytNode subscription).
