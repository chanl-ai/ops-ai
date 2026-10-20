import fs from 'node:fs';
import path from 'node:path';

import { repoIndex } from '@/lib/repo.mjs';

// The standalone HTML pages in docs/ (an install guide, the data model, two service designs), served as they are,
// read from docs/ at build time.
const pages = () => [...repoIndex().files].filter((f) => f.startsWith('docs/') && f.endsWith('.html'));

export const dynamic = 'force-static';
export const dynamicParams = false;

export function generateStaticParams() {
  return pages().map((f) => ({ path: f.slice('docs/'.length).split('/') }));
}

export async function GET(_req: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const rel = `docs/${(await params).path.join('/')}`;
  if (!pages().includes(rel)) return new Response('Not found', { status: 404 });
  return new Response(fs.readFileSync(path.join(repoIndex().root, rel)), {
    headers: { 'content-type': 'text/html; charset=utf-8' },
  });
}
