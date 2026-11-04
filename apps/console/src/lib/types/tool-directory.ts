import type { ListResult } from './query';

/** What a tool is: an app's tool, a team's own (custom) tool, a workflow called as a tool, or another agent. */
export type ToolKind = 'app' | 'custom' | 'workflow' | 'agent';

/**
 * Whether a tool can be called now: ready, waiting on its review, its app has no working account, or (on an app each
 * person signs in to) the caller has not connected their own.
 */
export type ToolStatus = 'ready' | 'needs_approval' | 'app_not_connected' | 'needs_your_sign_in';

export interface ToolRef {
  id: string;
  name: string;
}

/** One tool as GET /v1/tools lists it, already joined: its app, kind, status and who uses it. */
export interface ToolRow {
  /** The name a grant names (`person_get_record`), or `workflow:<id>` and `agent:<id>`. */
  id: string;
  name: string;
  /** A plugin tool's title (`Read a record`); null for any other tool. */
  title?: string | null;
  app: ToolRef | null;
  kind: ToolKind;
  access: 'read' | 'write' | 'workflow';
  status: ToolStatus;
  usedBy: { agents: ToolRef[]; workflows: ToolRef[] };
  /** The tool set an app's or custom tool belongs to; its page is /tools/{moduleId}/operations/{name}. */
  moduleId?: string | null;
}

export type ToolRowFilters = { app?: string[]; kind?: string[]; status?: string[] };

/** GET /v1/tools: a page of rows with its facets, and the name of each app the app facet counts, by its id. */
export interface ToolDirectory extends ListResult<ToolRow> {
  appNames: Record<string, string>;
}
