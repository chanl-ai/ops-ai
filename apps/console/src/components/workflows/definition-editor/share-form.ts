import type { HostedFormMode } from '@/lib/types/forms';

/** Who may send a hosted form. A signed link needs the embed app's origin; without it only members-only is offered. */
export const SHARE_MODES: { mode: HostedFormMode; title: string; hint: string }[] = [
  { mode: 'link', title: 'Anyone with the link', hint: 'A signed link that stops working when it expires or is rotated' },
  { mode: 'members', title: 'Team members, signed in', hint: 'Opens in Ops AI after sign-in; the run starts as that person' },
];

export function shareModes(publicFormPage: boolean) {
  return publicFormPage ? SHARE_MODES : SHARE_MODES.filter((m) => m.mode === 'members');
}

export function defaultShareMode(publicFormPage: boolean): HostedFormMode {
  return publicFormPage ? 'link' : 'members';
}
