import type { EvalCase, EvalCheck } from '@/lib/types/evals';
import type { ListParams } from '@/lib/types/query';

import type { EvalsApi } from './evals-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

interface WireCase {
  id: string;
  name: string;
  input: string;
  context: { collections?: string[] } | null;
  checks: { type: string; tool?: string | null; text?: string | null; rubric?: string | null }[];
  status: string;
  source: string;
  createdBy: string;
  createdAt: string;
}

/** The service answers nulls for the check fields a type does not use; the console leaves them unset. */
const kase = (c: WireCase): EvalCase => ({
  id: c.id,
  name: c.name,
  input: c.input,
  collections: c.context?.collections ?? [],
  checks: c.checks.map((k): EvalCheck => ({ type: k.type as EvalCheck['type'], ...(k.tool && { tool: k.tool }), ...(k.text && { text: k.text }), ...(k.rubric && { rubric: k.rubric }) })),
  status: c.status,
  source: c.source,
  createdBy: c.createdBy,
  createdAt: c.createdAt,
});

/** REST routes for agent evals; `get`, `send` and `qs` come from the HTTP transport of the service they are on. */
export function createEvalsHttp(get: Get, send: Send, qs: (p: ListParams) => string): EvalsApi {
  return {
    cases: async (aid) => (await get<{ cases: WireCase[] }>(`/agents/${aid}/eval-cases`)).cases.map(kase),
    addCases: async (aid, cases) =>
      (
        await send<{ cases: WireCase[] }>(
          'POST',
          `/agents/${aid}/eval-cases`,
          { cases: cases.map((c) => ({ name: c.name, input: c.input, context: { collections: c.collections }, checks: c.checks })) },
        )
      ).cases.map(kase),
    removeCase: (id) => send('DELETE', `/eval-cases/${id}`),
    run: (aid) => send('POST', `/agents/${aid}/eval-runs`),
    runs: (aid, p) => get(`/agents/${aid}/eval-runs?${qs(p)}`),
    getRun: (id) => get(`/eval-runs/${id}`),
  };
}
