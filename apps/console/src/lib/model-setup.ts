/**
 * Whether the overview asks the person to set up the workspace's model: only an account admin (the one who can add a
 * key) of a workspace with no model provider key, and only once the keys have loaded, so it never flashes.
 */
export function needsModelSetup({ admin, keys }: { admin: boolean; keys: readonly { name: string }[] | undefined }): boolean {
  return admin && keys !== undefined && keys.length === 0;
}
