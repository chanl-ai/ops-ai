import type { RunAsApi } from './run-as-contract';

type Get = <T>(path: string) => Promise<T>;

/** REST route for run-as principals; `get` comes from the main HTTP client. */
export function createRunAsHttp(get: Get): RunAsApi {
  return { principals: () => get('/run-as/principals') };
}
