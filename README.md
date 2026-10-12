# BytNode SDKs

Official client libraries for the [BytNode](https://bytnode.com) crypto market-data API.

| Language | Package | Install | Docs |
|---|---|---|---|
| Python 3.10+ | `bytnode` | `pip install https://github.com/bytnode/bytnode-SDK/releases/download/v0.2.0/bytnode-0.2.0-py3-none-any.whl` | [python/README.md](python/README.md) |
| TypeScript / JavaScript (Node 18+, Deno, Bun) | `bytnode` | `npm install https://github.com/bytnode/bytnode-SDK/releases/download/v0.2.0/bytnode-0.2.0.tgz` | [typescript/README.md](typescript/README.md) |

The packages are attached to each [GitHub release](https://github.com/bytnode/bytnode-SDK/releases);
they are not on PyPI or npm yet.

```python
from bytnode import Bytnode

client = Bytnode()  # reads BYTNODE_API_KEY
df = client.klines.iter("BTCUSDT", "1h", since="2026-01-01").to_pandas()
```

```ts
import { Bytnode } from 'bytnode';

const client = new Bytnode(); // reads BYTNODE_API_KEY
const { data } = await client.funding.rate({ symbol: 'BTCUSDT' });
```

Get a key at [bytnode.com/dashboard/keys](https://bytnode.com/dashboard/keys).

## What the SDKs do for you

- **Every route, typed.** All 129 REST routes, named after their path: `/v1/funding/rate/history` is
  `client.funding.rate.history(...)`. Parameters with a closed set of values are typed; every row is
  a typed model with the API's own field names and its dates already converted.
- **Pagination handled.** `.iter()` follows `next` page after page, with the largest pages the route
  allows. Time bounds as you write them: a date, an ISO string or epoch milliseconds.
- **Errors you can act on.** One exception per situation (`InvalidRequestError`,
  `PermissionDeniedError`, `RateLimitError`...) carrying the stable `code`, the faulty `param` and
  the API's explanation.
- **Retries done right.** Rate limits wait for `Retry-After`, 502/503/504 and network errors back off
  with jitter, a spent monthly quota fails fast instead of sleeping.
- **Real-time stream.** The WebSocket with automatic reconnection and re-subscription, typed
  messages, and loss detection from the sequence numbers.
- **pandas** (Python): `.to_pandas()` on any response or history, indexed by time.
- **MCP in one command.** `bytnode mcp install cursor` (or `claude-desktop`, `claude-code`, `vscode`,
  `windsurf`) plugs the BytNode MCP server into your AI client.

## How this repository works

The route methods and the models are **generated** from the public OpenAPI contract
(`spec/openapi.json`, a copy of [api.bytnode.com/openapi.json](https://api.bytnode.com/openapi.json))
by `codegen/`; the transport, retries, pagination, stream and CLI are written by hand. When the API
changes, `make update-spec generate` refreshes both SDKs — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Links

- API documentation: https://bytnode.com/docs
- API changelog: https://bytnode.com/docs/changelog
- SDK changelog: [CHANGELOG.md](CHANGELOG.md)
- Security: [SECURITY.md](SECURITY.md)

The code of the SDKs is MIT licensed ([LICENSE](LICENSE)). The data you fetch with them is governed
by your BytNode subscription.
