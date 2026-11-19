import type { MemberRole } from '@/lib/types/settings';

/** The team roles as people read them; `approver` is stored and sent, "Reviewer" is shown (roles-and-permissions Q1). */
export const MEMBER_ROLES: { value: MemberRole; label: string; description: string }[] = [
  { value: 'admin', label: 'Admin', description: 'Manages members, API keys and the audit log for the team' },
  { value: 'builder', label: 'Builder', description: 'Edits agents, workflows, tools and knowledge, and requests publishes' },
  { value: 'approver', label: 'Reviewer', description: 'Decides reviews and drafted actions' },
  { value: 'viewer', label: 'Viewer', description: 'Reads everything in the team, changes nothing' },
  { value: 'chat_user', label: 'Chat user', description: 'Chats with the team’s agents and edits their own memory, nothing else' },
];

export const roleLabel = (r: MemberRole) => MEMBER_ROLES.find((x) => x.value === r)?.label ?? r;
