/** An operation whose headers, path or query read a secret as `{{NAME}}`; `staged` when only an unpublished edit does. */
export interface SecretUser {
  moduleId: string;
  moduleName: string;
  operation: string;
  staged: boolean;
}

/** A stored credential, as tools-service lists it: never its value. Headers name it as `{{NAME}}`. */
export interface SecretMeta {
  name: string;
  version: number;
  /** The value's last four characters, so a person can tell which value is held; none for a short value. */
  ends?: string | null;
  createdBy: string;
  createdAt: string;
  rotatedAt?: string | null;
  lastUsedAt?: string | null;
  /** The operations that read it; a secret any operation names cannot be deleted. */
  usedBy: SecretUser[];
  /** The team whose tool modules and connections read it; another team that needs it holds its own. */
  teamId: string;
  /** The auth config this is the client secret of: changed on that config, never here. */
  authConfig?: { id: string; name: string } | null;
  /** True when this list may not change it (an auth config's client secret). */
  readOnly?: boolean;
  /** What a person calls it ("GitHub · Operations client secret") when an auth config holds it; none for a team's own. */
  label?: string | null;
}
