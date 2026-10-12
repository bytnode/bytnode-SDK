// Real-time trades and order book, with loss detection. Ctrl+C to stop.
//   npx tsx examples/stream.ts
import { Bytnode, channels } from 'bytnode';

const client = new Bytnode();
const stream = client.stream({
  channels: [channels.trades('BTCUSDT'), channels.book('BTCUSDT')],
  depth: 3,
  onGap: (channel, lost) => console.warn(`!! ${lost} message(s) lost on ${channel}`),
  onReconnect: (n) => console.warn(`reconnected (${n})`),
});

process.on('SIGINT', () => stream.close());

for await (const msg of stream) {
  if (msg.kind === 'book') {
    console.log(`book  mid ${msg.data.mid_avg}  spread ${msg.data.avg_spread_bps} bps`);
  } else {
    const notional = msg.data.reduce((sum, t) => sum + t.price * t.quantity, 0);
    console.log(`${msg.kind.padEnd(6)} ${String(msg.data.length).padStart(3)} prints, ${Math.round(notional)} USD`);
  }
}
