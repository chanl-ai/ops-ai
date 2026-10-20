import path from 'node:path';

import { createMDX } from 'fumadocs-mdx/next';

const repoRoot = path.resolve(import.meta.dirname, '../..');

/** @type {import('next').NextConfig} */
const config = {
  // Served under /docs so it can sit at a path of another host later.
  basePath: '/docs',
  // Every page, the search index and the HTML pages are built ahead, so the site is static files with no server code
  // that would need the repository at run time.
  output: 'export',
  images: { unoptimized: true },
  // About 700 pages; on a busy build machine the default 60 seconds per page batch is too tight.
  staticPageGenerationTimeout: 300,
  reactStrictMode: true,
  // The pages, images and OpenAPI files live outside this app (../../docs, ../../services), so the bundler and the
  // output tracing both start at the repository root.
  turbopack: { root: repoRoot },
  outputFileTracingRoot: repoRoot,
};

export default createMDX()(config);
