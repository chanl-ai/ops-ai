// The deployment's public config (agents-service `GET /v1/widget/{id}/config`), read on the server before any
// session exists. agents-service answers only a listed Origin, so the embed forwards the framing page's origin, taken
// from the request's Referer; with none, the read is refused and the chat is framed by nobody.
const AGENTS = process.env.OPS_EMBED_AGENTS_URL ?? 'http://127.0.0.1:8600';

export interface EmbedConfig {
  agentName: string;
  deploymentName: string;
  allowedOrigins: string[];
  paused: boolean;
  suggestions: string[];
}

export async function readConfig(deployment: string, tenant: string, referer: string | null): Promise<EmbedConfig | null> {
  let origin: string;
  try {
    origin = new URL(referer ?? '').origin;
  } catch {
    return null;
  }
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(tenant) || !/^[A-Za-z0-9_-]{1,64}$/.test(deployment)) return null;
  try {
    const res = await fetch(`${AGENTS}/v1/widget/${deployment}/config?tenant=${tenant}`, { cache: 'no-store', headers: { Origin: origin } });
    if (!res.ok) return null;
    return ((await res.json()) as { data: EmbedConfig }).data;
  } catch {
    return null;
  }
}
