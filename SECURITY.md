# Security

## Reporting a vulnerability

Please do not open a public issue. Report it privately through GitHub's
[security advisories](https://github.com/bytnode/bytnode-SDK/security/advisories/new) of this
repository, or through https://bytnode.com/contact, with the details and a way to reproduce.

## Using your API key safely

- Keep the key on the server side: environment variable `BYTNODE_API_KEY`, a secret manager, never
  in source code or in a web page. The REST API sends no CORS headers on purpose, and the TypeScript
  client refuses to run in a browser unless you opt in.
- The SDKs send the key only to `https://api.bytnode.com` and `wss://api.bytnode.com/ws` (or the
  URLs you configure), in the `X-API-KEY` header. Under Node and Python the WebSocket key also
  travels in a header, never in the URL.
- `bytnode check` and `bytnode mcp config` print the key masked (`cb_live_abcd...wxyz`).
  `bytnode mcp install` writes it into the MCP configuration file of the client you chose, as that
  client requires; a backup of the previous file is written next to it.
- A leaked key: revoke it at https://bytnode.com/dashboard/keys and create a new one.
