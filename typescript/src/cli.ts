#!/usr/bin/env node
/**
 * `bytnode` command line (`npx bytnode …`):
 *
 *     bytnode check                       is my key valid, how fast, what is left of my quota?
 *     bytnode mcp install cursor          add the BytNode MCP server to Cursor
 *     bytnode mcp config claude-desktop   print the snippet to paste by hand
 */

import { Bytnode } from './client.js';
import { APIError, BytnodeError } from './errors.js';
import { API_VERSION } from './generated/resources.js';
import { MCP_CLIENTS, type McpClient, configPath, installMcp, mask, mcpConfig, resolveKey } from './mcp.js';
import { VERSION } from './version.js';

const USAGE = `bytnode ${VERSION} (contract ${API_VERSION})

Usage:
  bytnode check [--api-key KEY]
  bytnode mcp install <${MCP_CLIENTS.join('|')}> [--api-key KEY] [--path FILE] [--dry-run]
  bytnode mcp config <client> [--api-key KEY] [--show-key]

The key defaults to the BYTNODE_API_KEY environment variable.`;

function flag(args: string[], name: string): string | undefined {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : undefined;
}

async function check(apiKey?: string): Promise<number> {
  const base = (process.env.BYTNODE_BASE_URL ?? 'https://api.bytnode.com').replace(/\/$/, '');
  console.log(`bytnode ${VERSION} (contract ${API_VERSION}) -> ${base}`);
  let t0 = performance.now();
  try {
    const health = await fetch(`${base}/v1/health`);
    console.log(`  ok API reachable (${Math.round(performance.now() - t0)} ms, HTTP ${health.status})`);
  } catch (err) {
    console.log(`  x API unreachable: ${(err as Error).message}`);
    return 1;
  }
  const client = new Bytnode({ apiKey, baseUrl: base, maxRetries: 0 });
  console.log(`  .. key ${mask(client.apiKey)}`);
  t0 = performance.now();
  try {
    const status = await client.status();
    console.log(`  ok key accepted (${Math.round(performance.now() - t0)} ms)`);
    const rl = status.rateLimit;
    if (rl?.limit != null) console.log(`  ok rate limit: ${rl.remaining}/${rl.limit} requests per ${rl.windowSeconds} s`);
    if (rl?.quotaLimit != null) console.log(`  ok monthly quota: ${rl.quotaRemaining}/${rl.quotaLimit} requests left`);
    if (!rl) console.log('  .. this key is not metered (no rate-limit headers)');
    const data = status.data as { feed_count?: number; stale_feed_count?: number } | null;
    if (data?.stale_feed_count != null) console.log(`  ok data feeds: ${data.feed_count} monitored, ${data.stale_feed_count} stale`);
    return 0;
  } catch (err) {
    console.log(`  x key refused: ${err instanceof APIError ? err.message : String(err)}`);
    return 1;
  }
}

export async function main(argv: string[] = process.argv.slice(2)): Promise<number> {
  const [command, sub, target] = argv;
  try {
    if (command === 'check') return await check(flag(argv, '--api-key'));
    if (command === 'mcp' && (sub === 'install' || sub === 'config') && MCP_CLIENTS.includes(target as McpClient)) {
      const client = target as McpClient;
      if (sub === 'install') {
        const r = await installMcp(client, { apiKey: flag(argv, '--api-key'), path: flag(argv, '--path'), dryRun: argv.includes('--dry-run') });
        if (r.command.length) {
          const shown = r.command.map((a) => (a.startsWith('X-API-KEY: ') ? `"X-API-KEY: ${mask(a.slice(11))}"` : a)).join(' ');
          console.log(`${client}: ${r.ran ? 'ran' : 'run this command'}: ${shown}`);
        } else if (r.dryRun) console.log(`${client}: would write the 'bytnode' server into ${r.path}`);
        else console.log(`${client}: 'bytnode' MCP server written into ${r.path}${r.backup ? ` (backup: ${r.backup})` : ''}. Restart the client to load it.`);
        return 0;
      }
      const key = resolveKey(flag(argv, '--api-key'));
      let text = JSON.stringify(mcpConfig(client, key), null, 2);
      if (!argv.includes('--show-key')) text = text.split(key).join(mask(key));
      if (client === 'claude-code') console.log('Run: claude mcp add --transport http bytnode https://api.bytnode.com/mcp --header "X-API-KEY: <key>"');
      console.log(text);
      if (client !== 'claude-code') console.log(`\nFile: ${await configPath(client)}`);
      return 0;
    }
    if (command === '--version' || command === '-v') {
      console.log(`bytnode ${VERSION} (contract ${API_VERSION})`);
      return 0;
    }
    console.log(USAGE);
    return command === undefined || command === '--help' || command === '-h' ? 0 : 1;
  } catch (err) {
    if (err instanceof BytnodeError || err instanceof SyntaxError || err instanceof TypeError || err instanceof RangeError) {
      console.error(`error: ${err.message}`);
      return 1;
    }
    throw err;
  }
}

const invoked = typeof process !== 'undefined' && process.argv[1] && /cli\.(c|m)?js$/.test(process.argv[1]);
if (invoked) {
  // exitCode, not exit(): exiting while fetch closes its sockets crashes Node on Windows
  main().then((code) => {
    process.exitCode = code;
  });
}
