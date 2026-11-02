import { ApiError } from '../../contract';
import type { ConnectionsApi } from '../../connections-contract';
import { notFound, respond } from '../runtime';
import type { AuthKind, ConnectionDetail, ConnectionEnvironment, MyConnection } from '@/lib/types/connections';

const KINDS: AuthKind[] = [
  { id: 'none', label: 'No sign-in', signsIn: false, holdsToken: false, perPerson: false },
  { id: 'api_key', label: 'API key', signsIn: false, holdsToken: false, perPerson: true, personFields: ['key'], fields: [{ name: 'key', label: 'Key', secret: true }] },
  { id: 'basic', label: 'Username and password', signsIn: false, holdsToken: false, perPerson: true, personFields: ['username', 'password'], fields: [{ name: 'username', label: 'Username', secret: false }, { name: 'password', label: 'Password', secret: true }] },
  { id: 'oauth2_client_credentials', label: 'OAuth 2.0 client credentials', signsIn: true, holdsToken: true, perPerson: false },
  { id: 'oauth2_auth_code', label: 'OAuth 2.0 sign-in', signsIn: true, holdsToken: true, perPerson: true, personFields: [] },
];

/**
 * Two connected systems with the service's sign-in rules: a kind that signs in with the team's account only refuses
 * any other setting, and a person's own sign-in is theirs alone. The mock's sign-in returns at once through the
 * console's callback, since there is no system to send the person to.
 */
export function createConnectionsMock(deps: { me: string }): ConnectionsApi {
  const at = new Date(Date.now() - 86_400_000 * 12).toISOString();
  const env = (signedIn: boolean) => ({ set: true, settings: {}, secrets: {}, signedIn: signedIn ? { account: 'ops-team@example.com', scopes: ['api'], since: at } : null });
  const rows: ConnectionDetail[] = [
    { id: 'conn_crm', name: 'Salesforce', teamId: 'team_ops', authKind: 'oauth2_auth_code', kindLabel: 'OAuth 2.0 sign-in', status: 'healthy', signIn: 'person_or_team', teamBackup: false, health: null, mayManage: true, revision: 3, environments: { test: env(true) }, environmentsSet: ['test'], usedBy: [{ id: 'mod_crm', name: 'Case updates' }], availableTo: [], updatedAt: at },
    { id: 'conn_desk', name: 'Freshdesk', teamId: 'team_ops', authKind: 'api_key', kindLabel: 'API key', status: 'healthy', signIn: 'person', teamBackup: false, health: null, mayManage: true, revision: 1, environments: { production: env(false) }, environmentsSet: ['production'], usedBy: [], availableTo: [], updatedAt: at },
    { id: 'conn_cases', name: 'Case desk', teamId: 'team_ops', authKind: 'basic', kindLabel: 'Username and password', status: 'healthy', signIn: 'person', teamBackup: false, health: null, mayManage: true, revision: 1, environments: { production: env(false) }, environmentsSet: ['production'], usedBy: [], availableTo: [], updatedAt: at },
    { id: 'conn_itsm', name: 'ServiceNow', teamId: 'team_ops', authKind: 'oauth2_client_credentials', kindLabel: 'OAuth 2.0 client credentials', status: 'healthy', signIn: 'team', health: null, mayManage: true, revision: 1, environments: { test: env(true) }, environmentsSet: ['test'], usedBy: [], availableTo: [], updatedAt: at },
  ];
  const mine: MyConnection[] = [];
  // One person's password the system refused, so Your connections shows the refused state (c-595).
  const refusedRow = (): MyConnection => ({ ...own(rows[2], 'production'), account: 'j.richardson', refused: true, refusedAt: at, refusedReason: 'cases.example.com answered 401.' });
  const find = (id: string) => rows.find((r) => r.id === id) ?? notFound(`Connection ${id}`);
  const own = (row: ConnectionDetail, environment: ConnectionEnvironment): MyConnection => {
    const kind = KINDS.find((k) => k.id === row.authKind);
    return { connectionId: row.id, connection: row.name, connectionStatus: row.status, environment, method: kind?.label ?? row.kindLabel, authKind: row.authKind, personFields: kind?.personFields ?? [], connected: true, docsUrl: null, scopes: [], since: new Date().toISOString() };
  };
  const signIn = (id: string, environment: ConnectionEnvironment) => ({
    authorizeUrl: `/connections/callback?code=mock&state=${encodeURIComponent(`${id}:${environment}`)}`,
    redirectUri: '/connections/callback',
    connectionId: id,
    expiresAt: new Date(Date.now() + 600_000).toISOString(),
  });
  return {
    get: (id) => respond(() => find(id)),
    kinds: () => respond(() => KINDS),
    setSignIn: (id, i) =>
      respond(() => {
        const row = find(id);
        if (i.revision !== row.revision) throw new ApiError('Someone changed this connection since you opened it. Reload to see their change.', 409);
        if (i.signIn !== 'team' && !KINDS.find((k) => k.id === row.authKind)?.perPerson) throw new ApiError(`${row.kindLabel} signs in with the team's account only.`, 400);
        Object.assign(row, { signIn: i.signIn, teamBackup: i.signIn === 'person_or_team' ? Boolean(i.teamBackup) : false, revision: row.revision + 1 });
        return row;
      }),
    test: (id, i) =>
      respond(() => {
        const row = find(id);
        const own = i.account !== 'team';
        const linked = !own || mine.some((m) => m.connectionId === id && m.environment === i.environment);
        row.health = linked
          ? { status: 'ok', account: own ? 'own' : 'team', environment: i.environment, at: new Date().toISOString(), by: deps.me, httpStatus: 200, latencyMs: 180 }
          : { status: 'failed', account: 'own', environment: i.environment, at: new Date().toISOString(), by: deps.me, code: 'CONNECTION_NOT_LINKED', message: `${row.name} needs you to connect your own account.` };
        return row;
      }),
    startSignIn: (id, i) => respond(() => (find(id), signIn(id, i.environment))),
    completeSignIn: (id, i) =>
      respond(() => {
        const row = find(id);
        const environment = (i.state.split(':')[1] ?? 'test') as ConnectionEnvironment;
        if (!mine.some((m) => m.connectionId === id && m.environment === environment)) {
          mine.push({ ...own(row, environment), account: `${deps.me.toLowerCase().replace(/\s+/g, '.')}@example.com`, scopes: ['api'] });
        }
        return row;
      }),
    openConnectLink: (link) => respond(() => signIn(link.split(':')[0] || rows[0].id, 'test')),
    mine: (every) =>
      respond(() => {
        if (!mine.some((m) => m.connectionId === 'conn_cases')) mine.push(refusedRow());
        if (!every) return [...mine];
        const open = rows.filter((r) => r.signIn !== 'team' && KINDS.find((k) => k.id === r.authKind)?.perPerson);
        return open.flatMap((r) => (r.environmentsSet as ConnectionEnvironment[]).map((e) => mine.find((m) => m.connectionId === r.id && m.environment === e) ?? { ...own(r, e), connected: false, since: null }));
      }),
    giveOwn: (id, i) =>
      respond(() => {
        const row = find(id);
        const kind = KINDS.find((k) => k.id === row.authKind);
        if (row.signIn === 'team' || !kind?.personFields?.length) throw new ApiError(`${row.name} signs in with the team's account.`, 400);
        const missing = kind.personFields.filter((f) => !i.credentials[f]?.trim());
        if (missing.length) throw new ApiError(`${kind.label} needs your ${missing.join(', ')}.`, 400);
        const at = mine.findIndex((m) => m.connectionId === id && m.environment === i.environment);
        const made: MyConnection = { ...own(row, i.environment), account: i.credentials.username ?? null, refused: false };
        if (at >= 0) mine.splice(at, 1, made);
        else mine.push(made);
        return made;
      }),
    disconnect: (id, environment) =>
      respond(() => {
        const at = mine.findIndex((m) => m.connectionId === id && m.environment === environment);
        if (at < 0) notFound(`Your sign-in to ${id}`);
        mine.splice(at, 1);
      }),
  };
}
