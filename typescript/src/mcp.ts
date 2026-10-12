/**
 * Plug the BytNode MCP server into an AI client (Claude, Cursor, VS Code, Windsurf).
 * Node only (it edits files in your home directory). From the command line: `npx bytnode mcp install cursor`.
 */

import { MissingAPIKeyError } from './errors.js';

export const MCP_URL = 'https://api.bytnode.com/mcp';
export const MCP_CLIENTS = ['claude-desktop', 'claude-code', 'cursor', 'vscode', 'windsurf'] as const;
export type McpClient = (typeof MCP_CLIENTS)[number];

export function resolveKey(apiKey?: string): string {
  const key = (apiKey ?? process.env.BYTNODE_API_KEY)?.trim();
  if (!key) throw new MissingAPIKeyError();
  return key;
}

/** `cb_live_abcd...wxyz`: enough to recognise a key, not enough to use it. */
export function mask(key: string): string {
  return key.length < 16 ? '***' : `${key.slice(0, 12)}...${key.slice(-4)}`;
}

/** The `bytnode` entry of the client's MCP configuration. */
export function serverEntry(client: McpClient, apiKey: string, url = MCP_URL): Record<string, unknown> {
  switch (client) {
    case 'cursor':
      return { url, headers: { 'X-API-KEY': apiKey } };
    case 'windsurf':
      return { serverUrl: url, headers: { 'X-API-KEY': apiKey } };
    case 'vscode':
    case 'claude-code':
      return { type: 'http', url, headers: { 'X-API-KEY': apiKey } };
    case 'claude-desktop':
      // Claude Desktop's config file only starts local processes: `mcp-remote` bridges to the
      // remote server. No space after the colon: it would be split on Windows.
      return { command: 'npx', args: ['-y', 'mcp-remote', url, '--header', 'X-API-KEY:${BYTNODE_API_KEY}'], env: { BYTNODE_API_KEY: apiKey } };
    default:
      throw new RangeError(`unknown MCP client ${JSON.stringify(client)}: one of ${MCP_CLIENTS.join(', ')}`);
  }
}

/** The configuration snippet to paste by hand. */
export function mcpConfig(client: McpClient, apiKey?: string, url = MCP_URL): Record<string, unknown> {
  return { [client === 'vscode' ? 'servers' : 'mcpServers']: { bytnode: serverEntry(client, resolveKey(apiKey), url) } };
}

export async function configPath(client: McpClient): Promise<string | null> {
  const os = await import('node:os');
  const path = await import('node:path');
  const home = os.homedir();
  switch (client) {
    case 'claude-desktop':
      if (process.platform === 'win32') return path.join(process.env.APPDATA ?? path.join(home, 'AppData', 'Roaming'), 'Claude', 'claude_desktop_config.json');
      if (process.platform === 'darwin') return path.join(home, 'Library', 'Application Support', 'Claude', 'claude_desktop_config.json');
      return path.join(home, '.config', 'Claude', 'claude_desktop_config.json');
    case 'cursor':
      return path.join(home, '.cursor', 'mcp.json');
    case 'windsurf':
      return path.join(home, '.codeium', 'windsurf', 'mcp_config.json');
    case 'vscode':
      return path.join(process.cwd(), '.vscode', 'mcp.json');
    default:
      return null;
  }
}

export function claudeCodeCommand(apiKey: string, url = MCP_URL): string[] {
  return ['claude', 'mcp', 'add', '--transport', 'http', '--scope', 'user', 'bytnode', url, '--header', `X-API-KEY: ${apiKey}`];
}

export interface InstallResult {
  client: McpClient;
  path: string | null;
  backup: string | null;
  command: string[];
  ran: boolean;
  dryRun: boolean;
}

/** Add (or update) the `bytnode` server in the client's MCP configuration; the file is backed up first. */
export async function installMcp(
  client: McpClient,
  options: { apiKey?: string; path?: string; dryRun?: boolean; url?: string } = {},
): Promise<InstallResult> {
  const key = resolveKey(options.apiKey);
  const result: InstallResult = { client, path: null, backup: null, command: [], ran: false, dryRun: !!options.dryRun };
  if (client === 'claude-code') {
    result.command = claudeCodeCommand(key, options.url);
    if (!options.dryRun) {
      const { spawnSync } = await import('node:child_process');
      const r = spawnSync(result.command[0]!, result.command.slice(1), { stdio: 'inherit', shell: process.platform === 'win32' });
      result.ran = r.status === 0;
    }
    return result;
  }
  const fs = await import('node:fs');
  const path = await import('node:path');
  const target = options.path ?? (await configPath(client))!;
  result.path = target;
  const rootKey = client === 'vscode' ? 'servers' : 'mcpServers';
  let current: Record<string, unknown> = {};
  if (fs.existsSync(target)) {
    const text = fs.readFileSync(target, 'utf8').trim();
    if (text) {
      try {
        current = JSON.parse(text);
      } catch (err) {
        throw new SyntaxError(`${target} is not valid JSON (${(err as Error).message}); fix it first, nothing was changed`);
      }
    }
  }
  const servers = (current[rootKey] ??= {}) as Record<string, unknown>;
  if (typeof servers !== 'object' || Array.isArray(servers)) throw new TypeError(`${target}: '${rootKey}' is not an object; nothing was changed`);
  servers.bytnode = serverEntry(client, key, options.url);
  if (options.dryRun) return result;
  fs.mkdirSync(path.dirname(target), { recursive: true });
  if (fs.existsSync(target)) {
    const stamp = new Date().toISOString().replace(/[-:]/g, '').replace('T', '-').slice(0, 15);
    result.backup = `${target}.bak-${stamp}`;
    fs.copyFileSync(target, result.backup);
  }
  fs.writeFileSync(target, JSON.stringify(current, null, 2) + '\n', 'utf8');
  return result;
}
