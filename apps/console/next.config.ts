import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  // `make up ISOLATED=1` runs a second dev server from this folder; Next locks its build directory, so the second
  // server gets its own.
  distDir: process.env.OPS_CONSOLE_DIST_DIR || '.next',
};

export default nextConfig;
