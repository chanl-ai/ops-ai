/**
 * The saved sign-in the Python SDK and `opsai` read: `~/.config/ops-ai/config.json`, or $OPS_CONFIG, holding named
 * profiles. Node only; a browser has no such file and gets nothing from here.
 */
import type { Config } from './transport.js';

interface SavedProfile {
  baseUrl?: string;
  apiKey?: string;
  accessToken?: string;
  refreshToken?: string;
  team?: string;
  services?: Config['services'];
}
interface SavedFile {
  current?: string;
  profiles?: Record<string, SavedProfile>;
}
// Only the parts used, so the SDK builds without @types/node.
interface NodeModules {
  fs: {
    existsSync(path: string): boolean;
    readFileSync(path: string, encoding: 'utf8'): string;
    writeFileSync(path: string, data: string, options: { mode: number }): void;
  };
  path: { join(...parts: string[]): string };
  os: { homedir(): string };
}
type NodeProcess = {
  env: Record<string, string | undefined>;
  getBuiltinModule?: (id: string) => unknown;
};

function node(): { env: NodeProcess['env']; m: NodeModules } | undefined {
  const proc = (globalThis as { process?: NodeProcess }).process;
  const get = proc?.getBuiltinModule?.bind(proc);
  if (!proc || !get) return undefined;
  return { env: proc.env, m: { fs: get('node:fs'), path: get('node:path'), os: get('node:os') } as NodeModules };
}

function configPath(n: NonNullable<ReturnType<typeof node>>): string {
  if (n.env.OPS_CONFIG) return n.env.OPS_CONFIG;
  const base = n.env.XDG_CONFIG_HOME || n.m.path.join(n.m.os.homedir(), '.config');
  return n.m.path.join(base, 'ops-ai', 'config.json');
}

/** The named profile (else $OPS_PROFILE, else the file's current one, else `default`) as client options. */
export function savedOptions(name?: string): Partial<Config> {
  const n = node();
  if (!n) return {};
  const file = configPath(n);
  if (!n.m.fs.existsSync(file)) return {};
  const saved = JSON.parse(n.m.fs.readFileSync(file, 'utf8')) as SavedFile;
  const chosen = name ?? n.env.OPS_PROFILE ?? saved.current ?? 'default';
  const p = saved.profiles?.[chosen];
  if (!p) return {};
  const out: Partial<Config> = { baseUrl: p.baseUrl, apiKey: p.apiKey, team: p.team, services: p.services };
  // A saved person's token: used unless OPS_TOKEN or an option gives another credential, as in the Python SDK.
  if (p.accessToken && !n.env.OPS_TOKEN) {
    out.accessToken = p.accessToken;
    if (p.refreshToken) {
      out.session = {
        accessToken: p.accessToken,
        refreshToken: p.refreshToken,
        onRenew: (accessToken, refreshToken) => {
          const fresh = JSON.parse(n.m.fs.readFileSync(file, 'utf8')) as SavedFile;
          Object.assign((fresh.profiles ??= {})[chosen] ?? {}, { accessToken, refreshToken });
          n.m.fs.writeFileSync(file, JSON.stringify(fresh, null, 2), { mode: 0o600 });
        },
      };
    }
  }
  return out;
}
