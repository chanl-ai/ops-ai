/** The Ops AI SDK for TypeScript; docs: https://opsai.chanl.ai/docs/sdk/typescript */
export { type ArgsOf, type DataOf, NOUNS, OpsAI, Raw, Resource, TERMINAL, type WaitedRun } from './client.js';
export {
  BadRequest, Conflict, Forbidden, NotFound, OpsError, RateLimited, ServerError, Unauthorized,
} from './errors.js';
export type { Config, Service, ServerEvent } from './transport.js';
