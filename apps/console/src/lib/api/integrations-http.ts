import type { IntegrationsApi } from './integrations-contract';

type Get = <T>(path: string) => Promise<T>;

/** The connection options route; `get` comes from the main HTTP client so auth and envelopes match. */
export function createIntegrationsHttp(get: Get): IntegrationsApi {
  return { options: () => get('/integrations/options') };
}
