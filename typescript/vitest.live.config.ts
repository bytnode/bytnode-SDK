import { defineConfig } from 'vitest/config';

// Calls the production API with BYTNODE_API_KEY: `npm run test:live`.
export default defineConfig({ test: { include: ['test/live.test.ts'], testTimeout: 60_000 } });
