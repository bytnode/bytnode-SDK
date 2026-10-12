import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { Bytnode } from '../src/index.js';

export const SPEC = JSON.parse(readFileSync(fileURLToPath(new URL('../../spec/openapi.json', import.meta.url)), 'utf8'));
export const FORCE_REQUIRED: Record<string, string[]> = JSON.parse(
  readFileSync(fileURLToPath(new URL('../../codegen/overrides.json', import.meta.url)), 'utf8'),
).force_required;
export const BASE = 'https://api.test.bytnode';
export const KEY = 'cb_live_test_key_0123456789';

export interface Call {
  url: URL;
  init: RequestInit;
}

export type Handler = (url: URL, init: RequestInit) => Response | Promise<Response>;

/** A client whose fetch is a list of scripted answers, and that never sleeps between retries. */
export function fakeClient(handlers: Handler | Handler[]): { client: Bytnode; calls: Call[] } {
  const calls: Call[] = [];
  const queue = Array.isArray(handlers) ? [...handlers] : null;
  const fetchImpl = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input));
    calls.push({ url, init });
    const h = queue ? (queue.length > 1 ? queue.shift()! : queue[0]!) : (handlers as Handler);
    return h(url, init);
  }) as typeof fetch;
  const client = new Bytnode({ apiKey: KEY, baseUrl: BASE, fetch: fetchImpl });
  client.core.sleep = async () => {};
  return { client, calls };
}

export const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', ...headers } });

export const err = (code: string, message: string, param?: string) => ({
  status: 'error',
  server_time: '2026-10-12T09:00:00.000Z',
  error: { code, message, ...(param ? { param } : {}) },
});

export function operations(): Array<{ path: string; method: string; op: any }> {
  const out = [];
  for (const [path, ops] of Object.entries<any>(SPEC.paths)) {
    for (const [method, op] of Object.entries<any>(ops)) if (method === 'get' || method === 'post') out.push({ path, method, op });
  }
  return out;
}

export const example = (op: any) => op.responses['200'].content['application/json'].example;
