/** A stored credential, as tools-service lists it: never its value. Headers name it as `{{NAME}}`. */
export interface SecretMeta {
  name: string;
  version: number;
  createdBy: string;
  createdAt: string;
  rotatedAt?: string | null;
  lastUsedAt?: string | null;
}
