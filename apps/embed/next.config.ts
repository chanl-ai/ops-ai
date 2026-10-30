import { resolve } from 'node:path';

import type { NextConfig } from 'next';

// The embed app draws the console's own chat components from apps/console/src (c-158). `@/lib/api` resolves to this
// app's widget client instead of the console's, so nothing reaches console routes; `scripts/check-bundle.mjs` proves it.
const AGENTS = process.env.OPS_EMBED_AGENTS_URL ?? 'http://127.0.0.1:8600';

const nextConfig: NextConfig = {
  distDir: process.env.OPS_EMBED_DIST_DIR || '.next',
  // A use-case run hands Next its own tsconfig, as for the console, so the committed one never gains build globs.
  typescript: { tsconfigPath: process.env.OPS_EMBED_TSCONFIG || 'tsconfig.json' },
  turbopack: {
    root: resolve(__dirname, '../..'),
    resolveAlias: { '@/lib/api': './src/widget-api/index.ts' },
  },
  // A hosted form's address carries its token (c-535): no Referer may take it to another site, and no page may frame
  // the form. proxy.ts sets frame-ancestors only for /embed/ pages, from each deployment's origins.
  async headers() {
    return [
      {
        source: '/f/:path*',
        headers: [
          { key: 'Referrer-Policy', value: 'no-referrer' },
          { key: 'Content-Security-Policy', value: "frame-ancestors 'none'" },
        ],
      },
    ];
  },
  // One host for the loader, the page, the config and the widget API, as a bank's ingress routes them.
  async rewrites() {
    return [
      { source: '/v1/:path*', destination: `${AGENTS}/v1/:path*` },
      { source: '/embed/v1.js', destination: `${AGENTS}/embed/v1.js` },
    ];
  },
};

export default nextConfig;
