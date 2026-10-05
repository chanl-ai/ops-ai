import type { RunAsPrincipal } from '@/lib/types/run-as';

/**
 * Staff and roles a playground or agent test can run as. The chosen id travels on the request
 * (`QueryInput.runAsId`, `agents.test`) and the server applies that principal's permissions.
 */
export interface RunAsApi {
  principals(): Promise<RunAsPrincipal[]>;
}
