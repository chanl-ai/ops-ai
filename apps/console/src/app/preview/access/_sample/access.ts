// Sample data for the c-150 mock pages: the six roles and their grids as platform-service returned them on the shared
// stack (2026-10-19), so the mock draws real areas, actions and scopes. Mock only; the build reads the routes.
import data from './roles.json';

export type Scope = 'own' | 'all';
export interface SampleRole {
  id: string;
  name: string;
  builtin: boolean;
  description: string;
  permissionCount: number;
  assignmentCount: number;
  permissions: { area: string; action: string; scope: Scope }[];
}

export const ROLES = data.roles as SampleRole[];
export const roleOf = (id: string) => ROLES.find((r) => r.id === id);

/** The areas and actions every grid shows, in a fixed reading order. */
export const AREAS = [...new Set(ROLES.flatMap((r) => r.permissions.map((p) => p.area)))].sort();
const ORDER = ['view', 'run', 'create', 'edit', 'publish', 'decide', 'delete', 'manage'];
export const ACTIONS = [...new Set(ROLES.flatMap((r) => r.permissions.map((p) => p.action)))].sort((a, b) => (ORDER.indexOf(a) + 99) % 99 - (ORDER.indexOf(b) + 99) % 99 || a.localeCompare(b));

export const AREA_LABEL: Record<string, string> = { secrets_egress: 'Secrets and egress' };
export const label = (s: string) => AREA_LABEL[s] ?? s.charAt(0).toUpperCase() + s.slice(1);

/** A person in the mock: Ravi, a viewer of Operations, whose grants are the Viewer role's. */
export const PERSON = { id: 'usr_viewer', name: 'Ravi Menon', email: 'r.menon@northfieldbank.com', team: 'Operations', roles: ['viewer'] };
export const grantsOf = (roleIds: string[]) =>
  roleIds.flatMap((id) => (roleOf(id)?.permissions ?? []).map((p) => ({ ...p, role: roleOf(id)!.name })));
