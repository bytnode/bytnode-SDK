"""`bytnode` command line: check a key, plug the MCP server into an AI client.

bytnode check                       # is my key valid, how fast, what is left of my quota?
bytnode mcp install cursor          # add the BytNode MCP server to Cursor
bytnode mcp config claude-desktop   # print the snippet to paste by hand
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Sequence

from . import mcp
from ._errors import APIError, BytnodeError, MissingAPIKeyError
from ._generated.routes import API_VERSION
from ._version import __version__


def _check(api_key: str | None, base_url: str | None) -> int:
    import httpx

    from ._client import Bytnode

    base = (base_url or os.environ.get("BYTNODE_BASE_URL") or "https://api.bytnode.com").rstrip("/")
    print(f"bytnode {__version__} (contract {API_VERSION}) -> {base}")
    t0 = time.perf_counter()
    try:
        health = httpx.get(base + "/v1/health", timeout=10)
    except httpx.HTTPError as exc:
        print(f"  x API unreachable: {exc}")
        return 1
    print(f"  ok API reachable ({(time.perf_counter() - t0) * 1000:.0f} ms, HTTP {health.status_code})")
    try:
        client = Bytnode(api_key, base_url=base, max_retries=0)
    except MissingAPIKeyError as exc:
        print(f"  x {exc}")
        return 1
    print(f"  .. key {mcp.mask(client.api_key)}")
    try:
        t0 = time.perf_counter()
        status = client.status()
    except APIError as exc:
        print(f"  x key refused: {exc}")
        return 1
    finally:
        client.close()
    print(f"  ok key accepted ({(time.perf_counter() - t0) * 1000:.0f} ms)")
    rl = status.rate_limit
    if rl:
        if rl.limit is not None:
            print(f"  ok rate limit: {rl.remaining}/{rl.limit} requests per {rl.window_s} s")
        if rl.quota_limit is not None:
            print(f"  ok monthly quota: {rl.quota_remaining}/{rl.quota_limit} requests left")
    else:
        print("  .. this key is not metered (no rate-limit headers)")
    data = status.data
    stale = getattr(data, "stale_feed_count", None)
    if stale is not None:
        print(f"  ok data feeds: {getattr(data, 'feed_count', '?')} monitored, {stale} stale")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bytnode", description="BytNode command line tools.")
    parser.add_argument("--version", action="version", version=f"bytnode {__version__} (contract {API_VERSION})")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="check the API key, latency and quota")
    p_check.add_argument("--api-key", help="default: BYTNODE_API_KEY")
    p_check.add_argument("--base-url", help=argparse.SUPPRESS)

    p_mcp = sub.add_parser("mcp", help="plug the BytNode MCP server into an AI client")
    mcp_sub = p_mcp.add_subparsers(dest="mcp_command", required=True)
    p_inst = mcp_sub.add_parser("install", help="write the server into the client's config")
    p_inst.add_argument("client", choices=mcp.CLIENTS)
    p_inst.add_argument("--api-key", help="default: BYTNODE_API_KEY")
    p_inst.add_argument("--path", help="config file to edit (default: the client's own)")
    p_inst.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    p_conf = mcp_sub.add_parser("config", help="print the config snippet to paste by hand")
    p_conf.add_argument("client", choices=mcp.CLIENTS)
    p_conf.add_argument("--api-key", help="default: BYTNODE_API_KEY")
    p_conf.add_argument("--show-key", action="store_true", help="print the key in clear (default: masked)")

    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            return _check(args.api_key, args.base_url)
        if args.mcp_command == "install":
            result = mcp.install(args.client, args.api_key, path=args.path, dry_run=args.dry_run)
            print(result.describe())
            if result.command and not result.ran and not args.dry_run:
                print("(the `claude` command was not found on PATH: run the command above yourself)")
            return 0
        snippet = mcp.config(args.client, args.api_key)
        text = json.dumps(snippet, indent=2)
        if not args.show_key:
            key = mcp._key(args.api_key)
            text = text.replace(key, mcp.mask(key))
        if args.client == "claude-code":
            print(
                'Run: claude mcp add --transport http bytnode https://api.bytnode.com/mcp --header "X-API-KEY: <key>"'
            )
        print(text)
        if args.client != "claude-code":
            print(f"\nFile: {mcp.config_path(args.client)}")
        return 0
    except (BytnodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
