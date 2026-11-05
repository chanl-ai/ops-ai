import { ApiError } from '../../contract';
import type { ConnectionsApi } from '../../connections-contract';
import { notFound, respond } from '../runtime';
import type { AuthKind, ConnectionStatus, MyConnection, SignInSetting } from '@/lib/types/connections';

const KINDS: AuthKind[] = [
  { id: 'none', label: 'No sign-in', signsIn: false, holdsToken: false, perPerson: false },
  { id: 'api_key', label: 'API key', signsIn: false, holdsToken: false, perPerson: true, personFields: ['key'], fields: [{ name: 'key', label: 'Key', secret: true }] },
  { id: 'basic', label: 'Username and password', signsIn: false, holdsToken: false, perPerson: true, personFields: ['username', 'password'], fields: [{ name: 'username', label: 'Username', secret: false }, { name: 'password', label: 'Password', secret: true }] },
  { id: 'oauth2_client_credentials', label: 'OAuth 2.0 client credentials', signsIn: true, holdsToken: true, perPerson: false },
  { id: 'oauth2_auth_code', label: 'OAuth 2.0 sign-in', signsIn: true, holdsToken: true, perPerson: true, personFields: [] },
];

/** An account of one of the team's apps, as far as the mock's sign-ins need it. */
interface MockAccount {
  id: string;
  appId: string;
  name: string;
  authKind: string;
  kindLabel: string;
  status: ConnectionStatus;
  signIn: SignInSetting;
  sandbox: boolean;
}

/**
 * Accounts of the team's apps with the service's sign-in rules: a person's own sign-in is theirs alone, on each account
 * they may connect, a sandbox among them. The mock's sign-in returns at once through the console's callback, since
 * there is no system to send the person to.
 */
export function createConnectionsMock(deps: { me: string }): ConnectionsApi {
  const at = new Date(Date.now() - 86_400_000 * 12).toISOString();
  const rows: MockAccount[] = [
    { id: 'conn_crm', appId: 'conn_crm', name: 'Salesforce', authKind: 'oauth2_auth_code', kindLabel: 'OAuth 2.0 sign-in', status: 'healthy', signIn: 'person_or_team', sandbox: false },
    { id: 'conn_crm_sandbox', appId: 'conn_crm', name: 'Salesforce sandbox', authKind: 'oauth2_auth_code', kindLabel: 'OAuth 2.0 sign-in', status: 'healthy', signIn: 'person_or_team', sandbox: true },
    { id: 'conn_desk', appId: 'conn_desk', name: 'Freshdesk', authKind: 'api_key', kindLabel: 'API key', status: 'healthy', signIn: 'person', sandbox: false },
    { id: 'conn_cases', appId: 'conn_cases', name: 'Case desk', authKind: 'basic', kindLabel: 'Username and password', status: 'healthy', signIn: 'person', sandbox: false },
    { id: 'conn_itsm', appId: 'conn_itsm', name: 'ServiceNow', authKind: 'oauth2_client_credentials', kindLabel: 'OAuth 2.0 client credentials', status: 'healthy', signIn: 'team', sandbox: false },
  ];
  const mine: MyConnection[] = [];
  // One person's password the system refused, so My accounts shows the refused state.
  const refusedRow = (): MyConnection => ({ ...own(find('conn_cases')), account: 'j.richardson', refused: true, refusedAt: at, refusedReason: 'cases.example.com answered 401.' });
  const find = (id: string) => rows.find((r) => r.id === id) ?? notFound(`Account ${id}`);
  const under = (appId: string, id: string) => {
    const row = find(id);
    return row.appId === appId ? row : notFound(`Account ${id}`);
  };
  const own = (row: MockAccount): MyConnection => {
    const kind = KINDS.find((k) => k.id === row.authKind);
    return { connectionId: row.id, appId: row.appId, app: row.name, connection: row.name, connectionStatus: row.status, sandbox: row.sandbox, method: kind?.label ?? row.kindLabel, authKind: row.authKind, personFields: kind?.personFields ?? [], connected: true, docsUrl: null, scopes: [], since: new Date().toISOString() };
  };
  const signIn = (row: MockAccount) => ({
    authorizeUrl: `/connections/callback?code=mock&state=${encodeURIComponent(row.id)}`,
    redirectUri: '/connections/callback',
    connectionId: row.id,
    appId: row.appId,
    expiresAt: new Date(Date.now() + 600_000).toISOString(),
  });
  return {
    kinds: () => respond(() => KINDS),
    startSignIn: (a) => respond(() => signIn(under(a.appId, a.accountId))),
    // The mock's state is the account's id, as its sign-in address carries it.
    finishSignIn: (i) =>
      respond(() => {
        const row = find(i.state);
        if (i.error) throw new ApiError(`${row.name} access was not given. Connect again to retry.`, 422, undefined, 'sign_in_refused', { who: 'person', providerCode: i.error, appId: row.appId, app: row.name });
        if (!mine.some((m) => m.connectionId === row.id)) {
          mine.push({ ...own(row), account: `${deps.me.toLowerCase().replace(/\s+/g, '.')}@example.com`, scopes: ['api'] });
        }
        return { appId: row.appId, accountId: row.id, check: false, account: { id: row.id, name: row.name } };
      }),
    openConnectLink: (link) => respond(() => signIn(rows.find((r) => r.id === link.split(':')[0]) ?? rows[0])),
    mine: (every) =>
      respond(() => {
        if (!mine.some((m) => m.connectionId === 'conn_cases')) mine.push(refusedRow());
        if (!every) return [...mine];
        const open = rows.filter((r) => r.signIn !== 'team' && KINDS.find((k) => k.id === r.authKind)?.perPerson);
        return open.map((r) => mine.find((m) => m.connectionId === r.id) ?? { ...own(r), connected: false, since: null });
      }),
    giveOwn: (id, i) =>
      respond(() => {
        const row = find(id);
        const kind = KINDS.find((k) => k.id === row.authKind);
        if (row.signIn === 'team' || !kind?.personFields?.length) throw new ApiError(`${row.name} signs in with the team's account.`, 400);
        const missing = kind.personFields.filter((f) => !i.credentials[f]?.trim());
        if (missing.length) throw new ApiError(`${kind.label} needs your ${missing.join(', ')}.`, 400);
        const at = mine.findIndex((m) => m.connectionId === id);
        const made: MyConnection = { ...own(row), account: i.credentials.username ?? null, refused: false };
        if (at >= 0) mine.splice(at, 1, made);
        else mine.push(made);
        return made;
      }),
    disconnect: (id) =>
      respond(() => {
        const at = mine.findIndex((m) => m.connectionId === id);
        if (at < 0) notFound(`Your sign-in to ${id}`);
        mine.splice(at, 1);
      }),
    startCredentialCheck: (a) =>
      respond(() => ({ ...signIn(rows.find((r) => r.id === a.accountId) ?? rows[0]), connectionId: a.accountId, appId: a.appId })),
  };
}
