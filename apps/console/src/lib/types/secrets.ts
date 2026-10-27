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
  createdBy: string;
  createdAt: string;
  rotatedAt?: string | null;
  lastUsedAt?: string | null;
  /** The operations that read it (c-093); a secret any operation names cannot be deleted. */
  usedBy: SecretUser[];
  /** The team whose tool modules and connections read it (c-509); another team that needs it holds its own. */
  teamId: string;
}
