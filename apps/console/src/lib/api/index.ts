import type { OpsApi } from './contract';
import { createHttpApi } from './http';
import { createMockApi } from './mock';

const baseUrl = process.env.NEXT_PUBLIC_OPS_API_URL;

/** Mock until a backend URL is configured; nothing outside this file knows which is in use. */
export const api: OpsApi = baseUrl ? createHttpApi(baseUrl) : createMockApi();

export { ApiError, type Lookups, type OpsApi } from './contract';
export { currentTeamId, DEFAULT_TEAM_ID, setCurrentTeamId, teamStore } from './team-context';
