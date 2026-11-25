// What deploy/fly/smoke.mjs shares with its tests: the renewal of the admin's token, the list of what a run made and
// its removal, and the sweep of what an earlier run that stopped part-way left in the team.

const APPROVER = /^smoke-approver-[a-z0-9]+@example\.com$/;
const AGENT = /^Smoke [a-z0-9]{4}$/;

/**
 * A fetch that renews the admin's session once on a 401 and sends the call again. The platform refuses every token
 * issued before a role, membership or policy change (401 permissions_changed), and the walk's own invite is such a
 * change. `headers` is the admin's header object, updated in place so calls built afterwards carry the new token.
 * `renew(sent)` is the SDK transport's renewal: it puts the new Authorization into `sent` and answers whether it did.
 */
export function renewingFetch({ plainFetch, renew, headers }) {
  const adminTokens = new Set([headers.Authorization]);
  const f = async (input, init) => {
    const response = await plainFetch(input, init);
    const sent = init?.headers && !Array.isArray(init.headers) && !(init.headers instanceof Headers) ? { ...init.headers } : null;
    if (response.status !== 401 || !sent?.Authorization || !adminTokens.has(sent.Authorization) || !(await renew(sent))) {
      return response;
    }
    headers.Authorization = sent.Authorization;
    adminTokens.add(sent.Authorization);
    return plainFetch(input, { ...init, headers: sent });
  };
  /** Renews now, for a caller that knows it changed the permissions. */
  f.refresh = async () => {
    const sent = { ...headers };
    if (!(await renew(sent))) return false;
    headers.Authorization = sent.Authorization;
    adminTokens.add(sent.Authorization);
    return true;
  };
  return f;
}

/** The records one run makes, registered as each is made so a run that throws still removes them. */
export function removals({ origin, headers, fetchImpl = globalThis.fetch, log = console.log }) {
  const steps = [];
  return {
    add(what, method, path, body) {
      if (!steps.some((s) => s.method === method && s.path === path)) steps.push({ what, method, path, body });
    },
    /** Deletes in reverse order of making; a refusal is printed, never a failure. */
    async run() {
      for (const { what, method, path, body } of steps.reverse()) {
        let r = await fetchImpl(`${origin}${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined }).catch((e) => ({ status: String(e) }));
        if (what === 'workflow' && r.status === 409) {
          // A workflow that has run keeps its versions for its runs: archived, it leaves the lists and starts nothing.
          r = await fetchImpl(`${origin}${path}/archive`, { method: 'POST', headers }).catch((e) => ({ status: String(e) }));
        }
        log(`${typeof r.status === 'number' && r.status < 300 ? 'REMOVED' : 'KEPT   '} ${what} ${path} ${r.status}`);
      }
    },
  };
}

const rowsOf = (body) => (Array.isArray(body?.data) ? body.data : Array.isArray(body) ? body : []);

/** Removes the approvers and agents earlier runs left in the team, by the names the walk gives them. */
export async function sweepStale({ origin, headers, fetchImpl = globalThis.fetch, log = console.log }) {
  const read = async (path) => rowsOf((await (await fetchImpl(`${origin}${path}`, { headers })).json().catch(() => ({}))).data);
  const found = [];
  try {
    for (const m of await read('/api/platform/v1/settings/members?search=smoke-approver&pageSize=100')) {
      if (APPROVER.test(m.email ?? '')) found.push(['approver', 'POST', '/api/platform/v1/settings/members/delete', { ids: [m.id] }]);
    }
    for (const a of await read('/api/agents/v1/agents?search=Smoke&pageSize=100')) {
      if (AGENT.test(a.name ?? '')) found.push(['agent', 'DELETE', `/api/agents/v1/agents/${a.id}`]);
    }
  } catch (e) {
    log(`KEPT    sweep of earlier runs: ${e}`);
  }
  const sweep = removals({ origin, headers, fetchImpl, log: (line) => log(`${line} (an earlier run's)`) });
  for (const f of found) sweep.add(...f);
  await sweep.run();
  return found.length;
}

