// uc-563, cli layer: docs/usecases/platform-service/a-developer-installs-the-sample-team.md. A developer runs the sample
// team installer (scripts/sample_team.py) against a stack, as `make sample-team` does: it makes a team, its people and
// their records through the public APIs; a second run finds everything and makes nothing; the team's builder then
// signs in and finds the agents and workflows. The installer's own lines go to a log, never to this script's output,
// because its FAIL lines are not this script's checks. Platform sign-in, the fake model and the fake bank.
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, openSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  AGENTS_PORT, DOCUMENTS_PORT, FILES_PORT, KB_PORT, MODELS_PORT, PLATFORM_PORT, ROOT, TOOLS_PORT, check, finish, withUiStack,
} from '@ops-ai/usecase-runner/harness';

const TAG = Math.random().toString(36).slice(2, 6);
const TEAM = `CLI bank ${TAG}`;
const PASSWORD = 'northfield-demo';
const ADMIN = 'w.kamau@harborpine.example';
// The sample team's lead, one of the people the installer adds (scripts/sample-team/sample-team.json).
const LEAD = 'alex.morgan@harborpine.example';
const LOG_DIR = join(ROOT, '.logs/usecase');

/** Runs the installer as a person would from the repository root; its lines go to its own log. */
function install(adminEnv, consoleUrl, extra = []) {
  mkdirSync(LOG_DIR, { recursive: true });
  const logPath = join(LOG_DIR, `uc563-install-${TAG}-${extra.length ? 'again' : 'first'}.log`);
  const log = openSync(logPath, 'w');
  const env = {
    ...process.env,
    OPS_PLATFORM_PORT: String(PLATFORM_PORT), OPS_AGENTS_PORT: String(AGENTS_PORT), OPS_TOOLS_PORT: String(TOOLS_PORT),
    OPS_KB_PORT: String(KB_PORT), OPS_FILES_PORT: String(FILES_PORT), OPS_DOCUMENTS_PORT: String(DOCUMENTS_PORT),
    OPS_MODELS_PORT: String(MODELS_PORT), OPS_FAKE_OPENAI_PORT: process.env.OPS_USECASE_FAKE_OPENAI_PORT ?? '8795',
  };
  const argv = ['run', '--quiet', 'python', 'scripts/sample_team.py', 'install', '--origin', consoleUrl, '--admin-env', adminEnv, '--name', TEAM, '--no-levy', ...extra];
  return new Promise((done) => {
    const child = spawn('uv', argv, { cwd: ROOT, env, stdio: ['ignore', log, log] });
    child.on('close', (code) => {
      const lines = readFileSync(logPath, 'utf8').split('\n');
      const count = (state) => lines.filter((l) => l.startsWith(`${state} `)).length;
      done({ code, made: count('MADE'), found: count('FOUND'), failed: lines.filter((l) => l.startsWith('FAIL ')).slice(0, 5), logPath });
    });
  });
}

await withUiStack(
  async (consoleUrl) => {
    const dir = mkdtempSync(join(tmpdir(), 'uc563-'));
    const adminEnv = join(dir, 'admin.env');
    writeFileSync(adminEnv, `OPS_DEMO_ADMIN_EMAIL=${ADMIN}\nOPS_DEMO_ADMIN_PASSWORD=${PASSWORD}\nOPS_DEMO_PASSWORD=${PASSWORD}\n`, { mode: 0o600 });

    const first = await install(adminEnv, consoleUrl);
    check('1 the installer makes the team, its people and their records with no FAIL line and exits 0', first.code === 0 && first.made > 0 && !first.failed.length, first);

    const again = await install(adminEnv, consoleUrl, ['--expect-found']);
    check('2 a second run finds everything and makes nothing (--expect-found exits 0)', again.code === 0 && again.made === 0 && again.found > 0 && !again.failed.length, again);

    // 3. The team's lead, one of the people the installer added, signs in and finds what it made.
    const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
    const signIn = await fetch(`${platform}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: LEAD, password: PASSWORD }) });
    const token = (await signIn.json()).data?.token;
    const teamsRes = await fetch(`${platform}/v1/teams`, { headers: { Authorization: `Bearer ${token}` } });
    const team = ((await teamsRes.json()).data ?? []).find((t) => t.name === TEAM);
    const H = { Authorization: `Bearer ${token}`, 'X-Team-Id': team?.id ?? '' };
    const read = async (path) => {
      const r = await fetch(`http://127.0.0.1:${AGENTS_PORT}${path}`, { headers: H });
      const body = await r.json().catch(() => ({}));
      const page = body.data;
      return { status: r.status, rows: Array.isArray(page) ? page : page?.items ?? page?.data ?? [] };
    };
    const agents = await read('/v1/agents?pageSize=50');
    const workflows = await read('/v1/workflows/definitions?pageSize=50');
    const agentNames = agents.rows.map((a) => a.name).sort();
    check('3 the team holds the sample agents and its workflows', !!team && agentNames.length >= 3 && workflows.rows.length >= 1, { signIn: signIn.status, teams: teamsRes.status, team: team?.id, agents: agents.status, agentNames, workflows: workflows.status, workflowIds: workflows.rows.map((w) => w.id ?? w.workflowId) });
  },
  { platform: true, demo: true, tools: { bank: 'core', gateway: true, mail: true } },
);

finish();
