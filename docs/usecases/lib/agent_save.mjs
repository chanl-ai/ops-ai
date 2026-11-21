// What the ui scripts share to save an agent: the API takes a save only from a caller who names the copy it read.

/**
 * The baseVersion and baseDigest of the agent as `headers` reads it now, to spread into a PATCH body. Read it
 * immediately before the save: any other write to the agent (a reference, a skill, a publish) changes the digest.
 */
export async function agentBase(agentsUrl, headers, id) {
  const r = await fetch(`${agentsUrl}/v1/agents/${id}`, { headers });
  const copy = r.ok ? ((await r.json().catch(() => ({}))).data ?? {}) : {};
  return { baseVersion: copy.version, baseDigest: copy.digest };
}

/** PATCH `fields` on an agent as `headers`, naming the copy it just read; returns the fetch Response of the PATCH. */
export async function saveAgent(agentsUrl, headers, id, fields) {
  return fetch(`${agentsUrl}/v1/agents/${id}`, { method: 'PATCH', headers, body: JSON.stringify({ ...fields, ...(await agentBase(agentsUrl, headers, id)) }) });
}
