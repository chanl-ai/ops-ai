import { BookOpen, Bot, Sparkles, Workflow, Wrench, type LucideIcon } from 'lucide-react';

import type { RefKind } from '@/lib/types/references';

/** The icon each kind of reference is drawn with, in every editor and picker. */
export const KIND_ICON: Record<RefKind, LucideIcon> = { tool: Wrench, knowledge: BookOpen, skill: Sparkles, agent: Bot, workflow: Workflow };

/** The heading each kind is listed under. */
export const KIND_LABEL: Record<RefKind, string> = { tool: 'Tools', knowledge: 'Knowledge', skill: 'Skills', agent: 'Agents', workflow: 'Workflows' };
