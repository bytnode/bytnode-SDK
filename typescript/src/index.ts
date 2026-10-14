/**
 * Official TypeScript SDK of the BytNode crypto market-data API.
 *
 * ```ts
 * import { Bytnode, channels, ind } from 'bytnode';
 *
 * const client = new Bytnode();   // reads BYTNODE_API_KEY
 * const candles = await client.klines.history({ symbol: 'BTCUSDT', timeframe: '1h', limit: 24 });
 * ```
 *
 * Docs: https://bytnode.com/docs · Reference: https://api.bytnode.com/openapi.json
 */

export { Bytnode, type ClientOptions } from './client.js';
export { ApiResponse, RowIterator, type Fields, type IterOptions, type RequestOptions, type TimeLike } from './core.js';
export * from './errors.js';
export type { RateLimit } from './ratelimit.js';
export {
  Stream,
  channels,
  type BookMessage,
  type LiquidationsMessage,
  type StreamBook,
  type StreamLiquidation,
  type StreamMessage,
  type StreamOptions,
  type StreamTrade,
  type TradesMessage,
} from './stream.js';
export { IndicatorSpec, type IndicatorValue, type IndicatorsParams, type IndicatorsResult } from './indicatorSpec.js';
export * as ind from './generated/indicators.js';
export * from './generated/literals.js';
export type * from './generated/models.js';
export { API_VERSION, ROUTES, type Resources, type SnapshotData, type SnapshotParams, type Depth } from './generated/resources.js';
export { toMs } from './time.js';
export { VERSION } from './version.js';
