import { existsSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { MCP_URL, claudeCodeCommand, installMcp, mask, serverEntry } from '../src/mcp.js';

const KEY = 'cb_live_abcdefghijklmnop1234';
const dir = () => mkdtempSync(join(tmpdir(), 'bytnode-mcp-'));

describe('mcp', () => {
  it('merges into an existing config and backs it up', async () => {
    const cfg = join(dir(), 'mcp.json');
    writeFileSync(cfg, JSON.stringify({ mcpServers: { other: { url: 'https://x' } }, keep: 1 }));
    const r = await installMcp('cursor', { apiKey: KEY, path: cfg });
    const data = JSON.parse(readFileSync(cfg, 'utf8'));
    expect(data.keep).toBe(1);
    expect(data.mcpServers.other).toBeDefined();
    expect(data.mcpServers.bytnode).toEqual({ url: MCP_URL, headers: { 'X-API-KEY': KEY } });
    expect(r.backup && existsSync(r.backup)).toBe(true);
  });

  it('creates the VS Code file under "servers"', async () => {
    const cfg = join(dir(), 'sub', 'mcp.json');
    await installMcp('vscode', { apiKey: KEY, path: cfg });
    expect(JSON.parse(readFileSync(cfg, 'utf8')).servers.bytnode.type).toBe('http');
  });

  it('refuses broken JSON and changes nothing', async () => {
    const cfg = join(dir(), 'mcp.json');
    writeFileSync(cfg, '{not json');
    await expect(installMcp('cursor', { apiKey: KEY, path: cfg })).rejects.toThrow(/not valid JSON/);
    expect(readFileSync(cfg, 'utf8')).toBe('{not json');
  });

  it('dry run writes nothing', async () => {
    const cfg = join(dir(), 'mcp.json');
    await installMcp('windsurf', { apiKey: KEY, path: cfg, dryRun: true });
    expect(existsSync(cfg)).toBe(false);
  });

  it('entries per client', () => {
    expect(serverEntry('claude-desktop', KEY)).toMatchObject({ command: 'npx', env: { BYTNODE_API_KEY: KEY } });
    expect(claudeCodeCommand(KEY)).toContain(`X-API-KEY: ${KEY}`);
    expect(mask(KEY)).toBe('cb_live_abcd...1234');
  });
});
