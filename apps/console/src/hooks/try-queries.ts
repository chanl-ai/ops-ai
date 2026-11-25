'use client';

/**
 * Trying one skill path or one workflow step, on the generated SDK: agents-service lists the paths with each tool
 * step's values and sample (`GET /v1/try-targets`), and tools-service tries one tool (`POST /v1/tool-modules/tries`),
 * where a write comes back as a plan and is sent only when its plan id comes back with the same values.
 */
import { useMutation } from '@tanstack/react-query';

import { sdk } from '@/lib/api/ops-sdk';
import type { OpsAI } from '@chanl-ai/ops-ai';

import { useTeamQuery } from './team-query';

type Agents = OpsAI['raw']['agents'];
type Tools = OpsAI['raw']['tools'];

export type TryTargets = Awaited<ReturnType<Agents['agents_try_targets']>>;
export type TryPath = TryTargets['paths'][number];
export type TryStep = TryPath['steps'][number];
export type TryResult = Awaited<ReturnType<Tools['tool_modules_try_one_tool']>>;
export type TryInput = NonNullable<Parameters<Tools['tool_modules_try_one_tool']>[0]>['body'];

export type TryTarget = { kind: 'skill'; skillId: string } | { kind: 'workflow_step'; workflowId: string; step: string };

const query = (t: TryTarget) => (t.kind === 'skill' ? { skill: t.skillId } : { workflow: t.workflowId, step: t.step });

/** The paths a builder can try; read fresh each time the panel opens, so a sample is the newest run's answer. */
export const useTryTargets = (target: TryTarget, enabled = true) =>
  useTeamQuery({
    queryKey: ['try-targets', target],
    queryFn: () => sdk((ops) => ops.raw.agents.agents_try_targets({ query: query(target) })),
    enabled,
    staleTime: 0,
  });

/** One tool tried: a read runs, a write is planned; with `planId` the planned write is sent. Nothing is cached. */
export const useTryTool = () => useMutation({ mutationFn: (body: TryInput) => sdk((ops) => ops.raw.tools.tool_modules_try_one_tool({ body })) });
