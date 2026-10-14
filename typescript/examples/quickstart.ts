// First steps: latest values, a typed error, your quota.
//   export BYTNODE_API_KEY=cb_live_...
//   npx tsx examples/quickstart.ts
import { Bytnode, InvalidRequestError } from 'bytnode';

const client = new Bytnode();

const last = await client.klines({ symbol: 'BTCUSDT', timeframe: '1h' }); // the last CLOSED candle
if (last.data) console.log('last close', last.data.close, 'at', last.data.time.toISOString());

const candles = await client.klines.history({ symbol: 'BTCUSDT', timeframe: '1h', limit: 3 }); // newest first
for (const c of candles.data ?? []) console.log(c.time.toISOString(), 'close', c.close, 'volume', c.volume);

const funding = await client.funding.rate({ symbol: 'BTCUSDT' });
if (funding.data) console.log(`funding ${funding.data.rate_pct} % per 8 h`);

try {
  await client.klines({ symbol: 'BTCUSD', timeframe: '1h' });
} catch (e) {
  if (e instanceof InvalidRequestError) console.log(`refused: ${e.code} on \`${e.param}\``);
}

console.log('quota left this month:', client.lastRateLimit?.quotaRemaining ?? 'n/a');
