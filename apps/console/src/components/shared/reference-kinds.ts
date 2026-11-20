import { BookOpen, Bot, Sparkles, Workflow, Wrench, type LucideIcon } from 'lucide-react';

import type { RefKind } from '@/lib/types/references';

/** The icon each kind of reference is drawn with, in every editor and picker. */
export const KIND_ICON: Record<RefKind, LucideIcon> = { tool: Wrench, knowledge: BookOpen, skill: Sparkles, agent: Bot, workflow: Workflow };
