import type { ConnectionRef } from '@/lib/types/integrations';

/**
 * The connections a knowledge source can read through. The sample integrations pages and their writes are gone
 * (c-617); apps are connected on the Apps pages over tools-service.
 */
export interface IntegrationsApi {
  options(): Promise<ConnectionRef[]>;
}
