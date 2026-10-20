import { resolve } from 'node:path';

import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  // The console image ships Next's traced server alone (deploy/fly/Dockerfile, target console). Traced from the
  // workspace root, so packages pnpm links from there are found.
  ...(process.env.OPS_CONSOLE_STANDALONE === '1' ? { output: 'standalone', outputFileTracingRoot: resolve(process.cwd(), '../..') } : {}),
  // `make up ISOLATED=1` runs a second dev server from this folder; Next locks its build directory, so the second
  // server gets its own.
  distDir: process.env.OPS_CONSOLE_DIST_DIR || '.next',
  // A use-case run hands Next its own tsconfig (extending this folder's), because Next writes the build directory's
  // type globs into whichever tsconfig it reads; the committed file then never changes during a run.
  typescript: {
    tsconfigPath: process.env.OPS_CONSOLE_TSCONFIG || 'tsconfig.json',
    // The cached production build a use case runs on is made once per source hash; `pnpm verify` is the type check,
    // so the build does not repeat it (and another lane's unfinished types do not stop the run).
    ignoreBuildErrors: process.env.OPS_CONSOLE_SKIP_TYPECHECK === '1',
  },
  experimental: {
    // Dev and build default to one worker per core and take several GB between them. Two workers compile the console
    // as fast as the dev loop needs, and worker threads stay off so a crash takes one process, not the server.
    cpus: 2,
    workerThreads: false,
    // Turbopack holds its task graph in memory; 'full' drops what a snapshot already wrote to disk after every one.
    turbopackMemoryEviction: 'full',
  },
};

export default nextConfig;
