import type { AuthMethod, SessionUser } from '@/lib/auth/provider';

/** Northfield people the mock can sign in. Every password is `northfield-demo`; every TOTP code is `123456`. */
export interface MockUser extends SessionUser {
  password: string | null;
  mfaEnrolled: boolean;
  method: AuthMethod;
}

export const DEMO_PASSWORD = 'northfield-demo';
export const DEMO_TOTP = '123456';

export const USERS: MockUser[] = [
  { id: 'usr_james', name: 'James Richardson', email: 'j.richardson@northfieldbank.com', teamIds: ['team_platform'], role: 'admin', password: DEMO_PASSWORD, mfaEnrolled: true, method: 'password' },
  { id: 'usr_maya', name: 'Maya Okafor', email: 'maya.okafor@northfieldbank.com', teamIds: ['team_cards'], role: 'member', password: DEMO_PASSWORD, mfaEnrolled: true, method: 'password' },
  { id: 'usr_new', name: 'New Analyst', email: 'new.analyst@northfieldbank.com', teamIds: ['team_lending'], role: 'member', password: DEMO_PASSWORD, mfaEnrolled: false, method: 'password' },
];

/** The console opens signed in as this person unless ?mock=signed-out. */
export const DEFAULT_USER_ID = 'usr_james';
/** Hard end of any session, however active; the policy's session length is the idle limit inside it. */
export const ABSOLUTE_SESSION_HOURS = 24;
