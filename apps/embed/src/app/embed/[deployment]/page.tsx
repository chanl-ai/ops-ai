import { headers } from 'next/headers';

import { readConfig } from '~/config';
import { Frame } from '~/frame';

// The console's preview frames the chat too (c-232), as `src/proxy.ts` lets it; its session is minted for that origin only.
const CONSOLE = process.env.OPS_CONSOLE_URL ? new URL(process.env.OPS_CONSOLE_URL).origin : null;

/** The chat page the loader frames (c-158). `src/proxy.ts` has already set `frame-ancestors` from the same config. */
export default async function EmbedPage({ params, searchParams }: { params: Promise<{ deployment: string }>; searchParams: Promise<{ tenant?: string }> }) {
  const { deployment } = await params;
  const { tenant = '' } = await searchParams;
  const config = await readConfig(deployment, tenant, (await headers()).get('referer'));
  if (!config) return <p className="p-4 text-sm text-muted-foreground">This chat is not available.</p>;
  if (config.paused) return <p className="p-4 text-sm text-muted-foreground" data-testid="embed-paused">The assistant is paused. Ask the team that runs it.</p>;
  return <Frame deployment={deployment} agentName={config.agentName} suggestions={config.suggestions} allowedOrigins={[...config.allowedOrigins, ...(CONSOLE ? [CONSOLE] : [])]} />;
}
