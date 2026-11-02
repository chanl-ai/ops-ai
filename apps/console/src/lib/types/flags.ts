/**
 * The install's feature flags (c-611), as platform-service's GET /v1/me lists them. The names come from the generated
 * SDK, whose schema carries the registry in ops_service_kit/flags.py, so the console keeps no list of its own.
 */
import type { OpsAI } from '@chanl-ai/ops-ai';

type MeAnswer = Awaited<ReturnType<OpsAI['raw']['platform']['me_me']>>;

export type FeatureFlag = MeAnswer['flags'][number];
export type FlagName = FeatureFlag['name'];
