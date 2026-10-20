import type { AccountProfile, AccountSession, MfaDevice, SessionFilters } from '@/lib/types/account';
import type { ListParams, ListResult } from '@/lib/types/query';

/**
 * The signed-in person's own account. Who that is comes from the session token, never from a parameter. Checking a
 * password or code is the AuthProvider's (lib/auth); this API changes the account once the page has checked.
 */
export interface AccountApi {
  profile(): Promise<AccountProfile>;
  updateProfile(input: { name: string }): Promise<AccountProfile>;
  /** Password accounts only (403 for SSO). The page re-authenticates with the current password first. */
  changePassword(input: { password: string }): Promise<void>;
  mfa: {
    list(): Promise<MfaDevice[]>;
    /** Replaces every recovery code; the new ones are returned once. */
    regenerateCodes(): Promise<{ codes: string[]; devices: MfaDevice[] }>;
    /** 409 when the workspace requires MFA and this is the last authenticator. */
    remove(id: string): Promise<MfaDevice[]>;
  };
  sessions: {
    list(params: ListParams<SessionFilters>): Promise<ListResult<AccountSession>>;
    /** 400 for the current session: sign out instead. */
    revoke(id: string): Promise<void>;
    /** Signs out every session except this one. */
    revokeOthers(): Promise<{ revoked: number }>;
  };
}
