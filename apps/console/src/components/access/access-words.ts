/** Areas and actions of the roles grid in a person's words, and the order the grid reads in. */
const AREA_WORDS: Record<string, string> = { secrets_egress: 'Secrets and egress' };
export const areaLabel = (area: string) => AREA_WORDS[area] ?? area.charAt(0).toUpperCase() + area.slice(1);
export const actionLabel = (action: string) => action.charAt(0).toUpperCase() + action.slice(1);
export const ACTION_ORDER = ['view', 'run', 'create', 'edit', 'publish', 'decide', 'delete', 'manage'];
export const byActionOrder = (a: string, b: string) => ((ACTION_ORDER.indexOf(a) + 99) % 99) - ((ACTION_ORDER.indexOf(b) + 99) % 99) || a.localeCompare(b);
