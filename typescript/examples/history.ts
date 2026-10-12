// A month of hourly candles, every page followed for you.
//   npx tsx examples/history.ts
import { Bytnode } from 'bytnode';

const client = new Bytnode();
const since = new Date(Date.now() - 30 * 24 * 3600 * 1000);

let rows = 0;
let high = -Infinity;
for await (const candle of client.klines.iter({ symbol: 'ETHUSDT', timeframe: '1h', since })) {
  rows++;
  if (candle.high != null) high = Math.max(high, candle.high);
}
console.log(`${rows} candles, highest high ${high}`);

const oi = await client.oi.history.iter({ symbol: 'ETHUSDT', timeframe: '1d', since }).toArray();
console.log('open interest, first and last day:', oi[0]?.time, oi.at(-1)?.time);
